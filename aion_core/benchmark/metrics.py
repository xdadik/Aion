"""Aion Hand Benchmark Metrics Tracker"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from aion_core.benchmark.runner import BenchmarkReport

logger = logging.getLogger(__name__)


class MetricsTracker:
    """Persists benchmark results over time and computes trends."""

    def __init__(self, storage_dir: str = "./benchmark_results") -> None:
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._metrics_file = self.storage_dir / "metrics_history.json"
        self._history: list[dict[str, Any]] = self._load()

    def _load(self) -> list[dict[str, Any]]:
        if self._metrics_file.exists():
            try:
                data = json.loads(self._metrics_file.read_text())
                if isinstance(data, list):
                    return data
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to load metrics: %s", exc)
        return []

    def _save(self) -> None:
        self._metrics_file.write_text(json.dumps(self._history, indent=2, default=str))

    def record_run(self, report: BenchmarkReport) -> dict[str, Any]:
        entry = {
            "run_id": report.run_id,
            "timestamp": report.timestamp,
            "agent_version": report.agent_version,
            "total_tasks": report.total_tasks,
            "passed": report.passed,
            "failed": report.failed,
            "overall_score": report.overall_score,
            "avg_tokens": report.avg_tokens,
            "avg_time": report.avg_time,
            "category_scores": report.category_scores,
            "difficulty_scores": report.difficulty_scores,
        }
        self._history.append(entry)
        self._save()
        logger.info("Recorded run %s (score=%.2f)", report.run_id, report.overall_score)
        return entry

    def get_trend(self, metric_name: str, days: int = 30) -> list[dict[str, Any]]:
        cutoff = datetime.now(UTC) - timedelta(days=days)
        trend = []
        for entry in self._history:
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                if ts.replace(tzinfo=UTC) >= cutoff:
                    trend.append(
                        {
                            "timestamp": entry["timestamp"],
                            "value": entry.get(metric_name, 0.0),
                        }
                    )
            except (KeyError, ValueError):
                continue
        return trend

    def get_best_score(self) -> dict[str, Any] | None:
        if not self._history:
            return None
        best = max(self._history, key=lambda e: e.get("overall_score", 0.0))
        return best

    def get_summary(self) -> dict[str, Any]:
        if not self._history:
            return {"total_runs": 0, "message": "No benchmark runs recorded yet."}
        scores = [e["overall_score"] for e in self._history if "overall_score" in e]
        return {
            "total_runs": len(self._history),
            "best_score": max(scores) if scores else 0.0,
            "worst_score": min(scores) if scores else 0.0,
            "avg_score": sum(scores) / len(scores) if scores else 0.0,
            "latest_run": self._history[-1] if self._history else None,
            "improvement_from_first": (
                round(scores[-1] - scores[0], 4) if len(scores) >= 2 else 0.0
            ),
        }


__all__ = ["MetricsTracker"]
