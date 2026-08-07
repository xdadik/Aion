"""Aion Hand agent module."""

from .background_review import (
    BackgroundReviewer,
    ReviewResult,
    ReviewTask,
)
from .context_engine import (
    ContextWindowManager,
    PruningCompressor,
    SummaryCompressor,
    ThreeTierPromptBuilder,
)
from .credential_pool import (
    CredentialPool,
    CredentialSource,
    PooledCredential,
    RotationStrategy,
)
from .error_classifier import (
    ClassifiedError,
    ErrorTracker,
    FailoverReason,
    classify_error,
    get_recovery_strategy,
)
from .moa_loop import MixtureOfAgents, MOAConfig, MOAResult, PIIFilter
from .subagent_lifecycle import (
    DelegationContext,
    SubagentHandle,
    SubagentLaunchRequest,
    SubagentLifecycle,
    SubagentResult,
)
from .tool_guardrails import ConcurrentToolExecutor, ToolGuardrailConfig, ToolGuardrails

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
