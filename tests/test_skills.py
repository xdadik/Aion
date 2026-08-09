"""Tests for aion_core.skills.engine - Skill serialisation."""

import unittest

from aion_core.skills.engine import Skill, SkillStatus


class TestSkillMarkdown(unittest.TestCase):
    def test_roundtrip(self):
        skill = Skill(name="test-skill", description="A test", content="Do stuff")
        md = skill.to_markdown()
        self.assertIn("test-skill", md)
        self.assertIn("A test", md)

    def test_from_markdown(self):
        md = "# Test Skill\n\nA test skill description.\n"
        skill = Skill.from_markdown(md)
        self.assertEqual(skill.name, "Test Skill")
        self.assertIn("test skill", skill.description.lower())

    def test_skill_status(self):
        for status in SkillStatus:
            self.assertIsInstance(status.value, str)

    def test_success_rate(self):
        skill = Skill(name="test", usage_count=10, success_count=7)
        self.assertAlmostEqual(skill.success_rate, 0.7)

    def test_to_dict(self):
        skill = Skill(name="test", tags=["python", "api"])
        d = skill.to_dict()
        self.assertEqual(d["name"], "test")
        self.assertIn("python", d["tags"])


if __name__ == "__main__":
    unittest.main()
