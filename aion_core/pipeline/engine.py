# Aion Hand - Pipeline Engine
# Master orchestrator that runs the full autonomous execution pipeline:
# analyze -> plan -> execute -> verify -> critique -> [repair] -> confidence -> learn

import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional

from .mission import MissionAnalyzer, MissionAnalysis
from .planner import DynamicPlanner, ExecutionPlan
from .executor import ParallelExecutor, ExecutionResult
from .verification import (
    VerificationPipeline,
    LogicVerifier,
    CompletenessVerifier,
    SecurityVerifier,
    CodeVerifier,
    FactChecker,
    VerificationResult,
)
from .critic import Critic, CritiqueResult
from .repair import RepairEngine, RepairResult
from .confidence import ConfidenceEstimator
from .learning import RuntimeLearning, TaskLesson

logger = logging.getLogger("aion_hand.pipeline")


@dataclass
class PipelineResult:
    """Complete result from a pipeline execution."""
    success: bool = False
    output: Any = None
    confidence: float = 0.0
    mission: Optional[MissionAnalysis] = None
    plan: Optional[ExecutionPlan] = None
    execution_results: Dict[str, ExecutionResult] = field(default_factory=dict)
    verifications: List[VerificationResult] = field(default_factory=list)
    critique: Optional[CritiqueResult] = None
    repairs: Optional[RepairResult] = None
    tokens_total: int = 0
    time_total: float = 0.0
    lessons_learned: List[str] = field(default_factory=list)
    lessons_applied: List[str] = field(default_factory=list)
    stages_completed: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "output": self._safe_output(),
            "confidence": round(self.confidence, 4),
            "mission": self.mission.to_dict() if self.mission else None,
            "plan": {
                "node_count": len(self.plan.nodes) if self.plan else 0,
                "entry_node": self.plan.entry_node if self.plan else "",
                "risk_level": self.plan.risk_level if self.plan else "",
                "complexity": self.plan.complexity if self.plan else 0,
            } if self.plan else None,
            "execution_summary": self._execution_summary(),
            "verifications": [v.to_dict() for v in self.verifications],
            "critique": self.critique.to_dict() if self.critique else None,
            "repairs": self.repairs.to_dict() if self.repairs else None,
            "tokens_total": self.tokens_total,
            "time_total": round(self.time_total, 3),
            "lessons_learned": self.lessons_learned,
            "lessons_applied": self.lessons_applied,
            "stages_completed": self.stages_completed,
            "error": self.error,
        }

    def _safe_output(self) -> Any:
        if self.output is None:
            return None
        output_str = str(self.output)
        if len(output_str) > 10000:
            return output_str[:10000] + f"... [truncated, total {len(output_str)} chars]"
        return self.output

    def _execution_summary(self) -> Dict[str, Any]:
        if not self.execution_results:
            return {"total": 0}
        statuses = {}
        for r in self.execution_results.values():
            statuses[r.status] = statuses.get(r.status, 0) + 1
        return {
            "total": len(self.execution_results),
            "statuses": statuses,
            "total_tokens": sum(r.tokens_used for r in self.execution_results.values()),
            "total_time": round(sum(r.elapsed for r in self.execution_results.values()), 3),
        }


class PipelineEngine:
    """Master orchestrator for the full autonomous execution pipeline.

    The engine coordinates all pipeline stages:
    1. Retrieve relevant lessons from past executions
    2. Analyze the mission (intent, goals, constraints, risks, complexity)
    3. Create execution plan (linear, parallel, or full DAG)
    4. Execute the plan (with parallel workers where possible)
    5. Verify results (logic, completeness, security, code, facts)
    6. Critique results (quality assessment)
    7. If confidence < threshold: repair and re-verify
    8. Estimate final confidence
    9. Record outcome for learning
    10. Return PipelineResult with all metrics

    Usage:
        engine = PipelineEngine(agent, config)
        result = await engine.execute("Build a REST API with auth")
    """

    DEFAULT_CONFIDENCE_THRESHOLD = 0.7
    MAX_REPAIR_CYCLES = 2

    def __init__(
        self,
        agent: Any,
        config: Optional[Any] = None,
        confidence_threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
        max_workers: int = 5,
        learning_path: Optional[str] = None,
        enable_learning: bool = True,
        max_repair_cycles: int = MAX_REPAIR_CYCLES,
    ):
        self._agent = agent
        self._config = config
        self._confidence_threshold = confidence_threshold
        self._max_repair_cycles = max_repair_cycles
        self._enable_learning = enable_learning

        # Initialize all sub-components
        self._analyzer = MissionAnalyzer(agent)
        self._planner = DynamicPlanner(agent)
        self._executor = ParallelExecutor(agent, max_workers=max_workers)
        self._verifier = VerificationPipeline()
        self._critic = Critic(agent)
        self._repair_engine = RepairEngine(agent)
        self._confidence = ConfidenceEstimator()
        self._learning = RuntimeLearning(storage_path=learning_path)

        # Register default verifiers
        self._register_default_verifiers()

        # Load past lessons
        if self._enable_learning:
            self._learning.load()

        logger.info(
            f"PipelineEngine initialized: threshold={self._confidence_threshold}, "
            f"workers={max_workers}, learning={'on' if self._enable_learning else 'off'}, "
            f"verifiers={self._verifier.get_verifiers()}"
        )

    def _register_default_verifiers(self) -> None:
        """Register all built-in verifiers."""
        self._verifier.add_verifier(LogicVerifier())
        self._verifier.add_verifier(SecurityVerifier())
        self._verifier.add_verifier(CodeVerifier())
        self._verifier.add_verifier(CompletenessVerifier())
        self._verifier.add_verifier(FactChecker(agent=self._agent))

    def add_verifier(self, verifier: Any) -> None:
        """Add a custom verifier to the pipeline."""
        self._verifier.add_verifier(verifier)

    def remove_verifier(self, name: str) -> bool:
        """Remove a verifier by name."""
        return self._verifier.remove_verifier(name)

    # ----------------------------------------------------------------
    # Full Pipeline
    # ----------------------------------------------------------------

    async def execute(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """Run the FULL pipeline: analyze -> plan -> execute -> verify -> critique -> repair -> learn.

        Args:
            task: The user's task/request.
            context: Optional additional context.

        Returns:
            PipelineResult with complete execution trace and metrics.
        """
        pipeline_start = time.monotonic()
        result = PipelineResult()
        total_tokens = 0

        try:
            # Stage 1: Retrieve relevant lessons
            lessons_applied = []
            lessons = []
            rules = []
            if self._enable_learning:
                lessons = self._learning.get_relevant_lessons(task)
                rules = self._learning.get_applicable_rules(task)
                lessons_applied = [r["rule"] for r in rules[:5]]
                logger.info(f"Retrieved {len(lessons)} relevant lessons, {len(rules)} applicable rules")
            result.lessons_applied = lessons_applied
            result.stages_completed.append("lessons")

            # Stage 2: Analyze mission
            mission = await self._analyzer.analyze(task, context)
            result.mission = mission
            analysis_tokens = mission.estimated_tokens
            logger.info(f"Mission analyzed: complexity={mission.complexity:.2f}, goals={len(mission.goals)}")
            result.stages_completed.append("analyze")

            # Stage 3: Create plan (informed by lessons)
            plan = await self._planner.plan(mission, lessons=lessons)
            result.plan = plan
            logger.info(f"Plan created: {len(plan.nodes)} nodes, entry={plan.entry_node}")
            result.stages_completed.append("plan")

            # Stage 4: Execute plan
            execution_results = await self._executor.execute(plan)
            result.execution_results = execution_results
            exec_tokens = sum(r.tokens_used for r in execution_results.values())
            total_tokens += analysis_tokens + exec_tokens

            succeeded = sum(1 for r in execution_results.values() if r.status == "success")
            total = len(execution_results)
            logger.info(f"Execution complete: {succeeded}/{total} nodes succeeded, {exec_tokens} tokens")
            result.stages_completed.append("execute")

            # Extract the primary output from execution results
            primary_output = self._extract_primary_output(plan, execution_results)

            # Stage 5: Verify results
            verifications = await self._verifier.verify(task, primary_output, mission=mission)
            result.verifications = verifications
            verif_passed = sum(1 for v in verifications if v.passed)
            logger.info(f"Verification complete: {verif_passed}/{len(verifications)} passed")
            result.stages_completed.append("verify")

            # Stage 6: Critique results
            critique = await self._critic.critique(task, primary_output, verifications)
            result.critique = critique
            logger.info(f"Critique complete: score={critique.score:.2f}, should_repair={critique.should_repair}")
            result.stages_completed.append("critique")

            # Stage 7: Estimate confidence and decide on repair
            confidence = self._confidence.estimate(
                result=primary_output,
                verifications=verifications,
                critique=critique,
                execution_results=execution_results,
            )
            logger.info(f"Initial confidence: {confidence:.3f}")

            # Stage 7b: Repair loop if confidence is below threshold
            current_output = primary_output
            current_verifications = verifications
            current_critique = critique
            repair_result = None

            for cycle in range(1, self._max_repair_cycles + 1):
                if confidence >= self._confidence_threshold and not critique.should_repair:
                    logger.info(f"Confidence {confidence:.3f} >= threshold {self._confidence_threshold}, skipping repair")
                    break

                logger.info(f"Repair cycle {cycle}/{self._max_repair_cycles} (confidence={confidence:.3f})")
                repair_result = await self._repair_engine.repair(
                    task=task,
                    result=current_output,
                    critique=current_critique,
                    verifications=current_verifications,
                    mission=mission,
                )
                result.repairs = repair_result
                total_tokens += repair_result.tokens_used

                if not repair_result.success or repair_result.repaired_output is None:
                    logger.warning(f"Repair cycle {cycle} failed, keeping current output")
                    break

                current_output = repair_result.repaired_output
                logger.info(f"Repair cycle {cycle} applied: {len(repair_result.repairs_made)} repairs")

                # Re-verify the repaired output
                current_verifications = await self._verifier.verify(task, current_output, mission=mission)
                result.verifications = current_verifications
                reverify_passed = sum(1 for v in current_verifications if v.passed)
                logger.info(f"Re-verification: {reverify_passed}/{len(current_verifications)} passed")

                # Re-critique
                current_critique = await self._critic.critique(task, current_output, current_verifications)
                result.critique = current_critique
                logger.info(f"Re-critique: score={current_critique.score:.2f}")

                # Re-estimate confidence
                confidence = self._confidence.estimate(
                    result=current_output,
                    verifications=current_verifications,
                    critique=current_critique,
                    execution_results=execution_results,
                )
                logger.info(f"Post-repair confidence: {confidence:.3f}")

                result.stages_completed.append(f"repair_{cycle}")

            # Stage 8: Final confidence
            result.confidence = confidence
            result.output = current_output
            result.tokens_total = total_tokens
            result.time_total = time.monotonic() - pipeline_start

            # Determine success
            all_exec_succeeded = all(
                r.status == "success" for r in execution_results.values()
            ) if execution_results else True
            result.success = all_exec_succeeded and confidence >= 0.5

            result.stages_completed.append("confidence")

            # Stage 9: Record outcome for learning
            if self._enable_learning:
                try:
                    lesson = await self._learning.record_outcome(
                        task=task,
                        plan=plan,
                        results=execution_results,
                        verifications=current_verifications,
                        critique=current_critique,
                        confidence=confidence,
                    )
                    result.lessons_learned = lesson.learned_rules
                    logger.info(f"Recorded lesson: {len(lesson.learned_rules)} rules learned")
                except Exception as e:
                    logger.error(f"Failed to record lesson: {e}")

            result.stages_completed.append("learn")

        except Exception as e:
            logger.error(f"Pipeline execution failed: {e}", exc_info=True)
            result.error = str(e)
            result.time_total = time.monotonic() - pipeline_start
            result.stages_completed.append("error")

        logger.info(
            f"Pipeline complete: success={result.success}, "
            f"confidence={result.confidence:.3f}, "
            f"tokens={result.tokens_total}, "
            f"time={result.time_total:.2f}s, "
            f"stages={result.stages_completed}"
        )

        return result

    # ----------------------------------------------------------------
    # Simple (light) pipeline
    # ----------------------------------------------------------------

    async def execute_simple(
        self,
        task: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> PipelineResult:
        """Light pipeline for simple tasks: chat -> verify -> return.

        Skips full planning and DAG execution. Directly calls agent.chat(),
        runs a quick verification, and returns. Much faster for trivial tasks.

        Args:
            task: The user's task.
            context: Optional additional context.

        Returns:
            PipelineResult with the simple execution result.
        """
        pipeline_start = time.monotonic()
        result = PipelineResult()

        try:
            # Light analysis
            mission = MissionAnalysis(
                intent=task[:200],
                goals=[task],
                complexity=0.2,
                estimated_tokens=1000,
                estimated_time=15,
                capabilities_needed=["llm"],
                raw_task=task,
            )
            result.mission = mission
            result.stages_completed.append("analyze")

            # Direct execution
            exec_response = await self._agent.chat(message=task)
            content = exec_response.get("content", "") if isinstance(exec_response, dict) else str(exec_response)
            tokens = exec_response.get("metadata", {}).get("tokens_used", 0) if isinstance(exec_response, dict) else 0
            if not tokens:
                tokens = exec_response.get("metadata", {}).get("total_tokens", len(content) // 4)
            result.tokens_total = tokens

            # Quick verification
            verifications = await self._verifier.verify(task, content, mission=mission)
            result.verifications = verifications
            result.stages_completed.append("verify")

            # Quick critique
            critique = await self._critic.critique(task, content, verifications)
            result.critique = critique
            result.stages_completed.append("critique")

            # Confidence
            confidence = self._confidence.estimate(
                result=content,
                verifications=verifications,
                critique=critique,
            )
            result.confidence = confidence
            result.output = content
            result.success = confidence >= 0.5
            result.time_total = time.monotonic() - pipeline_start

            result.stages_completed.append("confidence")

            # Record for learning
            if self._enable_learning:
                try:
                    fake_results = {
                        "simple": ExecutionResult(
                            node_id="simple",
                            status="success" if result.success else "failed",
                            output=content,
                            tokens_used=tokens,
                            elapsed=result.time_total,
                        )
                    }
                    await self._learning.record_outcome(
                        task=task,
                        plan=None,
                        results=fake_results,
                        verifications=verifications,
                        critique=critique,
                        confidence=confidence,
                    )
                    result.stages_completed.append("learn")
                except Exception as e:
                    logger.error(f"Failed to record simple lesson: {e}")

        except Exception as e:
            logger.error(f"Simple pipeline failed: {e}", exc_info=True)
            result.error = str(e)
            result.time_total = time.monotonic() - pipeline_start
            result.stages_completed.append("error")

        return result

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------

    def _extract_primary_output(
        self,
        plan: ExecutionPlan,
        results: Dict[str, ExecutionResult],
    ) -> Any:
        """Extract the primary output from execution results.

        Strategy:
        1. Look for the last successful non-verify node (likely the main result)
        2. If there's a merge node, use its output
        3. Fall back to the entry node's output
        4. Last resort: concatenate all successful outputs
        """
        if not results:
            return None

        # Find terminal (leaf) nodes
        all_deps = set()
        for node in plan.nodes.values():
            all_deps.update(node.dependencies)
        terminal = [
            nid for nid in plan.nodes
            if nid not in all_deps
        ]

        # Among terminal nodes, prefer non-verify, then merge, then any
        for node_id in terminal:
            node = plan.nodes.get(node_id)
            r = results.get(node_id)
            if r and r.status == "success" and node:
                if node.node_type == "merge":
                    return r.output

        for node_id in terminal:
            r = results.get(node_id)
            if r and r.status == "success":
                node = plan.nodes.get(node_id)
                if node and node.node_type != "verify":
                    return r.output

        # Fallback: any successful non-verify node
        for node_id, r in results.items():
            node = plan.nodes.get(node_id)
            if r.status == "success" and node and node.node_type != "verify":
                return r.output

        # Last resort: concatenate all successful outputs
        outputs = []
        for node_id, r in results.items():
            if r.status == "success" and r.output:
                outputs.append(str(r.output))
        return "\n\n".join(outputs) if outputs else None

    def get_stats(self) -> Dict[str, Any]:
        """Get pipeline statistics including learning stats."""
        stats = {
            "confidence_threshold": self._confidence_threshold,
            "max_workers": self._executor._max_workers,
            "verifiers": self._verifier.get_verifiers(),
            "learning_enabled": self._enable_learning,
        }
        if self._enable_learning:
            stats["learning"] = self._learning.get_stats()
        return stats
