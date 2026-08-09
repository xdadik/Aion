#!/usr/bin/env python3
"""Comprehensive tests for aion_core/knowledge/ modules."""

import sys
import tempfile
import time
import unittest
from pathlib import Path

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aion_core.knowledge.graph import Entity, Relation, KnowledgeGraph
from aion_core.knowledge.auto_builder import AutoKnowledgeBuilder
from aion_core.knowledge.reasoner import GraphReasoner
from aion_core.knowledge.manager import KnowledgeManager

# ===================================================================
# Entity tests
# ===================================================================


class TestEntity(unittest.TestCase):
    """Tests for the Entity dataclass."""

    def test_entity_creation_with_defaults(self):
        """Entity should auto-generate id and timestamps."""
        e = Entity(name="test", entity_type="concept")
        self.assertEqual(e.name, "test")
        self.assertEqual(e.entity_type, "concept")
        self.assertTrue(len(e.id) == 16)
        self.assertIsInstance(e.properties, dict)
        self.assertEqual(e.access_count, 0)
        self.assertIsInstance(e.created_at, str)
        self.assertIsInstance(e.updated_at, str)

    def test_entity_to_dict_from_dict_roundtrip(self):
        """Entity serializes and deserializes correctly."""
        original = Entity(
            id="abc123",
            name="MyEntity",
            entity_type="tool",
            properties={"key": "val"},
            access_count=5,
        )
        d = original.to_dict()
        restored = Entity.from_dict(d)
        self.assertEqual(restored.id, "abc123")
        self.assertEqual(restored.name, "MyEntity")
        self.assertEqual(restored.entity_type, "tool")
        self.assertEqual(restored.properties, {"key": "val"})
        self.assertEqual(restored.access_count, 5)

    def test_entity_touch_updates_timestamp(self):
        """Calling touch() should update updated_at and bump access_count."""
        e = Entity(name="touch-test")
        old_ts = e.updated_at
        old_count = e.access_count
        time.sleep(0.01)
        e.touch()
        self.assertGreater(e.updated_at, old_ts)
        self.assertEqual(e.access_count, old_count + 1)


# ===================================================================
# Relation tests
# ===================================================================


class TestRelation(unittest.TestCase):
    """Tests for the Relation dataclass."""

    def test_relation_creation(self):
        """Relation should store source/target/type/weight correctly."""
        r = Relation(
            source_id="s1",
            target_id="t1",
            relation_type="uses",
            weight=0.8,
        )
        self.assertEqual(r.source_id, "s1")
        self.assertEqual(r.target_id, "t1")
        self.assertEqual(r.relation_type, "uses")
        self.assertAlmostEqual(r.weight, 0.8)

    def test_relation_to_dict_from_dict_roundtrip(self):
        """Relation serializes and deserializes correctly."""
        original = Relation(
            id="rel1",
            source_id="a",
            target_id="b",
            relation_type="depends_on",
            weight=0.9,
            properties={"note": "important"},
        )
        d = original.to_dict()
        restored = Relation.from_dict(d)
        self.assertEqual(restored.id, "rel1")
        self.assertEqual(restored.source_id, "a")
        self.assertEqual(restored.target_id, "b")
        self.assertEqual(restored.relation_type, "depends_on")
        self.assertAlmostEqual(restored.weight, 0.9)
        self.assertEqual(restored.properties, {"note": "important"})


# ===================================================================
# KnowledgeGraph tests
# ===================================================================


class TestKnowledgeGraph(unittest.TestCase):
    """Tests for the KnowledgeGraph class."""

    def setUp(self):
        self.g = KnowledgeGraph()

    # --- Creation ---

    def test_graph_creation_empty(self):
        """New graph has zero entities and relations."""
        self.assertEqual(self.g.entity_count, 0)
        self.assertEqual(self.g.relation_count, 0)

    # --- Entity CRUD ---

    def test_add_entity(self):
        """add_entity creates and stores an entity."""
        e = self.g.add_entity(name="Python", entity_type="tool")
        self.assertIsInstance(e, Entity)
        self.assertEqual(e.name, "Python")
        self.assertEqual(e.entity_type, "tool")
        self.assertEqual(self.g.entity_count, 1)

    def test_get_entity_exists(self):
        """get_entity returns entity by id."""
        e = self.g.add_entity(name="X", entity_type="concept")
        fetched = self.g.get_entity(e.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "X")

    def test_get_entity_not_exists(self):
        """get_entity returns None for unknown id."""
        self.assertIsNone(self.g.get_entity("nonexistent"))

    def test_find_entities_by_type(self):
        """find_entities filters by entity_type."""
        self.g.add_entity(name="A", entity_type="tool")
        self.g.add_entity(name="B", entity_type="tool")
        self.g.add_entity(name="C", entity_type="concept")
        tools = self.g.find_entities(entity_type="tool")
        self.assertEqual(len(tools), 2)
        for t in tools:
            self.assertEqual(t.entity_type, "tool")

    def test_update_entity(self):
        """update_entity changes properties and name."""
        e = self.g.add_entity(name="Old", entity_type="concept")
        updated = self.g.update_entity(e.id, properties={"key": "val"}, name="New")
        self.assertIsNotNone(updated)
        self.assertEqual(updated.name, "New")
        self.assertEqual(updated.properties, {"key": "val"})

    def test_remove_entity(self):
        """remove_entity deletes entity and its relations."""
        e1 = self.g.add_entity(name="A", entity_type="concept")
        e2 = self.g.add_entity(name="B", entity_type="concept")
        self.g.add_relation(e1.id, e2.id, "related_to")
        result = self.g.remove_entity(e1.id)
        self.assertTrue(result)
        self.assertEqual(self.g.entity_count, 1)
        self.assertEqual(self.g.relation_count, 0)

    # --- Relation CRUD ---

    def test_add_relation(self):
        """add_relation creates a relation between two entities."""
        e1 = self.g.add_entity(name="A", entity_type="concept")
        e2 = self.g.add_entity(name="B", entity_type="concept")
        r = self.g.add_relation(e1.id, e2.id, "uses", weight=0.7)
        self.assertIsNotNone(r)
        self.assertEqual(r.relation_type, "uses")
        self.assertAlmostEqual(r.weight, 0.7)
        self.assertEqual(self.g.relation_count, 1)

    def test_get_relation(self):
        """get_relation returns a relation by id."""
        e1 = self.g.add_entity(name="A", entity_type="concept")
        e2 = self.g.add_entity(name="B", entity_type="concept")
        r = self.g.add_relation(e1.id, e2.id)
        fetched = self.g.get_relation(r.id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.source_id, e1.id)

    def test_get_relations_for_entity(self):
        """get_relations returns relations touching an entity."""
        e1 = self.g.add_entity(name="A", entity_type="concept")
        e2 = self.g.add_entity(name="B", entity_type="concept")
        self.g.add_relation(e1.id, e2.id, "uses")
        rels = self.g.get_relations(entity_id=e1.id)
        self.assertEqual(len(rels), 1)

    def test_get_related_entities(self):
        """get_related_entities returns neighbor entities."""
        e1 = self.g.add_entity(name="A", entity_type="concept")
        e2 = self.g.add_entity(name="B", entity_type="concept")
        self.g.add_relation(e1.id, e2.id, "related_to")
        related = self.g.get_related_entities(e1.id)
        self.assertEqual(len(related), 1)
        self.assertEqual(related[0].name, "B")

    def test_remove_relation(self):
        """remove_relation deletes a specific relation."""
        e1 = self.g.add_entity(name="A", entity_type="concept")
        e2 = self.g.add_entity(name="B", entity_type="concept")
        r = self.g.add_relation(e1.id, e2.id)
        result = self.g.remove_relation(r.id)
        self.assertTrue(result)
        self.assertEqual(self.g.relation_count, 0)

    # --- Graph traversal ---

    def test_find_path_connected_entities(self):
        """find_path returns a path between connected entities."""
        a = self.g.add_entity(name="A", entity_type="concept")
        b = self.g.add_entity(name="B", entity_type="concept")
        c = self.g.add_entity(name="C", entity_type="concept")
        self.g.add_relation(a.id, b.id, "related_to")
        self.g.add_relation(b.id, c.id, "related_to")
        path = self.g.find_path(a.id, c.id)
        self.assertIsNotNone(path)
        self.assertEqual(path, [a.id, b.id, c.id])

    def test_find_path_no_path(self):
        """find_path returns None for disconnected entities."""
        a = self.g.add_entity(name="A", entity_type="concept")
        b = self.g.add_entity(name="B", entity_type="concept")
        path = self.g.find_path(a.id, b.id)
        self.assertIsNone(path)

    def test_get_cluster(self):
        """get_cluster returns all entities in the connected component."""
        a = self.g.add_entity(name="A", entity_type="concept")
        b = self.g.add_entity(name="B", entity_type="concept")
        c = self.g.add_entity(name="C", entity_type="concept")
        self.g.add_relation(a.id, b.id, "related_to")
        self.g.add_relation(b.id, c.id, "related_to")
        cluster = self.g.get_cluster(a.id)
        self.assertEqual(len(cluster), 3)

    # --- Graph operations ---

    def test_merge_entities(self):
        """merge_entities rewires relations and removes the old entity."""
        a = self.g.add_entity(name="A", entity_type="concept")
        b = self.g.add_entity(name="B", entity_type="concept")
        c = self.g.add_entity(name="C", entity_type="concept")
        self.g.add_relation(b.id, c.id, "uses")
        result = self.g.merge_entities(a.id, b.id)
        self.assertTrue(result)
        self.assertEqual(self.g.entity_count, 2)
        # C should now be reachable from A
        related = self.g.get_related_entities(a.id)
        names = [e.name for e in related]
        self.assertIn("C", names)

    def test_get_most_connected(self):
        """get_most_connected returns entities sorted by relation count."""
        hub = self.g.add_entity(name="Hub", entity_type="concept")
        for i in range(5):
            leaf = self.g.add_entity(name=f"Leaf{i}", entity_type="concept")
            self.g.add_relation(hub.id, leaf.id, "related_to")
        top = self.g.get_most_connected(limit=10)
        self.assertGreaterEqual(len(top), 1)
        self.assertEqual(top[0][0].name, "Hub")
        self.assertEqual(top[0][1], 5)

    def test_get_entity_types_stats(self):
        """get_entity_types_stats returns counts by type."""
        self.g.add_entity(name="A", entity_type="tool")
        self.g.add_entity(name="B", entity_type="tool")
        self.g.add_entity(name="C", entity_type="concept")
        stats = self.g.get_entity_types_stats()
        self.assertEqual(stats["tool"], 2)
        self.assertEqual(stats["concept"], 1)

    # --- Properties ---

    def test_entity_count_relation_count(self):
        """entity_count and relation_count reflect current state."""
        e1 = self.g.add_entity(name="A", entity_type="concept")
        e2 = self.g.add_entity(name="B", entity_type="concept")
        self.assertEqual(self.g.entity_count, 2)
        self.g.add_relation(e1.id, e2.id)
        self.assertEqual(self.g.relation_count, 1)

    def test_graph_density_empty(self):
        """Empty graph or single-node graph has density 0."""
        self.assertAlmostEqual(self.g.graph_density, 0.0)
        self.g.add_entity(name="X", entity_type="concept")
        self.assertAlmostEqual(self.g.graph_density, 0.0)

    def test_graph_density_with_relations(self):
        """Density is |E| / (|V| * (|V|-1))."""
        a = self.g.add_entity(name="A", entity_type="concept")
        b = self.g.add_entity(name="B", entity_type="concept")
        self.g.add_relation(a.id, b.id)
        expected = 1.0 / (2 * 1)
        self.assertAlmostEqual(self.g.graph_density, expected)

    def test_get_stats(self):
        """get_stats returns a dict with expected keys."""
        stats = self.g.get_stats()
        self.assertIn("entity_count", stats)
        self.assertIn("relation_count", stats)
        self.assertIn("entity_types", stats)
        self.assertIn("graph_density", stats)
        self.assertIn("most_connected", stats)
        self.assertEqual(stats["entity_count"], 0)

    # --- Persistence ---

    def test_save_and_load(self):
        """Graph persists and restores correctly via JSON files."""
        e1 = self.g.add_entity(name="Alpha", entity_type="tool")
        e2 = self.g.add_entity(name="Beta", entity_type="concept")
        self.g.add_relation(e1.id, e2.id, "uses", weight=0.6)

        with tempfile.TemporaryDirectory() as tmpdir:
            self.g.save(tmpdir)

            new_g = KnowledgeGraph()
            new_g.load(tmpdir)
            self.assertEqual(new_g.entity_count, 2)
            self.assertEqual(new_g.relation_count, 1)
            fetched = new_g.get_entity(e1.id)
            self.assertIsNotNone(fetched)
            self.assertEqual(fetched.name, "Alpha")


# ===================================================================
# AutoKnowledgeBuilder tests
# ===================================================================


class TestAutoKnowledgeBuilder(unittest.TestCase):
    """Tests for the AutoKnowledgeBuilder class."""

    def setUp(self):
        self.g = KnowledgeGraph()
        self.builder = AutoKnowledgeBuilder(self.g)

    def test_builder_creation(self):
        """Builder wraps a KnowledgeGraph instance."""
        self.assertIs(self.builder._graph, self.g)

    def test_discover_patterns(self):
        """discover_patterns returns a dict with expected keys on an empty graph."""
        patterns = self.builder.discover_patterns()
        self.assertIsInstance(patterns, dict)
        self.assertIn("co_occurring_tools", patterns)
        self.assertIn("failure_patterns", patterns)
        self.assertIn("successful_strategies", patterns)
        self.assertIn("skill_ranking", patterns)


# ===================================================================
# GraphReasoner tests
# ===================================================================


class TestGraphReasoner(unittest.TestCase):
    """Tests for the GraphReasoner class."""

    def setUp(self):
        self.g = KnowledgeGraph()
        self.reasoner = GraphReasoner(self.g)

    def test_reasoner_creation(self):
        """Reasoner wraps a KnowledgeGraph instance."""
        self.assertIs(self.reasoner._graph, self.g)

    def test_get_context_for_task_empty_graph(self):
        """Context for a task on an empty graph returns empty lists."""
        result = self.reasoner.get_context_for_task("build a REST API")
        self.assertEqual(result["task"], "build a REST API")
        self.assertEqual(result["matched_entities"], [])
        self.assertEqual(result["related_entities"], [])
        self.assertEqual(result["relations"], [])
        self.assertEqual(result["similar_tasks"], [])
        self.assertEqual(result["total_context_size"], 0)

    def test_suggest_tools_empty_graph(self):
        """Suggest tools on an empty graph returns empty list."""
        result = self.reasoner.suggest_tools("build a REST API")
        self.assertEqual(result, [])

    def test_predict_risks_empty_graph(self):
        """Predict risks on an empty graph returns empty list."""
        result = self.reasoner.predict_risks("deploy to production")
        self.assertEqual(result, [])

    def test_explain_failure(self):
        """Explain failure on an empty graph returns a summary."""
        result = self.reasoner.explain_failure("ImportError: no module named 'xyz'")
        self.assertIsInstance(result, dict)
        self.assertEqual(result["error"], "ImportError: no module named 'xyz'")
        self.assertEqual(result["similar_past_errors"], [])
        self.assertEqual(result["known_fixes"], [])
        self.assertIn("summary", result)
        self.assertIn("No similar errors found", result["summary"])


# ===================================================================
# KnowledgeManager tests
# ===================================================================


class TestKnowledgeManager(unittest.TestCase):
    """Tests for the KnowledgeManager class."""

    def test_manager_creation(self):
        """Manager creates graph, builder, and reasoner internally."""
        km = KnowledgeManager()
        self.assertIsNotNone(km.graph)
        self.assertIsNotNone(km.builder)
        self.assertIsNotNone(km.reasoner)

    def test_initialize_creates_graph(self):
        """initialize() with a fresh dir loads nothing but marks initialized."""
        with tempfile.TemporaryDirectory() as tmpdir:
            km = KnowledgeManager(storage_dir=tmpdir)
            km.initialize()
            self.assertEqual(km.graph.entity_count, 0)

    def test_get_stats(self):
        """get_stats returns a dict with graph and patterns keys."""
        km = KnowledgeManager()
        stats = km.get_stats()
        self.assertIn("graph", stats)
        self.assertIn("patterns", stats)

    def test_graph_property(self):
        """The graph property returns the underlying KnowledgeGraph."""
        km = KnowledgeManager()
        self.assertIsInstance(km.graph, KnowledgeGraph)

    def test_builder_property(self):
        """The builder property returns an AutoKnowledgeBuilder."""
        km = KnowledgeManager()
        self.assertIsInstance(km.builder, AutoKnowledgeBuilder)

    def test_reasoner_property(self):
        """The reasoner property returns a GraphReasoner."""
        km = KnowledgeManager()
        self.assertIsInstance(km.reasoner, GraphReasoner)


if __name__ == "__main__":
    unittest.main()
