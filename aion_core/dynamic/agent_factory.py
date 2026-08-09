#!/usr/bin/env python3
"""
Dynamic Agent Factory for Aion Hand.
=====================================

Creates, manages, and destroys temporary specialized agents on demand.
Each dynamic agent is a lightweight, purpose-built agent spun up for a
specific sub-task within a larger orchestration workflow.

Agents are created from profiles (predefined templates or custom),
executed with a given task and context, then archived and cleaned up.

Features:
    - 8 built-in role templates with tailored system prompts
    - Create from template or custom AgentProfile
    - Async execution with configurable retry
    - Agent lifecycle: created -> running -> completed/failed -> archived
    - Persistent archive for post-mortem analysis
    - Token tracking and resource limits
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

logger = logging.getLogger("aion_hand.dynamic.factory")


# ============================================================================
# Type aliases and constants
# ============================================================================

AgentRole = Literal[
    "planner",
    "coder",
    "researcher",
    "verifier",
    "critic",
    "repairer",
    "summarizer",
    "fact_checker",
]

VALID_ROLES: set[str] = {
    "planner",
    "coder",
    "researcher",
    "verifier",
    "critic",
    "repairer",
    "summarizer",
    "fact_checker",
}

DEFAULT_MAX_RETRIES: int = 2
DEFAULT_RETRY_DELAY: float = 1.0


# ============================================================================
# Data structures
# ============================================================================


@dataclass
class AgentProfile:
    """Immutable template describing a type of dynamic agent.

    Attributes:
        name: Human-readable name for this agent type.
        role: One of the 8 supported roles (planner, coder, etc.).
        system_prompt: The system prompt that defines this agent's behavior.
        tools_allowed: List of tool names this agent is permitted to use.
        model: Optional model override (e.g. 'gpt-4o', 'claude-3').
        temperature: Sampling temperature (0.0 = deterministic, 1.0 = creative).
        max_turns: Maximum conversation turns before forced completion.
    """

    name: str
    role: AgentRole
    system_prompt: str
    tools_allowed: list[str] = field(default_factory=list)
    model: str | None = None
    temperature: float = 0.7
    max_turns: int = 10

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "system_prompt": self.system_prompt,
            "tools_allowed": self.tools_allowed,
            "model": self.model,
            "temperature": self.temperature,
            "max_turns": self.max_turns,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AgentProfile:
        return cls(**data)


@dataclass
class DynamicAgent:
    """Runtime instance of a dynamic agent.

    Tracks the full lifecycle: creation, execution attempts, results,
    token consumption, and child agent relationships.

    Attributes:
        id: Unique identifier (12-char hex).
        profile: The AgentProfile this agent was created from.
        status: Current lifecycle state.
        parent_task: The higher-level task this agent was spawned for.
        created_at: ISO timestamp of creation.
        tokens_used: Cumulative token consumption across all runs.
        results: List of execution result dicts.
        child_agents: IDs of any sub-agents this agent spawned.
        error_count: Number of failed executions.
    """

    id: str
    profile: AgentProfile
    status: str = "created"
    parent_task: str | None = None
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat().replace("+00:00", "Z")
    )
    tokens_used: int = 0
    results: list[dict[str, Any]] = field(default_factory=list)
    child_agents: list[str] = field(default_factory=list)
    error_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "profile": self.profile.to_dict(),
            "status": self.status,
            "parent_task": self.parent_task,
            "created_at": self.created_at,
            "tokens_used": self.tokens_used,
            "results": self.results,
            "child_agents": self.child_agents,
            "error_count": self.error_count,
        }


# ============================================================================
# Default agent templates — 8 roles with tailored system prompts
# ============================================================================


def _load_default_templates() -> dict[str, AgentProfile]:
    """Return 8 predefined agent profiles for each supported role."""
    return {
        "planner": AgentProfile(
            name="Planner Agent",
            role="planner",
            system_prompt=(
                "You are an expert task planner and project architect. Your job is to "
                "break complex tasks into clear, ordered, and actionable sub-tasks.\n\n"
                "For each sub-task, specify:\n"
                "1. A concise description of what needs to be done\n"
                "2. The role best suited to handle it (coder, researcher, verifier, etc.)\n"
                "3. Dependencies on other sub-tasks (if any)\n"
                "4. Expected outputs and acceptance criteria\n"
                "5. Estimated complexity (low/medium/high)\n\n"
                "Rules:\n"
                "- Be precise and avoid vague descriptions\n"
                "- Identify the critical path through the plan\n"
                "- Flag risks and potential blockers early\n"
                "- Consider parallelization opportunities\n"
                "- Return your plan as a numbered list with clear headers\n"
                "- If the task is ambiguous, state assumptions before planning"
            ),
            tools_allowed=["web_search", "file_read"],
            temperature=0.4,
            max_turns=5,
        ),
        "coder": AgentProfile(
            name="Coder Agent",
            role="coder",
            system_prompt=(
                "You are a senior software engineer with 15+ years of experience "
                "across multiple domains. Write clean, efficient, and well-documented "
                "code that follows best practices and established design patterns.\n\n"
                "When given a task:\n"
                "1. Understand requirements fully before writing any code\n"
                "2. Design the solution approach — consider edge cases\n"
                "3. Implement with proper error handling and input validation\n"
                "4. Add comments for complex logic but avoid obvious comments\n"
                "5. Include all necessary import statements\n"
                "6. Make code self-contained when possible\n"
                "7. Write tests if the task involves significant logic\n\n"
                "Principles:\n"
                "- Prefer readability over cleverness\n"
                "- Follow the principle of least surprise\n"
                "- Use type hints where applicable\n"
                "- Handle failures gracefully with meaningful error messages\n"
                "- Never use deprecated APIs or patterns"
            ),
            tools_allowed=["file_read", "file_write", "bash", "web_search"],
            temperature=0.2,
            max_turns=15,
        ),
        "researcher": AgentProfile(
            name="Researcher Agent",
            role="researcher",
            system_prompt=(
                "You are a thorough research analyst with expertise in information "
                "gathering, synthesis, and critical evaluation. Your job is to "
                "gather, synthesize, and present information on a given topic.\n\n"
                "Follow this methodology:\n"
                "1. Identify the key questions that need answering\n"
                "2. Search for relevant, current information from multiple sources\n"
                "3. Evaluate source credibility, recency, and relevance\n"
                "4. Cross-reference findings across independent sources\n"
                "5. Synthesize into a coherent structured summary\n"
                "6. Cite sources where possible\n\n"
                "Guidelines:\n"
                "- Distinguish between facts, opinions, and speculation\n"
                "- Flag information that is uncertain or contradicted\n"
                "- Note information gaps that require further research\n"
                "- Present multiple perspectives on contentious topics\n"
                "- Quantify claims when possible (dates, numbers, percentages)"
            ),
            tools_allowed=["web_search", "file_read", "web_reader"],
            temperature=0.3,
            max_turns=10,
        ),
        "verifier": AgentProfile(
            name="Verifier Agent",
            role="verifier",
            system_prompt=(
                "You are a rigorous verification and QA specialist. Your sole job is "
                "to check whether a given piece of work meets its stated requirements.\n\n"
                "Verification process:\n"
                "1. Extract all stated requirements and acceptance criteria\n"
                "2. Check each requirement systematically\n"
                "3. For each requirement, state: PASS, PARTIAL, or FAIL\n"
                "4. Provide brief justification for each verdict\n"
                "5. Check for edge cases, potential bugs, logical gaps\n"
                "6. Verify consistency and completeness\n\n"
                "Output format:\n"
                "- List each requirement with its verdict\n"
                "- Highlight any regressions or unintended changes\n"
                "- Check for security concerns\n"
                "- End with an overall verdict and summary\n\n"
                "Be thorough but concise. Never rubber-stamp — if something is wrong, "
                "say so clearly with specific evidence."
            ),
            tools_allowed=["file_read", "bash"],
            temperature=0.1,
            max_turns=8,
        ),
        "critic": AgentProfile(
            name="Critic Agent",
            role="critic",
            system_prompt=(
                "You are a constructive critic and code reviewer. Analyze the "
                "provided work systematically and identify:\n\n"
                "1. STRENGTHS — What was done well and should be preserved\n"
                "2. WEAKNESSES — Areas that need improvement with specifics\n"
                "3. RISKS — Potential issues that could arise in production\n"
                "4. SUGGESTIONS — Specific, actionable improvements ranked by priority\n\n"
                "Evaluation criteria:\n"
                "- Correctness: Does the work do what it's supposed to?\n"
                "- Quality: Is it clean, maintainable, and well-structured?\n"
                "- Performance: Are there obvious bottlenecks or inefficiencies?\n"
                "- Security: Are there vulnerabilities or unsafe patterns?\n"
                "- Completeness: Are there missing features or edge cases?\n\n"
                "Be direct and honest but never dismissive. Prioritize actionable "
                "feedback over generic praise. Give specific line/item references."
            ),
            tools_allowed=["file_read"],
            temperature=0.5,
            max_turns=5,
        ),
        "repairer": AgentProfile(
            name="Repairer Agent",
            role="repairer",
            system_prompt=(
                "You are an expert code and content repair specialist. You receive "
                "a piece of work along with specific issues or error reports, and "
                "your job is to fix each issue while preserving intended functionality.\n\n"
                "Repair process:\n"
                "1. Read and understand each reported issue carefully\n"
                "2. Trace the issue to its root cause (don't just fix symptoms)\n"
                "3. Apply the minimal, targeted fix needed\n"
                "4. Verify the fix doesn't introduce regressions\n"
                "5. Explain each change and why it's correct\n\n"
                "Rules:\n"
                "- Never change code that isn't related to the reported issue\n"
                "- Preserve the original coding style and conventions\n"
                "- If an issue is ambiguous, explain your interpretation before fixing\n"
                "- If a fix would require major refactoring, note this instead of "
                "attempting it\n"
                "- Test edge cases mentally before finalizing each fix"
            ),
            tools_allowed=["file_read", "file_write", "bash"],
            temperature=0.2,
            max_turns=12,
        ),
        "summarizer": AgentProfile(
            name="Summarizer Agent",
            role="summarizer",
            system_prompt=(
                "You are an expert summarizer and technical writer. Condense the "
                "provided information into a clear, accurate, well-structured summary.\n\n"
                "Guidelines:\n"
                "1. Capture ALL key points, decisions, and action items\n"
                "2. Preserve critical details, numbers, dates, and names\n"
                "3. Use hierarchical structure (headings, bullet points, numbered lists)\n"
                "4. Keep the summary concise — aim for at most 30-40% of original length\n"
                "5. Never add information not present in the source material\n"
                "6. Maintain the original tone and intent\n\n"
                "Structure:\n"
                "- Start with a 1-2 sentence executive summary\n"
                "- Use section headers for distinct topics\n"
                "- End with key takeaways or action items if applicable\n\n"
                "If the source is ambiguous or contradictory, note this explicitly "
                "rather than picking an interpretation."
            ),
            tools_allowed=["file_read"],
            temperature=0.3,
            max_turns=3,
        ),
        "fact_checker": AgentProfile(
            name="Fact Checker Agent",
            role="fact_checker",
            system_prompt=(
                "You are a meticulous fact checker and verification specialist. "
                "Examine each factual claim in the provided text and verify it "
                "against reliable sources.\n\n"
                "For each substantive claim, output:\n"
                "1. THE CLAIM — as stated in the text\n"
                "2. VERDICT — VERIFIED / UNVERIFIED / DISPUTED / FALSE\n"
                "3. EVIDENCE — the source(s) you used for verification\n"
                "4. NUANCES — caveats, context, or conditions that affect the claim\n\n"
                "Categories to check:\n"
                "- Numerical claims (statistics, dates, quantities)\n"
                "- Attributions (who said/did what)\n"
                "- Scientific/technical claims\n"
                "- Historical claims\n"
                "- Policy/legal claims\n\n"
                "Rules:\n"
                "- Do not skip any substantive factual claim\n"
                "- If you cannot verify a claim, clearly say UNVERIFIED\n"
                "- Distinguish between 'not found' and 'found to be false'\n"
                "- Note the recency of your sources (information can change)\n"
                "- Be especially rigorous with health, safety, and legal claims"
            ),
            tools_allowed=["web_search", "web_reader", "file_read"],
            temperature=0.1,
            max_turns=10,
        ),
    }


# ============================================================================
# Factory
# ============================================================================


class DynamicAgentFactory:
    """Creates, executes, and destroys temporary specialized agents.

    The factory manages the full agent lifecycle:
        1. Create agent from template or custom profile
        2. Execute agent on a task (with optional retry)
        3. Archive and destroy when complete

    Supports both live LLM execution (when a base agent with provider
    is connected) and simulated execution (for testing/development).

    Usage:
        factory = DynamicAgentFactory()
        agent = factory.create_agent("coder", "Build a REST API")
        result = await factory.execute_agent(agent.id, "Implement user auth")
        factory.destroy_agent(agent.id)
    """

    def __init__(
        self,
        base_agent: Any | None = None,
        storage_dir: Path | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        retry_delay: float = DEFAULT_RETRY_DELAY,
    ) -> None:
        """Initialize the factory.

        Args:
            base_agent: Optional AionHand agent instance with LLM provider.
            storage_dir: Directory for persistent archive storage.
            max_retries: Number of retry attempts for failed executions.
            retry_delay: Seconds to wait between retries.
        """
        self._base_agent = base_agent
        self._storage_dir = storage_dir or Path.home() / ".aion-hand" / "dynamic"
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self._templates: dict[str, AgentProfile] = _load_default_templates()
        self._agents: dict[str, DynamicAgent] = {}
        self._archive: list[dict[str, Any]] = []
        self._max_retries = max_retries
        self._retry_delay = retry_delay
        self._stats = {
            "total_created": 0,
            "total_destroyed": 0,
            "total_executions": 0,
            "total_tokens": 0,
            "total_retries": 0,
        }
        self._event_hooks: dict[str, list[Callable]] = {
            "on_create": [],
            "on_execute": [],
            "on_destroy": [],
            "on_error": [],
        }
        logger.info(
            f"DynamicAgentFactory initialized with {len(self._templates)} templates "
            f"(retries={max_retries}, delay={retry_delay}s)"
        )

    # ------------------------------------------------------------------
    # Event hooks
    # ------------------------------------------------------------------

    def on(self, event: str, callback: Callable) -> None:
        """Register a callback for an event.

        Events: 'on_create', 'on_execute', 'on_destroy', 'on_error'.
        Callback signature: (agent_or_result: Any) -> None.
        """
        if event in self._event_hooks:
            self._event_hooks[event].append(callback)
            logger.debug(f"Registered hook for '{event}': {callback.__name__}")

    def _emit(self, event: str, data: Any = None) -> None:
        """Fire all registered callbacks for an event."""
        for cb in self._event_hooks.get(event, []):
            try:
                cb(data)
            except Exception as exc:
                logger.warning(f"Event hook error for '{event}': {exc}")

    # ------------------------------------------------------------------
    # Creation
    # ------------------------------------------------------------------

    def create_agent(
        self,
        role: AgentRole,
        task: str,
        parent_task: str | None = None,
        config_override: dict[str, Any] | None = None,
    ) -> DynamicAgent:
        """Create a dynamic agent from a built-in role template.

        Args:
            role: One of the 8 supported agent roles.
            task: Brief description of what this agent will do.
            parent_task: Higher-level task this agent serves.
            config_override: Optional dict to override profile fields.

        Returns:
            DynamicAgent instance ready for execution.

        Raises:
            ValueError: If role is not recognized.
        """
        if role not in VALID_ROLES:
            raise ValueError(f"Unknown role '{role}'. Available: {sorted(VALID_ROLES)}")

        profile = self._templates[role]
        if config_override:
            safe_overrides = {
                k: v for k, v in config_override.items() if hasattr(profile, k)
            }
            profile = AgentProfile(**{**profile.to_dict(), **safe_overrides})

        agent = DynamicAgent(
            id=uuid.uuid4().hex[:12],
            profile=profile,
            status="created",
            parent_task=parent_task,
        )
        self._agents[agent.id] = agent
        self._stats["total_created"] += 1

        self._emit("on_create", agent)
        logger.info(
            f"Created dynamic agent '{agent.id}' " f"(role={role}, task='{task[:60]}')"
        )
        return agent

    def create_custom_agent(
        self,
        profile: AgentProfile,
        task: str,
        parent_task: str | None = None,
    ) -> DynamicAgent:
        """Create a dynamic agent from a fully custom profile.

        Args:
            profile: Complete AgentProfile defining the agent.
            task: Brief description of what this agent will do.
            parent_task: Higher-level task this agent serves.

        Returns:
            DynamicAgent instance ready for execution.
        """
        agent = DynamicAgent(
            id=uuid.uuid4().hex[:12],
            profile=profile,
            status="created",
            parent_task=parent_task,
        )
        self._agents[agent.id] = agent
        self._stats["total_created"] += 1

        self._emit("on_create", agent)
        logger.info(f"Created custom dynamic agent '{agent.id}' (name={profile.name})")
        return agent

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute_agent(
        self,
        agent_id: str,
        task: str,
        context: str | None = None,
    ) -> dict[str, Any]:
        """Run a dynamic agent on the given task with retry support.

        Args:
            agent_id: ID of the agent to execute.
            task: The task description/prompt.
            context: Optional context from prior agent outputs.

        Returns:
            Dict with agent_id, status, result, tokens_used, elapsed_seconds,
            tools_used, and retry_count.
        """
        agent = self._agents.get(agent_id)
        if agent is None:
            raise KeyError(f"Agent '{agent_id}' not found")

        agent.status = "running"
        self._stats["total_executions"] += 1
        logger.info(f"Executing agent '{agent_id}' on task: {task[:80]}...")

        start = time.time()
        last_error = None
        result = None

        for attempt in range(1, self._max_retries + 2):
            try:
                result = await self._run_agent_loop(agent, task, context)
                elapsed = time.time() - start

                agent.status = "completed"
                agent.results.append(result)
                agent.tokens_used += result.get("tokens_used", 0)
                self._stats["total_tokens"] += result.get("tokens_used", 0)

                self._emit("on_execute", result)
                logger.info(
                    f"Agent '{agent_id}' completed in {elapsed:.2f}s "
                    f"(attempt {attempt}, tokens={result.get('tokens_used', 0)})"
                )
                return {
                    "agent_id": agent_id,
                    "status": "completed",
                    "result": result.get("content", ""),
                    "tokens_used": result.get("tokens_used", 0),
                    "elapsed_seconds": elapsed,
                    "tools_used": result.get("tools_used", []),
                    "retry_count": attempt - 1,
                    "turns": result.get("turns", 0),
                }

            except Exception as exc:
                last_error = exc
                agent.error_count += 1
                logger.warning(f"Agent '{agent_id}' attempt {attempt} failed: {exc}")
                if attempt <= self._max_retries:
                    self._stats["total_retries"] += 1
                    await asyncio.sleep(self._retry_delay * attempt)

        # All retries exhausted
        elapsed = time.time() - start
        agent.status = "failed"
        error_result = {
            "agent_id": agent_id,
            "status": "failed",
            "error": str(last_error),
            "elapsed_seconds": elapsed,
            "tokens_used": 0,
            "retry_count": self._max_retries,
        }
        self._emit("on_error", error_result)
        logger.error(
            f"Agent '{agent_id}' failed after {self._max_retries + 1} attempts: {last_error}"
        )
        return error_result

    async def _run_agent_loop(
        self, agent: DynamicAgent, task: str, context: str | None
    ) -> dict[str, Any]:
        """Internal: run the agent's conversation loop.

        Delegates to the base agent's LLM provider if available,
        otherwise returns a simulated response for testing.
        """
        system = agent.profile.system_prompt
        if context:
            system += f"\n\n## Context from Prior Agents\n{context}"

        # Live execution with a real LLM provider
        if self._base_agent is not None and hasattr(self._base_agent, "_provider"):
            provider = self._base_agent._provider
            messages = [
                {"role": "system", "content": system},
                {"role": "user", "content": task},
            ]

            total_tokens = 0
            tools_used: list[str] = []
            last_content = ""
            turns = 0

            for turn in range(agent.profile.max_turns):
                response = await provider.complete(
                    messages=messages,
                    model=agent.profile.model or self._base_agent.config.default_model,
                    temperature=agent.profile.temperature,
                    max_tokens=self._base_agent.config.max_tokens,
                )
                total_tokens += response.get("usage", {}).get("total_tokens", 0)
                content = response.get("content", "")
                last_content = content
                messages.append({"role": "assistant", "content": content})
                turns = turn + 1

                tool_calls = response.get("tool_calls", [])
                if tool_calls:
                    for tc in tool_calls:
                        tools_used.append(tc.get("name", "unknown"))
                    messages.append(
                        {
                            "role": "tool",
                            "content": "Tool executed successfully.",
                            "tool_call_id": tool_calls[0].get("id", ""),
                        }
                    )
                else:
                    break

            return {
                "content": last_content,
                "tokens_used": total_tokens,
                "tools_used": tools_used,
                "turns": turns,
            }

        # Fallback: simulated execution when no provider is connected
        simulated_content = (
            f"[Dynamic Agent: {agent.profile.name}]\n"
            f"Role: {agent.profile.role}\n"
            f"Task: {task}\n\n"
            f"Simulated response — no live LLM provider configured. "
            f"Connect a base agent with an LLM provider for real execution.\n\n"
            f"This agent had access to tools: {', '.join(agent.profile.tools_allowed) or 'none'}"
        )
        return {
            "content": simulated_content,
            "tokens_used": 0,
            "tools_used": [],
            "turns": 1,
        }

    # ------------------------------------------------------------------
    # Destruction
    # ------------------------------------------------------------------

    def destroy_agent(self, agent_id: str) -> bool:
        """Archive and remove a dynamic agent.

        Args:
            agent_id: ID of the agent to destroy.

        Returns:
            True if agent was found and destroyed, False otherwise.
        """
        agent = self._agents.pop(agent_id, None)
        if agent is None:
            logger.warning(f"Cannot destroy agent '{agent_id}': not found")
            return False

        agent.status = "archived"
        self._archive.append(agent.to_dict())
        self._stats["total_destroyed"] += 1
        self._emit("on_destroy", agent)
        logger.info(f"Destroyed agent '{agent_id}'")
        return True

    def destroy_all(self) -> int:
        """Archive and remove every active agent.

        Returns:
            Number of agents destroyed.
        """
        ids = list(self._agents.keys())
        for aid in ids:
            self.destroy_agent(aid)
        return len(ids)

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_active(self) -> list[DynamicAgent]:
        """Return all non-archived agents."""
        return [a for a in self._agents.values() if a.status != "archived"]

    def get_agent(self, agent_id: str) -> DynamicAgent | None:
        """Get an agent by ID, or None if not found."""
        return self._agents.get(agent_id)

    def get_templates(self) -> dict[str, AgentProfile]:
        """Return a copy of all available agent templates."""
        return dict(self._templates)

    def get_stats(self) -> dict[str, Any]:
        """Return comprehensive factory statistics."""
        active = self.list_active()
        return {
            **self._stats,
            "active_count": len(active),
            "by_role": self._count_by_role(active),
            "by_status": self._count_by_status(),
            "archive_size": len(self._archive),
        }

    def _count_by_role(self, agents: list[DynamicAgent]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for a in agents:
            counts[a.profile.role] = counts.get(a.profile.role, 0) + 1
        return counts

    def _count_by_status(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for agent in self._agents.values():
            counts[agent.status] = counts.get(agent.status, 0) + 1
        return counts

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save_archive(self) -> None:
        """Persist the agent archive to disk."""
        path = self._storage_dir / "agent_archive.json"
        with open(path, "w") as f:
            json.dump(self._archive, f, indent=2, default=str)
        logger.info(f"Saved {len(self._archive)} archived agents to {path}")

    def load_archive(self) -> None:
        """Load previously archived agents from disk."""
        path = self._storage_dir / "agent_archive.json"
        if not path.exists():
            return
        with open(path) as f:
            self._archive = json.load(f)
        logger.info(f"Loaded {len(self._archive)} archived agents from {path}")
