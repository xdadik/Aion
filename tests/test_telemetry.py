"""Tests for the Telemetry module."""

from __future__ import annotations

import pytest

from aion_core.telemetry import (
    Counter,
    Gauge,
    Histogram,
    MetricsRegistry,
    TraceSpan,
    Tracer,
    EventLog,
    get_metrics,
    get_tracer,
    get_event_log,
    export_all,
)


class TestCounter:
    def test_initial_value(self):
        c = Counter(name="x")
        assert c.value == 0.0

    def test_inc_default(self):
        c = Counter(name="x")
        c.inc()
        assert c.value == 1.0

    def test_inc_with_amount(self):
        c = Counter(name="x")
        c.inc(5.0)
        assert c.value == 5.0

    def test_inc_negative_raises(self):
        c = Counter(name="x")
        with pytest.raises(ValueError):
            c.inc(-1.0)

    def test_to_dict(self):
        c = Counter(name="x", tags=(("a", "b"),))
        c.inc(3.0)
        d = c.to_dict()
        assert d["type"] == "counter"
        assert d["name"] == "x"
        assert d["value"] == 3.0
        assert d["tags"] == {"a": "b"}


class TestGauge:
    def test_set(self):
        g = Gauge(name="x")
        g.set(42.0)
        assert g.value == 42.0

    def test_inc_and_dec(self):
        g = Gauge(name="x")
        g.inc(10.0)
        g.dec(3.0)
        assert g.value == 7.0


class TestHistogram:
    def test_observe(self):
        h = Histogram(name="x")
        h.observe(0.1)
        h.observe(0.5)
        h.observe(1.0)
        assert h.count == 3
        assert h.sum == 1.6
        assert 0.5 < h.avg < 0.6

    def test_buckets(self):
        h = Histogram(name="x")
        h.observe(0.05)  # falls in 0.05 and larger
        h.observe(0.5)
        h.observe(2.0)
        # At least the 0.05 bucket should have entries
        assert any(c > 0 for c in h.bucket_counts)


class TestTracer:
    def test_start_span_returns_span(self):
        t = Tracer()
        span = t.start_span("op")
        assert isinstance(span, TraceSpan)
        assert span.name == "op"
        assert span.end_time is None

    def test_end_span(self):
        t = Tracer()
        span = t.start_span("op")
        span.end()
        assert span.end_time is not None
        assert span.duration_seconds >= 0.0

    def test_parent_child_spans_share_trace_id(self):
        t = Tracer()
        parent = t.start_span("parent")
        child = t.start_span("child", parent=parent)
        assert child.trace_id == parent.trace_id
        assert child.parent_span_id == parent.span_id

    def test_set_tag_and_add_event(self):
        t = Tracer()
        span = t.start_span("op")
        span.set_tag("user_id", "42")
        span.add_event("started", task="compute")
        assert span.tags["user_id"] == "42"
        assert len(span.events) == 1
        assert span.events[0]["name"] == "started"

    def test_to_dict(self):
        t = Tracer()
        t.start_span("op").end()
        d = t.to_dict()
        assert len(d) == 1
        assert d[0]["name"] == "op"


class TestMetricsRegistry:
    def test_counter_with_tags(self):
        m = MetricsRegistry()
        c1 = m.counter("requests", tags={"method": "GET"})
        c2 = m.counter("requests", tags={"method": "GET"})
        c3 = m.counter("requests", tags={"method": "POST"})
        assert c1 is c2  # same key
        assert c1 is not c3  # different tags
        c1.inc()
        assert c1.value == 1.0
        assert c3.value == 0.0

    def test_increment_helper(self):
        m = MetricsRegistry()
        m.increment("requests")
        m.increment("requests", 2)
        assert m.counter("requests").value == 3.0

    def test_observe_helper(self):
        m = MetricsRegistry()
        m.observe("latency", 0.5)
        m.observe("latency", 1.5)
        h = m.histogram("latency")
        assert h.count == 2
        assert h.sum == 2.0

    def test_set_gauge_helper(self):
        m = MetricsRegistry()
        m.set_gauge("queue_size", 42)
        assert m.gauge("queue_size").value == 42.0

    def test_to_dict(self):
        m = MetricsRegistry()
        m.increment("x")
        m.set_gauge("y", 5)
        m.observe("z", 0.1)
        d = m.to_dict()
        assert "counters" in d
        assert "gauges" in d
        assert "histograms" in d
        assert len(d["counters"]) == 1
        assert len(d["gauges"]) == 1
        assert len(d["histograms"]) == 1


class TestEventLog:
    def test_log_appends_event(self):
        log = EventLog()
        log.log("test_event", key="value")
        assert len(log.events) == 1
        assert log.events[0]["type"] == "test_event"
        assert log.events[0]["key"] == "value"

    def test_log_writes_to_file(self, tmp_path):
        f = tmp_path / "events.jsonl"
        log = EventLog(log_file=f)
        log.log("test", x=1)
        assert f.is_file()
        content = f.read_text()
        assert "test" in content

    def test_clear(self):
        log = EventLog()
        log.log("a")
        log.clear()
        assert len(log.events) == 0


class TestSingletons:
    def test_get_metrics_singleton(self):
        m1 = get_metrics()
        m2 = get_metrics()
        assert m1 is m2

    def test_get_tracer_singleton(self):
        t1 = get_tracer()
        t2 = get_tracer()
        assert t1 is t2


class TestExportAll:
    def test_export_writes_json(self, tmp_path):
        # Use fresh instances to avoid polluting the singleton
        m = MetricsRegistry()
        m.increment("x")
        t = Tracer()
        t.start_span("op").end()
        log = EventLog()
        log.log("event")

        out = tmp_path / "telemetry.json"
        # export_all uses the singletons, so let's populate them
        get_metrics().clear()
        get_metrics().increment("x")
        get_tracer().clear()
        get_tracer().start_span("op").end()
        get_event_log().clear()
        get_event_log().log("event")

        result = export_all(out)
        assert result.is_file()
        import json
        data = json.loads(out.read_text())
        assert "metrics" in data
        assert "traces" in data
        assert "events" in data
