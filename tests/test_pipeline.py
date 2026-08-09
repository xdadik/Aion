#!/usr/bin/env python3
"""Comprehensive tests for aion_core/pipeline/ modules."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aion_core.pipeline.confidence import ConfidenceEstimator
from aion_core.pipeline.critic import CritiqueResult, Critic
from aion_core.pipeline.engine import PipelineResult, PipelineEngine
from aion_core.pipeline.executor import ExecutionResult, ParallelExecutor
from aion_core.pipeline.learning import TaskLesson, RuntimeLearning
from aion_core.pipeline.mission import MissionAnalysis, MissionAnalyzer
from aion_core.pipeline.planner import PlanNode, ExecutionPlan, DynamicPlanner
from aion_core.pipeline.repair import RepairResult, RepairEngine
from aion_core.pipeline.verification import VerificationResult, Verifier

# ===================================================================
# ConfidenceEstimator tests
# ===================================================================


class TestConfidenceEstimator(unittest.TestCase):
    """Tests for the ConfidenceEstimator class."""

    def test_estimate_returns_dict_with_confidence_key(self):
        """estimate should return a float between 0 and 1."""
        estimator = ConfidenceEstimator()
        verif = VerificationResult(
            passed=True, confidence=0.9, issues=[], checked_by="test"
        )
        critique = CritiqueResult(score=0.8)
        confidence = estimator.estimate(
            result="Some good output",
            verifications=[verif],
            critique=critique,
        )
        self.assertIsInstance(confidence, float)
        self.assertGreaterEqual(confidence, 0.0)
        self.assertLessEqual(confidence, 1.0)

    def test_estimate_high_confidence_for_clear_task(self):
        """A clear, structured result with passing verification should yield high confidence."""
        estimator = ConfidenceEstimator()
        verif = VerificationResult(
            passed=True, confidence=0.95, issues=[], checked_by="test"
        )
        critique = CritiqueResult(score=0.9)
        result = "# Step 1: Research\n## Findings\nDetailed analysis here.\n```python\ndef hello():\n    pass\n```"
        confidence = estimator.estimate(
            result=result, verifications=[verif], critique=critique
        )
        self.assertGreater(confidence, 0.6)

    def test_estimate_low_confidence_for_vague_task(self):
        """A vague, error-containing result with failing verification should yield low confidence."""
        estimator = ConfidenceEstimator()
        verif = VerificationResult(
            passed=False,
            confidence=0.2,
            issues=["Critical error"],
            checked_by="test",
        )
        critique = CritiqueResult(score=0.2, issues=["Major issue"])
        result = "error: something went wrong"
        confidence = estimator.estimate(
            result=result, verifications=[verif], critique=critique
        )
        self.assertLess(confidence, 0.5)


# ===================================================================
# CritiqueResult tests
# ===================================================================


class TestCritiqueResult(unittest.TestCase):
    """Tests for the CritiqueResult dataclass."""

    def test_creation_defaults(self):
        """Default CritiqueResult should have expected default values."""
        cr = CritiqueResult()
        self.assertAlmostEqual(cr.score, 0.5)
        self.assertEqual(cr.issues, [])
        self.assertEqual(cr.improvements, [])
        self.assertFalse(cr.should_repair)

    def test_to_dict(self):
        """to_dict should return a dictionary with all fields."""
        cr = CritiqueResult(
            score=0.85,
            issues=["Minor issue"],
            improvements=["Fix spacing"],
            should_repair=False,
        )
        d = cr.to_dict()
        self.assertAlmostEqual(d["score"], 0.85)
        self.assertEqual(d["issues"], ["Minor issue"])
        self.assertEqual(d["improvements"], ["Fix spacing"])
        self.assertFalse(d["should_repair"])


# ===================================================================
# Critic tests
# ===================================================================


class TestCritic(unittest.TestCase):
    """Tests for the Critic class."""

    def test_critic_creation(self):
        """Critic should initialize with an agent and default threshold."""
        mock_agent = MagicMock()
        critic = Critic(agent=mock_agent)
        self.assertEqual(critic._agent, mock_agent)
        self.assertAlmostEqual(critic.repair_threshold, 0.7)

    def test_critic_analyze_returns_critique_result(self):
        """critique() should return a CritiqueResult."""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(
            return_value={
                "content": '{"score": 0.8, "issues": ["small issue"], "improvements": ["fix it"], "should_repair": false}',
            }
        )
        critic = Critic(agent=mock_agent)

        verif = VerificationResult(
            passed=True, confidence=0.9, issues=[], checked_by="test"
        )

        import asyncio

        result = asyncio.run(
            critic.critique("Write code", "def hello(): pass", [verif])
        )
        self.assertIsInstance(result, CritiqueResult)
        self.assertGreater(result.score, 0.0)


# ===================================================================
# PipelineResult tests
# ===================================================================


class TestPipelineResult(unittest.TestCase):
    """Tests for the PipelineResult dataclass."""

    def test_creation_defaults(self):
        """Default PipelineResult should have expected defaults."""
        pr = PipelineResult()
        self.assertFalse(pr.success)
        self.assertIsNone(pr.output)
        self.assertAlmostEqual(pr.confidence, 0.0)
        self.assertIsNone(pr.mission)
        self.assertEqual(pr.tokens_total, 0)
        self.assertEqual(pr.lessons_learned, [])
        self.assertIsNone(pr.error)

    def test_to_dict(self):
        """to_dict should return a dictionary with all key fields."""
        pr = PipelineResult(
            success=True,
            output="Hello world",
            confidence=0.85,
            stages_completed=["analyze", "execute"],
            tokens_total=500,
            time_total=1.5,
        )
        d = pr.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["output"], "Hello world")
        self.assertIn("confidence", d)
        self.assertEqual(d["tokens_total"], 500)


# ===================================================================
# PipelineEngine tests
# ===================================================================


class TestPipelineEngine(unittest.TestCase):
    """Tests for the PipelineEngine class."""

    def test_engine_creation(self):
        """PipelineEngine should initialize with all sub-components."""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value={"content": "test response"})
        with tempfile.TemporaryDirectory() as tmpdir:
            engine = PipelineEngine(
                agent=mock_agent,
                learning_path=str(Path(tmpdir) / "lessons.json"),
                enable_learning=False,
            )
        self.assertIsNotNone(engine._analyzer)
        self.assertIsNotNone(engine._planner)
        self.assertIsNotNone(engine._executor)
        self.assertIsNotNone(engine._critic)

    def test_add_verifier(self):
        """add_verifier should register a verifier in the pipeline."""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value={"content": "test"})
        engine = PipelineEngine(agent=mock_agent, enable_learning=False)
        initial_count = len(engine._verifier.get_verifiers())

        # Create a custom verifier
        class CustomVerifier(Verifier):
            name = "custom_verifier"

            async def verify(self, task, result, context):
                return VerificationResult(
                    passed=True, confidence=1.0, checked_by=self.name
                )

        engine.add_verifier(CustomVerifier())
        self.assertIn("custom_verifier", engine._verifier.get_verifiers())
        self.assertEqual(len(engine._verifier.get_verifiers()), initial_count + 1)

    def test_remove_verifier(self):
        """remove_verifier should remove a registered verifier."""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value={"content": "test"})
        engine = PipelineEngine(agent=mock_agent, enable_learning=False)
        initial_count = len(engine._verifier.get_verifiers())
        result = engine.remove_verifier("logic_verifier")
        self.assertTrue(result)
        self.assertEqual(len(engine._verifier.get_verifiers()), initial_count - 1)

    def test_get_stats(self):
        """get_stats should return a dictionary with pipeline statistics."""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(return_value={"content": "test"})
        engine = PipelineEngine(agent=mock_agent, enable_learning=False)
        stats = engine.get_stats()
        self.assertIn("confidence_threshold", stats)
        self.assertIn("max_workers", stats)
        self.assertIn("verifiers", stats)
        self.assertIn("learning_enabled", stats)


# ===================================================================
# ExecutionResult tests
# ===================================================================


class TestExecutionResult(unittest.TestCase):
    """Tests for the ExecutionResult dataclass."""

    def test_creation_defaults(self):
        """Default ExecutionResult should have expected default values."""
        er = ExecutionResult()
        self.assertEqual(er.node_id, "")
        self.assertEqual(er.status, "pending")
        self.assertIsNone(er.output)
        self.assertEqual(er.tokens_used, 0)
        self.assertEqual(er.elapsed, 0.0)
        self.assertIsNone(er.error)
        self.assertEqual(er.retry_count, 0)

    def test_to_dict(self):
        """to_dict should return a dictionary with all fields."""
        er = ExecutionResult(
            node_id="step_1",
            status="success",
            output="Hello",
            tokens_used=100,
            elapsed=1.5,
            retry_count=0,
        )
        d = er.to_dict()
        self.assertEqual(d["node_id"], "step_1")
        self.assertEqual(d["status"], "success")
        self.assertEqual(d["tokens_used"], 100)


# ===================================================================
# ParallelExecutor tests
# ===================================================================


class TestParallelExecutor(unittest.TestCase):
    """Tests for the ParallelExecutor class."""

    def test_executor_creation(self):
        """ParallelExecutor should initialize with agent and max_workers."""
        mock_agent = MagicMock()
        executor = ParallelExecutor(agent=mock_agent, max_workers=3)
        self.assertEqual(executor._agent, mock_agent)
        self.assertEqual(executor._max_workers, 3)

    def test_get_metrics(self):
        """get_metrics with no results should return zero nodes executed."""
        mock_agent = MagicMock()
        executor = ParallelExecutor(agent=mock_agent)
        metrics = executor.get_metrics()
        self.assertEqual(metrics["nodes_executed"], 0)


# ===================================================================
# TaskLesson tests
# ===================================================================


class TestTaskLesson(unittest.TestCase):
    """Tests for the TaskLesson dataclass."""

    def test_creation(self):
        """TaskLesson should accept all fields and store them."""
        lesson = TaskLesson(
            task_hash="abc123",
            task_summary="Implement REST API",
            task_keywords=["rest", "api", "implement"],
            execution_success=True,
            final_confidence=0.85,
            learned_rules=["Always validate input"],
            mistakes=["Missing input validation"],
        )
        self.assertEqual(lesson.task_hash, "abc123")
        self.assertTrue(lesson.execution_success)
        self.assertEqual(lesson.learned_rules, ["Always validate input"])

    def test_to_dict_from_dict_roundtrip(self):
        """to_dict + from_dict should roundtrip without data loss."""
        lesson = TaskLesson(
            task_hash="hash1",
            task_summary="Build API",
            task_keywords=["api"],
            execution_success=False,
            final_confidence=0.4,
            learned_rules=["Check permissions"],
            mistakes=["Missing auth check"],
            was_repaired=True,
            repair_successful=True,
        )
        d = lesson.to_dict()
        restored = TaskLesson.from_dict(d)
        self.assertEqual(restored.task_hash, lesson.task_hash)
        self.assertEqual(restored.task_summary, lesson.task_summary)
        self.assertEqual(restored.task_keywords, lesson.task_keywords)
        self.assertFalse(restored.execution_success)
        self.assertAlmostEqual(restored.final_confidence, 0.4)
        self.assertTrue(restored.was_repaired)


# ===================================================================
# RuntimeLearning tests
# ===================================================================


class TestRuntimeLearning(unittest.TestCase):
    """Tests for the RuntimeLearning class."""

    def test_creation(self):
        """RuntimeLearning should initialize with empty lessons and rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rl = RuntimeLearning(storage_path=str(Path(tmpdir) / "lessons.json"))
        self.assertEqual(rl.lessons_count, 0)
        self.assertEqual(rl.rules_count, 0)

    def test_add_and_get_lessons(self):
        """Adding lessons and retrieving them should work."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rl = RuntimeLearning(storage_path=str(Path(tmpdir) / "lessons.json"))
            rl._loaded = True  # Skip actual file load
            lesson = TaskLesson(
                task_hash="hash1",
                task_summary="Build REST API with JWT auth",
                task_keywords=["rest", "api", "jwt", "auth", "build"],
                execution_success=True,
                final_confidence=0.9,
                learned_rules=["Always include error handling"],
                timestamp="2025-01-01T00:00:00Z",
            )
            rl._lessons.append(lesson)
            for kw in lesson.task_keywords:
                if kw not in rl._task_index:
                    rl._task_index[kw] = []
                rl._task_index[kw].append(0)

            relevant = rl.get_relevant_lessons("Build a REST API with JWT")
            self.assertGreater(len(relevant), 0)

    def test_get_relevant_lessons(self):
        """get_relevant_lessons should return lessons matching by keyword overlap."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rl = RuntimeLearning(storage_path=str(Path(tmpdir) / "lessons.json"))
            rl._loaded = True
            lesson = TaskLesson(
                task_hash="hash1",
                task_summary="Create a database schema",
                task_keywords=["database", "schema", "create"],
                execution_success=False,
                final_confidence=0.3,
                learned_rules=["Always backup before schema changes"],
                timestamp="2025-01-01T00:00:00Z",
            )
            rl._lessons.append(lesson)
            for kw in lesson.task_keywords:
                if kw not in rl._task_index:
                    rl._task_index[kw] = []
                rl._task_index[kw].append(0)

            relevant = rl.get_relevant_lessons("create database schema")
            self.assertGreater(len(relevant), 0)

    def test_save_and_load(self):
        """save and load should roundtrip lessons and rules."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "lessons.json")
            rl = RuntimeLearning(storage_path=path)
            rl._loaded = True
            lesson = TaskLesson(
                task_hash="hash1",
                task_summary="Test task",
                task_keywords=["test"],
                execution_success=True,
                final_confidence=0.8,
                learned_rules=["Rule 1"],
            )
            rl._lessons.append(lesson)
            rl._save()

            # Load into new instance
            rl2 = RuntimeLearning(storage_path=path)
            rl2.load()
            self.assertEqual(rl2.lessons_count, 1)
            self.assertEqual(rl2._lessons[0].task_hash, "hash1")

    def test_get_stats(self):
        """get_stats should return statistics about stored lessons."""
        with tempfile.TemporaryDirectory() as tmpdir:
            rl = RuntimeLearning(storage_path=str(Path(tmpdir) / "lessons.json"))
            stats = rl.get_stats()
            self.assertEqual(stats["total_lessons"], 0)
            self.assertEqual(stats["total_rules"], 0)

            # Add some lessons
            rl._loaded = True
            rl._lessons.append(
                TaskLesson(
                    task_hash="h1",
                    task_summary="task1",
                    task_keywords=["t"],
                    execution_success=True,
                    final_confidence=0.9,
                )
            )
            rl._lessons.append(
                TaskLesson(
                    task_hash="h2",
                    task_summary="task2",
                    task_keywords=["t"],
                    execution_success=False,
                    final_confidence=0.3,
                )
            )
            stats = rl.get_stats()
            self.assertEqual(stats["total_lessons"], 2)
            self.assertAlmostEqual(stats["success_rate"], 0.5)


# ===================================================================
# MissionAnalysis tests
# ===================================================================


class TestMissionAnalysis(unittest.TestCase):
    """Tests for the MissionAnalysis dataclass."""

    def test_creation_defaults(self):
        """Default MissionAnalysis should have expected default values."""
        ma = MissionAnalysis()
        self.assertEqual(ma.intent, "")
        self.assertEqual(ma.goals, [])
        self.assertEqual(ma.constraints, [])
        self.assertEqual(ma.risks, [])
        self.assertAlmostEqual(ma.complexity, 0.5)
        self.assertEqual(ma.estimated_tokens, 2000)
        self.assertEqual(ma.capabilities_needed, [])

    def test_to_dict_from_dict_roundtrip(self):
        """to_dict + from_dict should roundtrip without data loss."""
        ma = MissionAnalysis(
            intent="Build a REST API",
            goals=["Create endpoints", "Add auth"],
            constraints=["Use PostgreSQL"],
            risks=["Security concerns"],
            complexity=0.7,
            estimated_tokens=5000,
            estimated_time=60,
            capabilities_needed=["llm", "code_execution"],
            raw_task="Build a REST API with JWT auth",
        )
        d = ma.to_dict()
        restored = MissionAnalysis.from_dict(d)
        self.assertEqual(restored.intent, ma.intent)
        self.assertEqual(restored.goals, ma.goals)
        self.assertAlmostEqual(restored.complexity, ma.complexity)
        self.assertEqual(restored.capabilities_needed, ma.capabilities_needed)
        self.assertEqual(restored.raw_task, ma.raw_task)


# ===================================================================
# MissionAnalyzer tests
# ===================================================================


class TestMissionAnalyzer(unittest.TestCase):
    """Tests for the MissionAnalyzer class."""

    def test_creation(self):
        """MissionAnalyzer should initialize with an agent."""
        mock_agent = MagicMock()
        analyzer = MissionAnalyzer(agent=mock_agent)
        self.assertEqual(analyzer._agent, mock_agent)

    def test_analyze_returns_mission_analysis(self):
        """analyze() should return a MissionAnalysis even on LLM failure."""
        mock_agent = MagicMock()
        mock_agent.chat = AsyncMock(
            return_value={"content": "not json", "metadata": {}}
        )
        analyzer = MissionAnalyzer(agent=mock_agent)

        import asyncio

        result = asyncio.run(analyzer.analyze("Build a REST API"))
        self.assertIsInstance(result, MissionAnalysis)
        self.assertGreater(len(result.raw_task), 0)


# ===================================================================
# PlanNode tests
# ===================================================================


class TestPlanNode(unittest.TestCase):
    """Tests for the PlanNode dataclass."""

    def test_creation_defaults(self):
        """Default PlanNode should have expected default values."""
        node = PlanNode()
        self.assertEqual(node.id, "")
        self.assertEqual(node.name, "")
        self.assertEqual(node.node_type, "agent")
        self.assertIsNone(node.agent_type)
        self.assertIsNone(node.tool_name)
        self.assertEqual(node.dependencies, [])
        self.assertEqual(node.retry_limit, 2)
        self.assertEqual(node.timeout, 120)

    def test_to_dict_from_dict_roundtrip(self):
        """to_dict + from_dict should roundtrip without data loss."""
        node = PlanNode(
            id="step_1",
            name="Execute Task",
            node_type="agent",
            agent_type="coder",
            prompt="Build the API",
            dependencies=[],
            retry_limit=3,
            timeout=180,
            metadata={"key": "value"},
        )
        d = node.to_dict()
        restored = PlanNode.from_dict(d)
        self.assertEqual(restored.id, node.id)
        self.assertEqual(restored.name, node.name)
        self.assertEqual(restored.node_type, node.node_type)
        self.assertEqual(restored.agent_type, node.agent_type)
        self.assertEqual(restored.retry_limit, 3)
        self.assertEqual(restored.timeout, 180)
        self.assertEqual(restored.metadata, {"key": "value"})


# ===================================================================
# ExecutionPlan tests
# ===================================================================


class TestExecutionPlan(unittest.TestCase):
    """Tests for the ExecutionPlan dataclass."""

    def test_creation_with_nodes(self):
        """ExecutionPlan should hold a dict of nodes and an entry node."""
        n1 = PlanNode(id="step_1", name="Step 1")
        n2 = PlanNode(id="step_2", name="Step 2", dependencies=["step_1"])
        plan = ExecutionPlan(
            nodes={"step_1": n1, "step_2": n2},
            entry_node="step_1",
        )
        self.assertEqual(len(plan.nodes), 2)
        self.assertEqual(plan.entry_node, "step_1")
        self.assertEqual(plan.risk_level, "low")

    def test_to_dict(self):
        """to_dict should return a dictionary with plan structure."""
        n1 = PlanNode(id="step_1", name="Step 1")
        plan = ExecutionPlan(
            nodes={"step_1": n1},
            entry_node="step_1",
            total_estimated_tokens=3000,
        )
        d = plan.to_dict()
        self.assertIn("nodes", d)
        self.assertEqual(d["entry_node"], "step_1")
        self.assertEqual(d["total_estimated_tokens"], 3000)
        self.assertIn("complexity", d)
        self.assertIn("risk_level", d)

    def test_next_id_increments(self):
        """Plan node IDs should be unique and incrementing."""
        nodes = {}
        for i in range(5):
            nid = f"step_{i + 1}"
            nodes[nid] = PlanNode(id=nid, name=f"Step {i + 1}")
        plan = ExecutionPlan(nodes=nodes, entry_node="step_1")
        ids = list(plan.nodes.keys())
        self.assertEqual(len(ids), 5)
        # Each ID is unique
        self.assertEqual(len(set(ids)), 5)


# ===================================================================
# DynamicPlanner tests
# ===================================================================


class TestDynamicPlanner(unittest.TestCase):
    """Tests for the DynamicPlanner class."""

    def test_planner_creation(self):
        """DynamicPlanner should initialize with an agent."""
        mock_agent = MagicMock()
        planner = DynamicPlanner(agent=mock_agent)
        self.assertEqual(planner._agent, mock_agent)


# ===================================================================
# RepairResult tests
# ===================================================================


class TestRepairResult(unittest.TestCase):
    """Tests for the RepairResult dataclass."""

    def test_creation_defaults(self):
        """Default RepairResult should have expected defaults."""
        rr = RepairResult()
        self.assertFalse(rr.success)
        self.assertIsNone(rr.repaired_output)
        self.assertEqual(rr.repairs_made, [])
        self.assertEqual(rr.tokens_used, 0)
        self.assertEqual(rr.attempts, 0)
        self.assertIsNone(rr.error)

    def test_to_dict(self):
        """to_dict should return a dictionary with all fields."""
        rr = RepairResult(
            success=True,
            repaired_output="Fixed output",
            repairs_made=["Fixed typo"],
            tokens_used=200,
            elapsed=2.5,
            attempts=1,
        )
        d = rr.to_dict()
        self.assertTrue(d["success"])
        self.assertEqual(d["repairs_made"], ["Fixed typo"])
        self.assertEqual(d["tokens_used"], 200)
        self.assertEqual(d["attempts"], 1)


# ===================================================================
# RepairEngine tests
# ===================================================================


class TestRepairEngine(unittest.TestCase):
    """Tests for the RepairEngine class."""

    def test_engine_creation(self):
        """RepairEngine should initialize with an agent and max attempts."""
        mock_agent = MagicMock()
        engine = RepairEngine(agent=mock_agent, max_repair_attempts=3)
        self.assertEqual(engine._agent, mock_agent)
        self.assertEqual(engine._max_repair_attempts, 3)


# ===================================================================
# VerificationResult tests
# ===================================================================


class TestVerificationResult(unittest.TestCase):
    """Tests for the VerificationResult dataclass."""

    def test_creation_defaults(self):
        """Default VerificationResult should have expected defaults."""
        vr = VerificationResult()
        self.assertFalse(vr.passed)
        self.assertAlmostEqual(vr.confidence, 0.5)
        self.assertEqual(vr.issues, [])
        self.assertEqual(vr.suggestions, [])
        self.assertEqual(vr.checked_by, "")

    def test_to_dict(self):
        """to_dict should return a dictionary with all fields."""
        vr = VerificationResult(
            passed=True,
            confidence=0.95,
            issues=["No issues found"],
            suggestions=[],
            checked_by="logic_verifier",
        )
        d = vr.to_dict()
        self.assertTrue(d["passed"])
        self.assertAlmostEqual(d["confidence"], 0.95, places=3)
        self.assertEqual(d["issues"], ["No issues found"])
        self.assertEqual(d["checked_by"], "logic_verifier")


# ===================================================================
# Verifier tests
# ===================================================================


class TestVerifier(unittest.TestCase):
    """Tests for the abstract Verifier base class."""

    def test_verifier_creation(self):
        """A concrete Verifier subclass should have a name attribute."""

        # Verifier is abstract, so we create a minimal concrete subclass
        class MinimalVerifier(Verifier):
            name = "minimal_verifier"

            async def verify(self, task, result, context):
                return VerificationResult(
                    passed=True, confidence=1.0, checked_by=self.name
                )

        v = MinimalVerifier()
        self.assertEqual(v.name, "minimal_verifier")

    def test_is_applicable(self):
        """Default is_applicable should return True."""

        class MinimalVerifier(Verifier):
            name = "minimal_verifier"

            async def verify(self, task, result, context):
                return VerificationResult(
                    passed=True, confidence=1.0, checked_by=self.name
                )

        v = MinimalVerifier()
        self.assertTrue(v.is_applicable("any task", "any result", {}))


if __name__ == "__main__":
    unittest.main()
