"""Tests for the Plugins module."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest

from aion_core.plugins import PluginLoader, PluginRegistry


class TestPluginRegistry:
    """PluginRegistry dataclass."""

    def test_default_empty(self):
        reg = PluginRegistry()
        assert reg.tools == []
        assert reg.skill_paths == []
        assert reg.personas == []
        assert reg.providers == []
        assert reg.cron_tasks == []
        assert reg.system_prompt_extensions == []

    def test_add_methods(self):
        reg = PluginRegistry()
        reg.add_tool({"name": "fake_tool"})
        reg.add_skill_path("/tmp/fake.md")
        reg.add_persona({"name": "fake"})
        reg.add_provider(object)
        reg.add_cron_task("0 9 * * *", lambda: None)
        reg.add_system_prompt_extension("be nice")
        assert len(reg.tools) == 1
        assert len(reg.skill_paths) == 1
        assert len(reg.personas) == 1
        assert len(reg.providers) == 1
        assert len(reg.cron_tasks) == 1
        assert len(reg.system_prompt_extensions) == 1

    def test_stats(self):
        reg = PluginRegistry()
        reg.add_tool(object())
        reg.add_tool(object())
        reg.add_skill_path("/x")
        stats = reg.stats()
        assert stats["tools"] == 2
        assert stats["skills"] == 1


class TestPluginLoader:
    """PluginLoader discovers .py files."""

    def test_no_plugins_dir_doesnt_crash(self, tmp_path):
        loader = PluginLoader(plugins_dir=tmp_path / "does-not-exist")
        # Should not raise, just return empty registry
        reg = loader.discover()
        assert reg.stats()["tools"] == 0

    def test_loads_simple_plugin(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        plugin_file = plugins_dir / "my_plugin.py"
        plugin_file.write_text(dedent("""
            from aion_core.plugins import PluginRegistry

            def register(reg: PluginRegistry) -> None:
                reg.add_tool({"name": "test_tool"})
                reg.add_system_prompt_extension("Be helpful.")
        """))
        loader = PluginLoader(plugins_dir=plugins_dir)
        loader.discover()
        assert "my_plugin" in loader.loaded_plugins
        assert loader.failed_plugins == []
        assert len(loader.registry.tools) == 1
        assert len(loader.registry.system_prompt_extensions) == 1

    def test_failed_plugin_doesnt_block_others(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        # Plugin that raises on import
        (plugins_dir / "broken.py").write_text("raise ImportError('boom')")
        # Plugin that works
        (plugins_dir / "good.py").write_text(dedent("""
            from aion_core.plugins import PluginRegistry
            def register(reg: PluginRegistry) -> None:
                reg.add_tool("ok")
        """))
        loader = PluginLoader(plugins_dir=plugins_dir)
        loader.discover()
        assert "good" in loader.loaded_plugins
        assert any(name == "broken" for name, _ in loader.failed_plugins)

    def test_plugin_without_register_warns(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        (plugins_dir / "no_register.py").write_text("# no register function here")
        loader = PluginLoader(plugins_dir=plugins_dir)
        loader.discover()
        # Should not be in loaded, but also not a hard failure
        assert "no_register" not in loader.loaded_plugins

    def test_loads_plugin_package(self, tmp_path):
        plugins_dir = tmp_path / "plugins"
        plugins_dir.mkdir()
        # Create a package (directory with __init__.py)
        pkg_dir = plugins_dir / "mypkg"
        pkg_dir.mkdir()
        (pkg_dir / "__init__.py").write_text(dedent("""
            from aion_core.plugins import PluginRegistry
            def register(reg: PluginRegistry) -> None:
                reg.add_tool("from_package")
        """))
        loader = PluginLoader(plugins_dir=plugins_dir)
        loader.discover()
        assert "mypkg" in loader.loaded_plugins
        assert len(loader.registry.tools) == 1


class TestApplyToAgent:
    """apply_to_agent integrates registry into an AionHand agent."""

    def test_apply_to_agent_without_subsystems_doesnt_crash(self, tmp_path):
        from unittest.mock import MagicMock
        loader = PluginLoader(plugins_dir=tmp_path / "no-plugins")
        loader.discover()
        agent = MagicMock()
        agent.tool_registry = None
        agent.skill_engine = None
        agent.provider_factory = None
        agent.cron_scheduler = None
        agent.config = None
        # Should not raise even with all subsystems missing
        result = loader.apply_to_agent(agent)
        assert isinstance(result, dict)
        assert result["tools"] == 0
