"""
Aion Hand Configuration Manager.
=================================

Hermes-inspired YAML configuration with profile support, AION_HOME, and
env management.  Zero external dependencies — uses only the Python stdlib.

Features
--------
- :class:`AionConfig` dataclass with ALL config fields
  (model, provider, security, memory, pipeline, gateway, cron, mcp, etc.)
- ``load_config()`` — loads from JSON config file, falls back to env vars,
  falls back to defaults
- ``save_config()`` — saves to JSON with atomic writes (temp + fsync + rename)
- ``get_aion_home()`` — resolves via ``AION_HOME`` env → ``AION_PROFILE``
  → ``~/.aion-hand``
- Profile support: ``config.json`` per profile directory
- ``env_int()``, ``env_float()``, ``env_bool()``, ``env_str()`` type-safe
  env readers
- ``normalize_proxy_env_vars()`` proxy normalization
- Section-specific config: ``ModelConfig``, ``SecurityConfig``,
  ``MemoryConfig``, ``PipelineConfig``, ``GatewayConfig``, ``CronConfig``,
  ``MCPConfig``
- Environment variable mapping: ``AION_PROVIDER``, ``AION_MODEL``,
  ``AION_API_KEY``, ``AION_LOG_LEVEL``, etc.
- Merge logic: CLI args > env vars > config.json > defaults

Design Notes
------------
Since we want *zero* external dependencies, we use JSON as the config file
format (``json`` is in stdlib).  If a future version adds ``pyyaml`` as an
optional dependency, the loader can transparently support YAML as well.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_AION_HOME = Path.home() / ".aion-hand"

# Well-known environment variable names
ENV_PROVIDER = "AION_PROVIDER"
ENV_MODEL = "AION_MODEL"
ENV_API_KEY = "AION_API_KEY"
ENV_API_BASE = "AION_API_BASE"
ENV_LOG_LEVEL = "AION_LOG_LEVEL"
ENV_HOME = "AION_HOME"
ENV_PROFILE = "AION_PROFILE"
ENV_CONFIG_FILE = "AION_CONFIG_FILE"
ENV_DATA_DIR = "AION_DATA_DIR"
ENV_MEMORY_DIR = "AION_MEMORY_DIR"
ENV_SKILLS_DIR = "AION_SKILLS_DIR"
ENV_TEMPERATURE = "AION_TEMPERATURE"
ENV_MAX_TOKENS = "AION_MAX_TOKENS"
ENV_TIMEOUT = "AION_TIMEOUT"
ENV_SECURITY_ENABLED = "AION_SECURITY_ENABLED"
ENV_SANDBOX_ENABLED = "AION_SANDBOX_ENABLED"
ENV_MCP_ENABLED = "AION_MCP_ENABLED"
ENV_GATEWAY_ENABLED = "AION_GATEWAY_ENABLED"
ENV_CRON_ENABLED = "AION_CRON_ENABLED"

# Known providers
KNOWN_PROVIDERS = (
    "openai",
    "anthropic",
    "ollama",
    "google",
    "azure",
    "mistral",
    "groq",
    "cohere",
    "local",
)

# ---------------------------------------------------------------------------
# Type-safe env var readers
# ---------------------------------------------------------------------------


def env_str(
    name: str,
    default: str = "",
    prefix: str = "AION_",
) -> str:
    """Read an environment variable as a string.

    Args:
        name:    Variable name (without prefix).
        default: Default value if unset.
        prefix:  Prefix to prepend (default ``"AION_"``).

    Returns:
        The variable value, or *default*.
    """
    return os.environ.get(f"{prefix}{name}", default)


def env_int(
    name: str,
    default: int = 0,
    prefix: str = "AION_",
) -> int:
    """Read an environment variable as an integer.

    Returns *default* if the variable is unset or not a valid integer.
    """
    val = os.environ.get(f"{prefix}{name}")
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        logger.warning("Invalid int for %s%s=%r, using default %d", prefix, name, val, default)
        return default


def env_float(
    name: str,
    default: float = 0.0,
    prefix: str = "AION_",
) -> float:
    """Read an environment variable as a float.

    Returns *default* if the variable is unset or not a valid float.
    """
    val = os.environ.get(f"{prefix}{name}")
    if val is None:
        return default
    try:
        return float(val)
    except (ValueError, TypeError):
        logger.warning("Invalid float for %s%s=%r, using default %f", prefix, name, val, default)
        return default


def env_bool(
    name: str,
    default: bool = False,
    prefix: str = "AION_",
) -> bool:
    """Read an environment variable as a boolean.

    Truthy values (case-insensitive): ``1``, ``true``, ``yes``, ``on``, ``enabled``.
    """
    val = os.environ.get(f"{prefix}{name}")
    if val is None:
        return default
    return val.strip().lower() in ("1", "true", "yes", "on", "enabled")


# ---------------------------------------------------------------------------
# AION_HOME resolution
# ---------------------------------------------------------------------------


def get_aion_home() -> Path:
    """Resolve the Aion Hand home directory.

    Resolution order:
        1. ``AION_HOME`` environment variable (explicit override)
        2. ``AION_PROFILE`` → ``~/.aion-hand/profiles/<name>``
        3. ``~/.aion-hand`` (default)

    The returned path is guaranteed to exist (created if necessary).
    """
    # 1. Explicit AION_HOME
    explicit = os.environ.get(ENV_HOME)
    if explicit:
        p = Path(explicit).expanduser().resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 2. Profile-based
    profile = os.environ.get(ENV_PROFILE)
    if profile:
        p = _DEFAULT_AION_HOME / "profiles" / profile
        p.mkdir(parents=True, exist_ok=True)
        return p

    # 3. Default
    _DEFAULT_AION_HOME.mkdir(parents=True, exist_ok=True)
    return _DEFAULT_AION_HOME


# ---------------------------------------------------------------------------
# Proxy normalization
# ---------------------------------------------------------------------------


def normalize_proxy_env_vars() -> dict[str, str]:
    """Normalize proxy environment variables.

    Ensures lowercase variants are set if uppercase ones exist.

    Returns:
        A dict with the effective proxy env vars.
    """
    mapping = {
        "http_proxy": "HTTP_PROXY",
        "https_proxy": "HTTPS_PROXY",
        "no_proxy": "NO_PROXY",
    }
    result: dict[str, str] = {}
    for lower, upper in mapping.items():
        val = os.environ.get(upper) or os.environ.get(lower)
        if val:
            result[lower] = val
            result[upper] = val
    return result


# ---------------------------------------------------------------------------
# Section-level configuration dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ModelConfig:
    """Configuration for the LLM model."""

    name: str = "llama3"
    provider: str = "ollama"
    api_key: str = ""
    api_base: str = ""
    temperature: float = 0.7
    max_tokens: int = 4096
    top_p: float = 0.9
    frequency_penalty: float = 0.0
    presence_penalty: float = 0.0
    timeout: int = 120
    retry_count: int = 3
    retry_delay: float = 1.0
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "name": self.name,
            "provider": self.provider,
            "api_key": self.api_key,
            "api_base": self.api_base,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "frequency_penalty": self.frequency_penalty,
            "presence_penalty": self.presence_penalty,
            "timeout": self.timeout,
            "retry_count": self.retry_count,
            "retry_delay": self.retry_delay,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ModelConfig":
        return cls(
            name=data.get("name", cls().name),
            provider=data.get("provider", cls().provider),
            api_key=data.get("api_key", ""),
            api_base=data.get("api_base", ""),
            temperature=float(data.get("temperature", cls().temperature)),
            max_tokens=int(data.get("max_tokens", cls().max_tokens)),
            top_p=float(data.get("top_p", cls().top_p)),
            frequency_penalty=float(data.get("frequency_penalty", cls().frequency_penalty)),
            presence_penalty=float(data.get("presence_penalty", cls().presence_penalty)),
            timeout=int(data.get("timeout", cls().timeout)),
            retry_count=int(data.get("retry_count", cls().retry_count)),
            retry_delay=float(data.get("retry_delay", cls().retry_delay)),
            extra=data.get("extra", {}),
        )


@dataclass
class SecurityConfig:
    """Configuration for security and sandbox features."""

    enabled: bool = True
    sandbox_enabled: bool = True
    sandbox_timeout: int = 30
    max_tool_calls_per_turn: int = 20
    max_code_length: int = 50000
    allowed_dirs: list[str] = field(default_factory=lambda: ["~/.aion-hand"])
    blocked_commands: list[str] = field(default_factory=lambda: [
        "rm -rf /", "dd if=/dev/zero", ":(){ :|:& };:",
    ])
    require_approval: bool = False
    audit_log: bool = True
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "enabled": self.enabled,
            "sandbox_enabled": self.sandbox_enabled,
            "sandbox_timeout": self.sandbox_timeout,
            "max_tool_calls_per_turn": self.max_tool_calls_per_turn,
            "max_code_length": self.max_code_length,
            "allowed_dirs": self.allowed_dirs,
            "blocked_commands": self.blocked_commands,
            "require_approval": self.require_approval,
            "audit_log": self.audit_log,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SecurityConfig":
        return cls(
            enabled=bool(data.get("enabled", cls().enabled)),
            sandbox_enabled=bool(data.get("sandbox_enabled", cls().sandbox_enabled)),
            sandbox_timeout=int(data.get("sandbox_timeout", cls().sandbox_timeout)),
            max_tool_calls_per_turn=int(data.get("max_tool_calls_per_turn", cls().max_tool_calls_per_turn)),
            max_code_length=int(data.get("max_code_length", cls().max_code_length)),
            allowed_dirs=data.get("allowed_dirs", cls().allowed_dirs),
            blocked_commands=data.get("blocked_commands", cls().blocked_commands),
            require_approval=bool(data.get("require_approval", cls().require_approval)),
            audit_log=bool(data.get("audit_log", cls().audit_log)),
            extra=data.get("extra", {}),
        )


@dataclass
class MemoryConfig:
    """Configuration for the multi-layer memory system."""

    enabled: bool = True
    working_max: int = 200
    session_max: int = 500
    episodic_max: int = 1000
    semantic_max: int = 2000
    procedural_max: int = 500
    user_profile_max: int = 200
    nudge_interval: int = 600  # seconds
    export_markdown: bool = True
    persistence_backend: str = "json"  # json | sqlite
    fts_enabled: bool = True
    search_default_limit: int = 20
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "enabled": self.enabled,
            "working_max": self.working_max,
            "session_max": self.session_max,
            "episodic_max": self.episodic_max,
            "semantic_max": self.semantic_max,
            "procedural_max": self.procedural_max,
            "user_profile_max": self.user_profile_max,
            "nudge_interval": self.nudge_interval,
            "export_markdown": self.export_markdown,
            "persistence_backend": self.persistence_backend,
            "fts_enabled": self.fts_enabled,
            "search_default_limit": self.search_default_limit,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MemoryConfig":
        return cls(
            enabled=bool(data.get("enabled", cls().enabled)),
            working_max=int(data.get("working_max", cls().working_max)),
            session_max=int(data.get("session_max", cls().session_max)),
            episodic_max=int(data.get("episodic_max", cls().episodic_max)),
            semantic_max=int(data.get("semantic_max", cls().semantic_max)),
            procedural_max=int(data.get("procedural_max", cls().procedural_max)),
            user_profile_max=int(data.get("user_profile_max", cls().user_profile_max)),
            nudge_interval=int(data.get("nudge_interval", cls().nudge_interval)),
            export_markdown=bool(data.get("export_markdown", cls().export_markdown)),
            persistence_backend=data.get("persistence_backend", cls().persistence_backend),
            fts_enabled=bool(data.get("fts_enabled", cls().fts_enabled)),
            search_default_limit=int(data.get("search_default_limit", cls().search_default_limit)),
            extra=data.get("extra", {}),
        )


@dataclass
class PipelineConfig:
    """Configuration for the learning/repair pipeline."""

    enabled: bool = True
    max_iterations: int = 5
    learning_rate: float = 0.1
    confidence_threshold: float = 0.7
    verification_enabled: bool = True
    auto_repair: bool = True
    max_repair_attempts: int = 3
    planner_model: str = ""
    critic_model: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "enabled": self.enabled,
            "max_iterations": self.max_iterations,
            "learning_rate": self.learning_rate,
            "confidence_threshold": self.confidence_threshold,
            "verification_enabled": self.verification_enabled,
            "auto_repair": self.auto_repair,
            "max_repair_attempts": self.max_repair_attempts,
            "planner_model": self.planner_model,
            "critic_model": self.critic_model,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PipelineConfig":
        return cls(
            enabled=bool(data.get("enabled", cls().enabled)),
            max_iterations=int(data.get("max_iterations", cls().max_iterations)),
            learning_rate=float(data.get("learning_rate", cls().learning_rate)),
            confidence_threshold=float(data.get("confidence_threshold", cls().confidence_threshold)),
            verification_enabled=bool(data.get("verification_enabled", cls().verification_enabled)),
            auto_repair=bool(data.get("auto_repair", cls().auto_repair)),
            max_repair_attempts=int(data.get("max_repair_attempts", cls().max_repair_attempts)),
            planner_model=data.get("planner_model", ""),
            critic_model=data.get("critic_model", ""),
            extra=data.get("extra", {}),
        )


@dataclass
class GatewayConfig:
    """Configuration for the messaging gateway."""

    enabled: bool = False
    platforms: list[str] = field(default_factory=list)
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    discord_bot_token: str = ""
    slack_bot_token: str = ""
    slack_channel: str = ""
    webhook_url: str = ""
    webhook_secret: str = ""
    rate_limit: int = 60
    max_message_length: int = 4000
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "enabled": self.enabled,
            "platforms": self.platforms,
            "telegram_bot_token": self.telegram_bot_token,
            "telegram_chat_id": self.telegram_chat_id,
            "discord_bot_token": self.discord_bot_token,
            "slack_bot_token": self.slack_bot_token,
            "slack_channel": self.slack_channel,
            "webhook_url": self.webhook_url,
            "webhook_secret": self.webhook_secret,
            "rate_limit": self.rate_limit,
            "max_message_length": self.max_message_length,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "GatewayConfig":
        return cls(
            enabled=bool(data.get("enabled", cls().enabled)),
            platforms=data.get("platforms", cls().platforms),
            telegram_bot_token=data.get("telegram_bot_token", ""),
            telegram_chat_id=data.get("telegram_chat_id", ""),
            discord_bot_token=data.get("discord_bot_token", ""),
            slack_bot_token=data.get("slack_bot_token", ""),
            slack_channel=data.get("slack_channel", ""),
            webhook_url=data.get("webhook_url", ""),
            webhook_secret=data.get("webhook_secret", ""),
            rate_limit=int(data.get("rate_limit", cls().rate_limit)),
            max_message_length=int(data.get("max_message_length", cls().max_message_length)),
            extra=data.get("extra", {}),
        )


@dataclass
class CronConfig:
    """Configuration for the cron scheduler."""

    enabled: bool = False
    tick_interval: int = 60
    max_tasks: int = 100
    default_timezone: str = "UTC"
    persistent: bool = True
    state_file: str = "cron_state.json"
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "enabled": self.enabled,
            "tick_interval": self.tick_interval,
            "max_tasks": self.max_tasks,
            "default_timezone": self.default_timezone,
            "persistent": self.persistent,
            "state_file": self.state_file,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CronConfig":
        return cls(
            enabled=bool(data.get("enabled", cls().enabled)),
            tick_interval=int(data.get("tick_interval", cls().tick_interval)),
            max_tasks=int(data.get("max_tasks", cls().max_tasks)),
            default_timezone=data.get("default_timezone", cls().default_timezone),
            persistent=bool(data.get("persistent", cls().persistent)),
            state_file=data.get("state_file", cls().state_file),
            extra=data.get("extra", {}),
        )


@dataclass
class MCPConfig:
    """Configuration for the Model Context Protocol integration."""

    enabled: bool = True
    servers: list[dict[str, Any]] = field(default_factory=list)
    default_timeout: int = 30
    max_retries: int = 2
    retry_delay: float = 1.0
    auto_discover: bool = True
    transport: str = "stdio"  # stdio | sse
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "enabled": self.enabled,
            "servers": self.servers,
            "default_timeout": self.default_timeout,
            "max_retries": self.max_retries,
            "retry_delay": self.retry_delay,
            "auto_discover": self.auto_discover,
            "transport": self.transport,
        }
        if self.extra:
            d["extra"] = self.extra
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MCPConfig":
        return cls(
            enabled=bool(data.get("enabled", cls().enabled)),
            servers=data.get("servers", cls().servers),
            default_timeout=int(data.get("default_timeout", cls().default_timeout)),
            max_retries=int(data.get("max_retries", cls().max_retries)),
            retry_delay=float(data.get("retry_delay", cls().retry_delay)),
            auto_discover=bool(data.get("auto_discover", cls().auto_discover)),
            transport=data.get("transport", cls().transport),
            extra=data.get("extra", {}),
        )


# ---------------------------------------------------------------------------
# Top-level configuration
# ---------------------------------------------------------------------------


@dataclass
class AionConfig:
    """Central configuration for Aion Hand.

    All fields have sensible defaults.  Configuration is loaded via
    ``load_config()`` which applies the merge priority:

        CLI args > env vars > config.json > defaults
    """

    # Identity
    name: str = "Aion Hand"
    version: str = "0.3.0"

    # Paths (resolved at load time)
    home_dir: str = ""
    data_dir: str = ""
    memory_dir: str = ""
    skills_dir: str = ""
    tools_dir: str = ""
    logs_dir: str = ""
    config_dir: str = ""

    # Core settings
    log_level: str = "INFO"
    debug: bool = False
    profile: str = "default"

    # Sub-configurations
    model: ModelConfig = field(default_factory=ModelConfig)
    security: SecurityConfig = field(default_factory=SecurityConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    pipeline: PipelineConfig = field(default_factory=PipelineConfig)
    gateway: GatewayConfig = field(default_factory=GatewayConfig)
    cron: CronConfig = field(default_factory=CronConfig)
    mcp: MCPConfig = field(default_factory=MCPConfig)

    # Dynamic agents
    dynamic_enabled: bool = True
    dynamic_storage_dir: str = ""

    # Knowledge graph
    knowledge_enabled: bool = True
    knowledge_dir: str = ""

    # Router
    router_enabled: bool = False

    # Benchmark
    benchmark_enabled: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict suitable for JSON dumping."""
        return {
            "name": self.name,
            "version": self.version,
            "home_dir": self.home_dir,
            "data_dir": self.data_dir,
            "memory_dir": self.memory_dir,
            "skills_dir": self.skills_dir,
            "tools_dir": self.tools_dir,
            "logs_dir": self.logs_dir,
            "config_dir": self.config_dir,
            "log_level": self.log_level,
            "debug": self.debug,
            "profile": self.profile,
            "model": self.model.to_dict(),
            "security": self.security.to_dict(),
            "memory": self.memory.to_dict(),
            "pipeline": self.pipeline.to_dict(),
            "gateway": self.gateway.to_dict(),
            "cron": self.cron.to_dict(),
            "mcp": self.mcp.to_dict(),
            "dynamic_enabled": self.dynamic_enabled,
            "dynamic_storage_dir": self.dynamic_storage_dir,
            "knowledge_enabled": self.knowledge_enabled,
            "knowledge_dir": self.knowledge_dir,
            "router_enabled": self.router_enabled,
            "benchmark_enabled": self.benchmark_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AionConfig":
        """Deserialize from a plain dict (e.g. loaded JSON)."""
        home = data.get("home_dir", "")
        return cls(
            name=data.get("name", cls().name),
            version=data.get("version", cls().version),
            home_dir=home,
            data_dir=data.get("data_dir", ""),
            memory_dir=data.get("memory_dir", ""),
            skills_dir=data.get("skills_dir", ""),
            tools_dir=data.get("tools_dir", ""),
            logs_dir=data.get("logs_dir", ""),
            config_dir=data.get("config_dir", ""),
            log_level=data.get("log_level", cls().log_level),
            debug=bool(data.get("debug", cls().debug)),
            profile=data.get("profile", cls().profile),
            model=ModelConfig.from_dict(data.get("model", {})),
            security=SecurityConfig.from_dict(data.get("security", {})),
            memory=MemoryConfig.from_dict(data.get("memory", {})),
            pipeline=PipelineConfig.from_dict(data.get("pipeline", {})),
            gateway=GatewayConfig.from_dict(data.get("gateway", {})),
            cron=CronConfig.from_dict(data.get("cron", {})),
            mcp=MCPConfig.from_dict(data.get("mcp", {})),
            dynamic_enabled=bool(data.get("dynamic_enabled", cls().dynamic_enabled)),
            dynamic_storage_dir=data.get("dynamic_storage_dir", ""),
            knowledge_enabled=bool(data.get("knowledge_enabled", cls().knowledge_enabled)),
            knowledge_dir=data.get("knowledge_dir", ""),
            router_enabled=bool(data.get("router_enabled", cls().router_enabled)),
            benchmark_enabled=bool(data.get("benchmark_enabled", cls().benchmark_enabled)),
        )


# ---------------------------------------------------------------------------
# Path resolution helpers
# ---------------------------------------------------------------------------


def _resolve_paths(config: AionConfig) -> AionConfig:
    """Fill in default path values relative to ``home_dir``."""
    home = Path(config.home_dir) if config.home_dir else get_aion_home()
    config.home_dir = str(home)
    if not config.data_dir:
        config.data_dir = str(home / "data")
    if not config.memory_dir:
        config.memory_dir = str(home / "memory")
    if not config.skills_dir:
        config.skills_dir = str(home / "skills")
    if not config.tools_dir:
        config.tools_dir = str(home / "tools")
    if not config.logs_dir:
        config.logs_dir = str(home / "logs")
    if not config.config_dir:
        config.config_dir = str(home / "config")
    if not config.dynamic_storage_dir:
        config.dynamic_storage_dir = str(home / "dynamic")
    if not config.knowledge_dir:
        config.knowledge_dir = str(home / "knowledge")
    return config


# ---------------------------------------------------------------------------
# Env var overlay
# ---------------------------------------------------------------------------


def _apply_env_overlays(config: AionConfig) -> AionConfig:
    """Overlay environment variables onto the config.

    Environment variables take precedence over file-based values.
    """
    # Model
    provider = os.environ.get(ENV_PROVIDER)
    if provider:
        config.model.provider = provider
    model = os.environ.get(ENV_MODEL)
    if model:
        config.model.name = model
    api_key = os.environ.get(ENV_API_KEY)
    if api_key:
        config.model.api_key = api_key
    api_base = os.environ.get(ENV_API_BASE)
    if api_base:
        config.model.api_base = api_base
    temp = os.environ.get(ENV_TEMPERATURE)
    if temp is not None:
        try:
            config.model.temperature = float(temp)
        except ValueError:
            pass
    max_tok = os.environ.get(ENV_MAX_TOKENS)
    if max_tok is not None:
        try:
            config.model.max_tokens = int(max_tok)
        except ValueError:
            pass
    timeout = os.environ.get(ENV_TIMEOUT)
    if timeout is not None:
        try:
            config.model.timeout = int(timeout)
        except ValueError:
            pass

    # General
    log_level = os.environ.get(ENV_LOG_LEVEL)
    if log_level:
        config.log_level = log_level.upper()

    # Paths
    data_dir = os.environ.get(ENV_DATA_DIR)
    if data_dir:
        config.data_dir = data_dir
    memory_dir = os.environ.get(ENV_MEMORY_DIR)
    if memory_dir:
        config.memory_dir = memory_dir
    skills_dir = os.environ.get(ENV_SKILLS_DIR)
    if skills_dir:
        config.skills_dir = skills_dir

    # Feature flags
    if os.environ.get(ENV_SECURITY_ENABLED) is not None:
        config.security.enabled = env_bool("SECURITY_ENABLED")
    if os.environ.get(ENV_SANDBOX_ENABLED) is not None:
        config.security.sandbox_enabled = env_bool("SANDBOX_ENABLED")
    if os.environ.get(ENV_MCP_ENABLED) is not None:
        config.mcp.enabled = env_bool("MCP_ENABLED")
    if os.environ.get(ENV_GATEWAY_ENABLED) is not None:
        config.gateway.enabled = env_bool("GATEWAY_ENABLED")
    if os.environ.get(ENV_CRON_ENABLED) is not None:
        config.cron.enabled = env_bool("CRON_ENABLED")

    return config


# ---------------------------------------------------------------------------
# Config file discovery
# ---------------------------------------------------------------------------


def _discover_config_file(explicit: str | None = None) -> Path | None:
    """Locate the config file.

    Search order:
        1. *explicit* path if provided
        2. ``AION_CONFIG_FILE`` env var
        3. ``<aion_home>/config/config.json``
        4. ``<aion_home>/config.json``
    """
    candidates: list[Path] = []

    # 1. Explicit path
    if explicit:
        candidates.append(Path(explicit).expanduser().resolve())

    # 2. Env var
    env_path = os.environ.get(ENV_CONFIG_FILE)
    if env_path:
        candidates.append(Path(env_path).expanduser().resolve())

    # 3/4. Convention paths
    home = get_aion_home()
    candidates.append(home / "config" / "config.json")
    candidates.append(home / "config.json")

    for candidate in candidates:
        if candidate.is_file():
            logger.debug("Config file found: %s", candidate)
            return candidate

    logger.debug("No config file found; using defaults + env vars")
    return None


# ---------------------------------------------------------------------------
# Load / Save
# ---------------------------------------------------------------------------


def load_config(
    config_file: str | None = None,
    profile: str | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> AionConfig:
    """Load the Aion Hand configuration.

    Merge priority (later overrides earlier):
        1. Built-in defaults
        2. Config file (``config.json``)
        3. Environment variables
        4. CLI overrides

    Args:
        config_file:    Explicit path to config file (skip discovery).
        profile:        Profile name to activate (sets ``AION_PROFILE``).
        cli_overrides:  Dict of top-level overrides from CLI args.

    Returns:
        A fully-resolved :class:`AionConfig` instance.
    """
    # 1. Start with defaults
    config = AionConfig()

    # Profile activation
    if profile:
        config.profile = profile
        os.environ[ENV_PROFILE] = profile

    # 2. Load from file
    discovered = _discover_config_file(config_file)
    if discovered is not None:
        try:
            raw = discovered.read_text(encoding="utf-8")
            file_data = json.loads(raw)
            config = AionConfig.from_dict(file_data)
            logger.info("Loaded config from %s", discovered)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to load config from %s: %s", discovered, exc)

    # 3. Resolve paths
    config = _resolve_paths(config)

    # 4. Apply environment variable overlays
    config = _apply_env_overlays(config)

    # 5. Apply CLI overrides
    if cli_overrides:
        config = _apply_overrides(config, cli_overrides)

    logger.debug(
        "Config loaded: provider=%s, model=%s, log_level=%s",
        config.model.provider,
        config.model.name,
        config.log_level,
    )
    return config


def _apply_overrides(config: AionConfig, overrides: dict[str, Any]) -> AionConfig:
    """Apply a flat dict of overrides onto the config.

    Supports dotted keys like ``model.temperature`` and ``security.enabled``.
    """
    for key, value in overrides.items():
        parts = key.split(".", 1)
        if len(parts) == 2:
            section_name, field_name = parts
            section_map = {
                "model": config.model,
                "security": config.security,
                "memory": config.memory,
                "pipeline": config.pipeline,
                "gateway": config.gateway,
                "cron": config.cron,
                "mcp": config.mcp,
            }
            section = section_map.get(section_name)
            if section is not None and hasattr(section, field_name):
                setattr(section, field_name, value)
                continue
        # Top-level field
        if hasattr(config, key):
            setattr(config, key, value)
    return config


def save_config(
    config: AionConfig,
    config_file: str | None = None,
) -> Path:
    """Save the configuration to a JSON file with atomic writes.

    Atomic write strategy:
        1. Write to a temp file in the same directory
        2. ``fsync`` the temp file
        3. ``os.replace`` (atomic on POSIX) to the target path

    Args:
        config:      The config to save.
        config_file: Explicit target path.  If *None*, saves to
                    ``<aion_home>/config/config.json``.

    Returns:
        The path the config was saved to.
    """
    if config_file:
        target = Path(config_file).expanduser().resolve()
    else:
        target = get_aion_home() / "config" / "config.json"

    target.parent.mkdir(parents=True, exist_ok=True)

    # Write to temp file first
    fd, tmp_path = tempfile.mkstemp(
        suffix=".tmp",
        prefix=".aion-config-",
        dir=target.parent,
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())

        # Atomic rename
        os.replace(tmp_path, target)
        logger.info("Config saved to %s", target)
    except BaseException:
        # Clean up temp file on any failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    return target


# ---------------------------------------------------------------------------
# Convenience: create default config
# ---------------------------------------------------------------------------


def create_default_config(home: Path | None = None) -> AionConfig:
    """Create a default configuration with paths resolved.

    This is useful for bootstrapping a fresh installation.

    Args:
        home: Override AION_HOME.  If *None*, uses the default.

    Returns:
        A ready-to-use :class:`AionConfig` with sensible defaults.
    """
    if home:
        os.environ[ENV_HOME] = str(home)

    config = AionConfig()
    config = _resolve_paths(config)
    config = _apply_env_overlays(config)
    return config


# ---------------------------------------------------------------------------
# CLI override parser helper
# ---------------------------------------------------------------------------


def parse_cli_overrides(argv: list[str] | None = None) -> dict[str, Any]:
    """Parse ``--config-key=value`` style CLI arguments.

    Examples::

        --model.provider=openai
        --model.temperature=0.5
        --log_level=DEBUG
        --security.enabled=false

    Args:
        argv: Argument list (defaults to ``sys.argv[1:]``).

    Returns:
        A dict suitable for ``cli_overrides`` in ``load_config()``.
    """
    if argv is None:
        argv = sys.argv[1:]

    overrides: dict[str, Any] = {}
    for arg in argv:
        if arg.startswith("--") and "=" in arg:
            key_val = arg[2:]
            key, _, val = key_val.partition("=")
            # Attempt type coercion
            overrides[key] = _coerce_cli_value(val)
    return overrides


def _coerce_cli_value(val: str) -> Any:
    """Attempt to coerce a CLI string value to the appropriate Python type."""
    # Boolean
    if val.lower() in ("true", "yes", "on", "1"):
        return True
    if val.lower() in ("false", "no", "off", "0"):
        return False
    # Integer
    try:
        return int(val)
    except ValueError:
        pass
    # Float
    try:
        return float(val)
    except ValueError:
        pass
    # JSON list/dict
    if val.startswith(("[", "{")):
        try:
            return json.loads(val)
        except (json.JSONDecodeError, ValueError):
            pass
    return val


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def validate_config(config: AionConfig) -> list[str]:
    """Validate a configuration and return a list of warnings.

    Does not raise — just collects warnings so the caller can decide
    whether to proceed.

    Returns:
        A list of warning strings (empty if all good).
    """
    warnings: list[str] = []

    # Model provider
    if config.model.provider and config.model.provider not in KNOWN_PROVIDERS:
        warnings.append(
            f"Unknown provider '{config.model.provider}'. "
            f"Known: {', '.join(KNOWN_PROVIDERS)}"
        )

    # API key for cloud providers
    if config.model.provider in ("openai", "anthropic", "google", "azure", "mistral", "groq", "cohere"):
        if not config.model.api_key:
            warnings.append(
                f"Provider '{config.model.provider}' typically requires an API key. "
                f"Set {ENV_API_KEY} or configure model.api_key."
            )

    # Log level
    valid_levels = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")
    if config.log_level.upper() not in valid_levels:
        warnings.append(
            f"Invalid log_level '{config.log_level}'. "
            f"Valid: {', '.join(valid_levels)}"
        )

    # Temperature
    if not (0.0 <= config.model.temperature <= 2.0):
        warnings.append(
            f"Model temperature {config.model.temperature} is outside typical range [0.0, 2.0]."
        )

    # Gateway tokens
    if config.gateway.enabled and config.gateway.platforms:
        for platform in config.gateway.platforms:
            if platform == "telegram" and not config.gateway.telegram_bot_token:
                warnings.append("Gateway: Telegram enabled but no bot_token configured.")
            elif platform == "discord" and not config.gateway.discord_bot_token:
                warnings.append("Gateway: Discord enabled but no bot_token configured.")
            elif platform == "slack" and not config.gateway.slack_bot_token:
                warnings.append("Gateway: Slack enabled but no bot_token configured.")

    # Memory limits
    if config.memory.working_max < 10:
        warnings.append("Memory working_max < 10 may cause poor performance.")
    if config.memory.search_default_limit < 1:
        warnings.append("Memory search_default_limit must be >= 1.")

    return warnings


# ---------------------------------------------------------------------------
# Config diff / merge utilities
# ---------------------------------------------------------------------------


def config_diff(a: AionConfig, b: AionConfig) -> dict[str, tuple[Any, Any]]:
    """Compute the difference between two configs.

    Returns:
        A dict mapping field paths to ``(old_value, new_value)`` tuples.
        Only changed fields are included.
    """
    diff: dict[str, tuple[Any, Any]] = {}

    def _compare(path: str, va: Any, vb: Any) -> None:
        if isinstance(va, (list, dict)) and isinstance(vb, (list, dict)):
            if va != vb:
                diff[path] = (va, vb)
        elif va != vb:
            diff[path] = (va, vb)

    top_level = [
        "name", "version", "home_dir", "data_dir", "memory_dir",
        "skills_dir", "tools_dir", "logs_dir", "config_dir",
        "log_level", "debug", "profile",
        "dynamic_enabled", "dynamic_storage_dir",
        "knowledge_enabled", "knowledge_dir",
        "router_enabled", "benchmark_enabled",
    ]
    for attr in top_level:
        _compare(attr, getattr(a, attr), getattr(b, attr))

    sections = [
        ("model", a.model, b.model),
        ("security", a.security, b.security),
        ("memory", a.memory, b.memory),
        ("pipeline", a.pipeline, b.pipeline),
        ("gateway", a.gateway, b.gateway),
        ("cron", a.cron, b.cron),
        ("mcp", a.mcp, b.mcp),
    ]
    for section_name, sa, sb in sections:
        sd = sa.to_dict() if hasattr(sa, "to_dict") else {}
        sd2 = sb.to_dict() if hasattr(sb, "to_dict") else {}
        for k in set(list(sd.keys()) + list(sd2.keys())):
            _compare(f"{section_name}.{k}", sd.get(k), sd2.get(k))

    return diff


def merge_configs(base: AionConfig, overlay: AionConfig) -> AionConfig:
    """Merge *overlay* on top of *base* (non-None overlay values win)."""
    result = copy.deepcopy(base)
    overlay_dict = overlay.to_dict()

    for key, value in overlay_dict.items():
        if value is None or value == "" or value == [] or value == {}:
            continue

        if key in ("model", "security", "memory", "pipeline", "gateway", "cron", "mcp"):
            base_section = getattr(result, key)
            overlay_section = getattr(overlay, key)
            if hasattr(base_section, "from_dict"):
                merged_section_data = {**base_section.to_dict(), **overlay_section.to_dict()}
                setattr(result, key, type(base_section).from_dict(merged_section_data))
        else:
            current = getattr(result, key, None)
            if current is None or value != current:
                setattr(result, key, value)

    return result
