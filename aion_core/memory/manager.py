"""
Memory Manager for the Aion Hand AI agent framework.

Combines OpenClaw's MEMORY.md / USER.md file-based persistence,
Hermes Agent's FTS5 full-text search, and a multi-layer memory architecture.

Layers:
    L1 Working   — Current conversation context (short-lived)
    L2 Session   — Current session facts (lives for one session)
    L3 Episodic  — Past conversation summaries
    L4 Semantic  — General facts and knowledge
    L5 Procedural— How-to / process knowledge
    L6 UserProfile— User preferences, patterns, identity
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import sqlite3
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_MEMORY_FILE = "memories.json"
_USER_PROFILE_FILE = "user_profile.json"
_FTS_DB_FILE = "memory_fts.db"
_MEMORY_MD_FILE = "MEMORY.md"
_USER_MD_FILE = "USER.md"
_NUDGE_STATE_FILE = "nudge_state.json"

DEFAULT_NUDGE_INTERVAL_SECONDS = 600  # 10 minutes


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class MemoryLayer(Enum):
    """The six layers of the memory architecture."""

    WORKING = "working"
    SESSION = "session"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    USER_PROFILE = "user_profile"

    def __str__(self) -> str:
        return self.value


DEFAULT_MAX_ENTRIES_PER_LAYER: dict[MemoryLayer, int] = {
    MemoryLayer.WORKING: 200,
    MemoryLayer.SESSION: 500,
    MemoryLayer.EPISODIC: 1000,
    MemoryLayer.SEMANTIC: 2000,
    MemoryLayer.PROCEDURAL: 500,
    MemoryLayer.USER_PROFILE: 200,
}


class NudgeAction(Enum):
    """Actions the nudge system can recommend."""

    CONSOLIDATE = "consolidate"
    SUMMARIZE = "summarize"
    PROMOTE = "promote"
    FORGET = "forget"
    UPDATE_IMPORTANCE = "update_importance"


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

@dataclass
class MemoryEntry:
    """A single memory entry stored in one layer."""

    id: str = field(default_factory=lambda: _make_id())
    content: str = ""
    layer: MemoryLayer = MemoryLayer.WORKING
    tags: list[str] = field(default_factory=list)
    importance: float = 0.5
    created_at: str = field(
        default_factory=lambda: _now_iso(),
    )
    updated_at: str = field(
        default_factory=lambda: _now_iso(),
    )
    access_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    # -- helpers --

    def touch(self) -> None:
        self.updated_at = _now_iso()
        self.access_count += 1

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["layer"] = self.layer.value
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryEntry":
        data = dict(data)  # shallow copy
        data["layer"] = MemoryLayer(data["layer"])
        return cls(**data)


@dataclass
class UserProfile:
    """Accumulated user model (Hermes Honcho–inspired)."""

    name: str = ""
    preferences: dict[str, Any] = field(default_factory=dict)
    patterns: list[str] = field(default_factory=list)
    communication_style: str = ""
    notes: list[str] = field(default_factory=list)
    first_seen: str = field(default_factory=lambda: _now_iso())
    last_seen: str = field(default_factory=lambda: _now_iso())
    interaction_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)

    def touch(self) -> None:
        self.last_seen = _now_iso()
        self.interaction_count += 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "UserProfile":
        return cls(**data)


@dataclass
class NudgeState:
    """State tracking for the memory nudging system."""

    last_nudge_time: float = 0.0
    nudge_count: int = 0
    pending_actions: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NudgeState":
        return cls(**data)


@dataclass
class SearchResult:
    """A single search result with relevance scoring."""

    entry: MemoryEntry
    score: float
    match_highlights: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry.to_dict(),
            "score": self.score,
            "match_highlights": self.match_highlights,
        }


@dataclass
class MemoryStats:
    """Aggregate statistics about memory usage."""

    total_entries: int = 0
    entries_by_layer: dict[str, int] = field(default_factory=dict)
    avg_importance: float = 0.0
    oldest_entry: str | None = None
    newest_entry: str | None = None
    total_access_count: int = 0
    user_profile_filled: bool = False
    nudge_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _make_id() -> str:
    return uuid.uuid4().hex[:12]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_iso(s: str) -> datetime:
    """Parse an ISO-8601 string into a timezone-aware datetime."""
    try:
        return datetime.fromisoformat(s)
    except (ValueError, TypeError):
        return datetime.now(timezone.utc)


def _tokenize_text(text: str) -> list[str]:
    """Lowercase unicode-aware tokenizer for search indexing."""
    return re.findall(r"\w+", text.lower())


def _compute_importance_score(
    entry: MemoryEntry,
    age_hours: float,
    recency_weight: float = 0.3,
    access_weight: float = 0.2,
    explicit_weight: float = 0.5,
) -> float:
    """Blend explicit importance with recency and access frequency."""
    recency = max(0.0, 1.0 - age_hours / 720)  # half-life ≈ 30 days
    access = min(1.0, entry.access_count / 20)
    return (
        explicit_weight * entry.importance
        + recency_weight * recency
        + access_weight * access
    )


# ---------------------------------------------------------------------------
# Storage backend (JSON files + SQLite FTS5)
# ---------------------------------------------------------------------------

class _MemoryStorage:
    """Low-level persistence for memory entries, user profile, and nudge state."""

    def __init__(self, memory_dir: Path, persist: bool = True) -> None:
        self._dir = memory_dir
        self._persist = persist
        self._entries: dict[str, MemoryEntry] = {}
        self._user_profile = UserProfile()
        self._nudge_state = NudgeState()
        self._dirty = False

    # -- load / save --------------------------------------------------------

    def load(self) -> None:
        """Load all persisted data from disk."""
        self._load_entries()
        self._load_user_profile()
        self._load_nudge_state()

    def _load_entries(self) -> None:
        path = self._dir / _MEMORY_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            for entry_data in raw:
                entry = MemoryEntry.from_dict(entry_data)
                self._entries[entry.id] = entry
            logger.info("Loaded %d memory entries from %s", len(self._entries), path)
        except Exception:
            logger.exception("Failed to load memory entries from %s", path)

    def _load_user_profile(self) -> None:
        path = self._dir / _USER_PROFILE_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._user_profile = UserProfile.from_dict(raw)
            logger.info("Loaded user profile from %s", path)
        except Exception:
            logger.exception("Failed to load user profile from %s", path)

    def _load_nudge_state(self) -> None:
        path = self._dir / _NUDGE_STATE_FILE
        if not path.exists():
            return
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            self._nudge_state = NudgeState.from_dict(raw)
            logger.info("Loaded nudge state from %s", path)
        except Exception:
            logger.exception("Failed to load nudge state from %s", path)

    def save(self) -> None:
        """Persist all data to disk."""
        if not self._persist:
            return
        self._dir.mkdir(parents=True, exist_ok=True)
        self._save_entries()
        self._save_user_profile()
        self._save_nudge_state()
        self._dirty = False

    def _save_entries(self) -> None:
        path = self._dir / _MEMORY_FILE
        data = [e.to_dict() for e in self._entries.values()]
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            logger.exception("Failed to save memory entries to %s", path)

    def _save_user_profile(self) -> None:
        path = self._dir / _USER_PROFILE_FILE
        try:
            path.write_text(
                json.dumps(self._user_profile.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save user profile to %s", path)

    def _save_nudge_state(self) -> None:
        path = self._dir / _NUDGE_STATE_FILE
        try:
            path.write_text(
                json.dumps(self._nudge_state.to_dict(), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            logger.exception("Failed to save nudge state to %s", path)

    # -- CRUD --------------------------------------------------------------

    def put(self, entry: MemoryEntry) -> None:
        self._entries[entry.id] = entry
        self._dirty = True

    def get(self, entry_id: str) -> MemoryEntry | None:
        return self._entries.get(entry_id)

    def remove(self, entry_id: str) -> bool:
        if entry_id in self._entries:
            del self._entries[entry_id]
            self._dirty = True
            return True
        return False

    def all_entries(self) -> Sequence[MemoryEntry]:
        return tuple(self._entries.values())

    def entries_by_layer(self, layer: MemoryLayer) -> list[MemoryEntry]:
        return [e for e in self._entries.values() if e.layer == layer]

    # -- user profile -------------------------------------------------------

    @property
    def user_profile(self) -> UserProfile:
        return self._user_profile

    @user_profile.setter
    def user_profile(self, value: UserProfile) -> None:
        self._user_profile = value
        self._dirty = True

    # -- nudge state --------------------------------------------------------

    @property
    def nudge_state(self) -> NudgeState:
        return self._nudge_state

    @nudge_state.setter
    def nudge_state(self, value: NudgeState) -> None:
        self._nudge_state = value
        self._dirty = True


class _FTSIndex:
    """SQLite FTS5 full-text search index over memory entries.

    Falls back to a simple LIKE-based search if FTS5 is not available in the
    SQLite build (rare, but possible on some minimal distributions).
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._fts5_available: bool | None = None
        self._indexed_ids: set[str] = set()

    def initialize(self) -> None:
        """Open (or create) the FTS database and build the virtual table."""
        if self._db_path is not None:
            self._db_path.parent.mkdir(parents=True, exist_ok=True)
            db_uri = str(self._db_path)
        else:
            db_uri = ":memory:"

        self._conn = sqlite3.connect(db_uri)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")

        # Detect FTS5 support
        try:
            self._conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS _ftstest USING fts5(content)")
            self._conn.execute("DROP TABLE IF EXISTS _ftstest")
            self._fts5_available = True
        except Exception:
            self._fts5_available = False

        if self._fts5_available:
            self._conn.execute(
                "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts "
                "USING fts5(entry_id, content, tags, layer)"
            )
        else:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS memory_fts ("
                "entry_id TEXT PRIMARY KEY, content TEXT, tags TEXT, layer TEXT)"
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_fts_content ON memory_fts(content)"
            )

        self._conn.commit()
        logger.info(
            "FTS index initialized (FTS5=%s) at %s",
            self._fts5_available,
            db_uri,
        )

    def rebuild(self, entries: Sequence[MemoryEntry]) -> None:
        """Rebuild the full index from the given entries."""
        if self._conn is None:
            return
        if self._fts5_available:
            self._conn.execute("DELETE FROM memory_fts")
        else:
            self._conn.execute("DELETE FROM memory_fts")

        self._indexed_ids = set()
        for entry in entries:
            self._insert_entry(entry)
        self._conn.commit()

    def index_entry(self, entry: MemoryEntry) -> None:
        """Add or update a single entry in the FTS index."""
        if self._conn is None:
            return
        if entry.id in self._indexed_ids:
            if self._fts5_available:
                self._conn.execute(
                    "DELETE FROM memory_fts WHERE entry_id = ?",
                    (entry.id,),
                )
            else:
                self._conn.execute(
                    "DELETE FROM memory_fts WHERE entry_id = ?",
                    (entry.id,),
                )
        self._insert_entry(entry)
        self._conn.commit()

    def remove_entry(self, entry_id: str) -> None:
        if self._conn is None:
            return
        if self._fts5_available:
            self._conn.execute("DELETE FROM memory_fts WHERE entry_id = ?", (entry_id,))
        else:
            self._conn.execute("DELETE FROM memory_fts WHERE entry_id = ?", (entry_id,))
        self._indexed_ids.discard(entry_id)
        self._conn.commit()

    def _insert_entry(self, entry: MemoryEntry) -> None:
        if self._conn is None:
            return
        tags_str = " ".join(entry.tags)
        if self._fts5_available:
            self._conn.execute(
                "INSERT INTO memory_fts(entry_id, content, tags, layer) VALUES (?, ?, ?, ?)",
                (entry.id, entry.content, tags_str, entry.layer.value),
            )
        else:
            self._conn.execute(
                "INSERT INTO memory_fts(entry_id, content, tags, layer) VALUES (?, ?, ?, ?)",
                (entry.id, entry.content, tags_str, entry.layer.value),
            )
        self._indexed_ids.add(entry.id)

    def search(
        self,
        query: str,
        limit: int = 20,
        layer_filter: str | None = None,
    ) -> list[tuple[str, float, list[str]]]:
        """Search the FTS index.

        Returns a list of ``(entry_id, score, highlighted_terms)`` tuples,
        ordered by descending score.
        """
        if self._conn is None:
            return []

        if not query.strip():
            return []

        tokens = _tokenize_text(query)
        highlights = list(set(tokens))
        rows: list[tuple[str, float, list[str]]] = []

        if self._fts5_available:
            # Build FTS5 query — use quoted phrase for multi-token, OR for
            # single tokens to get broader matching.
            if len(tokens) > 1:
                fts_query = '"' + " ".join(tokens) + '"'
            else:
                fts_query = tokens[0]

            sql = (
                "SELECT entry_id, rank "
                "FROM memory_fts "
                "WHERE memory_fts MATCH ? "
            )
            params: tuple = (fts_query,)

            if layer_filter:
                sql += " AND layer = ?"
                params = (*params, layer_filter)

            sql += " ORDER BY rank LIMIT ?"
            params = (*params, limit)

            try:
                cursor = self._conn.execute(sql, params)
                for row in cursor:
                    entry_id, rank = row
                    # FTS5 rank is negative (lower = better match)
                    score = max(0.0, 1.0 + rank)  # normalise to 0-1+
                    rows.append((entry_id, min(score, 1.0), highlights))
            except Exception:
                logger.exception("FTS5 query failed, falling back")
                rows = self._fallback_search(tokens, highlights, limit, layer_filter)

        else:
            rows = self._fallback_search(tokens, highlights, limit, layer_filter)

        return rows

    def _fallback_search(
        self,
        tokens: list[str],
        highlights: list[str],
        limit: int,
        layer_filter: str | None,
    ) -> list[tuple[str, float, list[str]]]:
        """LIKE-based fallback when FTS5 is not available."""
        if self._conn is None:
            return []

        # Score based on how many tokens match
        rows: list[tuple[str, float, list[str]]] = []
        for token in tokens:
            pattern = f"%{token}%"
            sql = "SELECT entry_id, content FROM memory_fts WHERE content LIKE ?"
            params: tuple = (pattern,)
            if layer_filter:
                sql += " AND layer = ?"
                params = (*params, layer_filter)

            try:
                cursor = self._conn.execute(sql, params)
                for row in cursor:
                    entry_id, content = row
                    matched_tokens = sum(1 for t in tokens if t in content.lower())
                    score = matched_tokens / len(tokens) if tokens else 0.0
                    # Avoid duplicates
                    existing = next((r for r in rows if r[0] == entry_id), None)
                    if existing is not None:
                        idx = rows.index(existing)
                        rows[idx] = (entry_id, max(existing[1], score), highlights)
                    else:
                        rows.append((entry_id, score, highlights))
            except Exception:
                logger.exception("Fallback search failed")

        rows.sort(key=lambda r: r[1], reverse=True)
        return rows[:limit]

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# MEMORY.md / USER.md export helpers
# ---------------------------------------------------------------------------

_LAYER_MD_HEADINGS: dict[MemoryLayer, str] = {
    MemoryLayer.WORKING: "## Working Memory",
    MemoryLayer.SESSION: "## Session Memory",
    MemoryLayer.EPISODIC: "## Episodic Memory (Conversation Summaries)",
    MemoryLayer.SEMANTIC: "## Semantic Memory (Facts & Knowledge)",
    MemoryLayer.PROCEDURAL: "## Procedural Memory (How-To)",
    MemoryLayer.USER_PROFILE: "## User Profile",
}

_LAYER_ORDER = [
    MemoryLayer.USER_PROFILE,
    MemoryLayer.SEMANTIC,
    MemoryLayer.PROCEDURAL,
    MemoryLayer.EPISODIC,
    MemoryLayer.SESSION,
    MemoryLayer.WORKING,
]


def _render_memory_md(entries: Sequence[MemoryEntry], profile: UserProfile) -> str:
    """Render all memories as an OpenClaw-compatible MEMORY.md string."""
    lines: list[str] = []
    lines.append("# MEMORY.md")
    lines.append(f"Last updated: {_now_iso()}")
    lines.append("")

    if profile.name or profile.preferences or profile.communication_style:
        lines.append("## User Profile")
        if profile.name:
            lines.append(f"- **Name**: {profile.name}")
        if profile.communication_style:
            lines.append(f"- **Communication style**: {profile.communication_style}")
        for k, v in profile.preferences.items():
            lines.append(f"- **Preference [{k}]**: {v}")
        for pat in profile.patterns:
            lines.append(f"- **Pattern**: {pat}")
        for note in profile.notes:
            lines.append(f"- **Note**: {note}")
        lines.append("")

    # Group entries by layer, skipping USER_PROFILE (already rendered above)
    for layer in _LAYER_ORDER:
        if layer == MemoryLayer.USER_PROFILE:
            continue
        layer_entries = sorted(
            [e for e in entries if e.layer == layer],
            key=lambda e: e.importance,
            reverse=True,
        )
        if not layer_entries:
            continue

        heading = _LAYER_MD_HEADINGS.get(layer, f"## {layer.value}")
        lines.append(heading)
        for entry in layer_entries:
            tags_str = f"  *(tags: {', '.join(entry.tags)})*" if entry.tags else ""
            imp_str = f"  [importance: {entry.importance:.2f}]"
            lines.append(f"- {entry.content}{tags_str}{imp_str}")
        lines.append("")

    return "\n".join(lines)


def _render_user_md(profile: UserProfile) -> str:
    """Render user profile as an OpenClaw-compatible USER.md string."""
    lines: list[str] = []
    lines.append("# USER.md")
    lines.append(f"Last updated: {profile.last_seen}")
    lines.append("")
    lines.append("## Identity")
    lines.append(f"- **Name**: {profile.name or '(unknown)'}")
    lines.append(f"- **First seen**: {profile.first_seen}")
    lines.append(f"- **Last seen**: {profile.last_seen}")
    lines.append(f"- **Interaction count**: {profile.interaction_count}")
    lines.append("")
    lines.append("## Communication Style")
    lines.append(f"- {profile.communication_style or '(not yet determined)'}")
    lines.append("")
    lines.append("## Preferences")
    for k, v in profile.preferences.items():
        lines.append(f"- **{k}**: {v}")
    lines.append("")
    lines.append("## Observed Patterns")
    for pat in profile.patterns:
        lines.append(f"- {pat}")
    lines.append("")
    lines.append("## Notes")
    for note in profile.notes:
        lines.append(f"- {note}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# MemoryManager — the public API
# ---------------------------------------------------------------------------

class MemoryManager:
    """Central memory manager combining multi-layer storage, FTS5 search,
    memory nudging, and user modelling.
    """

    def __init__(
        self,
        memory_dir: str | Path = ".aion/memory",
        persist: bool = True,
        max_entries: dict[MemoryLayer, int] | None = None,
        nudge_interval: float = DEFAULT_NUDGE_INTERVAL_SECONDS,
    ) -> None:
        self._memory_dir = Path(memory_dir)
        self._persist = persist
        self._max_entries = max_entries or dict(DEFAULT_MAX_ENTRIES_PER_LAYER)
        self._nudge_interval = nudge_interval

        self._storage = _MemoryStorage(self._memory_dir, persist)
        self._fts: _FTSIndex | None = None
        self._initialized = False

    # -- lifecycle ----------------------------------------------------------

    async def initialize(self) -> None:
        """Load existing memories and set up the FTS index."""
        if self._initialized:
            return

        self._storage.load()

        # Initialise FTS index
        fts_path = self._memory_dir / _FTS_DB_FILE if self._persist else None
        self._fts = _FTSIndex(fts_path)
        self._fts.initialize()
        self._fts.rebuild(self._storage.all_entries())

        self._initialized = True
        logger.info(
            "MemoryManager initialized — %d entries, persist=%s",
            len(self._storage.all_entries()),
            self._persist,
        )

    async def shutdown(self) -> None:
        """Persist all data and release resources."""
        if not self._initialized:
            return

        self._storage.save()
        if self._fts is not None:
            self._fts.close()
            self._fts = None
        self._initialized = False
        logger.info("MemoryManager shut down")

    # -- core store ---------------------------------------------------------

    async def store(
        self,
        content: str,
        layer: MemoryLayer = MemoryLayer.WORKING,
        tags: list[str] | None = None,
        importance: float = 0.5,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store a new memory entry.

        Returns the created ``MemoryEntry``.
        """
        self._ensure_initialized()

        entry = MemoryEntry(
            content=content.strip(),
            layer=layer,
            tags=tags or [],
            importance=max(0.0, min(1.0, importance)),
            metadata=metadata or {},
        )
        self._storage.put(entry)
        if self._fts is not None:
            self._fts.index_entry(entry)

        # Enforce per-layer cap — evict lowest-importance entries
        await self._enforce_layer_cap(layer)

        logger.debug(
            "Stored entry %s in layer %s: %.80s…",
            entry.id,
            layer.value,
            entry.content,
        )
        return entry

    async def store_conversation(
        self,
        user_message: str,
        agent_response: str,
        metadata: dict[str, Any] | None = None,
    ) -> list[MemoryEntry]:
        """Parse a user/agent exchange and store fragments into appropriate layers.

        Returns a list of the created ``MemoryEntry`` objects.
        """
        self._ensure_initialized()
        entries: list[MemoryEntry] = []

        # 1. Working memory — full exchange
        exchange_text = f"User: {user_message}\nAgent: {agent_response}"
        e_working = await self.store(
            content=exchange_text,
            layer=MemoryLayer.WORKING,
            tags=["conversation", "exchange"],
            importance=0.6,
            metadata=metadata,
        )
        entries.append(e_working)

        # 2. Session memory — key facts extracted from user message
        #    (heuristic: sentences containing "I", "my", "prefer", "like")
        user_facts = self._extract_facts(user_message)
        for fact in user_facts:
            e_session = await self.store(
                content=fact,
                layer=MemoryLayer.SESSION,
                tags=["user_fact", "session"],
                importance=0.7,
                metadata=metadata,
            )
            entries.append(e_session)

        # 3. Update user profile if fact seems preference-related
        if user_facts:
            self._update_user_profile_from_facts(user_facts)
            self._storage.user_profile.touch()

        return entries

    async def store_episodic_summary(
        self,
        summary: str,
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store a conversation summary in episodic memory."""
        return await self.store(
            content=summary,
            layer=MemoryLayer.EPISODIC,
            tags=tags or ["summary", "episodic"],
            importance=0.65,
            metadata=metadata,
        )

    async def store_knowledge(
        self,
        fact: str,
        tags: list[str] | None = None,
        importance: float = 0.7,
    ) -> MemoryEntry:
        """Store a fact or knowledge item in semantic memory."""
        return await self.store(
            content=fact,
            layer=MemoryLayer.SEMANTIC,
            tags=tags or ["knowledge", "fact"],
            importance=importance,
        )

    async def store_procedure(
        self,
        procedure: str,
        tags: list[str] | None = None,
        importance: float = 0.7,
    ) -> MemoryEntry:
        """Store a procedure / how-to in procedural memory."""
        return await self.store(
            content=procedure,
            layer=MemoryLayer.PROCEDURAL,
            tags=tags or ["procedure", "howto"],
            importance=importance,
        )

    # -- search & retrieval -------------------------------------------------

    async def search(
        self,
        query: str,
        limit: int = 20,
        layer_filter: MemoryLayer | None = None,
    ) -> list[SearchResult]:
        """Full-text search across all memory layers.

        Returns results ordered by relevance score (descending).
        """
        self._ensure_initialized()

        layer_str = layer_filter.value if layer_filter else None
        if self._fts is None:
            return []

        raw_results = self._fts.search(query, limit=limit, layer_filter=layer_str)

        results: list[SearchResult] = []
        for entry_id, score, highlights in raw_results:
            entry = self._storage.get(entry_id)
            if entry is None:
                continue
            # Re-rank using blended importance score
            age_hours = (datetime.now(timezone.utc) - _parse_iso(entry.created_at)).total_seconds() / 3600
            blended = _compute_importance_score(entry, age_hours)
            final_score = 0.6 * score + 0.4 * blended
            results.append(
                SearchResult(entry=entry, score=round(final_score, 4), match_highlights=highlights)
            )

        results.sort(key=lambda r: r.score, reverse=True)
        return results[:limit]

    async def search_relevant(
        self,
        message: str,
        max_tokens: int = 500,
    ) -> str:
        """Retrieve relevant context for the current conversation turn.

        This is the primary method called by the agent loop to inject memory
        context.  Results are concatenated into a single string.

        * ``max_tokens`` is a rough cap (estimated via len / 4).
        """
        self._ensure_initialized()

        results = await self.search(
            query=message,
            limit=15,
            layer_filter=None,
        )

        # Also fetch recent working + session memory
        recent = self._storage.entries_by_layer(MemoryLayer.WORKING)
        recent += self._storage.entries_by_layer(MemoryLayer.SESSION)
        recent.sort(key=lambda e: e.updated_at, reverse=True)
        recent_entries = recent[:10]

        seen_ids = {r.entry.id for r in results}
        for entry in recent_entries:
            if entry.id not in seen_ids:
                results.append(
                    SearchResult(
                        entry=entry,
                        score=0.3,
                        match_highlights=[],
                    )
                )
                seen_ids.add(entry.id)

        results.sort(key=lambda r: r.score, reverse=True)

        # Build context string, respecting token budget
        parts: list[str] = []
        total_chars = 0
        char_budget = max_tokens * 4

        for result in results:
            layer_tag = f"[{result.entry.layer.value}]"
            snippet = f"{layer_tag} {result.entry.content}"
            if total_chars + len(snippet) > char_budget:
                break
            parts.append(snippet)
            result.entry.touch()
            total_chars += len(snippet)

        return "\n".join(parts) if parts else ""

    async def search_content(
        self,
        query: str,
        limit: int = 20,
        layer_filter: MemoryLayer | None = None,
    ) -> list[str]:
        """Convenience method: search memory and return only content strings.

        Unlike ``search()`` which returns :class:`SearchResult` objects,
        this returns a plain list of content strings ordered by relevance,
        making it easy to use in prompts or further processing.

        Args:
            query: Search query string.
            limit: Maximum number of results.
            layer_filter: Optional layer to restrict the search.

        Returns:
            List of content strings ordered by relevance score.
        """
        results = await self.search(
            query=query,
            limit=limit,
            layer_filter=layer_filter,
        )
        return [r.entry.content for r in results]

    # -- nudging system -----------------------------------------------------

    async def nudge(self) -> dict[str, Any] | None:
        """Check if a nudge is due and, if so, return a consolidation prompt.

        Returns ``None`` if no nudge is due, or a dict with suggested actions
        and a human-readable prompt.
        """
        self._ensure_initialized()

        now = time.monotonic()
        state = self._storage.nudge_state

        if now - state.last_nudge_time < self._nudge_interval:
            return None

        state.last_nudge_time = now
        state.nudge_count += 1

        # Analyse what needs attention
        actions: list[dict[str, Any]] = []

        # 1. Check for working memory that could be consolidated to episodic
        working = self._storage.entries_by_layer(MemoryLayer.WORKING)
        if len(working) > self._max_entries.get(MemoryLayer.WORKING, 200) * 0.8:
            actions.append({
                "action": NudgeAction.CONSOLIDATE.value,
                "message": (
                    "Working memory is approaching capacity. "
                    "Consider summarizing recent conversations into episodic memory."
                ),
                "layer": MemoryLayer.WORKING.value,
                "count": len(working),
            })

        # 2. Check for old session memories that could be promoted to semantic
        session = self._storage.entries_by_layer(MemoryLayer.SESSION)
        old_sessions = [
            e for e in session
            if (datetime.now(timezone.utc) - _parse_iso(e.updated_at)).total_seconds() > 3600
        ]
        if old_sessions:
            actions.append({
                "action": NudgeAction.PROMOTE.value,
                "message": (
                    f"{len(old_sessions)} session memories are over an hour old. "
                    "Promote important ones to semantic memory."
                ),
                "layer": MemoryLayer.SESSION.value,
                "count": len(old_sessions),
            })

        # 3. Suggest importance re-evaluation for untouched entries
        all_entries = self._storage.all_entries()
        untouched = [e for e in all_entries if e.access_count == 0]
        if len(untouched) > 50:
            actions.append({
                "action": NudgeAction.UPDATE_IMPORTANCE.value,
                "message": (
                    f"{len(untouched)} entries have never been accessed. "
                    "Consider updating their importance or forgetting irrelevant ones."
                ),
                "count": len(untouched),
            })

        if not actions:
            return None

        state.pending_actions = actions
        prompt_lines = [
            "🧠 **Memory Nudge** — it's time to organize your memories:",
            "",
        ]
        for i, action in enumerate(actions, 1):
            prompt_lines.append(f"{i}. {action['message']}")

        nudge_result = {
            "prompt": "\n".join(prompt_lines),
            "actions": actions,
            "nudge_count": state.nudge_count,
        }

        logger.info("Memory nudge triggered (nudge #%d): %d actions", state.nudge_count, len(actions))
        return nudge_result

    async def mark_nudge_action_done(self, action_index: int) -> None:
        """Remove a pending nudge action after it has been handled."""
        state = self._storage.nudge_state
        if 0 <= action_index < len(state.pending_actions):
            state.pending_actions.pop(action_index)

    # -- export -------------------------------------------------------------

    async def export_memory_md(self) -> str:
        """Export all memories as an OpenClaw-compatible MEMORY.md string."""
        self._ensure_initialized()
        return _render_memory_md(self._storage.all_entries(), self._storage.user_profile)

    async def export_user_md(self) -> str:
        """Export the user profile as an OpenClaw-compatible USER.md string."""
        self._ensure_initialized()
        return _render_user_md(self._storage.user_profile)

    async def save_exports_to_disk(self) -> None:
        """Write MEMORY.md and USER.md files to the memory directory."""
        self._ensure_initialized()
        if not self._persist:
            return

        self._memory_dir.mkdir(parents=True, exist_ok=True)

        memory_md = await self.export_memory_md()
        (self._memory_dir / _MEMORY_MD_FILE).write_text(memory_md, encoding="utf-8")

        user_md = await self.export_user_md()
        (self._memory_dir / _USER_MD_FILE).write_text(user_md, encoding="utf-8")

        logger.info("Exported MEMORY.md and USER.md to %s", self._memory_dir)

    # -- stats --------------------------------------------------------------

    def _compute_stats(self) -> MemoryStats:
        """Internal implementation for computing memory statistics (sync)."""
        self._ensure_initialized()

        entries = self._storage.all_entries()
        total = len(entries)
        by_layer: dict[str, int] = {}
        imp_sum = 0.0
        access_sum = 0
        oldest: datetime | None = None
        newest: datetime | None = None

        for e in entries:
            by_layer[e.layer.value] = by_layer.get(e.layer.value, 0) + 1
            imp_sum += e.importance
            access_sum += e.access_count
            created = _parse_iso(e.created_at)
            if oldest is None or created < oldest:
                oldest = created
            if newest is None or created > newest:
                newest = created

        # Ensure all layers are present
        for layer in MemoryLayer:
            by_layer.setdefault(layer.value, 0)

        return MemoryStats(
            total_entries=total,
            entries_by_layer=by_layer,
            avg_importance=round(imp_sum / total, 3) if total else 0.0,
            oldest_entry=oldest.isoformat() if oldest else None,
            newest_entry=newest.isoformat() if newest else None,
            total_access_count=access_sum,
            user_profile_filled=bool(
                self._storage.user_profile.name
                or self._storage.user_profile.preferences
            ),
            nudge_count=self._storage.nudge_state.nudge_count,
        )

    def get_stats_sync(self) -> MemoryStats:
        """Synchronous convenience method to get memory statistics.

        Safe to call from sync contexts (e.g. DynamicManager.get_stats()).
        For async contexts, prefer ``await get_stats()`` which forwards here.
        """
        return self._compute_stats()

    async def get_stats(self) -> MemoryStats:
        """Compute and return memory statistics.

        This is the async interface. Internally it delegates to the sync
        ``_compute_stats`` implementation, so it is safe to call from both
        sync (via ``get_stats_sync``) and async (via ``await get_stats``)
        contexts.
        """
        return self._compute_stats()

    # -- cleanup ------------------------------------------------------------

    async def cleanup(
        self,
        max_age_days: float = 90.0,
        min_importance: float = 0.1,
    ) -> int:
        """Remove old and low-importance memories.

        Returns the number of entries removed.
        """
        self._ensure_initialized()

        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(days=max_age_days)
        removed = 0

        entries = list(self._storage.all_entries())
        for entry in entries:
            created = _parse_iso(entry.created_at)
            if created < cutoff and entry.importance < min_importance:
                self._storage.remove(entry.id)
                if self._fts is not None:
                    self._fts.remove_entry(entry.id)
                removed += 1

        if removed:
            logger.info(
                "Cleaned up %d entries (max_age=%d days, min_importance=%.2f)",
                removed,
                int(max_age_days),
                min_importance,
            )
            self._storage.save()

        return removed

    # -- user profile -------------------------------------------------------

    @property
    def user_profile(self) -> UserProfile:
        """Access the accumulated user profile (read-only)."""
        return self._storage.user_profile

    async def update_user_profile(
        self,
        name: str | None = None,
        preferences: dict[str, Any] | None = None,
        communication_style: str | None = None,
        patterns: list[str] | None = None,
        notes: list[str] | None = None,
    ) -> None:
        """Update fields of the user profile."""
        self._ensure_initialized()

        profile = self._storage.user_profile
        if name is not None:
            profile.name = name
        if preferences is not None:
            profile.preferences.update(preferences)
        if communication_style is not None:
            profile.communication_style = communication_style
        if patterns is not None:
            existing = set(profile.patterns)
            for p in patterns:
                if p not in existing:
                    profile.patterns.append(p)
        if notes is not None:
            existing = set(profile.notes)
            for n in notes:
                if n not in existing:
                    profile.notes.append(n)

        profile.touch()

        # Also store key profile data as a USER_PROFILE layer entry
        profile_summary = f"Name: {profile.name}. Style: {profile.communication_style}"
        if profile.preferences:
            profile_summary += f". Preferences: {json.dumps(profile.preferences)}"
        await self.store(
            content=profile_summary,
            layer=MemoryLayer.USER_PROFILE,
            tags=["user_profile", "auto"],
            importance=0.8,
        )

    # -- layer management ---------------------------------------------------

    async def promote_entry(
        self,
        entry_id: str,
        target_layer: MemoryLayer,
    ) -> MemoryEntry | None:
        """Move an entry from its current layer to a new one.

        Returns the updated entry, or ``None`` if not found.
        """
        self._ensure_initialized()

        entry = self._storage.get(entry_id)
        if entry is None:
            return None

        old_layer = entry.layer
        entry.layer = target_layer
        entry.touch()
        entry.tags.append(f"promoted_from_{old_layer.value}")

        self._storage.put(entry)
        if self._fts is not None:
            self._fts.index_entry(entry)

        logger.info(
            "Promoted entry %s from %s to %s",
            entry_id,
            old_layer.value,
            target_layer.value,
        )
        return entry

    async def forget(self, entry_id: str) -> bool:
        """Permanently remove a memory entry."""
        self._ensure_initialized()

        result = self._storage.remove(entry_id)
        if result and self._fts is not None:
            self._fts.remove_entry(entry_id)
            logger.info("Forgot entry %s", entry_id)
        return result

    # -- internals ----------------------------------------------------------

    def _ensure_initialized(self) -> None:
        if not self._initialized:
            raise RuntimeError(
                "MemoryManager is not initialized. Call await initialize() first."
            )

    async def _enforce_layer_cap(self, layer: MemoryLayer) -> None:
        """Evict lowest-importance entries when a layer exceeds its cap."""
        cap = self._max_entries.get(layer, 1000)
        entries = self._storage.entries_by_layer(layer)
        if len(entries) <= cap:
            return

        # Sort by blended importance (ascending) — evict the worst
        now = datetime.now(timezone.utc)
        scored: list[tuple[float, MemoryEntry]] = []
        for entry in entries:
            age_hours = (now - _parse_iso(entry.created_at)).total_seconds() / 3600
            blended = _compute_importance_score(entry, age_hours)
            scored.append((blended, entry))
        scored.sort(key=lambda t: t[0])

        excess = len(entries) - cap
        for score, entry in scored[:excess]:
            self._storage.remove(entry.id)
            if self._fts is not None:
                self._fts.remove_entry(entry.id)

        logger.debug(
            "Evicted %d entries from layer %s (cap=%d)",
            excess,
            layer.value,
            cap,
        )

    def _extract_facts(self, text: str) -> list[str]:
        """Heuristic extraction of preference/fact statements from user text."""
        sentences = re.split(r'[.!?;\n]+', text)
        facts: list[str] = []
        # Patterns that suggest preferences or personal facts
        preference_patterns = re.compile(
            r"\b(i\s+(?:prefer|like|love|hate|don'?t\s+like|always|never|usually|tend)\b"
            r"|(?:my\s+(?:name|favorite|preferred|go-to)))",
            re.IGNORECASE,
        )
        for sentence in sentences:
            s = sentence.strip()
            if len(s) < 5:
                continue
            if preference_patterns.search(s):
                facts.append(s)
        return facts

    def _update_user_profile_from_facts(self, facts: list[str]) -> None:
        """Heuristic update of user profile from extracted facts."""
        profile = self._storage.user_profile
        for fact in facts:
            # Extract name if present
            name_match = re.search(
                r"(?:my name is|i'm|i am|call me)\s+(\w[\w\s]*?)\s*[.!?;]?$",
                fact,
                re.IGNORECASE,
            )
            if name_match:
                profile.name = name_match.group(1).strip()

            # Extract preferences
            pref_match = re.search(
                r"i\s+(?:prefer|like|love)\s+(.+)",
                fact,
                re.IGNORECASE,
            )
            if pref_match:
                key = f"likes_{pref_match.group(1).strip().lower()}"
                profile.preferences[key] = fact

            # Add to patterns if not duplicate
            fact_lower = fact.lower()
            if not any(p.lower() == fact_lower for p in profile.patterns):
                profile.patterns.append(fact)
