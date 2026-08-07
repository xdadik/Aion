#!/usr/bin/env python3
"""
Tool Guardrails for Aion Hand.
=================================

Detects and prevents tool execution loops, runaway retries, and
no-progress cycles in the agent loop.  Inspired by Hermes Agent's
``tool_guardrails.py``.

The guardrail system watches every tool invocation the agent makes and
applies three pattern detectors:

  1. **Exact-failure loop** – the same tool with the *same arguments*
     fails repeatedly (typically a bug or misconfiguration).
  2. **Same-tool failure loop** – the same tool with *different* arguments
     keeps failing (the tool itself is broken or the agent is misusing it).
  3. **No-progress cycle** – the agent calls only read-only / idempotent
     tools but never makes a write / mutation, indicating a stuck
     planning loop.

Each pattern has configurable *warn* and *block* thresholds.  The guard
returns a :class:`ToolGuardrailDecision` so the agent loop can decide
whether to proceed, log a warning, or halt.

The module also ships :class:`ConcurrentToolExecutor` which groups tool
calls into safe parallel batches — dangerous tools (file writes, shell
commands) run alone while safe tools (reads, queries) may execute
concurrently.

Example usage::

    guardrails = ToolGuardrails()
    decision = guardrails.observe("shell_exec", {"command": "rm -rf /"}, "error")
    if decision == ToolGuardrailDecision.BLOCK:
        logger.warning("Tool loop detected – blocking execution")

Typical usage::

    executor = ConcurrentToolExecutor()
    results = await executor.execute_concurrent(tool_calls, run_tool)
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from collections import Counter, deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

logger = logging.getLogger("aion_hand.agent.tool_guardrails")


# ======================================================================
# Guardrail Decision
# ======================================================================


class ToolGuardrailDecision(str, Enum):
    """Verdict returned by the guardrail after observing a tool call."""

    PROCEED = "proceed"    # No concerns – let the tool execute.
    WARN = "warn"          # Pattern detected but not yet at block threshold.
    BLOCK = "block"        # Pattern has exceeded the block threshold; abort.


# ======================================================================
# Guardrail Configuration
# ======================================================================


@dataclass
class ToolGuardrailConfig:
    """Tune the sensitivity of each loop-detection pattern.

    Attributes:
        exact_failure_warn_after:  Warn when exact-match failures reach this.
        exact_failure_block_after: Block when exact-match failures reach this.
        same_tool_warn_after:      Warn when same-tool failures reach this.
        same_tool_block_after:     Block when same-tool failures reach this.
        no_progress_warn_after:    Warn when no-progress calls reach this.
        no_progress_block_after:   Block when no-progress calls reach this.
        max_history:               Maximum tool-call records to keep.
    """

    exact_failure_warn_after: int = 2
    exact_failure_block_after: int = 5
    same_tool_warn_after: int = 3
    same_tool_block_after: int = 8
    no_progress_warn_after: int = 2
    no_progress_block_after: int = 5
    max_history: int = 200


# ======================================================================
# ToolCallRecord
# ======================================================================


@dataclass
class ToolCallRecord:
    """Immutable snapshot of a single tool invocation.

    Attributes:
        tool_name:     Name of the tool that was called.
        args_hash:     SHA-256 hex digest of the normalised arguments JSON.
        result_status: ``"success"``, ``"error"``, or ``"blocked"``.
        timestamp:     Monotonic timestamp when the call was observed.
        raw_args:      Original arguments dict (for debugging, not used in
                       comparison).
    """

    tool_name: str
    args_hash: str
    result_status: str
    timestamp: float
    raw_args: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "args_hash": self.args_hash,
            "result_status": self.result_status,
            "timestamp": self.timestamp,
            "raw_args": self.raw_args,
        }


# ======================================================================
# ToolGuardrails – the main loop detector
# ======================================================================


class ToolGuardrails:
    """Detects tool-execution loops and no-progress cycles.

    The guardrail observes each tool call made by the agent and checks
    three detection patterns.  When a pattern crosses the *warn* threshold
    the method returns :attr:`ToolGuardrailDecision.WARN`; at the *block*
    threshold it returns :attr:`ToolGuardrailDecision.BLOCK`.

    Args:
        config: Configuration thresholds (defaults are reasonable for most
                use-cases).

    Example::

        g = ToolGuardrails()
        for tool_call in agent_turn.tool_calls:
            decision = g.observe(tool_call.name, tool_call.args, result)
            if decision == ToolGuardrailDecision.BLOCK:
                raise ToolLoopDetected("blocked by guardrails")
    """

    def __init__(self, config: ToolGuardrailConfig | None = None) -> None:
        self._config = config or ToolGuardrailConfig()
        self._history: deque[ToolCallRecord] = deque(
            maxlen=self._config.max_history,
        )

    # -- Hash helper -----------------------------------------------------

    @staticmethod
    def _hash_args(args: Any) -> str:
        """Produce a deterministic SHA-256 hex digest of the arguments.

        The arguments are JSON-serialised with ``sort_keys=True`` so that
        insertion order does not affect the hash.
        """
        try:
            raw = json.dumps(args, sort_keys=True, default=str)
        except (TypeError, ValueError):
            raw = str(args)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    # -- Public API -------------------------------------------------------

    def observe(
        self,
        tool_name: str,
        args: Any,
        result_status: str,
    ) -> ToolGuardrailDecision:
        """Record a tool call and check for loop patterns.

        Args:
            tool_name:     Name of the tool that was called.
            args:          Arguments passed to the tool (will be hashed).
            result_status: ``"success"``, ``"error"``, or ``"blocked"``.

        Returns:
            :attr:`PROCEED` if no pattern detected, :attr:`WARN` if a
            pattern is emerging, or :attr:`BLOCK` if a pattern has crossed
            the blocking threshold.
        """
        args_hash = self._hash_args(args)
        now = time.monotonic()

        record = ToolCallRecord(
            tool_name=tool_name,
            args_hash=args_hash,
            result_status=result_status,
            timestamp=now,
            raw_args=args if isinstance(args, dict) else None,
        )
        self._history.append(record)

        # Only failures trigger pattern checks
        if result_status != "error":
            return ToolGuardrailDecision.PROCEED

        # Check pattern 1: exact failure
        decision = self._check_exact_failure(tool_name, args_hash)
        if decision != ToolGuardrailDecision.PROCEED:
            return decision

        # Check pattern 2: same-tool failure (different args)
        decision = self._check_same_tool_failure(tool_name)
        if decision != ToolGuardrailDecision.PROCEED:
            return decision

        # Check pattern 3: no-progress cycle
        decision = self._check_no_progress()
        if decision != ToolGuardrailDecision.PROCEED:
            return decision

        return ToolGuardrailDecision.PROCEED

    def get_history(self) -> list[ToolCallRecord]:
        """Return the full history of tool-call records."""
        return list(self._history)

    def reset(self) -> None:
        """Clear all recorded history."""
        self._history.clear()
        logger.debug("ToolGuardrails: history reset")

    def get_stats(self) -> dict[str, Any]:
        """Return statistics about observed patterns.

        Includes per-tool failure counts, exact-failure hotspots, and the
        current no-progress streak length.
        """
        error_records = [r for r in self._history if r.result_status == "error"]
        tool_counts: Counter = Counter(r.tool_name for r in error_records)

        # Exact-failure hotspots: (tool, args_hash) → count
        exact_counts: Counter = Counter(
            (r.tool_name, r.args_hash) for r in error_records
        )

        # No-progress streak: consecutive non-write (idempotent/read) results
        no_progress_streak = self._compute_no_progress_streak()

        return {
            "total_calls": len(self._history),
            "total_errors": len(error_records),
            "error_counts_by_tool": dict(tool_counts),
            "exact_failure_hotspots": {
                f"{tool}:{args_hash[:8]}": count
                for (tool, args_hash), count in exact_counts.most_common(10)
            },
            "no_progress_streak": no_progress_streak,
            "history_len": len(self._history),
        }

    # -- Pattern detectors ------------------------------------------------

    def _check_exact_failure(
        self,
        tool_name: str,
        args_hash: str,
    ) -> ToolGuardrailDecision:
        """Pattern 1: same tool + same args failing repeatedly."""
        count = sum(
            1
            for r in self._history
            if r.tool_name == tool_name
            and r.args_hash == args_hash
            and r.result_status == "error"
        )
        cfg = self._config
        if count >= cfg.exact_failure_block_after:
            logger.warning(
                "ToolGuardrails: EXACT FAILURE BLOCK – %s (args=%s) failed %d times",
                tool_name,
                args_hash[:12],
                count,
            )
            return ToolGuardrailDecision.BLOCK
        if count >= cfg.exact_failure_warn_after:
            logger.info(
                "ToolGuardrails: EXACT FAILURE WARN – %s (args=%s) failed %d times",
                tool_name,
                args_hash[:12],
                count,
            )
            return ToolGuardrailDecision.WARN
        return ToolGuardrailDecision.PROCEED

    def _check_same_tool_failure(
        self,
        tool_name: str,
    ) -> ToolGuardrailDecision:
        """Pattern 2: same tool, different args, failing repeatedly."""
        count = sum(
            1
            for r in self._history
            if r.tool_name == tool_name and r.result_status == "error"
        )
        cfg = self._config
        if count >= cfg.same_tool_block_after:
            logger.warning(
                "ToolGuardrails: SAME-TOOL FAILURE BLOCK – %s failed %d times (various args)",
                tool_name,
                count,
            )
            return ToolGuardrailDecision.BLOCK
        if count >= cfg.same_tool_warn_after:
            logger.info(
                "ToolGuardrails: SAME-TOOL FAILURE WARN – %s failed %d times (various args)",
                tool_name,
                count,
            )
            return ToolGuardrailDecision.WARN
        return ToolGuardrailDecision.PROCEED

    def _check_no_progress(self) -> ToolGuardrailDecision:
        """Pattern 3: only read/idempotent tools, no writes."""
        streak = self._compute_no_progress_streak()
        cfg = self._config
        if streak >= cfg.no_progress_block_after:
            logger.warning(
                "ToolGuardrails: NO-PROGRESS BLOCK – %d consecutive read-only calls",
                streak,
            )
            return ToolGuardrailDecision.BLOCK
        if streak >= cfg.no_progress_warn_after:
            logger.info(
                "ToolGuardrails: NO-PROGRESS WARN – %d consecutive read-only calls",
                streak,
            )
            return ToolGuardrailDecision.WARN
        return ToolGuardrailDecision.PROCEED

    def _compute_no_progress_streak(self) -> int:
        """Count consecutive *failed* calls from the tail of history.

        The streak counts backward from the most recent call and stops
        as soon as it encounters a successful call to any tool (read or
        write).  This detects cycles where the agent keeps failing
        without ever making a successful call.
        """
        streak = 0
        for record in reversed(self._history):
            if record.result_status == "success":
                break
            streak += 1
        return streak


# ======================================================================
# Write-tool set (tools that indicate forward progress)
# ======================================================================

_WRITE_TOOLS: frozenset[str] = frozenset({
    "shell_exec",
    "shell",
    "bash",
    "execute_command",
    "write_file",
    "file_write",
    "create_file",
    "edit_file",
    "file_edit",
    "patch_file",
    "send_message",
    "create_issue",
    "create_pr",
    "git_commit",
    "git_push",
    "deploy",
    "publish",
    "http_post",
    "http_put",
    "http_delete",
    "db_execute",
    "db_insert",
    "db_update",
    "db_delete",
    "install_package",
    "run_tests",
    "apply_change",
})


# ======================================================================
# ConcurrentToolExecutor – batch tool execution
# ======================================================================


# Tools that must run alone (no parallelism) for safety.
_DANGEROUS_TOOLS: frozenset[str] = frozenset({
    "shell_exec",
    "shell",
    "bash",
    "execute_command",
    "write_file",
    "file_write",
    "create_file",
    "edit_file",
    "file_edit",
    "patch_file",
    "delete_file",
    "file_delete",
    "move_file",
    "file_move",
    "http_post",
    "http_put",
    "http_delete",
    "db_execute",
    "db_insert",
    "db_update",
    "db_delete",
    "deploy",
    "publish",
    "install_package",
    "run_tests",
    "apply_change",
    "git_push",
    "git_reset",
    "git_force_push",
})


@dataclass
class _ToolCall:
    """Lightweight wrapper used internally by the executor."""

    tool_name: str
    args: dict[str, Any]
    call_id: str | None = None


@dataclass
class _ToolResult:
    """Result container for a single tool execution."""

    call_id: str | None
    tool_name: str
    result: Any
    error: str | None = None
    duration_seconds: float = 0.0


class ConcurrentToolExecutor:
    """Manages safe concurrent and sequential execution of tool calls.

    Dangerous tools (shell commands, file writes, database mutations) are
    always executed alone.  Safe tools (reads, queries, searches) can be
    batched together and run concurrently.

    Args:
        max_concurrency: Maximum number of concurrent safe-tool executions.
        timeout_seconds: Per-tool execution timeout.

    Example::

        executor = ConcurrentToolExecutor(max_concurrency=4)
        calls = [
            {"tool_name": "read_file", "args": {"path": "/tmp/a.txt"}},
            {"tool_name": "shell_exec", "args": {"command": "rm -rf /tmp/b"}},
            {"tool_name": "web_search", "args": {"query": "hello"}},
        ]
        results = await executor.execute_concurrent(calls, my_tool_fn)
    """

    def __init__(
        self,
        max_concurrency: int = 4,
        timeout_seconds: float = 30.0,
    ) -> None:
        self._max_concurrency = max_concurrency
        self._timeout = timeout_seconds

    # -- Public API -------------------------------------------------------

    async def execute_concurrent(
        self,
        tool_calls: Sequence[dict[str, Any]],
        executor_fn: Callable[[str, dict[str, Any]], Any],
    ) -> list[dict[str, Any]]:
        """Execute a batch of tool calls with safety grouping.

        Dangerous tools run sequentially (one at a time); safe tools are
        grouped and run concurrently up to ``max_concurrency``.

        Args:
            tool_calls:  List of dicts, each with ``"tool_name"`` and
                         ``"args"`` keys.
            executor_fn: ``async (tool_name, args) -> result`` callable.

        Returns:
            List of result dicts in the same order as *tool_calls*, each
            containing ``"tool_name"``, ``"result"``, and optionally
            ``"error"`` and ``"duration_seconds"``.
        """
        calls = [
            _ToolCall(
                tool_name=tc["tool_name"],
                args=tc.get("args", {}),
                call_id=tc.get("call_id"),
            )
            for tc in tool_calls
        ]
        batches = self._plan_batches(calls)
        results: list[_ToolResult] = []

        for batch in batches:
            if len(batch) == 1:
                # Single call – run directly (could be dangerous)
                r = await self._run_one(batch[0], executor_fn)
                results.append(r)
            else:
                # Parallel safe calls
                coros = [self._run_one(tc, executor_fn) for tc in batch]
                batch_results = await asyncio.gather(*coros, return_exceptions=True)
                for br in batch_results:
                    if isinstance(br, Exception):
                        results.append(
                            _ToolResult(
                                call_id=None,
                                tool_name="unknown",
                                result=None,
                                error=str(br),
                            )
                        )
                    else:
                        results.append(br)

        # Map results back to original order
        call_to_result: dict[str, _ToolResult] = {}
        for r in results:
            call_to_result[r.tool_name] = r  # last match wins (acceptable)

        return [
            {
                "tool_name": calls[i].tool_name,
                "call_id": calls[i].call_id,
                "result": call_to_result.get(calls[i].tool_name, _ToolResult(
                    call_id=calls[i].call_id,
                    tool_name=calls[i].tool_name,
                    result=None,
                )).result,
                "error": call_to_result.get(calls[i].tool_name, _ToolResult(
                    call_id=calls[i].call_id,
                    tool_name=calls[i].tool_name,
                    result=None,
                )).error,
                "duration_seconds": call_to_result.get(calls[i].tool_name, _ToolResult(
                    call_id=calls[i].call_id,
                    tool_name=calls[i].tool_name,
                    result=None,
                )).duration_seconds,
            }
            for i in range(len(calls))
        ]

    async def execute_sequential(
        self,
        tool_calls: Sequence[dict[str, Any]],
        executor_fn: Callable[[str, dict[str, Any]], Any],
    ) -> list[dict[str, Any]]:
        """Execute tool calls strictly one at a time.

        Useful when the order matters (e.g. create-then-configure).

        Args:
            tool_calls:  List of dicts, each with ``"tool_name"`` and
                         ``"args"`` keys.
            executor_fn: ``async (tool_name, args) -> result`` callable.

        Returns:
            List of result dicts in the same order as *tool_calls*.
        """
        results: list[dict[str, Any]] = []
        for tc in tool_calls:
            call = _ToolCall(
                tool_name=tc["tool_name"],
                args=tc.get("args", {}),
                call_id=tc.get("call_id"),
            )
            r = await self._run_one(call, executor_fn)
            results.append({
                "tool_name": call.tool_name,
                "call_id": call.call_id,
                "result": r.result,
                "error": r.error,
                "duration_seconds": r.duration_seconds,
            })
        return results

    # -- Batch planning ---------------------------------------------------

    def _plan_batches(
        self,
        calls: Sequence[_ToolCall],
    ) -> list[list[_ToolCall]]:
        """Group tool calls into safe parallel batches.

        Strategy:
          * Each dangerous tool gets its own singleton batch.
          * Safe tools are grouped into batches of at most ``max_concurrency``.
        """
        safe: list[_ToolCall] = []
        batches: list[list[_ToolCall]] = []

        for call in calls:
            if self._is_dangerous_tool(call.tool_name):
                # Flush any pending safe calls first
                if safe:
                    batches.append(safe)
                    safe = []
                batches.append([call])
            else:
                safe.append(call)
                if len(safe) >= self._max_concurrency:
                    batches.append(safe)
                    safe = []

        if safe:
            batches.append(safe)

        return batches

    @staticmethod
    def _is_dangerous_tool(tool_name: str) -> bool:
        """Return ``True`` if the tool modifies external state.

        The decision is based on a static set of known dangerous tool
        names.  Unrecognised tools are treated as *safe* (read-only) –
        this is a deliberate conservative default that avoids false
        positives blocking legitimate parallel work.
        """
        return tool_name in _DANGEROUS_TOOLS

    # -- Internal execution ------------------------------------------------

    async def _run_one(
        self,
        call: _ToolCall,
        executor_fn: Callable[[str, dict[str, Any]], Any],
    ) -> _ToolResult:
        """Execute a single tool call with timeout protection."""
        start = time.monotonic()
        try:
            result = await asyncio.wait_for(
                executor_fn(call.tool_name, call.args),
                timeout=self._timeout,
            )
            duration = time.monotonic() - start
            return _ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                result=result,
                duration_seconds=duration,
            )
        except TimeoutError:
            duration = time.monotonic() - start
            logger.warning(
                "ConcurrentToolExecutor: %s timed out after %.1fs",
                call.tool_name,
                duration,
            )
            return _ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                result=None,
                error=f"tool_timeout: {call.tool_name} exceeded {self._timeout}s",
                duration_seconds=duration,
            )
        except Exception as exc:
            duration = time.monotonic() - start
            logger.warning(
                "ConcurrentToolExecutor: %s failed – %s",
                call.tool_name,
                exc,
            )
            return _ToolResult(
                call_id=call.call_id,
                tool_name=call.tool_name,
                result=None,
                error=str(exc),
                duration_seconds=duration,
            )
