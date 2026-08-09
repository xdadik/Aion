#!/usr/bin/env python3
"""
Context Engine for Aion Hand.
==============================

Manages the conversation context window with compression and a 3-tier
prompt architecture.  Provides:

  * :class:`ContextEngine` – abstract base for all compression strategies.
  * :class:`SummaryCompressor` – LLM-based summarisation of older messages.
  * :class:`PruningCompressor` – deterministic pruning without LLM calls.
  * :class:`ThreeTierPromptBuilder` – hierarchical system-prompt construction
    (STABLE / CONTEXT / VOLATILE).
  * :class:`ContextWindowManager` – orchestrates compression + assembly of the
    full payload sent to the LLM.

Design inspired by:
  - Hermes Agent: ``context_compressor.py`` (sliding-window summarisation)
    and ``system_prompt.py`` (3-tier prompt architecture).
  - LangChain:  ``ConversationSummaryMemory`` for the summariser pattern.
  - Anthropic:   Context-window management guidance for Claude.

Typical usage::

    manager = ContextWindowManager(max_context_tokens=128_000)
    manager.add_message("user", "Hello, can you help me?")
    manager.add_message("assistant", "Of course! What do you need?")

    if manager.compress_if_needed(target_tokens=100_000):
        logger.info("Context was compressed to fit the window")

    messages = manager.get_messages()
    stats   = manager.get_context_stats()
"""

from __future__ import annotations

import abc
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger("aion_hand.agent.context_engine")


# ======================================================================
# Constants
# ======================================================================

# ~4 characters per token is a widely-used heuristic for English text.
CHARS_PER_TOKEN: int = 4

# When the context utilisation exceeds this fraction, trigger compression.
DEFAULT_COMPRESSION_THRESHOLD: float = 0.80

# Protect the first N and last N messages from summarisation.
DEFAULT_PROTECT_HEAD: int = 2
DEFAULT_PROTECT_TAIL: int = 4

# Maximum length of a pruned tool-result string.
DEFAULT_PRUNE_MAX_CHARS: int = 500

# Markers injected into compressed conversation history.
COMPRESSION_MARKER_START: str = "[CONTEXT_SUMMARY_START]"
COMPRESSION_MARKER_END: str = "[CONTEXT_SUMMARY_END]"

# Tier ordering in the assembled system prompt.
_TIER_SEPARATOR: str = "\n\n---\n\n"


# ======================================================================
# Abstract Base – ContextEngine
# ======================================================================


class ContextEngine(abc.ABC):
    """Abstract base for context compression strategies.

    Every compressor must implement four operations:

    * ``should_compress`` – decide whether compression is needed.
    * ``compress`` – produce a shorter list of messages.
    * ``estimate_tokens`` – approximate token count for a message list.
    * ``select_context`` – pick the most relevant subset for a query.
    """

    # ---------------------------------------------------------------
    # Public interface
    # ---------------------------------------------------------------

    @abc.abstractmethod
    def should_compress(self, messages: list[dict[str, Any]], max_tokens: int) -> bool:
        """Return *True* if ``messages`` exceed ``max_tokens``."""

    @abc.abstractmethod
    def compress(
        self, messages: list[dict[str, Any]], target_tokens: int
    ) -> list[dict[str, Any]]:
        """Return a compressed copy of *messages* that fits within
        approximately ``target_tokens``."""

    @abc.abstractmethod
    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Estimate the token count for *messages*."""

    def select_context(
        self,
        query: str,
        all_messages: list[dict[str, Any]],
        max_tokens: int,
    ) -> list[dict[str, Any]]:
        """Select the most relevant messages for *query*.

        Default implementation simply returns the tail of *all_messages*
        that fits within ``max_tokens``.  Subclasses may override to
        provide relevance-based selection.
        """
        result: list[dict[str, Any]] = []
        budget = max_tokens
        for msg in reversed(all_messages):
            msg_tokens = self.estimate_tokens([msg])
            if msg_tokens > budget:
                break
            result.append(msg)
            budget -= msg_tokens
        result.reverse()
        return result


# ======================================================================
# SummaryCompressor – LLM-based summarisation
# ======================================================================


class SummaryCompressor(ContextEngine):
    """Compresses conversation history by generating an LLM summary of the
    older messages while protecting the head (system prompts) and tail
    (most recent exchanges).

    Because we are stdlib-only, the actual LLM call is *delegated* via a
    caller-supplied ``summary_fn``.  If no function is provided the
    compressor falls back to a simple truncation heuristic.

    Parameters
    ----------
    protect_head:
        Number of leading messages to keep intact.
    protect_tail:
        Number of trailing messages to keep intact.
    summary_fn:
        Async or sync callable ``(prompt: str) -> str`` that produces a
        summary from the supplied prompt text.
    """

    def __init__(
        self,
        protect_head: int = DEFAULT_PROTECT_HEAD,
        protect_tail: int = DEFAULT_PROTECT_TAIL,
        summary_fn: Callable[[str], str] | None = None,
    ) -> None:
        self.protect_head = protect_head
        self.protect_tail = protect_tail
        self._summary_fn = summary_fn
        self._compression_count: int = 0

    # ---------------------------------------------------------------
    # Token estimation
    # ---------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        """Heuristic: ~4 characters per token."""
        return max(1, len(text) // CHARS_PER_TOKEN)

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        """Sum token estimates for every message in the list."""
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                # Handle multi-part content (e.g. tool results).
                for part in content:
                    if isinstance(part, dict):
                        total += self._estimate_tokens(part.get("text", str(part)))
                    else:
                        total += self._estimate_tokens(str(part))
            else:
                total += self._estimate_tokens(str(content))
            # Account for role + structure overhead (~4 tokens).
            total += 4
        return total

    # ---------------------------------------------------------------
    # Should compress?
    # ---------------------------------------------------------------

    def should_compress(self, messages: list[dict[str, Any]], max_tokens: int) -> bool:
        """Compress when token estimate exceeds ``max_tokens`` *and* there
        is a middle section to summarise (head + tail < total)."""
        if len(messages) <= self.protect_head + self.protect_tail:
            return False
        return self.estimate_tokens(messages) > max_tokens

    # ---------------------------------------------------------------
    # Compression
    # ---------------------------------------------------------------

    def compress(
        self, messages: list[dict[str, Any]], target_tokens: int
    ) -> list[dict[str, Any]]:
        """Replace the middle portion of *messages* with a summary message.

        The head (first ``protect_head`` messages) and tail (last
        ``protect_tail`` messages) are preserved verbatim.
        """
        if len(messages) <= self.protect_head + self.protect_tail:
            return list(messages)

        head = messages[: self.protect_head]
        tail = messages[-self.protect_tail :]
        middle = messages[self.protect_head : -self.protect_tail]

        # Budget available for the summary.
        head_tokens = self.estimate_tokens(head)
        tail_tokens = self.estimate_tokens(tail)
        summary_budget = max(200, target_tokens - head_tokens - tail_tokens)

        summary_text = self._generate_summary(middle, summary_budget)
        self._compression_count += 1

        summary_message: dict[str, Any] = {
            "role": "system",
            "content": f"{COMPRESSION_MARKER_START}\n"
            f"Summary of {len(middle)} earlier messages:\n\n"
            f"{summary_text}\n"
            f"{COMPRESSION_MARKER_END}",
        }

        return head + [summary_message] + tail

    # ---------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------

    def _generate_summary(self, middle: list[dict[str, Any]], budget: int) -> str:
        """Produce a summary string for the *middle* messages.

        If a ``summary_fn`` is available, use it.  Otherwise fall back to
        a deterministic truncation.
        """
        prompt = self._build_summary_prompt(middle)

        if self._summary_fn is not None:
            try:
                raw = self._summary_fn(prompt)
                # Truncate to budget if the LLM returned too much.
                max_chars = budget * CHARS_PER_TOKEN
                if len(raw) > max_chars:
                    raw = raw[:max_chars] + "\n…[truncated]"
                return raw
            except Exception as exc:
                logger.warning("Summary function failed: %s – using truncation", exc)

        return self._truncation_fallback(middle, budget)

    def _build_summary_prompt(self, middle: list[dict[str, Any]]) -> str:
        """Build a prompt asking for a concise conversation summary."""
        parts: list[str] = []
        for msg in middle:
            role = msg.get("role", "unknown")
            content = msg.get("content", "")
            if isinstance(content, list):
                # Flatten multi-part content.
                content = " ".join(
                    p.get("text", str(p)) if isinstance(p, dict) else str(p)
                    for p in content
                )
            # Truncate individual messages to avoid an enormous prompt.
            if len(content) > 2000:
                content = content[:2000] + "…"
            parts.append(f"[{role}]: {content}")

        conversation_text = "\n".join(parts)
        return (
            "Summarise the following conversation history concisely. "
            "Preserve key facts, decisions, file paths, and code snippets. "
            "Omit redundant greetings and pleasantries.\n\n"
            f"{conversation_text}"
        )

    def _truncation_fallback(self, middle: list[dict[str, Any]], budget: int) -> str:
        """When no LLM is available, concatenate abbreviated messages."""
        max_chars = budget * CHARS_PER_TOKEN
        parts: list[str] = []
        used = 0
        for msg in middle:
            role = msg.get("role", "unknown")
            content = str(msg.get("content", ""))
            snippet = content[:200] + "…" if len(content) > 200 else content
            line = f"[{role}]: {snippet}"
            if used + len(line) > max_chars:
                parts.append("…[earlier messages omitted]")
                break
            parts.append(line)
            used += len(line)
        return "\n".join(parts)


# ======================================================================
# PruningCompressor – deterministic pruning (no LLM)
# ======================================================================


class PruningCompressor(ContextEngine):
    """Deterministic compressor that trims large tool outputs without
    calling an LLM.  Useful as a fast first-pass before summarisation,
    or as the sole compressor when latency must be minimised.

    Parameters
    ----------
    prune_tool_results_only:
        When *True*, only trim the ``tool`` role messages (large outputs).
        When *False*, trim any message exceeding ``max_message_chars``.
    max_message_chars:
        Threshold above which a message is a candidate for pruning.
    prune_to_chars:
        Target length for a pruned message's content.
    """

    def __init__(
        self,
        prune_tool_results_only: bool = True,
        max_message_chars: int = 4000,
        prune_to_chars: int = DEFAULT_PRUNE_MAX_CHARS,
    ) -> None:
        self.prune_tool_results_only = prune_tool_results_only
        self.max_message_chars = max_message_chars
        self.prune_to_chars = prune_to_chars
        self._prune_count: int = 0

    # ---------------------------------------------------------------
    # Token estimation (same heuristic)
    # ---------------------------------------------------------------

    def _estimate_tokens(self, text: str) -> int:
        return max(1, len(text) // CHARS_PER_TOKEN)

    def estimate_tokens(self, messages: list[dict[str, Any]]) -> int:
        total = 0
        for msg in messages:
            content = msg.get("content", "")
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        total += self._estimate_tokens(part.get("text", str(part)))
                    else:
                        total += self._estimate_tokens(str(part))
            else:
                total += self._estimate_tokens(str(content))
            total += 4  # role overhead
        return total

    # ---------------------------------------------------------------
    # Should compress?
    # ---------------------------------------------------------------

    def should_compress(self, messages: list[dict[str, Any]], max_tokens: int) -> bool:
        if self.estimate_tokens(messages) <= max_tokens:
            return False
        return any(self._should_prune(msg) for msg in messages)

    # ---------------------------------------------------------------
    # Compression
    # ---------------------------------------------------------------

    def compress(
        self, messages: list[dict[str, Any]], target_tokens: int
    ) -> list[dict[str, Any]]:
        """Prune messages in-place (conceptually) and return a new list."""
        result = [self._prune_message(msg) for msg in messages]

        # If still over budget after pruning, drop oldest messages.
        budget = target_tokens
        pruned: list[dict[str, Any]] = []
        for msg in reversed(result):
            tokens = self.estimate_tokens([msg])
            if tokens > budget:
                continue
            pruned.append(msg)
            budget -= tokens
        pruned.reverse()
        return pruned

    # ---------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------

    def _should_prune(self, msg: dict[str, Any]) -> bool:
        """Decide whether a message is a pruning candidate."""
        role = msg.get("role", "")
        content = msg.get("content", "")

        if self.prune_tool_results_only and role != "tool":
            return False

        text = str(content)
        return len(text) > self.max_message_chars

    def _prune_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Return a copy of *msg* with its content trimmed if needed."""
        if not self._should_prune(msg):
            return msg

        content = msg.get("content", "")
        text = str(content)

        if len(text) <= self.prune_to_chars:
            return msg

        self._prune_count += 1
        head = text[: self.prune_to_chars]
        original_len = len(text)
        truncated = (
            f"{head}\n\n"
            f"[… {original_len - self.prune_to_chars:,} characters omitted "
            f"(original {original_len:,} chars)]"
        )
        return {**msg, "content": truncated}


# ======================================================================
# ThreeTierPromptBuilder – hierarchical system-prompt construction
# ======================================================================


class PromptTier(Enum):
    """Classification of system-prompt sections by volatility.

    * **STABLE** – identity, core instructions; never changes within a
      session.
    * **CONTEXT** – project files, workspace info; changes rarely.
    * **VOLATILE** – memory snapshot, current timestamp; may change every
      turn.
    """

    STABLE = "stable"
    CONTEXT = "context"
    VOLATILE = "volatile"


class ThreeTierPromptBuilder:
    """Constructs a system prompt from three tiers of information.

    The assembled prompt is ordered STABLE → CONTEXT → VOLATILE so the
    LLM sees identity first, workspace context second, and current-state
    data last (closest to the conversation).

    Each tier has an independent token budget that can be queried before
    assembly, letting the caller adjust content proactively.

    Example::

        builder = ThreeTierPromptBuilder()
        stable   = builder.build_stable("Aion", ["code", "search"], "Be concise")
        context  = builder.build_context(["main.py"], {"lang": "python"})
        volatile = builder.build_volatile(memory, profile, ts)
        prompt   = builder.build_system_prompt(stable, context, volatile)
    """

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def build_system_prompt(
        self,
        stable_parts: str,
        context_parts: str,
        volatile_parts: str,
    ) -> str:
        """Assemble the full system prompt from three tier strings.

        Empty tiers are silently omitted.
        """
        sections: list[str] = []

        if stable_parts.strip():
            sections.append(self._wrap_tier(PromptTier.STABLE, stable_parts))
        if context_parts.strip():
            sections.append(self._wrap_tier(PromptTier.CONTEXT, context_parts))
        if volatile_parts.strip():
            sections.append(self._wrap_tier(PromptTier.VOLATILE, volatile_parts))

        return _TIER_SEPARATOR.join(sections)

    def build_stable(
        self,
        agent_name: str = "Aion Hand",
        capabilities: list[str] | None = None,
        guidelines: str = "",
    ) -> str:
        """Build the STABLE tier: identity, capabilities, and behavioural
        guidelines."""
        capabilities = capabilities or []
        parts: list[str] = []

        # Identity
        parts.append(
            f"# Identity\nYou are {agent_name}, an AI agent that assists users "
            f"with software engineering, research, and creative tasks."
        )

        # Capabilities
        if capabilities:
            cap_lines = "\n".join(f"- {c}" for c in capabilities)
            parts.append(f"# Capabilities\n{cap_lines}")

        # Guidelines
        if guidelines:
            parts.append(f"# Guidelines\n{guidelines}")

        return "\n\n".join(parts)

    def build_context(
        self,
        workspace_files: list[str] | None = None,
        project_rules: dict[str, str] | None = None,
    ) -> str:
        """Build the CONTEXT tier: workspace layout and project conventions."""
        workspace_files = workspace_files or []
        project_rules = project_rules or {}
        parts: list[str] = []

        if workspace_files:
            file_lines = "\n".join(f"- {f}" for f in workspace_files)
            parts.append(f"# Workspace Files\n{file_lines}")

        if project_rules:
            rule_lines = "\n".join(f"- **{k}**: {v}" for k, v in project_rules.items())
            parts.append(f"# Project Rules\n{rule_lines}")

        return "\n\n".join(parts)

    def build_volatile(
        self,
        memory_snapshot: str = "",
        user_profile: str = "",
        timestamp: str | None = None,
    ) -> str:
        """Build the VOLATILE tier: current memory state, user context,
        and wall-clock time."""
        if timestamp is None:
            timestamp = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

        parts: list[str] = [f"# Current Time\n{timestamp}"]

        if user_profile.strip():
            parts.append(f"# User Context\n{user_profile}")

        if memory_snapshot.strip():
            parts.append(f"# Memory Snapshot\n{memory_snapshot}")

        return "\n\n".join(parts)

    def estimate_tier_tokens(self, tier_text: str) -> int:
        """Estimate the token count for a single tier string."""
        return max(1, len(tier_text) // CHARS_PER_TOKEN)

    # ---------------------------------------------------------------
    # Internal helpers
    # ---------------------------------------------------------------

    @staticmethod
    def _wrap_tier(tier: PromptTier, content: str) -> str:
        """Wrap a tier's content with a labelled header."""
        return f"<!-- tier:{tier.value} -->\n{content}"


# ======================================================================
# ContextWindowManager – full context orchestration
# ======================================================================


@dataclass
class _MessageRecord:
    """Internal wrapper that preserves metadata alongside the API-facing
    message dict."""

    message: dict[str, Any]
    created_at: float = field(default_factory=time.time)
    token_estimate: int = 0


class ContextWindowManager:
    """Manages the full context payload: system prompt + conversation
    history.

    The manager monitors context utilisation and transparently compresses
    when a configurable threshold is exceeded.  Callers interact through
    a simple ``add_message`` / ``get_messages`` API.

    Parameters
    ----------
    max_context_tokens:
        Hard upper bound on total tokens (system + conversation).
    compression_threshold:
        Fraction of ``max_context_tokens`` at which compression triggers
        (default 0.80 = compress at 80 % utilisation).
    compressor:
        Override the default :class:`SummaryCompressor`.
    """

    def __init__(
        self,
        max_context_tokens: int = 128_000,
        compression_threshold: float = DEFAULT_COMPRESSION_THRESHOLD,
        compressor: ContextEngine | None = None,
    ) -> None:
        self.max_context_tokens = max_context_tokens
        self.compression_threshold = max(0.1, min(0.99, compression_threshold))
        self._compressor = compressor or SummaryCompressor()
        self._system_prompt: str = ""
        self._system_prompt_tokens: int = 0
        self._messages: list[_MessageRecord] = []
        self._total_compressions: int = 0

    # ---------------------------------------------------------------
    # System prompt
    # ---------------------------------------------------------------

    def set_system_prompt(self, prompt: str) -> None:
        """Replace the system prompt and update its token estimate."""
        self._system_prompt = prompt
        self._system_prompt_tokens = self._compressor.estimate_tokens(
            [{"role": "system", "content": prompt}]
        )

    # ---------------------------------------------------------------
    # Message management
    # ---------------------------------------------------------------

    def add_message(self, role: str, content: Any) -> None:
        """Append a message to the conversation history.

        *content* may be a string or a list (multi-part / tool-call).
        """
        msg: dict[str, Any] = {"role": role, "content": content}
        tokens = self._compressor.estimate_tokens([msg])
        record = _MessageRecord(message=msg, token_estimate=tokens)
        self._messages.append(record)

    def get_messages(self) -> list[dict[str, Any]]:
        """Return the assembled message list ready for the LLM API."""
        result: list[dict[str, Any]] = []
        if self._system_prompt:
            result.append({"role": "system", "content": self._system_prompt})
        result.extend(r.message for r in self._messages)
        return result

    def clear(self) -> None:
        """Remove all conversation messages (system prompt is preserved)."""
        self._messages.clear()

    # ---------------------------------------------------------------
    # Compression
    # ---------------------------------------------------------------

    def compress_if_needed(self, target_tokens: int | None = None) -> bool:
        """Check context utilisation and compress if over threshold.

        Returns *True* if compression was performed.
        """
        if target_tokens is None:
            target_tokens = int(self.max_context_tokens * self.compression_threshold)

        current_tokens = self._system_prompt_tokens + sum(
            r.token_estimate for r in self._messages
        )

        if current_tokens <= target_tokens:
            return False

        conversation = [r.message for r in self._messages]
        compressed = self._compressor.compress(
            conversation, target_tokens - self._system_prompt_tokens
        )

        # Rebuild internal list.
        self._messages.clear()
        for msg in compressed:
            tokens = self._compressor.estimate_tokens([msg])
            self._messages.append(_MessageRecord(message=msg, token_estimate=tokens))

        self._total_compressions += 1
        logger.info(
            "Context compressed: %d → %d tokens (%d compressions total)",
            current_tokens,
            self._system_prompt_tokens + sum(r.token_estimate for r in self._messages),
            self._total_compressions,
        )
        return True

    def _select_compressor(self) -> ContextEngine:
        """Return the active compressor (for external inspection)."""
        return self._compressor

    # ---------------------------------------------------------------
    # Configuration
    # ---------------------------------------------------------------

    def set_compression_threshold(self, percent: float) -> None:
        """Set the compression trigger as a fraction (e.g. ``0.75`` for
        75 %)."""
        self.compression_threshold = max(0.1, min(0.99, percent))

    def set_max_context_tokens(self, n: int) -> None:
        """Update the hard context-window ceiling."""
        if n < 1024:
            raise ValueError("max_context_tokens must be >= 1024")
        self.max_context_tokens = n

    # ---------------------------------------------------------------
    # Statistics
    # ---------------------------------------------------------------

    def get_context_stats(self) -> dict[str, Any]:
        """Return a dict with token counts and metadata for each section."""
        msg_tokens = sum(r.token_estimate for r in self._messages)
        total = self._system_prompt_tokens + msg_tokens
        return {
            "system_prompt_tokens": self._system_prompt_tokens,
            "conversation_tokens": msg_tokens,
            "total_tokens": total,
            "max_context_tokens": self.max_context_tokens,
            "utilisation": (
                round(total / self.max_context_tokens, 4)
                if self.max_context_tokens
                else 0.0
            ),
            "message_count": len(self._messages),
            "compression_threshold": self.compression_threshold,
            "total_compressions": self._total_compressions,
            "compressor_type": type(self._compressor).__name__,
        }

    # ---------------------------------------------------------------
    # Convenience factory
    # ---------------------------------------------------------------

    @classmethod
    def with_three_tier(
        cls,
        agent_name: str = "Aion Hand",
        capabilities: list[str] | None = None,
        guidelines: str = "",
        workspace_files: list[str] | None = None,
        project_rules: dict[str, str] | None = None,
        max_context_tokens: int = 128_000,
    ) -> ContextWindowManager:
        """Factory that wires up a :class:`ThreeTierPromptBuilder` and
        pre-populates the system prompt."""
        builder = ThreeTierPromptBuilder()
        stable = builder.build_stable(agent_name, capabilities, guidelines)
        context = builder.build_context(workspace_files, project_rules)

        manager = cls(max_context_tokens=max_context_tokens)
        manager.set_system_prompt(
            builder.build_system_prompt(stable, context, volatile_parts="")
        )
        return manager


# ======================================================================
# Utility helpers
# ======================================================================


def estimate_tokens_for_text(text: str) -> int:
    """Standalone convenience: estimate tokens for a single string."""
    return max(1, len(text) // CHARS_PER_TOKEN)


def estimate_tokens_for_messages(messages: list[dict[str, Any]]) -> int:
    """Standalone convenience: estimate tokens for a message list."""
    engine = SummaryCompressor()
    return engine.estimate_tokens(messages)


def build_three_tier_prompt(
    stable: str,
    context: str = "",
    volatile: str = "",
) -> str:
    """Standalone convenience: build a 3-tier system prompt."""
    builder = ThreeTierPromptBuilder()
    return builder.build_system_prompt(stable, context, volatile)
