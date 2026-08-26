"""
Aion Hand Configuration System
================================

Hermes-inspired configuration management with:
  - YAML/JSON config file support (zero external dependencies — JSON fallback)
  - Profile-based configuration directories
  - AION_HOME environment variable resolution
  - Type-safe environment variable readers
  - Merge priority: CLI args > env vars > config file > defaults

Quick start::

    from aion_core.config import AionConfig, load_config, get_aion_home

    config = load_config()
    print(config.model.name)
    print(get_aion_home())
"""

from aion_core.config.manager import (
    AionConfig,
    CronConfig,
    GatewayConfig,
    MCPConfig,
    MemoryConfig,
    ModelConfig,
    PipelineConfig,
    SecurityConfig,
    env_bool,
    env_float,
    env_int,
    env_str,
    get_aion_home,
    load_config,
    normalize_proxy_env_vars,
    save_config,
)

__all__ = [
    # Core
    "AionConfig",
    "load_config",
    "save_config",
    "get_aion_home",
    # Sub-configs
    "ModelConfig",
    "SecurityConfig",
    "MemoryConfig",
    "PipelineConfig",
    "GatewayConfig",
    "CronConfig",
    "MCPConfig",
    # Utilities
    "env_int",
    "env_float",
    "env_bool",
    "env_str",
    "normalize_proxy_env_vars",
]
