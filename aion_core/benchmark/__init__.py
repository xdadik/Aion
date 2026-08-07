"""
Aion Hand Benchmark Engine

Proves Aion is better with numbers, not claims.

Usage:
    from aion_core.benchmark import (
        BenchmarkTask,
        BenchmarkRunner,
        BenchmarkEvaluator,
        BenchmarkReport,
        TaskResult,
        MetricsTracker,
        BENCHMARK_TASKS,
        get_tasks_by_category,
        get_tasks_by_difficulty,
    )

    runner = BenchmarkRunner(agent=agent, output_dir="./benchmark_results")
    report = await runner.run_full_benchmark()
    print(await runner.generate_report_markdown(report))
"""

from aion_core.benchmark.evaluator import (
    BenchmarkEvaluator,
    TaskResult,
)
from aion_core.benchmark.metrics import MetricsTracker
from aion_core.benchmark.runner import (
    BenchmarkReport,
    BenchmarkRunner,
)
from aion_core.benchmark.tasks import (
    BENCHMARK_TASKS,
    BenchmarkTask,
    get_tasks_by_category,
    get_tasks_by_difficulty,
)

__all__ = [
    # Task definitions
    "BenchmarkTask",
    "BENCHMARK_TASKS",
    "get_tasks_by_category",
    "get_tasks_by_difficulty",
    # Evaluation
    "TaskResult",
    "BenchmarkEvaluator",
    # Running
    "BenchmarkReport",
    "BenchmarkRunner",
    # Metrics
    "MetricsTracker",
]

__version__ = "1.0.0"
