"""
Cron Scheduler for the Aion Hand AI agent framework.

Hermes Agent-inspired cron system that parses standard 5-field cron expressions
and drives a per-minute tick loop to evaluate and execute scheduled tasks.

Cron expression format (5 fields, standard UNIX):
    ┌───────────── minute  (0–59)
    │ ┌───────────── hour   (0–23)
    │ │ ┌───────────── day of month  (1–31)
    │ │ │ ┌───────────── month  (1–12)
    │ │ │ │ ┌───────────── day of week  (0–6, 0 = Sunday)
    * * * * *

    Special characters:
        *  — any value
        ,  — list separator   (e.g. 1,15)
        -  — range            (e.g. 1-5)
        /  — step             (e.g. */5  → every 5th value)

Examples:
    "5 * * * *"   — every hour at minute 5
    "0 9 * * *"   — daily at 09:00
    "*/15 * * * *"— every 15 minutes
    "0 9 * * 1"   — every Monday at 09:00
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cron expression parser helpers
# ---------------------------------------------------------------------------

# Field ranges for each cron position: (min_val, max_val)
_FIELD_RANGES = [
    (0, 59),  # minute
    (0, 23),  # hour
    (1, 31),  # day of month
    (1, 12),  # month
    (0, 6),  # day of week (0 = Sunday)
]


def _parse_field(field_str: str, min_val: int, max_val: int) -> set[int]:
    """Parse a single cron field into a set of matching integers.

    Supports:
        *       → all values
        5       → exact value
        1,3,5   → list of values
        1-5     → range
        */5     → step over full range
        1-10/2  → step over range
    """
    allowed: set[int] = set()

    for part in field_str.split(","):
        part = part.strip()
        if not part:
            continue

        # Handle step (e.g. "*/5" or "1-10/2")
        step = 1
        if "/" in part:
            base_part, step_str = part.split("/", 1)
            step = int(step_str)
        else:
            base_part = part

        if base_part == "*":
            range_start, range_end = min_val, max_val
        elif "-" in base_part:
            lo, hi = base_part.split("-", 1)
            range_start, range_end = int(lo), int(hi)
        else:
            # Single value
            val = int(base_part)
            if min_val <= val <= max_val:
                allowed.add(val)
            continue

        for v in range(range_start, range_end + 1, step):
            if min_val <= v <= max_val:
                allowed.add(v)

    return allowed


def parse_cron_expression(expression: str) -> list[set[int]]:
    """Parse a 5-field cron expression into a list of allowed-value sets.

    Returns:
        A list of 5 sets: [minute, hour, day_of_month, month, day_of_week].
        Each set contains the integer values that satisfy that field.

    Raises:
        ValueError: If the expression is malformed.
    """
    parts = expression.strip().split()
    if len(parts) != 5:
        raise ValueError(
            f"Invalid cron expression '{expression}': expected 5 fields, got {len(parts)}"
        )

    parsed: list[set[int]] = []
    for i, part in enumerate(parts):
        min_val, max_val = _FIELD_RANGES[i]
        try:
            allowed = _parse_field(part, min_val, max_val)
        except (ValueError, TypeError) as exc:
            raise ValueError(
                f"Invalid cron field '{part}' at position {i + 1} in '{expression}': {exc}"
            ) from exc
        if not allowed:
            raise ValueError(
                f"Cron field '{part}' at position {i + 1} matches no values"
            )
        parsed.append(allowed)

    return parsed


def next_occurrence(parsed_fields: list[set[int]], after: datetime) -> datetime:
    """Calculate the next datetime *after* ``after`` that matches the schedule.

    Uses minute-level resolution.  Day-of-week and day-of-month are OR-ed
    (standard Vixie cron behaviour): the target day must match *either*
    the month-day set *or* the week-day set.
    """
    # Start checking from the *next* minute
    candidate = after.replace(second=0, microsecond=0) + timedelta(minutes=1)

    minutes, hours, doms, months, dows = parsed_fields

    # We search for at most 366 days (one full leap year) to avoid infinite loops.
    max_iterations = 366 * 24 * 60
    for _ in range(max_iterations):
        if (
            candidate.month in months
            and candidate.hour in hours
            and candidate.minute in minutes
            # Day-of-month OR day-of-week match
            and (candidate.day in doms or candidate.weekday() in dows)
        ):
            return candidate
        candidate += timedelta(minutes=1)

    raise RuntimeError(
        "Could not find a matching time within the next 366 days — "
        "check your cron expression"
    )


# ---------------------------------------------------------------------------
# ScheduledTask data model
# ---------------------------------------------------------------------------


@dataclass
class ScheduledTask:
    """Represents a single recurring task managed by the scheduler.

    Attributes:
        id:            Unique identifier (UUID4).
        task:          The task description / instruction string.
        schedule:      Raw cron expression (e.g. ``"0 9 * * *"``).
        platforms:     List of platform names where to deliver results.
        enabled:       Whether the task is currently active.
        last_run:      Datetime of the most recent execution, if any.
        next_run:      Datetime of the next scheduled execution, if any.
        run_count:     Total number of completed runs.
        created_at:    When the task was registered.
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    task: str = ""
    schedule: str = "* * * * *"
    platforms: list[str] = field(default_factory=list)
    enabled: bool = True
    last_run: datetime | None = None
    next_run: datetime | None = None
    run_count: int = 0
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    # Internal — parsed cron fields, populated on validation.
    _parsed: list[set[int]] | None = field(default=None, repr=False, compare=False)

    def validate_and_compute(self) -> None:
        """Parse the cron expression and compute ``next_run``."""
        self._parsed = parse_cron_expression(self.schedule)
        if self.next_run is None:
            self.next_run = next_occurrence(self._parsed, self.created_at)


# ---------------------------------------------------------------------------
# CronScheduler
# ---------------------------------------------------------------------------


class CronScheduler:
    """Async cron scheduler that evaluates tasks on a per-minute tick loop.

    Inspired by the Hermes Agent cron system: each task is a natural-language
    instruction that the agent evaluates at the scheduled time.  Results can
    optionally be delivered to one or more messaging platforms.

    Usage::

        scheduler = CronScheduler(agent, timezone="Europe/London")
        await scheduler.initialize()

        task_id = await scheduler.add_task(
            task="Give me a weather briefing",
            schedule="0 8 * * *",
            platforms=["telegram"],
        )
        await scheduler.run_task_now(task_id)
        await scheduler.shutdown()
    """

    def __init__(self, agent: Any = None, timezone: str = "UTC") -> None:
        self._tasks: dict[str, ScheduledTask] = {}
        self._agent = agent
        self._timezone = timezone
        self._running: bool = False
        self._tick_task: asyncio.Task | None = None
        self._tick_interval: int = 60  # seconds between evaluation passes

        logger.info(
            "CronScheduler created (timezone=%s, tick=%ds, agent=%s)",
            self._timezone,
            self._tick_interval,
            "provided" if agent else "none (log-only mode)",
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Start the scheduler tick loop in the background."""
        if self._running:
            logger.warning("CronScheduler is already running")
            return

        self._running = True
        self._tick_task = asyncio.create_task(self._tick_loop(), name="cron-tick")
        logger.info(
            "CronScheduler started — tick loop running every %ds", self._tick_interval
        )

    async def shutdown(self) -> None:
        """Stop the scheduler tick loop and cancel all pending work."""
        self._running = False
        if self._tick_task and not self._tick_task.done():
            self._tick_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._tick_task
        logger.info("CronScheduler shut down (%d tasks unregistered)", len(self._tasks))

    # ------------------------------------------------------------------
    # Tick loop
    # ------------------------------------------------------------------

    async def _tick_loop(self) -> None:
        """Background coroutine: evaluate tasks every ``_tick_interval`` seconds."""
        while self._running:
            try:
                await self._evaluate_tasks()
            except Exception:
                logger.exception("Error during cron tick evaluation")
            await asyncio.sleep(self._tick_interval)

    async def _evaluate_tasks(self) -> None:
        """Check every enabled task and fire those whose ``next_run`` has arrived."""
        now = datetime.now(UTC)

        for task in list(self._tasks.values()):
            if not task.enabled or task.next_run is None:
                continue

            if now >= task.next_run:
                logger.info(
                    "Cron firing task %s (%s) — schedule: %s",
                    task.id,
                    task.task[:60],
                    task.schedule,
                )
                try:
                    await self._execute_task(task)
                except Exception:
                    logger.exception(
                        "Task %s execution failed: %s", task.id, task.task[:60]
                    )

    async def _execute_task(self, task: ScheduledTask) -> None:
        """Run a single task: delegate to the agent, then deliver results."""
        now = datetime.now(UTC)
        task.last_run = now
        task.run_count += 1

        # Delegate to the agent (via ``chat`` interface).
        if self._agent is None:
            logger.info(
                "Cron task %s fired (no agent): %s",
                task.id,
                task.task[:60],
            )
            # Compute next run and return
            assert task._parsed is not None
            task.next_run = next_occurrence(task._parsed, now)
            return

        try:
            result = await self._agent.chat(task.task)
        except AttributeError:
            # Agent may not expose ``chat``; fall back to a generic call.
            result = {"content": f"[cron] executed: {task.task}"}

        # Deliver to configured platforms.
        if (
            task.platforms
            and hasattr(self._agent, "_messenger")
            and self._agent._messenger is not None
        ):
            content = result.get("content", str(result))
            for platform in task.platforms:
                try:
                    await self._agent._messenger.broadcast([platform], content)
                except Exception:
                    logger.exception(
                        "Failed to deliver task %s result to platform '%s'",
                        task.id,
                        platform,
                    )

        # Compute next run.
        assert task._parsed is not None
        task.next_run = next_occurrence(task._parsed, now)

    # ------------------------------------------------------------------
    # Task management API
    # ------------------------------------------------------------------

    async def add_task(
        self,
        task: str,
        schedule: str,
        platforms: list[str] | None = None,
    ) -> str:
        """Register a new scheduled task.

        Args:
            task:      Natural-language task instruction for the agent.
            schedule:  5-field cron expression (e.g. ``"0 9 * * *"``).
            platforms: Optional list of platform names for result delivery.

        Returns:
            The unique task ID.

        Raises:
            ValueError: If the cron expression is invalid.
        """
        scheduled = ScheduledTask(
            task=task,
            schedule=schedule,
            platforms=platforms or [],
        )
        scheduled.validate_and_compute()

        self._tasks[scheduled.id] = scheduled
        logger.info(
            "Task %s registered: '%s' [%s] → next at %s, platforms=%s",
            scheduled.id,
            scheduled.task[:60],
            scheduled.schedule,
            scheduled.next_run,
            scheduled.platforms,
        )
        return scheduled.id

    async def remove_task(self, task_id: str) -> bool:
        """Remove a task by ID.

        Returns:
            ``True`` if the task existed and was removed, ``False`` otherwise.
        """
        removed = self._tasks.pop(task_id, None)
        if removed:
            logger.info("Task %s removed: '%s'", task_id, removed.task[:60])
            return True
        logger.warning("Task %s not found for removal", task_id)
        return False

    async def list_tasks(self) -> list[ScheduledTask]:
        """Return a list of all registered tasks (enabled and disabled)."""
        return list(self._tasks.values())

    async def enable_task(self, task_id: str) -> bool:
        """Enable a previously disabled task.

        Recomputes ``next_run`` if the old value has already passed.

        Returns:
            ``True`` if the task was found and enabled.
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning("Task %s not found for enable", task_id)
            return False

        task.enabled = True

        # Recompute next_run if it's in the past.
        now = datetime.now(UTC)
        if task.next_run is None or task.next_run <= now:
            assert task._parsed is not None
            task.next_run = next_occurrence(task._parsed, now)

        logger.info("Task %s enabled (next at %s)", task_id, task.next_run)
        return True

    async def disable_task(self, task_id: str) -> bool:
        """Disable a task without removing it.

        Returns:
            ``True`` if the task was found and disabled.
        """
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning("Task %s not found for disable", task_id)
            return False
        task.enabled = False
        logger.info("Task %s disabled", task_id)
        return True

    async def run_task_now(self, task_id: str) -> dict[str, Any]:
        """Immediately execute a task regardless of its schedule.

        Args:
            task_id: The task to run.

        Returns:
            A dict with keys ``task_id``, ``task``, ``run_count``, and ``result``.

        Raises:
            KeyError: If the task ID does not exist.
        """
        task = self._tasks.get(task_id)
        if task is None:
            raise KeyError(f"Task '{task_id}' not found")

        logger.info("Manual trigger: running task %s now", task_id)
        await self._execute_task(task)

        return {
            "task_id": task.id,
            "task": task.task,
            "run_count": task.run_count,
            "last_run": task.last_run,
            "next_run": task.next_run,
        }
