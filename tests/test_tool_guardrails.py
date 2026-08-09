"""Tests for tool guardrails and concurrent execution."""

import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from aion_core.agent.tool_guardrails import (
        ConcurrentToolExecutor,
        ToolGuardrailDecision,
        ToolGuardrails,
    )

    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False


@unittest.skipUnless(HAS_MODULE, "tool_guardrails not available")
class TestToolGuardrails(TestCase):
    def setUp(self):
        self.guardrails = ToolGuardrails()
        self.executor = ConcurrentToolExecutor()

    def test_first_call_proceeds(self):
        decision = self.guardrails.observe(
            "read_file", {"path": "/tmp/test.txt"}, "success"
        )
        self.assertEqual(decision, ToolGuardrailDecision.PROCEED)

    def test_get_stats(self):
        self.guardrails.observe("web_search", {"query": "test"}, "success")
        stats = self.guardrails.get_stats()
        self.assertIsInstance(stats, dict)

    def test_reset(self):
        self.guardrails.observe("web_search", {"query": "test"}, "error")
        self.guardrails.reset()
        stats = self.guardrails.get_stats()
        self.assertEqual(stats.get("total_calls", 0), 0)

    def test_is_dangerous_tool(self):
        self.assertTrue(self.executor._is_dangerous_tool("shell_exec"))
        self.assertTrue(self.executor._is_dangerous_tool("write_file"))
        self.assertFalse(self.executor._is_dangerous_tool("web_search"))
        self.assertFalse(self.executor._is_dangerous_tool("read_file"))


if __name__ == "__main__":
    unittest.main()
