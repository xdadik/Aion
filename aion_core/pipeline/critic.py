# Aion Hand - Critic
# Reviews and suggests improvements to execution results.

import json
import re
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from .verification import VerificationResult

logger = logging.getLogger("aion_hand.pipeline")


@dataclass
class CritiqueResult:
    """Result of critiquing an execution output."""
    score: float = 0.5  # 0.0-1.0 quality score
    issues: List[str] = field(default_factory=list)
    improvements: List[str] = field(default_factory=list)
    should_repair: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "score": round(self.score, 3),
            "issues": self.issues,
            "improvements": self.improvements,
            "should_repair": self.should_repair,
        }


class Critic:
    """Reviews execution results using verification outputs and LLM analysis.
    
    Analyzes verification results to identify quality issues,
    determines if repair is needed, and generates actionable suggestions.
    """

    CRITIQUE_SYSTEM_PROMPT = """You are a quality critic for AI agent outputs. Given a task,
its result, and verification results, provide a critique as JSON:

{
    "score": 0.0,
    "issues": ["issue1", "issue2"],
    "improvements": ["suggestion1", "suggestion2"],
    "should_repair": false,
    "reasoning": "brief explanation"
}

Guidelines:
- score: 0.0-1.0 (0.9+ excellent, 0.7-0.9 good, 0.5-0.7 needs work, <0.5 poor)
- issues: Specific problems found
- improvements: Actionable suggestions to fix issues
- should_repair: true if score < 0.7 AND there are actionable improvements
- Focus on: accuracy, completeness, clarity, logical consistency, safety

Return ONLY the JSON. No markdown, no explanation."""

    def __init__(self, agent: Any):
        self._agent = agent
        self._repair_threshold: float = 0.7

    @property
    def repair_threshold(self) -> float:
        return self._repair_threshold

    @repair_threshold.setter
    def repair_threshold(self, value: float) -> None:
        self._repair_threshold = max(0.0, min(1.0, value))

    async def critique(
        self,
        task: str,
        result: Any,
        verifications: List[VerificationResult],
    ) -> CritiqueResult:
        """Critique an execution result based on verification outputs.
        
        Args:
            task: The original task.
            result: The execution result to critique.
            verifications: List of verification results from the verification pipeline.
            
        Returns:
            A CritiqueResult with quality score, issues, and improvement suggestions.
        """
        logger.info(f"Critiquing result (task: {task[:60]}...)")

        # First, do heuristic analysis from verification results
        heuristic = self._heuristic_critique(task, result, verifications)

        # If heuristic is very confident (high or very low), use it directly
        if heuristic.score >= 0.9 or heuristic.score <= 0.3:
            logger.info(f"Heuristic critique confident: score={heuristic.score:.2f}")
            return heuristic

        # Otherwise, use LLM for deeper analysis
        llm_result = await self._llm_critique(task, result, verifications)
        if llm_result:
            # Blend heuristic and LLM results
            blended = self._blend_results(heuristic, llm_result)
            logger.info(f"LLM critique: score={blended.score:.2f}, should_repair={blended.should_repair}")
            return blended

        logger.info(f"Falling back to heuristic: score={heuristic.score:.2f}")
        return heuristic

    def _heuristic_critique(
        self,
        task: str,
        result: Any,
        verifications: List[VerificationResult],
    ) -> CritiqueResult:
        """Generate a critique based purely on verification results (no LLM)."""
        issues = []
        improvements = []
        score_factors = []

        # Process each verification result
        for v in verifications:
            if not v.passed:
                for issue in v.issues:
                    if issue and "No " not in issue and "No " not in issue[:4]:
                        issues.append(f"[{v.checked_by}] {issue}")
                        score_factors.append(-0.15)
                for suggestion in v.suggestions:
                    if suggestion:
                        improvements.append(suggestion)
            else:
                score_factors.append(v.confidence * 0.2)

        # Check result quality heuristics
        result_str = str(result) if result else ""
        word_count = len(result_str.split())

        if word_count < 5:
            issues.append("Result is extremely short")
            score_factors.append(-0.3)
        elif word_count < 20:
            issues.append("Result may be too brief for the task")
            score_factors.append(-0.1)
        elif word_count > 5000:
            improvements.append("Consider making the response more concise")

        # Check if result appears to be an error message
        error_indicators = ["error:", "exception:", "traceback", "failed to", "cannot", "unauthorized"]
        if any(ind in result_str.lower() for ind in error_indicators):
            issues.append("Result appears to contain error messages")
            score_factors.append(-0.4)

        # Check if task keywords appear in result
        task_keywords = set(re.findall(r"\b[a-zA-Z]{4,}\b", task.lower()))
        if task_keywords:
            result_lower = result_str.lower()
            keyword_coverage = sum(1 for kw in task_keywords if kw in result_lower) / len(task_keywords)
            score_factors.append(keyword_coverage * 0.3)
            if keyword_coverage < 0.3:
                issues.append(f"Low keyword coverage ({keyword_coverage:.0%}) - result may not address the task")

        # Calculate aggregate score
        if score_factors:
            raw_score = sum(score_factors) / len(score_factors)
            base_score = max(0.0, min(1.0, 0.5 + raw_score))
        else:
            base_score = 0.7  # Default: neutral-positive when no verifiers ran

        # Deduplicate issues and improvements
        issues = list(dict.fromkeys(issues))
        improvements = list(dict.fromkeys(improvements))

        should_repair = base_score < self._repair_threshold and len(improvements) > 0

        return CritiqueResult(
            score=base_score,
            issues=issues,
            improvements=improvements,
            should_repair=should_repair,
        )

    async def _llm_critique(
        self,
        task: str,
        result: Any,
        verifications: List[VerificationResult],
    ) -> Optional[CritiqueResult]:
        """Use the LLM to perform a deeper critique."""
        # Build verification summary
        verif_parts = []
        for v in verifications:
            status = "PASSED" if v.passed else "FAILED"
            verif_parts.append(f"- [{v.checked_by}] {status} (confidence: {v.confidence:.2f})")
            if v.issues:
                for issue in v.issues[:3]:
                    verif_parts.append(f"    Issue: {issue}")
            if v.suggestions:
                for sug in v.suggestions[:2]:
                    verif_parts.append(f"    Suggestion: {sug}")

        verif_summary = "\n".join(verif_parts)
        result_str = str(result)[:3000] if result else "(empty result)"

        user_message = (
            f"Task: {task[:500]}\n\n"
            f"Result:\n{result_str}\n\n"
            f"Verification Results:\n{verif_summary}"
        )

        try:
            response = await self._agent.chat(message=user_message)
            content = response.get("content", "") if isinstance(response, dict) else str(response)
        except Exception as e:
            logger.warning(f"LLM critique failed: {e}")
            return None

        return self._parse_llm_critique(content)

    def _parse_llm_critique(self, raw_content: str) -> Optional[CritiqueResult]:
        """Parse the LLM's critique JSON response."""
        json_str = None
        code_block_match = re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", raw_content, re.DOTALL)
        if code_block_match:
            json_str = code_block_match.group(1)
        else:
            brace_start = raw_content.find("{")
            brace_end = raw_content.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                json_str = raw_content[brace_start:brace_end + 1]

        if not json_str:
            return None

        try:
            data = json.loads(json_str)
            score = float(data.get("score", 0.5))
            score = max(0.0, min(1.0, score))
            issues = [str(i) for i in data.get("issues", []) if i]
            improvements = [str(i) for i in data.get("improvements", []) if i]
            should_repair = bool(data.get("should_repair", False))
            return CritiqueResult(
                score=score,
                issues=issues,
                improvements=improvements,
                should_repair=should_repair,
            )
        except (json.JSONDecodeError, TypeError, ValueError) as e:
            logger.warning(f"Failed to parse LLM critique: {e}")
            return None

    def _blend_results(
        self, heuristic: CritiqueResult, llm: CritiqueResult
    ) -> CritiqueResult:
        """Blend heuristic and LLM critique results."""
        alpha = 0.4  # Weight for LLM (0.6 for heuristic)
        blended_score = alpha * llm.score + (1 - alpha) * heuristic.score

        all_issues = list(dict.fromkeys(heuristic.issues + llm.issues))
        all_improvements = list(dict.fromkeys(heuristic.improvements + llm.improvements))

        should_repair = (
            blended_score < self._repair_threshold
            and len(all_improvements) > 0
        )

        return CritiqueResult(
            score=blended_score,
            issues=all_issues,
            improvements=all_improvements,
            should_repair=should_repair,
        )
