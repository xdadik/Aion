#!/usr/bin/env python3
"""
Aion Hand - Agent Loop
========================

The core control loop for the Aion Hand AI agent framework.
Inspired by Hermes Agent's architecture with improvements from
CrewAI's orchestration patterns and LangGraph's stateful design.

The agent loop manages the conversation turn cycle:
    receive user message -> think -> select tools -> execute -> respond

Key Design Decisions:
    - Provider-agnostic: Works with any LLM through the provider interface
    - Streaming-first: Supports token-by-token streaming responses
    - Interruptible: Supports cancel-and-redirect (Ctrl+C style from Hermes)
    - Context-aware: Compresses conversation history to fit context windows
    - Observable: Full token tracking, turn counting, and timing metrics
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from collections import Counter, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import (
    Any,
    AsyncIterator,
    Callable,
    Dict,
    List,
    Optional,
    Set,
)

from aion_core.agent.core import AgentConfig, AgentState

logger = logging.getLogger("aion_hand.agent.loop")


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------


class LoopState(Enum):
    """Internal state of a single agent loop execution."""
    IDLE = "idle"
    BUILDING_CONTEXT = "building_context"
    CALLING_LLM = "calling_llm"
    EXECUTING_TOOLS = "executing_tools"
    COMPRESSING_CONTEXT = "compressing_context"
    STREAMING_RESPONSE = "streaming_response"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    ERROR = "error"
    MAX_TURNS_REACHED = "max_turns_reached"


@dataclass
class ToolCallRequest:
    """Represents a single tool call requested by the LLM."""
    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ToolCallResult:
    """Represents the result of executing a tool call."""
    tool_call_id: str
    tool_name: str
    success: bool
    result: Any
    error: Optional[str] = None
    elapsed_seconds: float = 0.0


@dataclass
class TokenUsage:
    """Tracks token consumption across turns."""
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def accumulate(self, other: "TokenUsage") -> None:
        """Add another usage record into this accumulator."""
        self.prompt_tokens += other.prompt_tokens
        self.completion_tokens += other.completion_tokens
        self.total_tokens += other.total_tokens

    def to_dict(self) -> Dict[str, int]:
        return {
            "prompt": self.prompt_tokens,
            "completion": self.completion_tokens,
            "total": self.total_tokens,
        }


@dataclass
class ConversationMessage:
    """A single message in the conversation history."""
    role: str  # "system", "user", "assistant", "tool"
    content: str
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[ToolCallRequest]] = None
    name: Optional[str] = None  # For tool result messages, the tool name
    timestamp: float = field(default_factory=time.time)
    token_count: int = 0  # Approximate token count for context budgeting

    def to_provider_dict(self) -> Dict[str, Any]:
        """Convert to the format expected by LLM providers."""
        msg: Dict[str, Any] = {"role": self.role, "content": self.content}
        if self.tool_call_id is not None:
            msg["tool_call_id"] = self.tool_call_id
        if self.name is not None:
            msg["name"] = self.name
        if self.tool_calls is not None:
            msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments),
                    },
                }
                for tc in self.tool_calls
            ]
        return msg


@dataclass
class LoopResult:
    """The final result of an agent loop execution."""
    content: str
    tools_used: List[str] = field(default_factory=list)
    tokens: Dict[str, int] = field(default_factory=dict)
    turns: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Context Compressor
# ---------------------------------------------------------------------------


class ContextCompressor:
    """
    Hermes-inspired context compression to manage context window usage.

    Strategy:
    1. Keep the system message and the last N messages intact.
    2. Summarize older messages into a single compressed block.
    3. Preserve tool call results that are referenced by recent messages.

    This is a placeholder implementation that can be enhanced with
    LLM-based summarization in a future iteration.
    """

    # Approximate characters per token (conservative estimate)
    CHARS_PER_TOKEN: float = 4.0

    def __init__(self, context_window: int, reserve_tokens: int = 4096):
        """
        Args:
            context_window: Total context window size in tokens.
            reserve_tokens: Tokens to reserve for the response generation.
        """
        self.context_window = context_window
        self.reserve_tokens = reserve_tokens
        self._compression_count = 0

    def estimate_tokens(self, text: str) -> int:
        """Rough token estimate based on character count."""
        return max(1, int(len(text) / self.CHARS_PER_TOKEN))

    def _message_tokens(self, msg: ConversationMessage) -> int:
        """Estimate token count for a single message."""
        total = self.estimate_tokens(msg.content)
        if msg.tool_calls:
            for tc in msg.tool_calls:
                total += self.estimate_tokens(json.dumps(tc.arguments))
        return total

    def _total_tokens(self, messages: List[ConversationMessage]) -> int:
        """Sum of estimated tokens across all messages."""
        return sum(self._message_tokens(m) for m in messages)

    def needs_compression(
        self, messages: List[ConversationMessage], min_messages: int = 6
    ) -> bool:
        """Check whether the message list exceeds the context budget."""
        if len(messages) < min_messages:
            return False
        return self._total_tokens(messages) > (self.context_window - self.reserve_tokens)

    def compress(
        self,
        messages: List[ConversationMessage],
        keep_recent: int = 4,
    ) -> tuple[List[ConversationMessage], bool]:
        """
        Compress older messages, keeping the most recent ones intact.

        Args:
            messages: Full conversation history (excluding system message).
            keep_recent: Number of most recent messages to preserve as-is.

        Returns:
            Tuple of (compressed_messages, was_compressed).
        """
        if not self.needs_compression(messages):
            return messages, False

        self._compression_count += 1
        logger.info(
            f"Compressing context (compression #{self._compression_count}): "
            f"{len(messages)} messages, "
            f"~{self._total_tokens(messages)} tokens"
        )

        # Split into old and recent
        old_messages = messages[:-keep_recent] if len(messages) > keep_recent else []
        recent_messages = messages[-keep_recent:] if len(messages) > keep_recent else messages

        if not old_messages:
            return messages, False

        # Build a compressed summary of old messages
        summary_parts: List[str] = []
        for msg in old_messages:
            if msg.role == "user":
                summary_parts.append(f"[User]: {msg.content[:200]}")
            elif msg.role == "assistant":
                # Include tool call info if present
                if msg.tool_calls:
                    tool_names = [tc.name for tc in msg.tool_calls]
                    summary_parts.append(
                        f"[Assistant]: Called tools: {', '.join(tool_names)}. "
                        f"{msg.content[:150] if msg.content else '(no text response)'}"
                    )
                else:
                    summary_parts.append(f"[Assistant]: {msg.content[:200]}")
            elif msg.role == "tool":
                # Truncate tool results heavily
                result_str = str(msg.result if hasattr(msg, 'result') else msg.content)
                summary_parts.append(
                    f"[Tool result - {msg.name}]: {result_str[:100]}"
                )

        summary_text = (
            "[Previous conversation summary - compressed for context efficiency]\n"
            + "\n".join(summary_parts)
            + "\n[End of compressed history]"
        )

        compressed_msg = ConversationMessage(
            role="user",
            content=summary_text,
            name=None,
        )
        compressed_msg.token_count = self.estimate_tokens(summary_text)

        logger.info(
            f"Context compressed: {len(old_messages)} messages -> "
            f"~{compressed_msg.token_count} tokens"
        )

        return [compressed_msg] + recent_messages, True


# ---------------------------------------------------------------------------
# Feedback Loop
# ---------------------------------------------------------------------------


@dataclass
class ExecutionRecord:
    """A single execution result stored for feedback learning."""
    task: str
    tools_used: List[str] = field(default_factory=list)
    tokens: int = 0
    elapsed: float = 0.0
    success: bool = True
    errors: List[str] = field(default_factory=list)
    timestamp: float = field(default_factory=time.time)


class FeedbackLoop:
    """Maintains a rolling window of execution results for self-improvement.

    Stores the last N execution records and provides methods to:
    - Analyze common failure patterns across past executions.
    - Retrieve relevant past patterns for a given task to inject
      cautionary or success-promoting context into the system prompt.

    The window size is intentionally bounded so memory stays constant
    regardless of how long the agent has been running.
    """

    DEFAULT_WINDOW_SIZE: int = 50

    def __init__(self, window_size: int = DEFAULT_WINDOW_SIZE) -> None:
        self._records: deque[ExecutionRecord] = deque(maxlen=window_size)

    # -- Record management --------------------------------------------------

    def record(
        self,
        task: str,
        tools_used: List[str],
        tokens: int,
        elapsed: float,
        success: bool,
        errors: Optional[List[str]] = None,
    ) -> None:
        """Append an execution record, evicting the oldest if at capacity."""
        self._records.append(
            ExecutionRecord(
                task=task,
                tools_used=tools_used,
                tokens=tokens,
                elapsed=elapsed,
                success=success,
                errors=errors or [],
            )
        )
        logger.debug(
            f"FeedbackLoop recorded: success={success}, "
            f"task='{task[:80]}', tools={tools_used}"
        )

    @property
    def records(self) -> List[ExecutionRecord]:
        """Return a snapshot of all stored records."""
        return list(self._records)

    @property
    def total_records(self) -> int:
        """Number of records currently stored."""
        return len(self._records)

    # -- Analysis -------------------------------------------------------------

    def analyze_patterns(self) -> Dict[str, Any]:
        """Find common failure patterns across stored executions.

        Returns a dictionary with:
        - ``failure_tools``: Counter of tools most often involved in failures.
        - ``common_errors``: Counter of error message prefixes.
        - ``failure_rate``: Overall failure rate as a float 0-1.
        - ``avg_tokens_success`` / ``avg_tokens_failure``: Average token usage.
        - ``avg_time_success`` / ``avg_time_failure``: Average elapsed time.
        """
        if not self._records:
            return {
                "failure_tools": {},
                "common_errors": {},
                "failure_rate": 0.0,
                "avg_tokens_success": 0,
                "avg_tokens_failure": 0,
                "avg_time_success": 0.0,
                "avg_time_failure": 0.0,
            }

        successes = [r for r in self._records if r.success]
        failures = [r for r in self._records if not r.success]

        # Tools involved in failures
        failure_tool_counter: Counter[str] = Counter()
        for rec in failures:
            for tool in rec.tools_used:
                failure_tool_counter[tool] += 1

        # Common error prefixes (first 60 chars)
        error_counter: Counter[str] = Counter()
        for rec in failures:
            for err in rec.errors:
                error_counter[err[:60]] += 1

        def _avg(values: List[float]) -> float:
            return sum(values) / len(values) if values else 0.0

        return {
            "failure_tools": dict(failure_tool_counter.most_common(10)),
            "common_errors": dict(error_counter.most_common(10)),
            "failure_rate": len(failures) / len(self._records),
            "avg_tokens_success": _avg([r.tokens for r in successes]),
            "avg_tokens_failure": _avg([r.tokens for r in failures]),
            "avg_time_success": _avg([r.elapsed for r in successes]),
            "avg_time_failure": _avg([r.elapsed for r in failures]),
        }

    def get_context_for_task(self, task: str) -> str:
        """Return a contextual hint string based on relevant past patterns.

        Compares *task* against stored records using simple keyword
        overlap.  If similar past tasks are found:

        - Past **failures** produce a caution message naming the tools
          that failed and common errors.
        - Past **successes** produce a suggestion message naming the
          tools and approach that worked.

        Returns an empty string when no relevant patterns are found.
        """
        if not self._records:
            return ""

        task_keywords = set(task.lower().split())
        scored: List[tuple[float, ExecutionRecord]] = []

        for rec in self._records:
            rec_keywords = set(rec.task.lower().split())
            overlap = len(task_keywords & rec_keywords)
            if overlap > 0:
                score = overlap / max(len(task_keywords | rec_keywords), 1)
                scored.append((score, rec))

        if not scored:
            return ""

        scored.sort(key=lambda x: x[0], reverse=True)
        top = scored[:5]  # Consider the 5 most relevant records

        failures = [rec for _, rec in top if not rec.success]
        successes = [rec for _, rec in top if rec.success]

        parts: List[str] = []

        if failures:
            failed_tools = Counter()
            error_snippets: List[str] = []
            for rec in failures:
                for t in rec.tools_used:
                    failed_tools[t] += 1
                error_snippets.extend(rec.errors[:2])

            parts.append(
                "[Feedback Loop - Caution] Similar past tasks have encountered issues. "
                f"Tools that failed: {', '.join(t for t, _ in failed_tools.most_common(5))}. "
                f"Common errors: {'; '.join(error_snippets[:3]) or 'N/A'}. "
                "Consider alternative approaches or double-check tool arguments."
            )

        if successes:
            success_tools = Counter()
            for rec in successes:
                for t in rec.tools_used:
                    success_tools[t] += 1

            parts.append(
                "[Feedback Loop - Success Pattern] Similar past tasks succeeded using: "
                f"{', '.join(t for t, _ in success_tools.most_common(5))}. "
                "Consider reusing this approach."
            )

        return "\n".join(parts)

    def get_stats(self) -> Dict[str, Any]:
        """Return a summary dict suitable for inclusion in result metadata."""
        patterns = self.analyze_patterns()
        return {
            "feedback_records": self.total_records,
            "feedback_failure_rate": patterns["failure_rate"],
            "feedback_top_failure_tools": patterns["failure_tools"],
        }


# ---------------------------------------------------------------------------
# Agent Loop
# ---------------------------------------------------------------------------


class AgentLoop:
    """
    The core agent control loop.

    Implements the Hermes Agent-inspired turn cycle:
        receive user message -> think -> select tools -> execute -> respond

    The loop supports:
    - Multi-turn tool use (the LLM can call tools, see results, and call more)
    - Streaming responses via ``run_stream()``
    - Interrupt-and-redirect via ``interrupt()``
    - Context compression when approaching context window limits
    - Full token usage tracking across all turns

    Usage::

        loop = AgentLoop(
            provider=provider,
            memory=memory,
            tools=tools,
            skills=skills,
            config=config,
            personality=personality,
        )
        await loop.initialize()
        result = await loop.run(
            user_message="What is the weather in Tokyo?",
            system_context=personality,
            session_id="session_123",
        )
        print(result["content"])
    """

    # Number of recent messages to protect from compression
    _PROTECTED_RECENT_MESSAGES: int = 4

    def __init__(
        self,
        provider: Any,
        memory: Any,
        tools: Any,
        skills: Any,
        config: AgentConfig,
        personality: str,
    ) -> None:
        """
        Initialize the agent loop.

        Args:
            provider: LLM provider instance (must implement ``chat`` / ``chat_stream``).
            memory: Memory manager instance (may be ``None`` if memory is disabled).
            tools: Tool registry instance (may be ``None`` if tools are disabled).
            skills: Skills engine instance (may be ``None`` if skills are disabled).
            config: Agent configuration dataclass.
            personality: System personality / SOUL.md text.
        """
        self._provider = provider
        self._memory = memory
        self._tools = tools
        self._skills = skills
        self._config = config
        self._personality = personality

        # Conversation state per session
        self._sessions: Dict[str, List[ConversationMessage]] = {}

        # Loop execution state
        self._state: LoopState = LoopState.IDLE
        self._current_task: Optional[asyncio.Task] = None
        self._interrupt_event: asyncio.Event = asyncio.Event()

        # Context compressor
        self._compressor = ContextCompressor(
            context_window=config.context_window,
            reserve_tokens=config.max_tokens,
        )

        # Tool schemas cache (built once, updated on skill/tool changes)
        self._tool_schemas: List[Dict[str, Any]] = []

        # Streaming callback (optional, set externally)
        self._on_stream_token: Optional[Callable[[str], Any]] = None

        # Feedback loop for self-improvement
        self._feedback = FeedbackLoop()

        logger.debug("AgentLoop instance created")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Prepare the loop for execution.

        Builds the initial tool schema list from the tool registry and
        skills engine. This should be called once before the first ``run()``.
        """
        logger.info("Initializing agent loop...")
        self._refresh_tool_schemas()
        self._state = LoopState.IDLE
        logger.info("Agent loop initialized")

    def _refresh_tool_schemas(self) -> None:
        """Rebuild the tool schemas list from registry + skills."""
        schemas: List[Dict[str, Any]] = []

        if self._tools is not None:
            try:
                tool_schemas = self._tools.get_schemas()
                if tool_schemas:
                    schemas.extend(tool_schemas)
            except Exception as exc:
                logger.warning(f"Failed to get tool schemas: {exc}")

        if self._skills is not None:
            try:
                skill_schemas = self._skills.get_schemas()
                if skill_schemas:
                    schemas.extend(skill_schemas)
            except Exception as exc:
                logger.warning(f"Failed to get skill schemas: {exc}")

        self._tool_schemas = schemas
        logger.debug(f"Tool schemas refreshed: {len(schemas)} tools available")

    async def shutdown(self) -> None:
        """Clean up loop resources.

        Interrupts any running execution and clears session data.
        """
        logger.info("Shutting down agent loop...")
        await self.interrupt()
        self._sessions.clear()
        self._tool_schemas.clear()
        self._state = LoopState.IDLE
        logger.info("Agent loop shut down")

    # ------------------------------------------------------------------
    # Main execution
    # ------------------------------------------------------------------

    async def run(
        self,
        user_message: str,
        system_context: str,
        session_id: str,
    ) -> Dict[str, Any]:
        """Run the full agent loop for a single user message.

        This is the primary entry point. It orchestrates the full
        turn cycle: build context -> call LLM -> handle tool calls -> respond.

        Args:
            user_message: The user's input message.
            system_context: Full system prompt (personality + memory + skills context).
            session_id: Session identifier for conversation history tracking.

        Returns:
            A result dictionary with the shape::

                {
                    "content": "response text",
                    "tools_used": ["tool1", "tool2"],
                    "tokens": {"prompt": N, "completion": N, "total": N},
                    "turns": N,
                    "metadata": {
                        "elapsed_seconds": N,
                        "compressed": bool,
                        "session_id": str,
                    }
                }
        """
        start_time = time.monotonic()
        self._interrupt_event.clear()

        # Session bookkeeping
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        history: List[ConversationMessage] = self._sessions[session_id]

        # Tracking accumulators
        usage = TokenUsage()
        tools_used: Set[str] = set()
        turn = 0
        compressed = False
        final_content = ""
        max_turns = self._config.max_turns

        # ---- Check feedback loop for relevant past patterns ----
        feedback_hint = self._feedback.get_context_for_task(user_message)
        effective_system_context = system_context
        if feedback_hint:
            effective_system_context = system_context + "\n\n" + feedback_hint
            logger.info("Injected feedback loop context into system prompt")

        # Append user message to history
        user_msg = ConversationMessage(role="user", content=user_message)
        user_msg.token_count = self._compressor.estimate_tokens(user_message)
        history.append(user_msg)

        try:
            while turn < max_turns:
                turn += 1
                logger.debug(f"--- Turn {turn}/{max_turns} ---")

                # ---- Check for interrupt ----
                if self._interrupt_event.is_set():
                    self._state = LoopState.INTERRUPTED
                    logger.info("Loop interrupted by user")
                    final_content = "\n\n[Execution interrupted by user]"
                    break

                # ---- Build context (with compression if needed) ----
                self._state = LoopState.BUILDING_CONTEXT
                system_msg = ConversationMessage(role="system", content=effective_system_context)
                system_msg.token_count = self._compressor.estimate_tokens(system_context)

                # Compress history if approaching context window
                working_history, did_compress = self._compressor.compress(
                    history, keep_recent=self._PROTECTED_RECENT_MESSAGES
                )
                if did_compress:
                    compressed = True

                messages = [system_msg] + working_history

                # ---- Call the LLM ----
                self._state = LoopState.CALLING_LLM
                provider_messages = [m.to_provider_dict() for m in messages]

                try:
                    if self._config.streaming_enabled:
                        response_content, response_tool_calls, turn_usage = (
                            await self._call_provider_streaming(provider_messages)
                        )
                    else:
                        response_content, response_tool_calls, turn_usage = (
                            await self._call_provider(provider_messages)
                        )
                except Exception as exc:
                    logger.error(f"Provider call failed on turn {turn}: {exc}")
                    self._state = LoopState.ERROR
                    final_content = f"Sorry, I encountered an error communicating with the language model: {exc}"
                    break

                usage.accumulate(turn_usage)

                # ---- Store assistant message in history ----
                assistant_msg = ConversationMessage(
                    role="assistant",
                    content=response_content or "",
                    tool_calls=response_tool_calls if response_tool_calls else None,
                )
                assistant_msg.token_count = self._compressor.estimate_tokens(
                    response_content or ""
                )
                history.append(assistant_msg)

                # ---- Check for tool calls ----
                if not response_tool_calls:
                    # No tool calls -> this is the final response
                    final_content = response_content or ""
                    self._state = LoopState.COMPLETED
                    break

                # ---- Execute tools ----
                self._state = LoopState.EXECUTING_TOOLS
                logger.info(
                    f"Turn {turn}: Processing {len(response_tool_calls)} tool call(s)"
                )

                tool_results = await self._process_tool_calls(response_tool_calls)

                for tr in tool_results:
                    tools_used.add(tr.tool_name)

                    # Build tool result message
                    result_content = json.dumps(tr.result) if tr.success else json.dumps({
                        "error": tr.error or "Unknown tool error"
                    })

                    tool_msg = ConversationMessage(
                        role="tool",
                        content=result_content,
                        tool_call_id=tr.tool_call_id,
                        name=tr.tool_name,
                    )
                    tool_msg.token_count = self._compressor.estimate_tokens(result_content)
                    history.append(tool_msg)

                    logger.debug(
                        f"  Tool '{tr.tool_name}' -> "
                        f"{'OK' if tr.success else 'FAIL'} "
                        f"({tr.elapsed_seconds:.2f}s)"
                    )

                # Loop back to give the LLM the tool results

            else:
                # Exhausted max turns
                self._state = LoopState.MAX_TURNS_REACHED
                logger.warning(f"Max turns ({max_turns}) reached without final response")
                final_content = (
                    final_content
                    or "I was unable to complete the task within the maximum number of turns. "
                    "You may want to break this into smaller requests."
                )

        except asyncio.CancelledError:
            self._state = LoopState.INTERRUPTED
            logger.info("Loop cancelled")
            final_content = final_content or "\n\n[Execution was cancelled]"
        except Exception as exc:
            self._state = LoopState.ERROR
            logger.error(f"Unexpected loop error: {exc}", exc_info=True)
            final_content = f"An unexpected error occurred: {exc}"

        elapsed = time.monotonic() - start_time

        # Persist updated history back to session
        self._sessions[session_id] = history

        # Determine run success and collect any errors
        is_success = self._state in (LoopState.COMPLETED,)
        run_errors: List[str] = []
        if self._state == LoopState.ERROR:
            run_errors.append(final_content)
        if self._state == LoopState.MAX_TURNS_REACHED:
            run_errors.append("Max turns reached without final response")

        # Record outcome to feedback loop
        self._feedback.record(
            task=user_message,
            tools_used=sorted(tools_used),
            tokens=usage.total_tokens,
            elapsed=elapsed,
            success=is_success,
            errors=run_errors,
        )

        result: Dict[str, Any] = {
            "content": final_content,
            "tools_used": sorted(tools_used),
            "tokens": usage.to_dict(),
            "turns": turn,
            "metadata": {
                "elapsed_seconds": round(elapsed, 3),
                "compressed": compressed,
                "session_id": session_id,
                "final_state": self._state.value,
                "feedback": self._feedback.get_stats(),
            },
        }

        logger.info(
            f"Loop completed: {turn} turn(s), "
            f"{usage.total_tokens} tokens, "
            f"{len(tools_used)} tool(s), "
            f"{elapsed:.2f}s"
        )

        self._state = LoopState.IDLE
        return result

    # ------------------------------------------------------------------
    # Streaming execution
    # ------------------------------------------------------------------

    async def run_stream(
        self,
        user_message: str,
        system_context: str,
        session_id: str,
    ) -> AsyncIterator[Dict[str, Any]]:
        """Run the agent loop with streaming output.

        Yields dictionaries with a ``type`` key:
        - ``"token"``: A text chunk of the response.
        - ``"tool_call"``: A tool call initiation notice.
        - ``"tool_result"``: A tool execution result.
        - ``"done"``: Final summary (same shape as ``run()`` return value).

        This allows the caller to stream tokens to the user in real time
        while the loop processes tool calls in the background.
        """
        start_time = time.monotonic()
        self._interrupt_event.clear()

        if session_id not in self._sessions:
            self._sessions[session_id] = []
        history: List[ConversationMessage] = self._sessions[session_id]

        usage = TokenUsage()
        tools_used: Set[str] = set()
        turn = 0
        compressed = False
        collected_content = ""
        max_turns = self._config.max_turns

        user_msg = ConversationMessage(role="user", content=user_message)
        user_msg.token_count = self._compressor.estimate_tokens(user_message)
        history.append(user_msg)

        try:
            while turn < max_turns:
                turn += 1

                if self._interrupt_event.is_set():
                    yield {"type": "token", "content": "\n\n[Interrupted]"}
                    break

                # Build context
                system_msg = ConversationMessage(role="system", content=system_context)
                working_history, did_compress = self._compressor.compress(
                    history, keep_recent=self._PROTECTED_RECENT_MESSAGES
                )
                if did_compress:
                    compressed = True
                messages = [system_msg] + working_history
                provider_messages = [m.to_provider_dict() for m in messages]

                # Call provider with streaming
                response_content = ""
                response_tool_calls: List[ToolCallRequest] = []
                turn_usage = TokenUsage()

                try:
                    async for chunk in self._provider.chat_stream(
                        messages=provider_messages,
                        tools=self._tool_schemas or None,
                        max_tokens=self._config.max_tokens,
                        temperature=self._config.temperature,
                    ):
                        chunk_type = chunk.get("type", "")

                        if chunk_type == "token":
                            token_text = chunk.get("content", "")
                            response_content += token_text
                            collected_content = response_content
                            yield {"type": "token", "content": token_text}

                        elif chunk_type == "tool_call":
                            tc = ToolCallRequest(
                                id=chunk["id"],
                                name=chunk["name"],
                                arguments=chunk.get("arguments", {}),
                            )
                            response_tool_calls.append(tc)
                            yield {
                                "type": "tool_call",
                                "id": tc.id,
                                "name": tc.name,
                                "arguments": tc.arguments,
                            }

                        elif chunk_type == "usage":
                            turn_usage = TokenUsage(
                                prompt_tokens=chunk.get("prompt_tokens", 0),
                                completion_tokens=chunk.get("completion_tokens", 0),
                                total_tokens=chunk.get("total_tokens", 0),
                            )

                except Exception as exc:
                    logger.error(f"Streaming provider call failed: {exc}")
                    yield {"type": "token", "content": f"\nError: {exc}"}
                    break

                usage.accumulate(turn_usage)

                # Store assistant message
                assistant_msg = ConversationMessage(
                    role="assistant",
                    content=response_content,
                    tool_calls=response_tool_calls if response_tool_calls else None,
                )
                assistant_msg.token_count = self._compressor.estimate_tokens(response_content)
                history.append(assistant_msg)

                if not response_tool_calls:
                    break

                # Execute tools
                tool_results = await self._process_tool_calls(response_tool_calls)
                for tr in tool_results:
                    tools_used.add(tr.tool_name)
                    result_content = json.dumps(tr.result) if tr.success else json.dumps({
                        "error": tr.error or "Unknown tool error"
                    })

                    tool_msg = ConversationMessage(
                        role="tool",
                        content=result_content,
                        tool_call_id=tr.tool_call_id,
                        name=tr.tool_name,
                    )
                    tool_msg.token_count = self._compressor.estimate_tokens(result_content)
                    history.append(tool_msg)

                    yield {
                        "type": "tool_result",
                        "tool_call_id": tr.tool_call_id,
                        "name": tr.tool_name,
                        "success": tr.success,
                        "result": tr.result if tr.success else tr.error,
                    }

        except asyncio.CancelledError:
            yield {"type": "token", "content": "\n\n[Cancelled]"}
        except Exception as exc:
            logger.error(f"Streaming loop error: {exc}", exc_info=True)
            yield {"type": "token", "content": f"\nError: {exc}"}

        elapsed = time.monotonic() - start_time
        self._sessions[session_id] = history

        # Record streaming run outcome to feedback loop
        stream_success = True  # No exception means at least partial success
        self._feedback.record(
            task=user_message,
            tools_used=sorted(tools_used),
            tokens=usage.total_tokens,
            elapsed=elapsed,
            success=stream_success,
        )

        yield {
            "type": "done",
            "content": collected_content,
            "tools_used": sorted(tools_used),
            "tokens": usage.to_dict(),
            "turns": turn,
            "metadata": {
                "elapsed_seconds": round(elapsed, 3),
                "compressed": compressed,
                "session_id": session_id,
                "feedback": self._feedback.get_stats(),
            },
        }

    # ------------------------------------------------------------------
    # Provider communication
    # ------------------------------------------------------------------

    async def _call_provider(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[Optional[str], Optional[List[ToolCallRequest]], TokenUsage]:
        """Non-streaming provider call.

        Returns:
            Tuple of (content, tool_calls, token_usage).
        """
        response = await self._provider.chat(
            messages=messages,
            tools=self._tool_schemas or None,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
        )

        content = response.get("content")
        raw_tool_calls = response.get("tool_calls")
        usage_raw = response.get("usage", {})

        tool_calls: Optional[List[ToolCallRequest]] = None
        if raw_tool_calls:
            tool_calls = []
            for tc in raw_tool_calls:
                fn = tc.get("function", {})
                args_str = fn.get("arguments", "{}")
                try:
                    args = json.loads(args_str) if isinstance(args_str, str) else args_str
                except json.JSONDecodeError:
                    logger.warning(f"Failed to parse tool arguments: {args_str}")
                    args = {}
                tool_calls.append(
                    ToolCallRequest(
                        id=tc["id"],
                        name=fn["name"],
                        arguments=args,
                    )
                )

        usage = TokenUsage(
            prompt_tokens=usage_raw.get("prompt_tokens", 0),
            completion_tokens=usage_raw.get("completion_tokens", 0),
            total_tokens=usage_raw.get("total_tokens", 0),
        )

        return content, tool_calls, usage

    async def _call_provider_streaming(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[Optional[str], Optional[List[ToolCallRequest]], TokenUsage]:
        """Streaming provider call that collects the full response.

        Streams tokens through ``_on_stream_token`` callback if set,
        then returns the complete assembled response.

        Returns:
            Tuple of (content, tool_calls, token_usage).
        """
        content_parts: List[str] = []
        tool_calls_map: Dict[str, Dict[str, Any]] = {}
        usage = TokenUsage()

        async for chunk in self._provider.chat_stream(
            messages=messages,
            tools=self._tool_schemas or None,
            max_tokens=self._config.max_tokens,
            temperature=self._config.temperature,
        ):
            chunk_type = chunk.get("type", "")

            if chunk_type == "token":
                token_text = chunk.get("content", "")
                content_parts.append(token_text)
                if self._on_stream_token:
                    try:
                        self._on_stream_token(token_text)
                    except Exception:
                        pass  # Don't let callback errors break the loop

            elif chunk_type == "tool_call":
                tc_id = chunk.get("id", "")
                if tc_id not in tool_calls_map:
                    tool_calls_map[tc_id] = {
                        "id": tc_id,
                        "name": chunk.get("name", ""),
                        "arguments": chunk.get("arguments", {}),
                    }
                else:
                    # Merge incremental arguments
                    existing_args = tool_calls_map[tc_id]["arguments"]
                    new_args = chunk.get("arguments", {})
                    if isinstance(existing_args, str) and isinstance(new_args, str):
                        tool_calls_map[tc_id]["arguments"] = existing_args + new_args
                    elif isinstance(existing_args, dict) and isinstance(new_args, dict):
                        existing_args.update(new_args)

            elif chunk_type == "usage":
                usage = TokenUsage(
                    prompt_tokens=chunk.get("prompt_tokens", 0),
                    completion_tokens=chunk.get("completion_tokens", 0),
                    total_tokens=chunk.get("total_tokens", 0),
                )

        full_content = "".join(content_parts) if content_parts else None

        parsed_tool_calls: Optional[List[ToolCallRequest]] = None
        if tool_calls_map:
            parsed_tool_calls = []
            for tc_data in tool_calls_map.values():
                args = tc_data["arguments"]
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except json.JSONDecodeError:
                        args = {}
                parsed_tool_calls.append(
                    ToolCallRequest(
                        id=tc_data["id"],
                        name=tc_data["name"],
                        arguments=args,
                    )
                )

        return full_content, parsed_tool_calls, usage

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    async def _process_tool_calls(
        self, tool_calls: List[ToolCallRequest]
    ) -> List[ToolCallResult]:
        """Execute a batch of tool calls, potentially in parallel.

        Each tool call is dispatched to the tool registry. Errors are
        caught per-tool so that one failure does not block others.

        Args:
            tool_calls: List of tool call requests from the LLM.

        Returns:
            List of tool call results in the same order.
        """
        results: List[ToolCallResult] = []

        # Execute tool calls concurrently (Hermes-inspired parallel execution)
        tasks = [
            self._execute_single_tool(tc) for tc in tool_calls
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Convert exceptions to error results
        final_results: List[ToolCallResult] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                final_results.append(
                    ToolCallResult(
                        tool_call_id=tool_calls[i].id,
                        tool_name=tool_calls[i].name,
                        success=False,
                        result=None,
                        error=str(result),
                    )
                )
            else:
                final_results.append(result)

        return final_results

    async def _execute_single_tool(self, tool_call: ToolCallRequest) -> ToolCallResult:
        """Execute a single tool call and return its result.

        Args:
            tool_call: The tool call to execute.

        Returns:
            A ``ToolCallResult`` with success/failure information.
        """
        start = time.monotonic()
        tool_name = tool_call.name
        arguments = tool_call.arguments

        logger.debug(f"Executing tool: {tool_name}({json.dumps(arguments)[:200]})")

        try:
            if self._tools is not None:
                # Try the tool registry first
                result = await self._tools.execute(tool_name, **arguments)
                elapsed = time.monotonic() - start
                return ToolCallResult(
                    tool_call_id=tool_call.id,
                    tool_name=tool_name,
                    success=True,
                    result=result,
                    elapsed_seconds=round(elapsed, 4),
                )

            # No tool registry available
            elapsed = time.monotonic() - start
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                result=None,
                error="Tool registry is not available",
                elapsed_seconds=round(elapsed, 4),
            )

        except Exception as exc:
            elapsed = time.monotonic() - start
            logger.error(f"Tool '{tool_name}' execution failed: {exc}")
            return ToolCallResult(
                tool_call_id=tool_call.id,
                tool_name=tool_name,
                success=False,
                result=None,
                error=str(exc),
                elapsed_seconds=round(elapsed, 4),
            )

    # ------------------------------------------------------------------
    # Interrupt handling (Hermes Ctrl+C style)
    # ------------------------------------------------------------------

    async def interrupt(self) -> None:
        """Signal the loop to interrupt the current execution.

        This is the Hermes Agent-inspired cancel-and-redirect mechanism.
        When called, the next iteration of the loop will detect the
        interrupt flag and exit gracefully.

        For immediate cancellation of a running ``run()`` call, the
        caller should also cancel the corresponding ``asyncio.Task``.
        """
        logger.info("Interrupt signal received")
        self._interrupt_event.set()

        # If there is a tracked current task, cancel it
        if self._current_task is not None and not self._current_task.done():
            self._current_task.cancel()
            logger.debug("Current loop task cancelled")

    @property
    def is_interrupted(self) -> bool:
        """Check whether the loop has been interrupted."""
        return self._interrupt_event.is_set()

    @property
    def state(self) -> LoopState:
        """Current loop state."""
        return self._state

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    def get_session_history(
        self, session_id: str
    ) -> List[ConversationMessage]:
        """Retrieve the conversation history for a session.

        Args:
            session_id: The session identifier.

        Returns:
            List of conversation messages (empty list if session unknown).
        """
        return list(self._sessions.get(session_id, []))

    def clear_session(self, session_id: str) -> bool:
        """Clear conversation history for a session.

        Args:
            session_id: The session identifier.

        Returns:
            ``True`` if the session existed and was cleared, ``False`` otherwise.
        """
        if session_id in self._sessions:
            del self._sessions[session_id]
            logger.info(f"Session '{session_id}' cleared")
            return True
        return False

    def list_sessions(self) -> List[str]:
        """List all active session IDs."""
        return list(self._sessions.keys())

    # ------------------------------------------------------------------
    # Context management helpers
    # ------------------------------------------------------------------

    async def _compress_context(
        self, messages: List[ConversationMessage]
    ) -> List[ConversationMessage]:
        """Public-facing context compression (wraps ``ContextCompressor``).

        This method exists as an explicit API for callers that need to
        compress a message list independently of the loop.

        Args:
            messages: Conversation messages to compress.

        Returns:
            Potentially compressed message list.
        """
        compressed, _ = self._compressor.compress(
            messages, keep_recent=self._PROTECTED_RECENT_MESSAGES
        )
        return compressed

    def set_stream_callback(
        self, callback: Optional[Callable[[str], Any]]
    ) -> None:
        """Set a callback invoked for each streaming token.

        Args:
            callback: A callable that accepts a single string argument (the token).
                      Pass ``None`` to remove the callback.
        """
        self._on_stream_token = callback

    def estimate_session_tokens(self, session_id: str) -> int:
        """Estimate total tokens in a session's history.

        Args:
            session_id: The session to measure.

        Returns:
            Estimated token count.
        """
        messages = self._sessions.get(session_id, [])
        return self._compressor._total_tokens(messages)
