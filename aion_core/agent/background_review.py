"""
Post-turn background review system.

After each agent turn a ReviewTask is enqueued.  A long-running
background coroutine drains the queue and runs configurable review
checks (memory consistency, skill usage, response quality, insight
extraction) without blocking the main conversation loop.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import Counter
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


class ReviewType(str, Enum):
    """Kinds of background review."""

    MEMORY = "memory"
    SKILLS = "skills"
    QUALITY = "quality"
    INSIGHTS = "insights"
    GENERAL = "general"


@dataclass
class ReviewTask:
    """A unit of work for the background reviewer."""

    turn_id: str
    review_type: ReviewType
    payload: Dict[str, Any] = field(default_factory=dict)
    priority: int = 0
    created_at: float = field(default_factory=time.monotonic)
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


@dataclass
class ReviewResult:
    """Outcome of a single background review."""

    task_id: str
    review_type: ReviewType
    turn_id: str
    passed: bool = True
    score: float = 1.0
    findings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
    elapsed: float = 0.0
    error: Optional[str] = None


# Callable signature for review checks
ReviewCheck = Callable[
    [Dict[str, Any]], Coroutine[Any, Any, ReviewResult]
]


# ---------------------------------------------------------------------------
# BackgroundReviewer
# ---------------------------------------------------------------------------


class BackgroundReviewer:
    """Asyncio-based background review processor.

    Usage::

        reviewer = BackgroundReviewer()
        await reviewer.start()
        # ... enqueue tasks via submit_review ...
        await reviewer.shutdown()
    """

    def __init__(
        self,
        max_concurrent: int = 3,
        queue_size: int = 0,  # 0 = unlimited
    ) -> None:
        self._queue: asyncio.PriorityQueue[ReviewTask] = asyncio.PriorityQueue(
            maxsize=queue_size
        )
        self._max_concurrent = max_concurrent
        self._workers: List[asyncio.Task[None]] = []
        self._running = False
        self._results: List[ReviewResult] = []
        self._results_lock = asyncio.Lock()
        self._stats: Dict[str, int] = {
            "submitted": 0,
            "completed": 0,
            "failed": 0,
            "memory_reviews": 0,
            "skill_reviews": 0,
            "quality_reviews": 0,
            "insight_reviews": 0,
        }
        # Pluggable review hooks (can be overridden by the caller)
        self._check_memory: Optional[ReviewCheck] = None
        self._check_skills: Optional[ReviewCheck] = None
        self._check_quality: Optional[ReviewCheck] = None
        self._check_insights: Optional[ReviewCheck] = None

    # -- lifecycle --------------------------------------------------------

    async def start(self) -> None:
        """Spin up background worker coroutines."""
        if self._running:
            return
        self._running = True
        for i in range(self._max_concurrent):
            task = asyncio.create_task(
                self._worker(i), name=f"review-worker-{i}"
            )
            self._workers.append(task)
        logger.info(
            "BackgroundReviewer started with %d worker(s)", self._max_concurrent
        )

    async def shutdown(self, wait: bool = True) -> None:
        """Stop all workers and optionally wait for the queue to drain."""
        self._running = False
        for w in self._workers:
            w.cancel()
        if wait:
            await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()
        logger.info("BackgroundReviewer shut down")

    # -- enqueue ----------------------------------------------------------

    async def submit_review(self, task: ReviewTask) -> str:
        """Enqueue a review task and return its task_id."""
        # Negate priority so higher-priority (larger int) items come
        # first in the min-heap used by PriorityQueue.
        awaitable_item = (-task.priority, task.created_at, task)
        await self._queue.put(awaitable_item)
        self._stats["submitted"] += 1
        logger.debug(
            "Enqueued review task %s (%s)",
            task.task_id,
            task.review_type.value,
        )
        return task.task_id

    # -- worker -----------------------------------------------------------

    async def _worker(self, worker_id: int) -> None:
        """Long-running coroutine that pulls tasks from the queue."""
        while self._running:
            try:
                _, _, task = await asyncio.wait_for(
                    self._queue.get(), timeout=1.0
                )
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            result = await self._process_task(task)
            async with self._results_lock:
                self._results.append(result)
            if result.error is not None:
                self._stats["failed"] += 1
            else:
                self._stats["completed"] += 1
            self._queue.task_done()

    # -- dispatch ---------------------------------------------------------

    async def _process_task(self, task: ReviewTask) -> ReviewResult:
        """Route a task to the appropriate review handler."""
        t0 = time.monotonic()
        try:
            handler = {
                ReviewType.MEMORY: self._review_memory,
                ReviewType.SKILLS: self._review_skills,
                ReviewType.QUALITY: self._review_quality,
                ReviewType.INSIGHTS: self._extract_insights,
            }.get(task.review_type, self._review_quality)
            result = await handler(task.payload)
            result.task_id = task.task_id
            result.review_type = task.review_type
            result.turn_id = task.turn_id
            result.elapsed = time.monotonic() - t0
            return result
        except Exception as exc:
            logger.error(
                "Review task %s failed: %s", task.task_id, exc, exc_info=True
            )
            return ReviewResult(
                task_id=task.task_id,
                review_type=task.review_type,
                turn_id=task.turn_id,
                passed=False,
                score=0.0,
                error=str(exc),
                elapsed=time.monotonic() - t0,
            )

    # -- built-in review checks -------------------------------------------

    async def _review_memory(self, payload: Dict[str, Any]) -> ReviewResult:
        """Check memory consistency after a turn.

        Looks for contradictions between the turn output and previously
        stored facts in ``payload[\"existing_facts\"]``.
        """
        result = ReviewResult(
            task_id="", review_type=ReviewType.MEMORY, turn_id=""
        )
        self._stats["memory_reviews"] += 1

        facts: List[str] = payload.get("existing_facts", [])
        turn_output: str = payload.get("turn_output", "")
        new_claims: List[str] = payload.get("new_claims", [])

        if not turn_output:
            result.findings.append(
                "Empty turn output \u2013 nothing to review."
            )
            result.score = 0.5
            return result

        contradictions: List[str] = []
        for fact in facts:
            negation_markers = [
                "not ", "no longer", "never", "incorrectly", "wrong"
            ]
            lower_fact = fact.lower()
            for marker in negation_markers:
                if (
                    marker in lower_fact
                    and lower_fact.replace(marker, "")
                    in turn_output.lower()
                ):
                    contradictions.append(
                        f"Potential contradiction with fact: {fact}"
                    )
                    break

        result.findings.extend(contradictions)
        result.suggestions.extend(
            [f"Consider storing claim: {c}" for c in new_claims if c]
        )
        result.passed = len(contradictions) == 0
        result.score = max(0.0, 1.0 - len(contradictions) * 0.25)
        return result

    async def _review_skills(self, payload: Dict[str, Any]) -> ReviewResult:
        """Audit skill/tool usage during the turn."""
        result = ReviewResult(
            task_id="", review_type=ReviewType.SKILLS, turn_id=""
        )
        self._stats["skill_reviews"] += 1

        tools_used: List[str] = payload.get("tools_used", [])
        tools_available: List[str] = payload.get("tools_available", [])
        errors: List[str] = payload.get("tool_errors", [])

        if not tools_used:
            result.findings.append(
                "No tools/skills were invoked this turn."
            )
            result.score = 0.7
            return result

        unknown = [t for t in tools_used if t not in tools_available]
        for u in unknown:
            result.findings.append(f"Unknown tool invoked: {u}")

        if errors:
            result.findings.extend(f"Tool error: {e}" for e in errors)

        result.passed = len(unknown) == 0 and len(errors) == 0
        result.score = max(
            0.0, 1.0 - len(unknown) * 0.2 - len(errors) * 0.3
        )
        result.suggestions.append(
            f"{len(tools_used)} tool(s) used this turn."
        )
        return result

    async def _review_quality(self, payload: Dict[str, Any]) -> ReviewResult:
        """Assess response quality heuristically."""
        result = ReviewResult(
            task_id="", review_type=ReviewType.QUALITY, turn_id=""
        )
        self._stats["quality_reviews"] += 1

        response: str = payload.get("response", "")
        min_length: int = payload.get("min_length", 20)

        if not response or not response.strip():
            result.passed = False
            result.score = 0.0
            result.findings.append("Empty response.")
            return result

        issues: List[str] = []
        if len(response.strip()) < min_length:
            issues.append(
                f"Response too short "
                f"({len(response.strip())} < {min_length} chars)."
            )

        words = response.split()
        if len(words) > 10:
            counts = Counter(words)
            most_common_word, most_common_count = counts.most_common(1)[0]
            repetition_ratio = most_common_count / len(words)
            if repetition_ratio > 0.3:
                issues.append(
                    f"Excessive repetition of word '{most_common_word}' "
                    f"({repetition_ratio:.0%} of all words)."
                )

        result.findings.extend(issues)
        result.passed = len(issues) == 0
        result.score = max(0.0, 1.0 - len(issues) * 0.3)
        return result

    async def _extract_insights(self, payload: Dict[str, Any]) -> ReviewResult:
        """Extract reusable insights from the turn."""
        result = ReviewResult(
            task_id="", review_type=ReviewType.INSIGHTS, turn_id=""
        )
        self._stats["insight_reviews"] += 1

        turn_output: str = payload.get("turn_output", "")
        insight_markers = [
            "key takeaway",
            "important",
            "note that",
            "remember",
            "conclusion",
            "summary",
            "insight",
            "recommendation",
        ]

        insights: List[str] = []
        lower = turn_output.lower()
        sentences = turn_output.replace(". ", ".\n").split("\n")
        for sentence in sentences:
            for marker in insight_markers:
                if marker in sentence.lower():
                    cleaned = sentence.strip()
                    if len(cleaned) > 10:
                        insights.append(cleaned)
                    break

        if insights:
            result.suggestions.extend(insights)
            result.findings.append(
                f"Extracted {len(insights)} potential insight(s)."
            )
            result.score = min(1.0, 0.5 + 0.1 * len(insights))
        else:
            result.findings.append("No explicit insights detected.")
            result.score = 0.5

        result.passed = True
        return result

    # -- public queries ---------------------------------------------------

    async def process_queue(self) -> int:
        """Block until all currently-queued tasks are processed.

        Returns the number of tasks processed.
        """
        await self._queue.join()
        return self._stats["completed"]

    def get_stats(self) -> Dict[str, Any]:
        """Return aggregate statistics."""
        return dict(self._stats)

    def __repr__(self) -> str:
        return (
            f"BackgroundReviewer("
            f"workers={self._max_concurrent}, "
            f"queued={self._queue.qsize()}, "
            f"running={self._running}"
            f")"
        )
