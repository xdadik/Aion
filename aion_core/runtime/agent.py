"""Production AionHand factory.

Bridges the mature AgentConfig/AionHand startup path to the newer unified
AionConfig environment model so API-key configuration actually reaches the
agent's ProviderFactory without persisting secrets.
"""
from __future__ import annotations

from typing import Optional

from aion_core.agent.core import AgentConfig, AionHand
from aion_core.config.manager import AionConfig, load_config
from aion_core.runtime.production import resolve_api_key


def create_production_agent(config: Optional[AionConfig] = None) -> AionHand:
    """Create an AionHand instance from the unified production config."""
    cfg = config or load_config()
    provider = cfg.model.provider.strip().lower()
    api_key = resolve_api_key(provider, cfg.model.api_key)

    provider_config = dict(cfg.model.extra or {})
    if api_key:
        provider_config["api_key"] = api_key
    if cfg.model.api_base:
        provider_config["base_url"] = cfg.model.api_base
    provider_config["timeout"] = cfg.model.timeout
    provider_config["max_retries"] = cfg.model.retry_count
    provider_config["default_model"] = cfg.model.name

    agent_config = AgentConfig(
        name=cfg.name,
        version=cfg.version,
        default_provider=provider,
        default_model=cfg.model.name,
        providers={provider: provider_config},
        max_tokens=cfg.model.max_tokens,
        temperature=cfg.model.temperature,
        memory_enabled=cfg.memory.enabled,
        memory_persist=True,
        memory_nudge_interval=cfg.memory.nudge_interval,
        skills_enabled=True,
        tools_enabled=True,
        mcp_enabled=cfg.mcp.enabled,
        sandbox_enabled=cfg.security.sandbox_enabled,
        pipeline_enabled=cfg.pipeline.enabled,
        cron_enabled=cfg.cron.enabled,
        cron_timezone=cfg.cron.default_timezone,
        workflow_enabled=True,
    )
    return AionHand(config=agent_config)
