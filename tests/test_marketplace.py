"""Tests for the Skill Marketplace module."""

from __future__ import annotations

from pathlib import Path

import pytest

from aion_core.skills.engine import SkillEngine
from aion_core.skills.marketplace import CatalogEntry, SkillMarketplace


SAMPLE_SKILL_MD = """---
name: test-marketplace-skill
description: A test skill for marketplace testing
version: 1.0.0
---

# Test Skill

This is a test skill body.
"""


class TestMarketplaceInit:
    """Verify SkillMarketplace constructs."""

    def test_init_creates_skills_dir(self, tmp_path):
        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        assert (tmp_path / "skills").is_dir()

    def test_default_catalog_has_starter_pack(self, tmp_path):
        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        catalog = mp.list_catalog()
        assert len(catalog) > 0
        assert any(e.name == "aion-starter-pack" for e in catalog)


class TestInstallFromText:
    """Install skills from raw SKILL.md text."""

    @pytest.mark.asyncio
    async def test_install_from_url_with_mock(self, tmp_path, monkeypatch):
        # Mock urllib.request.urlopen to return our sample skill
        from io import BytesIO
        class _MockResp:
            def __enter__(self): return self
            def __exit__(self, *a): pass
            def read(self): return SAMPLE_SKILL_MD.encode("utf-8")
        def _mock_urlopen(*a, **kw): return _MockResp()
        monkeypatch.setattr("urllib.request.urlopen", _mock_urlopen)

        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        skill = await mp.install_from_url("https://fake.example.com/skill.md")
        assert skill is not None
        assert skill.name == "test-marketplace-skill"
        # File should be on disk
        assert (tmp_path / "skills" / "test-marketplace-skill.md").is_file()


class TestInstallFromDirectory:
    """Install skills from a local directory."""

    @pytest.mark.asyncio
    async def test_install_from_directory(self, tmp_path):
        # Set up a source dir with two SKILL.md files
        src = tmp_path / "src"
        src.mkdir()
        (src / "skill1").mkdir()
        (src / "skill1" / "SKILL.md").write_text("---\nname: dir-skill-1\ndescription: a\n---\nbody1")
        (src / "skill2").mkdir()
        (src / "skill2" / "SKILL.md").write_text("---\nname: dir-skill-2\ndescription: b\n---\nbody2")

        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        installed = await mp.install_from_directory(src)
        assert len(installed) == 2
        names = [s.name for s in installed]
        assert "dir-skill-1" in names
        assert "dir-skill-2" in names


class TestUninstall:
    """Uninstall a skill by name."""

    def test_uninstall_existing(self, tmp_path):
        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        # Manually drop a skill file
        skill_file = tmp_path / "skills" / "to-remove.md"
        skill_file.write_text("---\nname: to-remove\n---\nbody")
        assert skill_file.is_file()
        ok = mp.uninstall("to-remove")
        assert ok is True
        assert not skill_file.is_file()

    def test_uninstall_nonexistent_returns_false(self, tmp_path):
        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        ok = mp.uninstall("nope-not-here")
        assert ok is False


class TestListInstalled:
    """list_installed returns installed skill files."""

    def test_list_installed_empty(self, tmp_path):
        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        assert mp.list_installed() == []

    def test_list_installed_returns_files(self, tmp_path):
        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        (tmp_path / "skills" / "a.md").write_text("a")
        (tmp_path / "skills" / "b.md").write_text("b")
        installed = mp.list_installed()
        assert len(installed) == 2


class TestCatalogRefresh:
    """refresh_catalog fetches remote catalog."""

    def test_refresh_catalog_invalid_url_returns_zero(self, tmp_path):
        mp = SkillMarketplace(skills_dir=tmp_path / "skills")
        # Pass a clearly invalid URL
        n = mp.refresh_catalog("not-a-url://broken")
        assert n == 0
