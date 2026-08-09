# Aion Hand - Dynamic Planner
# Creates execution graphs (DAGs) from mission analysis.

import json
import logging
from dataclasses import asdict, dataclass, field
from typing import Any

from .mission import MissionAnalysis

logger = logging.getLogger("aion_hand.pipeline")


@dataclass
class PlanNode:
    """A single node in the execution plan graph."""

    id: str = ""
    name: str = ""
    node_type: str = "agent"  # agent, tool, parallel, condition, merge, verify
    agent_type: str | None = None  # planner, coder, researcher, verifier
    tool_name: str | None = None
    prompt: str | None = None
    dependencies: list[str] = field(default_factory=list)
    parallel_group: str | None = None
    retry_limit: int = 2
    timeout: int = 120
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PlanNode":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ExecutionPlan:
    """A complete execution plan: a DAG of PlanNodes."""

    nodes: dict[str, PlanNode] = field(default_factory=dict)
    entry_node: str = ""
    total_estimated_tokens: int = 0
    total_estimated_time: int = 0
    complexity: float = 0.5
    risk_level: str = "low"  # low, medium, high

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": {nid: n.to_dict() for nid, n in self.nodes.items()},
            "entry_node": self.entry_node,
            "total_estimated_tokens": self.total_estimated_tokens,
            "total_estimated_time": self.total_estimated_time,
            "complexity": self.complexity,
            "risk_level": self.risk_level,
        }


class DynamicPlanner:
    """Creates execution plans (DAGs) based on mission analysis.

    Simple tasks get a linear chain: analyze -> execute -> verify
    Complex tasks get parallel branches, merge points, and conditional routing.
    Always terminates with a verification node.
    """

    PLANNING_SYSTEM_PROMPT = """You are an execution planner for an AI agent. Given a mission analysis,
you must create an execution plan as a JSON array of nodes. Each node has:
- id: unique string like "step_1", "step_2a", "step_2b"
- name: human-readable name
- node_type: one of "agent", "tool", "parallel", "condition", "merge", "verify"
- agent_type: for agent nodes, one of "planner", "coder", "researcher", "verifier"
- tool_name: for tool nodes, the tool to call
- prompt: for agent/verify nodes, the prompt to use (use {context} placeholder for upstream results)
- dependencies: list of node IDs this node depends on (must complete first)
- parallel_group: if multiple nodes share the same parallel_group, they run concurrently
- retry_limit: how many retries on failure (0-3)
- timeout: max seconds for this node

Rules:
1. First node has no dependencies (entry node)
2. Last node must be type "verify"
3. Nodes in the same parallel_group run concurrently (they should NOT depend on each other)
4. A "merge" node collects results from parallel branches (depends on all of them)
5. For parallel groups, add a merge node afterwards
6. Keep plans minimal - don't over-plan simple tasks
7. Use {upstream_results} in prompts to reference results from dependency nodes

Return ONLY the JSON array. No markdown, no explanation."""

    def __init__(self, agent: Any):
        self._agent = agent

    async def plan(
        self,
        mission: MissionAnalysis,
        lessons: list[Any] | None = None,
    ) -> ExecutionPlan:
        """Build an execution plan from mission analysis.

        Args:
            mission: The analyzed mission from MissionAnalyzer.
            lessons: Optional past lessons to inform planning decisions.

        Returns:
            A complete ExecutionPlan with all nodes and dependencies.
        """
        logger.info(f"Planning execution for: {mission.intent[:80]}")

        # Determine risk level
        risk_level = self._determine_risk_level(mission)

        # For simple tasks, use deterministic planning (no LLM needed)
        if mission.complexity < 0.4 and len(mission.goals) <= 2:
            plan = self._create_simple_plan(mission, risk_level)
        # For complex tasks, use LLM-assisted planning
        else:
            plan = await self._create_complex_plan(mission, risk_level, lessons)

        # Always ensure a verification node exists
        self._ensure_verification_node(plan, mission)

        # Add retry protection for risky operations
        if risk_level in ("medium", "high"):
            self._add_retry_protection(plan, mission)

        # Apply lessons learned
        if lessons:
            self._apply_lessons(plan, lessons)

        # Calculate totals
        plan.total_estimated_tokens = mission.estimated_tokens + sum(
            n.metadata.get("node_tokens", 200) for n in plan.nodes.values()
        )
        plan.total_estimated_time = mission.estimated_time + sum(
            n.timeout for n in plan.nodes.values()
        )
        plan.complexity = mission.complexity
        plan.risk_level = risk_level

        logger.info(
            f"Plan created: {len(plan.nodes)} nodes, entry={plan.entry_node}, "
            f"risk={risk_level}, est_tokens={plan.total_estimated_tokens}"
        )
        return plan

    async def replan(
        self, plan: ExecutionPlan, failure_point: str, error: str
    ) -> ExecutionPlan:
        """Dynamically modify a plan based on execution failure.

        Adds repair nodes, alternative paths, and retry strategies.

        Args:
            plan: The original execution plan.
            failure_point: The node ID that failed.
            error: The error message from the failure.

        Returns:
            A modified ExecutionPlan with repair strategies.
        """
        logger.info(f"Replanning after failure at '{failure_point}': {error[:100]}")

        failed_node = plan.nodes.get(failure_point)
        if not failed_node:
            logger.error(f"Failure point '{failure_point}' not found in plan")
            return plan

        # Create a repair node
        repair_id = f"repair_{failure_point}"
        repair_prompt = (
            f"The previous step '{failed_node.name}' failed with error: {error}\n\n"
            f"Original task for that step: {failed_node.prompt or failed_node.name}\n\n"
            f"Please attempt to complete the same goal using a different approach. "
            f"Address the specific error that occurred."
        )

        repair_node = PlanNode(
            id=repair_id,
            name=f"Repair: {failed_node.name}",
            node_type="agent",
            agent_type=(
                "coder" if "code" in (failed_node.prompt or "").lower() else "planner"
            ),
            prompt=repair_prompt,
            dependencies=list(failed_node.dependencies),
            retry_limit=1,
            timeout=failed_node.timeout + 60,
            metadata={"is_repair": True, "repairing": failure_point},
        )

        # Find all nodes that depended on the failed node and redirect to repair
        downstream = []
        for nid, node in plan.nodes.items():
            if failure_point in node.dependencies:
                downstream.append(nid)

        # Replace failure_point with repair_id in downstream dependencies
        for nid in downstream:
            node = plan.nodes[nid]
            node.dependencies = [
                repair_id if dep == failure_point else dep for dep in node.dependencies
            ]

        # If the failed node was the entry, make repair the new entry
        if plan.entry_node == failure_point:
            plan.entry_node = repair_id

        # Add the repair node to the plan
        plan.nodes[repair_id] = repair_node

        # Mark the failed node as failed (keep it for reference but don't re-execute)
        failed_node.metadata["failed"] = True
        failed_node.metadata["error"] = error

        logger.info(
            f"Replan complete: added repair node '{repair_id}', redirected {len(downstream)} downstream nodes"
        )
        return plan

    def _determine_risk_level(self, mission: MissionAnalysis) -> str:
        """Determine overall risk level from mission analysis."""
        risk_score = 0.0
        risk_score += mission.complexity * 0.4
        risk_score += min(len(mission.risks) * 0.1, 0.3)
        dangerous_caps = {"shell", "database", "api_call", "file_write"}
        if any(cap in dangerous_caps for cap in mission.capabilities_needed):
            risk_score += 0.15
        if len(mission.goals) > 3:
            risk_score += 0.15
        if risk_score >= 0.6:
            return "high"
        elif risk_score >= 0.3:
            return "medium"
        return "low"

    def _create_simple_plan(
        self, mission: MissionAnalysis, risk_level: str
    ) -> ExecutionPlan:
        """Create a linear execution plan for simple tasks."""
        nodes = {}

        exec_prompt = (
            f"Task: {mission.raw_task}\n\n"
            f"Goals:\n" + "\n".join(f"- {g}" for g in mission.goals) + "\n\n"
            "Please complete this task thoroughly."
        )
        if mission.constraints:
            exec_prompt += "\n\nConstraints:\n" + "\n".join(
                f"- {c}" for c in mission.constraints
            )

        exec_node = PlanNode(
            id="step_execute",
            name="Execute Task",
            node_type="agent",
            agent_type=(
                "coder"
                if "code" in " ".join(mission.capabilities_needed)
                else "planner"
            ),
            prompt=exec_prompt,
            dependencies=[],
            retry_limit=2 if risk_level != "low" else 1,
            timeout=max(mission.estimated_time + 30, 120),
            metadata={"node_tokens": mission.estimated_tokens},
        )
        nodes["step_execute"] = exec_node

        return ExecutionPlan(
            nodes=nodes,
            entry_node="step_execute",
            total_estimated_tokens=mission.estimated_tokens,
            total_estimated_time=mission.estimated_time,
            complexity=mission.complexity,
            risk_level=risk_level,
        )

    async def _create_complex_plan(
        self,
        mission: MissionAnalysis,
        risk_level: str,
        lessons: list[Any] | None,
    ) -> ExecutionPlan:
        """Create a complex execution plan using LLM assistance."""
        capabilities_str = ", ".join(mission.capabilities_needed)
        constraints_str = (
            "\n".join(f"- {c}" for c in mission.constraints)
            if mission.constraints
            else "None specified"
        )
        risks_str = (
            "\n".join(f"- {r}" for r in mission.risks)
            if mission.risks
            else "None identified"
        )
        goals_str = "\n".join(f"- {g}" for g in mission.goals)

        lesson_str = ""
        if lessons:
            lesson_parts = []
            for lesson in lessons[:5]:
                if hasattr(lesson, "mistakes") and lesson.mistakes:
                    lesson_parts.append(f"- Avoid: {', '.join(lesson.mistakes[:3])}")
                if hasattr(lesson, "learned_rules") and lesson.learned_rules:
                    lesson_parts.append(f"- Rule: {lesson.learned_rules[0]}")
            if lesson_parts:
                lesson_str = "\n\nLessons from past similar tasks:\n" + "\n".join(
                    lesson_parts
                )

        user_message = (
            f"Create an execution plan for this mission:\n\n"
            f"Intent: {mission.intent}\n\n"
            f"Goals:\n{goals_str}\n\n"
            f"Constraints:\n{constraints_str}\n\n"
            f"Risks:\n{risks_str}\n\n"
            f"Complexity: {mission.complexity}\n"
            f"Capabilities needed: {capabilities_str}\n"
            f"Estimated time: {mission.estimated_time}s\n"
            f"Risk level: {risk_level}"
            f"{lesson_str}"
        )

        try:
            result = await self._agent.chat(message=user_message)
            raw_content = (
                result.get("content", "") if isinstance(result, dict) else str(result)
            )
        except Exception as e:
            logger.warning(f"LLM planning failed, using deterministic fallback: {e}")
            return self._create_deterministic_complex_plan(mission, risk_level)

        plan = self._parse_llm_plan(raw_content, mission, risk_level)
        if not plan.nodes:
            logger.warning("LLM plan parsing failed, using deterministic fallback")
            return self._create_deterministic_complex_plan(mission, risk_level)

        return plan

    def _parse_llm_plan(
        self, raw_content: str, mission: MissionAnalysis, risk_level: str
    ) -> ExecutionPlan:
        """Parse LLM-generated plan JSON into an ExecutionPlan."""
        import re

        json_str = None
        code_block_match = re.search(
            r"```(?:json)?\s*\n?(\[.*?\])\s*\n?```", raw_content, re.DOTALL
        )
        if code_block_match:
            json_str = code_block_match.group(1)
        else:
            bracket_start = raw_content.find("[")
            bracket_end = raw_content.rfind("]")
            if bracket_start != -1 and bracket_end > bracket_start:
                json_str = raw_content[bracket_start : bracket_end + 1]

        if not json_str:
            return ExecutionPlan(risk_level=risk_level, complexity=mission.complexity)

        try:
            nodes_data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse plan JSON: {e}")
            return ExecutionPlan(risk_level=risk_level, complexity=mission.complexity)

        if not isinstance(nodes_data, list) or len(nodes_data) == 0:
            return ExecutionPlan(risk_level=risk_level, complexity=mission.complexity)

        nodes = {}
        entry_node = ""
        all_node_ids = [n.get("id", f"step_{i+1}") for i, n in enumerate(nodes_data)]

        for i, node_data in enumerate(nodes_data):
            node_id = node_data.get("id", f"step_{i+1}")
            raw_deps = node_data.get("dependencies", [])
            valid_deps = [d for d in raw_deps if d in all_node_ids or d in nodes]

            node = PlanNode(
                id=node_id,
                name=node_data.get("name", f"Step {i+1}"),
                node_type=node_data.get("node_type", "agent"),
                agent_type=node_data.get("agent_type"),
                tool_name=node_data.get("tool_name"),
                prompt=node_data.get("prompt"),
                dependencies=valid_deps,
                parallel_group=node_data.get("parallel_group"),
                retry_limit=self._safe_int(node_data.get("retry_limit"), 2),
                timeout=self._safe_int(node_data.get("timeout"), 120),
            )
            nodes[node_id] = node

            if i == 0 or not valid_deps:
                entry_node = node_id

        if not entry_node and nodes:
            entry_node = list(nodes.keys())[0]

        return ExecutionPlan(
            nodes=nodes,
            entry_node=entry_node,
            total_estimated_tokens=mission.estimated_tokens,
            total_estimated_time=mission.estimated_time,
            complexity=mission.complexity,
            risk_level=risk_level,
        )

    def _create_deterministic_complex_plan(
        self, mission: MissionAnalysis, risk_level: str
    ) -> ExecutionPlan:
        """Create a multi-step plan deterministically when LLM planning fails."""
        nodes = {}
        node_counter = [0]

        def next_id(prefix="step") -> str:
            node_counter[0] += 1
            return f"{prefix}_{node_counter[0]}"

        # Step 1: Research/analyze if multiple goals or research needed
        research_id = next_id("research")
        needs_research = any(
            cap in mission.capabilities_needed
            for cap in ["web_search", "data_analysis", "browser"]
        )
        if needs_research or len(mission.goals) > 1:
            research_prompt = (
                f"Analyze this task and gather necessary information:\n\n"
                f"Task: {mission.raw_task}\n\n"
                f"Goals:\n" + "\n".join(f"- {g}" for g in mission.goals) + "\n\n"
                "Identify what information is needed, what approach to take, "
                "and any potential issues. Provide a clear analysis."
            )
            nodes[research_id] = PlanNode(
                id=research_id,
                name="Research & Analyze",
                node_type="agent",
                agent_type="researcher",
                prompt=research_prompt,
                dependencies=[],
                retry_limit=1,
                timeout=90,
            )

        execution_deps = [research_id] if research_id in nodes else []
        goal_nodes = []

        if len(mission.goals) > 1 and mission.complexity > 0.5:
            group_id = "parallel_goals"
            for _i, goal in enumerate(mission.goals[:5]):
                goal_id = next_id("goal")
                goal_prompt = (
                    f"Complete this specific goal:\n\n"
                    f"Goal: {goal}\n\n"
                    f"Overall task context: {mission.raw_task}\n\n"
                    f"Upstream research results: {{upstream_results}}\n\n"
                    f"Provide a thorough, complete response for this goal."
                )
                nodes[goal_id] = PlanNode(
                    id=goal_id,
                    name=f"Goal: {goal[:60]}",
                    node_type="agent",
                    agent_type="coder" if "code" in goal.lower() else "planner",
                    prompt=goal_prompt,
                    dependencies=list(execution_deps),
                    parallel_group=group_id,
                    retry_limit=2 if risk_level != "low" else 1,
                    timeout=max(
                        mission.estimated_time // max(len(mission.goals), 1) + 30, 60
                    ),
                )
                goal_nodes.append(goal_id)

            merge_id = next_id("merge")
            merge_prompt = (
                f"Merge the following results from parallel goal executions into a "
                f"coherent, comprehensive response:\n\n"
                f"Original task: {mission.raw_task}\n\n"
                f"Goals:\n" + "\n".join(f"- {g}" for g in mission.goals) + "\n\n"
                "Upstream results: {upstream_results}\n\n"
                "Synthesize all results into a unified, well-organized response. "
                "Resolve any conflicts between parallel results."
            )
            nodes[merge_id] = PlanNode(
                id=merge_id,
                name="Merge Results",
                node_type="merge",
                prompt=merge_prompt,
                dependencies=list(goal_nodes),
                retry_limit=1,
                timeout=90,
            )
        else:
            exec_id = next_id("execute")
            exec_prompt = (
                f"Task: {mission.raw_task}\n\n"
                f"Goals:\n" + "\n".join(f"- {g}" for g in mission.goals) + "\n\n"
            )
            if mission.constraints:
                exec_prompt += (
                    "Constraints:\n"
                    + "\n".join(f"- {c}" for c in mission.constraints)
                    + "\n\n"
                )
            if research_id in nodes:
                exec_prompt += "Research findings: {{upstream_results}}\n\n"
            exec_prompt += "Please complete this task thoroughly and precisely."

            nodes[exec_id] = PlanNode(
                id=exec_id,
                name="Execute Task",
                node_type="agent",
                agent_type=(
                    "coder"
                    if "code" in " ".join(mission.capabilities_needed)
                    else "planner"
                ),
                prompt=exec_prompt,
                dependencies=execution_deps,
                retry_limit=2 if risk_level != "low" else 1,
                timeout=max(mission.estimated_time + 30, 120),
            )

        entry_node = research_id if research_id in nodes else list(nodes.keys())[0]

        return ExecutionPlan(
            nodes=nodes,
            entry_node=entry_node,
            total_estimated_tokens=mission.estimated_tokens,
            total_estimated_time=mission.estimated_time,
            complexity=mission.complexity,
            risk_level=risk_level,
        )

    def _ensure_verification_node(
        self, plan: ExecutionPlan, mission: MissionAnalysis
    ) -> None:
        """Ensure the plan always ends with a verification node."""
        verify_nodes = [nid for nid, n in plan.nodes.items() if n.node_type == "verify"]

        if verify_nodes:
            terminal_nodes = self._find_terminal_nodes(plan)
            verify_node = plan.nodes[verify_nodes[-1]]
            for tid in terminal_nodes:
                if tid not in verify_nodes and tid != verify_nodes[-1]:
                    if tid not in verify_node.dependencies:
                        verify_node.dependencies.append(tid)
            return

        terminal_nodes = self._find_terminal_nodes(plan)
        verify_id = "verify_final"
        verify_prompt = (
            f"Verify the following task execution results:\n\n"
            f"Original task: {mission.raw_task}\n\n"
            f"Goals to verify:\n" + "\n".join(f"- {g}" for g in mission.goals) + "\n\n"
            "Upstream results: {upstream_results}\n\n"
            "Check: 1) All goals are addressed, 2) Results are consistent, "
            "3) No contradictions, 4) Constraints are respected. "
            "Provide a verification summary."
        )
        plan.nodes[verify_id] = PlanNode(
            id=verify_id,
            name="Final Verification",
            node_type="verify",
            agent_type="verifier",
            prompt=verify_prompt,
            dependencies=terminal_nodes,
            retry_limit=1,
            timeout=60,
            metadata={"is_final_verify": True},
        )

    def _find_terminal_nodes(self, plan: ExecutionPlan) -> list[str]:
        """Find nodes that nothing else depends on (terminal/leaf nodes)."""
        all_deps = set()
        for node in plan.nodes.values():
            all_deps.update(node.dependencies)
        terminal = [
            nid
            for nid in plan.nodes
            if nid not in all_deps and plan.nodes[nid].node_type != "verify"
        ]
        return terminal if terminal else [plan.entry_node]

    def _add_retry_protection(
        self, plan: ExecutionPlan, mission: MissionAnalysis
    ) -> None:
        """Add retry metadata and increase retry limits for risky nodes."""
        for node in plan.nodes.values():
            if node.node_type in ("agent", "tool") and node.retry_limit < 2:
                node.retry_limit = 2

        if plan.risk_level == "high":
            for node in plan.nodes.values():
                if node.node_type == "agent" and node.prompt:
                    safety_note = (
                        "\n\nIMPORTANT: Be cautious. If an operation seems risky, "
                        "explain the risk and ask for confirmation rather than proceeding."
                    )
                    if safety_note not in node.prompt:
                        node.prompt += safety_note

    def _apply_lessons(self, plan: ExecutionPlan, lessons: list[Any]) -> None:
        """Apply lessons from past executions to improve the plan."""
        applicable_rules = []
        for lesson in lessons[:10]:
            if hasattr(lesson, "learned_rules") and lesson.learned_rules:
                applicable_rules.extend(lesson.learned_rules[:2])
            if hasattr(lesson, "mistakes") and lesson.mistakes:
                for mistake in lesson.mistakes[:2]:
                    applicable_rules.append(f"Avoid: {mistake}")

        if not applicable_rules:
            return

        for node in plan.nodes.values():
            if node.node_type == "agent" and node.prompt:
                rules_text = "\n\nLearned rules from past executions:\n" + "\n".join(
                    f"- {r}" for r in applicable_rules[:8]
                )
                node.prompt += rules_text
                break

    @staticmethod
    def _safe_int(value: Any, default: int) -> int:
        """Safely convert to int."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return default
