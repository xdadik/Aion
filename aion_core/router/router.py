from __future__ import annotations

import json
import logging
import urllib.request
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
            "chat", "json", "function_calling", "vision", "code_interpreter"
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
            "chat", "json", "function_calling", "vision", "extended_thinking"
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
            "chat", "json", "function_calling", "vision", "audio", "video"
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
            "chat", "json", "function_calling", "vision", "code_interpreter",
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
            "chat", "json", "vision", "extended_thinking", "nuanced_reasoning"
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
            "chat", "json", "function_calling", "vision", "audio",
            "video", "multimodal_reasoning",
        ],
        "avg_latency_ms": 1000.0,
    },
    # ── OpenRouter models (one key → 300+ models; live-verified 2026-08) ──
    {
        "name": "meta-llama/llama-4-scout",
        "provider": "openrouter",
        "tier": "budget",
        "cost_per_1k_input": 0.0001,
        "cost_per_1k_output": 0.0003,
        "max_context": 1310720,
        "capabilities": ["chat", "json", "function_calling", "vision"],
        "avg_latency_ms": 350.0,
    },
    {
        "name": "mistralai/mistral-small-2603",
        "provider": "openrouter",
        "tier": "budget",
        "cost_per_1k_input": 0.0001,
        "cost_per_1k_output": 0.0006,
        "max_context": 262144,
        "capabilities": ["chat", "json", "function_calling"],
        "avg_latency_ms": 320.0,
    },
    {
        "name": "google/gemini-3.7-flash",
        "provider": "openrouter",
        "tier": "budget",
        "cost_per_1k_input": 0.0004,
        "cost_per_1k_output": 0.0019,
        "max_context": 1048576,
        "capabilities": ["chat", "json", "function_calling", "vision"],
        "avg_latency_ms": 280.0,
    },
    {
        "name": "qwen/qwen3.8-27b",
        "provider": "openrouter",
        "tier": "standard",
        "cost_per_1k_input": 0.0004,
        "cost_per_1k_output": 0.0026,
        "max_context": 1000000,
        "capabilities": ["chat", "json", "function_calling"],
        "avg_latency_ms": 450.0,
    },
    {
        "name": "deepseek/deepseek-chat",
        "provider": "openrouter",
        "tier": "standard",
        "cost_per_1k_input": 0.0014,
        "cost_per_1k_output": 0.0056,
        "max_context": 131072,
        "capabilities": ["chat", "json", "function_calling", "code"],
        "avg_latency_ms": 500.0,
    },
    {
        "name": "openai/gpt-4o",
        "provider": "openrouter",
        "tier": "standard",
        "cost_per_1k_input": 0.0025,
        "cost_per_1k_output": 0.0100,
        "max_context": 128000,
        "capabilities": ["chat", "json", "function_calling", "vision"],
        "avg_latency_ms": 600.0,
    },
    {
        "name": "anthropic/claude-sonnet-5",
        "provider": "openrouter",
        "tier": "premium",
        "cost_per_1k_input": 0.0020,
        "cost_per_1k_output": 0.0100,
        "max_context": 1000000,
        "capabilities": [
            "chat", "json", "function_calling", "vision", "extended_thinking"
        ],
        "avg_latency_ms": 700.0,
    },
    {
        "name": "anthropic/claude-opus-5-fast",
        "provider": "openrouter",
        "tier": "premium",
        "cost_per_1k_input": 0.0100,
        "cost_per_1k_output": 0.0500,
        "max_context": 1000000,
        "capabilities": [
            "chat", "json", "function_calling", "vision", "nuanced_reasoning"
        ],
        "avg_latency_ms": 900.0,
    },
    {
        "name": "openai/gpt-5.6-terra-pro",
        "provider": "openrouter",
        "tier": "premium",
        "cost_per_1k_input": 0.0020,
        "cost_per_1k_output": 0.0120,
        "max_context": 1050000,
        "capabilities": [
            "chat", "json", "function_calling", "vision", "code_interpreter"
        ],
        "avg_latency_ms": 850.0,
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
        estimated_cost = (
            model.cost_per_1k_input * (est_input / 1000)
            + model.cost_per_1k_output * (est_output / 1000)
        )

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
                result.append({
                    "name": p.name,
                    "provider": p.provider,
                    "tier": p.tier,
                    "cost_per_1k_input": p.cost_per_1k_input,
                    "cost_per_1k_output": p.cost_per_1k_output,
                    "max_context": p.max_context,
                    "capabilities": p.capabilities,
                    "avg_latency_ms": p.avg_latency_ms,
                })
        return result

    # ── OpenRouter live hydration ────────────────────────────────────
    #: Vendor prefixes considered "curated" when hydrating from the live
    #: OpenRouter catalog (417+ models at time of writing).
    OPENROUTER_CURATED_PREFIXES = (
        "openai/", "anthropic/", "google/", "meta-llama/",
        "deepseek/", "qwen/", "mistralai/", "x-ai/", "cohere/",
        "microsoft/", "amazon/", "nvidia/",
    )
    OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

    def hydrate_from_openrouter(
        self,
        max_models: int = 150,
        include_free: bool = True,
        timeout: float = 20.0,
    ) -> int:
        """Fetch the live OpenRouter catalog and register real models.

        OpenRouter's ``/api/v1/models`` endpoint is public (no key needed)
        and reports per-token pricing plus context length for 400+ models.
        This turns a single ``OPENROUTER_API_KEY`` into a fully-hydrated,
        current model registry — closing the "45+ providers" gap with one
        credential.

        Tiering by output price (USD / 1k tokens):
        - ``:free`` variants and $0 output  -> budget
        - output < $0.005                  -> budget
        - output < $0.02                   -> standard
        - else                             -> premium

        ``:batch`` variants are skipped (same model, async delivery).
        Returns the number of newly-registered models.
        """
        try:
            req = urllib.request.Request(
                self.OPENROUTER_MODELS_URL,
                headers={"User-Agent": "aion-hand-router"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - hydration is best-effort
            logger.warning("OpenRouter hydration failed (offline?): %s", exc)
            return 0

        existing = {m["name"] for m in self.list_models()}
        added = 0
        for entry in data.get("data", []):
            model_id = entry.get("id", "")
            if not model_id or model_id.endswith(":batch"):
                continue
            if not model_id.startswith(self.OPENROUTER_CURATED_PREFIXES):
                continue
            if model_id not in existing and added >= max_models:
                break

            pricing = entry.get("pricing", {}) or {}
            try:
                per_token_in = float(pricing.get("prompt") or 0.0)
                per_token_out = float(pricing.get("completion") or 0.0)
            except (TypeError, ValueError):
                continue
            cost_in = round(per_token_in * 1000, 6)
            cost_out = round(per_token_out * 1000, 6)
            if cost_in < 0 or cost_out < 0:  # negative = unsupported modality
                continue

            is_free = model_id.endswith(":free") or (cost_in == 0 and cost_out == 0)
            if is_free and not include_free:
                continue
            if is_free or cost_out < 0.005:
                tier = "budget"
            elif cost_out < 0.02:
                tier = "standard"
            else:
                tier = "premium"

            supported = entry.get("supported_parameters", []) or []
            caps = ["chat"]
            if "response_format" in supported or "structured_outputs" in supported:
                caps.append("json")
            if "tools" in supported or "tool_choice" in supported:
                caps.append("function_calling")
            if (entry.get("architecture", {}) or {}).get(
                "input_modalities", ["text"]
            ) != ["text"]:
                caps.append("vision")
            if entry.get("reasoning"):
                caps.append("extended_thinking")

            profile = ModelProfile(
                name=model_id,
                provider="openrouter",
                tier=tier,
                cost_per_1k_input=cost_in,
                cost_per_1k_output=cost_out,
                max_context=int(entry.get("context_length") or 8192),
                capabilities=caps,
                avg_latency_ms=500.0,
            )
            self.add_model(profile)
            if model_id not in existing:
                added += 1
        if added:
            logger.info(
                "OpenRouter hydration: +%d models (catalog: %d)",
                added, len(data.get("data", [])),
            )
        return added

    def add_model(self, profile: ModelProfile) -> None:
        """Register a new model profile.  Replaces existing entry with same name."""
        tier = profile.tier
        if tier not in self._models:
            self._models[tier] = []
        # Remove previous version if present
        self._models[tier] = [
            m for m in self._models[tier] if m.name != profile.name
        ]
        self._models[tier].append(profile)
        logger.info("Registered model %s (%s, %s)", profile.name, profile.provider, tier)

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
            "models_available": {
                t: len(profs) for t, profs in self._models.items()
            },
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
