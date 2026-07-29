"""
Aion Hand - The Ultimate Autonomous AI Agent Framework
=========================================================

Aion Hand combines the best features from:
  - OpenClaw: Personal AI assistant with messaging gateway, skills, and memory
  - NullClaw: Ultra-lightweight Zig-based execution runtime
  - Hermes Agent: Self-improving learning loop, FTS5 memory, subagents
  - CrewAI: Multi-agent orchestration with role-based design
  - LangGraph: Stateful agent graphs and workflow management
  - AutoGen: Multi-agent conversation patterns

Core Philosophy:
  - Provider Agnostic: Works with any LLM provider
  - Self-Improving: Built-in learning loop that creates and refines skills
  - Multi-Agent: Subagent spawning for parallel workflows
  - Extensible: MCP-compatible tool system with 40+ built-in tools
  - Persistent Memory: Multi-layer memory with FTS5 search
  - Cross-Platform: Runs anywhere - local, Docker, cloud, edge
  - Open Source: MIT Licensed

Usage:
    from aion_core import AionHand

    agent = AionHand()
    agent.start()
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

# ── Config ──
from aion_core.config.manager import AionConfig, load_config, save_config, get_aion_home

# ── Agent ──
from aion_core.agent.error_classifier import ClassifiedError, FailoverReason, classify_error, ErrorTracker, get_recovery_strategy
from aion_core.agent.tool_guardrails import ToolGuardrails, ConcurrentToolExecutor, ToolGuardrailConfig
from aion_core.agent.context_engine import ContextWindowManager, SummaryCompressor, PruningCompressor, ThreeTierPromptBuilder
from aion_core.agent.subagent_lifecycle import SubagentLifecycle, SubagentLaunchRequest, SubagentHandle, SubagentResult, DelegationContext
from aion_core.agent.credential_pool import CredentialPool, PooledCredential, RotationStrategy
from aion_core.agent.moa_loop import MixtureOfAgents, MOAConfig, MOAResult
from aion_core.agent.background_review import BackgroundReviewer

# ── Security ──
from aion_core.security.redact import SecretRedactor, redact_string, redact_dict, detect_secrets
from aion_core.security.filesafety import FileSafetyChecker

# ── Messaging ──
from aion_core.messaging.platforms import PlatformType, PlatformAdapter, PlatformRegistry, create_platform

__all__ = [
    # Core
    "AionHand",
    "AgentLoop",
    "MemoryManager",
    "ToolRegistry",
    "SkillEngine",
    "ProviderFactory",
    # Config
    "AionConfig",
    "load_config",
    "save_config",
    "get_aion_home",
    # Agent
    "ClassifiedError",
    "FailoverReason",
    "classify_error",
    "ErrorTracker",
    "get_recovery_strategy",
    "ToolGuardrails",
    "ConcurrentToolExecutor",
    "ToolGuardrailConfig",
    "ContextWindowManager",
    "SummaryCompressor",
    "PruningCompressor",
    "ThreeTierPromptBuilder",
    "SubagentLifecycle",
    "SubagentLaunchRequest",
    "SubagentHandle",
    "SubagentResult",
    "DelegationContext",
    "CredentialPool",
    "PooledCredential",
    "RotationStrategy",
    "MixtureOfAgents",
    "MOAConfig",
    "MOAResult",
    "BackgroundReviewer",
    # Security
    "SecretRedactor",
    "redact_string",
    "redact_dict",
    "detect_secrets",
    "FileSafetyChecker",
    # Messaging
    "PlatformType",
    "PlatformAdapter",
    "PlatformRegistry",
    "create_platform",
]
