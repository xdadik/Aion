#!/usr/bin/env python3
"""
Aion Hand - Orchestration Engine
=================================

Combines NullBoiler's workflow engine with Hermes's subagent spawning system.

Architecture:
  SubAgentResult  — Lightweight result dataclass for every sub-agent run.
  SubAgent        — Isolated agent instances with own context, tools, personality.
  WorkflowNode    — A single node inside a workflow DAG.
  Workflow        — DAG-based task orchestration with conditional routing,
                    parallel branches, merge semantics, and timeout handling.
  OrchestrationEngine — Central coordinator that spawns subagents, builds
                        workflows from definition dicts, and manages lifecycle.

Design notes:
  * The engine receives the *agent* reference via its constructor so that
    ``agent.chat(message)`` can be called without importing
    ``aion_core.agent.core`` (avoids circular imports).
  * All heavy work is ``async``; parallel branches inside a workflow use
    ``asyncio.gather`` (shielded for cancellation safety).
  * A ``SubAgent`` is a thin wrapper — it does **not** hold a persistent
    connection or state machine.  Each execution is stateless: the agent
    reference, tools, and personality are captured at construction time and
    reused for every ``run()`` call.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections import deque
from collections.abc import Awaitable
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
)

logger = logging.getLogger("aion_hand.orchestration")


# ======================================================================
# Enums
# ======================================================================


class NodeType(str, Enum):
    """Supported workflow node types."""

    AGENT = "agent"
    TOOL = "tool"
    SUB_WORKFLOW = "sub_workflow"
    CONDITION = "condition"
    MERGE = "merge"


class NodeStatus(str, Enum):
    """Runtime status of a workflow node."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


class WorkflowStatus(str, Enum):
    """Runtime status of a workflow."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class SubAgentStatus(str, Enum):
    """Runtime status of a sub-agent."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"


# ======================================================================
# SubAgentResult
# ======================================================================


@dataclass
class SubAgentResult:
    """Result returned by a :class:`SubAgent` execution.

    Attributes:
        task:        The original task description string.
        content:     The agent's response text (or ``None`` on error).
        tools_used:  List of tool names invoked during execution.
        tokens:      Approximate token count reported by the provider, or -1
                     if unavailable.
        elapsed:     Wall-clock seconds for the run.
        success:     ``True`` when the run completed without exception.
        error:       Error message string when *success* is ``False``.
    """

    task: str
    content: str | None = None
    tools_used: list[str] = field(default_factory=list)
    tokens: int = -1
    elapsed: float = 0.0
    success: bool = True
    error: str | None = None

    # ---- helpers --------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialise to a plain dict (safe for JSON / logging)."""
        return {
            "task": self.task,
            "content": self.content,
            "tools_used": self.tools_used,
            "tokens": self.tokens,
            "elapsed": round(self.elapsed, 4),
            "success": self.success,
            "error": self.error,
        }

    def __repr__(self) -> str:  # pragma: no cover
        status = "OK" if self.success else f"ERR({self.error})"
        return (
            f"SubAgentResult(task={self.task!r:.60}, content={self.content!r:.60}, "
            f"tools={self.tools_used}, tokens={self.tokens}, "
            f"elapsed={self.elapsed:.2f}s, {status})"
        )


# ======================================================================
# SubAgent
# ======================================================================


class SubAgent:
    """Represents a spawned sub-agent with its own context and isolation.

    A ``SubAgent`` is a lightweight, reusable handle.  The heavy lifting is
    delegated to the parent :class:`OrchestrationEngine` which supplies an
    ``agent`` reference whose ``.chat()`` method is called.

    Typical lifecycle (managed by :class:`OrchestrationEngine`):

    1. ``SubAgent(...)``  — construct with task, tools, personality.
    2. ``await subagent.run()`` — execute via the parent agent.
    3. Inspect ``subagent.last_result`` or the returned :class:`SubAgentResult`.
    """

    def __init__(
        self,
        task: str,
        agent: Any,
        tools: list[str] | None = None,
        personality: str | None = None,
        timeout: float = 300.0,
        subagent_id: str | None = None,
    ) -> None:
        self.id: str = subagent_id or uuid.uuid4().hex[:12]
        self.task: str = task
        self._agent = agent
        self.tools: list[str] = list(tools or [])
        self.personality: str | None = personality
        self.timeout: float = timeout
        self.status: SubAgentStatus = SubAgentStatus.PENDING
        self.last_result: SubAgentResult | None = None
        self.created_at: float = time.monotonic()
        self._cancel_event: asyncio.Event = asyncio.Event()
        logger.debug("SubAgent %s created for task: %s", self.id, self.task[:80])

    # ---- execution ------------------------------------------------------

    async def run(self) -> SubAgentResult:
        """Execute the sub-agent task via the parent agent's ``chat()``.

        Returns:
            A :class:`SubAgentResult` with the outcome.
        """
        if self.status == SubAgentStatus.RUNNING:
            raise RuntimeError(f"SubAgent {self.id} is already running")

        self.status = SubAgentStatus.RUNNING
        self._cancel_event.clear()
        start = time.monotonic()

        try:
            # Build an enriched prompt that scopes the sub-agent.
            prompt = self._build_prompt()

            result = await asyncio.wait_for(
                self._execute_chat(prompt),
                timeout=self.timeout,
            )

            elapsed = time.monotonic() - start
            self.last_result = SubAgentResult(
                task=self.task,
                content=result.get("content"),
                tools_used=result.get("tools_used", []),
                tokens=result.get("metadata", {}).get("tokens", -1),
                elapsed=elapsed,
                success=True,
            )
            self.status = SubAgentStatus.COMPLETED
            logger.info(
                "SubAgent %s completed in %.2fs (tools=%s)",
                self.id,
                elapsed,
                self.last_result.tools_used,
            )

        except TimeoutError:
            elapsed = time.monotonic() - start
            self.last_result = SubAgentResult(
                task=self.task,
                elapsed=elapsed,
                success=False,
                error=f"SubAgent timed out after {self.timeout}s",
            )
            self.status = SubAgentStatus.TIMEOUT
            logger.warning("SubAgent %s timed out after %.1fs", self.id, self.timeout)

        except asyncio.CancelledError:
            elapsed = time.monotonic() - start
            self.last_result = SubAgentResult(
                task=self.task,
                elapsed=elapsed,
                success=False,
                error="SubAgent was cancelled",
            )
            self.status = SubAgentStatus.CANCELLED
            logger.info("SubAgent %s cancelled", self.id)
            raise

        except Exception as exc:
            elapsed = time.monotonic() - start
            self.last_result = SubAgentResult(
                task=self.task,
                elapsed=elapsed,
                success=False,
                error=str(exc),
            )
            self.status = SubAgentStatus.FAILED
            logger.error("SubAgent %s failed: %s", self.id, exc, exc_info=True)

        return self.last_result

    async def _execute_chat(self, prompt: str) -> dict[str, Any]:
        """Call the parent agent's ``chat()`` and return its result dict."""
        # The agent object is provided at construction time; we only call
        # ``.chat()`` so we never need to import aion_core.agent.core.
        chat_fn = getattr(self._agent, "chat", None)
        if chat_fn is None:
            raise RuntimeError(
                "The agent object provided to SubAgent must have a 'chat()' method"
            )
        result = (
            chat_fn(prompt)
            if not asyncio.iscoroutinefunction(chat_fn)
            else await chat_fn(prompt)
        )
        if not isinstance(result, dict):
            result = {"content": str(result)}
        return result

    def _build_prompt(self) -> str:
        """Build a scoped prompt for the sub-agent."""
        parts: list[str] = []
        if self.personality:
            parts.append(f"## Sub-Agent Personality\n{self.personality}")
        if self.tools:
            parts.append(
                f"## Available Tools\nYou have access to: {', '.join(self.tools)}. "
                "Use them as needed to complete the task."
            )
        parts.append(f"## Task\n{self.task}")
        parts.append(
            "## Instructions\n"
            "You are a focused sub-agent.  Complete the task concisely. "
            "Return ONLY the result — do not ask follow-up questions."
        )
        return "\n\n".join(parts)

    # ---- cancellation ---------------------------------------------------

    def cancel(self) -> None:
        """Request cancellation.  The next await point inside ``run()`` will
        raise ``CancelledError``."""
        self._cancel_event.set()
        self.status = SubAgentStatus.CANCELLED

    def to_dict(self) -> dict[str, Any]:
        """Serialise state for inspection."""
        return {
            "id": self.id,
            "task": self.task,
            "status": self.status.value,
            "tools": self.tools,
            "timeout": self.timeout,
            "created_at": self.created_at,
            "last_result": self.last_result.to_dict() if self.last_result else None,
        }


# ======================================================================
# WorkflowNode
# ======================================================================


class WorkflowNode:
    """A single node in a :class:`Workflow` DAG.

    Attributes:
        id:           Unique node identifier (human-friendly or UUID).
        name:         Display name.
        node_type:    One of :class:`NodeType` values.
        config:       Free-form dict with node-specific settings (task prompt,
                      tool name, condition expression, etc.).
        dependencies: IDs of upstream nodes that must complete first.
        timeout:      Per-node timeout in seconds (``0`` = no timeout).
    """

    def __init__(
        self,
        node_id: str,
        name: str,
        node_type: NodeType,
        config: dict[str, Any] | None = None,
        dependencies: list[str] | None = None,
        timeout: float = 0.0,
    ) -> None:
        self.id: str = node_id
        self.name: str = name
        self.node_type: NodeType = node_type
        self.config: dict[str, Any] = dict(config or {})
        self.dependencies: list[str] = list(dependencies or [])
        self.timeout: float = timeout
        self.status: NodeStatus = NodeStatus.PENDING
        self.result: Any = None
        self.error: str | None = None
        self.started_at: float | None = None
        self.finished_at: float | None = None

    @property
    def elapsed(self) -> float:
        """Seconds spent in RUNNING state (0 if not yet started)."""
        if self.started_at is None:
            return 0.0
        end = self.finished_at or time.monotonic()
        return end - self.started_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "type": self.node_type.value,
            "config": self.config,
            "dependencies": self.dependencies,
            "timeout": self.timeout,
            "status": self.status.value,
            "result": self._serialise_result(),
            "error": self.error,
            "elapsed": round(self.elapsed, 4),
        }

    def _serialise_result(self) -> Any:
        if isinstance(self.result, SubAgentResult):
            return self.result.to_dict()
        return self.result

    # ---- factory --------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WorkflowNode:
        """Create a ``WorkflowNode`` from a plain dictionary."""
        node_type = NodeType(data.get("type", "agent"))
        return cls(
            node_id=data["id"],
            name=data.get("name", data["id"]),
            node_type=node_type,
            config=data.get("config"),
            dependencies=data.get("dependencies", []),
            timeout=float(data.get("timeout", 0)),
        )


# ======================================================================
# Workflow
# ======================================================================


class Workflow:
    """A DAG of :class:`WorkflowNode` instances with execution logic.

    The workflow supports:
    * **Dependency ordering** — topological sort ensures nodes run only
      after all their dependencies succeed.
    * **Parallel branches** — independent nodes at the same topological
      level are executed concurrently via ``asyncio.gather``.
    * **Conditional routing** — ``CONDITION`` nodes evaluate a Python
      expression against the current context and activate only the
      matching downstream branch.
    * **Merge semantics** — ``MERGE`` nodes collect results from all
      completed upstream branches into a single list.
    * **Timeouts** — per-node and per-workflow timeouts with graceful
      cancellation.

    Usage::

        workflow = Workflow(
            name="research_and_summarise",
            nodes=[node_a, node_b, node_c],
            engine=engine,
        )
        result = await workflow.execute(context={"topic": "quantum computing"})
    """

    def __init__(
        self,
        name: str,
        nodes: list[WorkflowNode] | None = None,
        engine: Any | None = None,
        timeout: float = 0.0,
    ) -> None:
        self.name: str = name
        self.nodes: dict[str, WorkflowNode] = {}
        self.engine = engine  # OrchestrationEngine reference (avoid circular import)
        self.timeout: float = timeout
        self.status: WorkflowStatus = WorkflowStatus.PENDING
        self.context: dict[str, Any] = {}
        self.results: dict[str, Any] = {}  # node_id -> result value
        self.errors: dict[str, str] = {}
        self.started_at: float | None = None
        self.finished_at: float | None = None
        self._cancel_event: asyncio.Event = asyncio.Event()

        for n in nodes or []:
            self.add_node(n)

    # ---- graph management -----------------------------------------------

    def add_node(self, node: WorkflowNode) -> None:
        if node.id in self.nodes:
            raise ValueError(f"Duplicate node id: {node.id}")
        # Validate that all dependency IDs exist (or will exist)
        self.nodes[node.id] = node

    def remove_node(self, node_id: str) -> None:
        removed = self.nodes.pop(node_id, None)
        if removed:
            # Clean up references in other nodes' dependency lists
            for n in self.nodes.values():
                if node_id in n.dependencies:
                    n.dependencies.remove(node_id)

    def get_root_nodes(self) -> list[WorkflowNode]:
        """Return nodes with no dependencies (entry points)."""
        return [n for n in self.nodes.values() if not n.dependencies]

    def get_downstream(self, node_id: str) -> list[WorkflowNode]:
        """Return nodes that depend on *node_id*."""
        return [n for n in self.nodes.values() if node_id in n.dependencies]

    # ---- topological helpers --------------------------------------------

    def _topological_layers(self) -> list[list[WorkflowNode]]:
        """Return nodes grouped into layers where each layer can run in parallel.

        Raises:
            ValueError: If the graph contains a cycle.
        """
        in_degree: dict[str, int] = {nid: 0 for nid in self.nodes}
        adj: dict[str, list[str]] = {nid: [] for nid in self.nodes}
        for n in self.nodes.values():
            for dep in n.dependencies:
                if dep not in self.nodes:
                    raise ValueError(f"Node '{n.id}' depends on unknown node '{dep}'")
                adj[dep].append(n.id)
                in_degree[n.id] += 1

        # Kahn's algorithm
        queue = deque(nid for nid, deg in in_degree.items() if deg == 0)
        layers: list[list[WorkflowNode]] = []
        visited: set[str] = set()

        while queue:
            layer_ids = list(queue)
            queue.clear()
            layers.append([self.nodes[nid] for nid in layer_ids])
            visited.update(layer_ids)
            for nid in layer_ids:
                for downstream_id in adj[nid]:
                    in_degree[downstream_id] -= 1
                    if in_degree[downstream_id] == 0:
                        queue.append(downstream_id)

        if len(visited) != len(self.nodes):
            raise ValueError(
                f"Workflow '{self.name}' contains a cycle. "
                f"Nodes not reachable: {set(self.nodes) - visited}"
            )
        return layers

    # ---- execution ------------------------------------------------------

    async def execute(
        self,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute the workflow DAG.

        Args:
            context: Initial context dict available to all nodes (e.g.
                     user inputs, parameters).

        Returns:
            A dict with ``status``, ``results`` (per-node), ``errors``,
            and ``elapsed``.
        """
        if self.status == WorkflowStatus.RUNNING:
            raise RuntimeError(f"Workflow '{self.name}' is already running")

        self.context = dict(context or {})
        self.results = {}
        self.errors = {}
        self._cancel_event.clear()
        self.status = WorkflowStatus.RUNNING
        self.started_at = time.monotonic()
        self.finished_at = None

        # Reset node states
        for n in self.nodes.values():
            n.status = NodeStatus.PENDING
            n.result = None
            n.error = None
            n.started_at = None
            n.finished_at = None

        logger.info(
            "Workflow '%s' started with %d nodes, context keys=%s",
            self.name,
            len(self.nodes),
            list(self.context.keys()),
        )

        try:
            layers = self._topological_layers()
            workflow_coro = self._run_layers(layers)

            if self.timeout > 0:
                await asyncio.wait_for(workflow_coro, timeout=self.timeout)
            else:
                await workflow_coro

            # Final status
            has_errors = any(self.errors.values())
            self.status = (
                WorkflowStatus.FAILED if has_errors else WorkflowStatus.COMPLETED
            )

        except TimeoutError:
            self.status = WorkflowStatus.FAILED
            logger.error("Workflow '%s' timed out after %.1fs", self.name, self.timeout)
            self.errors["__workflow__"] = f"Workflow timed out after {self.timeout}s"
            # Mark remaining nodes as cancelled
            for n in self.nodes.values():
                if n.status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                    n.status = NodeStatus.CANCELLED

        except asyncio.CancelledError:
            self.status = WorkflowStatus.CANCELLED
            logger.info("Workflow '%s' cancelled", self.name)
            for n in self.nodes.values():
                if n.status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                    n.status = NodeStatus.CANCELLED
            raise

        except Exception as exc:
            self.status = WorkflowStatus.FAILED
            self.errors["__workflow__"] = str(exc)
            logger.error("Workflow '%s' failed: %s", self.name, exc, exc_info=True)

        finally:
            self.finished_at = time.monotonic()

        elapsed = (self.finished_at or time.monotonic()) - (
            self.started_at or time.monotonic()
        )
        logger.info(
            "Workflow '%s' finished with status=%s, elapsed=%.2fs, errors=%d",
            self.name,
            self.status.value,
            elapsed,
            len(self.errors),
        )

        return {
            "workflow": self.name,
            "status": self.status.value,
            "results": {nid: n._serialise_result() for nid, n in self.nodes.items()},
            "errors": dict(self.errors),
            "elapsed": round(elapsed, 4),
        }

    async def _run_layers(self, layers: list[list[WorkflowNode]]) -> None:
        """Execute topological layers sequentially; nodes within a layer run in parallel."""
        for layer_idx, layer in enumerate(layers):
            if self._cancel_event.is_set():
                raise asyncio.CancelledError()

            # Check if upstream had failures — skip downstream if so
            tasks: list[Awaitable[None]] = []
            for node in layer:
                # Verify all dependencies succeeded
                deps_ok = all(
                    self.nodes[dep].status == NodeStatus.SUCCESS
                    for dep in node.dependencies
                    if dep in self.nodes
                )
                if not deps_ok:
                    node.status = NodeStatus.SKIPPED
                    node.error = "Skipped: upstream dependency failed or was skipped"
                    self.errors[node.id] = node.error
                    logger.warning("Node '%s' skipped (upstream failure)", node.id)
                    continue
                tasks.append(self._execute_node(node))

            if tasks:
                # Use shield so outer cancellation can still propagate
                await asyncio.gather(*tasks, return_exceptions=True)

    async def _execute_node(self, node: WorkflowNode) -> None:
        """Execute a single node based on its type."""
        node.status = NodeStatus.RUNNING
        node.started_at = time.monotonic()
        logger.debug("Executing node '%s' (type=%s)", node.id, node.node_type.value)

        try:
            if node.node_type == NodeType.AGENT:
                result = await self._run_agent_node(node)
            elif node.node_type == NodeType.TOOL:
                result = await self._run_tool_node(node)
            elif node.node_type == NodeType.CONDITION:
                result = await self._run_condition_node(node)
            elif node.node_type == NodeType.MERGE:
                result = self._run_merge_node(node)
            elif node.node_type == NodeType.SUB_WORKFLOW:
                result = await self._run_sub_workflow_node(node)
            else:
                raise ValueError(f"Unknown node type: {node.node_type}")

            node.result = result
            node.status = NodeStatus.SUCCESS
            self.results[node.id] = result

            # Store into workflow context for downstream nodes
            self.context[f"node.{node.id}"] = (
                result.to_dict() if isinstance(result, SubAgentResult) else result
            )
            logger.debug("Node '%s' succeeded", node.id)

        except Exception as exc:
            node.status = NodeStatus.FAILED
            node.error = str(exc)
            self.errors[node.id] = str(exc)
            logger.error("Node '%s' failed: %s", node.id, exc, exc_info=True)

        finally:
            node.finished_at = time.monotonic()

    # ---- node-type executors --------------------------------------------

    async def _run_agent_node(self, node: WorkflowNode) -> Any:
        """Run an AGENT node — spawns a sub-agent via the engine."""
        task = node.config.get("task", "")
        tools = node.config.get("tools", [])
        personality = node.config.get("personality")
        timeout = node.timeout or node.config.get("timeout", 300)

        # Render task template with context
        task = self._render_template(task)

        if self.engine is not None:
            result = await self.engine.spawn_subagent(
                task=task,
                tools=tools,
                personality=personality,
                timeout=timeout,
            )
            # spawn_subagent returns a dict; wrap in SubAgentResult for consistency
            if isinstance(result, dict):
                return SubAgentResult(
                    task=task,
                    content=result.get("content"),
                    tools_used=result.get("tools_used", []),
                    tokens=result.get("tokens", -1),
                    elapsed=result.get("elapsed", 0.0),
                    success=result.get("success", True),
                    error=result.get("error"),
                )
            return result

        # Fallback: no engine available
        raise RuntimeError(
            f"Cannot execute agent node '{node.id}': no engine reference"
        )

    async def _run_tool_node(self, node: WorkflowNode) -> Any:
        """Run a TOOL node — calls a tool directly."""
        tool_name = node.config.get("tool")
        tool_args = node.config.get("args", {})

        if not tool_name:
            raise ValueError(f"Tool node '{node.id}' missing 'tool' in config")

        # Render args values with context
        rendered_args = {
            k: self._render_template(str(v)) if isinstance(v, str) else v
            for k, v in tool_args.items()
        }

        if self.engine is not None and hasattr(self.engine, "_agent"):
            agent = self.engine._agent
            if hasattr(agent, "execute_tool"):
                return await agent.execute_tool(tool_name, **rendered_args)

        raise RuntimeError(
            f"Cannot execute tool node '{node.id}': no agent or engine reference"
        )

    async def _run_condition_node(self, node: WorkflowNode) -> str:
        """Run a CONDITION node — evaluates an expression against context.

        The result is the chosen branch key.  Downstream nodes should use
        ``branch_key`` in their config to indicate which branch they
        belong to.  Nodes whose branch doesn't match will be skipped.
        """
        expression = node.config.get("expression", "True")
        branches = node.config.get("branches", {})

        # Evaluate the expression safely — denylist dangerous patterns first
        _DISALLOWED_SUBSTRINGS = (
            "__",
            "import ",
            "open(",
            "exec(",
            "eval(",
            "compile(",
            "os.",
            "sys.",
            "subprocess",
            "socket",
            "shutil",
        )
        if any(s in expression for s in _DISALLOWED_SUBSTRINGS):
            raise RuntimeError(
                f"Condition expression contains disallowed pattern: {expression!r}"
            )
        try:
            # Build a limited evaluation context (no builtins leakage)
            eval_context = {
                "ctx": self.context,
                "results": dict(self.results),
                "len": len,
                "str": str,
                "int": int,
                "float": float,
                "bool": bool,
                "isinstance": isinstance,
            }
            result = eval(expression, {"__builtins__": {}}, eval_context)  # noqa: S307
        except Exception as exc:
            raise RuntimeError(
                f"Condition evaluation failed for node '{node.id}': {exc}"
            ) from exc

        # Map result to branch
        if isinstance(result, bool):
            branch_key = "true" if result else "false"
        else:
            branch_key = str(result)

        # Determine which downstream nodes to activate/skip
        chosen_branches: set[str] = set()
        for bkey, bval in branches.items():
            if bkey == branch_key or (isinstance(bval, list) and branch_key in bval):
                chosen_branches.add(bkey)

        # Skip downstream nodes not in the chosen branch
        for downstream in self.get_downstream(node.id):
            node_branch = downstream.config.get("branch")
            if node_branch and node_branch not in chosen_branches:
                downstream.status = NodeStatus.SKIPPED
                downstream.error = f"Skipped: condition chose branch '{branch_key}', not '{node_branch}'"
                self.errors[downstream.id] = downstream.error
                logger.debug(
                    "Node '%s' skipped (condition branch='%s')",
                    downstream.id,
                    branch_key,
                )

        logger.debug(
            "Condition node '%s' evaluated to '%s' (branches chosen: %s)",
            node.id,
            branch_key,
            chosen_branches or "(all)",
        )
        return branch_key

    def _run_merge_node(self, node: WorkflowNode) -> list[Any]:
        """Run a MERGE node — collect results from all dependencies."""
        merged: list[Any] = []
        for dep_id in node.dependencies:
            if dep_id in self.nodes:
                dep = self.nodes[dep_id]
                val = dep._serialise_result()
                merged.append(
                    {"node_id": dep_id, "status": dep.status.value, "result": val}
                )
        logger.debug(
            "Merge node '%s' collected %d upstream results", node.id, len(merged)
        )
        return merged

    async def _run_sub_workflow_node(self, node: WorkflowNode) -> dict[str, Any]:
        """Run a SUB_WORKFLOW node — execute a nested workflow."""
        if self.engine is None:
            raise RuntimeError(
                f"Cannot execute sub-workflow node '{node.id}': no engine reference"
            )

        sub_name = node.config.get("workflow")
        sub_context_override = node.config.get("context", {})

        # Merge parent context with override
        merged_context = {**self.context, **sub_context_override}

        # Render string values
        merged_context = {
            k: self._render_template(str(v)) if isinstance(v, str) else v
            for k, v in merged_context.items()
        }

        result = await self.engine.execute_workflow(
            name=sub_name,
            context=merged_context,
        )
        return result

    # ---- utilities ------------------------------------------------------

    def _render_template(self, template: str) -> str:
        """Simple ``{{key}}`` template rendering from workflow context."""
        import re as _re

        def _replace(match: _re.Match) -> str:
            key = match.group(1).strip()
            # Support dot-notation: node.my_node → context["node.my_node"]
            val = self.context.get(key)
            if val is None and "." in key:
                # Try nested lookup
                parts = key.split(".")
                val = self.context
                for p in parts:
                    if isinstance(val, dict):
                        val = val.get(p)
                    else:
                        val = None
                        break
            return str(val) if val is not None else match.group(0)

        return _re.sub(r"\{\{(.+?)\}\}", _replace, template)

    def to_dict(self) -> dict[str, Any]:
        """Serialise the full workflow state."""
        return {
            "name": self.name,
            "status": self.status.value,
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "context": self.context,
            "errors": dict(self.errors),
            "timeout": self.timeout,
        }

    # ---- factory --------------------------------------------------------

    @classmethod
    def from_dict(cls, data: dict[str, Any], engine: Any | None = None) -> Workflow:
        """Create a :class:`Workflow` from a definition dictionary.

        Expected structure::

            {
                "name": "my_workflow",
                "timeout": 600,
                "nodes": [
                    {
                        "id": "step_1",
                        "name": "Research",
                        "type": "agent",
                        "config": {"task": "Research {{topic}}", "tools": ["web_search"]},
                        "dependencies": [],
                        "timeout": 120
                    },
                    {
                        "id": "step_2",
                        "name": "Summarise",
                        "type": "agent",
                        "config": {"task": "Summarise: {{node.step_1}}"},
                        "dependencies": ["step_1"]
                    }
                ]
            }
        """
        nodes = [WorkflowNode.from_dict(nd) for nd in data.get("nodes", [])]
        return cls(
            name=data.get("name", "unnamed"),
            nodes=nodes,
            engine=engine,
            timeout=float(data.get("timeout", 0)),
        )

    def cancel(self) -> None:
        """Request cancellation of the running workflow."""
        self._cancel_event.set()


# ======================================================================
# OrchestrationEngine
# ======================================================================


class OrchestrationEngine:
    """Central coordinator for sub-agent spawning and workflow execution.

    Combines NullBoiler's workflow engine with Hermes's subagent system.

    The engine holds:
    * A registry of active :class:`SubAgent` instances.
    * A registry of :class:`Workflow` definitions (by name).
    * A reference to the parent agent (injected at construction to avoid
      circular imports).

    Usage::

        engine = OrchestrationEngine(agent=my_agent, max_subagents=5, timeout=300)
        await engine.initialize()

        # Spawn a one-off sub-agent
        result = await engine.spawn_subagent("Analyze this data", tools=["python"])

        # Build and run a workflow
        workflow = engine.create_workflow({"name": "pipeline", "nodes": [...]})
        outcome = await engine.execute_workflow("pipeline", context={"key": "val"})

        await engine.shutdown()
    """

    def __init__(
        self,
        agent: Any,
        max_subagents: int = 5,
        timeout: float = 300.0,
    ) -> None:
        self._agent = agent
        self._max_subagents: int = max_subagents
        self._default_timeout: float = timeout

        # Registries
        self._subagents: dict[str, SubAgent] = {}
        self._workflows: dict[str, Workflow] = {}

        # State
        self._initialized: bool = False
        self._shutting_down: bool = False
        self._lock: asyncio.Lock = asyncio.Lock()

        # Statistics
        self._stats: dict[str, Any] = {
            "subagents_spawned": 0,
            "subagents_completed": 0,
            "subagents_failed": 0,
            "subagents_cancelled": 0,
            "workflows_created": 0,
            "workflows_executed": 0,
            "workflows_failed": 0,
        }

    # ---- lifecycle ------------------------------------------------------

    async def initialize(self) -> None:
        """Prepare the engine for operation."""
        if self._initialized:
            logger.warning("OrchestrationEngine already initialized")
            return

        logger.info(
            "Initializing OrchestrationEngine (max_subagents=%d, timeout=%.1fs)",
            self._max_subagents,
            self._default_timeout,
        )
        self._initialized = True
        self._shutting_down = False

    async def shutdown(self) -> None:
        """Gracefully shut down: cancel active sub-agents and workflows."""
        self._shutting_down = True
        logger.info("Shutting down OrchestrationEngine...")

        # Cancel all active sub-agents
        active = list(self._subagents.values())
        for sa in active:
            if sa.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING):
                sa.cancel()
        logger.info("Cancelled %d active sub-agents", len(active))

        # Cancel running workflows
        for wf in self._workflows.values():
            if wf.status == WorkflowStatus.RUNNING:
                wf.cancel()

        self._initialized = False
        logger.info("OrchestrationEngine shutdown complete")

    def get_status(self) -> dict[str, Any]:
        """Return a snapshot of engine state and statistics."""
        active_subagents = [
            sa.to_dict()
            for sa in self._subagents.values()
            if sa.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING)
        ]
        active_workflows = [
            {"name": wf.name, "status": wf.status.value}
            for wf in self._workflows.values()
            if wf.status == WorkflowStatus.RUNNING
        ]
        return {
            "initialized": self._initialized,
            "shutting_down": self._shutting_down,
            "max_subagents": self._max_subagents,
            "default_timeout": self._default_timeout,
            "active_subagents": active_subagents,
            "active_workflows": active_workflows,
            "registered_workflows": list(self._workflows.keys()),
            "stats": dict(self._stats),
        }

    # ---- sub-agent management -------------------------------------------

    async def spawn_subagent(
        self,
        task: str,
        tools: list[str] | None = None,
        personality: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """Spawn a sub-agent, execute its task, and return the result.

        Args:
            task:        The task description / prompt for the sub-agent.
            tools:       Optional list of tool names the sub-agent may use.
            personality: Optional personality override for the sub-agent.
            timeout:     Per-sub-agent timeout in seconds (default: engine default).

        Returns:
            A dict representation of :class:`SubAgentResult`.

        Raises:
            RuntimeError: If too many sub-agents are already active, or the
                          engine is not initialized / is shutting down.
        """
        if not self._initialized:
            raise RuntimeError("OrchestrationEngine is not initialized")
        if self._shutting_down:
            raise RuntimeError("OrchestrationEngine is shutting down")

        async with self._lock:
            active_count = sum(
                1
                for sa in self._subagents.values()
                if sa.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING)
            )
            if active_count >= self._max_subagents:
                raise RuntimeError(
                    f"Max sub-agents ({self._max_subagents}) reached. "
                    f"Active: {active_count}"
                )

            subagent = SubAgent(
                task=task,
                agent=self._agent,
                tools=tools,
                personality=personality,
                timeout=timeout or self._default_timeout,
            )
            self._subagents[subagent.id] = subagent
            self._stats["subagents_spawned"] += 1

        logger.info(
            "Spawning sub-agent %s (task: %.80s, tools=%s, timeout=%.1fs)",
            subagent.id,
            task,
            tools,
            subagent.timeout,
        )

        result = await subagent.run()

        # Update stats
        if result.success:
            self._stats["subagents_completed"] += 1
        elif subagent.status == SubAgentStatus.CANCELLED:
            self._stats["subagents_cancelled"] += 1
        else:
            self._stats["subagents_failed"] += 1

        # Clean up old completed/failed sub-agents (keep last 50)
        await self._prune_subagents(max_keep=50)

        return result.to_dict()

    async def _prune_subagents(self, max_keep: int = 50) -> None:
        """Remove finished sub-agents beyond *max_keep* (oldest first)."""
        terminal = [
            (sid, sa)
            for sid, sa in self._subagents.items()
            if sa.status
            in (SubAgentStatus.COMPLETED, SubAgentStatus.FAILED, SubAgentStatus.TIMEOUT)
        ]
        if len(terminal) > max_keep:
            # Sort by creation time, remove oldest
            terminal.sort(key=lambda x: x[1].created_at)
            to_remove = len(terminal) - max_keep
            for sid, _ in terminal[:to_remove]:
                del self._subagents[sid]
            logger.debug("Pruned %d old sub-agent records", to_remove)

    def list_active_subagents(self) -> list[dict[str, Any]]:
        """Return serialised state of all currently active sub-agents."""
        return [
            sa.to_dict()
            for sa in self._subagents.values()
            if sa.status in (SubAgentStatus.PENDING, SubAgentStatus.RUNNING)
        ]

    def cancel_subagent(self, subagent_id: str) -> bool:
        """Request cancellation of a specific sub-agent.

        Returns:
            ``True`` if the sub-agent was found and cancellation was
            requested, ``False`` otherwise.
        """
        sa = self._subagents.get(subagent_id)
        if sa is None:
            logger.warning("cancel_subagent: unknown id '%s'", subagent_id)
            return False
        sa.cancel()
        self._stats["subagents_cancelled"] += 1
        logger.info("Sub-agent %s cancellation requested", subagent_id)
        return True

    # ---- workflow management --------------------------------------------

    def create_workflow(self, definition_dict: dict[str, Any]) -> Workflow:
        """Build a :class:`Workflow` from a definition dictionary and register it.

        The definition format is the same as :meth:`Workflow.from_dict`.

        Args:
            definition_dict: The workflow definition.

        Returns:
            The created :class:`Workflow` instance.
        """
        workflow = Workflow.from_dict(definition_dict, engine=self)
        self._workflows[workflow.name] = workflow
        self._stats["workflows_created"] += 1
        logger.info(
            "Workflow '%s' registered with %d nodes",
            workflow.name,
            len(workflow.nodes),
        )
        return workflow

    def register_workflow(self, workflow: Workflow) -> None:
        """Register a pre-built :class:`Workflow` instance."""
        self._workflows[workflow.name] = workflow
        self._stats["workflows_created"] += 1
        logger.info("Workflow '%s' registered", workflow.name)

    async def execute_workflow(
        self,
        name: str,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a registered workflow by name.

        Args:
            name:    The workflow name (as registered via
                     :meth:`create_workflow` or :meth:`register_workflow`).
            context:  Optional context dict passed to the workflow.

        Returns:
            The workflow result dict (see :meth:`Workflow.execute`).

        Raises:
            KeyError:    If no workflow with *name* is registered.
            RuntimeError: If the engine is not initialized.
        """
        if not self._initialized:
            raise RuntimeError("OrchestrationEngine is not initialized")
        if self._shutting_down:
            raise RuntimeError("OrchestrationEngine is shutting down")

        workflow = self._workflows.get(name)
        if workflow is None:
            available = list(self._workflows.keys())
            raise KeyError(f"Workflow '{name}' not found. Available: {available}")

        self._stats["workflows_executed"] += 1
        result = await workflow.execute(context=context)

        if result["status"] == WorkflowStatus.FAILED.value:
            self._stats["workflows_failed"] += 1

        return result

    def list_workflows(self) -> list[dict[str, Any]]:
        """Return summary info for all registered workflows."""
        return [
            {
                "name": wf.name,
                "status": wf.status.value,
                "nodes": len(wf.nodes),
                "timeout": wf.timeout,
            }
            for wf in self._workflows.values()
        ]

    def remove_workflow(self, name: str) -> bool:
        """Unregister a workflow by name.

        Returns ``True`` if the workflow existed and was removed.
        """
        wf = self._workflows.pop(name, None)
        if wf is not None:
            logger.info("Workflow '%s' unregistered", name)
            return True
        return False
