"""Tests for subagent lifecycle management."""
import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from aion_core.agent.subagent_lifecycle import (
        DelegationContext,
        SubagentLaunchRequest,
        SubagentLifecycle,
        SubagentState,
    )
    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False


@unittest.skipUnless(HAS_MODULE, "subagent_lifecycle not available")
class TestSubagentLifecycle(TestCase):
    def setUp(self):
        self.lifecycle = SubagentLifecycle(runner_fn=lambda req: None)

    def test_launch_creates_handle(self):
        req = SubagentLaunchRequest(goal="Test task", context="Test context")
        handle = self.lifecycle.launch(req)
        self.assertIsNotNone(handle)
        self.assertIsNotNone(handle.subagent_id)

    def test_cancel(self):
        req = SubagentLaunchRequest(goal="Test")
        handle = self.lifecycle.launch(req)
        result = self.lifecycle.cancel(handle.subagent_id)
        self.assertTrue(result)

    def test_list_active(self):
        req = SubagentLaunchRequest(goal="Test")
        self.lifecycle.launch(req)
        active = self.lifecycle.list_active()
        self.assertTrue(len(active) >= 1)

    def test_cleanup(self):
        req = SubagentLaunchRequest(goal="Test")
        handle = self.lifecycle.launch(req)
        result = self.lifecycle.cleanup(handle.subagent_id)
        self.assertTrue(result)

    def test_get_stats(self):
        stats = self.lifecycle.get_stats()
        self.assertIsInstance(stats, dict)

    def test_delegation_context(self):
        ctx = DelegationContext()
        self.assertFalse(ctx.is_delegated())
        token = ctx.set_delegation("test-123")
        self.assertTrue(ctx.is_delegated())
        self.assertEqual(ctx.get_current_delegation(), "test-123")
        ctx.reset(token)
        self.assertFalse(ctx.is_delegated())

    def test_states_enum(self):
        state_names = [s.name for s in SubagentState]
        self.assertIn("PENDING", state_names)
        self.assertIn("RUNNING", state_names)
        self.assertIn("SUCCEEDED", state_names)
        self.assertIn("FAILED", state_names)
        self.assertIn("CANCELLED", state_names)


if __name__ == "__main__":
    unittest.main()
