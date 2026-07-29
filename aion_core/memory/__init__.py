"""
aion_core.memory — Multi-layer memory manager for the Aion Hand AI agent.

Provides persistent, searchable memory with a 6-layer architecture, FTS5
full-text search, memory nudging, and OpenClaw-compatible MEMORY.md / USER.md
export.

Quick start::

    from aion_core.memory import MemoryManager, MemoryLayer, MemoryEntry

    mm = MemoryManager(memory_dir=".aion/memory")
    await mm.initialize()

    await mm.store("User prefers dark mode", layer=MemoryLayer.SEMANTIC, importance=0.8)
    results = await mm.search("dark mode")
    context = await mm.search_relevant("Can you change the theme?")

    await mm.shutdown()
"""

from .manager import (
    DEFAULT_MAX_ENTRIES_PER_LAYER,
    DEFAULT_NUDGE_INTERVAL_SECONDS,
    MemoryEntry,
    MemoryLayer,
    MemoryManager,
    MemoryStats,
    NudgeAction,
    NudgeState,
    SearchResult,
    UserProfile,
)

__all__ = [
    "DEFAULT_MAX_ENTRIES_PER_LAYER",
    "DEFAULT_NUDGE_INTERVAL_SECONDS",
    "MemoryEntry",
    "MemoryLayer",
    "MemoryManager",
    "MemoryStats",
    "NudgeAction",
    "NudgeState",
    "SearchResult",
    "UserProfile",
]
