# Aion Hand - Verification Pipeline
# Every output passes through multiple verification stages.

import ast
import asyncio
import json
import logging
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .mission import MissionAnalysis

logger = logging.getLogger("aion_hand.pipeline")


@dataclass
class VerificationResult:
    """Result of a single verification check."""
    passed: bool = False
    confidence: float = 0.5
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    checked_by: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "confidence": round(self.confidence, 3),
            "issues": self.issues,
            "suggestions": self.suggestions,
            "checked_by": self.checked_by,
        }


class Verifier(ABC):
    """Abstract base class for all verifiers."""

    name: str = "base_verifier"

    @abstractmethod
    async def verify(self, task: str, result: Any, context: dict) -> VerificationResult:
        pass

    def is_applicable(self, task: str, result: Any, context: dict) -> bool:
        return True


class LogicVerifier(Verifier):
    name = "logic_verifier"

    async def verify(self, task: str, result: Any, context: dict) -> VerificationResult:
        issues = []
        suggestions = []
        result_str = str(result) if result else ""

        contradiction_patterns = [
            (r"(?i)however.{1,100}(?:also true|is true)", "Potential contradiction detected"),
            (r"(?i)but.{1,100}(?:the same|also|nevertheless)", "Check for contradictory statements"),
        ]
        for pattern, issue_msg in contradiction_patterns:
            if re.search(pattern, result_str):
                issues.append(issue_msg)

        vague_patterns = [
            (r"(?i)(?:might|could|perhaps|maybe|possibly)", 8,
             "High number of hedging words"),
        ]
        for pattern, threshold, msg in vague_patterns:
            matches = re.findall(pattern, result_str)
            if len(matches) > threshold:
                issues.append(f"{msg} (found {len(matches)} instances)")
                suggestions.append("Replace hedging language with definitive statements")

        if not issues:
            issues.append("No logical issues detected")

        passed = len([i for i in issues if "No logical" not in i]) == 0
        confidence = 0.9 if passed else max(0.3, 1.0 - len(issues) * 0.2)

        return VerificationResult(passed=passed, confidence=confidence, issues=issues, suggestions=suggestions, checked_by=self.name)


class FactChecker(Verifier):
    name = "fact_checker"

    FACT_CHECK_PROMPT = """Review the result and identify factual issues. Task: {task}

Result: {result}

Respond in JSON: {{"factual_issues": [], "suggestions": [], "confidence": 0.0}}

Return ONLY JSON."""

    def __init__(self, agent: Any | None = None):
        self._agent = agent

    def is_applicable(self, task: str, result: Any, context: dict) -> bool:
        if self._agent is None:
            return False
        return len(str(result or "")) > 100

    async def verify(self, task: str, result: Any, context: dict) -> VerificationResult:
        issues = []
        suggestions = []
        confidence = 0.7

        if self._agent is None:
            return VerificationResult(passed=True, confidence=0.5, issues=["No agent for fact checking"], checked_by=self.name)

        result_str = str(result)[:4000] if result else ""
        prompt = self.FACT_CHECK_PROMPT.format(task=task[:500], result=result_str)

        try:
            response = await self._agent.chat(message=prompt)
            content = response.get("content", "") if isinstance(response, dict) else str(response)
            json_match = re.search(r"\{.*\}", content, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                issues = data.get("factual_issues", [])
                suggestions = data.get("suggestions", [])
                raw_conf = data.get("confidence", 0.7)
                try:
                    confidence = max(0.0, min(1.0, float(raw_conf)))
                except (TypeError, ValueError):
                    confidence = 0.7
        except Exception as e:
            logger.warning(f"FactChecker LLM call failed: {e}")
            issues.append("Fact check could not be performed")

        if not issues:
            issues.append("No factual issues detected")

        has_real_issues = len([i for i in issues if "could not be performed" not in i and "No factual" not in i]) == 0
        return VerificationResult(passed=has_real_issues, confidence=confidence, issues=issues, suggestions=suggestions, checked_by=self.name)


class CodeVerifier(Verifier):
    name = "code_verifier"

    SECURITY_PATTERNS = [
        (r"(?i)eval\s*\(", "Use of eval() - code injection risk"),
        (r"(?i)exec\s*\(", "Use of exec() - code injection risk"),
        (r"(?i)subprocess\.call\s*\(.*shell\s*=\s*True", "shell=True with subprocess - command injection"),
        (r"(?i)os\.system\s*\(", "Use of os.system() - prefer subprocess"),
        (r"(?i)pickle\.loads?\s*\(", "Use of pickle - deserialization vulnerability"),
        (r"(?i)yaml\.load\s*\(.*Loader", "yaml.load without SafeLoader"),
        (r"(?i)password\s*=\s*[""][^""]+", "Hardcoded password detected"),
        (r"(?i)api_key\s*=\s*[""][^""]+", "Hardcoded API key detected"),
    ]

    def is_applicable(self, task: str, result: Any, context: dict) -> bool:
        result_str = str(result) if result else ""
        return any(ind in result_str for ind in ["def ", "class ", "import ", "from ", "return "])

    async def verify(self, task: str, result: Any, context: dict) -> VerificationResult:
        issues = []
        suggestions = []
        result_str = str(result) if result else ""

        blocks = re.findall(r'```(\w*)\n(.*?)\n```', result_str, re.DOTALL)
        code_blocks = [{"lang": m[0], "code": m[1]} for m in blocks]
        if not code_blocks and any(k in result_str for k in ["def ", "import "]):
            code_blocks = [{"lang": "python", "code": result_str}]

        if not code_blocks:
            return VerificationResult(passed=True, confidence=0.8, issues=["No code blocks found"], checked_by=self.name)

        for i, block in enumerate(code_blocks):
            code = block["code"]
            if block["lang"] in ("python", "py", ""):
                try:
                    ast.parse(code)
                except SyntaxError as e:
                    issues.append(f"Syntax error at line {e.lineno}: {e.msg}")
            for pattern, message in self.SECURITY_PATTERNS:
                if re.search(pattern, code):
                    issues.append(message)
            if len(code) > 200 and "TODO" in code:
                issues.append(f"Code block {i+1} contains TODO - may be incomplete")

        if not issues:
            issues.append("No code issues detected")

        passed = len([i for i in issues if "No code" not in i]) == 0
        confidence = 0.95 if passed else max(0.2, 1.0 - len(issues) * 0.15)
        return VerificationResult(passed=passed, confidence=confidence, issues=issues, suggestions=suggestions, checked_by=self.name)


class SecurityVerifier(Verifier):
    name = "security_verifier"

    DANGEROUS_PATTERNS = [
        (r"(?i)rm\s+(-[rfRF]+\s+)?/", "Recursive root deletion"),
        (r"(?i)mkfs\.", "Filesystem format command"),
        (r"(?i)dd\s+if=.*of=/dev/", "Direct disk write"),
        (r"(?i)chmod\s+777", "Overly permissive permissions"),
        (r"(?i)curl.*\|\s*(ba)?sh", "Remote script execution via pipe"),
        (r"(?i)DROP\s+TABLE", "SQL DROP TABLE"),
        (r"(?i)DELETE\s+FROM.*WHERE\s+1\s*=\s*1", "SQL delete-all"),
    ]

    SENSITIVE_PATTERNS = [
        (r"(?:AKIA|ABIA|ACCA|ASIA)[A-Z0-9]{16}", "AWS access key detected"),
        (r"(?:sk|pk)_[a-zA-Z0-9]{40,}", "Potential API secret key"),
        (r"(?i)BEGIN\s+(RSA|EC|DSA|OPENSSH)\s+PRIVATE", "Private key detected"),
    ]

    async def verify(self, task: str, result: Any, context: dict) -> VerificationResult:
        issues = []
        suggestions = []
        result_str = str(result) if result else ""

        for pattern, message in self.DANGEROUS_PATTERNS + self.SENSITIVE_PATTERNS:
            if re.search(pattern, result_str):
                issues.append(f"SECURITY: {message}")
                suggestions.append("Remove or replace this dangerous operation")

        if not issues:
            issues.append("No security violations detected")

        passed = len([i for i in issues if "SECURITY" in i]) == 0
        confidence = 0.95 if passed else 0.2
        return VerificationResult(passed=passed, confidence=confidence, issues=issues, suggestions=suggestions, checked_by=self.name)


class CompletenessVerifier(Verifier):
    name = "completeness_verifier"

    def __init__(self, agent: Any | None = None):
        self._agent = agent

    async def verify(self, task: str, result: Any, context: dict) -> VerificationResult:
        issues = []
        suggestions = []
        mission = context.get("mission")
        result_str = str(result) if result else ""

        if mission is None:
            return VerificationResult(passed=True, confidence=0.5, issues=["No mission analysis for completeness check"], checked_by=self.name)

        stop_words = {"the", "a", "an", "is", "are", "was", "were", "be", "to", "of", "in", "for", "on", "with", "at", "by", "from", "as", "and", "or", "but", "not", "all", "that", "this", "it", "make", "ensure", "provide", "create", "write", "have", "has", "had", "do", "does", "will", "would", "could", "should"}

        unaddressed = []
        for goal in mission.goals:
            keywords = [w for w in re.findall(r"[a-zA-Z]{3,}", goal.lower()) if w not in stop_words]
            if keywords:
                matches = sum(1 for kw in keywords if kw in result_str.lower())
                if matches / len(keywords) < 0.3 and len(goal) > 5:
                    unaddressed.append(goal)

        for goal in unaddressed:
            issues.append(f"Goal not fully addressed: {goal}")
            suggestions.append(f"Ensure the result covers: {goal}")

        passed = len(unaddressed) == 0
        if not issues:
            issues.append("All goals appear to be addressed")
            confidence = 0.9
        else:
            confidence = max(0.2, 1.0 - len(unaddressed) / max(len(mission.goals), 1))

        return VerificationResult(passed=passed, confidence=confidence, issues=issues, suggestions=suggestions, checked_by=self.name)


class VerificationPipeline:
    def __init__(self):
        self._verifiers: list[Verifier] = []

    def add_verifier(self, verifier: Verifier) -> None:
        if any(v.name == verifier.name for v in self._verifiers):
            self._verifiers = [v for v in self._verifiers if v.name != verifier.name]
        self._verifiers.append(verifier)
        logger.debug(f"Registered verifier: {verifier.name}")

    def remove_verifier(self, name: str) -> bool:
        before = len(self._verifiers)
        self._verifiers = [v for v in self._verifiers if v.name != name]
        return len(self._verifiers) < before

    def get_verifiers(self) -> list[str]:
        return [v.name for v in self._verifiers]

    async def verify(self, task: str, result: Any, mission: MissionAnalysis | None = None) -> list[VerificationResult]:
        context = {"mission": mission}
        applicable = [v for v in self._verifiers if v.is_applicable(task, result, context)]
        logger.info(f"Running {len(applicable)}/{len(self._verifiers)} verifiers")

        if not applicable:
            return [VerificationResult(passed=True, confidence=1.0, issues=["No applicable verifiers"], checked_by="none")]

        tasks = [v.verify(task, result, context) for v in applicable]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        verification_results = []
        for verifier, vresult in zip(applicable, results, strict=True):
            if isinstance(vresult, Exception):
                logger.warning(f"Verifier '{verifier.name}' raised: {vresult}")
                verification_results.append(VerificationResult(passed=False, confidence=0.0, issues=[f"Verifier error: {str(vresult)}"], checked_by=verifier.name))
            else:
                verification_results.append(vresult)

        passed_count = sum(1 for r in verification_results if r.passed)
        logger.info(f"Verification complete: {passed_count}/{len(verification_results)} passed")
        return verification_results
