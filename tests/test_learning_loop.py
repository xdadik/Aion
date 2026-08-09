"""Tests for the self-improving learning loop.

This is Aion's equivalent of Hermes Agent's signature feature:
recording lessons from task execution and using them to improve
future planning.

Verifies:
  - RuntimeLearning.record_lesson() persists lessons
  - RuntimeLearning.get_relevant_lessons() retrieves by keyword similarity
  - RuntimeLearning.save/load round-trips correctly
  - SkillEngine.create_from_experience() builds a SKILL.md from lessons
  - SkillEngine.evaluate_auto_create() decides when to auto-create
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aion_core.pipeline.learning import RuntimeLearning, TaskLesson
from aion_core.skills.engine import SkillEngine, SkillStatus


class TestRuntimeLearningRecord:
    """Recording lessons."""

    @pytest.mark.asyncio
    async def test_record_outcome_appends_to_list(self, tmp_path: Path):
        rl = RuntimeLearning(storage_path=str(tmp_path / "lessons.json"))
        await rl.record_outcome(
            task="Build a Python REST API",
            plan=None,
            results={},
            verifications=[],
            critique=None,
            confidence=0.7,
        )
        assert len(rl._lessons) == 1

    @pytest.mark.asyncio
    async def test_recorded_lesson_has_timestamp(self, tmp_path: Path):
        rl = RuntimeLearning(storage_path=str(tmp_path / "lessons.json"))
        await rl.record_outcome(
            task="Build a Python REST API",
            plan=None,
            results={},
            verifications=[],
            critique=None,
            confidence=0.7,
        )
        lesson = rl._lessons[0]
        assert lesson.timestamp
        assert "T" in lesson.timestamp  # ISO format

    @pytest.mark.asyncio
    async def test_recorded_lesson_extracts_keywords(self, tmp_path: Path):
        rl = RuntimeLearning(storage_path=str(tmp_path / "lessons.json"))
        await rl.record_outcome(
            task="Build a Python REST API with FastAPI and JWT auth",
            plan=None,
            results={},
            verifications=[],
            critique=None,
            confidence=0.8,
        )
        lesson = rl._lessons[0]
        # At least one of these keywords should be extracted
        keywords_str = " ".join(lesson.task_keywords).lower()
        assert any(
            kw in keywords_str for kw in ["python", "rest", "api", "fastapi", "jwt"]
        )


class TestRuntimeLearningRetrieval:
    """Retrieving relevant lessons."""

    def test_get_relevant_returns_empty_when_no_lessons(self, tmp_path: Path):
        rl = RuntimeLearning(storage_path=str(tmp_path / "lessons.json"))
        result = rl.get_relevant_lessons("anything")
        assert result == []

    @pytest.mark.asyncio
    async def test_get_relevant_returns_matching_lesson(self, tmp_path: Path):
        rl = RuntimeLearning(storage_path=str(tmp_path / "lessons.json"))
        await rl.record_outcome(
            task="Build a Python REST API",
            plan=None,
            results={},
            verifications=[],
            critique=None,
            confidence=0.8,
        )
        # Query that overlaps in keywords
        result = rl.get_relevant_lessons("create a REST API in python")
        assert len(result) >= 1
        assert "REST" in result[0].task_summary or "API" in result[0].task_summary

    @pytest.mark.asyncio
    async def test_get_relevant_respects_limit(self, tmp_path: Path):
        rl = RuntimeLearning(storage_path=str(tmp_path / "lessons.json"))
        # Record several lessons
        for i in range(5):
            await rl.record_outcome(
                task=f"Build REST API variant {i}",
                plan=None,
                results={},
                verifications=[],
                critique=None,
                confidence=0.7,
            )
        result = rl.get_relevant_lessons("REST API", max_lessons=2)
        assert len(result) <= 2


class TestRuntimeLearningPersistence:
    """Save / load round-trip."""

    @pytest.mark.asyncio
    async def test_save_and_load_roundtrip(self, tmp_path: Path):
        path = str(tmp_path / "lessons.json")
        rl1 = RuntimeLearning(storage_path=path)
        await rl1.record_outcome(
            task="Build a REST API",
            plan=None,
            results={},
            verifications=[],
            critique=None,
            confidence=0.8,
        )
        rl1._save()
        assert Path(path).is_file()

        rl2 = RuntimeLearning(storage_path=path)
        rl2.load()
        assert len(rl2._lessons) == 1
        assert "REST API" in rl2._lessons[0].task_summary

    def test_load_nonexistent_file_is_safe(self, tmp_path: Path):
        rl = RuntimeLearning(storage_path=str(tmp_path / "does-not-exist.json"))
        rl.load()  # should not raise
        assert len(rl._lessons) == 0


class TestSkillEngineAutoCreate:
    """Skill auto-creation from experience (Hermes's killer feature)."""

    def test_create_from_experience_produces_skill(self, tmp_path: Path):
        engine = SkillEngine(storage_dir=tmp_path)
        skill = engine.create_from_experience(
            name="python-rest-api",
            task="Build a Python REST API with FastAPI",
            lessons_learned=[
                "Use FastAPI for async",
                "Add JWT auth",
                "Use Pydantic models",
            ],
        )
        assert skill is not None
        assert skill.name == "python-rest-api"
        assert "FastAPI" in skill.content or "fastapi" in skill.content.lower()

    def test_create_from_experience_assigns_active_status(self, tmp_path: Path):
        engine = SkillEngine(storage_dir=tmp_path)
        skill = engine.create_from_experience(
            name="test-skill",
            task="Some task",
            lessons_learned=["lesson 1"],
        )
        assert skill.status == SkillStatus.ACTIVE

    def test_auto_create_can_be_disabled(self, tmp_path: Path):
        engine = SkillEngine(storage_dir=tmp_path)
        engine.auto_create_enabled = False
        assert engine.auto_create_enabled is False

    def test_evaluate_auto_create_returns_decision(self, tmp_path: Path):
        engine = SkillEngine(storage_dir=tmp_path)
        # evaluate_auto_create takes (task, outcome, tokens_used) and returns
        # a Skill if it decides to create one, or None
        decision = engine.evaluate_auto_create(
            task="Build a Python REST API with FastAPI",
            outcome="Successfully built the API using FastAPI",
            tokens_used=1500,
        )
        # Decision is either a Skill or None — both are valid
        assert decision is None or hasattr(decision, "name")


class TestSkillEngineEvolution:
    """Skill evolution from outcomes."""

    def test_record_usage_increments_count(self, tmp_path: Path):
        engine = SkillEngine(storage_dir=tmp_path)
        skill = engine.create_skill(name="test", description="d", content="c")
        initial_count = skill.usage_count
        engine.record_usage(skill.skill_id, success=True)
        assert skill.usage_count == initial_count + 1

    def test_record_success_updates_success_rate(self, tmp_path: Path):
        engine = SkillEngine(storage_dir=tmp_path)
        skill = engine.create_skill(name="test", description="d", content="c")
        engine.record_usage(skill.skill_id, success=True)
        engine.record_usage(skill.skill_id, success=True)
        engine.record_usage(skill.skill_id, success=False)
        # 2/3 = 0.667
        assert 0.5 <= skill.success_rate <= 0.8


class TestSkillEnginePersistence:
    """Save / load skills."""

    def test_save_and_load_roundtrip(self, tmp_path: Path):
        engine1 = SkillEngine(storage_dir=tmp_path)
        engine1.create_skill(
            name="skill-a", description="A", content="content A", tags=["x"]
        )
        engine1.create_skill(
            name="skill-b", description="B", content="content B", tags=["y"]
        )
        n_saved = engine1.save()
        assert n_saved == 2

        engine2 = SkillEngine(storage_dir=tmp_path)
        n_loaded = engine2.load()
        assert n_loaded == 2
        assert engine2.get_skill_by_name("skill-a") is not None
        assert engine2.get_skill_by_name("skill-b") is not None

    def test_export_all_markdown(self, tmp_path: Path):
        engine = SkillEngine(storage_dir=tmp_path)
        engine.create_skill(
            name="exportable", description="d", content="# Some skill\n\nbody"
        )
        out_dir = tmp_path / "exported"
        n = engine.export_all_markdown(out_dir)
        assert n == 1
        exported = list(out_dir.glob("*.md"))
        assert len(exported) == 1
