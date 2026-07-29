"""Tests for Mixture-of-Agents (MoA) loop."""
import os
import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from aion_core.agent.moa_loop import PIIFilter, MixtureOfAgents, MOAConfig
    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False


class TestPIIFilter(TestCase):
    def setUp(self):
        if HAS_MODULE:
            self.filter = PIIFilter()

    @unittest.skipUnless(HAS_MODULE, "moa_loop not available")
    def test_scrub_email(self):
        result = self.filter.scrub("Contact me at john@example.com")
        self.assertNotIn("john@example.com", result)

    @unittest.skipUnless(HAS_MODULE, "moa_loop not available")
    def test_detect_email(self):
        findings = self.filter.detect("Contact me at john@example.com")
        self.assertTrue(len(findings) >= 1)

    @unittest.skipUnless(HAS_MODULE, "moa_loop not available")
    def test_scrub_no_false_positives(self):
        result = self.filter.scrub("The quick brown fox jumps over the lazy dog.")
        self.assertIn("quick", result)
        self.assertIn("fox", result)


class TestMixtureOfAgents(TestCase):
    @unittest.skipUnless(HAS_MODULE, "moa_loop not available")
    def test_config_defaults(self):
        config = MOAConfig(advisors=[], aggregator="gpt-4")
        self.assertEqual(config.aggregator, "gpt-4")

    @unittest.skipUnless(HAS_MODULE, "moa_loop not available")
    def test_get_stats(self):
        # MixtureOfAgents requires advisor_fn - use a dummy
        moa = MixtureOfAgents(advisor_fn=lambda p: "dummy")
        stats = moa.get_stats()
        self.assertIsInstance(stats, dict)


if __name__ == "__main__":
    unittest.main()
