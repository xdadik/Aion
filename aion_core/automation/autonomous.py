"""Bounded autonomous task execution primitives.

Automation should be persistent but never unbounded. AutonomousRunner provides
retry, timeout, cancellation, concurrency, and optional verification hooks
around the existing AionHand chat interface.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional


Verifier = Callable[[Dict[str, Any]], bool | Awaitable[bool]]


@dataclass
class AutomationTask:
    """A durable description of one autonomous task."""

    prompt: str
    task_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    timeout: float = 300.0
    max_attempts: int = 3
    verify: Optional[Verifier] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AutomationResult:
    task_id: str
    success: bool
    attempts: int
    elapsed: float
    response: Optional[Dict[str, Any]] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "attempts": self.attempts,
            "elapsed": round(self.elapsed, 4),
            "response": self.response,
            "error": self.error,
        }


class AutonomousRunner:
    """Run independent Aion tasks concurrently with hard resource bounds."""

    def __init__(self, agent: Any, *, max_concurrency: int = 4) -> None:
        if max_concurrency < 1:
            raise ValueError("max_concurrency must be >= 1")
        self.agent = agent
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._tasks: Dict[str, asyncio.Task[AutomationResult]] = {}

    async def run(self, task: AutomationTask) -> AutomationResult:
        if not task.prompt.strip():
            raise ValueError("Automation task prompt cannot be empty")
        if task.timeout <= 0:
            raise ValueError("Automation task timeout must be positive")
        if not 1 <= task.max_attempts <= 20:
            raise ValueError("max_attempts must be between 1 and 20")

        started = time.monotonic()
        attempts = 0
        last_error: Optional[str] = None

        async with self._semaphore:
            while attempts < task.max_attempts:
                attempts += 1
                try:
                    response = await asyncio.wait_for(
                        self.agent.chat(task.prompt), timeout=task.timeout
                    )
                    verified = True
                    if task.verify is not None:
                        verdict = task.verify(response)
                        verified = await verdict if asyncio.iscoroutine(verdict) else verdict
                    if verified:
                        return AutomationResult(
                            task.task_id, True, attempts, time.monotonic() - started, response
                        )
                    last_error = "Verification rejected the agent result"
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    last_error = f"{type(exc).__name__}: {exc}"

                if attempts < task.max_attempts:
                    await asyncio.sleep(min(2.0 ** (attempts - 1), 10.0))

        return AutomationResult(
            task.task_id, False, attempts, time.monotonic() - started, error=last_error
        )

    def submit(self, task: AutomationTask) -> asyncio.Task[AutomationResult]:
        """Schedule a task and retain a handle for status/cancellation."""
        if task.task_id in self._tasks and not self._tasks[task.task_id].done():
            raise ValueError(f"Task {task.task_id} is already running")
        handle = asyncio.create_task(self.run(task), name=f"aion-automation-{task.task_id}")
        self._tasks[task.task_id] = handle
        return handle

    def cancel(self, task_id: str) -> bool:
        handle = self._tasks.get(task_id)
        return bool(handle and handle.cancel())

    def status(self, task_id: str) -> str:
        handle = self._tasks.get(task_id)
        if handle is None:
            return "unknown"
        if handle.cancelled():
            return "cancelled"
        if not handle.done():
            return "running"
        try:
            return "completed" if handle.result().success else "failed"
        except Exception:
            return "failed"

    async def run_many(self, tasks: List[AutomationTask]) -> List[AutomationResult]:
        """Run many tasks concurrently while respecting max_concurrency."""
        if not tasks:
            return []
        return await asyncio.gather(*(self.run(task) for task in tasks))
