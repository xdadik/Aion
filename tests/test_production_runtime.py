import os

import pytest

from aion_core.automation.autonomous import AutonomousRunner, AutomationTask
from aion_core.config.manager import AionConfig
from aion_core.runtime.production import resolve_api_key, runtime_diagnostics


def test_provider_specific_key_precedes_generic(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "provider-secret")
    monkeypatch.setenv("AION_API_KEY", "generic-secret")
    assert resolve_api_key("openai") == "provider-secret"


def test_runtime_diagnostics_never_returns_secret(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "super-secret")
    cfg = AionConfig()
    cfg.model.provider = "openai"
    cfg.model.name = "test-model"
    diagnostics = runtime_diagnostics(cfg)
    assert diagnostics["api_key_present"] is True
    assert diagnostics["api_key"] == "[configured]"
    assert "super-secret" not in str(diagnostics)


@pytest.mark.asyncio
async def test_automation_retries_until_verification_passes():
    class FakeAgent:
        def __init__(self):
            self.calls = 0

        async def chat(self, prompt):
            self.calls += 1
            return {"content": f"attempt-{self.calls}"}

    agent = FakeAgent()
    runner = AutonomousRunner(agent)
    seen = []

    async def verify(response):
        seen.append(response["content"])
        return len(seen) >= 2

    result = await runner.run(
        AutomationTask(prompt="do work", max_attempts=3, timeout=2, verify=verify)
    )
    assert result.success is True
    assert result.attempts == 2
    assert agent.calls == 2


@pytest.mark.asyncio
async def test_automation_respects_concurrency_bound():
    active = 0
    peak = 0

    class FakeAgent:
        async def chat(self, prompt):
            nonlocal active, peak
            active += 1
            peak = max(peak, active)
            await __import__("asyncio").sleep(0.02)
            active -= 1
            return {"content": prompt}

    runner = AutonomousRunner(FakeAgent(), max_concurrency=2)
    results = await runner.run_many(
        [AutomationTask(prompt=str(i), timeout=2) for i in range(6)]
    )
    assert all(r.success for r in results)
    assert peak <= 2
