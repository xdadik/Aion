"""Tests for the knowledge graph module (aion_core.knowledge)."""
import sys, tempfile, unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from aion_core.knowledge import KnowledgeGraph, Entity, Relation


class TestEntityAndRelation(unittest.TestCase):
    def test_entity_roundtrip(self):
        entity = Entity(name="REST API", entity_type="project")
        restored = Entity.from_dict(entity.to_dict())
        self.assertEqual(restored.name, "REST API")
        self.assertEqual(restored.entity_type, "project")

    def test_relation_roundtrip(self):
        relation = Relation(source_id="a", target_id="b", relation_type="uses", weight=0.9)
        restored = Relation.from_dict(relation.to_dict())
        self.assertEqual(restored.source_id, "a")
        self.assertEqual(restored.target_id, "b")
        self.assertEqual(restored.weight, 0.9)


class TestKnowledgeGraph(unittest.TestCase):
    def setUp(self):
        self.graph = KnowledgeGraph()

    def test_add_entity_deduplicates_on_name_and_type(self):
        a = self.graph.add_entity("Docker", entity_type="tool")
        b = self.graph.add_entity("docker", entity_type="tool", properties={"version": "24"})
        self.assertEqual(a.id, b.id)
        self.assertEqual(a.properties["version"], "24")
        self.assertEqual(self.graph.entity_count, 1)

    def test_invalid_entity_type_raises(self):
        with self.assertRaises(ValueError):
            self.graph.add_entity("X", entity_type="bogus")

    def test_add_relation_requires_existing_entities(self):
        a = self.graph.add_entity("A", entity_type="concept")
        self.assertIsNone(self.graph.add_relation(a.id, "missing", relation_type="related_to"))

    def test_find_path_between_entities(self):
        a = self.graph.add_entity("A", entity_type="concept")
        b = self.graph.add_entity("B", entity_type="concept")
        c = self.graph.add_entity("C", entity_type="concept")
        self.graph.add_relation(a.id, b.id, relation_type="related_to")
        self.graph.add_relation(b.id, c.id, relation_type="depends_on")
        self.assertEqual(self.graph.find_path(a.id, c.id), [a.id, b.id, c.id])
        self.assertIsNone(self.graph.find_path(a.id, "missing"))

    def test_save_load_roundtrip(self):
        a = self.graph.add_entity("A", entity_type="concept")
        b = self.graph.add_entity("B", entity_type="concept")
        self.graph.add_relation(a.id, b.id, relation_type="related_to")
        with tempfile.TemporaryDirectory() as tmpdir:
            self.graph.save(tmpdir)
            loaded = KnowledgeGraph()
            loaded.load(tmpdir)
        self.assertEqual(loaded.entity_count, 2)
        self.assertEqual(loaded.relation_count, 1)
        self.assertEqual(loaded.get_related_entities(a.id)[0].id, b.id)


if __name__ == "__main__":
    unittest.main()
