"""Tests for the Computer Use module."""

from __future__ import annotations

import pytest

from aion_core.computer_use import ComputerUse, Point


class TestComputerUseInit:
    """Verify ComputerUse constructs without crashing."""

    def test_init_returns_some_backend(self):
        cu = ComputerUse()
        assert cu is not None
        assert cu.backend in ("pil+pynput", "macos", "linux-x11", "none")

    def test_available_flag(self):
        cu = ComputerUse()
        assert cu.available == (cu.backend != "none")


class TestComputerUseUnavailable:
    """When no backend is available, methods should raise RuntimeError."""

    @pytest.mark.asyncio
    async def test_screenshot_raises_when_unavailable(self):
        cu = ComputerUse(backend="none")
        if cu.available:
            pytest.skip("Backend is available on this host")
        with pytest.raises(RuntimeError, match="screenshot"):
            await cu.screenshot()

    @pytest.mark.asyncio
    async def test_mouse_click_raises_when_unavailable(self):
        cu = ComputerUse(backend="none")
        if cu.available:
            pytest.skip("Backend is available on this host")
        with pytest.raises(RuntimeError, match="mouse"):
            await cu.mouse_click(0, 0)

    @pytest.mark.asyncio
    async def test_keyboard_type_raises_when_unavailable(self):
        cu = ComputerUse(backend="none")
        if cu.available:
            pytest.skip("Backend is available on this host")
        with pytest.raises(RuntimeError, match="keyboard"):
            await cu.keyboard_type("test")


class TestPointDataclass:
    """Point dataclass."""

    def test_point_construction(self):
        p = Point(100, 200)
        assert p.x == 100
        assert p.y == 200
