# ADR-0003: Use SOUL.md format for agent personas

Date: 2026-08-08
Status: Accepted

## Context

Aion needs a way to define agent personas — different "personalities" /
operating modes the agent can switch between (e.g. researcher, coder,
assistant). Each persona shapes the system prompt, default model, and
temperature.

OpenClaw uses a `SOUL.md` format for this — a single Markdown file per
persona with YAML frontmatter (name, display_name, description, tags,
default_model, default_temperature) and a body that becomes the system
prompt. OpenClaw has 200+ community-published SOUL.md templates.

Hermes Agent does not have a persona system — its "personality" is a
single string in config.json.

## Decision

Adopt OpenClaw's `SOUL.md` format for Aion personas. The
`PersonaManager` resolves personas from:
1. `~/.aion-hand/personas/<name>.md` (user — wins)
2. `aion_core/persona/templates/<name>.md` (built-in)

The active persona is recorded in `~/.aion-hand/personas/.active` and
survives restarts. `PersonaManager.apply_to_agent(agent, name)` injects
the persona's system prompt + model/temperature overrides into an agent.

## Consequences

### Positive
- Direct compatibility with OpenClaw persona templates — users can drop
  any OpenClaw SOUL.md into `~/.aion-hand/personas/` and it works.
- 21 built-in personas cover common use cases (default, researcher, coder,
  assistant, analyst, writer, tutor, devops, pm, sales, chef, finance,
  fitness, travel, doctor, lawyer, therapist, gaming, sre, architect,
  philosopher).
- User personas shadow built-ins — users can override `default.md` to
  customise the agent's behaviour globally.

### Negative
- Two persona sources (built-in + user) means name conflicts need a
  resolution rule (user wins).
- Adds `pyyaml` dependency (shared with skill format — ADR-0002).

## Alternatives Considered

- **JSON config** — rejected: less human-readable, no Markdown body.
- **Python class per persona** — rejected: too heavy, requires code for
  every persona, no ecosystem compatibility.
- **Single "personality" string in config (Hermes-style)** — rejected:
  too limited — can't switch personas at runtime, no per-persona model
  overrides.
