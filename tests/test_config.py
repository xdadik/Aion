#!/usr/bin/env python3
"""Comprehensive tests for aion_core/config/manager.py."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aion_core.config.manager import (
    AionConfig,
    ModelConfig,
    SecurityConfig,
    MemoryConfig,
    PipelineConfig,
    GatewayConfig,
    CronConfig,
    MCPConfig,
    env_str,
    env_int,
    env_float,
    env_bool,
    get_aion_home,
    normalize_proxy_env_vars,
    validate_config,
    config_diff,
    merge_configs,
    load_config,
    save_config,
    create_default_config,
    parse_cli_overrides,
    KNOWN_PROVIDERS,
)


# ---------------------------------------------------------------------------
# Helper: isolated env-var patching
# ---------------------------------------------------------------------------

class _EnvPatcher:
    """Context manager that saves/restores os.environ for specific keys."""

    def __init__(self, **overrides):
        self._overrides = overrides
        self._saved: dict = {}

    def __enter__(self):
        for k in list(self._overrides.keys()):
            self._saved[k] = os.environ.pop(k, None)
        for k, v in self._overrides.items():
            if v is not None:
                os.environ[k] = v
        return self

    def __exit__(self, *exc):
        for k in list(self._overrides.keys()):
            os.environ.pop(k, None)
            if self._saved[k] is not None:
                os.environ[k] = self._saved[k]


# ===================================================================
# Tests
# ===================================================================


class TestGetAionHome(unittest.TestCase):
    """Tests for get_aion_home()."""

    def test_returns_path_instance(self):
        with _EnvPatcher(AION_HOME=None, AION_PROFILE=None):
            home = get_aion_home()
            self.assertIsInstance(home, Path)

    def test_default_uses_home_dot_aion_hand(self):
        with _EnvPatcher(AION_HOME=None, AION_PROFILE=None):
            home = get_aion_home()
            self.assertTrue(str(home).endswith(".aion-hand"))

    def test_explicit_aion_home_is_used(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with _EnvPatcher(AION_HOME=tmpdir, AION_PROFILE=None):
                home = get_aion_home()
                self.assertEqual(str(home), str(Path(tmpdir).resolve()))

    def test_profile_creates_subdirectory(self):
        with _EnvPatcher(AION_HOME=None, AION_PROFILE="testprofile"):
            home = get_aion_home()
            self.assertIn("testprofile", str(home))
            self.assertTrue(str(home).replace('\\', '/').endswith("profiles/testprofile"))



class TestEnvHelpers(unittest.TestCase):
    """Tests for env_str, env_int, env_float, env_bool."""

    def test_env_str_default(self):
        with _EnvPatcher(AION_TESTVAL=None):
            self.assertEqual(env_str("TESTVAL"), "")

    def test_env_str_set(self):
        with _EnvPatcher(AION_TESTVAL="hello"):
            self.assertEqual(env_str("TESTVAL"), "hello")

    def test_env_str_custom_prefix(self):
        with _EnvPatcher(MY_TESTVAL="world"):
            self.assertEqual(env_str("TESTVAL", prefix="MY_"), "world")

    def test_env_int_default(self):
        with _EnvPatcher(AION_TESTINT=None):
            self.assertEqual(env_int("TESTINT"), 0)

    def test_env_int_valid(self):
        with _EnvPatcher(AION_TESTINT="42"):
            self.assertEqual(env_int("TESTINT"), 42)

    def test_env_int_invalid_falls_back(self):
        with _EnvPatcher(AION_TESTINT="not-a-number"):
            self.assertEqual(env_int("TESTINT", default=99), 99)

    def test_env_float_default(self):
        with _EnvPatcher(AION_TESTFLOAT=None):
            self.assertEqual(env_float("TESTFLOAT"), 0.0)

    def test_env_float_valid(self):
        with _EnvPatcher(AION_TESTFLOAT="3.14"):
            self.assertAlmostEqual(env_float("TESTFLOAT"), 3.14, places=2)

    def test_env_float_invalid_falls_back(self):
        with _EnvPatcher(AION_TESTFLOAT="nope"):
            self.assertEqual(env_float("TESTFLOAT", default=1.5), 1.5)

    def test_env_bool_default(self):
        with _EnvPatcher(AION_TESTBOOL=None):
            self.assertFalse(env_bool("TESTBOOL"))

    def test_env_bool_truthy_values(self):
        for val in ("1", "true", "yes", "on", "enabled"):
            with _EnvPatcher(AION_TESTBOOL=val):
                self.assertTrue(env_bool("TESTBOOL"), f"Failed for value: {val}")

    def test_env_bool_falsy_values(self):
        for val in ("0", "false", "no", "off", "disabled", "random"):
            with _EnvPatcher(AION_TESTBOOL=val):
                self.assertFalse(env_bool("TESTBOOL"), f"Failed for value: {val}")


class TestModelConfigDefaults(unittest.TestCase):
    """Tests for ModelConfig default values."""

    def test_defaults(self):
        cfg = ModelConfig()
        self.assertEqual(cfg.name, "llama3")
        self.assertEqual(cfg.provider, "ollama")
        self.assertEqual(cfg.api_key, "")
        self.assertAlmostEqual(cfg.temperature, 0.7)
        self.assertEqual(cfg.max_tokens, 4096)
        self.assertEqual(cfg.top_p, 0.9)
        self.assertEqual(cfg.timeout, 120)
        self.assertEqual(cfg.retry_count, 3)

    def test_to_dict_roundtrip(self):
        cfg = ModelConfig(name="gpt-4o", provider="openai", temperature=0.5)
        d = cfg.to_dict()
        restored = ModelConfig.from_dict(d)
        self.assertEqual(restored.name, "gpt-4o")
        self.assertEqual(restored.provider, "openai")
        self.assertAlmostEqual(restored.temperature, 0.5)


class TestSecurityConfigDefaults(unittest.TestCase):
    """Tests for SecurityConfig default values."""

    def test_defaults(self):
        cfg = SecurityConfig()
        self.assertTrue(cfg.enabled)
        self.assertTrue(cfg.sandbox_enabled)
        self.assertEqual(cfg.max_tool_calls_per_turn, 20)
        self.assertTrue(cfg.audit_log)
        self.assertFalse(cfg.require_approval)
        self.assertIn("rm -rf /", cfg.blocked_commands)

    def test_roundtrip(self):
        cfg = SecurityConfig(enabled=False, sandbox_timeout=60)
        d = cfg.to_dict()
        restored = SecurityConfig.from_dict(d)
        self.assertFalse(restored.enabled)
        self.assertEqual(restored.sandbox_timeout, 60)


class TestMemoryConfigDefaults(unittest.TestCase):
    """Tests for MemoryConfig default values."""

    def test_defaults(self):
        cfg = MemoryConfig()
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.working_max, 200)
        self.assertEqual(cfg.session_max, 500)
        self.assertEqual(cfg.episodic_max, 1000)
        self.assertEqual(cfg.semantic_max, 2000)
        self.assertTrue(cfg.fts_enabled)
        self.assertEqual(cfg.persistence_backend, "json")

    def test_roundtrip(self):
        cfg = MemoryConfig(working_max=50, fts_enabled=False)
        d = cfg.to_dict()
        restored = MemoryConfig.from_dict(d)
        self.assertEqual(restored.working_max, 50)
        self.assertFalse(restored.fts_enabled)


class TestAionConfigDefaults(unittest.TestCase):
    """Tests for AionConfig defaults and top-level structure."""

    def test_default_name_and_version(self):
        cfg = AionConfig()
        self.assertEqual(cfg.name, "Aion Hand")
        self.assertEqual(cfg.version, "0.3.0")

    def test_default_log_level(self):
        cfg = AionConfig()
        self.assertEqual(cfg.log_level, "INFO")

    def test_subconfigs_are_default_instances(self):
        cfg = AionConfig()
        self.assertIsInstance(cfg.model, ModelConfig)
        self.assertIsInstance(cfg.security, SecurityConfig)
        self.assertIsInstance(cfg.memory, MemoryConfig)
        self.assertIsInstance(cfg.pipeline, PipelineConfig)
        self.assertIsInstance(cfg.gateway, GatewayConfig)
        self.assertIsInstance(cfg.cron, CronConfig)
        self.assertIsInstance(cfg.mcp, MCPConfig)

    def test_to_dict_returns_dict(self):
        cfg = AionConfig()
        d = cfg.to_dict()
        self.assertIsInstance(d, dict)
        self.assertIn("name", d)
        self.assertIn("model", d)
        self.assertIn("security", d)
        self.assertIn("memory", d)

    def test_from_dict_roundtrip(self):
        cfg = AionConfig(name="Custom", debug=True)
        d = cfg.to_dict()
        restored = AionConfig.from_dict(d)
        self.assertEqual(restored.name, "Custom")
        self.assertTrue(restored.debug)


class TestValidateConfig(unittest.TestCase):
    """Tests for validate_config()."""

    def test_valid_config_returns_empty_list(self):
        cfg = AionConfig()
        cfg.model.provider = "ollama"
        warnings = validate_config(cfg)
        self.assertIsInstance(warnings, list)

    def test_unknown_provider_warning(self):
        cfg = AionConfig()
        cfg.model.provider = "nonexistent_provider"
        warnings = validate_config(cfg)
        self.assertTrue(any("Unknown provider" in w for w in warnings))

    def test_missing_api_key_warning(self):
        cfg = AionConfig()
        cfg.model.provider = "openai"
        cfg.model.api_key = ""
        warnings = validate_config(cfg)
        self.assertTrue(any("API key" in w for w in warnings))

    def test_invalid_log_level_warning(self):
        cfg = AionConfig()
        cfg.log_level = "INVALID"
        warnings = validate_config(cfg)
        self.assertTrue(any("Invalid log_level" in w for w in warnings))

    def test_temperature_out_of_range(self):
        cfg = AionConfig()
        cfg.model.temperature = 5.0
        warnings = validate_config(cfg)
        self.assertTrue(any("temperature" in w for w in warnings))


class TestConfigDiff(unittest.TestCase):
    """Tests for config_diff()."""

    def test_identical_configs_empty_diff(self):
        cfg = AionConfig()
        diff = config_diff(cfg, cfg)
        self.assertEqual(diff, {})

    def test_different_model_name(self):
        a = AionConfig()
        b = AionConfig()
        b.model.name = "gpt-4o"
        diff = config_diff(a, b)
        self.assertIn("model.name", diff)
        self.assertEqual(diff["model.name"], ("llama3", "gpt-4o"))

    def test_different_security_enabled(self):
        a = AionConfig()
        b = AionConfig()
        b.security.enabled = False
        diff = config_diff(a, b)
        self.assertIn("security.enabled", diff)
        self.assertEqual(diff["security.enabled"], (True, False))

    def test_different_log_level(self):
        a = AionConfig()
        b = AionConfig()
        b.log_level = "DEBUG"
        diff = config_diff(a, b)
        self.assertIn("log_level", diff)


class TestMergeConfigs(unittest.TestCase):
    """Tests for merge_configs()."""

    def test_overlay_overrides_base(self):
        base = AionConfig()
        overlay = AionConfig()
        overlay.model.name = "gpt-4o"
        overlay.model.provider = "openai"
        merged = merge_configs(base, overlay)
        self.assertEqual(merged.model.name, "gpt-4o")
        self.assertEqual(merged.model.provider, "openai")

    def test_base_values_preserved_when_overlay_empty(self):
        base = AionConfig()
        overlay = AionConfig()
        merged = merge_configs(base, overlay)
        self.assertEqual(merged.model.name, base.model.name)

    def test_merge_does_not_mutate_base(self):
        base = AionConfig()
        overlay = AionConfig()
        overlay.log_level = "DEBUG"
        merged = merge_configs(base, overlay)
        self.assertEqual(base.log_level, "INFO")  # base unchanged

    def test_merge_with_complex_overlay(self):
        base = AionConfig()
        overlay = AionConfig()
        overlay.model.temperature = 0.1
        overlay.security.enabled = False
        overlay.debug = True
        merged = merge_configs(base, overlay)
        self.assertAlmostEqual(merged.model.temperature, 0.1)
        self.assertFalse(merged.security.enabled)
        self.assertTrue(merged.debug)


class TestNormalizeProxyEnvVars(unittest.TestCase):
    """Tests for normalize_proxy_env_vars()."""

    def test_returns_dict(self):
        result = normalize_proxy_env_vars()
        self.assertIsInstance(result, dict)

    def test_no_proxy_set_returns_empty(self):
        keys_to_remove = ["HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY",
                         "http_proxy", "https_proxy", "no_proxy"]
        saved = {}
        for k in keys_to_remove:
            saved[k] = os.environ.pop(k, None)
        try:
            result = normalize_proxy_env_vars()
            self.assertEqual(result, {})
        finally:
            for k, v in saved.items():
                if v is not None:
                    os.environ[k] = v


class TestLoadConfig(unittest.TestCase):
    """Tests for load_config()."""

    def test_loads_from_file(self):
        cfg_data = {
            "name": "TestConfig",
            "model": {"name": "gpt-4o", "provider": "openai"},
            "log_level": "DEBUG",
        }
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(cfg_data, f)
            tmppath = f.name
        try:
            cfg = load_config(config_file=tmppath)
            self.assertEqual(cfg.name, "TestConfig")
            self.assertEqual(cfg.model.name, "gpt-4o")
            self.assertEqual(cfg.log_level, "DEBUG")
        finally:
            os.unlink(tmppath)

    def test_defaults_when_no_file(self):
        with _EnvPatcher(AION_CONFIG_FILE=None):
            cfg = load_config()
            self.assertIsInstance(cfg, AionConfig)


class TestParseCliOverrides(unittest.TestCase):
    """Tests for parse_cli_overrides()."""

    def test_parse_model_provider(self):
        overrides = parse_cli_overrides(["--model.provider=openai"])
        self.assertEqual(overrides.get("model.provider"), "openai")

    def test_parse_boolean_true(self):
        overrides = parse_cli_overrides(["--debug=true"])
        self.assertTrue(overrides.get("debug"))

    def test_parse_integer(self):
        overrides = parse_cli_overrides(["--model.max_tokens=8192"])
        self.assertEqual(overrides.get("model.max_tokens"), 8192)

    def test_parse_float(self):
        overrides = parse_cli_overrides(["--model.temperature=0.5"])
        self.assertAlmostEqual(overrides.get("model.temperature"), 0.5)

    def test_empty_argv_returns_empty(self):
        overrides = parse_cli_overrides([])
        self.assertEqual(overrides, {})


class TestSaveConfig(unittest.TestCase):
    """Tests for save_config()."""

    def test_save_creates_file(self):
        cfg = AionConfig(name="SaveTest")
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmppath = f.name
        try:
            os.unlink(tmppath)  # remove so save creates it fresh
            result = save_config(cfg, config_file=tmppath)
            self.assertTrue(Path(tmppath).exists())
            with open(tmppath) as f:
                data = json.load(f)
            self.assertEqual(data["name"], "SaveTest")
        finally:
            if os.path.exists(tmppath):
                os.unlink(tmppath)


if __name__ == "__main__":
    unittest.main()
