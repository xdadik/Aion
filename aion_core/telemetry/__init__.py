"""Aion Hand Telemetry — metrics, tracing, observability.

Lightweight, stdlib-only observability for the Aion agent framework.
No external dependencies (no OpenTelemetry, no Prometheus client).
Exports JSON-formatted metrics + traces that can be shipped to any
backend (Prometheus pushgateway, Datadog, Honeycomb, etc.).

Components:
    - MetricsRegistry — counters, gauges, histograms
    - TraceSpan — distributed tracing (start/end, parent/child)
    - EventLog — structured event log (JSON lines)
    - TelemetryExporter — dump everything to JSON for external shipping

Usage:
    from aion_core.telemetry import get_metrics, get_tracer

    metrics = get_metrics()
    metrics.increment('agent.chat.turns', tags={'persona': 'coder'})
    metrics.observe('agent.chat.latency_seconds', 0.42)

    tracer = get_tracer()
    span = tracer.start_span('agent.chat', tags={'user_id': '42'})
    # ... do work ...
    span.end()
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, UTC
from pathlib import Path
from typing import Any

logger = logging.getLogger("aion_hand.telemetry")


# ---------------------------------------------------------------------------
# Counter / Gauge / Histogram
# ---------------------------------------------------------------------------

@dataclass
class Counter:
    """A monotonically increasing counter."""
    name: str
    value: float = 0.0
    tags: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def inc(self, amount: float = 1.0) -> None:
        if amount < 0:
            raise ValueError("Counter can only increase")
        self.value += amount

    def to_dict(self) -> dict[str, Any]:
        return {"type": "counter", "name": self.name, "value": self.value, "tags": dict(self.tags)}


@dataclass
class Gauge:
    """A gauge that can go up or down."""
    name: str
    value: float = 0.0
    tags: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def set(self, value: float) -> None:
        self.value = value

    def inc(self, amount: float = 1.0) -> None:
        self.value += amount

    def dec(self, amount: float = 1.0) -> None:
        self.value -= amount

    def to_dict(self) -> dict[str, Any]:
        return {"type": "gauge", "name": self.name, "value": self.value, "tags": dict(self.tags)}


@dataclass
class Histogram:
    """A histogram — observes values and tracks count + sum + buckets."""
    name: str
    count: int = 0
    sum: float = 0.0
    buckets: tuple[float, ...] = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
    bucket_counts: list[int] = field(default_factory=list)
    tags: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.bucket_counts:
            self.bucket_counts = [0] * len(self.buckets)

    def observe(self, value: float) -> None:
        self.count += 1
        self.sum += value
        for i, bound in enumerate(self.buckets):
            if value <= bound:
                self.bucket_counts[i] += 1

    @property
    def avg(self) -> float:
        return self.sum / self.count if self.count > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "histogram",
            "name": self.name,
            "count": self.count,
            "sum": round(self.sum, 6),
            "avg": round(self.avg, 6),
            "buckets": dict(zip([str(b) for b in self.buckets], self.bucket_counts)),
            "tags": dict(self.tags),
        }


# ---------------------------------------------------------------------------
# Trace span
# ---------------------------------------------------------------------------

@dataclass
class TraceSpan:
    """A single trace span."""
    span_id: str
    trace_id: str
    parent_span_id: str | None
    name: str
    start_time: float
    end_time: float | None = None
    tags: dict[str, Any] = field(default_factory=dict)
    events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        if self.end_time is None:
            return 0.0
        return self.end_time - self.start_time

    def set_tag(self, key: str, value: Any) -> None:
        self.tags[key] = value

    def add_event(self, name: str, **attrs: Any) -> None:
        self.events.append({
            "name": name,
            "timestamp": datetime.now(UTC).isoformat(),
            "attributes": attrs,
        })

    def end(self) -> None:
        if self.end_time is None:
            self.end_time = time.time()

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_span_id": self.parent_span_id,
            "name": self.name,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_seconds": round(self.duration_seconds, 6),
            "tags": self.tags,
            "events": self.events,
        }


# ---------------------------------------------------------------------------
# Tracer
# ---------------------------------------------------------------------------

class Tracer:
    """Distributed tracing — start_span returns a context-managed span."""

    def __init__(self) -> None:
        self._spans: list[TraceSpan] = []
        self._lock = threading.Lock()

    def start_span(
        self,
        name: str,
        *,
        parent: TraceSpan | None = None,
        tags: dict[str, Any] | None = None,
    ) -> TraceSpan:
        trace_id = parent.trace_id if parent else uuid.uuid4().hex
        span = TraceSpan(
            span_id=uuid.uuid4().hex[:16],
            trace_id=trace_id,
            parent_span_id=parent.span_id if parent else None,
            name=name,
            start_time=time.time(),
            tags=tags or {},
        )
        with self._lock:
            self._spans.append(span)
        return span

    @property
    def spans(self) -> list[TraceSpan]:
        return list(self._spans)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()

    def to_dict(self) -> list[dict[str, Any]]:
        return [s.to_dict() for s in self._spans]


# ---------------------------------------------------------------------------
# Metrics registry
# ---------------------------------------------------------------------------

class MetricsRegistry:
    """Registry of counters, gauges, and histograms."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], Counter] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], Gauge] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], Histogram] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(name: str, tags: dict[str, str] | None) -> tuple[str, tuple[tuple[str, str], ...]]:
        return (name, tuple(sorted((tags or {}).items())))

    def counter(self, name: str, tags: dict[str, str] | None = None) -> Counter:
        k = self._key(name, tags)
        with self._lock:
            if k not in self._counters:
                self._counters[k] = Counter(name=name, tags=k[1])
            return self._counters[k]

    def gauge(self, name: str, tags: dict[str, str] | None = None) -> Gauge:
        k = self._key(name, tags)
        with self._lock:
            if k not in self._gauges:
                self._gauges[k] = Gauge(name=name, tags=k[1])
            return self._gauges[k]

    def histogram(self, name: str, tags: dict[str, str] | None = None) -> Histogram:
        k = self._key(name, tags)
        with self._lock:
            if k not in self._histograms:
                self._histograms[k] = Histogram(name=name, tags=k[1])
            return self._histograms[k]

    # Convenience methods
    def increment(self, name: str, amount: float = 1.0, tags: dict[str, str] | None = None) -> None:
        self.counter(name, tags).inc(amount)

    def observe(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        self.histogram(name, tags).observe(value)

    def set_gauge(self, name: str, value: float, tags: dict[str, str] | None = None) -> None:
        self.gauge(name, tags).set(value)

    def to_dict(self) -> dict[str, Any]:
        return {
            "counters": [c.to_dict() for c in self._counters.values()],
            "gauges": [g.to_dict() for g in self._gauges.values()],
            "histograms": [h.to_dict() for h in self._histograms.values()],
        }

    def clear(self) -> None:
        with self._lock:
            self._counters.clear()
            self._gauges.clear()
            self._histograms.clear()


# ---------------------------------------------------------------------------
# Event log
# ---------------------------------------------------------------------------

class EventLog:
    """Append-only structured event log (JSON lines)."""

    def __init__(self, log_file: Path | str | None = None) -> None:
        self._log_file = Path(log_file) if log_file else None
        self._events: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        if self._log_file:
            self._log_file.parent.mkdir(parents=True, exist_ok=True)

    def log(self, event_type: str, **attrs: Any) -> None:
        event = {
            "timestamp": datetime.now(UTC).isoformat(),
            "type": event_type,
            **attrs,
        }
        with self._lock:
            self._events.append(event)
            if self._log_file:
                with self._log_file.open("a", encoding="utf-8") as f:
                    f.write(json.dumps(event, default=str) + "\n")

    @property
    def events(self) -> list[dict[str, Any]]:
        return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


# ---------------------------------------------------------------------------
# Singletons
# ---------------------------------------------------------------------------

_metrics: MetricsRegistry | None = None
_tracer: Tracer | None = None
_event_log: EventLog | None = None


def get_metrics() -> MetricsRegistry:
    """Return the process-wide MetricsRegistry."""
    global _metrics
    if _metrics is None:
        _metrics = MetricsRegistry()
    return _metrics


def get_tracer() -> Tracer:
    """Return the process-wide Tracer."""
    global _tracer
    if _tracer is None:
        _tracer = Tracer()
    return _tracer


def get_event_log() -> EventLog:
    """Return the process-wide EventLog."""
    global _event_log
    if _event_log is None:
        _event_log = EventLog()
    return _event_log


# ---------------------------------------------------------------------------
# Exporter
# ---------------------------------------------------------------------------

def export_all(output_path: Path | str) -> Path:
    """Export all telemetry (metrics + traces + events) to a JSON file.

    Useful for shipping to external observability backends.
    """
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "exported_at": datetime.now(UTC).isoformat(),
        "metrics": get_metrics().to_dict(),
        "traces": get_tracer().to_dict(),
        "events": get_event_log().events,
    }
    output_path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return output_path


__all__ = [
    "Counter",
    "Gauge",
    "Histogram",
    "TraceSpan",
    "Tracer",
    "MetricsRegistry",
    "EventLog",
    "get_metrics",
    "get_tracer",
    "get_event_log",
    "export_all",
]
