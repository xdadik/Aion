"""Cost tracking, budget management, and optimization suggestions.

The :class:`CostOptimizer` works alongside :class:`ModelRouter` to record
actual token usage, enforce spending limits, and surface opportunities to
cut costs.  State can be persisted to / loaded from a JSON file.
"""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from .router import ModelProfile, ModelRouter

logger = logging.getLogger(__name__)


@dataclass
class UsageRecord:
    """Single usage entry."""

    model: str
    provider: str
    tier: str
    tokens_input: int
    tokens_output: int
    cost: float
    timestamp: float = field(default_factory=time.time)


class CostOptimizer:
    """Track spending and suggest cost-reduction strategies.

    Parameters
    ----------
    router : ModelRouter
        The router whose model profiles provide pricing data.
    budget_limit : float, optional
        Soft cap in USD.  The optimizer will still record usage past
        this limit but :meth:`get_remaining_budget` will return 0.
    persist_path : str, optional
        File path for JSON persistence.  ``None`` disables persistence.
    """

    def __init__(
        self,
        router: ModelRouter,
        budget_limit: float | None = None,
        persist_path: str | None = None,
    ) -> None:
        self._router = router
        self._budget_limit = budget_limit
        self._persist_path = persist_path
        self._records: list[UsageRecord] = []
        self._total_spent: float = 0.0

        # Load persisted state if available
        if persist_path and os.path.exists(persist_path):
            self._load(persist_path)

    # ── public API ─────────────────────────────────────────────────
    def track_usage(
        self,
        model: str,
        tokens_input: int,
        tokens_output: int,
    ) -> float:
        """Record actual usage and return the computed cost (USD)."""
        profile = self._find_profile(model)
        cost = profile.cost_per_1k_input * (
            tokens_input / 1000
        ) + profile.cost_per_1k_output * (tokens_output / 1000)
        record = UsageRecord(
            model=model,
            provider=profile.provider,
            tier=profile.tier,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            cost=cost,
        )
        self._records.append(record)
        self._total_spent += cost
        logger.debug(
            "Tracked %s: %d in / %d out → $%.4f",
            model,
            tokens_input,
            tokens_output,
            cost,
        )
        self._auto_persist()
        return cost

    def estimate_cost(self, task: str, context: str | None = None) -> float:
        """Pre-execution cost estimate based on the router's decision."""
        decision = self._router.route(task, context)
        return decision.estimated_cost

    def get_remaining_budget(self) -> float:
        """Return remaining budget or ``float('inf')`` if no limit set."""
        if self._budget_limit is None:
            return float("inf")
        return max(0.0, self._budget_limit - self._total_spent)

    def get_usage_report(self, period: str | None = None) -> dict[str, Any]:
        """Spending breakdown.

        Parameters
        ----------
        period : str, optional
            One of ``"1h"``, ``"24h"``, ``"7d"``, ``"30d"``, or
            ``None`` for all-time.
        """
        cutoff = self._period_cutoff(period)
        filtered = [r for r in self._records if r.timestamp >= cutoff]

        total = sum(r.cost for r in filtered)
        total_in = sum(r.tokens_input for r in filtered)
        total_out = sum(r.tokens_output for r in filtered)

        by_model: dict[str, Any] = {}
        by_tier: dict[str, Any] = {}

        for r in filtered:
            # By model
            if r.model not in by_model:
                by_model[r.model] = {
                    "provider": r.provider,
                    "tier": r.tier,
                    "calls": 0,
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "cost": 0.0,
                }
            bm = by_model[r.model]
            bm["calls"] += 1
            bm["tokens_input"] += r.tokens_input
            bm["tokens_output"] += r.tokens_output
            bm["cost"] += r.cost

            # By tier
            if r.tier not in by_tier:
                by_tier[r.tier] = {
                    "calls": 0,
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "cost": 0.0,
                }
            bt = by_tier[r.tier]
            bt["calls"] += 1
            bt["tokens_input"] += r.tokens_input
            bt["tokens_output"] += r.tokens_output
            bt["cost"] += r.cost

        return {
            "period": period or "all",
            "total_cost": round(total, 6),
            "total_calls": len(filtered),
            "total_tokens_input": total_in,
            "total_tokens_output": total_out,
            "by_model": {
                k: {**v, "cost": round(v["cost"], 6)} for k, v in by_model.items()
            },
            "by_tier": {
                k: {**v, "cost": round(v["cost"], 6)} for k, v in by_tier.items()
            },
            "budget_limit": self._budget_limit,
            "remaining_budget": round(self.get_remaining_budget(), 6),
            "budget_used_pct": (
                round(total / self._budget_limit * 100, 1)
                if self._budget_limit and self._budget_limit > 0
                else None
            ),
        }

    def suggest_optimizations(self) -> list[dict[str, str]]:
        """Analyse usage patterns and return actionable cost-saving tips."""
        tips: list[dict[str, str]] = []

        if not self._records:
            tips.append(
                {
                    "type": "info",
                    "message": "No usage data yet. Suggestions will appear after routing some requests.",
                }
            )
            return tips

        report = self.get_usage_report()
        by_tier = report.get("by_tier", {})
        by_model = report.get("by_model", {})

        # 1. Premium over-use
        premium = by_tier.get("premium", {})
        premium_cost = premium.get("cost", 0)
        premium_calls = premium.get("calls", 0)
        total_cost = report["total_cost"]
        if total_cost > 0 and premium_cost / total_cost > 0.6:
            tips.append(
                {
                    "type": "high_cost",
                    "message": (
                        f"{premium_calls} premium-tier calls account for "
                        f"{premium_cost / total_cost * 100:.0f}% of spend. "
                        f"Review whether some tasks could use standard or budget models."
                    ),
                }
            )

        # 2. Single-model lock-in
        if len(by_model) == 1 and report["total_calls"] > 10:
            name = next(iter(by_model))
            tips.append(
                {
                    "type": "diversification",
                    "message": (
                        f"All {report['total_calls']} calls use {name}. "
                        f"Diversifying providers can improve resilience and potentially reduce cost."
                    ),
                }
            )

        # 3. High output-token usage (prompt caching opportunity)
        total_in = report["total_tokens_input"]
        total_out = report["total_tokens_output"]
        if total_in > 0 and total_out / total_in > 5:
            tips.append(
                {
                    "type": "caching",
                    "message": (
                        f"Output tokens are {total_out / total_in:.1f}× input tokens. "
                        f"Consider enabling prompt caching for repeated system prompts."
                    ),
                }
            )

        # 4. Budget warning
        if (
            self._budget_limit
            and self.get_remaining_budget() < self._budget_limit * 0.1
        ):
            tips.append(
                {
                    "type": "budget_warning",
                    "message": (
                        f"Only ${self.get_remaining_budget():.2f} remaining of "
                        f"${self._budget_limit:.2f} budget. Consider increasing the limit "
                        f"or routing more tasks to budget-tier models."
                    ),
                }
            )

        # 5. Low-hanging fruit — tasks going to standard that could be budget
        stats = self._router.get_routing_stats()
        if stats["total_routed"] > 0:
            std_pct = stats["percentages"].get("standard", 0)
            if std_pct > 50:
                tips.append(
                    {
                        "type": "downgrade_opportunity",
                        "message": (
                            f"{std_pct}% of requests route to standard tier. "
                            f"Some may be simple enough for budget models — review complexity thresholds."
                        ),
                    }
                )

        return tips

    def reset_budget(self) -> None:
        """Clear all usage records and reset the spending counter."""
        self._records.clear()
        self._total_spent = 0.0
        logger.info("Budget and usage records reset.")
        self._auto_persist()

    # ── persistence ────────────────────────────────────────────────
    def save(self, path: str | None = None) -> None:
        """Persist current state to *path* (or configured path)."""
        target = path or self._persist_path
        if not target:
            logger.warning("No persist path configured; skipping save.")
            return
        data = {
            "budget_limit": self._budget_limit,
            "total_spent": self._total_spent,
            "records": [
                {
                    "model": r.model,
                    "provider": r.provider,
                    "tier": r.tier,
                    "tokens_input": r.tokens_input,
                    "tokens_output": r.tokens_output,
                    "cost": r.cost,
                    "timestamp": r.timestamp,
                }
                for r in self._records
            ],
        }
        os.makedirs(os.path.dirname(target) or ".", exist_ok=True)
        with open(target, "w") as fh:
            json.dump(data, fh, indent=2)
        logger.debug("Saved optimizer state to %s", target)

    def load(self, path: str | None = None) -> None:
        """Load state from *path* (or configured path)."""
        self._load(path or self._persist_path)

    # ── private helpers ────────────────────────────────────────────
    def _find_profile(self, model: str) -> ModelProfile:
        """Look up a model profile from the router's registry."""
        for profiles in self._router._models.values():  # noqa: SLF001
            for p in profiles:
                if p.name == model:
                    return p
        # Fallback: return a synthetic budget profile so we never crash
        logger.warning("Model '%s' not found in router; using fallback pricing.", model)
        return ModelProfile(
            name=model,
            provider="unknown",
            tier="budget",
            cost_per_1k_input=0.15,
            cost_per_1k_output=0.60,
            max_context=4096,
        )

    def _auto_persist(self) -> None:
        if self._persist_path:
            self.save()

    def _load(self, path: str | None) -> None:  # type: ignore[override]
        if not path or not os.path.exists(path):
            return
        try:
            with open(path) as fh:
                data = json.load(fh)
            self._budget_limit = data.get("budget_limit", self._budget_limit)
            self._total_spent = data.get("total_spent", 0.0)
            self._records = [UsageRecord(**r) for r in data.get("records", [])]
            logger.info("Loaded %d usage records from %s", len(self._records), path)
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.error("Failed to load optimizer state from %s: %s", path, exc)

    @staticmethod
    def _period_cutoff(period: str | None) -> float:
        """Return the epoch-time cutoff for the given period string."""
        if not period:
            return 0.0
        deltas = {
            "1h": timedelta(hours=1),
            "24h": timedelta(hours=24),
            "7d": timedelta(days=7),
            "30d": timedelta(days=30),
        }
        if period not in deltas:
            raise ValueError(f"Unknown period '{period}'. Use: {', '.join(deltas)}")
        return (datetime.now(UTC) - deltas[period]).timestamp()
