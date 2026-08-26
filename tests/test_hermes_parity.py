"""Tests for Hermes-parity features: session store, checkpoints,
delegate_task / session_search / cronjob / rollback tools, NL schedules,
tool-RPC code execution and provider fallback chain."""

import asyncio
import os
import tempfile
import time
import unittest
from pathlib import Path

from aion_core.checkpoints import CheckpointManager
from aion_core.state import SessionStore
from aion_core.tools.registry import (
    ToolRegistry,
    _parse_nl_schedule,
)


class TestSessionStore(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.tmp.close()
        os.unlink(self.tmp.name)
        self.store = SessionStore(self.tmp.name)
        self.store.initialize()

    def tearDown(self):
        self.store.close()
        if os.path.exists(self.tmp.name):
            os.unlink(self.tmp.name)

    def test_create_and_list_sessions(self):
        sid = self.store.create_session(platform="cli", title="test session")
        sessions = self.store.list_sessions()
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0]["id"], sid)
        self.assertEqual(sessions[0]["platform"], "cli")

    def test_record_and_get_messages(self):
        sid = self.store.create_session()
        self.store.record_message(sid, "user", "hello world")
        self.store.record_message(
            sid, "assistant", "hi!", tools_used=["calculator"]
        )
        msgs = self.store.get_messages(sid)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0]["role"], "user")
        self.assertEqual(msgs[1]["role"], "assistant")

    def test_fts_search_across_sessions(self):
        s1 = self.store.create_session(platform="cli")
        s2 = self.store.create_session(platform="telegram")
        self.store.record_message(s1, "user", "Tashkent metro line discussion")
        self.store.record_message(s2, "user", "totally different topic")
        hits = self.store.search("metro")
        self.assertEqual(len(hits), 1)
        self.assertIn("metro", hits[0]["content"])

    def test_search_with_platform_filter(self):
        s1 = self.store.create_session(platform="cli")
        s2 = self.store.create_session(platform="telegram")
        self.store.record_message(s1, "user", "deploy the server")
        self.store.record_message(s2, "user", "deploy the server")
        cli_hits = self.store.search("deploy", platform="cli")
        self.assertEqual(len(cli_hits), 1)
        self.assertEqual(cli_hits[0]["platform"], "cli")

    def test_search_user_input_sanitized(self):
        sid = self.store.create_session()
        self.store.record_message(sid, "user", "normal content")
        # Quotes in the query must not crash the FTS matcher
        hits = self.store.search('weird "quote injection')
        self.assertIsInstance(hits, list)

    def test_stats(self):
        sid = self.store.create_session()
        self.store.record_message(sid, "user", "x")
        stats = self.store.stats()
        self.assertEqual(stats["sessions"], 1)
        self.assertEqual(stats["messages"], 1)


class TestCheckpointManager(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.mgr = CheckpointManager(Path(self.tmpdir) / "checkpoints")
        self.target = Path(self.tmpdir) / "target.txt"
        self.target.write_text("original content")

    def test_checkpoint_and_rollback(self):
        cid = self.mgr.create_checkpoint(
            files=[str(self.target)], reason="test write"
        )
        self.assertIsNotNone(cid)
        self.target.write_text("OVERWRITTEN")
        result = self.mgr.rollback(cid)
        self.assertTrue(result["success"])
        self.assertEqual(self.target.read_text(), "original content")

    def test_rollback_removes_new_files(self):
        new_file = Path(self.tmpdir) / "created-by-agent.txt"
        cid = self.mgr.create_checkpoint(
            files=[str(new_file)], reason="new file op"
        )
        new_file.write_text("created")
        result = self.mgr.rollback(cid)
        self.assertTrue(result["success"])
        self.assertFalse(new_file.exists())

    def test_list_checkpoints(self):
        self.mgr.create_checkpoint(files=[str(self.target)], reason="r1")
        self.mgr.create_checkpoint(files=[str(self.target)], reason="r2")
        listing = self.mgr.list_checkpoints()
        self.assertEqual(len(listing), 2)
        # newest first
        self.assertEqual(listing[0]["reason"], "r2")

    def test_pruning(self):
        mgr = CheckpointManager(Path(self.tmpdir) / "cp2")
        for i in range(12):
            mgr.create_checkpoint(
                files=[str(self.target)], reason=f"r{i}", keep_last=5
            )
        self.assertEqual(len(mgr.list_checkpoints(limit=100)), 5)


class TestNLScheduleParsing(unittest.TestCase):
    def test_interval_minutes(self):
        self.assertEqual(_parse_nl_schedule("30m"), "*/30 * * * *")

    def test_interval_hours(self):
        self.assertEqual(_parse_nl_schedule("2h"), "0 */2 * * *")

    def test_interval_seconds_too_small(self):
        self.assertIsNone(_parse_nl_schedule("30s"))

    def test_every_weekday(self):
        self.assertEqual(_parse_nl_schedule("every monday 9am"), "0 9 * * 1")
        self.assertEqual(_parse_nl_schedule("every sunday 18:30"), "30 18 * * 0")

    def test_every_day(self):
        self.assertEqual(_parse_nl_schedule("every day 9am"), "0 9 * * *")

    def test_pm_handling(self):
        self.assertEqual(_parse_nl_schedule("every friday 3pm"), "0 15 * * 5")

    def test_raw_cron_passthrough(self):
        self.assertEqual(_parse_nl_schedule("*/5 * * * *"), "*/5 * * * *")

    def test_garbage_returns_none(self):
        self.assertIsNone(_parse_nl_schedule("whenever I feel like it"))


class TestHermesParityTools(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.mkdtemp()
        # Standalone registry (config with temp dirs)
        from aion_core.agent.core import AgentConfig

        self.config = AgentConfig(
            home_dir=Path(self.tmpdir),
            data_dir=Path(self.tmpdir) / "data",
            tools_dir=Path(self.tmpdir) / "tools",
        )
        self.registry = ToolRegistry(self.config, approval_mode="auto")
        await self.registry.initialize()

    def test_session_search_tool_registered(self):
        self.assertIn("session_search", self.registry)

    def test_delegate_task_tool_registered(self):
        self.assertIn("delegate_task", self.registry)

    def test_cronjob_tool_registered(self):
        self.assertIn("cronjob", self.registry)

    def test_rollback_tool_registered(self):
        self.assertIn("rollback", self.registry)

    async def test_session_search_tool_live(self):
        # Record something via the default store the tool will find
        from aion_core.tools.registry import _get_session_store

        store = _get_session_store()
        sid = store.create_session(platform="test")
        store.record_message(sid, "user", "findme-unique-token-123")
        result = await self.registry.execute(
            "session_search", query="findme-unique-token-123", limit=3
        )
        self.assertTrue(result["success"])
        inner = result["result"]
        self.assertTrue(inner["success"])
        self.assertGreaterEqual(inner["count"], 1)

    async def test_rollback_tool_lists(self):
        result = await self.registry.execute("rollback", checkpoint_id="")
        self.assertTrue(result["success"])
        self.assertIn("checkpoints", result["result"])

    async def test_code_execute_with_rpc(self):
        # Set up an agent-like context exposing _tools
        class _FakeAgent:
            _tools = self.registry

        from aion_core.tools.registry import _TOOL_CONTEXT

        _TOOL_CONTEXT.agent = _FakeAgent()
        try:
            code = (
                "r = call_tool('calculator', expression='6*7')\n"
                "print('answer', r['result']['result'])"
            )
            result = await self.registry.execute(
                "code_execute",
                code=code,
                use_tools=True,
                language="python",
                timeout=20,
            )
            self.assertTrue(result["success"])
            inner = result["result"]
            self.assertTrue(inner["success"])
            self.assertIn("answer 42", inner["output"])
        finally:
            _TOOL_CONTEXT.agent = None

    async def test_file_write_creates_checkpoint(self):
        target = Path(self.tmpdir) / "cp-file.txt"
        target.write_text("before")
        result = await self.registry.execute(
            "file_write", path=str(target), content="after"
        )
        self.assertTrue(result["success"])
        self.assertIsNotNone(result["result"].get("checkpoint_id"))
        # and the rollback restores 'before'
        cid = result["result"]["checkpoint_id"]
        rb = await self.registry.execute("rollback", checkpoint_id=cid)
        self.assertTrue(rb["success"])
        self.assertEqual(target.read_text(), "before")

    async def test_cron_tool_create_list_delete_live(self):
        """End-to-end cronjob tool against a REAL CronScheduler.

        Regression: the handler previously called add_task(cron=...) without
        await and a non-existent list_jobs() — create always failed.
        """
        from aion_core.cron.scheduler import CronScheduler
        from aion_core.tools.registry import _TOOL_CONTEXT

        sched = CronScheduler()
        _TOOL_CONTEXT.cron_scheduler = sched
        try:
            created = await self.registry.execute(
                "cronjob",
                action="create",
                schedule="every monday 9am",
                task="send me the weekly report",
            )
            inner = created["result"]
            self.assertTrue(inner["success"], inner)
            self.assertEqual(inner["cron"], "0 9 * * 1")
            job_id = inner["job_id"]
            self.assertTrue(job_id)

            listed = await self.registry.execute("cronjob", action="list")
            inner = listed["result"]
            self.assertTrue(inner["success"], inner)
            self.assertEqual(inner["count"], 1)
            job = inner["jobs"][0]
            self.assertEqual(job["id"], job_id)
            self.assertEqual(job["task"], "send me the weekly report")
            self.assertEqual(job["schedule"], "0 9 * * 1")
            # next_run must be serialized as a string (JSON-safe for the LLM)
            self.assertIsInstance(job["next_run"], str)
            self.assertTrue(job["next_run"])

            deleted = await self.registry.execute(
                "cronjob", action="delete", job_id=job_id
            )
            self.assertTrue(deleted["result"]["success"])

            listed2 = await self.registry.execute("cronjob", action="list")
            self.assertEqual(listed2["result"]["count"], 0)
        finally:
            _TOOL_CONTEXT.cron_scheduler = None

    async def test_verify_output_scores_and_aggregates(self):
        """PipelineEngine.verify_output runs ONLY verification on an output.

        Regression: run_goal_loop previously called a non-existent
        PipelineEngine.verify() — silently caught, so the goal loop never
        judged anything and always burned max_iterations.
        """
        from aion_core.pipeline.engine import PipelineEngine

        class _FakeAgent:
            async def chat(self, message, **kwargs):
                return {"content": "ok"}

        engine = PipelineEngine(_FakeAgent(), enable_learning=False)
        verdict = await engine.verify_output(
            task="Write a fibonacci function",
            output="def fib(n):\n    return n if n < 2 else fib(n-1) + fib(n-2)\n",
        )
        self.assertIn("passed", verdict)
        self.assertIn("score", verdict)
        self.assertIn("total", verdict)
        self.assertGreaterEqual(verdict["total"], 1)
        self.assertGreaterEqual(verdict["score"], 0.0)
        self.assertLessEqual(verdict["score"], 1.0)
        self.assertIsInstance(verdict["issues"], list)

    async def test_verify_output_empty_result_is_pass(self):
        from aion_core.pipeline.engine import PipelineEngine

        class _FakeAgent:
            async def chat(self, message, **kwargs):
                return {"content": "ok"}

        engine = PipelineEngine(_FakeAgent(), enable_learning=False)
        # No verifiers applicable -> vacuous pass
        engine._verifier._verifiers = []
        verdict = await engine.verify_output(task="t", output="o")
        self.assertTrue(verdict["passed"])
        self.assertEqual(verdict["score"], 1.0)


class TestProviderChain(unittest.IsolatedAsyncioTestCase):
    def _make_provider(self, name, behavior):
        from aion_core.providers.factory import BaseProvider, ProviderResponse

        class _P(BaseProvider):
            PROVIDER_NAME = name
            BASE_URL = "http://localhost:1"

            def get_default_model(self):
                return "test"

            async def chat(self, messages, **kwargs):
                return behavior()

            async def chat_stream(self, messages, **kwargs):
                yield behavior()

            async def list_models(self):
                return ["test"]

        p = _P(api_key="k")
        return p

    async def test_failover_on_rate_limit(self):
        from aion_core.providers.factory import ProviderChain, ProviderResponse

        calls = {"n": 0}

        def failing():
            calls["n"] += 1
            raise RuntimeError("HTTP 429: rate limit exceeded")

        def working():
            return ProviderResponse(content="ok", model="m")
        chain = ProviderChain(
            primary=self._make_provider("primary", failing),
            fallbacks=[self._make_provider("backup", working)],
        )
        resp = await chain.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(resp.content, "ok")
        self.assertEqual(chain.failover_count, 1)

    async def test_non_transient_raises_immediately(self):
        from aion_core.providers.factory import ProviderChain

        def bad_request():
            raise RuntimeError("400: invalid model name")

        def working():
            return "should not be called"

        chain = ProviderChain(
            primary=self._make_provider("primary", bad_request),
            fallbacks=[self._make_provider("backup", working)],
        )
        with self.assertRaises(RuntimeError):
            await chain.chat([{"role": "user", "content": "hi"}])
        self.assertEqual(chain.failover_count, 0)

    async def test_all_fail_raises(self):
        from aion_core.providers.factory import ProviderChain

        def failing():
            raise RuntimeError("503 service unavailable")

        chain = ProviderChain(
            primary=self._make_provider("p1", failing),
            fallbacks=[self._make_provider("p2", failing)],
        )
        with self.assertRaises(RuntimeError):
            await chain.chat([{"role": "user", "content": "hi"}])


class TestAgentIntegration(unittest.IsolatedAsyncioTestCase):
    """Boot a REAL AionHand and verify the Hermes-parity wiring end to end.

    Regression class for bugs found by live smoke testing:
    * set_context(cron_scheduler=getattr(self, "_cron", None)) — attribute
      is _scheduler, so the cronjob tool always saw None.
    * shutdown() passed KnowledgeManager's SYNC shutdown() into
      asyncio.gather -> TypeError on every graceful shutdown.
    """

    async def test_boot_wire_search_shutdown(self):
        from aion_core.agent.core import AionHand, AgentConfig

        tmp = tempfile.mkdtemp(prefix="aion-it-")
        base = Path(tmp)
        config = AgentConfig(
            home_dir=base,
            data_dir=base / "data",
            memory_dir=base / "memory",
            skills_dir=base / "skills",
            tools_dir=base / "tools",
            logs_dir=base / "logs",
            config_file=base / "config.json",
            messaging_enabled=False,
            workflow_enabled=False,
            benchmark_enabled=False,
            knowledge_enabled=True,  # exercise the sync-shutdown path
            mcp_enabled=False,
        )
        agent = await AionHand(config=config).start()
        try:
            # Session store wired
            self.assertIsNotNone(agent._state)

            # Tool context actually received the live cron scheduler
            from aion_core.tools.registry import _TOOL_CONTEXT

            self.assertIs(_TOOL_CONTEXT.cron_scheduler, agent._scheduler)

            # cronjob tool works through the live agent
            created = await agent.execute_tool(
                "cronjob", action="create", schedule="30m", task="it-task"
            )
            inner = created.get("result", created)
            self.assertTrue(inner["success"], inner)

            # chat() persists both sides of the conversation
            result = await agent.chat(
                "integration secret ITTOKEN-7", session_id="it-session"
            )
            self.assertIn("content", result)
            msgs = agent._state.get_messages("it-session")
            roles = [m["role"] for m in msgs]
            self.assertIn("user", roles)
            self.assertIn("assistant", roles)

            # session_search tool finds the archived message
            found = await agent.execute_tool(
                "session_search", query="ITTOKEN-7", limit=5
            )
            inner = found.get("result", found)
            self.assertTrue(inner["success"])
            self.assertGreaterEqual(inner["count"], 1)
        finally:
            # Must not raise (regression: TypeError from sync shutdown)
            await agent.shutdown()

    async def test_goal_loop_uses_verify_output(self):
        """run_goal_loop must stop early when verify_output passes."""
        from aion_core.agent.core import AionHand, AgentConfig

        tmp = tempfile.mkdtemp(prefix="aion-goal-")
        base = Path(tmp)
        config = AgentConfig(
            home_dir=base,
            data_dir=base / "data",
            memory_dir=base / "memory",
            skills_dir=base / "skills",
            tools_dir=base / "tools",
            logs_dir=base / "logs",
            config_file=base / "config.json",
            messaging_enabled=False,
            workflow_enabled=False,
            benchmark_enabled=False,
            dynamic_enabled=False,
            mcp_enabled=False,
        )
        agent = await AionHand(config=config).start()
        try:
            calls = {"n": 0}

            async def fake_chat(message, **kwargs):
                calls["n"] += 1
                return {"content": "done", "tools_used": [], "metadata": {}}

            agent.chat = fake_chat  # type: ignore[method-assign]

            async def fake_verify_output(task, output, mission=None):
                return {
                    "passed": True, "score": 0.95, "passed_count": 5,
                    "total": 5, "issues": [],
                }

            agent._pipeline.verify_output = fake_verify_output  # type: ignore[method-assign]

            result = await agent.run_goal_loop("do the thing", max_iterations=10)
            self.assertTrue(result["achieved"])
            self.assertEqual(result["final_score"], 0.95)
            self.assertEqual(calls["n"], 1)  # stopped after first iteration
            self.assertIn("verification", result["iterations"][0])
        finally:
            await agent.shutdown()


if __name__ == "__main__":
    unittest.main()
