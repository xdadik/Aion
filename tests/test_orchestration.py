"""Tests for the Orchestration Engine: subagent spawning, workflow creation, workflow execution."""

import asyncio
import contextlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from aion_core.agent.core import AgentConfig, AionHand
from aion_core.orchestration.engine import (
    NodeStatus,
    NodeType,
    OrchestrationEngine,
    SubAgentResult,
    Workflow,
    WorkflowNode,
    WorkflowStatus,
)


def _make_config(tmpdir: str, **overrides) -> AgentConfig:
    base = Path(tmpdir) / ".aion"
    defaults = {
        "home_dir": base,
        "data_dir": base / "data",
        "memory_dir": base / "memory",
        "skills_dir": base / "skills",
        "tools_dir": base / "tools",
        "logs_dir": base / "logs",
        "config_file": base / "config.json",
        "messaging_enabled": False,
        "cron_enabled": False,
        "workflow_enabled": False,
        "pipeline_enabled": False,
        "knowledge_enabled": False,
        "benchmark_enabled": False,
        "dynamic_enabled": False,
        "routing_enabled": False,
        "mcp_enabled": False,
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


def _mock_provider():
    provider = MagicMock()
    provider.chat = AsyncMock(return_value=MagicMock(
        content="ok", tool_calls=None, usage=MagicMock(),
        model="gpt-4o", raw_response={}, finish_reason="stop",
    ))
    return provider


class TestWorkflowNode(unittest.TestCase):
    """Test WorkflowNode creation and serialization."""

    def test_create_agent_node(self):
        node = WorkflowNode(
            node_id="step_1", name="Research",
            node_type=NodeType.AGENT,
            config={"task": "Research {{topic}}"},
        )
        self.assertEqual(node.id, "step_1")
        self.assertEqual(node.name, "Research")
        self.assertEqual(node.node_type, NodeType.AGENT)
        self.assertEqual(node.status, NodeStatus.PENDING)
        self.assertIsNone(node.started_at)

    def test_create_tool_node(self):
        node = WorkflowNode(
            node_id="tool_1", name="Run Code",
            node_type=NodeType.TOOL,
            config={"tool": "code_execute", "args": {"code": "1+1"}},
            timeout=60,
        )
        self.assertEqual(node.node_type, NodeType.TOOL)
        self.assertEqual(node.timeout, 60)

    def test_create_condition_node(self):
        node = WorkflowNode(
            node_id="check", name="Check Result",
            node_type=NodeType.CONDITION,
            config={"expression": "ctx.result == 'ok'"},
        )
        self.assertEqual(node.node_type, NodeType.CONDITION)

    def test_create_merge_node(self):
        node = WorkflowNode(
            node_id="merge", name="Merge Results",
            node_type=NodeType.MERGE,
            dependencies=["step_1", "step_2"],
        )
        self.assertEqual(node.dependencies, ["step_1", "step_2"])

    def test_node_to_dict(self):
        node = WorkflowNode(
            node_id="n1", name="Node 1",
            node_type=NodeType.AGENT,
            config={"task": "test"},
        )
        d = node.to_dict()
        self.assertEqual(d["id"], "n1")
        self.assertEqual(d["type"], "agent")
        self.assertEqual(d["status"], "pending")

    def test_node_from_dict(self):
        data = {
            "id": "n2",
            "name": "Step 2",
            "type": "tool",
            "config": {"tool": "calculator"},
            "dependencies": ["n1"],
            "timeout": 30,
        }
        node = WorkflowNode.from_dict(data)
        self.assertEqual(node.id, "n2")
        self.assertEqual(node.node_type, NodeType.TOOL)
        self.assertEqual(node.dependencies, ["n1"])
        self.assertEqual(node.timeout, 30.0)

    def test_elapsed_before_start(self):
        node = WorkflowNode(node_id="n1", name="N", node_type=NodeType.AGENT)
        self.assertEqual(node.elapsed, 0.0)


class TestSubAgentResult(unittest.TestCase):
    """Test SubAgentResult data model."""

    def test_successful_result(self):
        result = SubAgentResult(
            task="Test task",
            content="Done",
            tools_used=["web_search"],
            elapsed=1.5,
            success=True,
        )
        self.assertTrue(result.success)
        self.assertIsNone(result.error)

    def test_failed_result(self):
        result = SubAgentResult(
            task="Test task",
            elapsed=0.5,
            success=False,
            error="Provider unavailable",
        )
        self.assertFalse(result.success)
        self.assertEqual(result.error, "Provider unavailable")

    def test_to_dict(self):
        result = SubAgentResult(
            task="Task", content="Result", elapsed=2.0,
        )
        d = result.to_dict()
        self.assertEqual(d["task"], "Task")
        self.assertEqual(d["content"], "Result")
        self.assertTrue(d["success"])
        self.assertIn("elapsed", d)


class TestWorkflow(unittest.IsolatedAsyncioTestCase):
    """Test Workflow DAG execution."""

    def test_create_workflow(self):
        n1 = WorkflowNode(node_id="n1", name="Step 1", node_type=NodeType.AGENT)
        n2 = WorkflowNode(node_id="n2", name="Step 2", node_type=NodeType.AGENT,
                           dependencies=["n1"])
        wf = Workflow(name="test_wf", nodes=[n1, n2])
        self.assertEqual(len(wf.nodes), 2)
        self.assertEqual(wf.status, WorkflowStatus.PENDING)

    def test_get_root_nodes(self):
        n1 = WorkflowNode(node_id="n1", name="Root", node_type=NodeType.AGENT)
        n2 = WorkflowNode(node_id="n2", name="Child", node_type=NodeType.AGENT,
                           dependencies=["n1"])
        wf = Workflow(name="test", nodes=[n1, n2])
        roots = wf.get_root_nodes()
        self.assertEqual(len(roots), 1)
        self.assertEqual(roots[0].id, "n1")

    def test_get_downstream(self):
        n1 = WorkflowNode(node_id="n1", name="Parent", node_type=NodeType.AGENT)
        n2 = WorkflowNode(node_id="n2", name="Child", node_type=NodeType.AGENT,
                           dependencies=["n1"])
        wf = Workflow(name="test", nodes=[n1, n2])
        downstream = wf.get_downstream("n1")
        self.assertEqual(len(downstream), 1)
        self.assertEqual(downstream[0].id, "n2")

    def test_duplicate_node_raises(self):
        n1 = WorkflowNode(node_id="n1", name="Step 1", node_type=NodeType.AGENT)
        wf = Workflow(name="test", nodes=[n1])
        with self.assertRaises(ValueError):
            wf.add_node(n1)

    def test_remove_node(self):
        n1 = WorkflowNode(node_id="n1", name="Step 1", node_type=NodeType.AGENT)
        n2 = WorkflowNode(node_id="n2", name="Step 2", node_type=NodeType.AGENT,
                           dependencies=["n1"])
        wf = Workflow(name="test", nodes=[n1, n2])
        wf.remove_node("n1")
        self.assertNotIn("n1", wf.nodes)
        self.assertNotIn("n1", n2.dependencies)

    def test_workflow_from_dict(self):
        definition = {
            "name": "pipeline",
            "timeout": 300,
            "nodes": [
                {"id": "step_1", "name": "Research", "type": "agent",
                 "config": {"task": "Research {{topic}}"}, "dependencies": []},
                {"id": "step_2", "name": "Summarize", "type": "agent",
                 "config": {"task": "Summarize"}, "dependencies": ["step_1"]},
            ],
        }
        wf = Workflow.from_dict(definition)
        self.assertEqual(wf.name, "pipeline")
        self.assertEqual(len(wf.nodes), 2)
        self.assertEqual(wf.timeout, 300)

    def test_workflow_to_dict(self):
        n1 = WorkflowNode(node_id="n1", name="Step 1", node_type=NodeType.AGENT)
        wf = Workflow(name="test_wf", nodes=[n1])
        d = wf.to_dict()
        self.assertEqual(d["name"], "test_wf")
        self.assertIn("n1", d["nodes"])

    def test_cycle_detection(self):
        n1 = WorkflowNode(node_id="n1", name="A", node_type=NodeType.AGENT,
                           dependencies=["n2"])
        n2 = WorkflowNode(node_id="n2", name="B", node_type=NodeType.AGENT,
                           dependencies=["n1"])
        wf = Workflow(name="cyclic", nodes=[n1, n2])
        with self.assertRaises(ValueError) as ctx:
            wf._topological_layers()
        self.assertIn("cycle", str(ctx.exception).lower())


class TestOrchestrationEngine(unittest.IsolatedAsyncioTestCase):
    """Test OrchestrationEngine lifecycle and management."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.agent = MagicMock()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_initialize_and_shutdown(self):
        engine = OrchestrationEngine(
            agent=self.agent, max_subagents=3, timeout=60.0,
        )
        await engine.initialize()
        self.assertTrue(engine._initialized)
        status = engine.get_status()
        self.assertTrue(status["initialized"])
        await engine.shutdown()
        self.assertFalse(engine._initialized)

    async def test_spawn_subagent_success(self):
        self.agent.chat = AsyncMock(return_value={
            "content": "Task completed",
            "tools_used": [],
            "metadata": {},
        })
        engine = OrchestrationEngine(agent=self.agent, max_subagents=5)
        await engine.initialize()
        result = await engine.spawn_subagent(
            task="Analyze data",
            tools=["web_search"],
            timeout=10,
        )
        self.assertTrue(result["success"])
        self.assertEqual(result["content"], "Task completed")
        await engine.shutdown()

    async def test_spawn_without_initialize_raises(self):
        engine = OrchestrationEngine(agent=self.agent)
        with self.assertRaises(RuntimeError):
            await engine.spawn_subagent(task="test")

    async def test_max_subagents_limit(self):
        self.agent.chat = AsyncMock(return_value={
            "content": "working", "tools_used": [],
            "metadata": {},
        })
        engine = OrchestrationEngine(agent=self.agent, max_subagents=1, timeout=60)
        await engine.initialize()

        # Spawn one task that takes a while
        async def slow_chat(msg):
            await asyncio.sleep(0.5)
            return {"content": "done", "tools_used": [], "metadata": {}}

        self.agent.chat = slow_chat

        # Start a blocking task
        blocker = asyncio.create_task(
            engine.spawn_subagent(task="blocker", timeout=10)
        )
        await asyncio.sleep(0.05)

        # Try to spawn another - should fail due to max_subagents limit
        with self.assertRaises(RuntimeError) as ctx:
            await engine.spawn_subagent(task="should fail")
        self.assertIn("Max sub-agents", str(ctx.exception))

        blocker.cancel()
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await blocker
        await engine.shutdown()

    async def test_cancel_subagent(self):
        self.agent.chat = AsyncMock(return_value={
            "content": "ok", "tools_used": [], "metadata": {},
        })
        engine = OrchestrationEngine(agent=self.agent, timeout=60)
        await engine.initialize()

        # Spawn and immediately cancel
        task = asyncio.create_task(
            engine.spawn_subagent(task="slow task", timeout=10)
        )
        await asyncio.sleep(0.05)
        active = engine.list_active_subagents()
        if active:
            engine.cancel_subagent(active[0]["id"])
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await task
        await engine.shutdown()

    async def test_create_and_register_workflow(self):
        engine = OrchestrationEngine(agent=self.agent)
        await engine.initialize()

        definition = {
            "name": "test_workflow",
            "nodes": [
                {"id": "s1", "name": "Step 1", "type": "agent",
                 "config": {"task": "Do something"}, "dependencies": []},
            ],
        }
        wf = engine.create_workflow(definition)
        self.assertIsNotNone(wf)
        self.assertIn("test_workflow", engine._workflows)

        listed = engine.list_workflows()
        self.assertEqual(len(listed), 1)
        self.assertEqual(listed[0]["name"], "test_workflow")
        await engine.shutdown()

    async def test_remove_workflow(self):
        engine = OrchestrationEngine(agent=self.agent)
        await engine.initialize()
        definition = {
            "name": "temp_wf",
            "nodes": [{"id": "s1", "name": "S1", "type": "agent",
                       "config": {}, "dependencies": []}],
        }
        engine.create_workflow(definition)
        self.assertTrue(engine.remove_workflow("temp_wf"))
        self.assertFalse(engine.remove_workflow("temp_wf"))
        await engine.shutdown()

    async def test_get_status(self):
        engine = OrchestrationEngine(agent=self.agent, max_subagents=3, timeout=120)
        await engine.initialize()
        status = engine.get_status()
        self.assertIn("initialized", status)
        self.assertIn("max_subagents", status)
        self.assertIn("stats", status)
        self.assertEqual(status["max_subagents"], 3)
        await engine.shutdown()


class TestSubagentSpawning(unittest.IsolatedAsyncioTestCase):
    """Test subagent spawning through the AionHand agent."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    async def test_spawn_raises_when_orchestrator_not_initialized(self):
        config = _make_config(self.tmpdir, workflow_enabled=False)
        agent = AionHand(config=config)
        with patch("aion_core.providers.factory.ProviderFactory.create", return_value=_mock_provider()):
            await agent.start()
        with self.assertRaises(RuntimeError) as ctx:
            await agent.spawn_subagent(task="Do something")
        self.assertIn("Orchestration engine", str(ctx.exception))
        await agent.shutdown()

    async def test_spawn_delegates_to_orchestrator(self):
        config = _make_config(self.tmpdir, workflow_enabled=True)
        mock_orchestrator = AsyncMock()
        mock_orchestrator.initialize = AsyncMock()
        mock_orchestrator.shutdown = AsyncMock()
        mock_orchestrator.spawn_subagent = AsyncMock(return_value={
            "task": "Analyze logs", "status": "completed", "result": "No errors",
        })
        mock_loop = MagicMock()
        mock_loop.initialize = AsyncMock()
        mock_loop.shutdown = AsyncMock()
        mock_loop.run = AsyncMock(return_value={
            "content": "ok", "tools_used": [], "metadata": {},
        })

        with patch("aion_core.providers.factory.ProviderFactory.create", return_value=_mock_provider()), \
             patch("aion_core.agent.loop.AgentLoop", return_value=mock_loop), \
             patch("aion_core.orchestration.engine.OrchestrationEngine", return_value=mock_orchestrator):
            agent = AionHand(config=config)
            await agent.start()
            result = await agent.spawn_subagent(
                task="Analyze logs", tools=["shell_command"], timeout=60,
            )
            self.assertEqual(result["status"], "completed")
            mock_orchestrator.spawn_subagent.assert_called_once()
            await agent.shutdown()


if __name__ == "__main__":
    unittest.main()
