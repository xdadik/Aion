#!/usr/bin/env python3
"""
Error Classification System for Aion Hand.
============================================

Provides a structured error taxonomy that maps raw Python exceptions onto a
well-defined set of :class:`FailoverReason` variants, each paired with a
recommended :class:`ErrorRecoveryStrategy`.  A :class:`ClassifiedError`
dataclass captures all the metadata the agent loop needs to make smart
retry / fallback / abort decisions at runtime.

The module also ships with:

  * :class:`ErrorTracker`  – tracks error frequencies and detects patterns
    (e.g. sustained rate-limiting or cascading auth failures) over a sliding
    time window.
  * :class:`ErrorBudget`   – enforces a per-provider error budget so that a
    single flaky upstream does not consume the entire retry allowance.

Design inspired by:
  - Hermes Agent:  ClassifiedError with 25+ FailoverReason variants, recovery
    strategies, and budget tracking
  - NullClaw:      Provider-agnostic error classification
  - OpenClaw:      Structured error handling with automatic failover

Typical usage::

    try:
        result = await provider.complete(messages)
    except Exception as exc:
        classified = classify_error(exc, provider="openai", model="gpt-4o")
        strategy   = get_recovery_strategy(classified.reason)
        if strategy == ErrorRecoveryStrategy.ROTATE_CREDENTIAL:
            await provider.rotate_key()
        elif strategy == ErrorRecoveryStrategy.FALLBACK_MODEL:
            result = await fallback_provider.complete(messages)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import Counter, defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aion_hand.agent.error_classifier")


# ======================================================================
# FailoverReason – the canonical error taxonomy
# ======================================================================


class FailoverReason(str, Enum):
    """Every way an LLM interaction can go wrong, grouped by domain.

    The 26 variants cover authentication, billing, throttling, transient
    infrastructure errors, content-policy violations, tool-execution
    failures, and more.  Each reason is mapped to exactly one
    :class:`ErrorRecoveryStrategy` via :func:`get_recovery_strategy`.
    """

    # -- Authentication & Billing ----------------------------------------
    AUTH = "auth"
    AUTH_PERMANENT = "auth_permanent"
    BILLING = "billing"

    # -- Rate Limiting & Overload -----------------------------------------
    RATE_LIMIT = "rate_limit"
    UPSTREAM_RATE_LIMIT = "upstream_rate_limit"
    OVERLOADED = "overloaded"

    # -- Server-Side Transients -------------------------------------------
    SERVER_ERROR = "server_error"
    TIMEOUT = "timeout"
    SSL_CERT = "ssl_cert"
    CONNECTION_REFUSED = "connection_refused"

    # -- Client-Side / Context Issues -------------------------------------
    CONTEXT_OVERFLOW = "context_overflow"
    IMAGE_TOO_LARGE = "image_too_large"
    MODEL_NOT_FOUND = "model_not_found"

    # -- Content & Formatting ----------------------------------------------
    CONTENT_POLICY = "content_policy"
    FORMAT_ERROR = "format_error"
    MULTIMODAL_UNSUPPORTED = "multimodal_unsupported"

    # -- Input Validation ------------------------------------------------
    INVALID_REQUEST = "invalid_request"
    STREAM_INTERRUPTED = "stream_interrupted"

    # -- Tool / Execution Layer -------------------------------------------
    TOOL_EXECUTION_ERROR = "tool_execution_error"
    TOOL_TIMEOUT = "tool_timeout"
    SANDBOX_VIOLATION = "sandbox_violation"
    MEMORY_ERROR = "memory_error"
    MCP_ERROR = "mcp_error"

    # -- Availability & Network -------------------------------------------
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    NETWORK_ERROR = "network_error"

    # -- Catch-All --------------------------------------------------------
    UNKNOWN = "unknown"


# ======================================================================
# ClassifiedError – the enriched error wrapper
# ======================================================================


@dataclass
class ClassifiedError:
    """A fully classified error with metadata for the agent loop.

    Attributes:
        reason:              The canonical failover reason.
        message:             Human-readable description of the error.
        retryable:           Whether the caller should attempt a retry.
        retry_after_seconds: Minimum back-off before the next attempt (0 if
                             the caller may retry immediately).
        provider:            Provider identifier (e.g. ``"openai"``).
        model:               Model name (e.g. ``"gpt-4o"``).
        context:             Arbitrary extra context (HTTP status, request
                             ID, etc.).
    """

    reason: FailoverReason
    message: str
    retryable: bool = True
    retry_after_seconds: float = 0.0
    provider: Optional[str] = None
    model: Optional[str] = None
    context: Dict[str, Any] = field(default_factory=dict)

    # -- Convenience helpers -----------------------------------------------

    def __str__(self) -> str:
        bits: List[str] = [self.reason.value, self.message]
        if self.provider:
            bits.append(f"provider={self.provider}")
        if self.model:
            bits.append(f"model={self.model}")
        if self.retry_after_seconds > 0:
            bits.append(f"retry_after={self.retry_after_seconds:.1f}s")
        return " | ".join(bits)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dict suitable for JSON logging."""
        return {
            "reason": self.reason.value,
            "message": self.message,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
            "provider": self.provider,
            "model": self.model,
            "context": self.context,
        }


# ======================================================================
# ErrorRecoveryStrategy – what to do about a failure
# ======================================================================


class ErrorRecoveryStrategy(str, Enum):
    """Recommended action after an error is classified.

    The agent loop should consult this enum to decide whether to retry,
    rotate credentials, switch models, compress context, or abort.
    """

    RETRY = "retry"                         # Simple retry (same provider/model)
    BACKOFF = "backoff"                     # Retry with exponential back-off
    ROTATE_CREDENTIAL = "rotate_credential"  # Switch API key / refresh token
    FALLBACK_MODEL = "fallback_model"       # Try a different model
    COMPRESS_CONTEXT = "compress_context"   # Summarise / truncate context
    SHRINK_IMAGE = "shrink_image"           # Downscale images & retry
    ABORT = "abort"                         # Fatal – give up
    SKIP_RETRY = "skip_retry"              # Non-retryable but not fatal


# ======================================================================
# Reason → Strategy mapping
# ======================================================================

_REASON_STRATEGY_MAP: Dict[FailoverReason, ErrorRecoveryStrategy] = {
    # Auth / Billing
    FailoverReason.AUTH:               ErrorRecoveryStrategy.ROTATE_CREDENTIAL,
    FailoverReason.AUTH_PERMANENT:     ErrorRecoveryStrategy.ABORT,
    FailoverReason.BILLING:            ErrorRecoveryStrategy.ABORT,

    # Rate limiting / overload
    FailoverReason.RATE_LIMIT:         ErrorRecoveryStrategy.BACKOFF,
    FailoverReason.UPSTREAM_RATE_LIMIT: ErrorRecoveryStrategy.BACKOFF,
    FailoverReason.OVERLOADED:         ErrorRecoveryStrategy.BACKOFF,

    # Server transients
    FailoverReason.SERVER_ERROR:       ErrorRecoveryStrategy.RETRY,
    FailoverReason.TIMEOUT:            ErrorRecoveryStrategy.BACKOFF,
    FailoverReason.SSL_CERT:           ErrorRecoveryStrategy.BACKOFF,
    FailoverReason.CONNECTION_REFUSED: ErrorRecoveryStrategy.BACKOFF,

    # Client-side
    FailoverReason.CONTEXT_OVERFLOW:   ErrorRecoveryStrategy.COMPRESS_CONTEXT,
    FailoverReason.IMAGE_TOO_LARGE:    ErrorRecoveryStrategy.SHRINK_IMAGE,
    FailoverReason.MODEL_NOT_FOUND:    ErrorRecoveryStrategy.FALLBACK_MODEL,

    # Content / format
    FailoverReason.CONTENT_POLICY:     ErrorRecoveryStrategy.SKIP_RETRY,
    FailoverReason.FORMAT_ERROR:       ErrorRecoveryStrategy.RETRY,
    FailoverReason.MULTIMODAL_UNSUPPORTED: ErrorRecoveryStrategy.FALLBACK_MODEL,

    # Input validation
    FailoverReason.INVALID_REQUEST:   ErrorRecoveryStrategy.SKIP_RETRY,
    FailoverReason.STREAM_INTERRUPTED: ErrorRecoveryStrategy.RETRY,

    # Tool / execution
    FailoverReason.TOOL_EXECUTION_ERROR: ErrorRecoveryStrategy.RETRY,
    FailoverReason.TOOL_TIMEOUT:       ErrorRecoveryStrategy.BACKOFF,
    FailoverReason.SANDBOX_VIOLATION:   ErrorRecoveryStrategy.ABORT,
    FailoverReason.MEMORY_ERROR:       ErrorRecoveryStrategy.ABORT,
    FailoverReason.MCP_ERROR:          ErrorRecoveryStrategy.BACKOFF,

    # Availability / network
    FailoverReason.PROVIDER_UNAVAILABLE: ErrorRecoveryStrategy.FALLBACK_MODEL,
    FailoverReason.NETWORK_ERROR:      ErrorRecoveryStrategy.BACKOFF,

    # Catch-all
    FailoverReason.UNKNOWN:            ErrorRecoveryStrategy.RETRY,
}


def get_recovery_strategy(reason: FailoverReason) -> ErrorRecoveryStrategy:
    """Return the recommended recovery strategy for a given failover reason.

    This is a thin wrapper over the constant map above, kept as a function
    so callers don't need to know the internal data structure.

    Args:
        reason: The classified failover reason.

    Returns:
        The strategy enum value.
    """
    return _REASON_STRATEGY_MAP.get(reason, ErrorRecoveryStrategy.RETRY)


# ======================================================================
# Built-in exception → reason heuristics
# ======================================================================

# Keywords we scan for in exception messages and HTTP response bodies.
_HTTP_STATUS_MAP: Dict[int, FailoverReason] = {
    400: FailoverReason.FORMAT_ERROR,
    401: FailoverReason.AUTH,
    402: FailoverReason.BILLING,
    403: FailoverReason.AUTH_PERMANENT,
    404: FailoverReason.MODEL_NOT_FOUND,
    413: FailoverReason.IMAGE_TOO_LARGE,
    422: FailoverReason.FORMAT_ERROR,
    429: FailoverReason.RATE_LIMIT,
    500: FailoverReason.SERVER_ERROR,
    502: FailoverReason.SERVER_ERROR,
    503: FailoverReason.OVERLOADED,
    504: FailoverReason.TIMEOUT,
}

_REASON_KEYWORD_MAP: List[tuple] = [
    # (keywords tuple, reason, retry_after_hint)
    (
        ("rate_limit", "ratelimit", "rate limit", "too many requests", "request_limit"),
        FailoverReason.RATE_LIMIT,
        1.0,
    ),
    (
        ("quota", "billing", "insufficient_quota", "payment_required", "payment required"),
        FailoverReason.BILLING,
        0.0,
    ),
    (
        ("invalid_api_key", "authentication", "unauthorized", "incorrect api key"),
        FailoverReason.AUTH,
        0.0,
    ),
    (
        ("account deactivated", "account suspended", "disabled", "banned"),
        FailoverReason.AUTH_PERMANENT,
        0.0,
    ),
    (
        ("context_length", "context_length_exceeded", "token limit", "max tokens",
         "too many tokens", "context window"),
        FailoverReason.CONTEXT_OVERFLOW,
        0.0,
    ),
    (
        ("image too large", "image_too_large", "max_image_size"),
        FailoverReason.IMAGE_TOO_LARGE,
        0.0,
    ),
    (
        ("model_not_found", "model not found", "does not exist", "not available for"),
        FailoverReason.MODEL_NOT_FOUND,
        0.0,
    ),
    (
        ("content_filter", "content_policy", "content management", "safety",
         "blocked by policy", "refusal"),
        FailoverReason.CONTENT_POLICY,
        0.0,
    ),
    (
        ("ssl", "certificate", "cert_verify_failed", "sslerror"),
        FailoverReason.SSL_CERT,
        5.0,
    ),
    (
        ("connection refused", "connectionreset", "connection reset"),
        FailoverReason.CONNECTION_REFUSED,
        2.0,
    ),
    (
        ("timeout", "timed out", "deadline exceeded", "read timeout"),
        FailoverReason.TIMEOUT,
        2.0,
    ),
    (
        ("overloaded", "capacity", "service unavailable", "try again later",
         "temporarily unavailable"),
        FailoverReason.OVERLOADED,
        5.0,
    ),
    (
        ("server_error", "internal error", "internal server error", "500"),
        FailoverReason.SERVER_ERROR,
        1.0,
    ),
    (
        ("multimodal", "image input", "vision", "not supported"),
        FailoverReason.MULTIMODAL_UNSUPPORTED,
        0.0,
    ),
    (
        ("invalid_request", "invalid request", "bad request", "invalid parameter",
         "invalid payload", "request validation"),
        FailoverReason.INVALID_REQUEST,
        0.0,
    ),
    (
        ("stream", "streaming", "stream interrupted", "incomplete response",
         "chunked encoding"),
        FailoverReason.STREAM_INTERRUPTED,
        1.0,
    ),
    (
        ("format", "json", "parse", "malformed", "invalid format", "unexpected"),
        FailoverReason.FORMAT_ERROR,
        0.0,
    ),
    (
        ("sandbox", "permission denied", "operation not permitted", "forbidden"),
        FailoverReason.SANDBOX_VIOLATION,
        0.0,
    ),
    (
        ("memory", "out of memory", "oom", "memory allocation"),
        FailoverReason.MEMORY_ERROR,
        0.0,
    ),
    (
        ("mcp", "model context protocol", "mcp_error"),
        FailoverReason.MCP_ERROR,
        2.0,
    ),
    (
        ("network", "dns", "resolve", "no route to host", "unreachable"),
        FailoverReason.NETWORK_ERROR,
        2.0,
    ),
]


def classify_error(
    error: BaseException,
    *,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> ClassifiedError:
    """Classify a raw exception into a :class:`ClassifiedError`.

    The classifier works in three stages:

    1. **HTTP status** – if the exception carries an ``http_status`` attribute
       (common in ``httpx`` / ``aiohttp`` wrappers), map that directly.
    2. **Message keywords** – scan ``str(error)`` for known phrases.
    3. **Exception type** – fall back to type-based heuristics for common
       built-in exceptions (``ConnectionError``, ``TimeoutError``, etc.).

    Args:
        error:    The exception instance to classify.
        provider: Optional provider name for richer context.
        model:    Optional model name for richer context.

    Returns:
        A :class:`ClassifiedError` with reason, retryability, suggested
        back-off, and context metadata.
    """
    error_type = type(error).__name__
    error_msg = str(error).lower()
    context: Dict[str, Any] = {
        "exception_type": error_type,
        "original_message": str(error),
    }

    reason: FailoverReason = FailoverReason.UNKNOWN
    retry_after: float = 0.0
    retryable: bool = True

    # ── Stage 1: HTTP status code ──────────────────────────────────────
    http_status: Optional[int] = getattr(error, "http_status", None)
    if http_status is None:
        http_status = getattr(error, "status_code", None)
    if http_status is not None:
        reason = _HTTP_STATUS_MAP.get(http_status, FailoverReason.UNKNOWN)
        # Extract Retry-After header if present
        retry_after_hdr = getattr(error, "retry_after", None)
        if retry_after_hdr is not None:
            try:
                retry_after = float(retry_after_hdr)
            except (TypeError, ValueError):
                retry_after = 1.0
        context["http_status"] = http_status

        # Special-case: 401 might be permanent if message mentions deactivation
        if reason == FailoverReason.AUTH and any(
            kw in error_msg for kw in ("deactivated", "suspended", "banned", "disabled")
        ):
            reason = FailoverReason.AUTH_PERMANENT

        # Non-retryable statuses
        if http_status in (402, 403, 404):
            retryable = False

    # ── Stage 2: Message keyword scanning ─────────────────────────────
    if reason == FailoverReason.UNKNOWN:
        for keywords, mapped_reason, hint in _REASON_KEYWORD_MAP:
            if any(kw in error_msg for kw in keywords):
                reason = mapped_reason
                retry_after = hint
                break

    # ── Stage 3: Exception-type heuristics ─────────────────────────────
    if reason == FailoverReason.UNKNOWN:
        reason, retry_after = _classify_by_exception_type(error)

    # ── Determine retryability ─────────────────────────────────────────
    if reason in (
        FailoverReason.AUTH_PERMANENT,
        FailoverReason.BILLING,
        FailoverReason.CONTENT_POLICY,
        FailoverReason.SANDBOX_VIOLATION,
        FailoverReason.MEMORY_ERROR,
    ):
        retryable = False

    logger.debug(
        "Classified error: reason=%s retryable=%s retry_after=%.1fs provider=%s",
        reason.value,
        retryable,
        retry_after,
        provider,
    )

    return ClassifiedError(
        reason=reason,
        message=str(error),
        retryable=retryable,
        retry_after_seconds=retry_after,
        provider=provider,
        model=model,
        context=context,
    )


def _classify_by_exception_type(
    error: BaseException,
) -> tuple[FailoverReason, float]:
    """Fall-back classification based purely on exception type.

    Returns a ``(reason, retry_after_hint)`` pair.
    """
    # TimeoutError and subclasses
    if isinstance(error, TimeoutError):
        return FailoverReason.TIMEOUT, 2.0

    # ConnectionError and subclasses (ConnectionRefusedError, etc.)
    if isinstance(error, ConnectionError):
        if isinstance(error, ConnectionRefusedError):
            return FailoverReason.CONNECTION_REFUSED, 2.0
        if isinstance(error, ConnectionResetError):
            return FailoverReason.CONNECTION_REFUSED, 2.0
        if isinstance(error, ConnectionAbortedError):
            return FailoverReason.CONNECTION_REFUSED, 2.0
        return FailoverReason.NETWORK_ERROR, 2.0

    # OSError family
    if isinstance(error, OSError):
        return FailoverReason.NETWORK_ERROR, 2.0

    # JSON / parsing errors
    if isinstance(error, (json.JSONDecodeError, ValueError)):
        return FailoverReason.FORMAT_ERROR, 0.0

    # asyncio.CancelledError – treat as user-initiated abort
    if isinstance(error, asyncio.CancelledError):
        return FailoverReason.UNKNOWN, 0.0

    # KeyError / AttributeError for model-not-found scenarios
    if isinstance(error, (KeyError, AttributeError)):
        return FailoverReason.MODEL_NOT_FOUND, 0.0

    return FailoverReason.UNKNOWN, 0.0


# ======================================================================
# ErrorTracker – sliding-window error frequency monitor
# ======================================================================


@dataclass
class _ErrorEntry:
    """Internal record stored by :class:`ErrorTracker`."""

    reason: FailoverReason
    provider: Optional[str]
    model: Optional[str]
    timestamp: float
    message: str


class ErrorTracker:
    """Tracks errors over a configurable sliding time window.

    The tracker maintains a bounded deque of recent errors and exposes
    methods for querying frequency, detecting sustained issues, and
    producing a human-readable summary.

    Args:
        window_seconds: How far back to keep errors (default 300 s / 5 min).
        max_entries:    Hard cap on stored entries to bound memory.

    Example::

        tracker = ErrorTracker()
        tracker.record(classified_error)
        if tracker.is_rate_limited("openai"):
            logger.warning("OpenAI is rate-limited, consider switching provider")
        print(tracker.get_summary())
    """

    def __init__(
        self,
        window_seconds: float = 300.0,
        max_entries: int = 500,
    ) -> None:
        self._window = window_seconds
        self._max_entries = max_entries
        self._errors: deque[_ErrorEntry] = deque(maxlen=max_entries)
        self._counts: Counter = Counter()
        self._provider_counts: Dict[str, Counter] = defaultdict(Counter)

    # -- Public API -------------------------------------------------------

    def record(self, error: ClassifiedError) -> None:
        """Register a classified error in the tracker.

        Args:
            error: The already-classified error to record.
        """
        now = time.monotonic()
        entry = _ErrorEntry(
            reason=error.reason,
            provider=error.provider,
            model=error.model,
            timestamp=now,
            message=error.message,
        )
        self._errors.append(entry)
        self._counts[error.reason] += 1
        if error.provider:
            self._provider_counts[error.provider][error.reason] += 1

        logger.debug(
            "ErrorTracker: recorded %s from %s",
            error.reason.value,
            error.provider or "unknown",
        )

    def get_error_counts(self) -> Dict[str, int]:
        """Return a dict mapping ``FailoverReason`` values to their total count.

        Only counts within the active window are returned.
        """
        self._expire()
        return {r.value: c for r, c in self._counts.items()}

    def get_recent_errors(self, limit: int = 20) -> List[ClassifiedError]:
        """Return the most recent ``limit`` errors as :class:`ClassifiedError`.

        The list is in newest-first order.
        """
        self._expire()
        recent = list(self._errors)
        recent.reverse()
        result: List[ClassifiedError] = []
        for entry in recent[:limit]:
            result.append(
                ClassifiedError(
                    reason=entry.reason,
                    message=entry.message,
                    provider=entry.provider,
                    model=entry.model,
                    retryable=True,  # not tracked per-entry
                    context={"tracked_at": entry.timestamp},
                )
            )
        return result

    def is_rate_limited(
        self,
        provider: Optional[str] = None,
        threshold: int = 5,
    ) -> bool:
        """Check whether a provider has exceeded the rate-limit error threshold.

        Args:
            provider:  Provider name to check.  If ``None``, aggregates across
                       all providers.
            threshold: Number of rate-limit errors in the window that
                       triggers the flag.

        Returns:
            ``True`` if the provider (or any provider) has exceeded the
            threshold for rate-limit errors.
        """
        self._expire()
        rate_limit_reasons = {
            FailoverReason.RATE_LIMIT,
            FailoverReason.UPSTREAM_RATE_LIMIT,
            FailoverReason.OVERLOADED,
        }
        if provider:
            return (
                sum(
                    count
                    for reason, count in self._provider_counts[provider].items()
                    if reason in rate_limit_reasons
                )
                >= threshold
            )
        return sum(self._counts[r] for r in rate_limit_reasons) >= threshold

    def is_auth_failing(
        self,
        provider: Optional[str] = None,
        threshold: int = 3,
    ) -> bool:
        """Check whether auth errors have exceeded the threshold.

        Useful for detecting when a credential is permanently invalid and
        the system should stop retrying.
        """
        self._expire()
        auth_reasons = {FailoverReason.AUTH, FailoverReason.AUTH_PERMANENT}
        if provider:
            return (
                sum(
                    count
                    for reason, count in self._provider_counts[provider].items()
                    if reason in auth_reasons
                )
                >= threshold
            )
        return sum(self._counts[r] for r in auth_reasons) >= threshold

    def clear(self) -> None:
        """Remove all recorded errors and reset counters."""
        self._errors.clear()
        self._counts.clear()
        self._provider_counts.clear()

    def get_summary(self) -> Dict[str, Any]:
        """Produce a summary dict suitable for logging or dashboards.

        Includes total count, per-reason breakdown, provider breakdown, and
        rate-limit status.
        """
        self._expire()
        return {
            "total_errors": sum(self._counts.values()),
            "window_seconds": self._window,
            "reason_counts": {r.value: c for r, c in self._counts.items()},
            "provider_counts": {
                p: {r.value: c for r, c in counts.items()}
                for p, counts in self._provider_counts.items()
            },
            "rate_limited_providers": [
                p
                for p in self._provider_counts
                if self.is_rate_limited(p)
            ],
            "auth_failing_providers": [
                p
                for p in self._provider_counts
                if self.is_auth_failing(p)
            ],
        }

    # -- Internal ---------------------------------------------------------

    def _expire(self) -> None:
        """Prune entries older than the sliding window and update counters."""
        cutoff = time.monotonic() - self._window
        while self._errors and self._errors[0].timestamp < cutoff:
            expired = self._errors.popleft()
            self._counts[expired.reason] = max(0, self._counts[expired.reason] - 1)
            if expired.provider and expired.provider in self._provider_counts:
                prov_counts = self._provider_counts[expired.provider]
                prov_counts[expired.reason] = max(0, prov_counts[expired.reason] - 1)
                if not prov_counts:
                    del self._provider_counts[expired.provider]


# ======================================================================
# ErrorBudget – per-provider error budget enforcement
# ======================================================================


@dataclass
class _ProviderBudget:
    """Internal budget state for one provider."""

    total: int
    remaining: int
    window_seconds: float
    consumed_timestamps: deque = field(default_factory=deque)


class ErrorBudget:
    """Enforces an error budget per provider.

    Each provider is allowed a configurable number of errors within a
    rolling time window.  When the budget is exhausted, :meth:`check`
    returns ``False`` and the caller should stop sending traffic to that
    provider (e.g. trigger a fallback).

    Args:
        default_budget:   Default errors allowed per window per provider.
        window_seconds:   Rolling window duration in seconds.
        providers:        Optional dict of ``{provider: budget}`` to override
                          the default on a per-provider basis.

    Example::

        budget = ErrorBudget(default_budget=10, window_seconds=60)
        budget.consume("openai")   # → True (9 remaining)
        budget.consume("openai")   # → True (8 remaining)
        # … after 10 errors in 60 seconds:
        budget.check("openai")     # → False
    """

    def __init__(
        self,
        default_budget: int = 10,
        window_seconds: float = 60.0,
        providers: Optional[Dict[str, int]] = None,
    ) -> None:
        self._default_budget = default_budget
        self._window = window_seconds
        self._budgets: Dict[str, _ProviderBudget] = {}
        # Seed per-provider overrides
        if providers:
            for prov, bgt in providers.items():
                self._budgets[prov] = _ProviderBudget(
                    total=bgt,
                    remaining=bgt,
                    window_seconds=window_seconds,
                )

    def _get_or_create(self, provider: str) -> _ProviderBudget:
        """Lazily create a budget entry for a provider."""
        if provider not in self._budgets:
            self._budgets[provider] = _ProviderBudget(
                total=self._default_budget,
                remaining=self._default_budget,
                window_seconds=self._window,
            )
        return self._budgets[provider]

    def check(self, provider: str) -> bool:
        """Return ``True`` if the provider still has error budget remaining.

        Args:
            provider: Provider identifier.

        Returns:
            ``True`` if calls to this provider are allowed, ``False`` if the
            budget has been exhausted.
        """
        budget = self._get_or_create(provider)
        self._expire_budget(budget)
        return budget.remaining > 0

    def consume(self, provider: str) -> bool:
        """Consume one error from the provider's budget.

        Args:
            provider: Provider identifier.

        Returns:
            ``True`` if the error was recorded (budget still has headroom),
            ``False`` if the budget was already exhausted.
        """
        budget = self._get_or_create(provider)
        self._expire_budget(budget)
        if budget.remaining <= 0:
            logger.warning(
                "ErrorBudget: provider %s budget exhausted (%d/%d)",
                provider,
                budget.total - budget.remaining,
                budget.total,
            )
            return False
        budget.remaining -= 1
        budget.consumed_timestamps.append(time.monotonic())
        logger.debug(
            "ErrorBudget: provider %s consumed (%d remaining)",
            provider,
            budget.remaining,
        )
        return True

    def reset(self, provider: str) -> None:
        """Reset the error budget for a specific provider.

        Args:
            provider: Provider identifier.
        """
        if provider in self._budgets:
            budget = self._budgets[provider]
            budget.remaining = budget.total
            budget.consumed_timestamps.clear()
            logger.debug("ErrorBudget: provider %s budget reset", provider)

    def get_remaining(self, provider: str) -> int:
        """Return how many errors the provider may still consume.

        Args:
            provider: Provider identifier.

        Returns:
            Remaining error budget (may be 0 or negative).
        """
        budget = self._get_or_create(provider)
        self._expire_budget(budget)
        return budget.remaining

    def get_summary(self) -> Dict[str, Any]:
        """Return a summary dict of all provider budgets.

        Includes total budget, remaining, and exhausted status per provider.
        """
        summary: Dict[str, Any] = {}
        for provider, budget in self._budgets.items():
            self._expire_budget(budget)
            summary[provider] = {
                "total": budget.total,
                "remaining": budget.remaining,
                "exhausted": budget.remaining <= 0,
                "window_seconds": budget.window_seconds,
            }
        return summary

    # -- Internal ---------------------------------------------------------

    def _expire_budget(self, budget: _ProviderBudget) -> None:
        """Release budget for expired entries."""
        cutoff = time.monotonic() - budget.window_seconds
        while budget.consumed_timestamps and budget.consumed_timestamps[0] < cutoff:
            budget.consumed_timestamps.popleft()
            budget.remaining = min(budget.remaining + 1, budget.total)
