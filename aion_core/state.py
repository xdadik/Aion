"""Session state persistence with full-text search across conversations.

Ports Hermes Agent's flagship ``hermes_state.py`` concept to Aion with a
zero-dependency stdlib implementation:

* Every conversation turn (user + assistant + tool usage) is persisted to a
  SQLite database at ``~/.aion-hand/data/state.db``.
* An FTS5 virtual table indexes message content so the agent — and the LLM
  via the ``session_search`` tool — can recall anything from any past
  conversation in ~20 ms without an LLM call.
* Sessions carry platform metadata (cli / telegram / discord / web / api)
  so gateway conversations become searchable too.

The store is deliberately independent from the memory system: memory holds
distilled facts, the session store holds the raw conversation history.
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("aion_hand.state")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    platform TEXT NOT NULL DEFAULT 'cli',
    title TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    message_count INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    tools_used TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id);
CREATE INDEX IF NOT EXISTS idx_messages_created ON messages(created_at);
"""


class SessionStore:
    """SQLite-backed session archive with FTS5 full-text search.

    Usage::

        store = SessionStore()          # defaults to ~/.aion-hand/data/state.db
        store.initialize()
        sid = store.create_session(platform="cli")
        store.record_message(sid, "user", "hello")
        store.record_message(sid, "assistant", "hi!", tools_used=["calculator"])
        hits = store.search("hello")    # FTS5 across ALL sessions
    """

    def __init__(self, db_path: str | Path | None = None) -> None:
        if db_path is None:
            db_path = Path.home() / ".aion-hand" / "data" / "state.db"
        self._db_path = Path(db_path)
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._fts5_available = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Create the database, schema and FTS index. Idempotent."""
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)

            # FTS5 availability probe (mirrors memory/manager.py pattern)
            try:
                self._conn.execute(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS _fts_probe USING fts5(x)"
                )
                self._conn.execute("DROP TABLE _fts_probe")
                self._fts5_available = True
            except sqlite3.OperationalError:
                self._fts5_available = False
                logger.warning("FTS5 unavailable; session search falls back to LIKE")

            if self._fts5_available:
                self._conn.executescript(
                    """
                    CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts
                    USING fts5(
                        message_id,
                        session_id,
                        content,
                        tokenize='unicode61'
                    );
                    """
                )
                # Backfill index for pre-existing rows
                row = self._conn.execute(
                    "SELECT COUNT(*) AS n FROM messages_fts"
                ).fetchone()
                if row and row["n"] == 0:
                    self._conn.execute(
                        """
                        INSERT INTO messages_fts (message_id, session_id, content)
                        SELECT id, session_id, content FROM messages
                        """
                    )
            self._conn.commit()
            logger.info(
                "SessionStore initialized at %s (FTS5=%s)",
                self._db_path,
                self._fts5_available,
            )

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.commit()
                self._conn.close()
                self._conn = None

    def _require_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self.initialize()
        assert self._conn is not None
        return self._conn

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------

    def create_session(
        self, platform: str = "cli", title: str = ""
    ) -> str:
        """Create a new session row and return its id."""
        sid = uuid.uuid4().hex[:12]
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._require_conn()
            conn.execute(
                "INSERT INTO sessions (id, platform, title, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?)",
                (sid, platform, title or "", now, now),
            )
            conn.commit()
        return sid

    def touch_session(self, session_id: str, title: str | None = None) -> None:
        """Bump updated_at (+ optionally set title) for a session."""
        now = datetime.now(UTC).isoformat()
        with self._lock:
            conn = self._require_conn()
            if title:
                conn.execute(
                    "UPDATE sessions SET updated_at=?, title=? WHERE id=?",
                    (now, title[:120], session_id),
                )
            else:
                conn.execute(
                    "UPDATE sessions SET updated_at=? WHERE id=?",
                    (now, session_id),
                )
            conn.commit()

    def list_sessions(self, limit: int = 20, platform: str | None = None) -> list[dict]:
        """Most recently active sessions."""
        conn = self._require_conn()
        if platform:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE platform=? "
                "ORDER BY updated_at DESC LIMIT ?",
                (platform, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM sessions ORDER BY updated_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_messages(self, session_id: str, limit: int = 100) -> list[dict]:
        """All messages of one session, oldest first."""
        conn = self._require_conn()
        rows = conn.execute(
            "SELECT * FROM (SELECT * FROM messages WHERE session_id=? "
            "ORDER BY id DESC LIMIT ?) ORDER BY id ASC",
            (session_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_message(
        self,
        session_id: str,
        role: str,
        content: str,
        tools_used: list[str] | None = None,
    ) -> None:
        """Persist one message and index it. Silent on failure by design —
        session logging must never break the chat loop."""
        try:
            import json

            now = datetime.now(UTC).isoformat()
            with self._lock:
                conn = self._require_conn()
                # Ensure the session row exists (chat() may pass an
                # agent-generated session id that was never registered).
                conn.execute(
                    "INSERT OR IGNORE INTO sessions (id, platform, title,"
                    " created_at, updated_at) VALUES (?, 'cli', '', ?, ?)",
                    (session_id, now, now),
                )
                cur = conn.execute(
                    "INSERT INTO messages (session_id, role, content, tools_used,"
                    " created_at) VALUES (?, ?, ?, ?, ?)",
                    (
                        session_id,
                        role,
                        content[:100_000],
                        json.dumps(tools_used or []),
                        now,
                    ),
                )
                if self._fts5_available:
                    conn.execute(
                        "INSERT INTO messages_fts (message_id, session_id, content)"
                        " VALUES (?, ?, ?)",
                        (cur.lastrowid, session_id, content[:100_000]),
                    )
                conn.execute(
                    "UPDATE sessions SET updated_at=?, message_count=message_count+1"
                    " WHERE id=?",
                    (now, session_id),
                )
                conn.commit()
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("Failed to record message to session store: %s", exc)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search(
        self,
        query: str,
        limit: int = 10,
        platform: str | None = None,
    ) -> list[dict]:
        """Full-text search across ALL past conversations.

        Returns matches with session metadata, newest first. FTS5 when
        available, LIKE fallback otherwise.
        """
        conn = self._require_conn()
        try:
            if self._fts5_available and query.strip():
                # Escape user input into a safe FTS MATCH expression
                safe = " ".join(
                    f'"{tok}"' for tok in query.replace('"', " ").split() if tok
                )
                sql = (
                    "SELECT m.id, m.session_id, m.role, m.content, m.created_at,"
                    " s.platform, s.title"
                    " FROM messages_fts f"
                    " JOIN messages m ON m.id = CAST(f.message_id AS INTEGER)"
                    " JOIN sessions s ON s.id = m.session_id"
                    " WHERE messages_fts MATCH ?"
                )
                params: list[Any] = [safe]
                if platform:
                    sql += " AND s.platform = ?"
                    params.append(platform)
                sql += " ORDER BY m.created_at DESC LIMIT ?"
                params.append(limit)
                rows = conn.execute(sql, params).fetchall()
            else:
                sql = (
                    "SELECT m.id, m.session_id, m.role, m.content, m.created_at,"
                    " s.platform, s.title FROM messages m"
                    " JOIN sessions s ON s.id = m.session_id"
                    " WHERE m.content LIKE ?"
                )
                params = [f"%{query}%"]
                if platform:
                    sql += " AND s.platform = ?"
                    params.append(platform)
                sql += " ORDER BY m.created_at DESC LIMIT ?"
                params.append(limit)
                rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]
        except sqlite3.OperationalError as exc:
            logger.warning("Session search failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        conn = self._require_conn()
        try:
            sessions = conn.execute("SELECT COUNT(*) n FROM sessions").fetchone()
            messages = conn.execute("SELECT COUNT(*) n FROM messages").fetchone()
            platforms = conn.execute(
                "SELECT platform, COUNT(*) n FROM sessions GROUP BY platform"
            ).fetchall()
            return {
                "db_path": str(self._db_path),
                "fts5": self._fts5_available,
                "sessions": sessions["n"] if sessions else 0,
                "messages": messages["n"] if messages else 0,
                "by_platform": {r["platform"]: r["n"] for r in platforms},
            }
        except sqlite3.Error:
            return {"db_path": str(self._db_path), "error": "unavailable"}


# ----------------------------------------------------------------------
# Module-level default store (used by the session_search tool)
# ----------------------------------------------------------------------

_default_store: SessionStore | None = None


def get_default_store() -> SessionStore:
    """Process-wide session store singleton."""
    global _default_store
    if _default_store is None:
        _default_store = SessionStore()
        _default_store.initialize()
    return _default_store
