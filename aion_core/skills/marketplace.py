"""Aion Skill Marketplace — download skills from remote sources.

Fetch SKILL.md files from a remote URL (HTTP/HTTPS) or a local git repo,
validate them, and install them into the user's skills directory.

Built-in catalog support for:
    - HTTP/HTTPS URLs (single file or tar.gz archive)
    - Git repositories (cloned via `git clone`)
    - Local directories (copied recursively)

Usage:
    from aion_core.skills.marketplace import SkillMarketplace
    mp = SkillMarketplace()
    skill = await mp.install_from_url("https://example.com/skills/my-skill.md")
    skills = mp.list_installed()
    ok = mp.uninstall("my-skill")
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from aion_core.skills.engine import Skill, SkillEngine, SkillStatus

logger = __import__("logging").getLogger("aion_hand.skills.marketplace")


# ---------------------------------------------------------------------------
# Catalog entry
# ---------------------------------------------------------------------------

@dataclass
class CatalogEntry:
    """A skill available in a remote catalog."""
    name: str
    description: str
    url: str
    source: str  # "http" | "git" | "local"
    version: str = "1.0.0"
    author: str = "unknown"
    tags: list[str] | None = None


# ---------------------------------------------------------------------------
# Marketplace
# ---------------------------------------------------------------------------

class SkillMarketplace:
    """Install / uninstall / list skills from remote sources.

    Installed skills land in ~/.aion-hand/skills/<name>.md and are picked
    up automatically by the SkillEngine on next load.
    """

    DEFAULT_CATALOG: list[CatalogEntry] = [
        # Built-in catalog — points to Aion's own GitHub-hosted skill library.
        # Users can extend this by passing a catalog URL to refresh_catalog().
        CatalogEntry(
            name="aion-starter-pack",
            description="Aion's 11 starter skills (plan, TDD, debugging, review, etc.)",
            url="https://github.com/xdadik/Aion/tree/main/skills/library",
            source="git",
            author="Aion Hand",
            tags=["official", "starter"],
        ),
    ]

    def __init__(
        self,
        skills_dir: Path | str | None = None,
        engine: SkillEngine | None = None,
    ) -> None:
        self.skills_dir = Path(skills_dir) if skills_dir else Path.home() / ".aion-hand" / "skills"
        self.skills_dir.mkdir(parents=True, exist_ok=True)
        self.engine = engine or SkillEngine(storage_dir=self.skills_dir)
        self._catalog: list[CatalogEntry] = list(self.DEFAULT_CATALOG)

    # ------------------------------------------------------------------
    #  Catalog
    # ------------------------------------------------------------------

    def list_catalog(self) -> list[CatalogEntry]:
        """Return the current catalog."""
        return list(self._catalog)

    def refresh_catalog(self, catalog_url: str) -> int:
        """Fetch a remote catalog (JSON array) and merge into the local catalog.

        Returns the number of new entries added.
        """
        try:
            req = urllib.request.Request(catalog_url, headers={"User-Agent": "AionHand/0.3"})
            with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                import json
                data = json.loads(resp.read().decode("utf-8"))
            added = 0
            for item in data:
                entry = CatalogEntry(
                    name=str(item.get("name", "unnamed")),
                    description=str(item.get("description", "")),
                    url=str(item.get("url", "")),
                    source=str(item.get("source", "http")),
                    version=str(item.get("version", "1.0.0")),
                    author=str(item.get("author", "unknown")),
                    tags=list(item.get("tags", [])),
                )
                # Avoid duplicates by name+url
                if not any(e.name == entry.name and e.url == entry.url for e in self._catalog):
                    self._catalog.append(entry)
                    added += 1
            return added
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Could not refresh catalog from {catalog_url}: {exc}")
            return 0

    # ------------------------------------------------------------------
    #  Install
    # ------------------------------------------------------------------

    async def install_from_url(self, url: str, *, name: str | None = None) -> Skill | None:
        """Fetch a single SKILL.md from a URL and install it."""
        try:
            def _fetch() -> str:
                req = urllib.request.Request(url, headers={"User-Agent": "AionHand/0.3"})
                with urllib.request.urlopen(req, timeout=15) as resp:  # noqa: S310
                    return resp.read().decode("utf-8")
            text = await asyncio.get_event_loop().run_in_executor(None, _fetch)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Failed to fetch skill from {url}: {exc}")
            return None

        return self._install_from_text(text, name=name, source=url)

    async def install_from_git(self, repo_url: str, *, skill_path: str | None = None) -> list[Skill]:
        """Clone a git repo and install any SKILL.md files found in it.

        Args:
            repo_url: Git URL to clone.
            skill_path: Optional subpath within the repo where SKILL.md lives.
                        If None, scans the whole repo.

        Returns:
            List of installed Skills (may be empty).
        """
        if not shutil.which("git"):
            logger.error("git not found on PATH — cannot install from git repo")
            return []

        with tempfile.TemporaryDirectory() as tmpdir:
            # Clone
            proc = await asyncio.create_subprocess_exec(
                "git", "clone", "--depth", "1", repo_url, tmpdir,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await proc.communicate()
            if proc.returncode != 0:
                logger.error(f"git clone failed: {stderr.decode(errors='replace')}")
                return []

            # Find SKILL.md files
            search_root = Path(tmpdir)
            if skill_path:
                search_root = search_root / skill_path
            skill_files = sorted(search_root.rglob("SKILL.md"))
            if not skill_files:
                # Also try *.md files that look like skills
                skill_files = sorted(search_root.rglob("*.md"))

            installed: list[Skill] = []
            for sf in skill_files:
                text = sf.read_text(encoding="utf-8", errors="replace")
                skill = self._install_from_text(text, source=f"{repo_url}#{sf.relative_to(Path(tmpdir))}")
                if skill is not None:
                    installed.append(skill)
            return installed

    async def install_from_directory(self, dir_path: Path | str) -> list[Skill]:
        """Install all SKILL.md files from a local directory."""
        dir_path = Path(dir_path)
        if not dir_path.is_dir():
            raise NotADirectoryError(f"Not a directory: {dir_path}")
        installed: list[Skill] = []
        for sf in sorted(dir_path.rglob("SKILL.md")):
            text = sf.read_text(encoding="utf-8", errors="replace")
            skill = self._install_from_text(text, source=str(sf))
            if skill is not None:
                installed.append(skill)
        return installed

    async def install_from_catalog(self, name: str) -> Skill | list[Skill] | None:
        """Install a skill by name from the catalog."""
        entry = next((e for e in self._catalog if e.name == name), None)
        if entry is None:
            logger.error(f"Skill '{name}' not in catalog")
            return None
        if entry.source == "http":
            return await self.install_from_url(entry.url, name=entry.name)
        if entry.source == "git":
            return await self.install_from_git(entry.url)
        if entry.source == "local":
            return await self.install_from_directory(entry.url)
        logger.error(f"Unknown source type: {entry.source}")
        return None

    def _install_from_text(self, text: str, *, name: str | None = None, source: str = "") -> Skill | None:
        """Validate and install a SKILL.md from its text content."""
        try:
            skill = Skill.from_markdown(text)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Invalid SKILL.md: {exc}")
            return None
        if name:
            skill.name = name
        if not skill.name:
            logger.error("SKILL.md has no name — skipping")
            return None

        # Write to disk
        dest = self.skills_dir / f"{skill.name}.md"
        dest.write_text(text, encoding="utf-8")
        skill.status = SkillStatus.ACTIVE

        # Register in engine
        self.engine._skills[skill.skill_id] = skill
        logger.info(f"Installed skill '{skill.name}' from {source}")
        return skill

    # ------------------------------------------------------------------
    #  Uninstall
    # ------------------------------------------------------------------

    def uninstall(self, name: str) -> bool:
        """Remove a skill by name."""
        # Find file
        target = self.skills_dir / f"{name}.md"
        if target.is_file():
            target.unlink()
            # Also remove from engine
            for sid, s in list(self.engine._skills.items()):
                if s.name.lower() == name.lower():
                    del self.engine._skills[sid]
            return True
        return False

    # ------------------------------------------------------------------
    #  Listing
    # ------------------------------------------------------------------

    def list_installed(self) -> list[Path]:
        """List installed skill files."""
        return sorted(self.skills_dir.glob("*.md"))


__all__ = ["SkillMarketplace", "CatalogEntry"]
