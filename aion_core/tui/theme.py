"""Shared Rich theme + console for the Aion TUI.

Centralising the theme means every panel, table, and code block uses the
same palette — giving Aion a recognisable visual identity.
"""

from __future__ import annotations

from typing import Any

try:
    from rich.console import Console
    from rich.theme import Theme
    _RICH_AVAILABLE = True
except ImportError:  # pragma: no cover - rich is in our requirements
    _RICH_AVAILABLE = False
    Theme = None  # type: ignore[assignment,misc]
    Console = None  # type: ignore[assignment,misc]


# Palette — "midnight aurora": deep blue base with cyan/magenta accents.
AION_THEME_DICT: dict[str, str] = {
    # Brand
    "aion.brand":      "bold #00E5FF",
    "aion.brand_dim":  "#0891B2",
    # Roles
    "aion.user":       "bold #FBBF24",
    "aion.agent":      "bold #00E5FF",
    "aion.system":     "dim #94A3B8",
    "aion.tool":       "bold #F472B6",
    "aion.error":      "bold #EF4444",
    "aion.success":    "bold #10B981",
    "aion.warning":    "bold #F59E0B",
    # UI chrome
    "aion.panel":      "#1E293B",
    "aion.border":     "#0891B2",
    "aion.muted":      "dim #64748B",
    "aion.tag":        "bold #A78BFA",
    "aion.meta":       "dim italic #94A3B8",
    # Syntax-ish
    "aion.code":       "#F1F5F9 on #0F172A",
    "aion.keyword":    "bold #C084FC",
    "aion.string":     "#86EFAC",
    "aion.number":     "#FCD34D",
}


def _build_theme() -> Any:
    """Return a Rich Theme; or None if rich is unavailable."""
    if not _RICH_AVAILABLE:
        return None
    return Theme(AION_THEME_DICT)


AION_THEME = _build_theme()

# Singleton console — reused across the whole TUI.
_console: Any = None


def get_console() -> Any:
    """Return a process-wide Rich Console (or a stub if rich is missing)."""
    global _console
    if _console is not None:
        return _console

    if _RICH_AVAILABLE:
        _console = Console(theme=AION_THEME, highlight=False, soft_wrap=False)
    else:
        # Minimal stub so the rest of the code can call .print() / .status()
        # without caring whether rich is present.
        class _Stub:
            def print(self, *args: Any, **kwargs: Any) -> None:
                stripped = " ".join(str(a) for a in args)
                if stripped:
                    print(stripped)

            def status(self, _msg: str, **_kw: Any) -> Any:
                class _NullCM:
                    def __enter__(self) -> None: pass
                    def __exit__(self, *_: Any) -> None: pass
                return _NullCM()

            def rule(self, *_a: Any, **_kw: Any) -> None: pass
        _console = _Stub()

    return _console
