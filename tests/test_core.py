"""Tests for aion_core.agent.core — AgentConfig and AgentState."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from aion_core.agent.core import AgentConfig, AgentState


class TestAgentConfigDefaults(unittest.TestCase):
    """Verify default values of AgentConfig."""

    def test_default_config_values(self):
        cfg = AgentConfig()
        self.assertEqual(cfg.name, "Aion Hand")
        self.assertEqual(cfg.version, "0.3.0")
        self.assertEqual(cfg.default_provider, "openai")
        self.assertEqual(cfg.default_model, "gpt-4o")
        self.assertEqual(cfg.max_turns, 50)
        self.assertEqual(cfg.max_tokens, 4096)
        self.assertAlmostEqual(cfg.temperature, 0.7)
        self.assertEqual(cfg.context_window, 128000)
        self.assertTrue(cfg.memory_enabled)
        self.assertTrue(cfg.tools_enabled)
        self.assertTrue(cfg.streaming_enabled)

    def test_config_paths_are_path_objects(self):
        cfg = AgentConfig()
        for attr in ("home_dir", "data_dir", "memory_dir",
                      "skills_dir", "tools_dir", "logs_dir", "config_file"):
            with self.subTest(attr=attr):
                val = getattr(cfg, attr)
                self.assertIsInstance(val, Path)


class TestAgentConfigSaveLoad(unittest.TestCase):
    """Round-trip save / load using a temporary directory."""

    def test_config_save_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            cfg = AgentConfig(name="TestBot", default_model="gpt-4-turbo")
            cfg.config_file = Path(tmp) / "config.json"
            cfg.home_dir = Path(tmp)
            cfg.data_dir = Path(tmp) / "data"

            cfg.save()

            loaded = AgentConfig.load(path=cfg.config_file)
            self.assertEqual(loaded.name, "TestBot")
            self.assertEqual(loaded.default_model, "gpt-4-turbo")
            self.assertEqual(loaded.version, cfg.version)
            # Paths should be Path objects after loading
            self.assertIsInstance(loaded.home_dir, Path)
            self.assertIsInstance(loaded.data_dir, Path)


class TestAgentStateEnum(unittest.TestCase):
    """Verify all expected AgentState enum members exist."""

    EXPECTED = [
        "UNINITIALIZED", "INITIALIZING", "IDLE", "THINKING",
        "EXECUTING", "WAITING", "RESPONDING", "ERROR",
        "SHUTTING_DOWN", "SHUTDOWN",
    ]

    def test_agent_state_enum(self):
        for name in self.EXPECTED:
            with self.subTest(name=name):
                self.assertTrue(hasattr(AgentState, name))
                member = getattr(AgentState, name)
                self.assertIsInstance(member, AgentState)

    def test_state_values_are_strings(self):
        for member in AgentState:
            self.assertIsInstance(member.value, str)


if __name__ == "__main__":
    unittest.main()
