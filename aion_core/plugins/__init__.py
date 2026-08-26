"""Aion Hand Plugins — runtime-loadable tools, skills, personas.

Users can drop Python files or packages into ~/.aion-hand/plugins/ and
Aion will auto-load them at startup. Each plugin can register:
    - tools (Tool instances)
    - skills (SKILL.md paths or Skill objects)
    - personas (Persona objects)
    - providers (Provider subclasses)
    - cron tasks (ScheduledTask instances)

A plugin is any module with a top-level function `register(registry)`
that takes a PluginRegistry and adds its contributions.

Example plugin file: ~/.aion-hand/plugins/my_plugin.py

    from aion_core.plugins import PluginRegistry

    def register(reg: PluginRegistry) -> None:
        reg.add_tool(my_tool)
        reg.add_skill_path("/path/to/skill.md")
        reg.add_persona(my_persona)
        reg.add_cron_task("0 9 * * *", my_morning_task)

Usage (in agent startup):
    from aion_core.plugins import PluginLoader
    loader = PluginLoader()
    loader.discover()  # scans ~/.aion-hand/plugins/
    loader.apply_to_agent(agent)
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger("aion_hand.plugins")


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

@dataclass
class PluginRegistry:
    """Collects contributions from one or more plugins."""
    tools: list[Any] = field(default_factory=list)
    skill_paths: list[Path] = field(default_factory=list)
    personas: list[Any] = field(default_factory=list)
    providers: list[Any] = field(default_factory=list)
    cron_tasks: list[tuple[str, Callable]] = field(default_factory=list)
    system_prompt_extensions: list[str] = field(default_factory=list)
    metadata: dict[str, dict[str, Any]] = field(default_factory=dict)

    def add_tool(self, tool: Any) -> None:
        self.tools.append(tool)

    def add_skill_path(self, path: Path | str) -> None:
        self.skill_paths.append(Path(path))

    def add_persona(self, persona: Any) -> None:
        self.personas.append(persona)

    def add_provider(self, provider_cls: Any) -> None:
        self.providers.append(provider_cls)

    def add_cron_task(self, schedule: str, fn: Callable) -> None:
        self.cron_tasks.append((schedule, fn))

    def add_system_prompt_extension(self, text: str) -> None:
        self.system_prompt_extensions.append(text)

    def stats(self) -> dict[str, int]:
        return {
            "tools": len(self.tools),
            "skills": len(self.skill_paths),
            "personas": len(self.personas),
            "providers": len(self.providers),
            "cron_tasks": len(self.cron_tasks),
        }


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

class PluginLoader:
    """Discovers and loads plugins from a directory.

    A plugin is a Python file (*.py) or package (directory with __init__.py)
    in the plugins directory. The plugin must define a top-level function
    called `register(registry: PluginRegistry) -> None`.

    Plugins that fail to load are logged but don't prevent other plugins
    from loading.
    """

    def __init__(self, plugins_dir: Path | str | None = None) -> None:
        self.plugins_dir = Path(plugins_dir) if plugins_dir else Path.home() / ".aion-hand" / "plugins"
        self.registry = PluginRegistry()
        self._loaded: list[str] = []
        self._failed: list[tuple[str, str]] = []

    @property
    def loaded_plugins(self) -> list[str]:
        return list(self._loaded)

    @property
    def failed_plugins(self) -> list[tuple[str, str]]:
        return list(self._failed)

    def discover(self) -> PluginRegistry:
        """Scan plugins_dir and load every plugin found."""
        if not self.plugins_dir.is_dir():
            logger.info(f"Plugins dir does not exist: {self.plugins_dir}")
            return self.registry

        # Find plugin files
        plugin_files = sorted(self.plugins_dir.glob("*.py"))
        plugin_files = [p for p in plugin_files if p.stem != "__init__"]

        # Find plugin packages
        plugin_packages = []
        for d in sorted(self.plugins_dir.iterdir()):
            if d.is_dir() and (d / "__init__.py").is_file():
                plugin_packages.append(d)

        for pf in plugin_files:
            self._load_file(pf)
        for pkg in plugin_packages:
            self._load_package(pkg)

        logger.info(
            f"Loaded {len(self._loaded)} plugins, "
            f"{len(self._failed)} failed, "
            f"registry: {self.registry.stats()}"
        )
        return self.registry

    def _load_file(self, path: Path) -> None:
        """Load a single .py plugin file."""
        mod_name = f"aion_plugin_{path.stem}"
        try:
            spec = importlib.util.spec_from_file_location(mod_name, path)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot create spec for {path}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            self._call_register(mod, path.stem)
        except Exception as exc:  # noqa: BLE001
            self._failed.append((path.stem, str(exc)))
            logger.exception(f"Plugin {path.stem} failed to load: {exc}")

    def _load_package(self, pkg_dir: Path) -> None:
        """Load a plugin package (directory with __init__.py)."""
        mod_name = f"aion_plugin_pkg_{pkg_dir.stem}"
        try:
            init_file = pkg_dir / "__init__.py"
            spec = importlib.util.spec_from_file_location(mod_name, init_file)
            if spec is None or spec.loader is None:
                raise ImportError(f"Cannot create spec for {init_file}")
            mod = importlib.util.module_from_spec(spec)
            sys.modules[mod_name] = mod
            spec.loader.exec_module(mod)
            self._call_register(mod, pkg_dir.stem)
        except Exception as exc:  # noqa: BLE001
            self._failed.append((pkg_dir.stem, str(exc)))
            logger.exception(f"Plugin package {pkg_dir.stem} failed: {exc}")

    def _call_register(self, mod: Any, name: str) -> None:
        """Call the plugin's register() function if present."""
        register_fn = getattr(mod, "register", None)
        if not callable(register_fn):
            logger.warning(f"Plugin {name} has no register() function — skipping")
            return
        register_fn(self.registry)
        self._loaded.append(name)
        logger.info(f"Plugin loaded: {name}")

    # ------------------------------------------------------------------
    #  Apply to agent
    # ------------------------------------------------------------------

    def apply_to_agent(self, agent: Any) -> dict[str, int]:
        """Apply all registry contributions to an AionHand agent.

        Returns a dict of how many of each contribution type were applied.
        """
        applied = {"tools": 0, "skills": 0, "personas": 0, "providers": 0, "cron_tasks": 0, "prompt_extensions": 0}

        # Tools
        tr = getattr(agent, "tool_registry", None)
        if tr is not None:
            for tool in self.registry.tools:
                try:
                    if hasattr(tr, "register"):
                        tr.register(tool)
                    elif hasattr(tr, "add_tool"):
                        tr.add_tool(tool)
                    applied["tools"] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Could not apply tool: {exc}")

        # Skills
        se = getattr(agent, "skill_engine", None)
        if se is not None:
            for path in self.registry.skill_paths:
                try:
                    if hasattr(se, "load_skill_file"):
                        se.load_skill_file(path)
                    elif hasattr(se, "add_skill_path"):
                        se.add_skill_path(path)
                    else:
                        # Fallback: read + create
                        text = path.read_text(encoding="utf-8")
                        from aion_core.skills.engine import Skill
                        skill = Skill.from_markdown(text)
                        se._skills[skill.skill_id] = skill
                    applied["skills"] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Could not apply skill {path}: {exc}")

        # Personas (load them into the persona manager's user dir)
        if self.registry.personas:
            try:
                from aion_core.persona import PersonaManager
                mgr = PersonaManager()
                for p in self.registry.personas:
                    mgr.save(p)
                applied["personas"] = len(self.registry.personas)
            except Exception as exc:  # noqa: BLE001
                logger.warning(f"Could not apply personas: {exc}")

        # Providers
        pf = getattr(agent, "provider_factory", None)
        if pf is not None:
            for prov_cls in self.registry.providers:
                try:
                    name = getattr(prov_cls, "name", prov_cls.__name__.lower().replace("provider", ""))
                    if hasattr(pf, "register"):
                        pf.register(name, prov_cls)
                    applied["providers"] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Could not apply provider: {exc}")

        # Cron tasks
        cs = getattr(agent, "cron_scheduler", None)
        if cs is not None:
            for schedule, fn in self.registry.cron_tasks:
                try:
                    if hasattr(cs, "add_task"):
                        cs.add_task(schedule, fn)
                    elif hasattr(cs, "schedule"):
                        cs.schedule(schedule, fn)
                    applied["cron_tasks"] += 1
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"Could not apply cron task: {exc}")

        # System prompt extensions
        if self.registry.system_prompt_extensions:
            cfg = getattr(agent, "config", None)
            if cfg is not None:
                existing = getattr(cfg, "system_prompt", "") or ""
                cfg.system_prompt = existing + "\n\n" + "\n\n".join(self.registry.system_prompt_extensions)
                applied["prompt_extensions"] = len(self.registry.system_prompt_extensions)

        return applied


__all__ = ["PluginRegistry", "PluginLoader"]
