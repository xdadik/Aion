"""
AutoKnowledgeBuilder — Automatically builds the knowledge graph from agent
activity: conversations, tool executions, task completions, skill usage, and
memory operations.
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

from .graph import KnowledgeGraph

logger = logging.getLogger(__name__)


class AutoKnowledgeBuilder:
    """Automatically extracts entities and relations from agent activity."""

    # Patterns used for naive entity extraction from free text
    _QUOTED_RE = re.compile(r'"([^"]+)"|\'([^\']+)\'')
    _WORD_RE = re.compile(r'\b([A-Za-z][A-Za-z0-9_.\-/]{2,})\b')

    # Keywords that suggest entity types
    _TYPE_HINTS: Dict[str, str] = {
        "file": "file",
        "tool": "tool",
        "skill": "skill",
        "task": "task",
        "project": "project",
        "error": "error",
        "agent": "agent",
        "person": "person",
    }

    def __init__(self, graph: KnowledgeGraph) -> None:
        self._graph = graph

    # ------------------------------------------------------------------
    # Conversation
    # ------------------------------------------------------------------

    def from_conversation(
        self,
        user_msg: str,
        agent_response: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Extract entities and relations from a conversation turn.

        Strategy:
        * Extract named "things" from both messages.
        * Link entities mentioned together in the same turn with
          ``related_to``.
        * If metadata includes ``tool_used``, create a ``uses`` relation.
        """
        metadata = metadata or {}

        mentioned: List[tuple] = []

        # Extract from user message
        user_entities = self._extract_entities_from_text(user_msg)
        mentioned.extend(user_entities)

        # Extract from agent response
        agent_entities = self._extract_entities_from_text(agent_response)
        mentioned.extend(agent_entities)

        # Deduplicate by (name, type)
        seen: set = set()
        entity_nodes = []
        for name, etype in mentioned:
            key = (name, etype)
            if key not in seen:
                seen.add(key)
                entity = self._graph.add_entity(name=name, entity_type=etype)
                entity_nodes.append(entity)

        # Link entities mentioned in the same turn
        for i, e1 in enumerate(entity_nodes):
            for e2 in entity_nodes[i + 1:]:
                self._graph.add_relation(
                    source_id=e1.id,
                    target_id=e2.id,
                    relation_type="related_to",
                    weight=0.3,
                )

        # If metadata mentions a tool, connect it
        tool_name = metadata.get("tool_used")
        if tool_name:
            tool_ent = self._graph.add_entity(name=str(tool_name), entity_type="tool")
            for ent in entity_nodes:
                self._graph.add_relation(
                    source_id=tool_ent.id,
                    target_id=ent.id,
                    relation_type="uses",
                    weight=0.6,
                )

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def from_tool_execution(
        self,
        tool_name: str,
        params: Dict[str, Any],
        result: Any,
    ) -> None:
        """
        Record a tool execution: create/update the tool entity, link
        parameter-referenced files/concepts, and record success/failure.
        """
        success = not isinstance(result, Exception) and not (
            isinstance(result, dict) and result.get("error")
        )

        existing = self._graph.find_entities(
            name_contains=str(tool_name), entity_type="tool", limit=1
        )

        if existing:
            existing[0].properties["execution_count"] = (
                existing[0].properties.get("execution_count", 0) + 1
            )
            existing[0].properties["last_params"] = {
                k: str(v)[:200] for k, v in params.items()
            }
            existing[0].properties["last_result"] = str(result)[:300]
            existing[0].properties["success"] = success
            tool_ent = existing[0]
        else:
            tool_ent = self._graph.add_entity(
                name=str(tool_name),
                entity_type="tool",
                properties={
                    "last_params": {k: str(v)[:200] for k, v in params.items()},
                    "execution_count": 1,
                    "last_result": str(result)[:300],
                    "success": success,
                },
            )

        # Extract file-like entities from params
        for _, value in params.items():
            val_str = str(value)
            if any(val_str.endswith(ext) for ext in (".py", ".js", ".ts", ".json", ".yaml", ".md", ".txt")):
                file_ent = self._graph.add_entity(
                    name=val_str.split("/")[-1],
                    entity_type="file",
                    properties={"full_path": val_str},
                )
                self._graph.add_relation(
                    source_id=tool_ent.id,
                    target_id=file_ent.id,
                    relation_type="uses",
                    weight=0.7,
                )

        # Record concept-like string values as concepts
        for value in params.values():
            if isinstance(value, str) and len(value) > 3 and len(value) < 80:
                if "/" not in value and not value.endswith((".py", ".json", ".yaml")):
                    concept = self._graph.add_entity(name=value, entity_type="concept")
                    self._graph.add_relation(
                        source_id=tool_ent.id,
                        target_id=concept.id,
                        relation_type="uses",
                        weight=0.4,
                    )

    # ------------------------------------------------------------------
    # Task completion
    # ------------------------------------------------------------------

    def from_task_completion(
        self,
        task: str,
        result: Any,
        success: bool,
    ) -> None:
        """Record the outcome of a task, creating an error entity on failure."""
        task_ent = self._graph.add_entity(
            name=str(task)[:200],
            entity_type="task",
            properties={
                "success": success,
                "result_summary": str(result)[:500],
            },
        )

        if not success:
            error_msg = str(result)[:300] if result else "Unknown error"
            error_ent = self._graph.add_entity(
                name=error_msg,
                entity_type="error",
                properties={"associated_task": str(task)},
            )
            self._graph.add_relation(
                source_id=error_ent.id,
                target_id=task_ent.id,
                relation_type="caused",
                weight=0.9,
            )
            self._graph.add_relation(
                source_id=task_ent.id,
                target_id=error_ent.id,
                relation_type="failed_because",
                weight=0.9,
            )

    # ------------------------------------------------------------------
    # Skill usage
    # ------------------------------------------------------------------

    def from_skill_usage(self, skill_name: str, success: bool) -> None:
        """Record skill performance.  add_entity deduplicates, so we always
        get the canonical entity back and can safely increment counters."""
        skill_ent = self._graph.add_entity(
            name=str(skill_name),
            entity_type="skill",
        )
        props = skill_ent.properties
        total = props.get("total_uses", 0) + 1
        successes = props.get("successes", 0) + (1 if success else 0)
        props.update({
            "total_uses": total,
            "successes": successes,
            "success_rate": round(successes / total, 3) if total else 0,
        })

    # ------------------------------------------------------------------
    # Memory
    # ------------------------------------------------------------------

    def from_memory(self, content: str, memory_type: str = "concept") -> None:
        """
        Connect a memory content to existing entities.  If the content
        mentions entities by name, create ``related_to`` links.
        """
        mem_ent = self._graph.add_entity(
            name=str(content)[:150],
            entity_type="memory",
            properties={"memory_type": memory_type},
        )

        # Find entities whose name appears in the memory content
        content_lower = content.lower()
        for entity in self._graph.find_entities(limit=500):
            if entity.id == mem_ent.id:
                continue
            if entity.name.lower() in content_lower:
                self._graph.add_relation(
                    source_id=mem_ent.id,
                    target_id=entity.id,
                    relation_type="related_to",
                    weight=0.5,
                )

    # ------------------------------------------------------------------
    # Pattern discovery
    # ------------------------------------------------------------------

    def discover_patterns(self) -> Dict[str, Any]:
        """Analyse the graph for interesting patterns."""
        patterns: Dict[str, Any] = {}

        # --- Co-occurring tools ---
        tool_nodes = self._graph.find_entities(entity_type="tool")
        tool_graph: Dict[str, set] = defaultdict(set)
        for t1 in tool_nodes:
            related = self._graph.get_related_entities(t1.id, depth=2)
            for r in related:
                if r.entity_type == "tool" and r.id != t1.id:
                    tool_graph[t1.name].add(r.name)

        co_occurring = []
        for tool, peers in tool_graph.items():
            if peers:
                co_occurring.append({"tool": tool, "co_occurs_with": sorted(peers)})
        co_occurring.sort(key=lambda x: len(x["co_occurs_with"]), reverse=True)
        patterns["co_occurring_tools"] = co_occurring[:10]

        # --- Failure patterns ---
        error_nodes = self._graph.find_entities(entity_type="error")
        failure_patterns: List[Dict[str, Any]] = []
        for err in error_nodes:
            fixes = self._graph.get_relations(
                entity_id=err.id, relation_type="fixed_by"
            )
            tasks = self._graph.get_relations(
                entity_id=err.id, relation_type="caused"
            )
            caused_by = self._graph.get_relations(
                entity_id=err.id, relation_type="related_to", direction="out"
            )
            failure_patterns.append({
                "error": err.name,
                "has_fix": bool(fixes),
                "affected_tasks": [self._graph.get_entity(t.target_id).name if self._graph.get_entity(t.target_id) else "unknown" for t in tasks],
                "related_entities": len(caused_by),
            })
        patterns["failure_patterns"] = failure_patterns[:10]

        # --- Successful strategies ---
        successful_tasks = [
            e for e in self._graph.find_entities(entity_type="task")
            if e.properties.get("success") is True
        ]
        strategies: List[Dict[str, Any]] = []
        for task in successful_tasks:
            tools_used = self._graph.get_relations(
                entity_id=task.id, relation_type="uses"
            )
            tool_names = []
            for rel in tools_used:
                tool_ent = self._graph.get_entity(rel.target_id)
                if tool_ent:
                    tool_names.append(tool_ent.name)
            if tool_names:
                strategies.append({
                    "task": task.name,
                    "tools_used": tool_names,
                })
        patterns["successful_strategies"] = strategies[:10]

        # --- Skill performance ranking ---
        skill_nodes = self._graph.find_entities(entity_type="skill")
        skill_ranking = []
        for sk in skill_nodes:
            props = sk.properties
            if "total_uses" in props:
                skill_ranking.append({
                    "skill": sk.name,
                    "uses": props["total_uses"],
                    "success_rate": props.get("success_rate", 0),
                })
        skill_ranking.sort(key=lambda x: x["success_rate"], reverse=True)
        patterns["skill_ranking"] = skill_ranking[:10]

        return patterns

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _extract_entities_from_text(self, text: str) -> List[tuple]:
        """Naive extraction of (name, entity_type) pairs from text."""
        entities: List[tuple] = []

        # Quoted strings are often file names or specific identifiers
        for match in self._QUOTED_RE.finditer(text):
            name = match.group(1) or match.group(2) or ""
            name = name.strip()
            if not name:
                continue
            etype = "file" if self._looks_like_file(name) else "concept"
            entities.append((name, etype))

        # Word-level extraction
        words = self._WORD_RE.findall(text)
        for word in words:
            lower = word.lower()
            if lower in self._TYPE_HINTS:
                continue  # skip the keyword itself
            # Check for file-like tokens
            if self._looks_like_file(word):
                entities.append((word, "file"))
            elif self._looks_like_tool_name(word):
                entities.append((word, "tool"))

        return entities

    @staticmethod
    def _looks_like_file(name: str) -> bool:
        file_extensions = (
            ".py", ".js", ".ts", ".json", ".yaml", ".yml", ".toml",
            ".md", ".txt", ".csv", ".html", ".css", ".sh", ".cfg",
            ".ini", ".xml", ".sql",
        )
        return any(name.endswith(ext) for ext in file_extensions)

    @staticmethod
    def _looks_like_tool_name(name: str) -> bool:
        """Heuristic: CamelCase or snake_case names with common tool suffixes."""
        if not name:
            return False
        # Common tool/action verbs
        tool_prefixes = ("read", "write", "search", "fetch", "execute", "run",
                         "build", "create", "delete", "update", "list", "get",
                         "set", "find", "parse", "format", "compile", "deploy")
        lower = name.lower().replace("-", "_")
        return any(lower.startswith(prefix + "_") or lower == prefix
                   for prefix in tool_prefixes)
