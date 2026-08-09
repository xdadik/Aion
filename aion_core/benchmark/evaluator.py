""" "
Aion Hand Benchmark Evaluator

Evaluates agent outputs against task criteria using heuristic checks.
Each criterion is a string descriptor parsed into a check type and parameters.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any

from aion_core.benchmark.tasks import BenchmarkTask

logger = logging.getLogger(__name__)


@dataclass
class TaskResult:
    """Result of evaluating a single benchmark task."""

    task_id: str
    task_name: str
    success: bool = False
    score: float = 0.0
    criteria_met: list[str] = field(default_factory=list)
    criteria_failed: list[str] = field(default_factory=list)
    turns_used: int = 0
    tokens_used: int = 0
    time_elapsed: float = 0.0
    tools_used: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    agent_output: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary for JSON persistence."""
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "success": self.success,
            "score": round(self.score, 4),
            "criteria_met": self.criteria_met,
            "criteria_failed": self.criteria_failed,
            "turns_used": self.turns_used,
            "tokens_used": self.tokens_used,
            "time_elapsed": round(self.time_elapsed, 3),
            "tools_used": self.tools_used,
            "errors": self.errors,
            "agent_output": self.agent_output[:2000],
            "metadata": self.metadata,
        }


class BenchmarkEvaluator:
    """
    Evaluates agent outputs against task criteria.

    Criterion format:  "check_type:param1,param2,..."
    Supported check types:
        keywords:w1,w2,...       - All keywords must appear (comma-separated)
        min_length:N             - Output length >= N characters
        has_code:true|false      - Whether output should contain code blocks
        tool_used:tool_name      - Specific tool must appear in metadata
        pattern_match:regex      - Regex must match somewhere in output
    """

    def __init__(self) -> None:
        self._check_handlers = {
            "keywords": self._check_keywords,
            "min_length": self._check_min_length,
            "has_code": self._check_has_code,
            "tool_used": self._check_tool_used,
            "pattern_match": self._check_pattern_match,
        }
        self._results_history: list[TaskResult] = []

    # -- Public API ----------------------------------------------------------

    def evaluate(
        self,
        task: BenchmarkTask,
        agent_output: str,
        metadata: dict[str, Any] | None = None,
    ) -> TaskResult:
        """
        Evaluate agent output against a task's criteria.

        Args:
            task: The benchmark task definition.
            agent_output: The raw text output from the agent.
            metadata: Optional dict with extra context (tools_used, turns, tokens, etc.).

        Returns:
            A TaskResult with score, criteria breakdown, and metadata.
        """
        metadata = metadata or {}
        criteria_met: list[str] = []
        criteria_failed: list[str] = []

        for criterion in task.evaluation_criteria:
            passed = self._check_criterion(criterion, agent_output, metadata)
            if passed:
                criteria_met.append(criterion)
            else:
                criteria_failed.append(criterion)

        score = self._compute_score(task.evaluation_criteria, criteria_met)
        success = score >= 0.6  # 60% threshold to "pass"

        result = TaskResult(
            task_id=task.id,
            task_name=task.name,
            success=success,
            score=score,
            criteria_met=criteria_met,
            criteria_failed=criteria_failed,
            turns_used=metadata.get("turns_used", 0),
            tokens_used=metadata.get("tokens_used", 0),
            time_elapsed=metadata.get("time_elapsed", 0.0),
            tools_used=metadata.get("tools_used", []),
            errors=metadata.get("errors", []),
            agent_output=agent_output,
            metadata=metadata,
        )

        self._results_history.append(result)
        logger.info(
            "Task %s: score=%.2f, success=%s, criteria_met=%d/%d",
            task.id,
            score,
            success,
            len(criteria_met),
            len(task.evaluation_criteria),
        )
        return result

    def get_history(self) -> list[TaskResult]:
        """Return all evaluation results from this evaluator instance."""
        return list(self._results_history)

    def clear_history(self) -> None:
        """Reset evaluation history."""
        self._results_history.clear()

    # -- Criterion Dispatch --------------------------------------------------

    def _check_criterion(
        self,
        criterion: str,
        output: str,
        metadata: dict[str, Any],
    ) -> bool:
        """
        Parse a criterion string and dispatch to the appropriate checker.

        Criterion format: "check_type:param1,param2,..."
        Falls back to simple keyword-in-output if the format is unrecognized.
        """
        if ":" not in criterion:
            return criterion.lower() in output.lower()

        check_type, params_str = criterion.split(":", 1)
        check_type = check_type.strip().lower()
        params = params_str.strip()

        handler = self._check_handlers.get(check_type)
        if handler is None:
            logger.warning("Unknown check type '%s', treating as keyword", check_type)
            return check_type in output.lower()

        try:
            return handler(params, output, metadata)
        except Exception as exc:
            logger.error(
                "Criterion '%s' raised %s: %s", criterion, type(exc).__name__, exc
            )
            return False

    # -- Check Implementations ----------------------------------------------

    @staticmethod
    def _check_keywords(params: str, output: str, metadata: dict[str, Any]) -> bool:
        """
        All comma-separated keywords must appear in the output (case-insensitive).

        Format: "keywords:word1,word2,word3"
        """
        keywords = [k.strip() for k in params.split(",") if k.strip()]
        if not keywords:
            return False
        output_lower = output.lower()
        return all(kw.lower() in output_lower for kw in keywords)

    @staticmethod
    def _check_min_length(params: str, output: str, metadata: dict[str, Any]) -> bool:
        """
        Output must meet or exceed a minimum character length.

        Format: "min_length:200"
        """
        try:
            min_len = int(params.strip())
        except ValueError:
            logger.warning("Invalid min_length param: '%s'", params)
            return False
        return len(output.strip()) >= min_len

    @staticmethod
    def _check_has_code(params: str, output: str, metadata: dict[str, Any]) -> bool:
        """
        Check whether the output contains (or does not contain) code blocks.

        Format: "has_code:true" or "has_code:false"
        """
        expect_code = params.strip().lower()
        has_code = "```" in output

        if expect_code == "true":
            return has_code
        elif expect_code == "false":
            return not has_code
        else:
            logger.warning("Invalid has_code param: '%s'", params)
            return False

    @staticmethod
    def _check_tool_used(params: str, output: str, metadata: dict[str, Any]) -> bool:
        """
        A specific tool name must appear in the metadata's tools_used list.

        Format: "tool_used:web_search"
        """
        tool_name = params.strip()
        tools_used = metadata.get("tools_used", [])
        if isinstance(tools_used, list):
            return any(tool_name.lower() in str(t).lower() for t in tools_used)
        return False

    @staticmethod
    def _check_pattern_match(
        params: str, output: str, metadata: dict[str, Any]
    ) -> bool:
        """
        A regex pattern must match somewhere in the output.

        Format: "pattern_match:\\$\\d+"
        """
        try:
            pattern = params.strip()
            return bool(re.search(pattern, output))
        except re.error as exc:
            logger.warning("Invalid regex pattern '%s': %s", params, exc)
            return False

    # -- Scoring -------------------------------------------------------------

    @staticmethod
    def _compute_score(
        all_criteria: list[str],
        criteria_met: list[str],
    ) -> float:
        """
        Compute a score based on criteria results.

        Uniform weighting: each met criterion contributes 1/N to the score.
        If ALL criteria met, a small perfection bonus is applied.
        Returns a float in [0.0, 1.0].
        """
        if not all_criteria:
            return 0.0

        n = len(all_criteria)
        n_met = len(criteria_met)
        raw = n_met / n

        # Bonus: full marks get a small bump to reward perfection
        if n_met == n:
            return min(1.0, raw + 0.05)

        return round(raw, 4)


__all__ = ["TaskResult", "BenchmarkEvaluator"]
