from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .estimator import ComplexityEstimator, TaskComplexity

logger = logging.getLogger(__name__)


# ── Tier enum ─────────────────────────────────────────────────────────
class Tier(str, Enum):
    BUDGET = "budget"
    STANDARD = "standard"
    PREMIUM = "premium"


# ── Dataclasses ───────────────────────────────────────────────────────
@dataclass
class ModelProfile:
    """Describes a single LLM available for routing.

    All pricing is in **USD per 1 000 tokens**.
    """

    name: str
    provider: str
    tier: str  # "budget" | "standard" | "premium"
    cost_per_1k_input: float
    cost_per_1k_output: float
    max_context: int  # tokens
    capabilities: list[str] = field(default_factory=list)
    avg_latency_ms: float = 500.0

    @property
    def tier_enum(self) -> Tier:
        return Tier(self.tier)


@dataclass
class RoutingDecision:
    """Result of a routing call."""

    model: str
    provider: str
    tier: str
    estimated_cost: float
    reasoning: str
    complexity: TaskComplexity | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "model": self.model,
            "provider": self.provider,
            "tier": self.tier,
            "estimated_cost": self.estimated_cost,
            "reasoning": self.reasoning,
            "complexity_score": self.complexity.score if self.complexity else None,
            "reasoning_type": (
                self.complexity.reasoning_type.value if self.complexity else None
            ),
            "estimated_turns": (
                self.complexity.estimated_turns if self.complexity else None
            ),
        }


# ── Default model profiles (real names, approximate pricing as of 2024) ──
_DEFAULT_PROFILES: list[dict[str, Any]] = [
    # ── Budget tier ────────────────────────────────────────────────
    {
        "name": "gpt-4o-mini",
        "provider": "openai",
        "tier": "budget",
        "cost_per_1k_input": 0.150,
        "cost_per_1k_output": 0.600,
        "max_context": 128000,
        "capabilities": ["chat", "json", "function_calling", "vision"],
        "avg_latency_ms": 350.0,
    },
    {
        "name": "claude-3-haiku-20240307",
        "provider": "anthropic",
        "tier": "budget",
        "cost_per_1k_input": 0.250,
        "cost_per_1k_output": 1.250,
        "max_context": 200000,
        "capabilities": ["chat", "json", "vision"],
        "avg_latency_ms": 400.0,
    },
    {
        "name": "gemini-1.5-flash",
        "provider": "google",
        "tier": "budget",
        "cost_per_1k_input": 0.075,
        "cost_per_1k_output": 0.300,
        "max_context": 1000000,
        "capabilities": ["chat", "json", "function_calling", "vision", "audio"],
        "avg_latency_ms": 300.0,
    },
    # ── Standard tier ──────────────────────────────────────────────
    {
        "name": "gpt-4o",
        "provider": "openai",
        "tier": "standard",
        "cost_per_1k_input": 2.500,
        "cost_per_1k_output": 10.000,
        "max_context": 128000,
        "capabilities": [
            "chat",
            "json",
            "function_calling",
            "vision",
            "code_interpreter",
        ],
        "avg_latency_ms": 600.0,
    },
    {
        "name": "claude-3-5-sonnet-20241022",
        "provider": "anthropic",
        "tier": "standard",
        "cost_per_1k_input": 3.000,
        "cost_per_1k_output": 15.000,
        "max_context": 200000,
        "capabilities": [
            "chat",
            "json",
            "function_calling",
            "vision",
            "extended_thinking",
        ],
        "avg_latency_ms": 700.0,
    },
    {
        "name": "gemini-1.5-pro",
        "provider": "google",
        "tier": "standard",
        "cost_per_1k_input": 1.250,
        "cost_per_1k_output": 5.000,
        "max_context": 2000000,
        "capabilities": [
            "chat",
            "json",
            "function_calling",
            "vision",
            "audio",
            "video",
        ],
        "avg_latency_ms": 550.0,
    },
    # ── Premium tier ───────────────────────────────────────────────
    {
        "name": "gpt-4-turbo-2024-04-09",
        "provider": "openai",
        "tier": "premium",
        "cost_per_1k_input": 10.000,
        "cost_per_1k_output": 30.000,
        "max_context": 128000,
        "capabilities": [
            "chat",
            "json",
            "function_calling",
            "vision",
            "code_interpreter",
            "knowledge_cutoff_2024_04",
        ],
        "avg_latency_ms": 900.0,
    },
    {
        "name": "claude-3-opus-20240229",
        "provider": "anthropic",
        "tier": "premium",
        "cost_per_1k_input": 15.000,
        "cost_per_1k_output": 75.000,
        "max_context": 200000,
        "capabilities": [
            "chat",
            "json",
            "vision",
            "extended_thinking",
            "nuanced_reasoning",
        ],
        "avg_latency_ms": 1200.0,
    },
    {
        "name": "gemini-ultra-1.0",
        "provider": "google",
        "tier": "premium",
        "cost_per_1k_input": 7.000,
        "cost_per_1k_output": 21.000,
        "max_context": 32000,
        "capabilities": [
            "chat",
            "json",
            "function_calling",
            "vision",
            "audio",
            "video",
            "multimodal_reasoning",
        ],
        "avg_latency_ms": 1000.0,
    },
]


class ModelRouter:
    """Routes tasks to the optimal LLM model.

    Parameters
    ----------
    config : dict, optional
        * ``model_profiles`` — list of dicts (overrides defaults)
        * ``estimator_config`` — forwarded to :class:`ComplexityEstimator`
        * ``default_tier`` — fallback tier when no models match (default ``budget``)
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        cfg = config or {}
        self._estimator = ComplexityEstimator(cfg.get("estimator_config"))
        self._default_tier: str = cfg.get("default_tier", "budget")

        # Build model registry  tier -> [ModelProfile, ...]
        self._models: dict[str, list[ModelProfile]] = {
            "budget": [],
            "standard": [],
            "premium": [],
        }

        # Load defaults first, then user overrides
        for entry in _DEFAULT_PROFILES:
            self.add_model(ModelProfile(**entry))

        for entry in cfg.get("model_profiles", []):
            self.add_model(ModelProfile(**entry))

        # Routing stats
        self._stats: dict[str, int] = {"budget": 0, "standard": 0, "premium": 0}
        self._total_routed: int = 0

    # ── public API ─────────────────────────────────────────────────
    def route(
        self,
        task: str,
        context: str | None = None,
        force_tier: str | None = None,
        preferred_provider: str | None = None,
    ) -> RoutingDecision:
        """Analyse *task* and return a :class:`RoutingDecision`."""
        complexity = self._estimator.estimate(task, context)

        # Determine tier
        if force_tier:
            tier = force_tier
        else:
            tier = complexity.suggested_model_tier

        # Pick a model from that tier
        model = self._select_model(tier, preferred_provider, task, context)

        # Rough cost estimate (assume ~200 tokens in, ~300 out per turn)
        est_input = max(len(task + "\n" + (context or "")) // 4, 200)
        est_output = 300 * complexity.estimated_turns
        estimated_cost = model.cost_per_1k_input * (
            est_input / 1000
        ) + model.cost_per_1k_output * (est_output / 1000)

        # Reasoning string
        if force_tier:
            reason = (
                f"Forced to {tier} tier.  Selected {model.name} "
                f"({model.provider}) — ${estimated_cost:.4f} estimated."
            )
        else:
            reason = (
                f"Complexity {complexity.score:.2f} ({complexity.reasoning_type.value}), "
                f"~{complexity.estimated_turns} turn(s).  Routed to {tier} tier → "
                f"{model.name} ({model.provider}) — ${estimated_cost:.4f} estimated."
            )

        # Update stats
        if tier in self._stats:
            self._stats[tier] += 1
        self._total_routed += 1

        return RoutingDecision(
            model=model.name,
            provider=model.provider,
            tier=model.tier,
            estimated_cost=round(estimated_cost, 6),
            reasoning=reason,
            complexity=complexity,
        )

    def get_model_for_tier(self, tier: str) -> ModelProfile:
        """Return the first available model for *tier*.

        Raises :class:`ValueError` if the tier is empty.
        """
        models = self._models.get(tier, [])
        if not models:
            raise ValueError(f"No models registered for tier '{tier}'")
        return models[0]

    def list_models(self) -> list[dict[str, Any]]:
        """Return every registered model as a plain dict."""
        result: list[dict[str, Any]] = []
        for tier_profiles in self._models.values():
            for p in tier_profiles:
                result.append(
                    {
                        "name": p.name,
                        "provider": p.provider,
                        "tier": p.tier,
                        "cost_per_1k_input": p.cost_per_1k_input,
                        "cost_per_1k_output": p.cost_per_1k_output,
                        "max_context": p.max_context,
                        "capabilities": p.capabilities,
                        "avg_latency_ms": p.avg_latency_ms,
                    }
                )
        return result

    def add_model(self, profile: ModelProfile) -> None:
        """Register a new model profile.  Replaces existing entry with same name."""
        tier = profile.tier
        if tier not in self._models:
            self._models[tier] = []
        # Remove previous version if present
        self._models[tier] = [m for m in self._models[tier] if m.name != profile.name]
        self._models[tier].append(profile)
        logger.info(
            "Registered model %s (%s, %s)", profile.name, profile.provider, tier
        )

    def remove_model(self, name: str) -> bool:
        """Remove a model by name.  Returns ``True`` if found and removed."""
        for tier, profiles in self._models.items():
            before = len(profiles)
            self._models[tier] = [m for m in profiles if m.name != name]
            if len(self._models[tier]) < before:
                logger.info("Removed model %s from tier %s", name, tier)
                return True
        return False

    def get_routing_stats(self) -> dict[str, Any]:
        """Return routing statistics."""
        return {
            "total_routed": self._total_routed,
            "by_tier": dict(self._stats),
            "percentages": {
                t: round(c / max(self._total_routed, 1) * 100, 1)
                for t, c in self._stats.items()
            },
            "models_available": {t: len(profs) for t, profs in self._models.items()},
        }

    def reset_stats(self) -> None:
        """Zero-out routing counters."""
        self._stats = {"budget": 0, "standard": 0, "premium": 0}
        self._total_routed = 0

    # ── private helpers ────────────────────────────────────────────
    def _select_model(
        self,
        tier: str,
        preferred_provider: str | None,
        task: str,
        context: str | None,
    ) -> ModelProfile:
        """Pick the best model from a tier.

        Strategy:
        1. If a preferred provider is given and has a model in this
           tier, use it.
        2. Otherwise pick the cheapest model that can fit the context
           (based on token estimate).
        3. Fall back to the first model in the tier.
        4. If the tier has no models, fall back to ``self._default_tier``.
        """
        candidates = self._models.get(tier, [])
        if not candidates:
            logger.warning(
                "No models in tier '%s'; falling back to '%s'.",
                tier,
                self._default_tier,
            )
            candidates = self._models.get(self._default_tier, [])
        if not candidates:
            raise RuntimeError("No models registered in any tier.")

        # Preferred provider filter
        if preferred_provider:
            provider_matches = [
                m for m in candidates if m.provider == preferred_provider
            ]
            if provider_matches:
                return self._cheapest(provider_matches)

        # Context-length filter
        est_tokens = len(task + "\n" + (context or "")) // 4
        fitting = [m for m in candidates if m.max_context >= est_tokens]
        if fitting:
            return self._cheapest(fitting)

        # Last resort: pick the one with the largest context window
        return max(candidates, key=lambda m: m.max_context)

    @staticmethod
    def _cheapest(models: list[ModelProfile]) -> ModelProfile:
        """Return the model with the lowest input + output cost."""
        return min(
            models,
            key=lambda m: m.cost_per_1k_input + m.cost_per_1k_output,
        )
