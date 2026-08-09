"""Tests for context engine and three-tier prompts."""

import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from aion_core.agent.context_engine import (
        ContextWindowManager,
        PruningCompressor,
        ThreeTierPromptBuilder,
        estimate_tokens_for_text,
    )

    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False


@unittest.skipUnless(HAS_MODULE, "context_engine not available")
class TestContextEngine(TestCase):
    def test_estimate_tokens(self):
        tokens = estimate_tokens_for_text("Hello world, this is a test message.")
        self.assertTrue(tokens > 0)

    def test_pruning_compress(self):
        compressor = PruningCompressor()
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"},
        ]
        result = compressor.compress(messages, target_tokens=1000)
        self.assertIsInstance(result, list)

    def test_three_tier_builder_stable(self):
        builder = ThreeTierPromptBuilder()
        stable = builder.build_stable(
            agent_name="TestAgent",
            capabilities=["web_search"],
            guidelines="Be helpful.",
        )
        self.assertIn("TestAgent", stable)

    def test_context_window_manager(self):
        manager = ContextWindowManager(max_context_tokens=4096)
        manager.set_system_prompt("You are a helpful assistant.")
        manager.add_message("user", "Hello!")
        messages = manager.get_messages()
        self.assertTrue(len(messages) >= 2)


if __name__ == "__main__":
    unittest.main()
