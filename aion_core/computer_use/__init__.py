"""Aion Hand Computer Use — screen, mouse, keyboard automation.

Provides cross-platform (best-effort) computer-use primitives:
    - screen capture
    - mouse move / click / drag
    - keyboard type / press / hotkey

Backends (tried in order):
    1. PIL.ImageGrab + pynput (cross-platform)
    2. macOS `screencapture` + AppleScript (mac-only)
    3. Linux `xdotool` + `scrot` (Linux X11)
    4. None — functions raise RuntimeError

This module is intentionally lazy: nothing imports until first use,
so `import aion_core.computer_use` never fails even on a headless server.

Usage:
    from aion_core.computer_use import ComputerUse
    cu = ComputerUse()
    img_path = await cu.screenshot()
    await cu.mouse_click(100, 200)
    await cu.keyboard_type("Hello")
"""

from __future__ import annotations

import asyncio
import shutil
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = __import__("logging").getLogger("aion_hand.computer_use")


# ---------------------------------------------------------------------------
# Backend detection
# ---------------------------------------------------------------------------

def _detect_backend() -> str:
    """Return 'pil+pynput', 'macos', 'linux-x11', or 'none'."""
    try:
        from PIL import ImageGrab  # type: ignore[import-not-found]  # noqa: F401
        import pynput  # type: ignore[import-not-found]  # noqa: F401
        return "pil+pynput"
    except ImportError:
        pass
    if sys.platform == "darwin" and shutil.which("screencapture"):
        return "macos"
    if sys.platform.startswith("linux") and shutil.which("xdotool") and shutil.which("scrot"):
        return "linux-x11"
    return "none"


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class Point:
    x: int
    y: int


# ---------------------------------------------------------------------------
# ComputerUse
# ---------------------------------------------------------------------------

class ComputerUse:
    """Screen / mouse / keyboard automation, multi-backend."""

    def __init__(self, *, backend: str | None = None) -> None:
        self._backend = backend or _detect_backend()
        self._kb: Any = None
        self._mouse: Any = None
        logger.info(f"ComputerUse init: backend={self._backend}")

    @property
    def backend(self) -> str:
        return self._backend

    @property
    def available(self) -> bool:
        return self._backend != "none"

    # ------------------------------------------------------------------
    #  Screen
    # ------------------------------------------------------------------

    async def screenshot(self, output_path: Path | str | None = None) -> Path:
        """Capture the screen and save as PNG. Returns the file path."""
        if output_path is None:
            output_path = Path(tempfile.gettempdir()) / f"aion_screen_{asyncio.get_event_loop().time():.0f}.png"
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if self._backend == "pil+pynput":
            def _grab() -> None:
                from PIL import ImageGrab  # type: ignore[import-not-found]
                img = ImageGrab.grab()
                img.save(str(output_path))
            await asyncio.get_event_loop().run_in_executor(None, _grab)
            return output_path

        if self._backend == "macos":
            proc = await asyncio.create_subprocess_exec(
                "screencapture", "-x", str(output_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return output_path

        if self._backend == "linux-x11":
            proc = await asyncio.create_subprocess_exec(
                "scrot", str(output_path),
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await proc.wait()
            return output_path

        raise RuntimeError("No screenshot backend available. Install: pip install pillow pynput")

    async def screen_size(self) -> Point:
        """Return the screen resolution as a Point(width, height)."""
        if self._backend == "pil+pynput":
            def _size() -> Point:
                from PIL import ImageGrab  # type: ignore[import-not-found]
                # ImageGrab.grab() returns full screen — its size is screen size
                img = ImageGrab.grab()
                return Point(img.width, img.height)
            return await asyncio.get_event_loop().run_in_executor(None, _size)
        # Fallback: parse `xdpyinfo` on Linux, `system_profiler` on macOS — omitted for brevity
        raise RuntimeError("Cannot determine screen size on this backend")

    # ------------------------------------------------------------------
    #  Mouse
    # ------------------------------------------------------------------

    async def mouse_move(self, x: int, y: int) -> None:
        """Move the mouse cursor to (x, y)."""
        if self._backend == "pil+pynput":
            def _move() -> None:
                from pynput.mouse import Controller  # type: ignore[import-not-found]
                if self._mouse is None:
                    self._mouse = Controller()
                self._mouse.position = (x, y)
            await asyncio.get_event_loop().run_in_executor(None, _move)
            return
        if self._backend == "macos" or self._backend == "linux-x11":
            # Both platforms have `cliclick` (mac via brew) or `xdotool` (linux)
            tool = "xdotool" if self._backend == "linux-x11" else None
            if tool and shutil.which(tool):
                await asyncio.create_subprocess_exec(tool, "mousemove", str(x), str(y))
                return
        raise RuntimeError("No mouse backend available")

    async def mouse_click(self, x: int | None = None, y: int | None = None, *, button: str = "left") -> None:
        """Click at (x, y), or at the current cursor position if x/y are None."""
        if x is not None and y is not None:
            await self.mouse_move(x, y)
        if self._backend == "pil+pynput":
            def _click() -> None:
                from pynput.mouse import Controller, Button  # type: ignore[import-not-found]
                if self._mouse is None:
                    self._mouse = Controller()
                btn = Button.left if button == "left" else Button.right if button == "right" else Button.middle
                self._mouse.click(btn)
            await asyncio.get_event_loop().run_in_executor(None, _click)
            return
        if self._backend == "linux-x11" and shutil.which("xdotool"):
            await asyncio.create_subprocess_exec("xdotool", "click", "1" if button == "left" else "3")
            return
        raise RuntimeError("No mouse backend available")

    async def mouse_double_click(self, x: int | None = None, y: int | None = None) -> None:
        """Double-click at (x, y) or current position."""
        await self.mouse_click(x, y)
        await asyncio.sleep(0.05)
        await self.mouse_click()

    # ------------------------------------------------------------------
    #  Keyboard
    # ------------------------------------------------------------------

    async def keyboard_type(self, text: str) -> None:
        """Type a string (no special keys)."""
        if self._backend == "pil+pynput":
            def _type() -> None:
                from pynput.keyboard import Controller  # type: ignore[import-not-found]
                if self._kb is None:
                    self._kb = Controller()
                self._kb.type(text)
            await asyncio.get_event_loop().run_in_executor(None, _type)
            return
        if self._backend == "linux-x11" and shutil.which("xdotool"):
            await asyncio.create_subprocess_exec("xdotool", "type", "--", text)
            return
        raise RuntimeError("No keyboard backend available")

    async def keyboard_press(self, key: str) -> None:
        """Press a single key (e.g. 'enter', 'escape', 'tab')."""
        if self._backend == "pil+pynput":
            def _press() -> None:
                from pynput.keyboard import Controller, Key  # type: ignore[import-not-found]
                if self._kb is None:
                    self._kb = Controller()
                # Map common names
                special = {
                    "enter": Key.enter, "return": Key.enter,
                    "tab": Key.tab, "escape": Key.esc, "esc": Key.esc,
                    "space": Key.space, "backspace": Key.backspace,
                    "delete": Key.delete, "up": Key.up, "down": Key.down,
                    "left": Key.left, "right": Key.right,
                    "shift": Key.shift, "ctrl": Key.ctrl, "cmd": Key.cmd, "alt": Key.alt,
                }
                k = special.get(key.lower())
                if k is not None:
                    self._kb.press(k)
                    self._kb.release(k)
                else:
                    # Single char
                    self._kb.press(key)
                    self._kb.release(key)
            await asyncio.get_event_loop().run_in_executor(None, _press)
            return
        if self._backend == "linux-x11" and shutil.which("xdotool"):
            await asyncio.create_subprocess_exec("xdotool", "key", key)
            return
        raise RuntimeError("No keyboard backend available")

    async def keyboard_hotkey(self, *keys: str) -> None:
        """Press a hotkey combination, e.g. keyboard_hotkey('ctrl', 'c')."""
        if self._backend == "pil+pynput":
            def _hotkey() -> None:
                from pynput.keyboard import Controller, Key  # type: ignore[import-not-found]
                if self._kb is None:
                    self._kb = Controller()
                special = {
                    "enter": Key.enter, "tab": Key.tab, "escape": Key.esc, "esc": Key.esc,
                    "space": Key.space, "backspace": Key.backspace, "delete": Key.delete,
                    "up": Key.up, "down": Key.down, "left": Key.left, "right": Key.right,
                    "shift": Key.shift, "ctrl": Key.ctrl, "cmd": Key.cmd, "alt": Key.alt,
                }
                mapped = [special.get(k.lower(), k) for k in keys]
                for k in mapped:
                    self._kb.press(k)
                for k in reversed(mapped):
                    self._kb.release(k)
            await asyncio.get_event_loop().run_in_executor(None, _hotkey)
            return
        if self._backend == "linux-x11" and shutil.which("xdotool"):
            await asyncio.create_subprocess_exec("xdotool", "key", "+".join(keys))
            return
        raise RuntimeError("No keyboard backend available")


__all__ = ["ComputerUse", "Point"]
