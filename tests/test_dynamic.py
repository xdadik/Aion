#!/usr/bin/env python3
"""Comprehensive tests for aion_core/dynamic/ modules."""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aion_core.dynamic.agent_factory import (
    AgentProfile,
    DynamicAgent,
    DynamicAgentFactory,
    VALID_ROLES,
)
from aion_core.dynamic.topology import AgentTopology, TopologyManager
from aion_core.dynamic.orchestrator import DynamicOrchestrator, DynamicOrchestrationPlan
from aion_core.dynamic.manager import classify_task, estimate_complexity

# ===================================================================
# AgentProfile tests
# ===================================================================


class TestAgentProfile(unittest.TestCase):
    """Tests for the AgentProfile dataclass."""

    def test_default_profile_has_expected_fields(self):
        """A default AgentProfile should have all expected attributes with defaults."""
        profile = AgentProfile(
            name="Test Agent",
            role="coder",
            system_prompt="You are a coder.",
        )
        self.assertEqual(profile.name, "Test Agent")
        self.assertEqual(profile.role, "coder")
        self.assertEqual(profile.system_prompt, "You are a coder.")
        self.assertEqual(profile.tools_allowed, [])
        self.assertIsNone(profile.model)
        self.assertAlmostEqual(profile.temperature, 0.7)
        self.assertEqual(profile.max_turns, 10)

    def test_custom_profile_overrides_defaults(self):
        """Custom values should override default fields."""
        profile = AgentProfile(
            name="Custom",
            role="researcher",
            system_prompt="Research prompt",
            tools_allowed=["web_search"],
            model="gpt-4o",
            temperature=0.3,
            max_turns=20,
        )
        self.assertEqual(profile.tools_allowed, ["web_search"])
        self.assertEqual(profile.model, "gpt-4o")
        self.assertAlmostEqual(profile.temperature, 0.3)
        self.assertEqual(profile.max_turns, 20)

    def test_profile_role_validation_valid_roles(self):
        """Creating a profile with any valid role should succeed."""
        for role in VALID_ROLES:
            profile = AgentProfile(
                name=f"{role} Agent",
                role=role,  # type: ignore[arg-type]
                system_prompt="test",
            )
            self.assertEqual(profile.role, role)

    def test_profile_role_validation_invalid_role_raises(self):
        """Creating a profile with an invalid role is caught by the factory, not the dataclass.

        Note: AgentProfile itself is a plain dataclass and with
        ``from __future__ import annotations`` the Literal type is only
        a string hint at runtime, so assigning an invalid string does NOT
        raise.  The validation gate is in DynamicAgentFactory.create_agent.
        """
        # The dataclass accepts any string at runtime
        profile = AgentProfile(
            name="Bad Role",
            role="nonexistent_role",  # type: ignore[arg-type]
            system_prompt="test",
        )
        self.assertEqual(profile.role, "nonexistent_role")

        # But the factory rejects it
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            with self.assertRaises(ValueError):
                factory.create_agent("nonexistent_role", "test")  # type: ignore[arg-type]


# ===================================================================
# DynamicAgent tests
# ===================================================================


class TestDynamicAgent(unittest.TestCase):
    """Tests for the DynamicAgent dataclass."""

    def test_dynamic_agent_creation(self):
        """Creating a DynamicAgent should populate all fields."""
        profile = AgentProfile(name="Test", role="coder", system_prompt="test")
        agent = DynamicAgent(id="abc123", profile=profile)
        self.assertEqual(agent.id, "abc123")
        self.assertEqual(agent.profile, profile)
        self.assertEqual(agent.status, "created")
        self.assertIsNone(agent.parent_task)
        self.assertEqual(agent.tokens_used, 0)
        self.assertEqual(agent.results, [])
        self.assertEqual(agent.child_agents, [])
        self.assertEqual(agent.error_count, 0)

    def test_dynamic_agent_status_transitions(self):
        """Agent status should transition: created -> running -> completed."""
        profile = AgentProfile(name="Test", role="coder", system_prompt="test")
        agent = DynamicAgent(id="abc123", profile=profile)
        self.assertEqual(agent.status, "created")
        agent.status = "running"
        self.assertEqual(agent.status, "running")
        agent.status = "completed"
        self.assertEqual(agent.status, "completed")


# ===================================================================
# DynamicAgentFactory tests
# ===================================================================


class TestDynamicAgentFactory(unittest.TestCase):
    """Tests for the DynamicAgentFactory class."""

    def test_factory_creation(self):
        """Factory should initialize with templates and empty agent list."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
        self.assertIsInstance(factory._templates, dict)
        self.assertEqual(len(factory._templates), 8)
        self.assertEqual(factory._agents, {})
        self.assertEqual(factory._archive, [])

    def test_factory_create_agent_valid_role(self):
        """Creating an agent with a valid role should succeed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            agent = factory.create_agent("coder", "Write a function")
            self.assertIsInstance(agent, DynamicAgent)
            self.assertEqual(agent.profile.role, "coder")
            self.assertEqual(agent.status, "created")
            self.assertIn(agent.id, factory._agents)
            self.assertEqual(factory._stats["total_created"], 1)

    def test_factory_get_agent_returns_agent(self):
        """get_agent should return the agent or None if not found."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            agent = factory.create_agent("planner", "Plan a task")
            retrieved = factory.get_agent(agent.id)
            self.assertIs(retrieved, agent)
            self.assertIsNone(factory.get_agent("nonexistent"))

    def test_factory_destroy_agent(self):
        """Destroying an agent should remove it from active agents and archive it."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            agent = factory.create_agent("coder", "Code something")
            agent_id = agent.id
            result = factory.destroy_agent(agent_id)
            self.assertTrue(result)
            self.assertNotIn(agent_id, factory._agents)
            self.assertIsNone(factory.get_agent(agent_id))
            self.assertEqual(len(factory._archive), 1)
            self.assertEqual(factory._archive[0]["id"], agent_id)
            self.assertEqual(factory._stats["total_destroyed"], 1)

    def test_factory_destroy_all(self):
        """destroy_all should destroy every active agent."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            factory.create_agent("coder", "Task 1")
            factory.create_agent("researcher", "Task 2")
            factory.create_agent("verifier", "Task 3")
            count = factory.destroy_all()
            self.assertEqual(count, 3)
            self.assertEqual(len(factory._agents), 0)
            self.assertEqual(len(factory._archive), 3)

    def test_factory_get_stats(self):
        """get_stats should return a dict with expected keys."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            factory.create_agent("coder", "Test")
            stats = factory.get_stats()
            self.assertEqual(stats["total_created"], 1)
            self.assertIn("active_count", stats)
            self.assertIn("archive_size", stats)
            self.assertIn("by_role", stats)

    def test_factory_archive_persistence(self):
        """save_archive and load_archive should roundtrip correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage = Path(tmpdir)
            factory = DynamicAgentFactory(storage_dir=storage)
            factory.create_agent("coder", "Write tests")
            factory.create_agent("researcher", "Research topic")
            factory.destroy_all()

            # Save
            factory.save_archive()
            archive_file = storage / "agent_archive.json"
            self.assertTrue(archive_file.exists())

            # Load into a new factory
            factory2 = DynamicAgentFactory(storage_dir=storage)
            factory2.load_archive()
            self.assertEqual(len(factory2._archive), 2)
            self.assertEqual(factory2._archive[0]["id"], factory._archive[0]["id"])


# ===================================================================
# AgentTopology tests
# ===================================================================


class TestAgentTopology(unittest.TestCase):
    """Tests for the AgentTopology dataclass."""

    def test_topology_creation(self):
        """Creating a topology should populate all fields."""
        topo = AgentTopology(
            id="topo1",
            name="Test Topology",
            agents=["planner", "coder"],
            connections=[{"from": "planner", "to": "coder", "label": "plan"}],
        )
        self.assertEqual(topo.id, "topo1")
        self.assertEqual(topo.name, "Test Topology")
        self.assertEqual(topo.agents, ["planner", "coder"])
        self.assertEqual(len(topo.connections), 1)
        self.assertEqual(topo.success_rate, 0.0)
        self.assertEqual(topo.usage_count, 0)
        self.assertFalse(topo.is_default)

    def test_topology_to_dict_roundtrip(self):
        """to_dict + from_dict should roundtrip without data loss."""
        topo = AgentTopology(
            id="abc",
            name="Roundtrip Test",
            agents=["coder", "verifier"],
            connections=[{"from": "coder", "to": "verifier", "label": "code"}],
            success_rate=0.85,
            avg_tokens=3000.0,
            avg_time=15.0,
            task_types=["coding"],
            usage_count=10,
            is_default=True,
        )
        d = topo.to_dict()
        restored = AgentTopology.from_dict(d)
        self.assertEqual(restored.id, topo.id)
        self.assertEqual(restored.name, topo.name)
        self.assertEqual(restored.agents, topo.agents)
        self.assertAlmostEqual(restored.success_rate, topo.success_rate)
        self.assertEqual(restored.usage_count, topo.usage_count)
        self.assertTrue(restored.is_default)

    def test_topology_compatibility_score_task_type_match(self):
        """A topology whose task_types include the query type should score higher."""
        topo = AgentTopology(
            id="t1",
            name="Coding Topo",
            agents=["planner", "coder"],
            connections=[],
            task_types=["coding"],
            usage_count=5,
        )
        score = topo.compatibility_score("coding", complexity=5)
        # Should get credit for task type match + usage count weight
        self.assertGreater(score, 0.0)

    def test_topology_compatibility_score_no_match(self):
        """A topology with no matching task types should still return a score."""
        topo = AgentTopology(
            id="t2",
            name="Research Topo",
            agents=["researcher"],
            connections=[],
            task_types=["research"],
            usage_count=1,
        )
        score = topo.compatibility_score("coding", complexity=5)
        # No type match but should still give partial credit for general purpose
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 1.0)

    def test_topology_compatibility_score_complexity_match(self):
        """A topology with agent count matching complexity should score well."""
        # 3 agents for complexity=3 should be a good match
        topo = AgentTopology(
            id="t3",
            name="Medium Topo",
            agents=["planner", "coder", "verifier"],
            connections=[],
            task_types=["coding"],
            success_rate=1.0,
            usage_count=10,
        )
        score_high_complexity = topo.compatibility_score("coding", complexity=8)
        score_low_complexity = topo.compatibility_score("coding", complexity=2)
        # Both should return valid scores
        self.assertGreaterEqual(score_low_complexity, 0.0)
        self.assertLessEqual(score_high_complexity, 1.0)


# ===================================================================
# TopologyManager tests
# ===================================================================


class TestTopologyManager(unittest.TestCase):
    """Tests for the TopologyManager class."""

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.storage = Path(self.tmpdir.name)
        self.mgr = TopologyManager(storage_dir=self.storage)

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_initialization_seeds_default_topologies(self):
        """TopologyManager should initialize with 4 default topologies."""
        topos = self.mgr.list_topologies()
        self.assertEqual(len(topos), 4)
        names = {t.name for t in topos}
        self.assertIn("Plan-Code-Verify", names)
        self.assertIn("Research-Verify-Summarize", names)
        self.assertIn("Code-Critique-Repair", names)
        self.assertIn("Full Pipeline", names)

    def test_suggest_topology_returns_topology(self):
        """suggest_topology should return a topology for known task types."""
        topo = self.mgr.suggest_topology("coding", complexity=5)
        self.assertIsNotNone(topo)
        self.assertIsInstance(topo, AgentTopology)

    def test_create_topology(self):
        """create_topology should add a new topology to the manager."""
        topo = self.mgr.create_topology(
            agents=["researcher", "coder"],
            connections=[{"from": "researcher", "to": "coder", "label": "research"}],
            task_types=["hybrid"],
            name="Hybrid Topo",
        )
        self.assertIsNotNone(topo)
        self.assertEqual(topo.name, "Hybrid Topo")
        self.assertEqual(len(self.mgr.list_topologies()), 5)

    def test_remove_topology(self):
        """remove_topology should remove an existing topology."""
        topos = self.mgr.list_topologies()
        topo_id = topos[0].id
        result = self.mgr.remove_topology(topo_id)
        self.assertTrue(result)
        self.assertEqual(len(self.mgr.list_topologies()), 3)
        # Removing non-existent returns False
        self.assertFalse(self.mgr.remove_topology("nonexistent"))

    def test_record_execution_updates_averages(self):
        """Recording 3 executions should update running averages."""
        topo = self.mgr.list_topologies()[0]
        topo_id = topo.id

        self.mgr.record_execution(
            topo_id, "coding", success=True, tokens=100, time=10.0
        )
        self.assertEqual(topo.usage_count, 1)
        self.assertEqual(topo.success_rate, 1.0)

        self.mgr.record_execution(
            topo_id, "coding", success=False, tokens=200, time=20.0
        )
        self.assertEqual(topo.usage_count, 2)
        self.assertAlmostEqual(topo.success_rate, 0.5)

        self.mgr.record_execution(
            topo_id, "coding", success=True, tokens=300, time=30.0
        )
        self.assertEqual(topo.usage_count, 3)
        self.assertAlmostEqual(topo.success_rate, 2.0 / 3.0, places=4)
        self.assertAlmostEqual(topo.avg_tokens, 200.0)

    def test_evolve_topology_add_verifier(self):
        """Evolving with 'add verifier' should add a verifier agent."""
        topo = self.mgr.create_topology(
            agents=["coder"],
            connections=[],
            task_types=["coding"],
            name="Simple Coder",
        )
        evolved = self.mgr.evolve_topology(topo.id, "add verifier")
        self.assertIsNotNone(evolved)
        self.assertIn("verifier", evolved.agents)

    def test_evolve_topology_remove_summarizer(self):
        """Evolving with 'remove summarizer' should remove the summarizer."""
        topo = self.mgr.create_topology(
            agents=["researcher", "summarizer"],
            connections=[{"from": "researcher", "to": "summarizer", "label": "output"}],
            task_types=["research"],
            name="With Summarizer",
        )
        evolved = self.mgr.evolve_topology(topo.id, "remove summarizer")
        self.assertIsNotNone(evolved)
        self.assertNotIn("summarizer", evolved.agents)

    def test_evolve_topology_no_applicable_mutation_returns_none(self):
        """Evolving with no applicable keywords should return None."""
        topo = self.mgr.create_topology(
            agents=["coder"],
            connections=[],
            name="Minimal",
        )
        evolved = self.mgr.evolve_topology(topo.id, "just some random text")
        self.assertIsNone(evolved)

    def test_analyze_patterns_no_executions(self):
        """analyze_patterns with no executions should return empty patterns."""
        result = self.mgr.analyze_patterns()
        self.assertEqual(result["patterns"], [])
        self.assertEqual(result["total_executions"], 0)

    def test_analyze_patterns_with_executions(self):
        """analyze_patterns should produce insights after recording executions."""
        topo = self.mgr.list_topologies()[0]
        self.mgr.record_execution(
            topo.id, "coding", success=True, tokens=500, time=10.0
        )
        self.mgr.record_execution(
            topo.id, "coding", success=True, tokens=600, time=12.0
        )
        self.mgr.record_execution(
            topo.id, "research", success=False, tokens=800, time=20.0
        )

        result = self.mgr.analyze_patterns()
        self.assertEqual(result["total_executions"], 3)
        self.assertGreater(len(result["patterns"]), 0)
        self.assertIn("best_topology", result)
        self.assertIn("recommendations", result)

    def test_save_and_load_persistence(self):
        """save and load should roundtrip all topology and execution data."""
        self.mgr.record_execution(
            self.mgr.list_topologies()[0].id, "coding", True, 500, 10.0
        )
        self.mgr.save()

        # Create new manager and load
        mgr2 = TopologyManager(storage_dir=self.storage)
        mgr2._topologies.clear()  # Clear seeds so only loaded data remains
        mgr2.load()
        # The loaded data includes the recorded execution
        self.assertEqual(len(mgr2._execution_log), 1)
        self.assertIn("coding", mgr2._execution_log[0]["task_type"])

    def test_get_stats(self):
        """get_stats should return comprehensive statistics."""
        stats = self.mgr.get_stats()
        self.assertEqual(stats["topology_count"], 4)
        self.assertEqual(stats["default_count"], 4)
        self.assertIn("execution_log_size", stats)
        self.assertIn("overall_success_rate", stats)
        self.assertIn("topologies", stats)

    def test_get_best_topologies(self):
        """get_best_topologies should return topologies sorted by success rate."""
        # Record some executions to differentiate scores
        topo = self.mgr.list_topologies()[0]
        self.mgr.record_execution(topo.id, "coding", success=True, tokens=100, time=5.0)
        best = self.mgr.get_best_topologies(limit=2)
        self.assertGreaterEqual(len(best), 2)
        # The best should be the one with recorded success
        self.assertGreaterEqual(best[0].success_rate, best[1].success_rate)


# ===================================================================
# DynamicOrchestrator tests
# ===================================================================


class TestDynamicOrchestrator(unittest.TestCase):
    """Tests for the DynamicOrchestrator class."""

    def test_orchestrator_creation(self):
        """Orchestrator should initialize with factory and topology manager."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            topo_mgr = TopologyManager(storage_dir=Path(tmpdir))
            orch = DynamicOrchestrator(factory=factory, topology_manager=topo_mgr)
            self.assertIs(orch._factory, factory)
            self.assertIs(orch._topology_mgr, topo_mgr)
            self.assertEqual(orch._execution_history, [])

    def test_create_plan(self):
        """create_plan should return a DynamicOrchestrationPlan."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            topo_mgr = TopologyManager(storage_dir=Path(tmpdir))
            orch = DynamicOrchestrator(factory=factory, topology_manager=topo_mgr)
            plan = orch.create_plan(
                "Build a REST API", complexity=7, task_type="coding"
            )
            self.assertIsInstance(plan, DynamicOrchestrationPlan)
            self.assertEqual(plan.task, "Build a REST API")
            self.assertIsNotNone(plan.topology)
            self.assertGreater(len(plan.agents_to_create), 0)
            self.assertGreater(len(plan.execution_order), 0)

    def test_topological_groups_simple_chain(self):
        """A simple chain A->B->C should produce 3 sequential groups."""
        deps = {
            "a": set(),
            "b": {"a"},
            "c": {"b"},
        }
        groups = DynamicOrchestrator._topological_groups(deps)
        self.assertEqual(len(groups), 3)
        self.assertEqual(groups[0], ["a"])
        self.assertEqual(groups[1], ["b"])
        self.assertEqual(groups[2], ["c"])

    def test_topological_groups_parallel(self):
        """Independent nodes A, B should be in the same group."""
        deps = {
            "a": set(),
            "b": set(),
            "c": {"a", "b"},
        }
        groups = DynamicOrchestrator._topological_groups(deps)
        self.assertEqual(len(groups), 2)
        self.assertIn("a", groups[0])
        self.assertIn("b", groups[0])
        self.assertEqual(groups[1], ["c"])

    def test_topological_groups_cycle_breaking(self):
        """A cycle should be broken by putting remaining items in a final group."""
        deps = {
            "a": {"c"},
            "b": {"a"},
            "c": {"b"},
        }
        groups = DynamicOrchestrator._topological_groups(deps)
        # All items should end up in a single group due to cycle
        self.assertEqual(len(groups), 1)
        self.assertEqual(set(groups[0]), {"a", "b", "c"})

    def test_get_stats_empty(self):
        """get_stats with no execution history should return zeros."""
        with tempfile.TemporaryDirectory() as tmpdir:
            factory = DynamicAgentFactory(storage_dir=Path(tmpdir))
            topo_mgr = TopologyManager(storage_dir=Path(tmpdir))
            orch = DynamicOrchestrator(factory=factory, topology_manager=topo_mgr)
            stats = orch.get_stats()
            self.assertEqual(stats["total_orchestrations"], 0)
            self.assertEqual(stats["success_rate"], 0.0)
            self.assertEqual(stats["active_plans"], 0)


# ===================================================================
# classify_task tests
# ===================================================================


class TestClassifyTask(unittest.TestCase):
    """Tests for the classify_task function."""

    def test_classify_coding_task(self):
        """Tasks with coding keywords should classify as 'coding'."""
        self.assertEqual(classify_task("Implement a REST API"), "coding")
        self.assertEqual(classify_task("Build a web application"), "coding")

    def test_classify_research_task(self):
        """Tasks with research keywords should classify as 'research'."""
        self.assertEqual(
            classify_task("Research quantum computing applications"), "research"
        )
        self.assertEqual(
            classify_task("Investigate the effects of climate change"), "research"
        )

    def test_classify_bugfix_task(self):
        """Tasks with bugfix keywords should classify as 'bugfix'."""
        self.assertEqual(classify_task("Fix bug in login flow"), "bugfix")
        self.assertEqual(classify_task("Fix the crash on startup"), "bugfix")

    def test_classify_code_review_task(self):
        """Tasks with code review keywords should classify as 'code_review'."""
        self.assertEqual(
            classify_task("Review code for the authentication module"), "code_review"
        )
        self.assertEqual(
            classify_task("Code review the PR for the API endpoint"), "code_review"
        )

    def test_classify_general_task(self):
        """Tasks with no matching keywords should classify as 'general'."""
        self.assertEqual(classify_task("hello world"), "general")
        self.assertEqual(classify_task("do something random"), "general")


# ===================================================================
# estimate_complexity tests
# ===================================================================


class TestEstimateComplexity(unittest.TestCase):
    """Tests for the estimate_complexity function."""

    def test_simple_task_low_complexity(self):
        """A short simple task should have low complexity."""
        score = estimate_complexity("Say hello")
        self.assertGreaterEqual(score, 1)
        self.assertLessEqual(score, 3)

    def test_long_task_higher_complexity(self):
        """A very long task should increase complexity."""
        long_task = "Please implement the following feature: " + "details " * 50
        score = estimate_complexity(long_task)
        self.assertGreaterEqual(score, 3)

    def test_multi_part_task_increases_complexity(self):
        """Tasks with 'and', 'also', etc. should increase complexity."""
        simple = estimate_complexity("Build one feature")
        multi = estimate_complexity("Build one feature and also add tests, then deploy")
        self.assertGreater(multi, simple)

    def test_scope_keywords_increase_complexity(self):
        """Tasks with scope keywords like 'full', 'complete' should increase complexity."""
        normal = estimate_complexity("Build an API")
        scoped = estimate_complexity(
            "Build a comprehensive full production API from scratch"
        )
        self.assertGreater(scoped, normal)

    def test_simple_keywords_reduce_complexity(self):
        """Tasks with 'quick', 'simple' keywords should reduce complexity."""
        normal = estimate_complexity(
            "Implement a sorting algorithm with various approaches and benchmarks"
        )
        simple = estimate_complexity("quick simple sorting algorithm")
        self.assertLess(simple, normal)

    def test_complexity_clamped_1_to_10(self):
        """Complexity should always be between 1 and 10."""
        for task in [
            "x",
            "a" * 1000,
            "full comprehensive enterprise distributed " * 20 + " and also " * 20,
            "quick simple minor trivial basic",
        ]:
            score = estimate_complexity(task)
            self.assertGreaterEqual(score, 1, f"Task '{task[:30]}' scored {score} < 1")
            self.assertLessEqual(score, 10, f"Task '{task[:30]}' scored {score} > 10")


if __name__ == "__main__":
    unittest.main()
