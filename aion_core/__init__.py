"""Aion Hand public package API.

The package initializer is intentionally lightweight.  Importing ``aion_core``
must not initialize every optional subsystem (network adapters, messaging,
MCP, model providers, etc.).  Heavy modules are exposed lazily through
``__getattr__`` so a small component such as the security policy can be used
without importing the entire application graph.
"""

from __future__ import annotations

from importlib import import_module
from typing import Any

__version__ = "0.3.0"
__author__ = "Aion Hand Contributors"
__license__ = "MIT"

_LAZY_IMPORTS: dict[str, tuple[str, str]] = {
    "AionHand": ("aion_core.agent.core", "AionHand"),
    "AgentLoop": ("aion_core.agent.loop", "AgentLoop"),
    "MemoryManager": ("aion_core.memory.manager", "MemoryManager"),
    "ToolRegistry": ("aion_core.tools.registry", "ToolRegistry"),
    "SkillEngine": ("aion_core.skills.engine", "SkillEngine"),
    "ProviderFactory": ("aion_core.providers.factory", "ProviderFactory"),
    "AionConfig": ("aion_core.config.manager", "AionConfig"),
    "load_config": ("aion_core.config.manager", "load_config"),
    "save_config": ("aion_core.config.manager", "save_config"),
    "get_aion_home": ("aion_core.config.manager", "get_aion_home"),
    "ClassifiedError": ("aion_core.agent.error_classifier", "ClassifiedError"),
    "FailoverReason": ("aion_core.agent.error_classifier", "FailoverReason"),
    "classify_error": ("aion_core.agent.error_classifier", "classify_error"),
    "ErrorTracker": ("aion_core.agent.error_classifier", "ErrorTracker"),
    "get_recovery_strategy": ("aion_core.agent.error_classifier", "get_recovery_strategy"),
    "ToolGuardrails": ("aion_core.agent.tool_guardrails", "ToolGuardrails"),
    "ConcurrentToolExecutor": ("aion_core.agent.tool_guardrails", "ConcurrentToolExecutor"),
    "ToolGuardrailConfig": ("aion_core.agent.tool_guardrails", "ToolGuardrailConfig"),
    "ContextWindowManager": ("aion_core.agent.context_engine", "ContextWindowManager"),
    "SummaryCompressor": ("aion_core.agent.context_engine", "SummaryCompressor"),
    "PruningCompressor": ("aion_core.agent.context_engine", "PruningCompressor"),
    "ThreeTierPromptBuilder": ("aion_core.agent.context_engine", "ThreeTierPromptBuilder"),
    "SubagentLifecycle": ("aion_core.agent.subagent_lifecycle", "SubagentLifecycle"),
    "SubagentLaunchRequest": ("aion_core.agent.subagent_lifecycle", "SubagentLaunchRequest"),
    "SubagentHandle": ("aion_core.agent.subagent_lifecycle", "SubagentHandle"),
    "SubagentResult": ("aion_core.agent.subagent_lifecycle", "SubagentResult"),
    "DelegationContext": ("aion_core.agent.subagent_lifecycle", "DelegationContext"),
    "CredentialPool": ("aion_core.agent.credential_pool", "CredentialPool"),
    "PooledCredential": ("aion_core.agent.credential_pool", "PooledCredential"),
    "RotationStrategy": ("aion_core.agent.credential_pool", "RotationStrategy"),
    "MixtureOfAgents": ("aion_core.agent.moa_loop", "MixtureOfAgents"),
    "MOAConfig": ("aion_core.agent.moa_loop", "MOAConfig"),
    "MOAResult": ("aion_core.agent.moa_loop", "MOAResult"),
    "BackgroundReviewer": ("aion_core.agent.background_review", "BackgroundReviewer"),
    "SecretRedactor": ("aion_core.security.redact", "SecretRedactor"),
    "redact_string": ("aion_core.security.redact", "redact_string"),
    "redact_dict": ("aion_core.security.redact", "redact_dict"),
    "detect_secrets": ("aion_core.security.redact", "detect_secrets"),
    "FileSafetyChecker": ("aion_core.security.filesafety", "FileSafetyChecker"),
    "PlatformType": ("aion_core.messaging.platforms", "PlatformType"),
    "PlatformAdapter": ("aion_core.messaging.platforms", "PlatformAdapter"),
    "PlatformRegistry": ("aion_core.messaging.platforms", "PlatformRegistry"),
    "create_platform": ("aion_core.messaging.platforms", "create_platform"),
    "RuntimeStatus": ("aion_core.runtime.production", "RuntimeStatus"),
    "build_provider": ("aion_core.runtime.production", "build_provider"),
    "provider_health_check": ("aion_core.runtime.production", "provider_health_check"),
    "resolve_api_key": ("aion_core.runtime.production", "resolve_api_key"),
    "runtime_diagnostics": ("aion_core.runtime.production", "runtime_diagnostics"),
    "create_production_agent": ("aion_core.runtime.agent", "create_production_agent"),
    "AutonomousRunner": ("aion_core.automation.autonomous", "AutonomousRunner"),
    "AutomationResult": ("aion_core.automation.autonomous", "AutomationResult"),
    "AutomationTask": ("aion_core.automation.autonomous", "AutomationTask"),
}

__all__ = list(_LAZY_IMPORTS)


def __getattr__(name: str) -> Any:
    """Load public components only when they are actually requested."""
    target = _LAZY_IMPORTS.get(name)
    if target is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attribute_name = target
    module = import_module(module_name)
    value = getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(__all__))
