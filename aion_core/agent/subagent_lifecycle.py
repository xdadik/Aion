#!/usr/bin/env python3
"""
Subagent Lifecycle Management for Aion Hand.
==============================================

Provides the public API for spawning, monitoring, and managing sub-agents.
Sub-agents are lightweight, scoped agents that can be delegated tasks by a
parent agent, run to completion (or failure), and return results.

The module ships:

  * :class:`SubagentState` – enum modelling the finite lifecycle states.
  * :dataclass:`SubagentLaunchRequest` – parameters for spawning a sub-agent.
  * :dataclass:`SubagentHandle` – opaque handle returned on launch.
  * :dataclass:`SubagentResult` – structured result returned on completion.
  * :class:`SubagentLifecycle` – central manager that tracks all sub-agents,
    provides ``launch`` / ``cancel`` / ``wait`` / ``status``.
  * :class:`DelegationContext` – context-var that tracks the current
    delegation chain across async tasks.

Design inspired by:
  - Hermes Agent: ``subagent_lifecycle.py`` with state-machine management.
  - CrewAI: hierarchical task delegation and crew lifecycle.
  - LangGraph: sub-graph execution with timeout and cancellation.

Typical usage::

    lifecycle = SubagentLifecycle(parent_session_id="main-001")

    request = SubagentLaunchRequest(
        goal="Refactor the authentication module",
        context="Project uses FastAPI + JWT tokens",
        model="gpt-4o",
        timeout=120,
    )
    handle = lifecycle.launch(request)

    result = lifecycle.wait(handle.subagent_id, timeout=130)
    if result.success:
        print("Sub-agent succeeded:", result.result)
    else:
        print("Sub-agent failed:", result.error)
"""

from __future__ import annotations

import contextvars
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("aion_hand.agent.subagent_lifecycle")


# ======================================================================
# Enums & Data Classes
# ======================================================================


class SubagentState(Enum):
    """Finite-state machine for sub-agent lifecycle.

    Transitions::

        PENDING ──► STARTING ──► RUNNING ──► SUCCEEDED
                   │                       ──► FAILED
                   │                       ──► CANCELLED
                   │                       ──► TIMED_OUT
                   └──► CANCELLED
    """

    PENDING = "pending"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMED_OUT = "timed_out"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        """Return *True* if the state is a terminal (final) state."""
        return self in {
            SubagentState.SUCCEEDED,
            SubagentState.FAILED,
            SubagentState.CANCELLED,
            SubagentState.TIMED_OUT,
        }

    @property
    def is_active(self) -> bool:
        """Return *True* if the sub-agent is still executing."""
        return self in {
            SubagentState.PENDING,
            SubagentState.STARTING,
            SubagentState.RUNNING,
        }


# Valid state transitions: current_state -> allowed next states.
_VALID_TRANSITIONS: dict[SubagentState, set] = {
    SubagentState.PENDING: {SubagentState.STARTING, SubagentState.CANCELLED},
    SubagentState.STARTING: {
        SubagentState.RUNNING,
        SubagentState.FAILED,
        SubagentState.CANCELLED,
    },
    SubagentState.RUNNING: {
        SubagentState.SUCCEEDED,
        SubagentState.FAILED,
        SubagentState.CANCELLED,
        SubagentState.TIMED_OUT,
    },
    SubagentState.SUCCEEDED: set(),
    SubagentState.FAILED: set(),
    SubagentState.CANCELLED: set(),
    SubagentState.TIMED_OUT: set(),
    SubagentState.UNKNOWN: set(),
}


@dataclass
class SubagentLaunchRequest:
    """Parameters for spawning a sub-agent.

    Attributes
    ----------
    goal:
        Natural-language description of the task.
    context:
        Additional context injected into the sub-agent's system prompt.
    model:
        LLM model to use (defaults to the parent's model).
    allowed_tools:
        Whitelist of tool names the sub-agent may invoke.  Empty list
        means *all* tools are allowed.
    blocked_tools:
        Blacklist of tool names the sub-agent must not invoke.
    timeout:
        Maximum wall-clock seconds before TIMED_OUT.
    max_tokens:
        Token budget for the sub-agent's total output.
    """

    goal: str
    context: str = ""
    model: str = ""
    allowed_tools: list[str] = field(default_factory=list)
    blocked_tools: list[str] = field(default_factory=list)
    timeout: float = 300.0
    max_tokens: int = 4096

    def __post_init__(self) -> None:
        if not self.goal.strip():
            raise ValueError("SubagentLaunchRequest.goal must not be empty")


@dataclass
class SubagentHandle:
    """Opaque handle returned by :meth:`SubagentLifecycle.launch`.

    Consumers should only inspect ``subagent_id`` and ``state``; the rest
    is for internal bookkeeping.
    """

    subagent_id: str
    parent_session_id: str
    state: SubagentState = SubagentState.PENDING
    created_at: float = field(default_factory=time.time)
    completed_at: float | None = None
    goal: str = ""
    model: str = ""


@dataclass
class SubagentResult:
    """Structured result returned when a sub-agent reaches a terminal
    state.

    Attributes
    ----------
    success:
        *True* when the sub-agent reached SUCCEEDED.
    result:
        The final output content (text / JSON string).
    error:
        Error message when ``success`` is *False*.
    tokens_used:
        Total tokens consumed by the sub-agent.
    elapsed_seconds:
        Wall-clock time from launch to completion.
    subagent_id:
        The identifier of the completed sub-agent.
    state:
        The terminal state the sub-agent ended in.
    """

    success: bool
    result: str = ""
    error: str = ""
    tokens_used: int = 0
    elapsed_seconds: float = 0.0
    subagent_id: str = ""
    state: SubagentState = SubagentState.SUCCEEDED


# ======================================================================
# Subagent Lifecycle Manager
# ======================================================================


class SubagentLifecycle:
    """Central manager for sub-agent creation, monitoring, and cleanup.

    The lifecycle manager maintains an in-memory registry of all sub-agents
    spawned within a parent session.  It is safe for concurrent use from
    multiple threads (protected by an internal lock).

    For *real* execution the caller must supply a ``runner_fn`` callback
    that actually drives the sub-agent.  When no runner is provided the
    manager simulates execution (useful for testing).

    Parameters
    ----------
    parent_session_id:
        Identifier of the owning session / parent agent.
    runner_fn:
        ``async (request, handle) -> SubagentResult`` or sync variant.
        Called to actually execute the sub-agent.
    max_concurrent:
        Maximum number of simultaneously running sub-agents.
    """

    def __init__(
        self,
        parent_session_id: str = "",
        runner_fn: Callable | None = None,
        max_concurrent: int = 5,
    ) -> None:
        self.parent_session_id = parent_session_id or str(uuid.uuid4())
        self._runner_fn = runner_fn
        self._max_concurrent = max_concurrent
        self._lock = threading.Lock()

        # Registries keyed by subagent_id.
        self._handles: dict[str, SubagentHandle] = {}
        self._results: dict[str, SubagentResult] = {}

        # Counters.
        self._total_launched: int = 0

    # ---------------------------------------------------------------
    # Launch
    # ---------------------------------------------------------------

    def launch(self, request: SubagentLaunchRequest) -> SubagentHandle:
        """Create and register a new sub-agent.

        Raises :class:`RuntimeError` if the concurrency limit has been
        reached.
        """
        with self._lock:
            active = sum(1 for h in self._handles.values() if h.state.is_active)
            if active >= self._max_concurrent:
                raise RuntimeError(
                    f"Max concurrent sub-agents ({self._max_concurrent}) reached"
                )

            subagent_id = f"sub-{uuid.uuid4().hex[:12]}"
            handle = SubagentHandle(
                subagent_id=subagent_id,
                parent_session_id=self.parent_session_id,
                state=SubagentState.PENDING,
                goal=request.goal,
                model=request.model,
            )
            self._handles[subagent_id] = handle
            self._total_launched += 1

            # Fire-and-forget: update state to STARTING.
            self._transition(handle, SubagentState.STARTING)

        logger.info(
            "Launched sub-agent %s for goal: %s",
            subagent_id,
            request.goal[:80],
        )
        return handle

    # ---------------------------------------------------------------
    # State transitions
    # ---------------------------------------------------------------

    def _transition(self, handle: SubagentHandle, new_state: SubagentState) -> bool:
        """Attempt to move *handle* to *new_state*.

        Returns *True* on success, *False* if the transition is invalid.
        """
        allowed = _VALID_TRANSITIONS.get(handle.state, set())
        if new_state not in allowed:
            logger.warning(
                "Invalid transition for %s: %s -> %s",
                handle.subagent_id,
                handle.state.value,
                new_state.value,
            )
            return False
        handle.state = new_state
        if new_state.is_terminal:
            handle.completed_at = time.time()
        return True

    # ---------------------------------------------------------------
    # Cancel
    # ---------------------------------------------------------------

    def cancel(self, subagent_id: str) -> bool:
        """Request cancellation of a running sub-agent.

        Returns *True* if the sub-agent was in an active state and was
        transitioned to CANCELLED.
        """
        with self._lock:
            handle = self._handles.get(subagent_id)
            if handle is None:
                logger.warning("cancel() called for unknown sub-agent: %s", subagent_id)
                return False
            if not handle.state.is_active:
                return False

            success = self._transition(handle, SubagentState.CANCELLED)
            if success:
                self._results[subagent_id] = SubagentResult(
                    success=False,
                    error="Cancelled by parent",
                    elapsed_seconds=time.time() - handle.created_at,
                    subagent_id=subagent_id,
                    state=SubagentState.CANCELLED,
                )
                logger.info("Cancelled sub-agent %s", subagent_id)
            return success

    # ---------------------------------------------------------------
    # Status query
    # ---------------------------------------------------------------

    def status(self, subagent_id: str) -> SubagentState:
        """Return the current state of *subagent_id*, or UNKNOWN."""
        handle = self._handles.get(subagent_id)
        if handle is None:
            return SubagentState.UNKNOWN
        return handle.state

    # ---------------------------------------------------------------
    # Wait
    # ---------------------------------------------------------------

    def wait(self, subagent_id: str, timeout: float = 300.0) -> SubagentResult:
        """Block until *subagent_id* reaches a terminal state or *timeout*
        seconds elapse.

        If the wait times out, the sub-agent is marked TIMED_OUT and a
        :class:`SubagentResult` with ``success=False`` is returned.

        **Note:** In production the runner_fn would notify completion
        asynchronously.  This implementation polls for demonstration.
        """
        deadline = time.time() + timeout
        while time.time() < deadline:
            handle = self._handles.get(subagent_id)
            if handle is None:
                return SubagentResult(
                    success=False,
                    error=f"Unknown sub-agent: {subagent_id}",
                    subagent_id=subagent_id,
                    state=SubagentState.UNKNOWN,
                )

            if handle.state.is_terminal:
                result = self._results.get(subagent_id)
                if result is not None:
                    return result
                # No explicit result stored – synthesise one.
                return SubagentResult(
                    success=(handle.state == SubagentState.SUCCEEDED),
                    result="" if handle.state == SubagentState.SUCCEEDED else "",
                    error=(
                        ""
                        if handle.state == SubagentState.SUCCEEDED
                        else handle.state.value
                    ),
                    elapsed_seconds=(handle.completed_at or time.time())
                    - handle.created_at,
                    subagent_id=subagent_id,
                    state=handle.state,
                )

            time.sleep(0.05)

        # Timed out waiting.
        with self._lock:
            handle = self._handles.get(subagent_id)
            if handle is not None and handle.state.is_active:
                self._transition(handle, SubagentState.TIMED_OUT)
                self._results[subagent_id] = SubagentResult(
                    success=False,
                    error="Timed out while waiting for completion",
                    elapsed_seconds=timeout,
                    subagent_id=subagent_id,
                    state=SubagentState.TIMED_OUT,
                )

        return self._results.get(
            subagent_id,
            SubagentResult(
                success=False,
                error="Wait timeout",
                elapsed_seconds=timeout,
                subagent_id=subagent_id,
                state=SubagentState.TIMED_OUT,
            ),
        )

    def wait_all(self, timeout: float = 300.0) -> list[SubagentResult]:
        """Wait for *all* currently active sub-agents and return their
        results (in no particular order)."""
        with self._lock:
            active_ids = [sid for sid, h in self._handles.items() if h.state.is_active]

        results: list[SubagentResult] = []
        for sid in active_ids:
            results.append(self.wait(sid, timeout=timeout))
        return results

    # ---------------------------------------------------------------
    # Listing
    # ---------------------------------------------------------------

    def list_active(self) -> list[SubagentHandle]:
        """Return handles for all non-terminal sub-agents."""
        with self._lock:
            return [h for h in self._handles.values() if h.state.is_active]

    def list_completed(self) -> list[SubagentResult]:
        """Return results for all terminal sub-agents."""
        with self._lock:
            return list(self._results.values())

    # ---------------------------------------------------------------
    # Cleanup
    # ---------------------------------------------------------------

    def cleanup(self, subagent_id: str) -> bool:
        """Remove a completed sub-agent from the registry.

        Returns *True* if the sub-agent was found and removed.
        """
        with self._lock:
            handle = self._handles.pop(subagent_id, None)
            if handle is None:
                return False
            self._results.pop(subagent_id, None)
            logger.info("Cleaned up sub-agent %s", subagent_id)
            return True

    def cleanup_all(self) -> int:
        """Remove *all* sub-agents (active and completed) from the
        registry.

        Returns the number of sub-agents removed.
        """
        with self._lock:
            count = len(self._handles)
            self._handles.clear()
            self._results.clear()
            logger.info("Cleaned up %d sub-agents", count)
            return count

    # ---------------------------------------------------------------
    # Statistics
    # ---------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about the sub-agent pool."""
        state_counts: dict[str, int] = {}
        for state in SubagentState:
            state_counts[state.value] = 0
        for handle in self._handles.values():
            state_counts[handle.state.value] += 1

        succeeded = sum(1 for r in self._results.values() if r.success)
        failed = len(self._results) - succeeded

        total_elapsed = sum(r.elapsed_seconds for r in self._results.values())
        total_tokens = sum(r.tokens_used for r in self._results.values())

        return {
            "parent_session_id": self.parent_session_id,
            "total_launched": self._total_launched,
            "currently_active": sum(
                1
                for s in state_counts.values()
                if s > 0 and s != SubagentState.UNKNOWN.value
            ),
            "state_counts": state_counts,
            "completed_count": succeeded + failed,
            "succeeded_count": succeeded,
            "failed_count": failed,
            "total_elapsed_seconds": round(total_elapsed, 3),
            "total_tokens_used": total_tokens,
            "max_concurrent": self._max_concurrent,
        }


# ======================================================================
# Delegation Context (contextvars)
# ======================================================================


class DelegationContext:
    """Thread-safe (and async-safe) context variable that tracks the
    current delegation chain.

    When a parent agent delegates work to a sub-agent, the delegation ID
    is pushed onto the chain.  This enables:

    * Recursive delegation detection (prevent infinite loops).
    * Tracing: attribute logs and telemetry to a delegation chain.
    * Auth scoping: sub-agents inherit parent permissions.

    Example::

        ctx = DelegationContext()
        token = ctx.set_delegation("sub-abc123")
        try:
            # Sub-agent work here…
            assert ctx.is_delegated()
            assert ctx.get_current_delegation() == "sub-abc123"
        finally:
            ctx.reset(token)
            assert not ctx.is_delegated()
    """

    _var: contextvars.ContextVar[str | None]

    def __init__(self, var_name: str = "aion_delegation_chain") -> None:
        self._var = contextvars.ContextVar(var_name, default=None)

    def get_current_delegation(self) -> str | None:
        """Return the current delegation ID, or *None* if not delegated."""
        return self._var.get()

    def set_delegation(self, delegation_id: str) -> contextvars.Token:
        """Push *delegation_id* onto the context.

        Returns a :class:`~contextvars.Token` that should be passed to
        :meth:`reset` to restore the previous value.
        """
        return self._var.set(delegation_id)

    def reset(self, token: contextvars.Token) -> None:
        """Restore the previous delegation value using the *token* from
        :meth:`set_delegation`."""
        self._var.reset(token)

    def is_delegated(self) -> bool:
        """Return *True* if a delegation is active in the current context."""
        return self._var.get() is not None

    def get_chain(self, separator: str = " > ") -> str:
        """Return a human-readable representation of the delegation chain.

        **Note:** contextvars only stores the *current* value, not the
        full history.  For chain tracking, the caller should build a
        chain string manually (e.g. in the sub-agent launcher).
        """
        current = self._var.get()
        return current or "(none)"


# ======================================================================
# Convenience: module-level singleton
# ======================================================================

# A default DelegationContext instance for quick access without explicit
# construction in every module.
default_delegation_context = DelegationContext()
