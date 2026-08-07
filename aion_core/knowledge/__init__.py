"""
Aion Hand Knowledge Graph System
===================================

Lets the agent reason over RELATIONSHIPS between entities, not just retrieve text.

Core components:
  - KnowledgeGraph: in-memory graph with JSON persistence, BFS/DFS traversal, search
  - Entity / Relation: typed dataclasses with weights and properties
  - AutoKnowledgeBuilder: automatically builds graph from agent activity
  - GraphReasoner: reasons over the graph for context, tools, risks, strategy
  - KnowledgeManager: high-level API combining all of the above

Usage::

    from aion_core.knowledge import KnowledgeManager

    km = KnowledgeManager(".aion/knowledge")
    km.initialize()

    km.record("conversation", {
        "user_msg": "Build a REST API",
        "agent_response": "I'll create FastAPI endpoints...",
        "metadata": {"tool_used": "write_file"},
    })

    context = km.query("Build a REST API with authentication")
    km.save()
"""

from .auto_builder import AutoKnowledgeBuilder
from .graph import Entity, KnowledgeGraph, Relation
from .manager import KnowledgeManager
from .reasoner import GraphReasoner

__all__ = [
    "KnowledgeManager",
    "KnowledgeGraph",
    "Entity",
    "Relation",
    "AutoKnowledgeBuilder",
    "GraphReasoner",
]
