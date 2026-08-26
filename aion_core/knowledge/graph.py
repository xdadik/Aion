"""
Knowledge Graph - Core graph data structure for Aion Hand.

Provides Entity and Relation dataclasses and a KnowledgeGraph class with
full CRUD, graph traversal (BFS/DFS), clustering, persistence, and search.
"""

from __future__ import annotations

import json
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field, asdict
from datetime import datetime, UTC
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

ENTITY_TYPES = (
    "person", "project", "file", "tool", "concept",
    "task", "agent", "memory", "error", "skill",
)

RELATION_TYPES = (
    "uses", "depends_on", "created_by", "related_to",
    "caused", "fixed_by", "part_of", "similar_to",
    "succeeded_after", "failed_because",
)


@dataclass
class Entity:
    """A node in the knowledge graph."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    name: str = ""
    entity_type: str = "concept"
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    updated_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )
    access_count: int = 0

    def touch(self) -> None:
        """Update the *updated_at* timestamp and bump access count."""
        self.updated_at = datetime.now(UTC).isoformat()
        self.access_count += 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entity:
        return cls(**data)


@dataclass
class Relation:
    """A directed, weighted edge in the knowledge graph."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:16])
    source_id: str = ""
    target_id: str = ""
    relation_type: str = "related_to"
    weight: float = 0.5
    properties: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat(),
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Relation:
        return cls(**data)


# ---------------------------------------------------------------------------
# KnowledgeGraph
# ---------------------------------------------------------------------------

class KnowledgeGraph:
    """In-memory knowledge graph with JSON persistence and graph algorithms."""

    def __init__(self) -> None:
        # Primary storage
        self._entities: dict[str, Entity] = {}
        self._relations: dict[str, Relation] = {}

        # Adjacency lists for fast traversal
        self._outgoing: dict[str, list[str]] = defaultdict(list)   # entity_id -> [relation_ids]
        self._incoming: dict[str, list[str]] = defaultdict(list)   # entity_id -> [relation_ids]

        # Name+type dedup index: (name, type) -> entity_id
        self._dedup_index: dict[tuple[str, str], str] = {}

    # ------------------------------------------------------------------
    # Entity CRUD
    # ------------------------------------------------------------------

    def add_entity(
        self,
        name: str,
        entity_type: str = "concept",
        properties: dict[str, Any] | None = None,
        entity_id: str | None = None,
    ) -> Entity:
        """Create an entity, deduplicating on (name, entity_type)."""
        if entity_type not in ENTITY_TYPES:
            raise ValueError(
                f"Invalid entity_type '{entity_type}'. Must be one of {ENTITY_TYPES}"
            )

        key = (name.lower().strip(), entity_type)
        if key in self._dedup_index:
            existing = self._entities[self._dedup_index[key]]
            existing.touch()
            # Merge in any new properties
            if properties:
                existing.properties.update(properties)
            return existing

        entity = Entity(
            id=entity_id or uuid.uuid4().hex[:16],
            name=name.strip(),
            entity_type=entity_type,
            properties=properties or {},
        )
        self._entities[entity.id] = entity
        self._dedup_index[key] = entity.id
        return entity

    def get_entity(self, entity_id: str) -> Entity | None:
        """Return an entity by id, bumping its access count."""
        entity = self._entities.get(entity_id)
        if entity is not None:
            entity.touch()
        return entity

    def find_entities(
        self,
        entity_type: str | None = None,
        name_contains: str | None = None,
        properties_filter: dict[str, Any] | None = None,
        limit: int = 100,
    ) -> list[Entity]:
        """Find entities matching optional type / name / property filters."""
        results: list[Entity] = []
        for entity in self._entities.values():
            if entity_type and entity.entity_type != entity_type:
                continue
            if name_contains and name_contains.lower() not in entity.name.lower():
                continue
            if properties_filter:
                if not all(
                    entity.properties.get(k) == v
                    for k, v in properties_filter.items()
                ):
                    continue
            results.append(entity)
            if len(results) >= limit:
                break
        return results

    def update_entity(
        self,
        entity_id: str,
        properties: dict[str, Any] | None = None,
        name: str | None = None,
    ) -> Entity | None:
        """Update an existing entity's name and/or properties."""
        entity = self._entities.get(entity_id)
        if entity is None:
            return None
        if name and name.strip() != entity.name:
            old_key = (entity.name.lower().strip(), entity.entity_type)
            self._dedup_index.pop(old_key, None)
            entity.name = name.strip()
            new_key = (entity.name.lower().strip(), entity.entity_type)
            self._dedup_index[new_key] = entity.id
        if properties:
            entity.properties.update(properties)
        entity.touch()
        return entity

    def remove_entity(self, entity_id: str) -> bool:
        """Remove an entity and **all** its incident relations."""
        entity = self._entities.pop(entity_id, None)
        if entity is None:
            return False
        key = (entity.name.lower().strip(), entity.entity_type)
        self._dedup_index.pop(key, None)

        # Collect relation ids to remove
        rel_ids = set(self._outgoing.get(entity_id, []))
        rel_ids.update(self._incoming.get(entity_id, []))
        for rid in rel_ids:
            self._remove_relation(rid)

        self._outgoing.pop(entity_id, None)
        self._incoming.pop(entity_id, None)
        return True

    # ------------------------------------------------------------------
    # Relation CRUD
    # ------------------------------------------------------------------

    def add_relation(
        self,
        source_id: str,
        target_id: str,
        relation_type: str = "related_to",
        weight: float = 0.5,
        properties: dict[str, Any] | None = None,
        relation_id: str | None = None,
    ) -> Relation | None:
        """Create a relation between two existing entities."""
        if source_id not in self._entities or target_id not in self._entities:
            return None
        if relation_type not in RELATION_TYPES:
            raise ValueError(
                f"Invalid relation_type '{relation_type}'. Must be one of {RELATION_TYPES}"
            )
        weight = max(0.0, min(1.0, weight))

        rel = Relation(
            id=relation_id or uuid.uuid4().hex[:16],
            source_id=source_id,
            target_id=target_id,
            relation_type=relation_type,
            weight=weight,
            properties=properties or {},
        )
        self._relations[rel.id] = rel
        self._outgoing[source_id].append(rel.id)
        self._incoming[target_id].append(rel.id)
        return rel

    def get_relation(self, relation_id: str) -> Relation | None:
        return self._relations.get(relation_id)

    def get_relations(
        self,
        entity_id: str | None = None,
        relation_type: str | None = None,
        direction: str = "both",
    ) -> list[Relation]:
        """
        Get relations touching *entity_id*.  *direction* is ``'out'``,
        ``'in'``, or ``'both'``.
        """
        rel_ids: set[str] = set()
        if entity_id is not None:
            if direction in ("both", "out"):
                rel_ids.update(self._outgoing.get(entity_id, []))
            if direction in ("both", "in"):
                rel_ids.update(self._incoming.get(entity_id, []))

        results: list[Relation] = []
        pool = (
            [self._relations[rid] for rid in rel_ids]
            if entity_id is not None
            else list(self._relations.values())
        )
        for rel in pool:
            if relation_type and rel.relation_type != relation_type:
                continue
            results.append(rel)
        return results

    def get_related_entities(
        self,
        entity_id: str,
        relation_type: str | None = None,
        direction: str = "both",
        depth: int = 1,
    ) -> list[Entity]:
        """Get entities connected via relations, up to *depth* hops."""
        visited: set[str] = {entity_id}
        frontier: set[str] = {entity_id}
        result_entities: list[Entity] = []

        for _ in range(depth):
            next_frontier: set[str] = set()
            for eid in frontier:
                rels = self.get_relations(eid, relation_type=relation_type, direction=direction)
                for rel in rels:
                    neighbor = rel.target_id if eid == rel.source_id else rel.source_id
                    if neighbor not in visited:
                        visited.add(neighbor)
                        next_frontier.add(neighbor)
                        ent = self._entities.get(neighbor)
                        if ent is not None:
                            result_entities.append(ent)
            frontier = next_frontier

        return result_entities

    def remove_relation(self, relation_id: str) -> bool:
        return self._remove_relation(relation_id)

    def _remove_relation(self, relation_id: str) -> bool:
        rel = self._relations.pop(relation_id, None)
        if rel is None:
            return False
        out = self._outgoing.get(rel.source_id, [])
        if relation_id in out:
            out.remove(relation_id)
        inc = self._incoming.get(rel.target_id, [])
        if relation_id in inc:
            inc.remove(relation_id)
        return True

    # ------------------------------------------------------------------
    # Graph traversal
    # ------------------------------------------------------------------

    def find_path(
        self,
        source_id: str,
        target_id: str,
        relation_types: set[str] | None = None,
        max_depth: int = 10,
    ) -> list[str] | None:
        """
        BFS shortest path from *source_id* to *target_id*.
        Returns a list of entity ids (including both endpoints) or ``None``.
        """
        if source_id not in self._entities or target_id not in self._entities:
            return None
        if source_id == target_id:
            return [source_id]

        visited: set[str] = {source_id}
        queue: deque = deque()
        # Each entry: (current_node, path_so_far)
        queue.append((source_id, [source_id]))

        while queue:
            current, path = queue.popleft()
            if len(path) - 1 >= max_depth:
                continue

            for rel_id in self._outgoing.get(current, []):
                rel = self._relations.get(rel_id)
                if rel is None:
                    continue
                if relation_types and rel.relation_type not in relation_types:
                    continue
                neighbor = rel.target_id
                if neighbor in visited:
                    continue
                new_path = path + [neighbor]
                if neighbor == target_id:
                    return new_path
                visited.add(neighbor)
                queue.append((neighbor, new_path))

            for rel_id in self._incoming.get(current, []):
                rel = self._relations.get(rel_id)
                if rel is None:
                    continue
                if relation_types and rel.relation_type not in relation_types:
                    continue
                neighbor = rel.source_id
                if neighbor in visited:
                    continue
                new_path = path + [neighbor]
                if neighbor == target_id:
                    return new_path
                visited.add(neighbor)
                queue.append((neighbor, new_path))

        return None

    def get_cluster(self, entity_id: str, max_size: int = 50) -> list[Entity]:
        """Get the connected component containing *entity_id* via BFS."""
        if entity_id not in self._entities:
            return []

        visited: set[str] = {entity_id}
        queue: deque = deque([entity_id])
        entity_ids: list[str] = [entity_id]

        while queue and len(entity_ids) < max_size:
            current = queue.popleft()
            neighbors: set[str] = set()

            for rel_id in self._outgoing.get(current, []):
                rel = self._relations.get(rel_id)
                if rel:
                    neighbors.add(rel.target_id)
            for rel_id in self._incoming.get(current, []):
                rel = self._relations.get(rel_id)
                if rel:
                    neighbors.add(rel.source_id)

            for n in neighbors:
                if n not in visited:
                    visited.add(n)
                    queue.append(n)
                    entity_ids.append(n)

        return [self._entities[eid] for eid in entity_ids if eid in self._entities]

    # ------------------------------------------------------------------
    # Graph operations
    # ------------------------------------------------------------------

    def merge_entities(self, keep_id: str, remove_id: str) -> bool:
        """Merge *remove_id* into *keep_id*, re-wiring all relations."""
        if keep_id not in self._entities or remove_id not in self._entities:
            return False
        if keep_id == remove_id:
            return False

        # Rewire outgoing relations
        for rel_id in list(self._outgoing.get(remove_id, [])):
            rel = self._relations.get(rel_id)
            if rel:
                rel.source_id = keep_id
                self._outgoing[keep_id].append(rel_id)
        self._outgoing.pop(remove_id, None)

        # Rewire incoming relations
        for rel_id in list(self._incoming.get(remove_id, [])):
            rel = self._relations.get(rel_id)
            if rel:
                rel.target_id = keep_id
                self._incoming[keep_id].append(rel_id)
        self._incoming.pop(remove_id, None)

        # Remove the duplicate entity
        return self.remove_entity(remove_id)

    def get_most_connected(self, limit: int = 10) -> list[tuple[Entity, int]]:
        """Return the top *limit* entities ranked by total relation count."""
        counts: dict[str, int] = defaultdict(int)
        for rel in self._relations.values():
            counts[rel.source_id] += 1
            counts[rel.target_id] += 1
        ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:limit]
        return [
            (self._entities[eid], count)
            for eid, count in ranked
            if eid in self._entities
        ]

    def get_entity_types_stats(self) -> dict[str, int]:
        """Return a mapping of entity_type -> count."""
        stats: dict[str, int] = defaultdict(int)
        for entity in self._entities.values():
            stats[entity.entity_type] += 1
        return dict(stats)

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def semantic_search(self, query: str, limit: int = 10) -> list[Entity]:
        """
        Simple keyword-based semantic search across entity names and properties.
        Matches entities whose name or property values contain the query terms.
        """
        terms = query.lower().split()
        if not terms:
            return []

        scored: list[tuple[float, Entity]] = []
        for entity in self._entities.values():
            score = 0.0
            text = entity.name.lower()
            # Check property values that are strings
            for v in entity.properties.values():
                if isinstance(v, str):
                    text += " " + v.lower()
            for term in terms:
                if term in text:
                    score += text.count(term)
            if score > 0:
                scored.append((score, entity))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [e for _, e in scored[:limit]]

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    @property
    def entity_count(self) -> int:
        return len(self._entities)

    @property
    def relation_count(self) -> int:
        return len(self._relations)

    @property
    def graph_density(self) -> float:
        """
        Density = |E| / (|V| * (|V| - 1)).
        Returns 0.0 for graphs with fewer than 2 nodes.
        """
        n = self.entity_count
        if n < 2:
            return 0.0
        return self.relation_count / (n * (n - 1))

    def get_stats(self) -> dict[str, Any]:
        return {
            "entity_count": self.entity_count,
            "relation_count": self.relation_count,
            "entity_types": self.get_entity_types_stats(),
            "graph_density": round(self.graph_density, 6),
            "most_connected": [
                {"name": e.name, "type": e.entity_type, "connections": c}
                for e, c in self.get_most_connected(5)
            ],
        }

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, directory: str | Path) -> None:
        """Persist the graph to ``entities.json`` and ``relations.json``."""
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)

        entities_data = [e.to_dict() for e in self._entities.values()]
        relations_data = [r.to_dict() for r in self._relations.values()]

        with open(path / "entities.json", "w", encoding="utf-8") as f:
            json.dump(entities_data, f, indent=2, ensure_ascii=False)

        with open(path / "relations.json", "w", encoding="utf-8") as f:
            json.dump(relations_data, f, indent=2, ensure_ascii=False)

    def load(self, directory: str | Path) -> None:
        """Load the graph from ``entities.json`` and ``relations.json``."""
        path = Path(directory)

        self._entities.clear()
        self._relations.clear()
        self._outgoing.clear()
        self._incoming.clear()
        self._dedup_index.clear()

        # Load entities
        entity_file = path / "entities.json"
        if entity_file.exists():
            with open(entity_file, encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                entity = Entity.from_dict(item)
                self._entities[entity.id] = entity
                key = (entity.name.lower().strip(), entity.entity_type)
                self._dedup_index[key] = entity.id

        # Load relations
        relation_file = path / "relations.json"
        if relation_file.exists():
            with open(relation_file, encoding="utf-8") as f:
                data = json.load(f)
            for item in data:
                rel = Relation.from_dict(item)
                # Only add if both endpoints exist
                if rel.source_id in self._entities and rel.target_id in self._entities:
                    self._relations[rel.id] = rel
                    self._outgoing[rel.source_id].append(rel.id)
                    self._incoming[rel.target_id].append(rel.id)

    def __repr__(self) -> str:
        return (
            f"KnowledgeGraph(entities={self.entity_count}, "
            f"relations={self.relation_count}, "
            f"density={self.graph_density:.4f})"
        )
