"""Aion Hand TUI — Rich-based terminal user interface.

A beautiful, interactive terminal UI for the Aion Hand agent framework.
Built on `rich` for rendering and `prompt_toolkit` for input.

Features:
    - Streaming markdown rendering with syntax highlighting
    - Tool-call visualization in collapsible panels
    - Live memory + skills side panels
    - Command palette (/help, /memory, /skills, /tools, /config, /reset, ...)
    - State-aware status bar (idle/thinking/executing/responding)
    - Multi-line input with history
    - Works with zero optional deps (falls back to plain text)

Public API:
    from aion_core.tui import AionTUI
    await AionTUI(agent).run()
"""

from __future__ import annotations

from .app import AionTUI
from .theme import AION_THEME, get_console


def _cli_main() -> None:
    """Console-script entry point: `aion-tui`."""
    import asyncio

    from aion_core.agent.core import AionHand

    async def _run() -> None:
        agent = AionHand()
        await agent.start()
        try:
            await AionTUI(agent).run()
        finally:
            await agent.shutdown()

    asyncio.run(_run())


__all__ = ["AionTUI", "AION_THEME", "get_console"]
