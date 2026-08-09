"""
Mixture-of-Agents (MOA) loop with multi-reference aggregation.

Orchestrates multiple LLM advisor calls in parallel, aggregates their
responses through a designated aggregator model, and scrubs PII from
all inputs and outputs.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# PII Filter
# ---------------------------------------------------------------------------


class PIIFilter:
    """Detects and scrubs personally-identifiable information from text.

    Supported patterns:
    * Email addresses
    * US phone numbers (multiple formats)
    * US Social Security Numbers
    * Credit card numbers (Visa, MasterCard, Amex, Discover)
    * IPv4 addresses (opt-in)
    """

    # Email: standard RFC-5322-ish pattern
    _EMAIL_RE = re.compile(
        r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}",
    )

    # Phone: various US formats
    _PHONE_RE = re.compile(
        r"(?:"
        r"\+?1?[-.\s]?"
        r"\(?[2-9]\d{2}\)?[-.\s]?"
        r"[2-9]\d{2}[-.\s]?"
        r"\d{4}"
        r"|"
        r"\+?1?[-.\s]?[2-9]\d{9}"
        r")"
    )

    # SSN: xxx-xx-xxxx with no all-zero groups
    _SSN_RE = re.compile(r"\b(?!000|666|9\d{2})\d{3}-(?!00)\d{2}-(?!0000)\d{4}\b")

    # Credit cards: 13-19 digits, Luhn-compatible prefix patterns
    _CC_RE = re.compile(
        r"\b("
        r"4\d{12}(?:\d{3})?"  # Visa
        r"|5[1-5]\d{14}"  # MasterCard
        r"|3(?:0[0-5]|[68]\d)\d{11}"  # Amex / Diners Club
        r"|6(?:011|5\d{2})\d{12}"  # Discover
        r"|35(?:2[89]|[3-8]\d)\d{12}"  # JCB
        r")\b"
    )

    # IPv4 addresses (opt-in)
    _IPV4_RE = re.compile(
        r"\b(?:25[0-5]|2[0-4]\d|[01]?\d\d?)"
        r"(?:\.(?:25[0-5]|2[0-4]\d|[01]?\d\d?)){3}\b"
    )

    DEFAULT_REPLACEMENTS = {
        "email": "[EMAIL_REDACTED]",
        "phone": "[PHONE_REDACTED]",
        "ssn": "[SSN_REDACTED]",
        "credit_card": "[CC_REDACTED]",
        "ipv4": "[IP_REDACTED]",
    }

    def __init__(
        self,
        replacement_map: dict[str, str] | None = None,
        include_ipv4: bool = False,
    ) -> None:
        self._replacements = {**self.DEFAULT_REPLACEMENTS}
        if replacement_map:
            self._replacements.update(replacement_map)
        self._patterns: list[re.Pattern[str]] = [
            (self._EMAIL_RE, self._replacements["email"]),
            (self._PHONE_RE, self._replacements["phone"]),
            (self._SSN_RE, self._replacements["ssn"]),
            (self._CC_RE, self._replacements["credit_card"]),
        ]
        if include_ipv4:
            self._patterns.append((self._IPV4_RE, self._replacements["ipv4"]))

    def scrub(self, text: str) -> str:
        """Return *text* with all detected PII replaced."""
        result = text
        for pattern, replacement in self._patterns:
            result = pattern.sub(replacement, result)
        return result

    def detect(self, text: str) -> list[dict[str, Any]]:
        """Return a list of dicts describing each PII match."""
        findings: list[dict[str, Any]] = []
        type_names = ["email", "phone", "ssn", "credit_card"]
        if len(self._patterns) > 4:
            type_names.append("ipv4")
        for idx, (pattern, _) in enumerate(self._patterns):
            ptype = type_names[idx] if idx < len(type_names) else "unknown"
            for m in pattern.finditer(text):
                findings.append(
                    {
                        "type": ptype,
                        "value": m.group(),
                        "start": m.start(),
                        "end": m.end(),
                    }
                )
        return findings


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class MOAConfig:
    """Configuration for a Mixture-of-Agents run."""

    advisors: list[str] = field(default_factory=lambda: ["advisor_a", "advisor_b"])
    aggregator: str = "aggregator"
    max_tokens: int = 4096
    timeout: float = 30.0
    pii_filter: PIIFilter | None = field(default_factory=PIIFilter)


@dataclass
class MOAResult:
    """Result of a single MOA execution."""

    final_response: str
    advisor_responses: dict[str, str]
    tokens: dict[str, int] = field(default_factory=dict)
    elapsed: float = 0.0
    pii_scrubbed: bool = False


# ---------------------------------------------------------------------------
# Advisor / aggregator callable type
# ---------------------------------------------------------------------------

AdvisorFn = Callable[[str, str, int, float], str]


# ---------------------------------------------------------------------------
# MixtureOfAgents
# ---------------------------------------------------------------------------


class MixtureOfAgents:
    """Orchestrates a Mixture-of-Agents loop.

    1.  The user prompt is (optionally) PII-scrubbed.
    2.  All advisors are called in parallel with the prompt.
    3.  Advisor responses are collected and aggregated into a single
        final response by the aggregator.
    4.  The final response is PII-scrubbed before being returned.

    Parameters
    ----------
    advisor_fn:
        A callable ``(model_name, prompt, max_tokens, timeout) -> str``
        that executes a single LLM call.
    aggregator_fn:
        Same signature as *advisor_fn* but used for the final
        aggregation step.  Falls back to *advisor_fn* when None.
    """

    def __init__(
        self,
        advisor_fn: AdvisorFn,
        aggregator_fn: AdvisorFn | None = None,
    ) -> None:
        self._advisor_fn = advisor_fn
        self._aggregator_fn = aggregator_fn or advisor_fn
        self._config: MOAConfig | None = None
        self._stats: dict[str, Any] = {
            "total_executions": 0,
            "total_advisor_calls": 0,
            "total_aggregator_calls": 0,
            "total_pii_detections": 0,
            "errors": [],
        }

    # -- public API --------------------------------------------------------

    def configure(self, config: MOAConfig) -> None:
        """Apply a new configuration."""
        self._config = config
        logger.info(
            "MOA configured with %d advisor(s), aggregator=%s",
            len(config.advisors),
            config.aggregator,
        )

    async def execute(self, prompt: str) -> MOAResult:
        """Run the full MOA loop on *prompt* and return an MOAResult.

        This is an async method because advisors run concurrently.
        """
        if self._config is None:
            raise RuntimeError("Call configure() before execute()")

        cfg = self._config
        t0 = time.monotonic()
        pii_scrubbed = False

        # Step 1 – PII filter on the user prompt
        if cfg.pii_filter is not None:
            detections = cfg.pii_filter.detect(prompt)
            if detections:
                self._stats["total_pii_detections"] += len(detections)
                prompt = cfg.pii_filter.scrub(prompt)
                pii_scrubbed = True
                logger.info("Scrubbed %d PII item(s) from prompt", len(detections))

        # Step 2 – run advisors in parallel
        advisor_responses = await self._run_advisors(
            prompt, cfg.advisors, cfg.max_tokens, cfg.timeout
        )

        # Step 3 – aggregate
        final = await self._aggregate(
            prompt, advisor_responses, cfg.aggregator, cfg.max_tokens, cfg.timeout
        )

        # Step 4 – PII scrub the final response
        if cfg.pii_filter is not None:
            detections = cfg.pii_filter.detect(final)
            if detections:
                self._stats["total_pii_detections"] += len(detections)
                final = cfg.pii_filter.scrub(final)
                pii_scrubbed = True

        elapsed = time.monotonic() - t0
        self._stats["total_executions"] += 1

        return MOAResult(
            final_response=final,
            advisor_responses=advisor_responses,
            tokens=self._estimate_tokens(prompt, advisor_responses, final),
            elapsed=elapsed,
            pii_scrubbed=pii_scrubbed,
        )

    def get_stats(self) -> dict[str, Any]:
        """Return aggregate execution statistics."""
        return dict(self._stats)

    # -- internals ---------------------------------------------------------

    async def _run_advisors(
        self,
        prompt: str,
        advisors: list[str],
        max_tokens: int,
        timeout: float,
    ) -> dict[str, str]:
        """Execute all advisors concurrently."""

        async def _single(name: str) -> tuple[str, str]:
            try:
                loop = asyncio.get_running_loop()
                result = await loop.run_in_executor(
                    None, self._advisor_fn, name, prompt, max_tokens, timeout
                )
                self._stats["total_advisor_calls"] += 1
                return name, result
            except Exception as exc:
                self._stats["errors"].append({"advisor": name, "error": str(exc)})
                logger.error("Advisor %s failed: %s", name, exc)
                return name, f"[ERROR: advisor {name} failed – {exc}]"

        tasks = [_single(name) for name in advisors]
        results = await asyncio.gather(*tasks, return_exceptions=False)
        return dict(results)

    async def _aggregate(
        self,
        prompt: str,
        advisor_responses: dict[str, str],
        aggregator: str,
        max_tokens: int,
        timeout: float,
    ) -> str:
        """Send the collected advisor responses to the aggregator."""
        parts = [f"Advisor {name}:\n{resp}" for name, resp in advisor_responses.items()]
        aggregation_prompt = (
            f"Original prompt: {prompt}\n\n"
            f"Here are responses from {len(parts)} advisor model(s):\n\n"
            f"{'---'.join(parts)}\n\n"
            f"Synthesize the above into a single, comprehensive, and "
            f"accurate final answer. Preserve key details from all "
            f"advisors. Resolve any contradictions by favoring the "
            f"most detailed and well-reasoned response."
        )
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                None,
                self._aggregator_fn,
                aggregator,
                aggregation_prompt,
                max_tokens,
                timeout,
            )
            self._stats["total_aggregator_calls"] += 1
            return result
        except Exception as exc:
            self._stats["errors"].append({"aggregator": aggregator, "error": str(exc)})
            logger.error("Aggregator failed: %s", exc)
            # Fallback: concatenate advisor responses
            return "\n\n".join(
                f"[{name}] {resp}" for name, resp in advisor_responses.items()
            )

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _estimate_tokens(
        prompt: str,
        advisor_responses: dict[str, str],
        final: str,
    ) -> dict[str, int]:
        """Rough token estimate (~4 chars per token)."""

        def _est(text: str) -> int:
            return max(1, len(text) // 4)

        return {
            "prompt": _est(prompt),
            "advisor_total": sum(_est(v) for v in advisor_responses.values()),
            "final": _est(final),
        }

    def __repr__(self) -> str:
        cfg = self._config
        advisors = cfg.advisors if cfg else []
        return (
            f"MixtureOfAgents("
            f"advisors={advisors!r}, "
            f"aggregator={cfg.aggregator if cfg else None!r}"
            f")"
        )
