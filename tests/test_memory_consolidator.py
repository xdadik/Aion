"""Tests for the Memory Consolidator module."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aion_core.memory.consolidator import ConsolidatorConfig, MemoryConsolidator


class TestConsolidatorConfig:
    """ConsolidatorConfig dataclass."""

    def test_defaults(self, tmp_path):
        cfg = ConsolidatorConfig()
        assert cfg.enabled is True
        assert cfg.interval_seconds == 300.0
        assert cfg.max_memory_entries > 0

    def test_custom_paths(self, tmp_path):
        cfg = ConsolidatorConfig(
            memory_md_path=tmp_path / "M.md",
            user_md_path=tmp_path / "U.md",
        )
        assert cfg.memory_md_path == tmp_path / "M.md"


class TestConsolidatorInit:
    """Verify MemoryConsolidator constructs."""

    def test_init_without_memory_manager(self):
        c = MemoryConsolidator()
        assert c.memory_manager is None
        assert c.skill_engine is None
        assert c._task is None

    def test_start_when_disabled_does_nothing(self):
        cfg = ConsolidatorConfig(enabled=False)
        c = MemoryConsolidator(config=cfg)
        c.start()
        assert c._task is None

    def test_start_when_enabled_creates_task(self):
        # Use very short interval so the loop runs at least once
        # start() must be called from within an event loop
        async def _go():
            cfg = ConsolidatorConfig(enabled=True, interval_seconds=0.05)
            c = MemoryConsolidator(config=cfg)
            c.start()
            assert c._task is not None
            await c.stop()
        asyncio.run(_go())


class TestConsolidatorStats:
    """stats() returns a useful dict."""

    def test_stats_initial(self):
        c = MemoryConsolidator()
        s = c.stats()
        assert s["enabled"] is True
        assert s["running"] is False
        assert s["runs_completed"] == 0
        assert s["facts_promoted"] == 0
        assert s["user_attrs_learned"] == 0
        assert s["skills_created"] == 0


class TestUserFactExtraction:
    """The consolidator should detect user-attribute patterns."""

    @pytest.mark.asyncio
    async def test_extract_user_name(self, tmp_path):
        # Set up a fake memory_manager that returns items
        mock_mm = MagicMock()
        mock_mm.recent_working = MagicMock(return_value=[
            {"content": "Hi, my name is Alice", "timestamp": "2026-01-01T00:00:00Z"},
        ])
        # Make store() not crash
        mock_mm.store = MagicMock()

        cfg = ConsolidatorConfig(
            memory_md_path=tmp_path / "M.md",
            user_md_path=tmp_path / "U.md",
        )
        c = MemoryConsolidator(memory_manager=mock_mm, config=cfg)
        await c._consolidate_once()
        # Should have called store at least once for the user attribute
        assert mock_mm.store.called
        # Verify the call included "Alice"
        all_calls_text = str(mock_mm.store.call_args_list)
        assert "Alice" in all_calls_text

    @pytest.mark.asyncio
    async def test_extract_user_location(self, tmp_path):
        mock_mm = MagicMock()
        mock_mm.recent_working = MagicMock(return_value=[
            {"content": "I live in Berlin and I work as a designer"},
        ])
        mock_mm.store = MagicMock()

        cfg = ConsolidatorConfig(
            memory_md_path=tmp_path / "M.md",
            user_md_path=tmp_path / "U.md",
        )
        c = MemoryConsolidator(memory_manager=mock_mm, config=cfg)
        await c._consolidate_once()
        all_calls_text = str(mock_mm.store.call_args_list)
        assert "Berlin" in all_calls_text

    @pytest.mark.asyncio
    async def test_update_memory_md_writes_file(self, tmp_path):
        mock_mm = MagicMock()
        mock_mm.recent_working = MagicMock(return_value=[
            {"content": "This is a long enough memory content to be saved.", "timestamp": "2026-01-01T00:00:00Z"},
        ])
        mock_mm.store = MagicMock()

        mem_path = tmp_path / "M.md"
        cfg = ConsolidatorConfig(memory_md_path=mem_path, user_md_path=tmp_path / "U.md")
        c = MemoryConsolidator(memory_manager=mock_mm, config=cfg)
        await c._consolidate_once()
        assert mem_path.is_file()
        content = mem_path.read_text()
        assert "long enough memory" in content

    @pytest.mark.asyncio
    async def test_no_items_skips_silently(self, tmp_path):
        mock_mm = MagicMock()
        mock_mm.recent_working = MagicMock(return_value=[])
        cfg = ConsolidatorConfig(memory_md_path=tmp_path / "M.md", user_md_path=tmp_path / "U.md")
        c = MemoryConsolidator(memory_manager=mock_mm, config=cfg)
        # Should not raise
        await c._consolidate_once()
        # And no MEMORY.md should be written (no items)
        assert not (tmp_path / "M.md").is_file()


class TestConsolidatorLifecycle:
    """Start / stop / cancel."""

    @pytest.mark.asyncio
    async def test_start_stop_completes_cleanly(self):
        cfg = ConsolidatorConfig(enabled=True, interval_seconds=0.1)
        c = MemoryConsolidator(config=cfg)
        c.start()
        await asyncio.sleep(0.05)
        await c.stop()
        assert c._task is None
