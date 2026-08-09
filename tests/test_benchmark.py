"""Benchmark harness smoke tests.

Verifies that the benchmark runner, evaluator, and task suite are
structurally sound and can execute end-to-end with a mock agent.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aion_core.benchmark.evaluator import BenchmarkEvaluator
from aion_core.benchmark.runner import BenchmarkReport, BenchmarkRunner
from aion_core.benchmark.tasks import (
    BENCHMARK_TASKS,
    BenchmarkTask,
    Category,
    Difficulty,
)


class TestBenchmarkTaskSuite:
    """Verify the built-in task suite is well-formed."""

    def test_tasks_are_non_empty(self):
        assert (
            len(BENCHMARK_TASKS) > 0
        ), "Benchmark suite should ship with at least one task"

    def test_each_task_has_unique_id(self):
        ids = [t.id for t in BENCHMARK_TASKS]
        assert len(ids) == len(set(ids)), "Duplicate task IDs"

    def test_each_task_has_required_fields(self):
        for t in BENCHMARK_TASKS:
            assert t.id, f"Task missing id: {t}"
            assert t.name, f"Task {t.id} missing name"
            assert t.task_prompt, f"Task {t.id} missing prompt"
            assert isinstance(
                t.category, Category
            ), f"Task {t.id} category not Category"
            assert isinstance(
                t.difficulty, Difficulty
            ), f"Task {t.id} difficulty not Difficulty"
            assert t.max_turns > 0, f"Task {t.id} max_turns must be > 0"

    def test_categories_represented(self):
        cats = {t.category for t in BENCHMARK_TASKS}
        # We don't require all categories, but we want at least 2
        assert len(cats) >= 2, f"Only {len(cats)} categories represented"

    def test_difficulties_represented(self):
        diffs = {t.difficulty for t in BENCHMARK_TASKS}
        assert len(diffs) >= 2, f"Only {len(diffs)} difficulties represented"


class TestBenchmarkEvaluator:
    """Evaluator scoring logic."""

    def test_evaluator_instantiable(self):
        ev = BenchmarkEvaluator()
        assert ev is not None

    def test_evaluate_empty_output(self):
        ev = BenchmarkEvaluator()
        task = BENCHMARK_TASKS[0]
        result = ev.evaluate(
            task,
            "",
            {"tools_used": [], "turns_used": 0, "tokens_used": 0, "errors": []},
        )
        assert result is not None
        assert (
            result.success is False or result.score <= 0.5
        )  # empty output shouldn't pass

    def test_evaluate_with_relevant_output(self):
        ev = BenchmarkEvaluator()
        task = BENCHMARK_TASKS[0]
        # Produce an output that mentions keywords from the task
        output = f"Completed: {task.name}. " + ("detail " * 50)
        result = ev.evaluate(
            task,
            output,
            {"tools_used": [], "turns_used": 1, "tokens_used": 100, "errors": []},
        )
        assert result is not None
        assert 0.0 <= result.score <= 1.0


class TestBenchmarkRunner:
    """Runner end-to-end with a mock agent."""

    def _make_mock_agent(self, output: str = "Done.") -> MagicMock:
        agent = MagicMock()
        agent.run = AsyncMock(
            return_value={
                "output": output,
                "tools_used": ["web_search"],
                "turns_used": 2,
                "tokens_used": 250,
            }
        )
        return agent

    def test_runner_instantiable(self, tmp_path):
        agent = self._make_mock_agent()
        runner = BenchmarkRunner(
            agent=agent, output_dir=str(tmp_path), agent_version="test-0.1"
        )
        assert runner is not None

    @pytest.mark.asyncio
    async def test_run_task_completes(self, tmp_path):
        agent = self._make_mock_agent("Hello world from the agent.")
        runner = BenchmarkRunner(
            agent=agent, output_dir=str(tmp_path), agent_version="test-0.1"
        )
        task = BENCHMARK_TASKS[0]
        result = await runner.run_task(task)
        assert result is not None
        assert result.task_id == task.id
        assert result.time_elapsed >= 0.0

    @pytest.mark.asyncio
    async def test_run_full_benchmark_produces_report(self, tmp_path):
        agent = self._make_mock_agent("Generic successful output. ")
        runner = BenchmarkRunner(
            agent=agent, output_dir=str(tmp_path), agent_version="test-0.1"
        )
        report = await runner.run_full_benchmark()
        assert isinstance(report, BenchmarkReport)
        assert report.total_tasks == len(BENCHMARK_TASKS)
        assert report.passed + report.failed == report.total_tasks
        assert 0.0 <= report.overall_score <= 1.0
        assert report.avg_time >= 0.0

    @pytest.mark.asyncio
    async def test_report_serialises_to_dict(self, tmp_path):
        agent = self._make_mock_agent()
        runner = BenchmarkRunner(
            agent=agent, output_dir=str(tmp_path), agent_version="test-0.1"
        )
        report = await runner.run_full_benchmark()
        d = report.to_dict()
        assert "run_id" in d
        assert "overall_score" in d
        assert "task_results" in d
        assert isinstance(d["task_results"], list)

    @pytest.mark.asyncio
    async def test_run_subset_by_category(self, tmp_path):
        agent = self._make_mock_agent()
        runner = BenchmarkRunner(
            agent=agent, output_dir=str(tmp_path), agent_version="test-0.1"
        )
        # Pick the first category present in the suite
        first_cat = BENCHMARK_TASKS[0].category.value
        report = await runner.run_suite(categories=[first_cat])
        assert report.total_tasks >= 1
        # All tasks should belong to the requested category
        for r in report.task_results:
            task = next(t for t in BENCHMARK_TASKS if t.id == r["task_id"])
            assert task.category.value == first_cat
