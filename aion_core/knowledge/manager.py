"""
KnowledgeManager — High-level API that combines the KnowledgeGraph,
AutoKnowledgeBuilder, and GraphReasoner into a single interface for the
Aion Hand agent.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .auto_builder import AutoKnowledgeBuilder
from .graph import KnowledgeGraph
from .reasoner import GraphReasoner

logger = logging.getLogger(__name__)


class KnowledgeManager:
    """
    High-level knowledge management interface.

    Usage::

        km = KnowledgeManager("/path/to/storage")
        km.initialize()

        km.record("conversation", {
            "user_msg": "Build a REST API",
            "agent_response": "I'll create FastAPI endpoints...",
            "metadata": {"tool_used": "write_file"},
        })

        context = km.query("Build a REST API with authentication")
        km.save()
        km.shutdown()
    """

    def __init__(self, storage_dir: str | Path = ".aion/knowledge") -> None:
        self.storage_dir = Path(storage_dir)
        self._graph = KnowledgeGraph()
        self._builder = AutoKnowledgeBuilder(self._graph)
        self._reasoner = GraphReasoner(self._graph)
        self._initialized = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def initialize(self) -> None:
        """Load the graph from disk (no error if files don't exist yet)."""
        if self.storage_dir.exists():
            self._graph.load(self.storage_dir)
            logger.info(
                "Loaded knowledge graph: %s", self._graph
            )
        else:
            logger.info("No existing knowledge graph at %s — starting fresh.", self.storage_dir)
        self._initialized = True

    def save(self) -> None:
        """Persist the graph to disk."""
        self._graph.save(self.storage_dir)
        logger.info("Saved knowledge graph to %s", self.storage_dir)

    def shutdown(self) -> None:
        """Save and release resources."""
        if self._initialized:
            self.save()
        self._initialized = False
        logger.info("KnowledgeManager shut down.")

    # ------------------------------------------------------------------
    # Event recording
    # ------------------------------------------------------------------

    def record(self, event_type: str, data: dict[str, Any]) -> None:
        """
        Route an event to the appropriate builder method.

        Supported *event_type* values:
        - ``"conversation"``  — data keys: ``user_msg``, ``agent_response``, ``metadata``
        - ``"tool_execution"``— data keys: ``tool_name``, ``params``, ``result``
        - ``"task_completion"``— data keys: ``task``, ``result``, ``success``
        - ``"skill_usage"``   — data keys: ``skill_name``, ``success``
        - ``"memory"``         — data keys: ``content``, ``type``
        """
        try:
            if event_type == "conversation":
                self._builder.from_conversation(
                    user_msg=data.get("user_msg", ""),
                    agent_response=data.get("agent_response", ""),
                    metadata=data.get("metadata"),
                )
            elif event_type == "tool_execution":
                self._builder.from_tool_execution(
                    tool_name=data.get("tool_name", ""),
                    params=data.get("params", {}),
                    result=data.get("result", ""),
                )
            elif event_type == "task_completion":
                self._builder.from_task_completion(
                    task=data.get("task", ""),
                    result=data.get("result", ""),
                    success=data.get("success", False),
                )
            elif event_type == "skill_usage":
                self._builder.from_skill_usage(
                    skill_name=data.get("skill_name", ""),
                    success=data.get("success", False),
                )
            elif event_type == "memory":
                self._builder.from_memory(
                    content=data.get("content", ""),
                    memory_type=data.get("type", "concept"),
                )
            else:
                logger.warning("Unknown event_type: %s", event_type)
        except Exception:
            logger.exception("Error recording %s event", event_type)

    # ------------------------------------------------------------------
    # Querying
    # ------------------------------------------------------------------

    def query(self, task: str) -> dict[str, Any]:
        """
        Full context query for a task.  Returns entities, tool suggestions,
        risk predictions, strategy, and similar tasks all in one call.
        """
        return {
            "context": self._reasoner.get_context_for_task(task),
            "suggested_tools": self._reasoner.suggest_tools(task),
            "predicted_risks": self._reasoner.predict_risks(task),
            "suggested_strategy": self._reasoner.suggest_strategy(task),
        }

    def search(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search across all knowledge for entities matching the query."""
        entities = self._graph.semantic_search(query, limit=limit)
        return [
            {
                "id": e.id,
                "name": e.name,
                "type": e.entity_type,
                "properties": e.properties,
            }
            for e in entities
        ]

    # ------------------------------------------------------------------
    # Statistics & patterns
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Full graph statistics plus discovered patterns."""
        return {
            "graph": self._graph.get_stats(),
            "patterns": self._builder.discover_patterns(),
        }

    # ------------------------------------------------------------------
    # Direct graph access (for advanced usage)
    # ------------------------------------------------------------------

    @property
    def graph(self) -> KnowledgeGraph:
        """Direct access to the underlying KnowledgeGraph."""
        return self._graph

    @property
    def builder(self) -> AutoKnowledgeBuilder:
        """Direct access to the AutoKnowledgeBuilder."""
        return self._builder

    @property
    def reasoner(self) -> GraphReasoner:
        """Direct access to the GraphReasoner."""
        return self._reasoner

    def __repr__(self) -> str:
        return (
            f"KnowledgeManager(graph={self._graph}, "
            f"storage={self.storage_dir})"
        )
