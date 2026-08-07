"""High-level API that combines routing and cost optimisation.

:class:`RouterManager` is the single entry-point most callers should use.
It delegates to :class:`ModelRouter` for routing decisions and
:class:`CostOptimizer` for spend tracking / persistence.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from .optimizer import CostOptimizer
from .router import ModelRouter, RoutingDecision

logger = logging.getLogger(__name__)


class RouterManager:
    """Convenience facade over :class:`ModelRouter` + :class:`CostOptimizer`.

    Parameters
    ----------
    config : dict, optional
        Keys:

        * ``budget_limit`` (float) — soft spending cap in USD
        * ``persist_path`` (str) — JSON file for state persistence
        * ``model_profiles`` (list[dict]) — extra model profiles
        * ``estimator_config`` (dict) — forwarded to the estimator
        * ``default_tier`` (str) — fallback tier
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}

        self.router = ModelRouter(cfg)
        self.optimizer = CostOptimizer(
            router=self.router,
            budget_limit=cfg.get("budget_limit"),
            persist_path=cfg.get("persist_path"),
        )

        logger.info(
            "RouterManager ready — %d models, budget_limit=%s",
            len(self.router.list_models()),
            cfg.get("budget_limit", "none"),
        )

    # ── core workflow ──────────────────────────────────────────────
    def route(
        self,
        task: str,
        context: str | None = None,
        force_tier: str | None = None,
        preferred_provider: str | None = None,
    ) -> RoutingDecision:
        """Route a task and optionally check budget before proceeding.

        If a budget limit is set and the remaining budget is less than
        the estimated cost, the request is downgraded to the budget tier.
        """
        decision = self.router.route(task, context, force_tier, preferred_provider)

        # Budget guard — downgrade if we'd overshoot
        remaining = self.optimizer.get_remaining_budget()
        if (
            remaining != float("inf")
            and decision.estimated_cost > remaining
            and force_tier is None
        ):
            logger.warning(
                "Estimated cost $%.4f exceeds remaining budget $%.4f; "
                "downgrading to budget tier.",
                decision.estimated_cost,
                remaining,
            )
            decision = self.router.route(task, context, force_tier="budget")

        return decision

    def track(
        self,
        model: str,
        tokens_input: int,
        tokens_output: int,
    ) -> float:
        """Record actual token usage for *model*.  Returns the cost (USD)."""
        return self.optimizer.track_usage(model, tokens_input, tokens_output)

    # ── reporting ──────────────────────────────────────────────────
    def get_report(self, period: str | None = None) -> dict[str, Any]:
        """Combined routing stats + cost report."""
        return {
            "routing_stats": self.router.get_routing_stats(),
            "usage_report": self.optimizer.get_usage_report(period),
            "optimizations": [
                {"type": t["type"], "message": t["message"]}
                for t in self.optimizer.suggest_optimizations()
            ],
        }

    # ── persistence ────────────────────────────────────────────────
    def save(self, path: str | None = None) -> None:
        """Persist optimizer state (routing stats are ephemeral)."""
        self.optimizer.save(path)

    def load(self, path: str | None = None) -> None:
        """Load persisted optimizer state."""
        self.optimizer.load(path)
