"""Complexity estimation for LLM routing decisions.

Heuristic-based scoring that examines task text and context to produce a
0–1 complexity score along with a reasoning-type classification and a
tier suggestion.  No ML model is required — pure keyword / structural
heuristics tuned for real-world prompt patterns.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


# ── Reasoning type classification ─────────────────────────────────────
class ReasoningType(str, Enum):
    SIMPLE = "simple"
    CREATIVE = "creative"
    ANALYSIS = "analysis"
    CODING = "coding"
    RESEARCH = "research"


# ── Dataclass returned by the estimator ───────────────────────────────
@dataclass
class TaskComplexity:
    """Full complexity breakdown produced by ``ComplexityEstimator``."""

    score: float  # 0.0 – 1.0
    reasoning_type: ReasoningType = ReasoningType.SIMPLE
    estimated_turns: int = 1
    suggested_model_tier: str = "budget"  # budget / standard / premium
    factors: dict = field(default_factory=dict)  # individual factor scores


# ── Keyword / pattern tables ──────────────────────────────────────────
_CODING_KEYWORDS: list[str] = [
    "function",
    "class",
    "def ",
    "import ",
    "return ",
    "async ",
    "await ",
    "refactor",
    "debug",
    "compile",
    "syntax error",
    "runtime error",
    "unit test",
    "integration test",
    "api endpoint",
    "sql query",
    "algorithm",
    "data structure",
    "git merge",
    "pull request",
    "code review",
    "type hint",
    "interface",
    "implement",
    "module",
    "dependency",
    "dockerfile",
    "kubernetes",
    "ci/cd",
    "microservice",
    "protobuf",
    "graphql",
    "rest api",
    "websocket",
    "multithread",
    "python",
    "javascript",
    "typescript",
    "rust",
    "golang",
    "java ",
    "code",
    "coding",
    "program",
    "script",
    "parse",
    "serialize",
    "error handling",
    "exception",
    "recursion",
    "optimization",
]

_RESEARCH_KEYWORDS: list[str] = [
    "research",
    "study",
    "survey",
    "literature",
    "citation",
    "reference",
    "peer-reviewed",
    "experiment",
    "hypothesis",
    "methodology",
    "systematic review",
    "meta-analysis",
    "dataset",
    "correlation",
    "statistical significance",
    "empirical",
    "qualitative",
    "quantitative",
    "longitudinal",
    "cross-sectional",
    "case study",
    "randomized",
    "control group",
    "variable",
    "p-value",
    "investigate",
    "investigation",
    "review of",
    "examine",
    "academic",
    "journal",
    "paper",
    "publication",
    "findings",
    "literature review",
    "state of the art",
    "prior work",
]

_ANALYSIS_KEYWORDS: list[str] = [
    "analyze",
    "analysis",
    "compare",
    "compar",
    "contrast",
    "evaluate",
    "evaluat",
    "assess",
    "benchmark",
    "metrics",
    "kpi",
    "dashboard",
    "trend",
    "forecast",
    "regression",
    "classification",
    "clustering",
    "anomaly detection",
    "data pipeline",
    "etl",
    "aggregate",
    "breakdown",
    "pivot",
    "correlation",
    "insight",
    "roi",
    "cost-benefit",
    "trade-off",
    "across",
    "versus",
    "vs ",
    "pros and cons",
    "strengths",
    "weaknesses",
    "opportunities",
    "threats",
    "swot",
    "architecture",
    "mechanism",
    "performance",
    "accuracy",
]

_CREATIVE_KEYWORDS: list[str] = [
    "write",
    "story",
    "poem",
    "song",
    "creative",
    "brainstorm",
    "ideate",
    "design",
    "mockup",
    "wireframe",
    "prototype",
    "narrative",
    "script",
    "slogan",
    "tagline",
    "brand voice",
    "campaign",
    "copywriting",
    "headline",
    "blog post",
    "article",
    "whitepaper",
    "ebook",
    "newsletter",
    "social media post",
    "landing page",
]

_MULTI_STEP_INDICATORS: list[str] = [
    "then",
    "after that",
    "next step",
    "finally",
    "lastly",
    "step 1",
    "step 2",
    "step 3",
    "first",
    "second",
    "third",
    "part 1",
    "part 2",
    "part 3",
    "phase 1",
    "phase 2",
    "phase 3",
    "multi-step",
    "multi-step",
    "pipeline",
    "workflow",
    "chain of",
    "sequential",
    "iterative",
    "loop through",
    "repeat until",
]

_TOOL_INDICATORS: list[str] = [
    "search",
    "look up",
    "find",
    "fetch",
    "scrape",
    "download",
    "calculate",
    "compute",
    "convert",
    "translate",
    "summarize",
    "extract",
    "parse",
    "read file",
    "write file",
    "run command",
    "execute",
    "api call",
    "http request",
    "database query",
    "webhook",
    "browser",
    "screenshot",
    "pdf",
    "spreadsheet",
]


class ComplexityEstimator:
    """Heuristic complexity estimator for LLM task routing.

    Produces a :class:`TaskComplexity` with a 0–1 score and a suggested
    model tier.  The estimator inspects task length, keyword density,
    multi-step indicators, and expected tool usage.
    """

    # ── weights for each signal ────────────────────────────────────
    W_LENGTH = 0.05
    W_KEYWORD = 0.35
    W_MULTI_STEP = 0.20
    W_TOOLS = 0.15
    W_DOMAIN = 0.15
    W_CONTEXT_SIZE = 0.10

    def __init__(self, config: dict | None = None) -> None:
        cfg = config or {}
        self._min_chars = cfg.get("min_chars_for_high", 800)
        self._keyword_threshold = cfg.get("keyword_threshold", 1)

    # ── public API ─────────────────────────────────────────────────
    def estimate(
        self,
        task: str,
        context: str | None = None,
    ) -> TaskComplexity:
        """Return a :class:`TaskComplexity` for *task* + optional *context*."""
        combined = f"{task}\n{context or ''}"
        combined_lower = combined.lower()

        factors: dict[str, float] = {}

        # 1. Length signal
        factors["length"] = self._score_length(combined)

        # 2. Keyword / domain signal
        reasoning_type, factors["keyword"] = self._score_keywords(combined_lower)

        # 3. Multi-step signal
        factors["multi_step"] = self._score_multi_step(combined_lower)

        # 4. Tool-usage signal
        factors["tools"] = self._score_tools(combined_lower)

        # 5. Domain complexity (structured data, maths, etc.)
        factors["domain"] = self._score_domain(combined)

        # 6. Context size
        factors["context_size"] = self._score_context(context)

        # Weighted aggregate
        score = (
            self.W_LENGTH * factors["length"]
            + self.W_KEYWORD * factors["keyword"]
            + self.W_MULTI_STEP * factors["multi_step"]
            + self.W_TOOLS * factors["tools"]
            + self.W_DOMAIN * factors["domain"]
            + self.W_CONTEXT_SIZE * factors["context_size"]
        )
        score = max(0.0, min(1.0, score))

        estimated_turns = self._estimate_turns(factors, score)
        tier = self._pick_tier(score, reasoning_type)

        return TaskComplexity(
            score=score,
            reasoning_type=reasoning_type,
            estimated_turns=estimated_turns,
            suggested_model_tier=tier,
            factors=factors,
        )

    # ── private scoring helpers ────────────────────────────────────
    def _score_length(self, text: str) -> float:
        length = len(text)
        if length <= 100:
            return 0.1
        if length <= 300:
            return 0.3
        if length <= 600:
            return 0.5
        if length <= self._min_chars:
            return 0.7
        return 1.0

    def _score_keywords(self, text: str) -> tuple[ReasoningType, float]:
        """Return (dominant reasoning type, keyword density score).

        Uses a flexible stem-prefix match so that e.g. "comparing" matches
        the keyword "compare" and "functions" matches "function".
        """
        text_words = set(re.findall(r"\b\w+\b", text))

        def _count(keywords: list[str]) -> int:
            n = 0
            for kw in keywords:
                kw_stripped = kw.strip()
                if not kw_stripped:
                    continue
                # Multi-word phrase: try exact substring match
                if " " in kw_stripped:
                    if kw_stripped in text:
                        n += 1
                else:
                    # Single word: prefix match (word starts with keyword)
                    if any(
                        w.startswith(kw_stripped) for w in text_words if len(w) >= 3
                    ):
                        n += 1
            return n

        hits: dict[ReasoningType, int] = {
            ReasoningType.CODING: _count(_CODING_KEYWORDS),
            ReasoningType.RESEARCH: _count(_RESEARCH_KEYWORDS),
            ReasoningType.ANALYSIS: _count(_ANALYSIS_KEYWORDS),
            ReasoningType.CREATIVE: _count(_CREATIVE_KEYWORDS),
        }
        dominant = max(hits, key=hits.get)  # type: ignore[arg-type]
        count = hits[dominant]
        score = min(1.0, count * 0.25)
        if count >= 5:
            score = 1.0
        if count < self._keyword_threshold:
            dominant = ReasoningType.SIMPLE
        return dominant, score

    def _score_multi_step(self, text: str) -> float:
        count = sum(1 for ind in _MULTI_STEP_INDICATORS if ind in text)
        if count == 0:
            return 0.0
        if count <= 2:
            return 0.3
        if count <= 4:
            return 0.6
        return 1.0

    def _score_tools(self, text: str) -> float:
        count = sum(1 for t in _TOOL_INDICATORS if t in text)
        if count == 0:
            return 0.0
        if count == 1:
            return 0.2
        if count <= 3:
            return 0.5
        return 1.0

    def _score_domain(self, text: str) -> float:
        """Extra complexity for structured / mathematical content."""
        score = 0.0
        # Code blocks
        code_blocks = text.count("```") // 2
        score += min(0.3, code_blocks * 0.1)
        # Math symbols
        math_chars = len(re.findall(r"[∑∫∂√∞±≈≠≤≥∈∉∩∪]", text))
        score += min(0.3, math_chars * 0.1)
        # Number-heavy content
        numbers = len(re.findall(r"\b\d+\.?\d*%?\b", text))
        if numbers > 10:
            score += 0.2
        # URLs or file paths
        urls = len(re.findall(r"https?://\S+", text))
        paths = len(re.findall(r"/[\w./\-]+", text))
        score += min(0.2, (urls + paths) * 0.05)
        return min(1.0, score)

    def _score_context(self, context: str | None) -> float:
        if not context:
            return 0.0
        ctx_len = len(context)
        if ctx_len <= 500:
            return 0.2
        if ctx_len <= 2000:
            return 0.5
        if ctx_len <= 5000:
            return 0.7
        return 1.0

    def _estimate_turns(self, factors: dict[str, float], score: float) -> int:
        if factors["multi_step"] >= 0.6 or score >= 0.7:
            return 4
        if factors["multi_step"] >= 0.3 or score >= 0.5:
            return 2
        return 1

    @staticmethod
    def _pick_tier(score: float, reasoning_type: ReasoningType) -> str:
        """Map score + reasoning type to a model tier."""
        # Coding and research get premium when moderately complex
        if score >= 0.55 or (
            reasoning_type
            in (ReasoningType.CODING, ReasoningType.ANALYSIS, ReasoningType.RESEARCH)
            and score >= 0.35
        ):
            return "premium"
        if score >= 0.35 or (
            reasoning_type
            in (ReasoningType.CODING, ReasoningType.ANALYSIS, ReasoningType.RESEARCH)
            and score >= 0.15
        ):
            return "standard"
        return "budget"
