"""
Dynamic Agent System for Aion Hand.
=====================================

Spins up specialized agents on demand, orchestrates their execution
across learned topologies, and continuously improves through
pattern recognition and topology evolution.

Architecture:
    DynamicManager (high-level API)
        -> DynamicOrchestrator (coordination)
            -> DynamicAgentFactory (create/destroy agents)
            -> TopologyManager (learn/suggest/evolve topologies)

Quick start:
    from aion_core.dynamic import DynamicManager

    mgr = DynamicManager()
    await mgr.initialize()
    result = await mgr.execute("Build a REST API with JWT auth", complexity=7)
    await mgr.shutdown()
"""

from .agent_factory import (
    AgentProfile,
    DynamicAgent,
    DynamicAgentFactory,
    AgentRole,
)
from .topology import (
    AgentTopology,
    TopologyManager,
)
from .orchestrator import (
    DynamicOrchestrationPlan,
    DynamicOrchestrator,
)
from .manager import (
    DynamicManager,
)

__all__ = [
    # Data models
    "AgentProfile",
    "DynamicAgent",
    "AgentRole",
    "AgentTopology",
    "DynamicOrchestrationPlan",
    # Core services
    "DynamicAgentFactory",
    "TopologyManager",
    "DynamicOrchestrator",
    "DynamicManager",
]
