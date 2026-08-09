"""Tests for the Health module."""

from __future__ import annotations

import pytest

from aion_core.health import (
    CheckResult,
    HealthReport,
    HealthRegistry,
    get_health_registry,
    register_default_checks,
)


class TestCheckResult:
    def test_passed_check_to_dict(self):
        r = CheckResult(name="x", passed=True, duration_seconds=0.001)
        d = r.to_dict()
        assert d["name"] == "x"
        assert d["passed"] is True
        assert d["error"] is None

    def test_failed_check_with_error(self):
        r = CheckResult(name="x", passed=False, duration_seconds=0.001, error="boom")
        d = r.to_dict()
        assert d["passed"] is False
        assert d["error"] == "boom"


class TestHealthReport:
    def test_pass_report_has_200_status(self):
        r = HealthReport(
            status="pass",
            checks=[CheckResult(name="x", passed=True, duration_seconds=0.001)],
            timestamp="2026-01-01T00:00:00Z",
            duration_seconds=0.001,
        )
        assert r.http_status == 200
        assert r.body["status"] == "pass"
        assert r.body["checks_passed"] == 1

    def test_fail_report_has_503_status(self):
        r = HealthReport(
            status="fail",
            checks=[
                CheckResult(
                    name="x", passed=False, duration_seconds=0.001, error="oops"
                )
            ],
            timestamp="2026-01-01T00:00:00Z",
            duration_seconds=0.001,
        )
        assert r.http_status == 503
        assert r.body["checks_failed"] == 1


class TestHealthRegistry:
    @pytest.mark.asyncio
    async def test_liveness_decorator_registers_check(self):
        reg = HealthRegistry()

        @reg.liveness("always_ok")
        async def _check():
            return True

        report = await reg.run_liveness()
        assert report.status == "pass"
        assert len(report.checks) == 1
        assert report.checks[0].name == "always_ok"

    @pytest.mark.asyncio
    async def test_readiness_decorator_registers_check(self):
        reg = HealthRegistry()

        @reg.readiness("db")
        async def _check():
            return True

        report = await reg.run_readiness()
        assert report.status == "pass"
        assert report.checks[0].name == "db"

    @pytest.mark.asyncio
    async def test_check_decorator_registers_for_both(self):
        reg = HealthRegistry()

        @reg.check("memory")
        async def _check():
            return True

        live = await reg.run_liveness()
        ready = await reg.run_readiness()
        assert any(c.name == "memory" for c in live.checks)
        assert any(c.name == "memory" for c in ready.checks)

    @pytest.mark.asyncio
    async def test_failed_check_makes_report_fail(self):
        reg = HealthRegistry()

        @reg.liveness("broken")
        async def _check():
            return False

        report = await reg.run_liveness()
        assert report.status == "fail"
        assert report.http_status == 503

    @pytest.mark.asyncio
    async def test_exception_in_check_makes_report_fail(self):
        reg = HealthRegistry()

        @reg.liveness("raises")
        async def _check():
            raise RuntimeError("boom")

        report = await reg.run_liveness()
        assert report.status == "fail"
        assert report.checks[0].passed is False
        assert "boom" in report.checks[0].error

    @pytest.mark.asyncio
    async def test_check_returning_tuple(self):
        reg = HealthRegistry()

        @reg.liveness("with_message")
        async def _check():
            return (False, "db unreachable")

        report = await reg.run_liveness()
        assert report.status == "fail"
        assert report.checks[0].error == "db unreachable"


class TestDefaultChecks:
    @pytest.mark.asyncio
    async def test_register_default_checks_without_agent(self):
        # Should work even without an agent
        reg = register_default_checks(agent=None)
        report = await reg.run_liveness()
        # process + event_loop checks should pass
        assert any(c.name == "process" for c in report.checks)
        assert all(
            c.passed for c in report.checks if c.name in ("process", "event_loop")
        )

    @pytest.mark.asyncio
    async def test_register_default_checks_with_mock_agent(self):
        from unittest.mock import MagicMock

        agent = MagicMock()
        agent.state = MagicMock()
        agent.state.name = "IDLE"
        agent._memory = MagicMock()
        agent._tools = MagicMock()
        agent._tools.list_tools.return_value = [{"name": "test_tool"}]
        reg = register_default_checks(agent=agent)
        ready = await reg.run_readiness()
        assert ready.status == "pass"


class TestSingleton:
    def test_get_health_registry_returns_same_instance(self):
        r1 = get_health_registry()
        r2 = get_health_registry()
        assert r1 is r2
