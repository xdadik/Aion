# Aion Hand - Mission Analyzer
# First stage of the execution pipeline: deep task analysis before any planning.

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger("aion_hand.pipeline")


@dataclass
class MissionAnalysis:
    """Complete analysis of a user mission before execution."""
    intent: str = ""
    goals: list[str] = field(default_factory=list)
    constraints: list[str] = field(default_factory=list)
    risks: list[str] = field(default_factory=list)
    complexity: float = 0.5
    estimated_tokens: int = 2000
    estimated_time: int = 30
    capabilities_needed: list[str] = field(default_factory=list)
    raw_task: str = ""
    context_summary: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MissionAnalysis":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class MissionAnalyzer:
    """Deeply analyzes a user task before any planning occurs.

    Uses the LLM to extract intent, goals, constraints, risks, and
    estimate resource requirements. This analysis informs the planner
    so it can create an optimal execution graph.
    """

    ANALYSIS_SYSTEM_PROMPT = """You are a mission analysis engine. Given a user task and optional context,
you must provide a deep analysis in exactly this JSON format (no other text):

{
    "intent": "A one-sentence summary of what the user actually wants accomplished",
    "goals": ["goal1", "goal2"],
    "constraints": ["constraint1", "constraint2"],
    "risks": ["risk1", "risk2"],
    "complexity": 0.0,
    "estimated_tokens": 2000,
    "estimated_time": 30,
    "capabilities_needed": ["capability1", "capability2"]
}

Guidelines:
- "intent": What is the true underlying intent? Not just the surface request.
- "goals": Break the intent into 1-5 specific, measurable goals.
- "constraints": List any time, budget, safety, compatibility, or quality constraints mentioned or implied.
- "risks": Identify potential failure modes, ambiguity, missing information, or dangerous operations.
- "complexity": Float 0.0-1.0. 0.0=simple factual question, 0.3=moderate task, 0.6=complex multi-step, 0.8+=high risk or ambiguity.
- "estimated_tokens": Rough total tokens the execution might consume (input+output across all steps).
- "estimated_time": Rough seconds for the full pipeline to execute.
- "capabilities_needed": Which tools/abilities are needed. Choose from: ["llm", "web_search", "code_execution", "file_read", "file_write", "math", "image_generation", "data_analysis", "browser", "database", "api_call", "shell"]

Return ONLY the JSON. No markdown, no explanation."""

    def __init__(self, agent: Any):
        self._agent = agent

    async def analyze(self, task: str, context: dict | None = None) -> MissionAnalysis:
        """Perform deep mission analysis using the LLM.

        Args:
            task: The user's task/request string.
            context: Optional additional context (previous conversation, user preferences, etc.)

        Returns:
            A fully populated MissionAnalysis with intent, goals, constraints, risks,
            complexity estimates, and required capabilities.
        """
        context = context or {}
        logger.info(f"Analyzing mission: {task[:80]}{'...' if len(task) > 80 else ''}")

        # Build the user message with task and context
        context_str = ""
        if context:
            context_parts = []
            for key, value in context.items():
                if isinstance(value, (str, int, float, bool)):
                    context_parts.append(f"  {key}: {value}")
                elif isinstance(value, list) and len(value) < 20 or isinstance(value, dict) and len(value) < 20:
                    context_parts.append(f"  {key}: {json.dumps(value)}")
                else:
                    context_parts.append(f"  {key}: [{type(value).__name__}, len={len(value) if hasattr(value, '__len__') else '?'}]")
            if context_parts:
                context_str = "\n\nAdditional context:\n" + "\n".join(context_parts)

        user_message = f"Analyze this mission:\n\nTask: {task}{context_str}"

        # Use the agent's chat to call the LLM
        try:
            result = await self._agent.chat(
                message=user_message,
            )
            raw_content = result.get("content", "") if isinstance(result, dict) else str(result)
            tokens_used = result.get("metadata", {}).get("tokens_used", 0) if isinstance(result, dict) else 0
        except Exception as e:
            logger.warning(f"LLM analysis failed, falling back to heuristic: {e}")
            raw_content = ""
            tokens_used = 0

        # Try to parse the LLM response as JSON
        analysis = self._parse_llm_response(raw_content, task, context_str)
        analysis.raw_task = task
        analysis.context_summary = context_str.strip() if context_str else ""

        # Add tokens for the analysis step itself
        analysis.estimated_tokens += max(int(tokens_used), 500)

        logger.info(
            f"Mission analysis complete: complexity={analysis.complexity:.2f}, "
            f"goals={len(analysis.goals)}, risks={len(analysis.risks)}, "
            f"capabilities={analysis.capabilities_needed}, "
            f"est_tokens={analysis.estimated_tokens}, est_time={analysis.estimated_time}s"
        )

        return analysis

    def _parse_llm_response(
        self, raw_content: str, task: str, context_str: str
    ) -> MissionAnalysis:
        """Parse the LLM's JSON response into a MissionAnalysis.

        Falls back to heuristic analysis if parsing fails.
        """
        # Try to extract JSON from the response (it may be wrapped in markdown)
        json_str = self._extract_json(raw_content)

        if json_str:
            try:
                data = json.loads(json_str)
                return self._build_from_llm_data(data, task)
            except (json.JSONDecodeError, TypeError, KeyError) as e:
                logger.warning(f"Failed to parse LLM analysis JSON: {e}")

        # Fallback: heuristic analysis
        return self._heuristic_analysis(task, context_str)

    def _extract_json(self, text: str) -> str | None:
        """Extract JSON object from text that may contain markdown fences or extra text."""
        if not text:
            return None

        # Try to find JSON in code blocks first
        code_block_pattern = r"```(?:json)?\s*\n?(\{.*?\})\s*\n?```"
        matches = re.findall(code_block_pattern, text, re.DOTALL)
        if matches:
            return matches[0]

        # Try to find a raw JSON object
        brace_start = text.find("{")
        brace_end = text.rfind("}")
        if brace_start != -1 and brace_end > brace_start:
            return text[brace_start:brace_end + 1]

        return None

    def _build_from_llm_data(self, data: dict[str, Any], task: str) -> MissionAnalysis:
        """Build MissionAnalysis from parsed LLM JSON data."""
        analysis = MissionAnalysis(
            intent=data.get("intent", task[:100]),
            goals=self._ensure_list(data.get("goals")),
            constraints=self._ensure_list(data.get("constraints")),
            risks=self._ensure_list(data.get("risks")),
            complexity=self._clamp_float(data.get("complexity", 0.5), 0.0, 1.0),
            estimated_tokens=self._clamp_int(data.get("estimated_tokens", 2000), 200, 100000),
            estimated_time=self._clamp_int(data.get("estimated_time", 30), 5, 3600),
            capabilities_needed=self._ensure_list(data.get("capabilities_needed")),
        )

        # Validate and enrich
        if not analysis.intent:
            analysis.intent = task[:100]
        if not analysis.goals:
            analysis.goals = [task]

        return analysis

    def _heuristic_analysis(self, task: str, context_str: str) -> MissionAnalysis:
        """Fallback heuristic analysis when LLM parsing fails."""
        task_lower = task.lower()

        # Estimate complexity based on task features
        complexity = 0.3
        complexity_indicators = [
            (r"\b(write|create|build|implement|develop)\b", 0.2),
            (r"\b(analyze|investigate|research)\b", 0.15),
            (r"\b(multiple|several|all of)\b", 0.15),
            (r"\b(and then|after that|finally)\b", 0.1),
            (r"\b(debug|fix|troubleshoot)\b", 0.2),
            (r"\b(refactor|optimize|improve)\b", 0.25),
            (r"\b(secure|security|vulnerability)\b", 0.2),
            (r"\b(integrate|connect|api)\b", 0.15),
            (r"\b(test|verify|validate)\b", 0.1),
            (r"\b(deploy|production|release)\b", 0.2),
        ]
        for pattern, weight in complexity_indicators:
            if re.search(pattern, task_lower):
                complexity += weight
        complexity = min(complexity, 1.0)

        # Estimate tokens based on task length and complexity
        word_count = len(task.split())
        base_tokens = max(word_count * 4, 500)
        estimated_tokens = int(base_tokens * (1.0 + complexity * 3.0))

        # Estimate time
        estimated_time = max(10, int(estimated_tokens / 50) + 5)

        # Detect needed capabilities
        capabilities = ["llm"]  # Always need LLM
        capability_patterns = [
            (r"\b(search|find|look up|google)\b", "web_search"),
            (r"\b(code|program|script|function|class)\b", "code_execution"),
            (r"\b(read|open|load|parse)\s+(file|csv|json|xml)\b", "file_read"),
            (r"\b(write|save|create|generate)\s+(file|csv|json|report)\b", "file_write"),
            (r"\b(calculate|compute|math|statistics|average|sum)\b", "math"),
            (r"\b(image|picture|diagram|chart|plot)\b", "data_analysis"),
            (r"\b(browser|webpage|website|scrape)\b", "browser"),
            (r"\b(database|sql|query|table)\b", "database"),
            (r"\b(api|endpoint|request|http)\b", "api_call"),
            (r"\b(run|execute|command|terminal|shell)\b", "shell"),
            (r"\b(data|dataset|csv|excel|pandas)\b", "data_analysis"),
        ]
        for pattern, capability in capability_patterns:
            if re.search(pattern, task_lower):
                if capability not in capabilities:
                    capabilities.append(capability)

        # Extract basic goals from the task
        goals = self._extract_goals_heuristic(task)

        # Detect constraints
        constraints = []
        constraint_patterns = [
            (r"\b(within|under|less than|no more than)\s+(\d+)\s*(seconds?|minutes?|hours?)\b",
             lambda m: f"Time constraint: {m.group(0)}"),
            (r"\b(budget|cost|under)\s+\$?(\d+)",
             lambda m: f"Budget constraint: {m.group(0)}"),
            (r"\b(safe|safely|secure|security)\b",
             lambda m: "Safety requirement"),
            (r"\b(compatible with|works with)\s+(\w+)",
             lambda m: f"Compatibility: {m.group(0)}"),
        ]
        for pattern, formatter in constraint_patterns:
            match = re.search(pattern, task_lower)
            if match:
                constraints.append(formatter(match))

        # Detect risks
        risks = []
        risk_patterns = [
            (r"\b(delete|remove|drop|destroy)\b", "Destructive operation detected"),
            (r"\b(production|live|real data)\b", "Operates on production/live data"),
            (r"\b(overwrite|replace all)\b", "Potential data loss"),
            (r"\b(send|email|notify|post)\b", "External communication will occur"),
            (r"\b(install|download|fetch)\b", "External resource access required"),
        ]
        for pattern, risk_msg in risk_patterns:
            if re.search(pattern, task_lower):
                risks.append(risk_msg)

        logger.info(f"Heuristic analysis: complexity={complexity:.2f}, caps={capabilities}")

        return MissionAnalysis(
            intent=task[:200],
            goals=goals,
            constraints=constraints,
            risks=risks,
            complexity=complexity,
            estimated_tokens=estimated_tokens,
            estimated_time=estimated_time,
            capabilities_needed=capabilities,
        )

    def _extract_goals_heuristic(self, task: str) -> list[str]:
        """Extract goals from task text using simple heuristics."""
        goals = []

        # Split on common separators that indicate multiple goals
        separators = [r"\band then\b", r"\bafter that\b", r"\bthen\b", r"\bfurthermore\b",
                       r"\balso\b", r"\badditionally\b", r"\bfinally\b", r"\bnext\b"]
        parts = [task]
        for sep in separators:
            new_parts = []
            for part in parts:
                new_parts.extend(re.split(sep, part, flags=re.IGNORECASE))
            parts = new_parts

        # Clean up and deduplicate
        seen = set()
        for part in parts:
            goal = part.strip().strip(".,;:!").strip()
            if goal and len(goal) > 5 and goal not in seen:
                goals.append(goal)
                seen.add(goal)

        if not goals:
            goals = [task]

        return goals[:10]  # Cap at 10 goals

    @staticmethod
    def _ensure_list(value: Any) -> list[str]:
        """Ensure a value is a list of strings."""
        if value is None:
            return []
        if isinstance(value, list):
            return [str(item) for item in value if item is not None]
        return [str(value)]

    @staticmethod
    def _clamp_float(value: Any, min_val: float, max_val: float) -> float:
        """Clamp a value to a float range."""
        try:
            return max(min_val, min(max_val, float(value)))
        except (TypeError, ValueError):
            return (min_val + max_val) / 2.0

    @staticmethod
    def _clamp_int(value: Any, min_val: int, max_val: int) -> int:
        """Clamp a value to an integer range."""
        try:
            return max(min_val, min(max_val, int(value)))
        except (TypeError, ValueError):
            return (min_val + max_val) // 2
