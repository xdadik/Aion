# Aion Hand - Confidence Estimator
# Combines verification pass rates, critique scores, and execution signals
# into a single confidence score for the pipeline result.

import logging
import re
from typing import Any, Dict, List, Optional

from .critic import CritiqueResult
from .executor import ExecutionResult
from .verification import VerificationResult

logger = logging.getLogger("aion_hand.pipeline")


class ConfidenceEstimator:
    """Estimates overall confidence in a pipeline execution result.

    Combines multiple signals into a single 0.0-1.0 confidence score:
    - Verification pass rate and average verifier confidence
    - Critique quality score
    - Execution success rate across plan nodes
    - Result length and quality heuristics

    The weighting adjusts based on which signals are available.
    A result with no verification data but a successful execution
    gets a moderate default confidence rather than failing.
    """

    def __init__(
        self,
        weight_verification: float = 0.35,
        weight_critique: float = 0.30,
        weight_execution: float = 0.20,
        weight_heuristic: float = 0.15,
    ):
        self._weight_verification = weight_verification
        self._weight_critique = weight_critique
        self._weight_execution = weight_execution
        self._weight_heuristic = weight_heuristic

    def estimate(
        self,
        result: Any,
        verifications: list[VerificationResult],
        critique: CritiqueResult,
        execution_results: dict[str, ExecutionResult] | None = None,
    ) -> float:
        """Estimate overall confidence in the result.

        Args:
            result: The final output from execution/repair.
            verifications: List of verification results.
            critique: Critique result with quality score.
            execution_results: Optional dict of per-node execution results.

        Returns:
            Confidence float between 0.0 and 1.0.
        """
        scores = {}
        total_weight = 0.0

        # Signal 1: Verification pass rate and confidence
        verif_score, verif_weight = self._verification_signal(verifications)
        if verif_weight > 0:
            scores["verification"] = (verif_score, verif_weight)
            total_weight += verif_weight

        # Signal 2: Critique score
        if critique is not None:
            scores["critique"] = (critique.score, self._weight_critique)
            total_weight += self._weight_critique

        # Signal 3: Execution success rate
        exec_score, exec_weight = self._execution_signal(execution_results)
        if exec_weight > 0:
            scores["execution"] = (exec_score, exec_weight)
            total_weight += exec_weight

        # Signal 4: Heuristic quality check on the result itself
        heur_score = self._heuristic_signal(result)
        scores["heuristic"] = (heur_score, self._weight_heuristic)
        total_weight += self._weight_heuristic

        # Weighted combination
        if total_weight == 0:
            logger.warning("No signals available for confidence estimation, returning 0.5")
            return 0.5

        confidence = 0.0
        for _signal_name, (signal_score, signal_weight) in scores.items():
            normalized_weight = signal_weight / total_weight
            confidence += signal_score * normalized_weight

        confidence = max(0.0, min(1.0, confidence))
        logger.info(
            f"Confidence estimate: {confidence:.3f} "
            f"(signals: {', '.join(f'{n}={s:.2f}' for n, (s, _) in scores.items())})"
        )
        return confidence

    def _verification_signal(
        self, verifications: list[VerificationResult]
    ) -> tuple:
        """Compute verification signal: pass rate * average confidence."""
        if not verifications:
            return (0.7, 0.0)  # No verifiers ran, no weight

        real_verifiers = [
            v for v in verifications
            if v.checked_by and v.checked_by != "none"
               and "No applicable" not in " ".join(v.issues)
        ]

        if not real_verifiers:
            return (0.7, self._weight_verification * 0.3)

        passed_count = sum(1 for v in real_verifiers if v.passed)
        pass_rate = passed_count / len(real_verifiers)

        avg_confidence = sum(v.confidence for v in real_verifiers) / len(real_verifiers)

        # Security verifier is a hard gate
        security_failed = any(
            not v.passed and v.checked_by == "security_verifier"
            for v in real_verifiers
        )
        if security_failed:
            logger.warning("Security verifier failed, capping verification signal")
            pass_rate = min(pass_rate, 0.3)

        score = pass_rate * 0.6 + avg_confidence * 0.4
        weight = self._weight_verification

        return (score, weight)

    def _execution_signal(
        self, execution_results: dict[str, ExecutionResult] | None
    ) -> tuple:
        """Compute execution signal: success rate across plan nodes."""
        if not execution_results:
            return (0.8, 0.0)  # No execution data available

        total = len(execution_results)
        if total == 0:
            return (0.8, 0.0)

        successful = sum(
            1 for r in execution_results.values()
            if r.status == "success"
        )
        success_rate = successful / total

        # Penalize if the final/verify node failed
        verify_failed = any(
            r.status != "success"
            for nid, r in execution_results.items()
            if "verify" in nid.lower()
        )
        if verify_failed:
            success_rate *= 0.7

        # Check for retries (more retries = less confident)
        total_retries = sum(r.retry_count for r in execution_results.values())
        retry_penalty = min(total_retries * 0.05, 0.3)
        score = max(0.0, success_rate - retry_penalty)

        return (score, self._weight_execution)

    def _heuristic_signal(self, result: Any) -> float:
        """Compute heuristic quality signal based on the result itself."""
        if result is None:
            return 0.2

        result_str = str(result)
        score = 0.5

        # Length check
        word_count = len(result_str.split())
        if word_count < 3:
            score -= 0.3
        elif word_count < 10:
            score -= 0.1
        elif word_count > 20 or word_count > 100:
            score += 0.1

        # Error indicators
        error_patterns = [
            r'(?i)error[:"]', r'(?i)exception[:"]', r'(?i)traceback',
            r"(?i)failed to", r"(?i)cannot ", r"(?i)unauthorized",
            r"(?i)access denied", r"(?i)not found",
        ]
        error_count = sum(1 for p in error_patterns if re.search(p, result_str))
        if error_count > 0:
            score -= min(error_count * 0.15, 0.4)

        # Quality indicators
        if any(marker in result_str for marker in ["#", "**", "- ", "1.", "First", "Step"]):
            score += 0.1  # Has structure

        if any(marker in result_str for marker in ["```", "code", "function", "class"]):
            score += 0.05  # Contains code

        # Hedging
        hedging_words = ["maybe", "perhaps", "might", "could be", "I think", "not sure"]
        hedging_count = sum(1 for w in hedging_words if w in result_str.lower())
        if hedging_count > 3:
            score -= 0.1

        return max(0.0, min(1.0, score))
