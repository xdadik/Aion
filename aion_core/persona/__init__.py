"""Aion Hand Persona System — SOUL.md format.

Inspired by OpenClaw's SOUL.md (the agent persona template format),
this module lets users define, switch, and persist agent personas.

A persona is a single Markdown file (~/.aion-hand/personas/<name>.md) with:

    ---
    name: researcher
    display_name: Deep Researcher
    description: Methodical, cites sources, asks clarifying questions
    tags: [research, analysis]
    default_model: gpt-4o
    default_temperature: 0.2
    ---
    # SOUL: Deep Researcher

    ## Identity
    You are a meticulous researcher...

    ## Voice & Tone
    - Precise, calm, slightly academic
    - Always cites sources inline as [1], [2]
    - Prefers questions over assumptions

    ## Operating Principles
    1. Always search the web before answering factual claims
    2. ...

    ## Tools you prefer
    - web_search
    - web_fetch
    - read_file

    ## Avoid
    - Speculation without evidence
    - ...

A persona is loaded into the agent's system prompt at startup. Switching
personas at runtime rewrites the system prompt and clears the working
memory (so the new persona starts fresh).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore[import-not-found]

    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

DEFAULT_PERSONA_DIR = Path.home() / ".aion-hand" / "personas"
BUILTIN_PERSONA_DIR = Path(__file__).parent / "templates"


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------


@dataclass
class Persona:
    """A single agent persona."""

    name: str
    display_name: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    default_model: str | None = None
    default_temperature: float | None = None
    body_markdown: str = ""
    source_path: str | None = None

    def to_system_prompt(self) -> str:
        """Render the persona as a system prompt for the LLM."""
        lines = []
        if self.display_name:
            lines.append(f"# Persona: {self.display_name}")
        if self.description:
            lines.append(f"\n*{self.description}*\n")
        lines.append(self.body_markdown.strip())
        return "\n".join(lines).strip()

    def to_markdown(self) -> str:
        """Serialise back to the SOUL.md on-disk format."""
        front = {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "tags": self.tags,
        }
        if self.default_model is not None:
            front["default_model"] = self.default_model
        if self.default_temperature is not None:
            front["default_temperature"] = self.default_temperature
        if _YAML_AVAILABLE:
            front_str = yaml.safe_dump(
                front, sort_keys=False, allow_unicode=True
            ).strip()
        else:
            # Minimal YAML serialiser — good enough for our flat structure.
            front_str = "\n".join(f"{k}: {v!r}" for k, v in front.items())
        return f"---\n{front_str}\n---\n\n{self.body_markdown.strip()}\n"

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "display_name": self.display_name,
            "description": self.description,
            "tags": self.tags,
            "default_model": self.default_model,
            "default_temperature": self.default_temperature,
            "body_markdown": self.body_markdown,
            "source_path": self.source_path,
        }


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def parse_persona_markdown(text: str, source_path: str | None = None) -> Persona:
    """Parse a SOUL.md document into a Persona.

    Frontmatter is YAML (or simple key:value if PyYAML is missing).
    Body is the system-prompt markdown.
    """
    m = _FRONTMATTER_RE.match(text)
    if not m:
        # No frontmatter — entire text is the body, name is unknown
        return Persona(
            name="unnamed",
            body_markdown=text.strip(),
            source_path=source_path,
        )

    front_raw, body = m.group(1), m.group(2)
    front: dict[str, Any]
    if _YAML_AVAILABLE:
        front = yaml.safe_load(front_raw) or {}
    else:
        # Crude fallback: key: value, with [a, b, c] parsed as list
        front = {}
        for line in front_raw.splitlines():
            if ":" not in line:
                continue
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if v.startswith("[") and v.endswith("]"):
                front[k] = [
                    x.strip().strip("'\"") for x in v[1:-1].split(",") if x.strip()
                ]
            else:
                front[k] = v.strip("'\"")

    return Persona(
        name=str(front.get("name", "unnamed")),
        display_name=str(front.get("display_name", "")),
        description=str(front.get("description", "")),
        tags=list(front.get("tags", []) or []),
        default_model=front.get("default_model"),
        default_temperature=front.get("default_temperature"),
        body_markdown=body.strip(),
        source_path=source_path,
    )


# ---------------------------------------------------------------------------
# Manager
# ---------------------------------------------------------------------------


class PersonaManager:
    """Load, list, switch, and persist personas.

    Personas are searched in this order:
        1. ~/.aion-hand/personas/<name>.md          (user, wins)
        2. <package>/persona/templates/<name>.md    (built-in)

    The active persona is recorded in ~/.aion-hand/personas/.active
    so it survives restarts.
    """

    def __init__(
        self,
        user_dir: Path | str | None = None,
        builtin_dir: Path | str | None = None,
    ):
        self.user_dir = Path(user_dir) if user_dir else DEFAULT_PERSONA_DIR
        self.builtin_dir = Path(builtin_dir) if builtin_dir else BUILTIN_PERSONA_DIR
        self._active_file = self.user_dir / ".active"
        self.user_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    #  Listing
    # ------------------------------------------------------------------

    def list_personas(self) -> list[str]:
        """Return all persona names (user + built-in, user shadows builtin)."""
        names: set[str] = set()
        if self.builtin_dir.is_dir():
            for p in self.builtin_dir.glob("*.md"):
                names.add(p.stem)
        for p in self.user_dir.glob("*.md"):
            names.add(p.stem)
        return sorted(names)

    def persona_exists(self, name: str) -> bool:
        return self._resolve_path(name) is not None

    def _resolve_path(self, name: str) -> Path | None:
        user_path = self.user_dir / f"{name}.md"
        if user_path.is_file():
            return user_path
        builtin_path = self.builtin_dir / f"{name}.md"
        if builtin_path.is_file():
            return builtin_path
        return None

    # ------------------------------------------------------------------
    #  Loading / saving
    # ------------------------------------------------------------------

    def load(self, name: str) -> Persona | None:
        path = self._resolve_path(name)
        if path is None:
            return None
        text = path.read_text(encoding="utf-8")
        return parse_persona_markdown(text, source_path=str(path))

    def save(self, persona: Persona) -> Path:
        """Save a persona to the user dir."""
        self.user_dir.mkdir(parents=True, exist_ok=True)
        path = self.user_dir / f"{persona.name}.md"
        path.write_text(persona.to_markdown(), encoding="utf-8")
        return path

    def delete(self, name: str) -> bool:
        path = self.user_dir / f"{name}.md"
        if path.is_file():
            path.unlink()
            return True
        return False  # built-in personas cannot be deleted

    # ------------------------------------------------------------------
    #  Active persona
    # ------------------------------------------------------------------

    def get_active_name(self) -> str:
        """Return the active persona name, or 'default' if none set."""
        if self._active_file.is_file():
            return self._active_file.read_text(encoding="utf-8").strip() or "default"
        return "default"

    def set_active(self, name: str) -> bool:
        if not self.persona_exists(name):
            return False
        self._active_file.write_text(name, encoding="utf-8")
        return True

    def get_active(self) -> Persona | None:
        return self.load(self.get_active_name())

    # ------------------------------------------------------------------
    #  Agent integration
    # ------------------------------------------------------------------

    def apply_to_agent(self, agent: Any, name: str | None = None) -> bool:
        """Load a persona and inject its system prompt into an agent.

        If the agent has ``set_system_prompt`` we use it; otherwise we
        set ``agent.config.system_prompt`` directly. Returns True on success.
        """
        target = name or self.get_active_name()
        persona = self.load(target)
        if persona is None:
            return False
        prompt = persona.to_system_prompt()
        if hasattr(agent, "set_system_prompt"):
            try:
                agent.set_system_prompt(prompt)
            except Exception:  # noqa: BLE001
                return False
        else:
            cfg = getattr(agent, "config", None)
            if cfg is not None:
                try:
                    cfg.system_prompt = prompt
                except Exception:  # noqa: BLE001
                    return False
        # Persist the active persona
        self.set_active(target)
        # Apply model/temperature overrides if present
        cfg = getattr(agent, "config", None)
        if cfg is not None:
            if persona.default_model and hasattr(cfg, "default_model"):
                try:
                    cfg.default_model = persona.default_model
                except Exception:  # noqa: BLE001
                    pass
            if persona.default_temperature is not None and hasattr(
                cfg, "default_temperature"
            ):
                try:
                    cfg.default_temperature = persona.default_temperature
                except Exception:  # noqa: BLE001
                    pass
        return True


# ---------------------------------------------------------------------------
#  Public API
# ---------------------------------------------------------------------------

__all__ = [
    "Persona",
    "PersonaManager",
    "parse_persona_markdown",
    "DEFAULT_PERSONA_DIR",
    "BUILTIN_PERSONA_DIR",
]
