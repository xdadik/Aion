"""Production runtime bootstrap for Aion Hand.

This module provides one reliable entry point for applications and deployments:
configuration is loaded with environment precedence, secrets stay in memory,
the configured provider is instantiated through ProviderFactory, and a health
check can be run before starting an autonomous agent.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional

from aion_core.config.manager import AionConfig, load_config
from aion_core.providers.factory import BaseProvider, ProviderFactory


_PROVIDER_ENV = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "gemini": "GOOGLE_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "ollama": "OLLAMA_API_KEY",
    "custom": "CUSTOM_API_KEY",
}


@dataclass(frozen=True)
class RuntimeStatus:
    """Serializable health information for the runtime."""

    provider: str
    model: str
    configured: bool
    healthy: bool
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "provider": self.provider,
            "model": self.model,
            "configured": self.configured,
            "healthy": self.healthy,
            "error": self.error,
        }


def resolve_api_key(provider: str, configured_key: str = "") -> str:
    """Resolve a provider key without writing it to disk.

    Provider-specific environment variables win over the generic AION_API_KEY
    when no explicit in-memory key was supplied. This keeps API credentials
    out of config files by default.
    """
    if configured_key:
        return configured_key
    env_name = _PROVIDER_ENV.get(provider.lower().strip())
    if env_name:
        return os.environ.get(env_name, "")
    return os.environ.get("AION_API_KEY", "")


def build_provider(config: Optional[AionConfig] = None) -> BaseProvider:
    """Build the configured provider using safe environment precedence."""
    cfg = config or load_config()
    provider_name = cfg.model.provider.strip().lower()
    if not provider_name:
        raise ValueError("AION_PROVIDER/model.provider is empty")

    provider_config: Dict[str, Any] = dict(cfg.model.extra or {})
    api_key = resolve_api_key(provider_name, cfg.model.api_key)
    if api_key:
        provider_config["api_key"] = api_key
    if cfg.model.api_base:
        provider_config["base_url"] = cfg.model.api_base
    provider_config["timeout"] = cfg.model.timeout
    provider_config["max_retries"] = cfg.model.retry_count
    provider_config["default_model"] = cfg.model.name

    return ProviderFactory.create(
        provider_name,
        provider_config,
        default_model=cfg.model.name,
    )


async def provider_health_check(provider: BaseProvider) -> RuntimeStatus:
    """Check provider readiness without sending a paid generation request."""
    try:
        models = await provider.list_models()
        model = provider.default_model
        healthy = bool(model in models or models or provider.PROVIDER_NAME == "ollama")
        return RuntimeStatus(
            provider=provider.PROVIDER_NAME,
            model=model,
            configured=bool(getattr(provider, "api_key", None)) or provider.PROVIDER_NAME == "ollama",
            healthy=healthy,
            error=None if healthy else "Provider returned no usable models",
        )
    except Exception as exc:
        return RuntimeStatus(
            provider=provider.PROVIDER_NAME,
            model=provider.default_model,
            configured=bool(getattr(provider, "api_key", None)) or provider.PROVIDER_NAME == "ollama",
            healthy=False,
            error=f"{type(exc).__name__}: {exc}",
        )


def runtime_diagnostics(config: Optional[AionConfig] = None) -> Dict[str, Any]:
    """Return non-secret diagnostics suitable for logs and CI."""
    cfg = config or load_config()
    provider = cfg.model.provider.strip().lower()
    key_present = bool(resolve_api_key(provider, cfg.model.api_key))
    return {
        "version": cfg.version,
        "provider": provider,
        "model": cfg.model.name,
        "api_key_present": key_present,
        "api_key": "[configured]" if key_present else "[missing]",
        "security_enabled": cfg.security.enabled,
        "sandbox_enabled": cfg.security.sandbox_enabled,
        "memory_enabled": cfg.memory.enabled,
        "pipeline_enabled": cfg.pipeline.enabled,
        "mcp_enabled": cfg.mcp.enabled,
    }
