"""Aion Hand Benchmark Runner"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from aion_core.benchmark.evaluator import BenchmarkEvaluator, TaskResult
from aion_core.benchmark.tasks import (
    BENCHMARK_TASKS,
    BenchmarkTask,
    Category,
    Difficulty,
)

logger = logging.getLogger(__name__)


@dataclass
class BenchmarkReport:
    """Aggregated report for a benchmark run."""
    run_id: str
    timestamp: str
    agent_version: str
    total_tasks: int
    passed: int
    failed: int
    overall_score: float
    avg_tokens: float
    avg_time: float
    category_scores: dict[str, float] = field(default_factory=dict)
    difficulty_scores: dict[str, float] = field(default_factory=dict)
    task_results: list[dict[str, Any]] = field(default_factory=list)
    comparison: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "agent_version": self.agent_version,
            "total_tasks": self.total_tasks,
            "passed": self.passed,
            "failed": self.failed,
            "overall_score": round(self.overall_score, 4),
            "avg_tokens": round(self.avg_tokens, 1),
            "avg_time": round(self.avg_time, 3),
            "category_scores": {k: round(v, 4) for k, v in self.category_scores.items()},
            "difficulty_scores": {k: round(v, 4) for k, v in self.difficulty_scores.items()},
            "task_results": self.task_results,
            "comparison": self.comparison,
        }


class BenchmarkRunner:
    def __init__(self, agent: Any, output_dir: str = "./benchmark_results", agent_version: str = "unknown") -> None:
        self.agent = agent
        self.output_dir = Path(output_dir)
        self.agent_version = agent_version
        self.evaluator = BenchmarkEvaluator()
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_tasks(
        self,
        task_ids: list[str] | None = None,
        categories: list[str] | None = None,
        difficulties: list[str] | None = None,
    ) -> list[BenchmarkTask]:
        """Filter BENCHMARK_TASKS by optional IDs, categories, and difficulties."""
        tasks = list(BENCHMARK_TASKS)
        if task_ids:
            ids_set = set(task_ids)
            tasks = [t for t in tasks if t.id in ids_set]
        if categories:
            cat_set = {c.lower() for c in categories}
            tasks = [
                t for t in tasks
                if (t.category.value if isinstance(t.category, Category) else str(t.category)).lower() in cat_set
            ]
        if difficulties:
            diff_set = {d.lower() for d in difficulties}
            tasks = [
                t for t in tasks
                if (t.difficulty.value if isinstance(t.difficulty, Difficulty) else str(t.difficulty)).lower() in diff_set
            ]
        return tasks

    async def run_suite(
        self,
        task_ids: list[str] | None = None,
        categories: list[str] | None = None,
        difficulties: list[str] | None = None,
    ) -> BenchmarkReport:
        tasks = self._resolve_tasks(task_ids, categories, difficulties)
        return await self._run_task_list(tasks)

    async def run_full_benchmark(self) -> BenchmarkReport:
        logger.info("Starting full benchmark with %d tasks", len(BENCHMARK_TASKS))
        return await self._run_task_list(list(BENCHMARK_TASKS))

    async def _run_task_list(self, tasks: list[BenchmarkTask]) -> BenchmarkReport:
        results: list[TaskResult] = []
        for task in tasks:
            try:
                result = await self.run_task(task)
            except Exception as exc:
                logger.error("Unhandled error on task %s: %s", task.id, exc)
                result = TaskResult(task_id=task.id, task_name=task.name, success=False, errors=[str(exc)])
            results.append(result)
        return self._compile_report(results, tasks)

    def _compile_report(self, results: list[TaskResult], tasks: list[BenchmarkTask]) -> BenchmarkReport:
        if not results:
            return BenchmarkReport(
                run_id=str(uuid.uuid4())[:8],
                timestamp=datetime.now(UTC).isoformat(),
                agent_version=self.agent_version,
                total_tasks=0, passed=0, failed=0,
                overall_score=0.0, avg_tokens=0.0, avg_time=0.0,
            )
        total = len(results)
        passed = sum(1 for r in results if r.success)
        failed = total - passed
        overall_score = sum(r.score for r in results) / total
        avg_tokens = sum(r.tokens_used for r in results) / total
        avg_time = sum(r.time_elapsed for r in results) / total
        task_map = {t.id: t for t in tasks}
        category_scores: dict[str, list[float]] = {}
        difficulty_scores: dict[str, list[float]] = {}
        for r in results:
            t = task_map.get(r.task_id)
            if t is None:
                continue
            cat = t.category.value if isinstance(t.category, Category) else str(t.category)
            diff = t.difficulty.value if isinstance(t.difficulty, Difficulty) else str(t.difficulty)
            category_scores.setdefault(cat, []).append(r.score)
            difficulty_scores.setdefault(diff, []).append(r.score)
        cat_avg = {k: sum(v) / len(v) for k, v in category_scores.items()}
        diff_avg = {k: sum(v) / len(v) for k, v in difficulty_scores.items()}
        return BenchmarkReport(
            run_id=str(uuid.uuid4())[:8],
            timestamp=datetime.now(UTC).isoformat(),
            agent_version=self.agent_version,
            total_tasks=total, passed=passed, failed=failed,
            overall_score=overall_score, avg_tokens=avg_tokens, avg_time=avg_time,
            category_scores=cat_avg, difficulty_scores=diff_avg,
            task_results=[r.to_dict() for r in results],
        )

    async def run_task(self, task: BenchmarkTask) -> TaskResult:
        logger.info("Running task %s: %s", task.id, task.name)
        start_time = time.monotonic()
        metadata: dict[str, Any] = {"tools_used": [], "turns_used": 0, "tokens_used": 0, "errors": []}
        agent_output = ""
        try:
            agent_output = await self._execute_agent(task, metadata)
        except Exception as exc:
            metadata["errors"].append(f"Agent execution error: {exc}")
            logger.error("Task %s agent error: %s", task.id, exc)
        elapsed = time.monotonic() - start_time
        metadata["time_elapsed"] = elapsed
        result = self.evaluator.evaluate(task, agent_output or "", metadata)
        result.time_elapsed = elapsed
        logger.info("Task %s complete: score=%.2f, time=%.2fs", task.id, result.score, elapsed)
        return result

    def compare_with_baseline(self, current: BenchmarkReport, baseline_path: str) -> dict[str, Any]:
        baseline_file = Path(baseline_path)
        if not baseline_file.exists():
            logger.warning("Baseline file not found: %s", baseline_path)
            return {"error": f"Baseline not found: {baseline_path}"}
        with open(baseline_file) as f:
            baseline = json.load(f)
        comparison: dict[str, Any] = {
            "baseline_run_id": baseline.get("run_id", "unknown"),
            "current_run_id": current.run_id,
            "overall_delta": round(current.overall_score - baseline.get("overall_score", 0), 4),
            "category_deltas": {},
            "difficulty_deltas": {},
            "verdict": "",
        }
        for cat, score in current.category_scores.items():
            base = baseline.get("category_scores", {}).get(cat, 0)
            comparison["category_deltas"][cat] = round(score - base, 4)
        for diff, score in current.difficulty_scores.items():
            base = baseline.get("difficulty_scores", {}).get(diff, 0)
            comparison["difficulty_deltas"][diff] = round(score - base, 4)
        delta = comparison["overall_delta"]
        if delta > 0.05:
            comparison["verdict"] = "IMPROVEMENT"
        elif delta < -0.05:
            comparison["verdict"] = "REGRESSION"
        else:
            comparison["verdict"] = "STABLE"
        current.comparison = comparison
        return comparison

    async def _execute_agent(self, task: BenchmarkTask, metadata: dict[str, Any]) -> str:
        prompt = task.task_prompt
        raw = await self.agent.run(prompt, max_turns=task.max_turns, max_tokens=task.max_tokens, timeout=task.timeout)
        if isinstance(raw, dict):
            output = str(raw.get("output", raw.get("text", "")))
            metadata["tools_used"] = raw.get("tools_used", raw.get("tool_calls", []))
            metadata["turns_used"] = raw.get("turns_used", raw.get("num_turns", 1))
            metadata["tokens_used"] = raw.get("tokens_used", raw.get("total_tokens", 0))
            if raw.get("error"):
                metadata["errors"].append(str(raw["error"]))
        else:
            output = str(raw)
            metadata["turns_used"] = 1
        tools = metadata.get("tools_used", [])
        if isinstance(tools, list):
            metadata["tools_used"] = [str(t) for t in tools]
        else:
            metadata["tools_used"] = []
        return output


__all__ = ["BenchmarkReport", "BenchmarkRunner"]
