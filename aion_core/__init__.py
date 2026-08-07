"""
Aion Hand - The Ultimate Autonomous AI Agent Framework
=========================================================

A modular autonomous agent runtime with provider abstraction, persistent
memory, tool use, orchestration, automation, and security controls.
"""

__version__ = "0.3.0"
__author__ = "Aion Hand Contributors"
__license__ = "MIT"

try:
    from aion_core.agent.core import AionHand
except ImportError:
    AionHand = None  # type: ignore[assignment,misc]
try:
    from aion_core.agent.loop import AgentLoop
except ImportError:
    AgentLoop = None  # type: ignore[assignment,misc]
try:
    from aion_core.memory.manager import MemoryManager
except ImportError:
    MemoryManager = None  # type: ignore[assignment,misc]
try:
    from aion_core.tools.registry import ToolRegistry
except ImportError:
    ToolRegistry = None  # type: ignore[assignment,misc]
try:
    from aion_core.skills.engine import SkillEngine
except ImportError:
    SkillEngine = None  # type: ignore[assignment,misc]
try:
    from aion_core.providers.factory import ProviderFactory
except ImportError:
    ProviderFactory = None  # type: ignore[assignment,misc]

from aion_core.config.manager import AionConfig, get_aion_home, load_config, save_config
from aion_core.agent.error_classifier import ClassifiedError, FailoverReason, classify_error, ErrorTracker, get_recovery_strategy
from aion_core.agent.tool_guardrails import ToolGuardrails, ConcurrentToolExecutor, ToolGuardrailConfig
from aion_core.agent.context_engine import ContextWindowManager, SummaryCompressor, PruningCompressor, ThreeTierPromptBuilder
from aion_core.agent.subagent_lifecycle import SubagentLifecycle, SubagentLaunchRequest, SubagentHandle, SubagentResult, DelegationContext
from aion_core.agent.credential_pool import CredentialPool, PooledCredential, RotationStrategy
from aion_core.agent.moa_loop import MixtureOfAgents, MOAConfig, MOAResult
from aion_core.agent.background_review import BackgroundReviewer
from aion_core.security.redact import SecretRedactor, redact_string, redact_dict, detect_secrets
from aion_core.security.filesafety import FileSafetyChecker
from aion_core.messaging.platforms import PlatformType, PlatformAdapter, PlatformRegistry, create_platform
from aion_core.runtime.production import RuntimeStatus, build_provider, provider_health_check, resolve_api_key, runtime_diagnostics
from aion_core.runtime.agent import create_production_agent
from aion_core.automation.autonomous import AutonomousRunner, AutomationResult, AutomationTask

__all__ = [
    "AionHand", "AgentLoop", "MemoryManager", "ToolRegistry", "SkillEngine", "ProviderFactory",
    "AionConfig", "load_config", "save_config", "get_aion_home",
    "ClassifiedError", "FailoverReason", "classify_error", "ErrorTracker", "get_recovery_strategy",
    "ToolGuardrails", "ConcurrentToolExecutor", "ToolGuardrailConfig",
    "ContextWindowManager", "SummaryCompressor", "PruningCompressor", "ThreeTierPromptBuilder",
    "SubagentLifecycle", "SubagentLaunchRequest", "SubagentHandle", "SubagentResult", "DelegationContext",
    "CredentialPool", "PooledCredential", "RotationStrategy", "MixtureOfAgents", "MOAConfig", "MOAResult",
    "BackgroundReviewer", "SecretRedactor", "redact_string", "redact_dict", "detect_secrets", "FileSafetyChecker",
    "PlatformType", "PlatformAdapter", "PlatformRegistry", "create_platform",
    "RuntimeStatus", "build_provider", "provider_health_check", "resolve_api_key", "runtime_diagnostics",
    "create_production_agent", "AutonomousRunner", "AutomationResult", "AutomationTask",
]
