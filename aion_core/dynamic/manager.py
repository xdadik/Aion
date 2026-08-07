#!/usr/bin/env python3
"""
Dynamic Manager for Aion Hand.
=================================

High-level API that combines the factory, topology manager, and
orchestrator into a single, easy-to-use interface. This is the
primary entry point for the dynamic agent system.

The manager handles initialization, delegation to the appropriate
subsystem, and graceful shutdown. It also aggregates statistics
from all subsystems for monitoring and debugging.

Usage:
    # Basic usage
    mgr = DynamicManager()
    await mgr.initialize()
    result = await mgr.execute("Build a REST API with JWT auth", complexity=7)
    print(result)
    await mgr.shutdown()

    # With existing AionHand agent
    from aion_core import AionHand
    agent = await AionHand()
    mgr = DynamicManager(base_agent=agent)
    await mgr.initialize()
    result = await mgr.execute("Research quantum computing applications")
    await mgr.shutdown()

    # Statistics
    stats = mgr.get_stats()
    print(f"Agents created: {stats['factory']['total_created']}")
    print(f"Success rate: {stats['orchestrator']['success_rate']}")

Architecture:
    DynamicManager
        +-- DynamicAgentFactory    (agent creation/destruction)
        +-- TopologyManager       (topology selection/learning)
        +-- DynamicOrchestrator    (execution coordination)
"""

from __future__ import annotations

import logging
import re
import time
from pathlib import Path
from typing import Any

from aion_core.dynamic.agent_factory import DynamicAgentFactory
from aion_core.dynamic.orchestrator import DynamicOrchestrator
from aion_core.dynamic.topology import TopologyManager

logger = logging.getLogger("aion_hand.dynamic.manager")


# ============================================================================
# Task classification helpers
# ============================================================================

_TASK_TYPE_KEYWORDS: dict[str, list[str]] = {
    # More specific types first — they win ties over generic ones
    # Multi-word keywords prevent false positives; single-word keywords
    # are used only when they're strongly domain-specific.
    "code_review": [
        "review code", "code review", "audit code", "inspect code",
        "check code", "code quality", "code standards",
        "review the code", "audit the code", "pr review",
    ],
    "bugfix": [
        "fix bug", "fix the bug", "debug error", "fix crash",
        "not working", "broken", "failing", "exception",
        "fix the", "bugfix",
    ],
    "writing": [
        "write documentation", "write a guide", "write tutorial",
        "draft document", "write readme", "write article",
        "create documentation", "documentation for",
    ],
    "analysis": [
        "analyze performance", "benchmark", "profile code",
        "assess performance", "measure performance",
        "performance of the",
    ],
    "research": [
        "research", "investigate", "study the",
        "explore the", "find out about", "learn about",
        "compare and contrast", "evaluate the",
    ],
    "coding": [
        "implement", "build", "develop", "program",
        "create api", "write code", "code the",
        "create function", "create class", "write script",
        "build app", "build web", "deploy",
        "write tests", "refactor", "debug",
    ],
    "general": [],
}


def classify_task(task: str) -> str:
    """Classify a task into a category based on keyword matching.

    Uses word-boundary matching to avoid false positives
    (e.g. "app" should not match inside "applications").
    More specific task types (code_review, bugfix) are checked
    before generic ones (coding) so they win on ties.

    Args:
        task: The task description to classify.

    Returns:
        A task type string (e.g. "coding", "research", "general").
    """
    task_lower = task.lower()
    best_type = "general"
    best_score = 0

    for task_type, keywords in _TASK_TYPE_KEYWORDS.items():
        if task_type == "general":
            continue
        # Score: each keyword match, multi-word keywords worth more
        score = sum(
            len(kw.split())  # multi-word keywords get higher weight
            for kw in keywords
            if re.search(r'\b' + re.escape(kw) + r'\b', task_lower)
        )
        if score > best_score:
            best_score = score
            best_type = task_type

    return best_type


def estimate_complexity(task: str) -> int:
    """Estimate task complexity from 1-10 based on heuristics.

    Heuristics:
        - Length: longer tasks tend to be more complex
        - Multi-part indicators: "and", "also", "additionally", numbered lists
        - Scope indicators: "full", "complete", "end-to-end", "comprehensive"
        - Simple indicators: "quick", "simple", "small", "minor"

    Args:
        task: The task description.

    Returns:
        Complexity score from 1 (trivial) to 10 (extreme).
    """
    task_lower = task.lower()

    # Base complexity from length
    base = min(5, len(task) // 50)

    # Multi-part indicators
    multi_part = sum([
        task_lower.count(" and "),
        task_lower.count(" also "),
        task_lower.count(" additionally "),
        task_lower.count(" furthermore "),
        task_lower.count(" moreover "),
        task_lower.count(", then "),
        task_lower.count(". then "),
    ])
    base += min(3, multi_part)

    # Scope indicators
    scope_keywords = [
        "full", "complete", "end-to-end", "comprehensive",
        "entire", "whole", "all of", "from scratch",
        "production", "enterprise", "distributed",
    ]
    for kw in scope_keywords:
        if kw in task_lower:
            base += 1
            break

    # Simple indicators (reduce complexity)
    simple_keywords = ["quick", "simple", "small", "minor", "trivial", "basic"]
    for kw in simple_keywords:
        if kw in task_lower:
            base = max(1, base - 2)
            break

    return max(1, min(10, base))


# ============================================================================
# Dynamic Manager
# ============================================================================


class DynamicManager:
    """High-level API for the dynamic agent system.

    Combines the agent factory, topology manager, and orchestrator
    into a single interface with automatic task classification,
    complexity estimation, and statistics aggregation.

    This is the recommended entry point for all dynamic agent operations.

    Attributes:
        initialized: Whether the manager has been initialized.
        factory: The underlying DynamicAgentFactory.
        topology_manager: The underlying TopologyManager.
        orchestrator: The underlying DynamicOrchestrator.
    """

    def __init__(
        self,
        base_agent: Any | None = None,
        storage_dir: Path | None = None,
        max_retries: int = 2,
        retry_delay: float = 1.0,
        auto_classify: bool = True,
    ) -> None:
        """Initialize the dynamic manager.

        Args:
            base_agent: Optional AionHand agent with LLM provider.
            storage_dir: Directory for persistent storage.
            max_retries: Agent execution retry count.
            retry_delay: Seconds between retries.
            auto_classify: Whether to auto-classify tasks and estimate complexity.
        """
        self.initialized: bool = False
        self._base_agent = base_agent
        self._storage_dir = storage_dir or Path.home() / ".aion-hand" / "dynamic"
        self._auto_classify = auto_classify
        self._start_time: float | None = None

        # Create subsystems
        self.factory = DynamicAgentFactory(
            base_agent=base_agent,
            storage_dir=self._storage_dir,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )
        self.topology_manager = TopologyManager(
            storage_dir=self._storage_dir,
        )
        self.orchestrator = DynamicOrchestrator(
            factory=self.factory,
            topology_manager=self.topology_manager,
            base_agent=base_agent,
        )

        logger.info("DynamicManager created (not yet initialized)")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Initialize the dynamic manager and all subsystems.

        Loads persisted topology data and agent archives from disk.
        Call this before execute().

        Raises:
            RuntimeError: If already initialized.
        """
        if self.initialized:
            logger.warning("DynamicManager already initialized")
            return

        self._start_time = time.time()
        logger.info("Initializing DynamicManager...")

        # Load persisted data
        self.topology_manager.load()
        self.factory.load_archive()

        self.initialized = True
        logger.info(
            f"DynamicManager initialized (topologies="
            f"{len(self.topology_manager.list_topologies())}, "
            f"archive={len(self.factory._archive)})"
        )

    async def shutdown(self) -> None:
        """Gracefully shutdown the dynamic manager.

        Saves all persisted data to disk and destroys any
        remaining active agents.
        """
        if not self.initialized:
            return

        logger.info("Shutting down DynamicManager...")

        # Save state
        self.topology_manager.save()
        self.factory.save_archive()

        # Destroy any remaining agents
        destroyed = self.factory.destroy_all()
        if destroyed:
            logger.info(f"Cleaned up {destroyed} remaining agents")

        self.initialized = False
        elapsed = time.time() - self._start_time if self._start_time else 0
        logger.info(
            f"DynamicManager shutdown complete "
            f"(session duration: {elapsed:.1f}s)"
        )

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        task: str,
        complexity: int | None = None,
        task_type: str | None = None,
    ) -> dict[str, Any]:
        """Execute a task using the full dynamic agent pipeline.

        Automatically classifies the task and estimates complexity
        if auto_classify is enabled (default).

        Args:
            task: The task description or request.
            complexity: Optional override for complexity (1-10).
                If None, estimated automatically from task text.
            task_type: Optional override for task type category.
                If None, classified automatically from task text.

        Returns:
            Full orchestration result dict with:
                - success: bool
                - task: str
                - topology: str (name)
                - results: list of per-agent results
                - total_tokens: int
                - elapsed_seconds: float

        Raises:
            RuntimeError: If manager not initialized.
        """
        if not self.initialized:
            raise RuntimeError(
                "DynamicManager not initialized. Call await mgr.initialize() first."
            )

        # Auto-classify if enabled
        if self._auto_classify:
            resolved_type = task_type or classify_task(task)
            resolved_complexity = complexity or estimate_complexity(task)
        else:
            resolved_type = task_type or "general"
            resolved_complexity = complexity or 5

        logger.info(
            f"Executing task (type={resolved_type}, "
            f"complexity={resolved_complexity}): '{task[:60]}...'"
        )

        return await self.orchestrator.orchestrate(
            task=task,
            complexity=resolved_complexity,
            task_type=resolved_type,
        )

    async def execute_quick(
        self,
        task: str,
        roles: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute a task with a minimal, fast topology.

        Uses only 1-2 agents for quick turnaround. Ideal for
        simple tasks that don't need full orchestration.

        Args:
            task: The task description.
            roles: Optional list of 1-2 roles to use.
                Defaults to ["coder"].

        Returns:
            Orchestration result dict.
        """

        if not self.initialized:
            raise RuntimeError("DynamicManager not initialized")

        return await self.orchestrator.orchestrate(
            task=task,
            complexity=1,
            task_type="quick",
        )

    # ------------------------------------------------------------------
    # Planning (inspect before execution)
    # ------------------------------------------------------------------

    def create_plan(
        self,
        task: str,
        complexity: int | None = None,
        task_type: str | None = None,
    ) -> dict[str, Any]:
        """Create an execution plan without running it.

        Useful for previewing which agents will be used and
        how they'll be organized before committing resources.

        Args:
            task: The task description.
            complexity: Optional complexity override (1-10).
            task_type: Optional task type override.

        Returns:
            Plan dict with topology, agents, parallel groups, estimates.
        """
        if not self.initialized:
            raise RuntimeError("DynamicManager not initialized")

        resolved_type = task_type or classify_task(task)
        resolved_complexity = complexity or estimate_complexity(task)

        plan = self.orchestrator.create_plan(
            task=task,
            complexity=resolved_complexity,
            task_type=resolved_type,
        )
        return plan.to_dict()

    async def execute_plan_by_id(self, plan_id: str) -> dict[str, Any]:
        """Execute a previously created plan by its ID.

        Args:
            plan_id: ID of the plan to execute.

        Returns:
            Execution result dict.

        Raises:
            KeyError: If plan ID is not found.
        """
        plans = self.orchestrator.get_active_plans()
        if plan_id not in plans:
            raise KeyError(f"Plan '{plan_id}' not found. Active plans: {list(plans.keys())}")
        return await self.orchestrator.execute_plan(plans[plan_id])

    # ------------------------------------------------------------------
    # Learning and evolution
    # ------------------------------------------------------------------

    def evolve_topology(
        self,
        topology_name: str,
        lesson: str,
    ) -> dict[str, Any] | None:
        """Evolve a topology based on a lesson learned.

        Finds the topology by name and applies heuristic mutations
        based on the lesson text.

        Args:
            topology_name: Name of the topology to evolve.
            lesson: Natural language lesson (e.g. "add verifier").

        Returns:
            Dict of the evolved topology, or None if not found.
        """
        for topo in self.topology_manager.list_topologies():
            if topo.name == topology_name:
                evolved = self.topology_manager.evolve_topology(topo.id, lesson)
                if evolved:
                    return evolved.to_dict()
                return None
        logger.warning(f"Topology '{topology_name}' not found for evolution")
        return None

    def analyze_patterns(self) -> dict[str, Any]:
        """Analyze execution patterns across all topologies.

        Returns insights about which topologies work best for
        which task types, along with recommendations.

        Returns:
            Pattern analysis dict with insights and recommendations.
        """
        return self.topology_manager.analyze_patterns()

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return comprehensive statistics from all subsystems.

        Aggregates statistics from the factory, topology manager,
        and orchestrator into a single dict.

        Returns:
            Dict with nested stats from each subsystem:
                - factory: agent creation/destruction stats
                - topology: topology selection/learning stats
                - orchestrator: execution history stats
                - session: manager session info
        """
        uptime = (
            time.time() - self._start_time
            if self._start_time
            else 0.0
        )

        return {
            "session": {
                "initialized": self.initialized,
                "uptime_seconds": round(uptime, 1),
                "auto_classify": self._auto_classify,
                "storage_dir": str(self._storage_dir),
            },
            "factory": self.factory.get_stats(),
            "topology": self.topology_manager.get_stats(),
            "orchestrator": self.orchestrator.get_stats(),
        }

    def get_summary(self) -> str:
        """Return a human-readable summary of current state.

        Useful for debugging and status reporting.

        Returns:
            Multi-line string summary.
        """
        stats = self.get_stats()
        f_stats = stats["factory"]
        t_stats = stats["topology"]
        o_stats = stats["orchestrator"]
        s_stats = stats["session"]

        lines = [
            "=" * 60,
            "  Aion Hand — Dynamic Agent System",
            "=" * 60,
            "",
            f"  Session: {'INITIALIZED' if s_stats['initialized'] else 'NOT INITIALIZED'}",
            f"  Uptime: {s_stats['uptime_seconds']:.1f}s",
            "",
            "  Factory:",
            f"    Agents created:    {f_stats['total_created']}",
            f"    Agents destroyed:  {f_stats['total_destroyed']}",
            f"    Active agents:     {f_stats['active_count']}",
            f"    Total executions:  {f_stats['total_executions']}",
            f"    Total tokens:      {f_stats['total_tokens']}",
            f"    Total retries:     {f_stats.get('total_retries', 0)}",
            f"    Archive size:      {f_stats['archive_size']}",
            "",
            "  Topology:",
            f"    Topologies:       {t_stats['topology_count']}",
            f"    Execution log:     {t_stats['execution_log_size']}",
            f"    Overall success:   {t_stats['overall_success_rate']:.1%}",
            "",
            "  Orchestrator:",
            f"    Orchestrations:   {o_stats['total_orchestrations']}",
            f"    Success rate:      {o_stats['success_rate']:.1%}",
            f"    Active plans:      {o_stats['active_plans']}",
            f"    Avg tokens/orch:  {o_stats['avg_tokens']:.0f}",
            f"    Avg time/orch:     {o_stats['avg_time']:.1f}s",
            "",
            "=" * 60,
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self) -> DynamicManager:
        await self.initialize()
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.shutdown()
