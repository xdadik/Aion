"""Aion Hand Health Checks — liveness + readiness probes.

Provides health-check endpoints suitable for Kubernetes / Docker /
load balancers. Two flavors:

    - Liveness  — "is the process alive?"  →  /health/live
    - Readiness — "is the agent ready to serve?"  →  /health/ready

Each probe runs a list of registered checks and returns 200 OK if all
pass, 503 if any fail. The response body is JSON with per-check detail.

Usage:
    from aion_core.health import HealthRegistry

    health = HealthRegistry()

    @health.check("memory")
    async def check_memory():
        # ... verify memory manager responds ...
        return True  # or False, or raise

    @health.check("provider")
    async def check_provider():
        ...

    # In your HTTP server:
    async def health_live_handler(request):
        result = await health.run_liveness()
        return web.json_response(result.body, status=result.status)

    # Or run as a standalone aiohttp server:
    await health.serve(port=8080)
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from collections.abc import Awaitable, Callable

logger = logging.getLogger("aion_hand.health")


# ---------------------------------------------------------------------------
# Check result
# ---------------------------------------------------------------------------


@dataclass
class CheckResult:
    """Result of a single health check."""

    name: str
    passed: bool
    duration_seconds: float
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "passed": self.passed,
            "duration_seconds": round(self.duration_seconds, 6),
            "error": self.error,
            "metadata": self.metadata,
        }


@dataclass
class HealthReport:
    """Aggregate health report."""

    status: str  # "pass" | "fail"
    checks: list[CheckResult]
    timestamp: str
    duration_seconds: float

    @property
    def http_status(self) -> int:
        return 200 if self.status == "pass" else 503

    @property
    def body(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "timestamp": self.timestamp,
            "duration_seconds": round(self.duration_seconds, 6),
            "checks": [c.to_dict() for c in self.checks],
            "checks_total": len(self.checks),
            "checks_passed": sum(1 for c in self.checks if c.passed),
            "checks_failed": sum(1 for c in self.checks if not c.passed),
        }


# ---------------------------------------------------------------------------
# Check function type
# ---------------------------------------------------------------------------

CheckFn = Callable[[], Awaitable[bool | tuple[bool, str]]]


# ---------------------------------------------------------------------------
# Health registry
# ---------------------------------------------------------------------------


class HealthRegistry:
    """Registry of health checks for liveness + readiness probes."""

    def __init__(self) -> None:
        self._liveness_checks: dict[str, CheckFn] = {}
        self._readiness_checks: dict[str, CheckFn] = {}
        self._last_liveness: HealthReport | None = None
        self._last_readiness: HealthReport | None = None

    # ------------------------------------------------------------------
    #  Registration
    # ------------------------------------------------------------------

    def liveness(self, name: str) -> Callable[[CheckFn], CheckFn]:
        """Decorator: register a liveness check."""

        def decorator(fn: CheckFn) -> CheckFn:
            self._liveness_checks[name] = fn
            return fn

        return decorator

    def readiness(self, name: str) -> Callable[[CheckFn], CheckFn]:
        """Decorator: register a readiness check."""

        def decorator(fn: CheckFn) -> CheckFn:
            self._readiness_checks[name] = fn
            return fn

        return decorator

    # Convenience: register for both
    def check(self, name: str) -> Callable[[CheckFn], CheckFn]:
        """Decorator: register for BOTH liveness and readiness."""

        def decorator(fn: CheckFn) -> CheckFn:
            self._liveness_checks[name] = fn
            self._readiness_checks[name] = fn
            return fn

        return decorator

    # ------------------------------------------------------------------
    #  Run probes
    # ------------------------------------------------------------------

    async def run_liveness(self) -> HealthReport:
        """Run all liveness checks."""
        return await self._run_checks(self._liveness_checks)

    async def run_readiness(self) -> HealthReport:
        """Run all readiness checks."""
        return await self._run_checks(self._readiness_checks)

    async def _run_checks(self, checks: dict[str, CheckFn]) -> HealthReport:
        start = time.time()
        results: list[CheckResult] = []
        for name, fn in checks.items():
            t0 = time.time()
            try:
                result = await fn()
                if isinstance(result, tuple):
                    passed, error = result
                else:
                    passed, error = bool(result), None
                results.append(
                    CheckResult(
                        name=name,
                        passed=passed,
                        duration_seconds=time.time() - t0,
                        error=error,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                results.append(
                    CheckResult(
                        name=name,
                        passed=False,
                        duration_seconds=time.time() - t0,
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        status = "pass" if all(c.passed for c in results) else "fail"
        report = HealthReport(
            status=status,
            checks=results,
            timestamp=datetime.now(UTC).isoformat(),
            duration_seconds=time.time() - start,
        )
        return report

    # ------------------------------------------------------------------
    #  Standalone HTTP server (optional)
    # ------------------------------------------------------------------

    async def serve(self, host: str = "0.0.0.0", port: int = 8080) -> None:
        """Run a standalone HTTP health server using aiohttp.

        Endpoints:
            GET /health/live   → liveness probe
            GET /health/ready  → readiness probe
            GET /health        → full report (both)
        """
        try:
            from aiohttp import web
        except ImportError as exc:
            raise RuntimeError(
                "aiohttp is required for serve(). Install: pip install aiohttp"
            ) from exc

        async def live_handler(_request: Any) -> Any:
            report = await self.run_liveness()
            self._last_liveness = report
            return web.json_response(report.body, status=report.http_status)

        async def ready_handler(_request: Any) -> Any:
            report = await self.run_readiness()
            self._last_readiness = report
            return web.json_response(report.body, status=report.http_status)

        async def full_handler(_request: Any) -> Any:
            live = await self.run_liveness()
            ready = await self.run_readiness()
            return web.json_response(
                {
                    "liveness": live.body,
                    "readiness": ready.body,
                }
            )

        app = web.Application()
        app.router.add_get("/health/live", live_handler)
        app.router.add_get("/health/ready", ready_handler)
        app.router.add_get("/health", full_handler)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host, port)
        await site.start()
        logger.info("[health] HTTP server listening on %s:%d", host, port)
        # Run forever
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await runner.cleanup()


# ---------------------------------------------------------------------------
#  Singleton
# ---------------------------------------------------------------------------

_default_registry: HealthRegistry | None = None


def get_health_registry() -> HealthRegistry:
    """Return the process-wide HealthRegistry."""
    global _default_registry
    if _default_registry is None:
        _default_registry = HealthRegistry()
    return _default_registry


# ---------------------------------------------------------------------------
#  Default checks
# ---------------------------------------------------------------------------


def register_default_checks(agent: Any | None = None) -> HealthRegistry:
    """Register a sensible set of default health checks for an Aion agent."""
    health = get_health_registry()

    @health.liveness("process")
    async def _process_alive() -> bool:
        """Process is alive if this code runs."""
        return True

    @health.liveness("event_loop")
    async def _event_loop_alive() -> bool:
        """Event loop is running."""
        try:
            loop = asyncio.get_running_loop()
            return loop.is_running()
        except RuntimeError:
            return False

    if agent is not None:

        @health.readiness("agent_state")
        async def _agent_ready() -> bool:
            state = getattr(agent, "state", None)
            # If agent has a state enum, IDLE means ready
            state_name = state.name if hasattr(state, "name") else str(state)
            return (
                state_name in ("IDLE", "INITIALIZING")
                or state_name == "AgentState.IDLE"
            )

        memory = getattr(agent, "_memory", None) or getattr(
            agent, "memory_manager", None
        )
        if memory is not None:

            @health.readiness("memory")
            async def _memory_ready(_memory=memory) -> bool:  # type: ignore[no-untyped-def]
                try:
                    return _memory is not None
                except Exception:  # noqa: BLE001
                    return False

        tools = getattr(agent, "_tools", None) or getattr(agent, "tool_registry", None)
        if tools is not None:

            @health.readiness("tools")
            async def _tools_ready(_tools=tools) -> bool:  # type: ignore[no-untyped-def]
                try:
                    tools_list = (
                        _tools.list_tools() if hasattr(_tools, "list_tools") else []
                    )
                    return len(tools_list) > 0
                except Exception:  # noqa: BLE001
                    return False

    return health


__all__ = [
    "CheckResult",
    "HealthReport",
    "HealthRegistry",
    "get_health_registry",
    "register_default_checks",
]
