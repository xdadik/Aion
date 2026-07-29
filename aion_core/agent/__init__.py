"""Aion Hand agent module."""

from .credential_pool import (
    CredentialSource,
    CredentialPool,
    PooledCredential,
    RotationStrategy,
)
from .moa_loop import MOAConfig, MOAResult, MixtureOfAgents, PIIFilter
from .background_review import (
    BackgroundReviewer,
    ReviewResult,
    ReviewTask,
)
from .error_classifier import (
    ClassifiedError,
    FailoverReason,
    classify_error,
    ErrorTracker,
    get_recovery_strategy,
)
from .tool_guardrails import ToolGuardrails, ConcurrentToolExecutor, ToolGuardrailConfig
from .context_engine import ContextWindowManager, SummaryCompressor, PruningCompressor, ThreeTierPromptBuilder
from .subagent_lifecycle import SubagentLifecycle, SubagentLaunchRequest, SubagentHandle, SubagentResult, DelegationContext

__all__ = [
    # Existing
    "CredentialSource",
    "CredentialPool",
    "PooledCredential",
    "RotationStrategy",
    "MOAConfig",
    "MOAResult",
    "MixtureOfAgents",
    "PIIFilter",
    "BackgroundReviewer",
    "ReviewResult",
    "ReviewTask",
    # Error classification
    "ClassifiedError",
    "FailoverReason",
    "classify_error",
    "ErrorTracker",
    "get_recovery_strategy",
    # Tool guardrails
    "ToolGuardrails",
    "ConcurrentToolExecutor",
    "ToolGuardrailConfig",
    # Context engine
    "ContextWindowManager",
    "SummaryCompressor",
    "PruningCompressor",
    "ThreeTierPromptBuilder",
    # Subagent lifecycle
    "SubagentLifecycle",
    "SubagentLaunchRequest",
    "SubagentHandle",
    "SubagentResult",
    "DelegationContext",
]
