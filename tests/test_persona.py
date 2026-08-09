"""Tests for the Aion Persona system (SOUL.md)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from aion_core.persona import (
    BUILTIN_PERSONA_DIR,
    Persona,
    PersonaManager,
    parse_persona_markdown,
)


class TestPersonaDataclass:
    """Persona dataclass behaviour."""

    def test_to_system_prompt_includes_body(self):
        p = Persona(name="x", body_markdown="Hello world")
        prompt = p.to_system_prompt()
        assert "Hello world" in prompt

    def test_to_system_prompt_includes_display_name(self):
        p = Persona(name="x", display_name="Big X", body_markdown="body")
        prompt = p.to_system_prompt()
        assert "Big X" in prompt

    def test_to_markdown_roundtrip(self):
        p = Persona(
            name="test",
            display_name="Test Persona",
            description="A test",
            tags=["a", "b"],
            body_markdown="# Body\n\nSome content.",
        )
        text = p.to_markdown()
        parsed = parse_persona_markdown(text)
        assert parsed.name == "test"
        assert parsed.display_name == "Test Persona"
        assert parsed.description == "A test"
        assert "a" in parsed.tags and "b" in parsed.tags
        assert "Some content." in parsed.body_markdown

    def test_to_dict(self):
        p = Persona(name="x", display_name="X", tags=["t"])
        d = p.to_dict()
        assert d["name"] == "x"
        assert d["display_name"] == "X"
        assert d["tags"] == ["t"]


class TestParsePersonaMarkdown:
    """Frontmatter parsing."""

    def test_parse_with_yaml_frontmatter(self):
        text = """---
name: foo
display_name: Foo Bar
description: A foo
tags: [x, y]
---

# Foo Body

Some content."""
        p = parse_persona_markdown(text)
        assert p.name == "foo"
        assert p.display_name == "Foo Bar"
        assert "x" in p.tags
        assert "Foo Body" in p.body_markdown

    def test_parse_without_frontmatter(self):
        text = "# Just a body\n\nNo frontmatter."
        p = parse_persona_markdown(text)
        assert p.name == "unnamed"
        assert "Just a body" in p.body_markdown

    def test_parse_with_source_path(self):
        p = parse_persona_markdown("---\nname: x\n---\nbody", source_path="/tmp/x.md")
        assert p.source_path == "/tmp/x.md"


class TestPersonaManager:
    """PersonaManager file operations."""

    def test_list_includes_builtins(self):
        mgr = PersonaManager()  # uses default dirs
        names = mgr.list_personas()
        # Built-in templates should always be discoverable
        assert "default" in names
        assert "researcher" in names
        assert "coder" in names

    def test_load_builtin_default(self):
        mgr = PersonaManager()
        p = mgr.load("default")
        assert p is not None
        assert p.name == "default"
        assert "Aion" in p.body_markdown or "Aion" in p.display_name

    def test_load_nonexistent_returns_none(self):
        mgr = PersonaManager()
        assert mgr.load("does-not-exist-xyz") is None

    def test_persona_exists(self):
        mgr = PersonaManager()
        assert mgr.persona_exists("default") is True
        assert mgr.persona_exists("nope-nada-12345") is False

    def test_save_and_delete_user_persona(self, tmp_path: Path):
        mgr = PersonaManager(user_dir=tmp_path, builtin_dir=BUILTIN_PERSONA_DIR)
        p = Persona(name="mytemp", body_markdown="hello")
        path = mgr.save(p)
        assert path.is_file()
        assert mgr.persona_exists("mytemp")

        # User persona should shadow nothing (no builtin conflict) and be loadable
        loaded = mgr.load("mytemp")
        assert loaded is not None
        assert loaded.body_markdown == "hello"

        # Delete
        assert mgr.delete("mytemp") is True
        assert not mgr.persona_exists("mytemp")

    def test_delete_builtin_returns_false(self, tmp_path: Path):
        # Cannot delete a built-in (it lives in the package, not user_dir)
        mgr = PersonaManager(user_dir=tmp_path, builtin_dir=BUILTIN_PERSONA_DIR)
        assert mgr.delete("default") is False

    def test_user_persona_shadows_builtin(self, tmp_path: Path):
        mgr = PersonaManager(user_dir=tmp_path, builtin_dir=BUILTIN_PERSONA_DIR)
        # Save a user "default" that overrides the builtin
        p = Persona(name="default", body_markdown="USER OVERRIDE")
        mgr.save(p)
        loaded = mgr.load("default")
        assert loaded is not None
        assert "USER OVERRIDE" in loaded.body_markdown

    def test_set_and_get_active(self, tmp_path: Path):
        mgr = PersonaManager(user_dir=tmp_path, builtin_dir=BUILTIN_PERSONA_DIR)
        # Default active is "default"
        assert mgr.get_active_name() == "default"

        # Switch to researcher
        assert mgr.set_active("researcher") is True
        assert mgr.get_active_name() == "researcher"

        # Switching to nonexistent fails
        assert mgr.set_active("nope-xyz") is False

    def test_apply_to_agent_calls_set_system_prompt(self, tmp_path: Path):
        mgr = PersonaManager(user_dir=tmp_path, builtin_dir=BUILTIN_PERSONA_DIR)
        agent = MagicMock_with_set_system_prompt()
        ok = mgr.apply_to_agent(agent, "researcher")
        assert ok is True
        assert agent.set_system_prompt.called
        prompt = agent.set_system_prompt.call_args[0][0]
        assert "Deep Researcher" in prompt or "researcher" in prompt.lower()


# Helper to avoid importing unittest.mock at top-level clutter
def MagicMock_with_set_system_prompt():
    from unittest.mock import MagicMock

    m = MagicMock()
    m.set_system_prompt = MagicMock()
    m.config = MagicMock()
    m.config.default_model = None
    m.config.default_temperature = None
    return m
