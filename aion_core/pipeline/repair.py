# Aion Hand - Repair Engine
# Fixes identified issues in execution results using targeted strategies and LLM assistance.

import json
import re
import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from .mission import MissionAnalysis
from .verification import VerificationResult
from .critic import CritiqueResult

logger = logging.getLogger("aion_hand.pipeline")


@dataclass
class RepairResult:
    """Result of a repair attempt."""
    success: bool = False
    repaired_output: Any = None
    repairs_made: List[str] = field(default_factory=list)
    tokens_used: int = 0
    elapsed: float = 0.0
    error: Optional[str] = None
    attempts: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "repaired_output": self._safe_output(),
            "repairs_made": self.repairs_made,
            "tokens_used": self.tokens_used,
            "elapsed": round(self.elapsed, 3),
            "error": self.error,
            "attempts": self.attempts,
        }

    def _safe_output(self) -> Any:
        if self.repaired_output is None:
            return None
        output_str = str(self.repaired_output)
        if len(output_str) > 5000:
            return output_str[:5000] + f"... [truncated, total {len(output_str)} chars]"
        return self.repaired_output


class RepairEngine:
    """Repairs execution results based on critique and verification feedback.
    
    Uses targeted repair strategies for specific failure modes, then falls
    back to LLM-based repair for complex issues. Supports multiple repair
    attempts with escalating strategies.
    """

    REPAIR_SYSTEM_PROMPT = """You are a repair engine for an AI agent. Given a task, its flawed result,
and specific issues identified by verification and critique, produce a corrected result.

You must respond in exactly this JSON format (no other text):
{
    "repaired_output": "the complete corrected result here",
    "repairs_made": ["description of fix 1", "description of fix 2"],
    "success": true
}

Guidelines:
- Address EVERY issue listed in the feedback
- Preserve the good parts of the original result
- Fix specific problems without overhauling the entire response
- If the result has contradictions, resolve them consistently
- If goals are missing, add the missing content
- If security/code issues exist, fix them directly
- "repaired_output" should be the COMPLETE final result, not a diff
- Only set success=false if the task is fundamentally impossible

Return ONLY the JSON. No markdown, no explanation."""

    def __init__(self, agent: Any, max_repair_attempts: int = 2):
        self._agent = agent
        self._max_repair_attempts = max_repair_attempts

    async def repair(
        self,
        task: str,
        result: Any,
        critique: CritiqueResult,
        verifications: List[VerificationResult],
        mission: Optional[MissionAnalysis] = None,
    ) -> RepairResult:
        start_time = time.monotonic()

        logger.info(f"Starting repair for task: {task[:60]}...")
        logger.info(
            f"  Critique score: {critique.score:.2f}, "
            f"issues: {len(critique.issues)}, improvements: {len(critique.improvements)}"
        )

        all_issues = self._collect_issues(verifications, critique)
        all_suggestions = self._collect_suggestions(verifications, critique)

        if not all_issues and not all_suggestions:
            logger.info("No actionable issues or suggestions found for repair")
            return RepairResult(
                success=True,
                repaired_output=result,
                repairs_made=["No repairs needed"],
                elapsed=time.monotonic() - start_time,
            )

        repaired_output = result
        repairs_made = []
        tokens_used = 0

        repaired_output, heuristic_repairs = self._apply_heuristic_repairs(
            repaired_output, all_issues, all_suggestions
        )
        repairs_made.extend(heuristic_repairs)

        heuristic_only_issues = {
            "SECURITY:", "Syntax error", "TODO", "incomplete",
            "No code issues", "No factual issues", "No security",
            "No logical issues", "All goals appear to be addressed",
            "No applicable verifiers",
        }
        non_heuristic_issues = [
            i for i in all_issues
            if not any(marker in i for marker in heuristic_only_issues)
        ]

        if not non_heuristic_issues and critique.score >= 0.7:
            elapsed = time.monotonic() - start_time
            logger.info(f"Heuristic repairs sufficient: {len(repairs_made)} repairs made")
            return RepairResult(
                success=True,
                repaired_output=repaired_output,
                repairs_made=repairs_made,
                tokens_used=tokens_used,
                elapsed=elapsed,
                attempts=1,
            )

        for attempt in range(1, self._max_repair_attempts + 1):
            logger.info(f"LLM repair attempt {attempt}/{self._max_repair_attempts}")

            llm_result = await self._llm_repair(
                task=task,
                result=repaired_output if attempt > 1 else result,
                issues=non_heuristic_issues if attempt == 1 else [],
                all_issues=all_issues,
                suggestions=all_suggestions,
                previous_repairs=repairs_made,
                mission=mission,
            )

            if llm_result.success:
                tokens_used += llm_result.tokens_used
                repairs_made.extend(llm_result.repairs_made)
                repaired_output = llm_result.repaired_output
                elapsed = time.monotonic() - start_time
                logger.info(f"LLM repair succeeded on attempt {attempt}: {len(llm_result.repairs_made)} repairs")
                return RepairResult(
                    success=True,
                    repaired_output=repaired_output,
                    repairs_made=repairs_made,
                    tokens_used=tokens_used,
                    elapsed=elapsed,
                    attempts=attempt,
                )

            tokens_used += llm_result.tokens_used
            if llm_result.repaired_output:
                repaired_output = llm_result.repaired_output
            repairs_made.extend(llm_result.repairs_made)
            logger.warning(f"LLM repair attempt {attempt} did not fully succeed")

        elapsed = time.monotonic() - start_time
        logger.warning(f"All repair attempts exhausted. Repairs made: {len(repairs_made)}")

        return RepairResult(
            success=len(repairs_made) > 0,
            repaired_output=repaired_output,
            repairs_made=repairs_made,
            tokens_used=tokens_used,
            elapsed=elapsed,
            attempts=self._max_repair_attempts,
            error="Maximum repair attempts reached; partial repairs may have been applied",
        )

    def _collect_issues(
        self,
        verifications: List[VerificationResult],
        critique: CritiqueResult,
    ) -> List[str]:
        issues = []
        noise_prefixes = [
            "No ", "No code", "No factual", "No security", "No logical",
            "All goals", "No applicable",
        ]

        for v in verifications:
            if not v.passed:
                for issue in v.issues:
                    if issue and not any(issue.startswith(p) for p in noise_prefixes):
                        issues.append(f"[{v.checked_by}] {issue}")

        for issue in critique.issues:
            if issue and not any(issue.startswith(p) for p in noise_prefixes):
                issues.append(f"[critic] {issue}")

        return list(dict.fromkeys(issues))

    def _collect_suggestions(
        self,
        verifications: List[VerificationResult],
        critique: CritiqueResult,
    ) -> List[str]:
        suggestions = []
        for v in verifications:
            for suggestion in v.suggestions:
                if suggestion:
                    suggestions.append(f"[{v.checked_by}] {suggestion}")

        for improvement in critique.improvements:
            if improvement:
                suggestions.append(f"[critic] {improvement}")

        return list(dict.fromkeys(suggestions))

    def _apply_heuristic_repairs(
        self,
        result: Any,
        issues: List[str],
        suggestions: List[str],
    ) -> tuple:
        if not isinstance(result, str):
            return result, []

        repaired = result
        repairs = []

        dangerous_replacements = [
            (r"(?m)^(\s*)eval\s*\(",
             r"\1# REMOVED: eval() - security risk\n\1# Use ast.literal_eval() instead\n\1"),
            (r"(?m)^(\s*)exec\s*\(",
             r"\1# REMOVED: exec() - security risk\n\1# Use subprocess or direct calls instead\n\1"),
        ]
        for pattern, replacement in dangerous_replacements:
            new_text, count = re.subn(pattern, replacement, repaired)
            if count > 0:
                repaired = new_text
                repairs.append(f"Removed {count} dangerous code pattern(s)")

        secret_patterns = [
            (r"(?i)(password|api_key|secret)\s*=\s*[\"'][^\"]{8,}[\"']",
             lambda m: f"{m.group(1)} = '***REDACTED***'"),
        ]
        for pattern, replacement in secret_patterns:
            new_text, count = re.subn(pattern, replacement, repaired)
            if count > 0:
                repaired = new_text
                repairs.append(f"Redacted {count} hardcoded secret(s)")

        new_text, count = re.subn(r"chmod\s+777", "chmod 755", repaired)
        if count > 0:
            repaired = new_text
            repairs.append(f"Reduced permissions from 777 to 755 ({count} occurrences)")

        new_text, count = re.subn(
            r"(?i)DROP\s+TABLE\s+(?!IF\s+EXISTS)(\w+)",
            r"DROP TABLE IF EXISTS \1",
            repaired,
        )
        if count > 0:
            repaired = new_text
            repairs.append(f"Added IF EXISTS to DROP TABLE statements ({count})")

        new_text, count = re.subn(
            r"(?i)DELETE\s+FROM\s+(\w+)\s*;\s*$",
            r"-- REMOVED: Unconditional DELETE on \1 (dangerous)\n-- Use DELETE FROM \1 WHERE <condition> instead",
            repaired,
            flags=re.MULTILINE,
        )
        if count > 0:
            repaired = new_text
            repairs.append(f"Removed unconditional DELETE statement(s) ({count})")

        return repaired, repairs

    async def _llm_repair(
        self,
        task: str,
        result: Any,
        issues: List[str],
        all_issues: List[str],
        suggestions: List[str],
        previous_repairs: List[str],
        mission: Optional[MissionAnalysis] = None,
    ) -> RepairResult:
        start_time = time.monotonic()

        result_str = str(result)[:6000] if result else "(empty result)"

        issues_text = "\n".join(f"- {issue}" for issue in all_issues) if all_issues else "- See suggestions below"
        suggestions_text = "\n".join(f"- {sug}" for sug in suggestions) if suggestions else "- General quality improvement needed"
        previous_text = "\n".join(f"- {r}" for r in previous_repairs) if previous_repairs else "(none)"

        constraints_text = ""
        if mission and mission.constraints:
            constraints_text = "\nConstraints to respect:\n" + "\n".join(f"- {c}" for c in mission.constraints)

        goals_text = ""
        if mission and mission.goals:
            goals_text = "\nGoals that must be met:\n" + "\n".join(f"- {g}" for g in mission.goals)

        user_message = (
            f"Task: {task}\n\n"
            f"Flawed result:\n{result_str}\n\n"
            f"Issues found:\n{issues_text}\n\n"
            f"Suggestions for improvement:\n{suggestions_text}\n\n"
            f"Previous repairs already applied:\n{previous_text}"
            f"{goals_text}{constraints_text}\n\n"
            f"Please provide the complete repaired result."
        )

        try:
            response = await self._agent.chat(message=user_message)
            content = response.get("content", "") if isinstance(response, dict) else str(response)
            tokens = response.get("metadata", {}).get("tokens_used", 0) if isinstance(response, dict) else 0
            if not tokens:
                tokens = response.get("metadata", {}).get("total_tokens", 0)
        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.error(f"LLM repair call failed: {e}")
            return RepairResult(
                success=False,
                repaired_output=result,
                tokens_used=0,
                elapsed=elapsed,
                attempts=1,
                error=f"LLM call failed: {e}",
            )

        elapsed = time.monotonic() - start_time
        parsed = self._parse_repair_response(content, result)
        parsed.tokens_used = tokens or len(content) // 4
        parsed.elapsed = elapsed
        parsed.attempts = 1

        return parsed

    def _parse_repair_response(self, raw_content: str, original_result: Any) -> RepairResult:
        json_str = None

        code_block_match = re.search(r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```", raw_content, re.DOTALL)
        if code_block_match:
            json_str = code_block_match.group(1)
        else:
            brace_start = raw_content.find("{")
            brace_end = raw_content.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                json_str = raw_content[brace_start:brace_end + 1]

        if json_str:
            try:
                data = json.loads(json_str)
                repaired_output = data.get("repaired_output", "")
                repairs_made = [str(r) for r in data.get("repairs_made", []) if r]
                success = bool(data.get("success", True))

                if repaired_output:
                    return RepairResult(
                        success=success,
                        repaired_output=repaired_output,
                        repairs_made=repairs_made if repairs_made else ["LLM repair applied"],
                    )
            except (json.JSONDecodeError, TypeError, ValueError) as e:
                logger.warning(f"Failed to parse repair JSON: {e}")

        logger.info("Using full LLM response as repaired output (JSON parse failed)")
        return RepairResult(
            success=True,
            repaired_output=raw_content,
            repairs_made=["LLM-based repair (full response used)"],
        )
