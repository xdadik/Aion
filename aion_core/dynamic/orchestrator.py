#!/usr/bin/env python3
"""
Dynamic Orchestrator for Aion Hand.
====================================

High-level coordinator that selects topologies, creates agents,
executes them in optimal order (respecting DAG dependencies),
collects results, records outcomes for learning, and cleans up.

The orchestrator bridges the factory (agent creation) and topology
manager (selection/learning) to provide a unified execution interface.

Execution strategies:
    - orchestrate(): Full one-shot lifecycle (suggest -> create -> execute -> destroy -> record)
    - create_plan() + execute_plan(): Two-phase execution with plan inspection
    - execute_parallel(): Run multiple independent agents concurrently
    - execute_sequential(): Run agents one-by-one with context forwarding

Features:
    - DAG-based parallel execution with dependency resolution
    - Context forwarding between sequential agents
    - Automatic outcome recording for topology learning
    - Fallback to single-agent execution when no topology is available
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from aion_core.dynamic.agent_factory import (
    DynamicAgent,
    DynamicAgentFactory,
)
from aion_core.dynamic.topology import AgentTopology, TopologyManager

logger = logging.getLogger("aion_hand.dynamic.orchestrator")


# ============================================================================
# Data structures
# ============================================================================


@dataclass
class DynamicOrchestrationPlan:
    """A pre-computed execution plan ready to be run.

    Created by create_plan() and executed by execute_plan().
    Contains all information needed to spin up and run agents.

    Attributes:
        task: The original user task.
        topology: The selected topology for this plan.
        agents_to_create: List of agent specs to create.
        execution_order: Agent IDs in execution order.
        parallel_groups: Groups of IDs that can run concurrently.
        estimated_tokens: Rough token estimate.
        estimated_time: Rough time estimate in seconds.
    """

    task: str
    topology: AgentTopology | None
    agents_to_create: list[dict[str, Any]]
    execution_order: list[str]
    parallel_groups: list[list[str]]
    estimated_tokens: int = 0
    estimated_time: float = 0.0
    created_at: str = field(
        default_factory=lambda: time.strftime("%Y-%m-%dT%H:%M:%S")
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task,
            "topology_name": self.topology.name if self.topology else None,
            "topology_id": self.topology.id if self.topology else None,
            "agents_to_create": self.agents_to_create,
            "execution_order": self.execution_order,
            "parallel_groups": self.parallel_groups,
            "estimated_tokens": self.estimated_tokens,
            "estimated_time": round(self.estimated_time, 2),
            "created_at": self.created_at,
        }


# ============================================================================
# Role-specific task transformers
# ============================================================================

_ROLE_TASK_PREFIXES: dict[str, str] = {
    "planner": "Create a detailed execution plan for the following task. "
               "Break it into ordered sub-tasks with roles and dependencies:\n\n",
    "researcher": "Research the following topic thoroughly. "
                   "Gather information from multiple sources and present findings:\n\n",
    "coder": "Implement the following based on the plan and context provided. "
             "Write clean, tested, well-documented code:\n\n",
    "critic": "Critically review the following work. "
              "Identify strengths, weaknesses, risks, and suggest improvements:\n\n",
    "verifier": "Verify the correctness and completeness of the following. "
                "Check each requirement and report PASS/PARTIAL/FAIL:\n\n",
    "repairer": "Fix the issues identified in the following. "
                "Apply minimal targeted fixes and explain each change:\n\n",
    "summarizer": "Summarize the following into a concise, structured summary. "
                  "Capture key points, decisions, and action items:\n\n",
    "fact_checker": "Fact-check all substantive claims in the following. "
                    "Verify each against sources and report VERIFIED/UNVERIFIED/FALSE:\n\n",
}


# ============================================================================
# Orchestrator
# ============================================================================


class DynamicOrchestrator:
    """High-level coordinator for dynamic agent workflows.

    Usage:
        factory = DynamicAgentFactory()
        topo_mgr = TopologyManager()
        orch = DynamicOrchestrator(factory, topo_mgr)

        # One-shot execution
        result = await orch.orchestrate("Build a REST API", complexity=7)

        # Two-phase execution
        plan = orch.create_plan("Write documentation", complexity=3)
        result = await orch.execute_plan(plan)
    """

    def __init__(
        self,
        factory: DynamicAgentFactory | None = None,
        topology_manager: TopologyManager | None = None,
        base_agent: Any | None = None,
    ) -> None:
        """Initialize the orchestrator.

        Args:
            factory: DynamicAgentFactory for creating/destroying agents.
                If *None*, a default factory is created.
            topology_manager: TopologyManager for selecting/learning topologies.
                If *None*, a default manager is created.
            base_agent: Optional AionHand agent for LLM provider access.
        """
        self._factory = factory or DynamicAgentFactory(base_agent=base_agent)
        self._topology_mgr = topology_manager or TopologyManager()
        self._base_agent = base_agent
        self._active_plans: dict[str, DynamicOrchestrationPlan] = {}
        self._execution_history: list[dict[str, Any]] = []
        logger.info("DynamicOrchestrator initialized")

    # ------------------------------------------------------------------
    # Full orchestration (one-shot)
    # ------------------------------------------------------------------

    async def orchestrate(
        self,
        task: str,
        complexity: int = 5,
        task_type: str = "general",
    ) -> dict[str, Any]:
        """Run the full orchestration lifecycle in one call.

        Steps:
            1. Suggest best topology for the task
            2. Create agents from topology
            3. Execute in optimal order (parallel where possible)
            4. Collect and aggregate results
            5. Destroy all agents
            6. Record outcome for topology learning

        Args:
            task: The user's task/request.
            complexity: Complexity from 1 (trivial) to 10 (extreme).
            task_type: Category for topology selection (e.g. "coding").

        Returns:
            Dict with success, task, topology, results, metrics.
        """
        start = time.time()
        logger.info(
            f"Orchestrating: '{task[:60]}...' (complexity={complexity}, "
            f"type={task_type})"
        )

        # Step 1: suggest topology
        topology = self._topology_mgr.suggest_topology(task_type, complexity)
        if topology is None:
            logger.warning("No topology available, using fallback solo coder")
            topology = self._topology_mgr.create_topology(
                agents=["coder"],
                connections=[],
                task_types=[task_type],
                name="Fallback Solo",
            )

        # Step 2: create agents based on topology
        agents: list[DynamicAgent] = []
        for role in topology.agents:
            agent = self._factory.create_agent(
                role=role,  # type: ignore[arg-type]
                task=task,
                parent_task=task,
            )
            agents.append(agent)

        # Step 3: determine execution order via DAG resolution
        agent_tasks = self._build_agent_tasks(agents, task)
        parallel_groups = self._compute_parallel_groups(agents, topology)

        # Step 4: execute groups sequentially, agents within a group in parallel
        total_tokens = 0
        all_results: list[dict] = []

        for group in parallel_groups:
            if len(group) == 1:
                result = await self._execute_single(
                    agent_tasks[group[0]], all_results
                )
                all_results.append(result)
                total_tokens += result.get("tokens_used", 0)
            else:
                group_results = await self._execute_parallel_group(
                    [agent_tasks[aid] for aid in group], all_results
                )
                all_results.extend(group_results)
                total_tokens += sum(
                    r.get("tokens_used", 0) for r in group_results
                )

        # Step 5: destroy all agents
        destroyed = self._factory.destroy_all()

        # Step 6: record outcome for topology learning
        elapsed = time.time() - start
        success = all(r.get("status") == "completed" for r in all_results)
        self._topology_mgr.record_execution(
            topology_id=topology.id,
            task_type=task_type,
            success=success,
            tokens=total_tokens,
            time=elapsed,
        )

        # Record in orchestrator history
        history_entry = {
            "task": task,
            "complexity": complexity,
            "task_type": task_type,
            "topology": topology.name,
            "success": success,
            "tokens": total_tokens,
            "time": round(elapsed, 3),
            "agents_used": len(agents),
        }
        self._execution_history.append(history_entry)

        logger.info(
            f"Orchestration complete: success={success}, "
            f"tokens={total_tokens}, time={elapsed:.2f}s, "
            f"agents_created={len(agents)}, agents_destroyed={destroyed}"
        )

        return {
            "success": success,
            "task": task,
            "topology": topology.name,
            "topology_id": topology.id,
            "results": all_results,
            "total_tokens": total_tokens,
            "elapsed_seconds": round(elapsed, 3),
            "agents_created": len(agents),
            "agents_destroyed": destroyed,
        }

    # ------------------------------------------------------------------
    # Plan creation (without execution)
    # ------------------------------------------------------------------

    def create_plan(
        self,
        task: str,
        complexity: int = 5,
        task_type: str = "general",
    ) -> DynamicOrchestrationPlan:
        """Create an execution plan without running it.

        Useful for inspecting the plan before execution, or for
        saving plans for later replay.

        Args:
            task: The user's task.
            complexity: Task complexity (1-10).
            task_type: Category for topology selection.

        Returns:
            DynamicOrchestrationPlan ready for execution.
        """
        topology = self._topology_mgr.suggest_topology(task_type, complexity)
        if topology is None:
            topology = self._topology_mgr.create_topology(
                agents=["coder"],
                connections=[],
                task_types=[task_type],
                name="Fallback Solo",
            )

        agents_to_create = [
            {"role": role, "task": task}
            for role in topology.agents
        ]

        # Pre-assign IDs for planning purposes
        execution_order = [
            f"agent_{i}" for i in range(len(topology.agents))
        ]
        parallel_groups = self._compute_parallel_groups_pre(
            execution_order, topology
        )

        # Rough estimates based on topology size
        est_tokens = len(topology.agents) * 1500
        est_time = len(topology.agents) * 5.0

        plan = DynamicOrchestrationPlan(
            task=task,
            topology=topology,
            agents_to_create=agents_to_create,
            execution_order=execution_order,
            parallel_groups=parallel_groups,
            estimated_tokens=est_tokens,
            estimated_time=est_time,
        )

        plan_id = f"plan_{len(self._active_plans) + 1}"
        self._active_plans[plan_id] = plan
        logger.info(
            f"Created plan '{plan_id}' with topology '{topology.name}' "
            f"({len(topology.agents)} agents, {len(parallel_groups)} groups)"
        )
        return plan

    # ------------------------------------------------------------------
    # Plan execution
    # ------------------------------------------------------------------

    async def execute_plan(self, plan: DynamicOrchestrationPlan) -> dict[str, Any]:
        """Execute a previously created plan.

        Creates agents from the plan spec, runs them according to
        the parallel groups, then destroys all agents.

        Args:
            plan: DynamicOrchestrationPlan from create_plan().

        Returns:
            Dict with success, results, tokens, time.
        """
        logger.info(f"Executing plan for: '{plan.task[:60]}...'")
        start = time.time()

        # Create agents
        agents: list[DynamicAgent] = []
        for spec in plan.agents_to_create:
            agent = self._factory.create_agent(
                role=spec["role"],  # type: ignore[arg-type]
                task=spec["task"],
                parent_task=plan.task,
            )
            agents.append(agent)

        # Build lookup: pre-assigned ID -> actual agent
        id_to_agent: dict[str, DynamicAgent] = {}
        for i, agent in enumerate(agents):
            id_to_agent[f"agent_{i}"] = agent

        # Execute in parallel groups
        total_tokens = 0
        all_results: list[dict] = []

        for group in plan.parallel_groups:
            if len(group) == 1:
                agent = id_to_agent[group[0]]
                result = await self._execute_single(
                    {"agent": agent, "task": plan.task}, all_results
                )
                all_results.append(result)
                total_tokens += result.get("tokens_used", 0)
            else:
                tasks = [
                    {"agent": id_to_agent[aid], "task": plan.task}
                    for aid in group
                ]
                group_results = await self._execute_parallel_group(
                    tasks, all_results
                )
                all_results.extend(group_results)
                total_tokens += sum(
                    r.get("tokens_used", 0) for r in group_results
                )

        # Cleanup
        self._factory.destroy_all()
        elapsed = time.time() - start
        success = all(r.get("status") == "completed" for r in all_results)

        # Record outcome
        if plan.topology:
            self._topology_mgr.record_execution(
                topology_id=plan.topology.id,
                task_type="planned",
                success=success,
                tokens=total_tokens,
                time=elapsed,
            )

        return {
            "success": success,
            "task": plan.task,
            "topology": plan.topology.name if plan.topology else None,
            "results": all_results,
            "total_tokens": total_tokens,
            "elapsed_seconds": round(elapsed, 3),
        }

    # ------------------------------------------------------------------
    # Direct execution strategies
    # ------------------------------------------------------------------

    async def execute_parallel(
        self,
        agent_tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute multiple agents in parallel and return combined results.

        Args:
            agent_tasks: List of dicts with 'agent' (DynamicAgent) and 'task' (str).

        Returns:
            Dict with success, results, tokens, time, strategy.
        """
        start = time.time()
        results = await self._execute_parallel_group(agent_tasks, [])
        elapsed = time.time() - start
        total_tokens = sum(r.get("tokens_used", 0) for r in results)
        success = all(r.get("status") == "completed" for r in results)

        return {
            "success": success,
            "results": results,
            "total_tokens": total_tokens,
            "elapsed_seconds": round(elapsed, 3),
            "strategy": "parallel",
        }

    async def execute_sequential(
        self,
        agent_tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Execute multiple agents one after another, forwarding context.

        Each agent receives the results of all prior agents as context,
        enabling a pipeline of refinements.

        Args:
            agent_tasks: List of dicts with 'agent' (DynamicAgent) and 'task' (str).

        Returns:
            Dict with success, results, tokens, time, strategy.
        """
        start = time.time()
        all_results: list[dict] = []
        total_tokens = 0

        for task_spec in agent_tasks:
            result = await self._execute_single(task_spec, all_results)
            all_results.append(result)
            total_tokens += result.get("tokens_used", 0)

        elapsed = time.time() - start
        success = all(r.get("status") == "completed" for r in all_results)

        return {
            "success": success,
            "results": all_results,
            "total_tokens": total_tokens,
            "elapsed_seconds": round(elapsed, 3),
            "strategy": "sequential",
        }

    # ------------------------------------------------------------------
    # Internal execution helpers
    # ------------------------------------------------------------------

    async def _execute_single(
        self,
        task_spec: dict[str, Any],
        prior_results: list[dict],
    ) -> dict[str, Any]:
        """Execute a single agent, passing prior results as context.

        Builds a context string from the last 3 prior agent results
        so downstream agents can build on earlier work.

        Args:
            task_spec: Dict with 'agent' (DynamicAgent) and 'task' (str).
            prior_results: List of result dicts from earlier agents.

        Returns:
            Execution result dict from the factory.
        """
        agent: DynamicAgent = task_spec["agent"]
        task: str = task_spec["task"]

        context = None
        if prior_results:
            ctx_parts = []
            for pr in prior_results[-3:]:  # Last 3 results for context
                result_text = pr.get("result", "")
                agent_id = pr.get("agent_id", "?")
                if result_text:
                    ctx_parts.append(
                        f"[Agent {agent_id} output]:\n{result_text[:500]}"
                    )
            if ctx_parts:
                context = "\n\n---\n\n".join(ctx_parts)

        return await self._factory.execute_agent(agent.id, task, context)

    async def _execute_parallel_group(
        self,
        task_specs: list[dict[str, Any]],
        prior_results: list[dict],
    ) -> list[dict[str, Any]]:
        """Execute a group of agents concurrently using asyncio.gather.

        All agents in the group receive the same prior context but
        execute independently.

        Args:
            task_specs: List of task spec dicts.
            prior_results: Context from earlier execution groups.

        Returns:
            List of result dicts (order matches input order).
        """
        coros = [
            self._execute_single(spec, prior_results) for spec in task_specs
        ]
        return list(await asyncio.gather(*coros, return_exceptions=False))

    def _build_agent_tasks(
        self,
        agents: list[DynamicAgent],
        task: str,
    ) -> dict[str, dict[str, Any]]:
        """Map agent IDs to role-specific task descriptions.

        Each role gets a tailored prompt prefix so the agent knows
        exactly what perspective to take.

        Args:
            agents: List of DynamicAgent instances.
            task: The original user task.

        Returns:
            Dict mapping agent IDs to task spec dicts.
        """
        tasks = {}
        for agent in agents:
            role = agent.profile.role
            prefix = _ROLE_TASK_PREFIXES.get(role, "")
            role_task = f"{prefix}{task}" if prefix else task
            tasks[agent.id] = {"agent": agent, "task": role_task}
        return tasks

    def _compute_parallel_groups(
        self,
        agents: list[DynamicAgent],
        topology: AgentTopology,
    ) -> list[list[str]]:
        """Determine which agents can run in parallel based on DAG connections.

        Uses topological sort to group agents by dependency level.
        Agents in the same group have no dependencies on each other
        and can execute concurrently.

        Args:
            agents: List of DynamicAgent instances.
            topology: The AgentTopology defining connections.

        Returns:
            List of groups, where each group is a list of agent IDs.
        """
        if not topology.connections:
            # No connections = all can run in parallel
            return [[a.id for a in agents]]

        # Build dependency graph: agent -> set of prerequisite agents
        deps: dict[str, set] = {a.id: set() for a in agents}
        role_to_id = {a.profile.role: a.id for a in agents}

        for conn in topology.connections:
            from_id = role_to_id.get(conn["from"])
            to_id = role_to_id.get(conn["to"])
            if from_id and to_id:
                deps[to_id].add(from_id)

        # Topological sort with parallel grouping
        return self._topological_groups(deps)

    def _compute_parallel_groups_pre(
        self,
        ids: list[str],
        topology: AgentTopology,
    ) -> list[list[str]]:
        """Same as _compute_parallel_groups but uses pre-assigned IDs.

        Used by create_plan() which works with placeholder IDs
        rather than real agent instances.
        """
        if not topology.connections:
            return [ids]

        deps: dict[str, set] = {aid: set() for aid in ids}
        role_to_id = {}
        for i, role in enumerate(topology.agents):
            if i < len(ids):
                role_to_id[role] = ids[i]

        for conn in topology.connections:
            from_id = role_to_id.get(conn["from"])
            to_id = role_to_id.get(conn["to"])
            if from_id and to_id:
                deps[to_id].add(from_id)

        return self._topological_groups(deps)

    @staticmethod
    def _topological_groups(deps: dict[str, set]) -> list[list[str]]:
        """Group items into parallel execution layers via topological sort.

        Items with all dependencies satisfied are in the same layer.
        Cycles are broken by putting remaining items into a final group.

        Args:
            deps: Dict mapping item ID to set of prerequisite item IDs.

        Returns:
            List of layers, each layer being a list of item IDs.
        """
        groups: list[list[str]] = []
        completed: set = set()
        remaining = set(deps.keys())

        while remaining:
            # Items whose dependencies are all satisfied
            ready = {aid for aid in remaining if deps[aid].issubset(completed)}
            if not ready:
                # Cycle detected — put remaining in a sequential group
                groups.append(list(remaining))
                break
            groups.append(list(ready))
            completed.update(ready)
            remaining -= ready

        return groups

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_active_plans(self) -> dict[str, DynamicOrchestrationPlan]:
        """Return all stored plans."""
        return dict(self._active_plans)

    def get_history(self, limit: int = 20) -> list[dict[str, Any]]:
        """Return recent execution history.

        Args:
            limit: Maximum number of history entries to return.

        Returns:
            List of history dicts, most recent first.
        """
        return list(reversed(self._execution_history[-limit:]))

    def get_stats(self) -> dict[str, Any]:
        """Return orchestrator statistics."""
        total = len(self._execution_history)
        successes = sum(1 for h in self._execution_history if h["success"])
        return {
            "total_orchestrations": total,
            "successes": successes,
            "success_rate": round(successes / total, 3) if total else 0.0,
            "active_plans": len(self._active_plans),
            "history_size": total,
            "avg_tokens": (
                round(
                    sum(h["tokens"] for h in self._execution_history) / total,
                    1,
                )
                if total else 0
            ),
            "avg_time": (
                round(
                    sum(h["time"] for h in self._execution_history) / total,
                    2,
                )
                if total else 0.0
            ),
        }
