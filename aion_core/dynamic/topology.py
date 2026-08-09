#!/usr/bin/env python3
"""
Topology Manager for Aion Hand.
=================================

Learns which agent combinations (topologies) work best for different
task types. Tracks execution outcomes, suggests optimal topologies,
and can evolve existing topologies based on lessons learned.

A topology is a directed acyclic graph (DAG) of agent roles with
connections defining data flow. The manager tracks metrics per
topology (success rate, token usage, latency) and uses these to
suggest the best topology for a given task.

Features:
    - 4 pre-seeded topologies for common workflows
    - Heuristic-based topology suggestion
    - Lesson-driven topology evolution (add/remove agents)
    - Pattern analysis across execution history
    - JSON persistence for learning continuity
"""

from __future__ import annotations

import json
import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("aion_hand.dynamic.topology")


# ============================================================================
# Data structures
# ============================================================================


@dataclass
class AgentTopology:
    """Describes a pattern of agent roles and their connections.

    A topology defines which agents to use, in what order, and how
    data flows between them. The orchestrator uses this to create
    the actual agent instances and determine parallel execution groups.

    Attributes:
        id: Unique identifier (8-char hex).
        name: Human-readable name for this topology.
        agents: Ordered list of role names (e.g. ["planner", "coder", "verifier"]).
        connections: Directed edges defining data flow between agents.
        success_rate: Running average of successful executions (0.0-1.0).
        avg_tokens: Running average of tokens consumed.
        avg_time: Running average of execution time in seconds.
        task_types: List of task types this topology has been used for.
        usage_count: Total number of times this topology has been executed.
        is_default: Whether this is a pre-seeded topology.
    """

    id: str
    name: str
    agents: list[str]
    connections: list[dict[str, str]]
    success_rate: float = 0.0
    avg_tokens: float = 0.0
    avg_time: float = 0.0
    task_types: list[str] = field(default_factory=list)
    usage_count: int = 0
    is_default: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "agents": self.agents,
            "connections": self.connections,
            "success_rate": self.success_rate,
            "avg_tokens": self.avg_tokens,
            "avg_time": self.avg_time,
            "task_types": self.task_types,
            "usage_count": self.usage_count,
            "is_default": self.is_default,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentTopology:
        return cls(**data)

    def compatibility_score(self, task_type: str, complexity: int) -> float:
        """Heuristic score (0-1) for how well this topology fits a task.

        Scoring breakdown:
        - Task type match: up to 0.4 points
        - Historical success rate: up to 0.4 points
        - Agent count vs. complexity: up to 0.2 points
        """
        score = 0.0

        # Task type match (up to 0.4)
        if task_type in self.task_types:
            # More usage = higher confidence in the match
            type_weight = min(1.0, self.usage_count / 5.0)
            score += 0.4 * type_weight
        elif self.task_types:
            # Partial credit for general-purpose topologies
            score += 0.15

        # Success rate (up to 0.4)
        score += self.success_rate * 0.4

        # Size-complexity match (up to 0.2)
        # Simple tasks (1-3) prefer fewer agents; complex (7-10) prefer more.
        ideal_size = max(2, min(6, complexity))
        size_diff = abs(len(self.agents) - ideal_size)
        score += max(0.0, 0.2 - size_diff * 0.05)

        return min(score, 1.0)


# ============================================================================
# Topology Manager
# ============================================================================


class TopologyManager:
    """Manages, persists, and learns from agent topologies.

    Responsibilities:
        - Seed default topologies on initialization
        - Record execution outcomes for learning
        - Suggest the best topology for a given task
        - Evolve topologies based on lessons learned
        - Analyze patterns across execution history
        - Persist state to JSON for continuity

    Usage:
        mgr = TopologyManager()
        topo = mgr.suggest_topology("coding", complexity=7)
        mgr.record_execution(topo.id, "coding", success=True, tokens=5000, time=12.3)
        patterns = mgr.analyze_patterns()
    """

    def __init__(self, storage_dir: Path | None = None) -> None:
        """Initialize the topology manager.

        Args:
            storage_dir: Directory for JSON persistence.
        """
        self._storage_dir = storage_dir or Path.home() / ".aion-hand" / "dynamic"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._topologies: dict[str, AgentTopology] = {}
        self._execution_log: list[dict[str, Any]] = []
        self._seed_default_topologies()
        logger.info(
            f"TopologyManager initialized with {len(self._topologies)} topologies"
        )

    # ------------------------------------------------------------------
    # Built-in topologies
    # ------------------------------------------------------------------

    def _seed_default_topologies(self) -> None:
        """Pre-populate with commonly useful topology patterns."""
        defaults = [
            {
                "name": "Plan-Code-Verify",
                "agents": ["planner", "coder", "verifier"],
                "connections": [
                    {"from": "planner", "to": "coder", "label": "plan"},
                    {"from": "coder", "to": "verifier", "label": "code"},
                ],
                "task_types": ["coding", "development", "implementation"],
            },
            {
                "name": "Research-Verify-Summarize",
                "agents": ["researcher", "fact_checker", "summarizer"],
                "connections": [
                    {"from": "researcher", "to": "fact_checker", "label": "findings"},
                    {"from": "fact_checker", "to": "summarizer", "label": "verified"},
                ],
                "task_types": ["research", "analysis", "investigation"],
            },
            {
                "name": "Code-Critique-Repair",
                "agents": ["coder", "critic", "repairer"],
                "connections": [
                    {"from": "coder", "to": "critic", "label": "draft"},
                    {"from": "critic", "to": "repairer", "label": "feedback"},
                ],
                "task_types": ["code_review", "refactoring", "bugfix"],
            },
            {
                "name": "Full Pipeline",
                "agents": [
                    "planner",
                    "researcher",
                    "coder",
                    "critic",
                    "repairer",
                    "verifier",
                    "summarizer",
                ],
                "connections": [
                    {"from": "planner", "to": "researcher", "label": "plan"},
                    {"from": "researcher", "to": "coder", "label": "research"},
                    {"from": "coder", "to": "critic", "label": "code"},
                    {"from": "critic", "to": "repairer", "label": "critique"},
                    {"from": "repairer", "to": "verifier", "label": "fixed_code"},
                    {"from": "verifier", "to": "summarizer", "label": "verification"},
                ],
                "task_types": ["complex", "full_pipeline", "end_to_end"],
            },
        ]
        for d in defaults:
            topo = AgentTopology(
                id=uuid.uuid4().hex[:8],
                name=d["name"],
                agents=d["agents"],
                connections=d["connections"],
                task_types=d["task_types"],
                is_default=True,
            )
            self._topologies[topo.id] = topo
        logger.info(f"Seeded {len(defaults)} default topologies")

    # ------------------------------------------------------------------
    # Recording
    # ------------------------------------------------------------------

    def record_execution(
        self,
        topology_id: str,
        task_type: str,
        success: bool,
        tokens: int,
        time: float,
    ) -> None:
        """Record the outcome of a topology execution for learning.

        Updates running averages for success_rate, avg_tokens, and avg_time.
        Appends to execution log for pattern analysis.

        Args:
            topology_id: ID of the topology that was executed.
            task_type: Category of the task (e.g. "coding", "research").
            success: Whether the execution achieved its goals.
            tokens: Total tokens consumed by all agents in the topology.
            time: Total wall-clock time in seconds.
        """
        topo = self._topologies.get(topology_id)
        if topo is None:
            logger.warning(f"record_execution: unknown topology '{topology_id}'")
            return

        topo.usage_count += 1

        # Add task type if new
        if task_type not in topo.task_types:
            topo.task_types.append(task_type)

        # Running average using Welford's online algorithm
        n = topo.usage_count
        topo.success_rate = (
            (topo.success_rate * (n - 1)) + (1.0 if success else 0.0)
        ) / n
        topo.avg_tokens = (topo.avg_tokens * (n - 1) + tokens) / n
        topo.avg_time = (topo.avg_time * (n - 1) + time) / n

        self._execution_log.append(
            {
                "topology_id": topology_id,
                "topology_name": topo.name,
                "task_type": task_type,
                "success": success,
                "tokens": tokens,
                "time": time,
            }
        )

        logger.info(
            f"Recorded execution: topo={topo.name}, success={success}, "
            f"tokens={tokens}, time={time:.2f}s, "
            f"running_rate={topo.success_rate:.2%}"
        )

    # ------------------------------------------------------------------
    # Suggestion
    # ------------------------------------------------------------------

    def suggest_topology(
        self,
        task_type: str,
        complexity: int = 5,
    ) -> AgentTopology | None:
        """Return the best topology for the given task type and complexity.

        Scores all topologies and returns the one with the highest
        compatibility score.

        Args:
            task_type: Category of the task (e.g. "coding", "research").
            complexity: Task complexity from 1 (trivial) to 10 (extreme).

        Returns:
            Best matching AgentTopology, or None if no topologies exist.
        """
        if not self._topologies:
            return None

        scored: list[tuple[float, AgentTopology]] = [
            (t.compatibility_score(task_type, complexity), t)
            for t in self._topologies.values()
        ]
        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best = scored[0]

        logger.info(
            f"Suggested topology '{best.name}' (score={best_score:.2f}) "
            f"for task_type='{task_type}', complexity={complexity}"
        )
        return best

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def create_topology(
        self,
        agents: list[str],
        connections: list[dict[str, str]],
        task_types: list[str] | None = None,
        name: str | None = None,
    ) -> AgentTopology:
        """Create and register a new topology.

        Args:
            agents: Ordered list of agent role names.
            connections: Directed edges between agents.
            task_types: Categories this topology is suited for.
            name: Human-readable name.

        Returns:
            The newly created AgentTopology.
        """
        topo = AgentTopology(
            id=uuid.uuid4().hex[:8],
            name=name or f"Topology-{len(self._topologies) + 1}",
            agents=agents,
            connections=connections,
            task_types=task_types or [],
        )
        self._topologies[topo.id] = topo
        logger.info(
            f"Created topology '{topo.name}' (id={topo.id}) with agents={agents}"
        )
        return topo

    def remove_topology(self, topology_id: str) -> bool:
        """Remove a topology by ID.

        Args:
            topology_id: ID of the topology to remove.

        Returns:
            True if removed, False if not found.
        """
        topo = self._topologies.pop(topology_id, None)
        if topo is None:
            logger.warning(f"Cannot remove topology '{topology_id}': not found")
            return False
        logger.info(f"Removed topology '{topo.name}' (id={topology_id})")
        return True

    def evolve_topology(
        self,
        topology_id: str,
        lesson: str,
    ) -> AgentTopology | None:
        """Apply a lesson to a topology, producing a modified copy.

        Uses heuristic mutations based on keywords in the lesson text.
        A more sophisticated version could use an LLM for decisions.

        Supported mutations:
        - "add verifier" / "needs verification" -> append verifier agent
        - "add critic" / "needs review" -> append critic agent
        - "add fact_checker" / "needs fact checking" -> append fact_checker
        - "remove summarizer" -> remove summarizer and its connections
        - "parallel" -> mark connections for parallel execution

        Args:
            topology_id: ID of the topology to evolve.
            lesson: Natural language description of what to change.

        Returns:
            New evolved AgentTopology, or the existing match if duplicate.
        """
        original = self._topologies.get(topology_id)
        if original is None:
            logger.warning(f"evolve_topology: unknown topology '{topology_id}'")
            return None

        new_agents = list(original.agents)
        new_connections = [dict(c) for c in original.connections]
        lesson_lower = lesson.lower()

        # Heuristic mutations based on lesson keywords
        mutations_applied = []

        if "add verifier" in lesson_lower or "needs verification" in lesson_lower:
            if "verifier" not in new_agents:
                new_agents.append("verifier")
                if new_agents:
                    new_connections.append(
                        {
                            "from": new_agents[-2],
                            "to": "verifier",
                            "label": "output",
                        }
                    )
                mutations_applied.append("added verifier")

        if "add critic" in lesson_lower or "needs review" in lesson_lower:
            if "critic" not in new_agents:
                new_agents.append("critic")
                if len(new_agents) >= 2:
                    new_connections.append(
                        {
                            "from": new_agents[-2],
                            "to": "critic",
                            "label": "draft",
                        }
                    )
                mutations_applied.append("added critic")

        if "add fact_checker" in lesson_lower or "needs fact checking" in lesson_lower:
            if "fact_checker" not in new_agents:
                new_agents.append("fact_checker")
                if len(new_agents) >= 2:
                    new_connections.append(
                        {
                            "from": new_agents[-2],
                            "to": "fact_checker",
                            "label": "claims",
                        }
                    )
                mutations_applied.append("added fact_checker")

        if "remove summarizer" in lesson_lower or "skip summary" in lesson_lower:
            if "summarizer" in new_agents:
                new_agents.remove("summarizer")
                new_connections = [
                    c
                    for c in new_connections
                    if c.get("to") != "summarizer" and c.get("from") != "summarizer"
                ]
                mutations_applied.append("removed summarizer")

        if "remove researcher" in lesson_lower and "researcher" in new_agents:
            new_agents.remove("researcher")
            new_connections = [
                c
                for c in new_connections
                if c.get("to") != "researcher" and c.get("from") != "researcher"
            ]
            # Reconnect around the removed agent
            for i, conn in enumerate(new_connections):
                if conn.get("label") == "research":
                    new_connections[i]["label"] = "direct"
            mutations_applied.append("removed researcher")

        if "parallel" in lesson_lower:
            for conn in new_connections:
                if conn.get("label") == "output":
                    conn["label"] = "output (parallel)"
                elif conn.get("label") == "findings":
                    conn["label"] = "findings (parallel)"
            mutations_applied.append("marked parallel")

        if not mutations_applied:
            logger.info("No applicable mutations found in lesson")
            return None

        # Don't create a duplicate
        for existing in self._topologies.values():
            if existing.agents == new_agents:
                logger.info(
                    f"Evolved topology matches existing '{existing.name}', "
                    f"returning existing instead of creating duplicate"
                )
                return existing

        evolved = self.create_topology(
            agents=new_agents,
            connections=new_connections,
            task_types=list(original.task_types),
            name=f"{original.name} (evolved)",
        )
        logger.info(
            f"Evolved topology '{original.name}' -> '{evolved.name}' "
            f"(mutations: {', '.join(mutations_applied)})"
        )
        return evolved

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def get_best_topologies(self, limit: int = 5) -> list[AgentTopology]:
        """Return top-performing topologies sorted by success rate.

        Args:
            limit: Maximum number of topologies to return.

        Returns:
            List of AgentTopology sorted by (success_rate, -avg_tokens).
        """
        sorted_topos = sorted(
            self._topologies.values(),
            key=lambda t: (t.success_rate, -t.avg_tokens),
            reverse=True,
        )
        return sorted_topos[:limit]

    def analyze_patterns(self) -> dict[str, Any]:
        """Analyze execution log to find patterns in successful topologies.

        Returns:
            Dict with patterns, insights, and summary statistics.
        """
        if not self._execution_log:
            return {
                "patterns": [],
                "total_executions": 0,
                "topologies_tracked": 0,
                "summary": "No execution data yet. Patterns will emerge as topologies are used.",
            }

        # Group by topology
        by_topo: dict[str, list[dict]] = defaultdict(list)
        for entry in self._execution_log:
            by_topo[entry["topology_id"]].append(entry)

        patterns = []
        for topo_id, entries in by_topo.items():
            topo = self._topologies.get(topo_id)
            successes = [e for e in entries if e["success"]]
            failures = [e for e in entries if not e["success"]]
            success_rate = len(successes) / len(entries) if entries else 0

            # Most common successful task type
            task_counts: dict[str, int] = defaultdict(int)
            for e in successes:
                task_counts[e["task_type"]] += 1
            best_task = (
                max(task_counts, key=task_counts.get) if task_counts else "unknown"
            )

            # Efficiency score: success rate / (avg_tokens / 1000)
            avg_t = sum(e["tokens"] for e in entries) / len(entries) if entries else 0
            efficiency = success_rate / (avg_t / 1000 + 1)

            patterns.append(
                {
                    "topology_name": topo.name if topo else topo_id,
                    "topology_id": topo_id,
                    "topology_agents": topo.agents if topo else [],
                    "executions": len(entries),
                    "successes": len(successes),
                    "failures": len(failures),
                    "success_rate": round(success_rate, 3),
                    "avg_tokens": round(avg_t, 1),
                    "avg_time": round(
                        sum(e["time"] for e in entries) / len(entries), 2
                    ),
                    "best_task_type": best_task,
                    "efficiency_score": round(efficiency, 3),
                    "insight": self._generate_insight(
                        success_rate, len(topo.agents) if topo else 0
                    ),
                }
            )

        # Sort by success rate descending
        patterns.sort(key=lambda p: p["success_rate"], reverse=True)

        # Cross-topology insights
        overall_success = sum(1 for e in self._execution_log if e["success"]) / len(
            self._execution_log
        )
        best_overall = patterns[0] if patterns else {}

        return {
            "patterns": patterns,
            "total_executions": len(self._execution_log),
            "topologies_tracked": len(by_topo),
            "overall_success_rate": round(overall_success, 3),
            "best_topology": best_overall.get("topology_name", "none"),
            "recommendations": self._generate_recommendations(patterns),
        }

    @staticmethod
    def _generate_insight(success_rate: float, agent_count: int) -> str:
        """Produce a human-readable insight about a topology's performance."""
        if success_rate >= 0.9:
            return (
                f"Excellent performer. The {agent_count}-agent pipeline "
                f"is highly reliable. Use this topology confidently for "
                f"matching task types."
            )
        elif success_rate >= 0.7:
            return (
                f"Good performer. The {agent_count}-agent pipeline works "
                f"well but has room for minor tuning. Consider adjusting "
                f"agent order or adding context passing."
            )
        elif success_rate >= 0.5:
            return (
                f"Moderate success. The {agent_count}-agent pipeline may "
                f"benefit from adding verification steps or improving "
                f"inter-agent context flow."
            )
        else:
            return (
                f"Low success rate. Consider restructuring the "
                f"{agent_count}-agent pipeline, trying a different topology, "
                f"or reducing complexity."
            )

    @staticmethod
    def _generate_recommendations(patterns: list[dict]) -> list[str]:
        """Generate actionable recommendations from pattern analysis."""
        recommendations = []

        if not patterns:
            return ["Execute more tasks to generate recommendations."]

        # Check for underperformers
        for p in patterns:
            if p["success_rate"] < 0.5 and p["executions"] >= 3:
                recommendations.append(
                    f"Consider retiring '{p['topology_name']}' — "
                    f"low success rate ({p['success_rate']:.0%}) after "
                    f"{p['executions']} executions."
                )

        # Check for high-efficiency winners
        if len(patterns) >= 2:
            best = patterns[0]
            if best["success_rate"] >= 0.8:
                recommendations.append(
                    f"'{best['topology_name']}' is a strong performer — "
                    f"prefer it for '{best['best_task_type']}' tasks."
                )

        # Token efficiency
        for p in patterns:
            if p["avg_tokens"] > 10000 and p["success_rate"] < 0.6:
                recommendations.append(
                    f"'{p['topology_name']}' uses high tokens ({p['avg_tokens']:.0f}) "
                    f"with low success. Consider a lighter alternative."
                )

        if not recommendations:
            recommendations.append(
                "All topologies performing within acceptable ranges."
            )

        return recommendations

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self) -> None:
        """Persist topologies and execution log to disk."""
        data = {
            "topologies": [t.to_dict() for t in self._topologies.values()],
            "execution_log": self._execution_log,
        }
        path = self._storage_dir / "topologies.json"
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        logger.info(
            f"Saved {len(self._topologies)} topologies and "
            f"{len(self._execution_log)} execution records to {path}"
        )

    def load(self) -> None:
        """Load topologies and execution log from disk."""
        path = self._storage_dir / "topologies.json"
        if not path.exists():
            logger.info("No topology data to load — using defaults")
            return
        with open(path) as f:
            data = json.load(f)
        self._topologies.clear()
        for td in data.get("topologies", []):
            topo = AgentTopology.from_dict(td)
            self._topologies[topo.id] = topo
        self._execution_log = data.get("execution_log", [])
        logger.info(
            f"Loaded {len(self._topologies)} topologies and "
            f"{len(self._execution_log)} execution records"
        )

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def get_topology(self, topology_id: str) -> AgentTopology | None:
        """Get a topology by ID."""
        return self._topologies.get(topology_id)

    def list_topologies(self) -> list[AgentTopology]:
        """Return all registered topologies."""
        return list(self._topologies.values())

    def get_stats(self) -> dict[str, Any]:
        """Return comprehensive topology statistics."""
        return {
            "topology_count": len(self._topologies),
            "default_count": sum(1 for t in self._topologies.values() if t.is_default),
            "execution_log_size": len(self._execution_log),
            "total_executions": len(self._execution_log),
            "overall_success_rate": (
                round(
                    sum(1 for e in self._execution_log if e["success"])
                    / len(self._execution_log),
                    3,
                )
                if self._execution_log
                else 0.0
            ),
            "topologies": {
                t.name: {
                    "success_rate": round(t.success_rate, 3),
                    "usage_count": t.usage_count,
                    "agents": t.agents,
                    "task_types": t.task_types,
                    "avg_tokens": round(t.avg_tokens, 1),
                    "avg_time": round(t.avg_time, 2),
                }
                for t in self._topologies.values()
            },
        }
