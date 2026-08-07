"""Aion Hand Skills Engine.

Self-improving skill system inspired by Hermes Agent's SKILL.md format.
Skills are created from experience and refined over time.

A Skill has:
  - name, description, version
  - SKILL.md content (instructions for the agent)
  - metadata (created, modified, usage count, success rate)
  - tags for categorization and discovery

Usage:
    engine = SkillEngine()
    skill = engine.create_from_experience(
        name="python-rest-api",
        task="Build a REST API",
        lessons_learned=["Use FastAPI for async", "Add JWT auth"],
    )
    skills = engine.find_relevant("Build an API endpoint")
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class SkillStatus(str, Enum):
    """Lifecycle status of a skill."""
    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"
    DEPRECATED = "deprecated"


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass
class Skill:
    """Represents a single learnable skill.

    Skills follow the SKILL.md format from Hermes Agent:
        # Skill Name
        Description of the skill.
        ## When to use
        Conditions under which this skill applies.
        ## Instructions
        Step-by-step instructions.
        ## Lessons Learned
        Key insights from past experience.
    """

    name: str
    description: str = ""
    content: str = ""
    version: str = "1.0.0"
    status: SkillStatus = SkillStatus.DRAFT
    tags: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    modified_at: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    usage_count: int = 0
    success_count: int = 0
    skill_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])

    # --- Properties ---

    @property
    def success_rate(self) -> float:
        """Return success rate as a float 0-1."""
        if self.usage_count == 0:
            return 0.0
        return self.success_count / self.usage_count

    # --- Serialization ---

    def to_markdown(self) -> str:
        """Serialize the skill to SKILL.md format."""
        tags_str = ", ".join(self.tags) if self.tags else "none"
        parts = [
            f"# {self.name}",
            "",
            f"**Version:** {self.version} | **Status:** {self.status.value} | "
            f"**Tags:** {tags_str}",
            "",
            self.description or "(no description)",
            "",
        ]
        # When to use section
        when = self.metadata.get("when_to_use", "")
        if when:
            parts.extend(["## When to Use", "", when, ""])

        # Instructions section
        instructions = self.metadata.get("instructions", "")
        if instructions:
            parts.extend(["## Instructions", "", instructions, ""])

        # Content
        if self.content:
            parts.extend(["## Details", "", self.content, ""])

        # Lessons learned
        lessons = self.metadata.get("lessons_learned", [])
        if lessons:
            parts.append("## Lessons Learned")
            parts.append("")
            for i, lesson in enumerate(lessons, 1):
                parts.append(f"{i}. {lesson}")
            parts.append("")

        # Metadata footer
        parts.extend([
            "---",
            f"Created: {self.created_at} | Modified: {self.modified_at}",
            f"Usage: {self.usage_count} | Success Rate: {self.success_rate:.0%}",
        ])
        return "\n".join(parts)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dictionary."""
        return {
            "skill_id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "content": self.content,
            "version": self.version,
            "status": self.status.value,
            "tags": self.tags,
            "metadata": self.metadata,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "usage_count": self.usage_count,
            "success_count": self.success_count,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Skill:
        """Deserialize from dictionary."""
        data = dict(data)  # copy
        data["status"] = SkillStatus(data.get("status", "draft"))
        return cls(**data)

    @classmethod
    def from_markdown(cls, md_text: str) -> Skill:
        """Parse a SKILL.md formatted string into a Skill object.

        Supports two formats:
          1. YAML frontmatter (Hermes / OpenClaw style):
                ---
                name: my-skill
                description: What it does
                tags: [a, b]
                ---
                # Body content with sections

          2. Plain markdown (legacy Aion style):
                # Name
                Description text
                ## Sections...
        """
        # First, check for YAML frontmatter
        front_matter: dict[str, Any] = {}
        body_text = md_text
        # Allow leading whitespace / HTML comments / blank lines before the frontmatter
        frontmatter_match = re.match(
            r"^(?:\s|<!--.*?-->)*---\s*\n(.*?)\n---\s*\n?(.*)$",
            md_text,
            re.DOTALL,
        )
        if frontmatter_match:
            front_raw = frontmatter_match.group(1)
            body_text = frontmatter_match.group(2)
            # Parse simple YAML key: value pairs (and inline lists)
            try:
                import yaml  # type: ignore[import-not-found]
                front_matter = yaml.safe_load(front_raw) or {}
            except ImportError:
                # Crude fallback
                for line in front_raw.splitlines():
                    if ":" not in line:
                        continue
                    k, _, v = line.partition(":")
                    k, v = k.strip(), v.strip()
                    if v.startswith("[") and v.endswith("]"):
                        front_matter[k] = [x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()]
                    else:
                        front_matter[k] = v.strip("'\"")

        lines = body_text.strip().split("\n") if body_text else []
        name = front_matter.get("name") or "unnamed"
        description = str(front_matter.get("description", ""))
        sections: dict[str, list[str]] = {}
        current_section = "_header"
        sections[current_section] = []

        for line in lines:
            if line.startswith("# ") and not line.startswith("## "):
                # If name not set from frontmatter, use the H1
                if not front_matter.get("name"):
                    name = line[2:].strip()
                current_section = "_header"
                sections[current_section] = []
            elif line.startswith("## "):
                current_section = line[3:].strip().lower().replace(" ", "_")
                sections[current_section] = []
            else:
                sections.setdefault(current_section, []).append(line)

        # If description not set from frontmatter, derive from header lines
        if not description:
            header_lines = sections.get("_header", [])
            desc_lines = []
            for hl in header_lines:
                hl = hl.strip()
                if hl and not hl.startswith("**") and not hl.startswith("---"):
                    desc_lines.append(hl)
            description = " ".join(desc_lines)

        metadata: dict[str, Any] = {}
        lessons = sections.get("lessons_learned", [])
        lessons_clean = [l.strip().lstrip("0123456789. ") for l in lessons if l.strip()]
        if lessons_clean:
            metadata["lessons_learned"] = lessons_clean

        when_lines = sections.get("when_to_use", [])
        if when_lines:
            metadata["when_to_use"] = "\n".join(when_lines).strip()

        instructions = sections.get("instructions", [])
        if instructions:
            metadata["instructions"] = "\n".join(instructions).strip()

        details = sections.get("details", [])
        content = "\n".join(details).strip() if details else body_text.strip()

        # Tags: prefer frontmatter, fall back to inline "**Tags:**" line
        tags: list[str] = []
        if front_matter.get("tags"):
            tags_raw = front_matter["tags"]
            if isinstance(tags_raw, list):
                tags = [str(t) for t in tags_raw]
            else:
                tags = [t.strip() for t in str(tags_raw).split(",")]
        else:
            tags_match = re.search(r"\*\*Tags:\*\*\s*(.+?)(?:\n|$)", md_text)
            if tags_match:
                tags_str = tags_match.group(1).strip()
                if tags_str.lower() != "none":
                    tags = [t.strip() for t in tags_str.split(",")]

        return cls(
            name=name,
            description=description,
            content=content,
            tags=tags,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Skill Engine
# ---------------------------------------------------------------------------

class SkillEngine:
    """Manages the lifecycle of skills: create, find, evaluate, evolve.

    Inspired by Hermes Agent's skill management with improvements:
      - Automatic skill creation from experience
      - Relevance matching via keyword + tag scoring
      - Skill evolution from outcomes
      - Persistent storage via JSON files
    """

    def __init__(self, storage_dir: Path | None = None):
        self._skills: dict[str, Skill] = {}
        self._storage_dir = storage_dir or Path.home() / ".aion-hand" / "skills"
        self._auto_create_enabled = True

    # --- CRUD ---

    def create_skill(
        self,
        name: str,
        description: str = "",
        content: str = "",
        tags: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Skill:
        """Create a new skill."""
        skill = Skill(
            name=name,
            description=description,
            content=content,
            tags=tags or [],
            metadata=metadata or {},
        )
        self._skills[skill.skill_id] = skill
        logger.info(f"Skill created: {skill.name} ({skill.skill_id})")
        return skill

    def get_skill(self, skill_id: str) -> Skill | None:
        """Get a skill by ID."""
        return self._skills.get(skill_id)

    def get_skill_by_name(self, name: str) -> Skill | None:
        """Get a skill by name."""
        for skill in self._skills.values():
            if skill.name.lower() == name.lower():
                return skill
        return None

    def list_skills(
        self,
        status: SkillStatus | None = None,
        tag: str | None = None,
    ) -> list[Skill]:
        """List skills with optional filtering."""
        skills = list(self._skills.values())
        if status is not None:
            skills = [s for s in skills if s.status == status]
        if tag is not None:
            skills = [s for s in skills if tag.lower() in [t.lower() for t in s.tags]]
        return sorted(skills, key=lambda s: s.name)

    def delete_skill(self, skill_id: str) -> bool:
        """Delete a skill by ID."""
        if skill_id in self._skills:
            del self._skills[skill_id]
            return True
        return False

    def update_skill(self, skill_id: str, **kwargs) -> Skill | None:
        """Update a skill's fields."""
        skill = self._skills.get(skill_id)
        if skill is None:
            return None
        for key, value in kwargs.items():
            if hasattr(skill, key):
                setattr(skill, key, value)
        skill.modified_at = datetime.now(UTC).isoformat()
        return skill

    # --- Skill Discovery ---

    def find_relevant(self, query: str, limit: int = 5) -> list[Skill]:
        """Find skills relevant to a query using keyword + tag matching."""
        query_lower = query.lower()
        query_words = set(re.findall(r"\w+", query_lower))
        scored: list[tuple] = []

        for skill in self._skills.values():
            if skill.status == SkillStatus.ARCHIVED:
                continue
            score = 0.0
            name_lower = skill.name.lower()
            desc_lower = skill.description.lower()
            content_lower = skill.content.lower()

            # Exact name match (highest score)
            if query_lower in name_lower:
                score += 10.0
            # Name word overlap
            name_words = set(re.findall(r"\w+", name_lower))
            if name_words & query_words:
                score += len(name_words & query_words) * 3.0
            # Description match
            if query_lower in desc_lower:
                score += 5.0
            desc_words = set(re.findall(r"\w+", desc_lower))
            if desc_words & query_words:
                score += len(desc_words & query_words) * 2.0
            # Content match
            if query_lower in content_lower:
                score += 1.0
            content_words = set(re.findall(r"\w+", content_lower))
            if content_words & query_words:
                score += len(content_words & query_words) * 0.5
            # Tag match
            for tag in skill.tags:
                if tag.lower() in query_lower or tag.lower() in query_words:
                    score += 4.0
            # Usage bonus (more used = more likely relevant)
            score += min(skill.success_rate * 2.0, 2.0)

            if score > 0:
                scored.append((score, skill))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [s for _, s in scored[:limit]]

    # --- Auto-creation from Experience ---

    def create_from_experience(
        self,
        name: str,
        task: str,
        lessons_learned: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> Skill | None:
        """Create a new skill from a completed task and lessons learned."""
        if not self._auto_create_enabled:
            return None

        existing = self.get_skill_by_name(name)
        if existing:
            logger.info(f"Skill '{name}' already exists, updating instead")
            return self.evolve_skill(existing.skill_id, lessons_learned or [])

        content = f"Task: {task}\n"
        if lessons_learned:
            content += "\nKey insights:\n"
            for lesson in lessons_learned:
                content += f"- {lesson}\n"

        skill = self.create_skill(
            name=name,
            description=f"Learned from task: {task[:100]}",
            content=content,
            tags=tags or [],
            metadata={
                "lessons_learned": lessons_learned or [],
                "source_task": task,
                "auto_created": True,
            },
        )
        skill.status = SkillStatus.ACTIVE
        logger.info(f"Auto-created skill: {skill.name} ({skill.skill_id})")
        return skill

    def evaluate_auto_create(
        self,
        task: str,
        outcome: str,
        tokens_used: int = 0,
    ) -> Skill | None:
        """Evaluate if a completed task should result in a new skill.

        Heuristics:
          - Task involved tool usage
          - Task took multiple turns
          - Task has reusable patterns
          - Outcome was successful
        """
        task_lower = task.lower()
        indicators = [
            "build", "create", "implement", "develop", "deploy",
            "configure", "setup", "install", "analyze", "process",
        ]
        has_indicator = any(ind in task_lower for ind in indicators)
        is_long_task = tokens_used > 1000 or len(task) > 100
        is_success = any(
            w in outcome.lower() for w in ["success", "complete", "done", "ok"]
        )

        if has_indicator and (is_long_task or is_success):
            name = self._generate_skill_name(task)
            return self.create_from_experience(
                name=name,
                task=task[:500],
                lessons_learned=[f"Outcome: {outcome[:200]}"],
            )
        return None

    def _generate_skill_name(self, task: str) -> str:
        """Generate a skill name from task text."""
        words = re.findall(r"\w+", task.lower())
        stop_words = {"the", "a", "an", "and", "or", "to", "for", "with", "is", "it"}
        keywords = [w for w in words[:10] if w not in stop_words and len(w) > 2]
        return "-".join(keywords[:5]) if keywords else "unnamed-skill"

    # --- Evolution ---

    def evolve_skill(
        self,
        skill_id: str,
        new_lessons: list[str],
    ) -> Skill | None:
        """Evolve an existing skill with new lessons learned."""
        skill = self._skills.get(skill_id)
        if skill is None:
            return None

        existing = skill.metadata.get("lessons_learned", [])
        combined = existing + [l for l in new_lessons if l not in existing]
        skill.metadata["lessons_learned"] = combined
        skill.modified_at = datetime.now(UTC).isoformat()
        if skill.status == SkillStatus.DRAFT:
            skill.status = SkillStatus.ACTIVE

        logger.info(
            f"Skill evolved: {skill.name} ({len(new_lessons)} new lessons)"
        )
        return skill

    def record_usage(self, skill_id: str, success: bool = True) -> None:
        """Record a skill usage for statistics."""
        skill = self._skills.get(skill_id)
        if skill:
            skill.usage_count += 1
            if success:
                skill.success_count += 1

    # --- Persistence ---

    def save(self, directory: Path | None = None) -> int:
        """Save all skills to JSON files."""
        save_dir = directory or self._storage_dir
        save_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for skill in self._skills.values():
            filepath = save_dir / f"{skill.skill_id}.json"
            try:
                atomic_write = getattr(
                    __import__("aion_core.security.filesafety", fromlist=["FileSafetyChecker"]),
                    "FileSafetyChecker",
                    None,
                )
            except (ImportError, AttributeError):
                filepath.write_text(json.dumps(skill.to_dict(), indent=2))
            else:
                checker = atomic_write()
                checker.atomic_write(str(filepath), json.dumps(skill.to_dict(), indent=2))
            count += 1
        logger.info(f"Saved {count} skills to {save_dir}")
        return count

    def load(self, directory: Path | None = None) -> int:
        """Load skills from JSON files."""
        load_dir = directory or self._storage_dir
        if not load_dir.exists():
            return 0
        count = 0
        for filepath in sorted(load_dir.glob("*.json")):
            try:
                data = json.loads(filepath.read_text())
                skill = Skill.from_dict(data)
                self._skills[skill.skill_id] = skill
                count += 1
            except (json.JSONDecodeError, KeyError, TypeError) as e:
                logger.warning(f"Failed to load skill from {filepath}: {e}")
        logger.info(f"Loaded {count} skills from {load_dir}")
        return count

    # --- Properties ---

    @property
    def auto_create_enabled(self) -> bool:
        return self._auto_create_enabled

    @auto_create_enabled.setter
    def auto_create_enabled(self, value: bool) -> None:
        self._auto_create_enabled = value

    @property
    def skill_count(self) -> int:
        return len(self._skills)

    def get_stats(self) -> dict[str, Any]:
        """Return skill engine statistics."""
        skills = list(self._skills.values())
        active = [s for s in skills if s.status == SkillStatus.ACTIVE]
        return {
            "total_skills": len(skills),
            "active_skills": len(active),
            "draft_skills": len([s for s in skills if s.status == SkillStatus.DRAFT]),
            "archived_skills": len([s for s in skills if s.status == SkillStatus.ARCHIVED]),
            "auto_create_enabled": self._auto_create_enabled,
            "storage_dir": str(self._storage_dir),
        }

    def export_all_markdown(self, directory: Path | None = None) -> int:
        """Export all skills as SKILL.md files."""
        export_dir = directory or self._storage_dir / "exported"
        export_dir.mkdir(parents=True, exist_ok=True)
        count = 0
        for skill in self._skills.values():
            filepath = export_dir / f"{skill.name.replace(' ', '_')}.md"
            filepath.write_text(skill.to_markdown())
            count += 1
        return count
