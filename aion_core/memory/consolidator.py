"""Aion Memory Consolidator — real background consolidation task.

Runs periodically (default every 5 minutes) in a background asyncio task.
On each run it:
    1. Examines the working memory (current conversation) for new facts
    2. Promotes durable facts to long-term memory layers
    3. Updates MEMORY.md with a structured summary
    4. Updates USER.md with newly-learned user attributes
    5. Triggers skill auto-creation when patterns repeat

This is Aion's equivalent of Hermes Agent's "background review" feature
and OpenClaw's MEMORY.md auto-update — both signature capabilities.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("aion_hand.memory.consolidator")


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------


@dataclass
class ConsolidatorConfig:
    """Background consolidation configuration."""

    enabled: bool = True
    interval_seconds: float = 300.0  # 5 minutes
    max_memory_entries: int = 500
    max_user_attributes: int = 50
    memory_md_path: Path = Path.home() / ".aion-hand" / "memories" / "MEMORY.md"
    user_md_path: Path = Path.home() / ".aion-hand" / "memories" / "USER.md"


# ---------------------------------------------------------------------------
# Consolidator
# ---------------------------------------------------------------------------


class MemoryConsolidator:
    """Periodic background task that consolidates working memory into long-term.

    Designed to run alongside the main agent loop. Call `start()` once
    after agent init, and `stop()` before shutdown.
    """

    # Patterns that suggest a durable fact about the user
    _USER_FACT_PATTERNS = [
        re.compile(r"\bmy name is (\w+)", re.IGNORECASE),
        re.compile(r"\bI (?:live|am based) in ([\w\s,]+)", re.IGNORECASE),
        re.compile(r"\bI work (?:at|for|as) ([\w\s]+)", re.IGNORECASE),
        re.compile(r"\bI (?:prefer|like|use) ([\w\s,]+)", re.IGNORECASE),
        re.compile(
            r"\bI (?:don't|do not|cannot) (?:like|use|want) ([\w\s,]+)", re.IGNORECASE
        ),
        re.compile(r"\bmy (?:timezone|tz) is ([\w/]+)", re.IGNORECASE),
    ]

    def __init__(
        self,
        memory_manager: Any = None,
        skill_engine: Any = None,
        config: ConsolidatorConfig | None = None,
    ) -> None:
        self.memory_manager = memory_manager
        self.skill_engine = skill_engine
        self.config = config or ConsolidatorConfig()
        self._task: asyncio.Task | None = None
        self._stop_event = asyncio.Event()
        self._last_run: datetime | None = None
        self._runs_completed = 0
        self._facts_promoted = 0
        self._user_attrs_learned = 0
        self._skills_created = 0

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the background consolidation task."""
        if not self.config.enabled:
            logger.info("Memory consolidator disabled by config")
            return
        if self._task is not None:
            logger.warning("Memory consolidator already running")
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(
            self._run_loop(), name="aion-memory-consolidator"
        )
        logger.info(
            f"Memory consolidator started (interval={self.config.interval_seconds}s)"
        )

    async def stop(self) -> None:
        """Stop the background task gracefully."""
        if self._task is None:
            return
        self._stop_event.set()
        self._task.cancel()
        try:
            await self._task
        except asyncio.CancelledError:
            pass
        self._task = None
        logger.info("Memory consolidator stopped")

    # ------------------------------------------------------------------
    #  Main loop
    # ------------------------------------------------------------------

    async def _run_loop(self) -> None:
        """Background loop — runs until stop() is called."""
        while not self._stop_event.is_set():
            try:
                await self._consolidate_once()
                self._runs_completed += 1
                self._last_run = datetime.now(UTC)
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"Consolidation cycle failed: {exc}")
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(), timeout=self.config.interval_seconds
                )
            except TimeoutError:
                pass  # interval elapsed, loop again
            except asyncio.CancelledError:
                break

    async def _consolidate_once(self) -> None:
        """One consolidation cycle."""
        # 1. Pull recent working-memory items
        recent = self._get_recent_working_items()
        if not recent:
            return

        # 2. Extract durable facts and promote to long-term
        promoted = self._promote_durable_facts(recent)
        self._facts_promoted += promoted

        # 3. Extract user attributes
        user_attrs = self._extract_user_attributes(recent)
        self._user_attrs_learned += user_attrs

        # 4. Update MEMORY.md
        self._update_memory_md(recent)

        # 5. Update USER.md
        self._update_user_md()

        # 6. Trigger skill auto-creation if patterns repeat
        if self.skill_engine is not None:
            created = self._maybe_create_skills(recent)
            self._skills_created += created

    # ------------------------------------------------------------------
    #  Helpers
    # ------------------------------------------------------------------

    def _get_recent_working_items(self) -> list[dict[str, Any]]:
        """Get recent items from the working memory since last consolidation."""
        if self.memory_manager is None:
            return []
        try:
            # Try various API names — memory_manager shape varies
            for method in (
                "recent_working",
                "get_working",
                "working_items",
                "get_recent_working",
            ):
                fn = getattr(self.memory_manager, method, None)
                if callable(fn):
                    items = fn(limit=20)
                    if isinstance(items, list):
                        return items
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"Could not get working items: {exc}")
        return []

    def _promote_durable_facts(self, items: list[dict[str, Any]]) -> int:
        """Identify items that look like durable facts and store them in L3/L4."""
        if self.memory_manager is None:
            return 0
        promoted = 0
        for item in items:
            content = str(item.get("content") or item.get("text") or "")
            if not content or len(content) < 10:
                continue
            # Heuristic: items containing "is", "=", "always", "never", dates
            if any(
                kw in content.lower()
                for kw in (
                    " is ",
                    " are ",
                    " always ",
                    " never ",
                    " = ",
                    " located ",
                    " works at ",
                )
            ):
                try:
                    # Promote to semantic layer (L4)
                    if hasattr(self.memory_manager, "store"):
                        self.memory_manager.store(content=content, layer="semantic")
                    promoted += 1
                except Exception:  # noqa: BLE001
                    pass
        return promoted

    def _extract_user_attributes(self, items: list[dict[str, Any]]) -> int:
        """Extract user attributes (name, location, job, preferences) from items."""
        if self.memory_manager is None:
            return 0
        attrs: list[tuple[str, str]] = []
        for item in items:
            content = str(item.get("content") or item.get("text") or "")
            for pat in self._USER_FACT_PATTERNS:
                m = pat.search(content)
                if m:
                    attr_name = (
                        pat.pattern.split("(")[0]
                        .replace("\\b", "")
                        .replace("my ", "")
                        .replace("i ", "")
                        .strip()
                    )
                    attr_value = m.group(1).strip()
                    if attr_value and len(attr_value) < 80:
                        attrs.append((attr_name, attr_value))
        # Store in user profile (L6)
        stored = 0
        for name, value in attrs:
            try:
                if hasattr(self.memory_manager, "store"):
                    self.memory_manager.store(
                        content=f"User {name}: {value}",
                        layer="user_profile",
                    )
                    stored += 1
            except Exception:  # noqa: BLE001
                pass
        return stored

    def _update_memory_md(self, items: list[dict[str, Any]]) -> None:
        """Append recent consolidated memories to MEMORY.md (OpenClaw-style)."""
        try:
            self.config.memory_md_path.parent.mkdir(parents=True, exist_ok=True)
            existing = ""
            if self.config.memory_md_path.is_file():
                existing = self.config.memory_md_path.read_text(encoding="utf-8")
            new_entries: list[str] = []
            for item in items[:10]:
                content = str(item.get("content") or item.get("text") or "").strip()
                if not content or len(content) < 10:
                    continue
                timestamp = item.get("timestamp") or datetime.now(UTC).isoformat()
                new_entries.append(f"- [{timestamp}] {content[:200]}")
            if not new_entries:
                return
            new_block = (
                f"\n## {datetime.now(UTC).strftime('%Y-%m-%d %H:%M')} UTC\n"
                + "\n".join(new_entries)
                + "\n"
            )
            self.config.memory_md_path.write_text(
                existing + new_block, encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not update MEMORY.md: {exc}")

    def _update_user_md(self) -> None:
        """Refresh USER.md from current user-profile memory entries."""
        if self.memory_manager is None:
            return
        try:
            entries: list[Any] = []
            for method in ("get_user_profile", "get_layer", "user_attributes"):
                fn = getattr(self.memory_manager, method, None)
                if callable(fn):
                    try:
                        result = (
                            fn() if method == "get_user_profile" else fn("user_profile")
                        )
                        if isinstance(result, list):
                            entries = result
                            break
                    except Exception:  # noqa: BLE001
                        continue
            if not entries:
                return
            self.config.user_md_path.parent.mkdir(parents=True, exist_ok=True)
            lines = ["# User Profile", ""]
            for e in entries[: self.config.max_user_attributes]:
                content = getattr(e, "content", str(e))
                lines.append(f"- {content}")
            self.config.user_md_path.write_text(
                "\n".join(lines) + "\n", encoding="utf-8"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not update USER.md: {exc}")

    def _maybe_create_skills(self, items: list[dict[str, Any]]) -> int:
        """If the same task pattern appears 3+ times, suggest skill creation."""
        if self.skill_engine is None:
            return 0
        try:
            created = 0
            for item in items:
                content = str(item.get("content") or item.get("text") or "")
                if len(content) < 20:
                    continue
                # SkillEngine.evaluate_auto_create decides if a skill should be made
                if hasattr(self.skill_engine, "evaluate_auto_create"):
                    skill = self.skill_engine.evaluate_auto_create(
                        task=content[:200],
                        outcome=content,
                        tokens_used=0,
                    )
                    if skill is not None:
                        created += 1
            return created
        except Exception:  # noqa: BLE001
            return 0

    # ------------------------------------------------------------------
    #  Stats
    # ------------------------------------------------------------------

    def stats(self) -> dict[str, Any]:
        return {
            "enabled": self.config.enabled,
            "running": self._task is not None and not self._task.done(),
            "runs_completed": self._runs_completed,
            "last_run": self._last_run.isoformat() if self._last_run else None,
            "facts_promoted": self._facts_promoted,
            "user_attrs_learned": self._user_attrs_learned,
            "skills_created": self._skills_created,
        }


__all__ = ["MemoryConsolidator", "ConsolidatorConfig"]
