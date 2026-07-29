# Aion Hand - Runtime Learning
# Feedback loop that records execution outcomes, extracts lessons,
# derives rules from failures, and applies them to future tasks.

import json
import os
import re
import hashlib
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional, Set
from datetime import datetime

logger = logging.getLogger("aion_hand.pipeline")


@dataclass
class TaskLesson:
    """A complete lesson learned from a single task execution."""
    task_hash: str = ""
    task_summary: str = ""
    task_keywords: List[str] = field(default_factory=list)
    mission_complexity: float = 0.5
    mission_capabilities: List[str] = field(default_factory=list)
    plan_node_count: int = 0
    plan_risk_level: str = "low"
    execution_success: bool = False
    execution_nodes_succeeded: int = 0
    execution_nodes_total: int = 0
    execution_tokens: int = 0
    execution_time: float = 0.0
    verifications_passed: int = 0
    verifications_total: int = 0
    critique_score: float = 0.5
    final_confidence: float = 0.5
    mistakes: List[str] = field(default_factory=list)
    learned_rules: List[str] = field(default_factory=list)
    was_repaired: bool = False
    repair_successful: bool = False
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TaskLesson":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class RuntimeLearning:
    """Records outcomes, extracts lessons and rules, and applies them to future tasks.
    
    Persists lessons to a JSON file for cross-session learning.
    Uses keyword-based similarity to retrieve relevant past lessons
    for any new task, enabling continuous improvement.
    """

    MAX_STORED_LESSONS = 500
    MAX_RULES_PER_TASK = 5
    KEYWORD_EXTRACT_MIN_LEN = 3

    def __init__(self, storage_path: Optional[str] = None):
        self._storage_path = storage_path or os.path.join(
            os.path.expanduser("~"), ".aion-hand", "data", "pipeline_lessons.json"
        )
        self._lessons: List[TaskLesson] = []
        self._rules: List[Dict[str, Any]] = []
        self._task_index: Dict[str, List[int]] = {}  # keyword -> [lesson indices]
        self._loaded = False

    @property
    def lessons_count(self) -> int:
        return len(self._lessons)

    @property
    def rules_count(self) -> int:
        return len(self._rules)

    def load(self) -> None:
        """Load lessons and rules from the persistence file."""
        if self._loaded:
            return

        self._loaded = True
        if not os.path.exists(self._storage_path):
            logger.info(f"No lesson storage found at {self._storage_path}")
            return

        try:
            with open(self._storage_path, "r") as f:
                data = json.load(f)

            lessons_data = data.get("lessons", [])
            self._lessons = [TaskLesson.from_dict(ld) for ld in lessons_data]
            self._rules = data.get("rules", [])
            self._rebuild_index()

            logger.info(
                f"Loaded {len(self._lessons)} lessons and {len(self._rules)} rules "
                f"from {self._storage_path}"
            )
        except (json.JSONDecodeError, OSError, KeyError) as e:
            logger.error(f"Failed to load lessons: {e}")
            self._lessons = []
            self._rules = []

    def _ensure_loaded(self) -> None:
        if not self._loaded:
            self.load()

    async def record_outcome(
        self,
        task: str,
        plan: Any,
        results: Dict[str, Any],
        verifications: List[Any],
        critique: Any,
        confidence: float,
    ) -> TaskLesson:
        """Record a complete execution outcome and extract lessons.
        
        Args:
            task: The original task string.
            plan: The ExecutionPlan that was used.
            results: Dict of node_id -> ExecutionResult.
            verifications: List of VerificationResult.
            critique: CritiqueResult.
            confidence: Final confidence score.
            
        Returns:
            The TaskLesson that was recorded.
        """
        self._ensure_loaded()

        task_hash = self._hash_task(task)
        keywords = self._extract_keywords(task)

        # Count execution metrics
        nodes_succeeded = 0
        nodes_total = len(results)
        total_tokens = 0
        total_time = 0.0
        for r in results.values():
            if hasattr(r, 'status') and r.status == "success":
                nodes_succeeded += 1
            if hasattr(r, 'tokens_used'):
                total_tokens += r.tokens_used
            if hasattr(r, 'elapsed'):
                total_time += r.elapsed

        # Count verification metrics
        verif_passed = 0
        verif_total = len(verifications)
        for v in verifications:
            if hasattr(v, 'passed') and v.passed:
                verif_passed += 1

        # Extract failures and mistakes
        mistakes = self._extract_mistakes(results, verifications, critique)

        # Generate rules from failures
        rules = self._generate_rules(task, mistakes, results, verifications, critique)

        # Check if repair happened
        was_repaired = False
        repair_successful = False
        for r in results.values():
            if hasattr(r, 'metadata') and r.metadata.get("is_repair"):
                was_repaired = True
                if hasattr(r, 'status') and r.status == "success":
                    repair_successful = True

        # Determine overall success
        execution_success = nodes_succeeded == nodes_total and nodes_total > 0

        lesson = TaskLesson(
            task_hash=task_hash,
            task_summary=task[:200],
            task_keywords=keywords,
            mission_complexity=getattr(plan, 'complexity', 0.5) if plan else 0.5,
            mission_capabilities=getattr(plan, 'capabilities_needed', []) if hasattr(plan, 'capabilities_needed') else [],
            plan_node_count=len(plan.nodes) if plan and hasattr(plan, 'nodes') else 0,
            plan_risk_level=getattr(plan, 'risk_level', 'low') if plan else 'low',
            execution_success=execution_success,
            execution_nodes_succeeded=nodes_succeeded,
            execution_nodes_total=nodes_total,
            execution_tokens=total_tokens,
            execution_time=total_time,
            verifications_passed=verif_passed,
            verifications_total=verif_total,
            critique_score=getattr(critique, 'score', 0.5) if critique else 0.5,
            final_confidence=confidence,
            mistakes=mistakes,
            learned_rules=rules,
            was_repaired=was_repaired,
            repair_successful=repair_successful,
            timestamp=datetime.utcnow().isoformat() + "Z",
        )

        self._lessons.append(lesson)

        # Add rules to global rule list
        for rule in rules:
            rule_entry = {
                "rule": rule,
                "task_hash": task_hash,
                "keywords": keywords,
                "confidence_boost": self._rule_confidence_boost(critique, confidence),
                "timestamp": lesson.timestamp,
            }
            self._rules.append(rule_entry)

        # Update keyword index
        for kw in keywords:
            if kw not in self._task_index:
                self._task_index[kw] = []
            self._task_index[kw].append(len(self._lessons) - 1)

        # Trim if exceeding max
        if len(self._lessons) > self.MAX_STORED_LESSONS:
            self._trim_lessons()

        # Persist to disk
        self._save()

        logger.info(
            f"Recorded lesson: success={execution_success}, confidence={confidence:.2f}, "
            f"rules={len(rules)}, mistakes={len(mistakes)}"
        )
        return lesson

    def get_relevant_lessons(self, task: str, max_lessons: int = 5) -> List[TaskLesson]:
        """Retrieve past lessons relevant to a new task.
        
        Uses keyword overlap to find similar past tasks and returns
        the most relevant lessons, prioritizing failed tasks (more
        informative than successes).
        
        Args:
            task: The new task string.
            max_lessons: Maximum number of lessons to return.
            
        Returns:
            List of relevant TaskLesson objects, ordered by relevance.
        """
        self._ensure_loaded()

        if not self._lessons:
            return []

        task_keywords = set(self._extract_keywords(task))
        if not task_keywords:
            return []

        # Score each lesson by keyword overlap
        scored = []
        for i, lesson in enumerate(self._lessons):
            lesson_keywords = set(lesson.task_keywords)
            if not lesson_keywords:
                continue

            overlap = len(task_keywords & lesson_keywords)
            if overlap == 0:
                continue

            # Jaccard-like similarity
            union = len(task_keywords | lesson_keywords)
            similarity = overlap / union if union > 0 else 0.0

            # Boost score for failures (more informative)
            boost = 1.5 if not lesson.execution_success else 1.0
            # Boost for low confidence (more lessons to learn)
            if lesson.final_confidence < 0.7:
                boost *= 1.3
            # Recency bonus (more recent = more relevant)
            recency = 1.0
            if lesson.timestamp:
                try:
                    lesson_time = datetime.fromisoformat(lesson.timestamp.replace("Z", "+00:00"))
                    age_hours = (datetime.utcnow() - lesson_time.replace(tzinfo=None)).total_seconds() / 3600
                    recency = 1.0 / (1.0 + age_hours / 168)  # Half-life ~ 1 week
                except (ValueError, OSError):
                    pass

            final_score = similarity * boost * recency
            scored.append((final_score, i, lesson))

        # Sort by relevance descending
        scored.sort(key=lambda x: x[0], reverse=True)

        return [lesson for _, _, lesson in scored[:max_lessons]]

    def get_applicable_rules(self, task: str, max_rules: int = 10) -> List[Dict[str, Any]]:
        """Get rules that apply to a given task.
        
        Args:
            task: The new task string.
            max_rules: Maximum rules to return.
            
        Returns:
            List of rule dictionaries with 'rule' and 'confidence_boost' keys.
        """
        self._ensure_loaded()

        if not self._rules:
            return []

        task_keywords = set(self._extract_keywords(task))
        if not task_keywords:
            return []

        matched_rules = []
        seen_rules: Set[str] = set()

        # Match by keyword
        for kw in task_keywords:
            if kw in self._task_index:
                for lesson_idx in self._task_index[kw]:
                    if lesson_idx < len(self._lessons):
                        lesson = self._lessons[lesson_idx]
                        for rule in lesson.learned_rules:
                            rule_key = rule.lower().strip()
                            if rule_key not in seen_rules:
                                seen_rules.add(rule_key)
                                matched_rules.append({
                                    "rule": rule,
                                    "source_task": lesson.task_summary,
                                    "source_success": lesson.execution_success,
                                    "confidence_boost": self._rule_confidence_boost_from_lesson(lesson),
                                })

        # Sort by confidence boost (higher = more impactful rule)
        matched_rules.sort(key=lambda r: r.get("confidence_boost", 0.0), reverse=True)

        return matched_rules[:max_rules]

    def _extract_mistakes(
        self,
        results: Dict[str, Any],
        verifications: List[Any],
        critique: Any,
    ) -> List[str]:
        """Extract specific mistakes from execution results."""
        mistakes = []

        # From execution results
        for node_id, r in results.items():
            if hasattr(r, 'status') and r.status == "failed":
                error = getattr(r, 'error', None) or "unknown error"
                mistakes.append(f"Node '{node_id}' failed: {str(error)[:100]}")
            if hasattr(r, 'status') and r.status == "timeout":
                mistakes.append(f"Node '{node_id}' timed out")
            if hasattr(r, 'retry_count') and r.retry_count > 0:
                mistakes.append(f"Node '{node_id}' needed {r.retry_count} retry/retries")

        # From verification results
        for v in verifications:
            if hasattr(v, 'passed') and not v.passed:
                if hasattr(v, 'issues'):
                    for issue in v.issues:
                        if issue and not any(
                            issue.startswith(p)
                            for p in ["No ", "No code", "No factual", "No security", "No logical"]
                        ):
                            verifier = getattr(v, 'checked_by', 'unknown')
                            mistakes.append(f"[{verifier}] {issue}")

        # From critique
        if critique and hasattr(critique, 'issues'):
            for issue in critique.issues:
                if issue and not any(issue.startswith(p) for p in ["No ", "[critic]"]):
                    mistakes.append(f"[critic] {issue}")

        return list(dict.fromkeys(mistakes))

    def _generate_rules(
        self,
        task: str,
        mistakes: List[str],
        results: Dict[str, Any],
        verifications: List[Any],
        critique: Any,
    ) -> List[str]:
        """Generate actionable rules from failures to prevent recurrence."""
        rules = []

        for mistake in mistakes:
            # Timeout -> increase timeout rule
            if "timed out" in mistake:
                node_id = mistake.split("'")[1] if "'" in mistake else "node"
                rules.append(f"Increase timeout for node type '{node_id}' by 50%")
                continue

            # Retry -> improve prompt rule
            if "retry" in mistake:
                rules.append("Consider breaking this type of task into smaller sub-steps")
                continue

            # Security
            if "SECURITY" in mistake or "security" in mistake:
                rules.append("Always run security checks before executing code or shell commands")
                continue

            # Syntax error
            if "Syntax error" in mistake:
                rules.append("Validate code syntax before including it in the response")
                continue

            # Incomplete
            if "not fully addressed" in mistake or "Goal not" in mistake:
                goal = mistake.split(":")[-1].strip() if ":" in mistake else "goal"
                rules.append(f"Ensure all goals are explicitly addressed, especially: {goal[:60]}")
                continue

            # Contradiction
            if "contradiction" in mistake:
                rules.append("Review the response for logical consistency before finalizing")
                continue

            # Node failure
            if "failed" in mistake:
                error_text = mistake.lower()
                if "permission" in error_text or "unauthorized" in error_text:
                    rules.append("Check permissions before attempting file or system operations")
                elif "not found" in error_text:
                    rules.append("Verify that referenced files, modules, or resources exist before using them")
                elif "connection" in error_text or "network" in error_text:
                    rules.append("Handle network errors gracefully with retries and fallbacks")
                else:
                    rules.append(f"Prevent the error type: {mistake[:80]}")
                continue

        if len(rules) > self.MAX_RULES_PER_TASK:
            rules = rules[:self.MAX_RULES_PER_TASK]

        return list(dict.fromkeys(rules))

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract meaningful keywords from task text."""
        stop_words = {
            "the", "a", "an", "is", "are", "was", "were", "be", "to", "of",
            "in", "for", "on", "with", "at", "by", "from", "as", "and", "or",
            "but", "not", "all", "that", "this", "it", "make", "ensure", "have",
            "has", "had", "do", "does", "will", "would", "could", "should",
            "can", "may", "need", "use", "using", "please", "how", "what",
            "why", "when", "where", "which", "who", "been", "being", "about",
        }
        words = re.findall(r"\b[a-zA-Z]{3,}\b", text.lower())
        keywords = [w for w in words if w not in stop_words]
        return list(dict.fromkeys(keywords))

    def _hash_task(self, task: str) -> str:
        """Create a stable hash for task deduplication and lookup."""
        normalized = re.sub(r"\s+", " ", task.strip().lower())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def _rule_confidence_boost(self, critique: Any, confidence: float) -> float:
        """Calculate how much confidence boost a rule should provide.
        
        Rules from low-confidence executions are more informative.
        """
        score = getattr(critique, 'score', 0.5) if critique else 0.5
        if score < 0.5:
            return 0.1
        elif score < 0.7:
            return 0.05
        return 0.02

    def _rule_confidence_boost_from_lesson(self, lesson: TaskLesson) -> float:
        """Calculate confidence boost from a stored lesson."""
        if not lesson.execution_success:
            return 0.1
        if lesson.final_confidence < 0.7:
            return 0.05
        return 0.02

    def _rebuild_index(self) -> None:
        """Rebuild the keyword-to-lesson index from loaded lessons."""
        self._task_index = {}
        for i, lesson in enumerate(self._lessons):
            for kw in lesson.task_keywords:
                if kw not in self._task_index:
                    self._task_index[kw] = []
                self._task_index[kw].append(i)

    def _trim_lessons(self) -> None:
        """Remove oldest lessons when exceeding storage limit."""
        if len(self._lessons) <= self.MAX_STORED_LESSONS:
            return

        # Keep the most recent lessons
        trim_count = len(self._lessons) - self.MAX_STORED_LESSONS
        removed_hashes = set(self._lessons[i].task_hash for i in range(trim_count))
        self._lessons = self._lessons[trim_count:]

        # Remove rules from trimmed lessons
        self._rules = [
            r for r in self._rules
            if r.get("task_hash") not in removed_hashes
        ]

        # Rebuild index
        self._rebuild_index()

        logger.info(f"Trimmed {trim_count} old lessons, {len(self._lessons)} remaining")

    def _save(self) -> None:
        """Persist lessons and rules to disk."""
        try:
            os.makedirs(os.path.dirname(self._storage_path), exist_ok=True)
            data = {
                "lessons": [l.to_dict() for l in self._lessons],
                "rules": self._rules,
                "saved_at": datetime.utcnow().isoformat() + "Z",
                "total_lessons": len(self._lessons),
                "total_rules": len(self._rules),
            }
            with open(self._storage_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        except OSError as e:
            logger.error(f"Failed to save lessons to {self._storage_path}: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics about stored lessons."""
        self._ensure_loaded()

        if not self._lessons:
            return {"total_lessons": 0, "total_rules": 0}

        successes = sum(1 for l in self._lessons if l.execution_success)
        failures = len(self._lessons) - successes
        avg_confidence = sum(l.final_confidence for l in self._lessons) / len(self._lessons)
        repaired = sum(1 for l in self._lessons if l.was_repaired)
        repair_success = sum(1 for l in self._lessons if l.was_repaired and l.repair_successful)

        return {
            "total_lessons": len(self._lessons),
            "total_rules": len(self._rules),
            "successes": successes,
            "failures": failures,
            "success_rate": round(successes / len(self._lessons), 3) if self._lessons else 0,
            "avg_confidence": round(avg_confidence, 3),
            "repaired": repaired,
            "repair_success_rate": round(repair_success / repaired, 3) if repaired else 0,
            "keyword_index_size": len(self._task_index),
        }
