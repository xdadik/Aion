#!/usr/bin/env python3
"""Comprehensive tests for aion_core/router/ modules."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aion_core.router.estimator import ComplexityEstimator, ReasoningType, TaskComplexity
from aion_core.router.manager import RouterManager
from aion_core.router.optimizer import CostOptimizer, UsageRecord
from aion_core.router.router import Tier, ModelProfile, RoutingDecision, ModelRouter


# ===================================================================
# ComplexityEstimator tests
# ===================================================================


class TestComplexityEstimator(unittest.TestCase):
    """Tests for the ComplexityEstimator class."""

    def test_estimate_returns_task_complexity(self):
        """estimate() should return a TaskComplexity instance."""
        est = ComplexityEstimator()
        result = est.estimate("Hello")
        self.assertIsInstance(result, TaskComplexity)
        self.assertIsInstance(result.score, float)
        self.assertGreaterEqual(result.score, 0.0)
        self.assertLessEqual(result.score, 1.0)
        self.assertIsInstance(result.reasoning_type, ReasoningType)
        self.assertIsInstance(result.estimated_turns, int)
        self.assertIsInstance(result.suggested_model_tier, str)
        self.assertIsInstance(result.factors, dict)

    def test_estimate_simple_task(self):
        """A simple greeting should score low and route to budget tier."""
        est = ComplexityEstimator()
        result = est.estimate("Hello, how are you?")
        self.assertLess(result.score, 0.4)
        self.assertEqual(result.suggested_model_tier, "budget")

    def test_estimate_complex_task(self):
        """A complex coding task should score higher."""
        est = ComplexityEstimator()
        task = (
            "Implement a REST API with authentication using Python, "
            "including unit tests, error handling, and a database schema. "
            "Then deploy it using Docker and set up CI/CD."
        )
        result = est.estimate(task)
        self.assertGreater(result.score, 0.3)


# ===================================================================
# UsageRecord tests
# ===================================================================


class TestUsageRecord(unittest.TestCase):
    """Tests for the UsageRecord dataclass."""

    def test_creation_defaults(self):
        """UsageRecord should store model/provider/tier/tokens/cost with auto timestamp."""
        r = UsageRecord(
            model="gpt-4o",
            provider="openai",
            tier="standard",
            tokens_input=1000,
            tokens_output=500,
            cost=0.075,
        )
        self.assertEqual(r.model, "gpt-4o")
        self.assertEqual(r.provider, "openai")
        self.assertEqual(r.tier, "standard")
        self.assertEqual(r.tokens_input, 1000)
        self.assertEqual(r.tokens_output, 500)
        self.assertAlmostEqual(r.cost, 0.075)
        self.assertIsInstance(r.timestamp, float)


# ===================================================================
# CostOptimizer tests
# ===================================================================


class TestCostOptimizer(unittest.TestCase):
    """Tests for the CostOptimizer class."""

    def setUp(self):
        self.router = ModelRouter()

    def test_creation_with_budget(self):
        """CostOptimizer stores the budget limit."""
        opt = CostOptimizer(self.router, budget_limit=10.0)
        self.assertEqual(opt.get_remaining_budget(), 10.0)

    def test_track_usage(self):
        """track_usage returns a cost and accumulates total spent."""
        opt = CostOptimizer(self.router)
        cost = opt.track_usage("gpt-4o-mini", 1000, 500)
        self.assertIsInstance(cost, float)
        self.assertGreater(cost, 0.0)
        report = opt.get_usage_report()
        self.assertEqual(report["total_calls"], 1)

    def test_estimate_cost(self):
        """estimate_cost returns a float cost estimate."""
        opt = CostOptimizer(self.router)
        cost = opt.estimate_cost("simple task")
        self.assertIsInstance(cost, float)
        self.assertGreater(cost, 0.0)

    def test_get_remaining_budget(self):
        """Remaining budget decreases after tracking usage."""
        opt = CostOptimizer(self.router, budget_limit=1.0)
        remaining_before = opt.get_remaining_budget()
        opt.track_usage("gpt-4o-mini", 1000, 500)
        remaining_after = opt.get_remaining_budget()
        self.assertLess(remaining_after, remaining_before)

    def test_get_usage_report(self):
        """Usage report contains expected keys."""
        opt = CostOptimizer(self.router, budget_limit=5.0)
        opt.track_usage("gpt-4o-mini", 1000, 500)
        report = opt.get_usage_report()
        self.assertIn("period", report)
        self.assertIn("total_cost", report)
        self.assertIn("total_calls", report)
        self.assertIn("by_model", report)
        self.assertIn("by_tier", report)
        self.assertIn("remaining_budget", report)

    def test_suggest_optimizations_empty(self):
        """With no records, suggest_optimizations returns an info tip."""
        opt = CostOptimizer(self.router)
        tips = opt.suggest_optimizations()
        self.assertIsInstance(tips, list)
        self.assertTrue(any(t["type"] == "info" for t in tips))

    def test_reset_budget(self):
        """reset_budget clears records and total spent."""
        opt = CostOptimizer(self.router, budget_limit=1.0)
        opt.track_usage("gpt-4o-mini", 1000, 500)
        opt.reset_budget()
        self.assertAlmostEqual(opt.get_remaining_budget(), 1.0)
        report = opt.get_usage_report()
        self.assertEqual(report["total_calls"], 0)

    def test_save_and_load(self):
        """Optimizer state persists and restores correctly."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "optimizer_state.json")
            opt = CostOptimizer(self.router, budget_limit=50.0, persist_path=path)
            opt.track_usage("gpt-4o-mini", 2000, 1000)
            opt.save()

            # Create a new optimizer and load from same path
            opt2 = CostOptimizer(self.router, budget_limit=100.0, persist_path=path)
            opt2.load(path)
            report = opt2.get_usage_report()
            self.assertEqual(report["total_calls"], 1)


# ===================================================================
# Tier tests
# ===================================================================


class TestTier(unittest.TestCase):
    """Tests for the Tier enum."""

    def test_tier_values(self):
        """Tier enum has the expected string values."""
        self.assertEqual(Tier.BUDGET.value, "budget")
        self.assertEqual(Tier.STANDARD.value, "standard")
        self.assertEqual(Tier.PREMIUM.value, "premium")


# ===================================================================
# ModelProfile tests
# ===================================================================


class TestModelProfile(unittest.TestCase):
    """Tests for the ModelProfile dataclass."""

    def test_creation_defaults(self):
        """ModelProfile stores all fields correctly."""
        p = ModelProfile(
            name="test-model",
            provider="test",
            tier="budget",
            cost_per_1k_input=0.1,
            cost_per_1k_output=0.3,
            max_context=4096,
        )
        self.assertEqual(p.name, "test-model")
        self.assertEqual(p.provider, "test")
        self.assertEqual(p.tier, "budget")
        self.assertEqual(p.cost_per_1k_input, 0.1)
        self.assertEqual(p.cost_per_1k_output, 0.3)
        self.assertEqual(p.max_context, 4096)
        self.assertEqual(p.capabilities, [])
        self.assertAlmostEqual(p.avg_latency_ms, 500.0)

    def test_to_dict(self):
        """to_dict is not a method on ModelProfile, but it's a dataclass — use dataclasses.asdict."""
        from dataclasses import asdict
        p = ModelProfile(
            name="m1", provider="p1", tier="budget",
            cost_per_1k_input=0.1, cost_per_1k_output=0.2, max_context=2048,
        )
        d = asdict(p)
        self.assertEqual(d["name"], "m1")
        self.assertEqual(d["provider"], "p1")
        self.assertEqual(d["tier"], "budget")


# ===================================================================
# RoutingDecision tests
# ===================================================================


class TestRoutingDecision(unittest.TestCase):
    """Tests for the RoutingDecision dataclass."""

    def test_creation_defaults(self):
        """RoutingDecision stores routing result fields."""
        rd = RoutingDecision(
            model="gpt-4o-mini",
            provider="openai",
            tier="budget",
            estimated_cost=0.05,
            reasoning="Low complexity",
        )
        self.assertEqual(rd.model, "gpt-4o-mini")
        self.assertEqual(rd.provider, "openai")
        self.assertEqual(rd.tier, "budget")
        self.assertAlmostEqual(rd.estimated_cost, 0.05)
        self.assertEqual(rd.reasoning, "Low complexity")
        self.assertIsNone(rd.complexity)

    def test_to_dict(self):
        """to_dict returns a dict with expected keys."""
        rd = RoutingDecision(
            model="gpt-4o-mini",
            provider="openai",
            tier="budget",
            estimated_cost=0.05,
            reasoning="Low complexity",
        )
        d = rd.to_dict()
        self.assertIn("model", d)
        self.assertIn("provider", d)
        self.assertIn("tier", d)
        self.assertIn("estimated_cost", d)
        self.assertIn("reasoning", d)
        self.assertIsNone(d["complexity_score"])
        self.assertIsNone(d["reasoning_type"])
        self.assertIsNone(d["estimated_turns"])


# ===================================================================
# ModelRouter tests
# ===================================================================


class TestModelRouter(unittest.TestCase):
    """Tests for the ModelRouter class."""

    def test_router_creation(self):
        """Router initializes with default model profiles."""
        r = ModelRouter()
        models = r.list_models()
        self.assertGreater(len(models), 0)

    def test_add_model(self):
        """add_model registers a new model profile."""
        r = ModelRouter()
        profile = ModelProfile(
            name="custom-model",
            provider="custom",
            tier="budget",
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.02,
            max_context=8192,
        )
        r.add_model(profile)
        names = [m["name"] for m in r.list_models()]
        self.assertIn("custom-model", names)

    def test_remove_model(self):
        """remove_model deletes a model by name."""
        r = ModelRouter()
        # Add a custom model then remove it
        profile = ModelProfile(
            name="to-remove",
            provider="test",
            tier="budget",
            cost_per_1k_input=0.01,
            cost_per_1k_output=0.02,
            max_context=4096,
        )
        r.add_model(profile)
        self.assertTrue(r.remove_model("to-remove"))
        names = [m["name"] for m in r.list_models()]
        self.assertNotIn("to-remove", names)

    def test_list_models(self):
        """list_models returns a non-empty list of dicts."""
        r = ModelRouter()
        models = r.list_models()
        self.assertIsInstance(models, list)
        for m in models:
            self.assertIn("name", m)
            self.assertIn("provider", m)
            self.assertIn("tier", m)

    def test_get_model_for_tier(self):
        """get_model_for_tier returns a ModelProfile for a valid tier."""
        r = ModelRouter()
        model = r.get_model_for_tier("budget")
        self.assertIsInstance(model, ModelProfile)
        self.assertEqual(model.tier, "budget")

    def test_get_routing_stats(self):
        """get_routing_stats returns a dict with expected keys."""
        r = ModelRouter()
        stats = r.get_routing_stats()
        self.assertIn("total_routed", stats)
        self.assertIn("by_tier", stats)
        self.assertIn("percentages", stats)
        self.assertIn("models_available", stats)
        self.assertEqual(stats["total_routed"], 0)

    def test_reset_stats(self):
        """reset_stats zeroes out routing counters."""
        r = ModelRouter()
        r.route("some task")
        self.assertGreater(r.get_routing_stats()["total_routed"], 0)
        r.reset_stats()
        self.assertEqual(r.get_routing_stats()["total_routed"], 0)


# ===================================================================
# RouterManager tests
# ===================================================================


class TestRouterManager(unittest.TestCase):
    """Tests for the RouterManager class."""

    def test_manager_creation(self):
        """RouterManager creates a router and optimizer."""
        rm = RouterManager()
        self.assertIsInstance(rm.router, ModelRouter)
        self.assertIsInstance(rm.optimizer, CostOptimizer)

    def test_route_delegates_to_router(self):
        """route() returns a RoutingDecision."""
        rm = RouterManager()
        decision = rm.route("simple task")
        self.assertIsInstance(decision, RoutingDecision)
        self.assertIn(decision.model, [m["name"] for m in rm.router.list_models()])

    def test_track_records_usage(self):
        """track() records usage and returns a cost."""
        rm = RouterManager()
        cost = rm.track("gpt-4o-mini", 1000, 500)
        self.assertIsInstance(cost, float)
        self.assertGreater(cost, 0.0)
        report = rm.optimizer.get_usage_report()
        self.assertEqual(report["total_calls"], 1)

    def test_get_report(self):
        """get_report returns routing stats, usage report, and optimizations."""
        rm = RouterManager()
        report = rm.get_report()
        self.assertIn("routing_stats", report)
        self.assertIn("usage_report", report)
        self.assertIn("optimizations", report)

    def test_save_and_load(self):
        """save/load persists optimizer state."""
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "rm_state.json")
            rm = RouterManager(config={"persist_path": path})
            rm.track("gpt-4o-mini", 1000, 500)
            rm.save()

            rm2 = RouterManager(config={"persist_path": path})
            rm2.load(path)
            report = rm2.optimizer.get_usage_report()
            self.assertEqual(report["total_calls"], 1)


if __name__ == "__main__":
    unittest.main()
