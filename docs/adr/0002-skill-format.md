# ADR-0002: Use Hermes-compatible SKILL.md format with YAML frontmatter

Date: 2026-08-08
Status: Accepted

## Context

Aion needs a format for declaring skills (reusable agent capabilities).
Two established formats exist:

1. **Hermes Agent / OpenClaw SKILL.md** — Markdown with YAML frontmatter:
   ```markdown
   ---
   name: my-skill
   description: What it does
   tags: [a, b]
   ---
   # Skill Name
   ## When to use
   ...
   ```

2. **Legacy Aion format** — plain Markdown with `# Name` as first line:
   ```markdown
   # My Skill
   Description text
   ## When to use
   ...
   ```

Hermes has 200+ community-published skills in format #1. OpenClaw uses
the same format. The legacy Aion format has no ecosystem.

## Decision

Adopt the Hermes / OpenClaw SKILL.md format with YAML frontmatter as
the canonical Aion skill format. Keep backwards compatibility with the
plain-markdown format for any existing Aion-authored skills.

The parser (`Skill.from_markdown`) supports both formats:
- If the file starts with `---` (optionally preceded by HTML comments
  or whitespace), parse YAML frontmatter.
- Otherwise, fall back to `# Name` parsing.

## Consequences

### Positive
- Direct compatibility with the 200+ Hermes community skills — users can
  `pip install` or copy any Hermes skill and it works in Aion.
- Skill marketplace can list skills from any Hermes-compatible source.
- Richer metadata (version, author, tags, dependencies) via frontmatter.
- Clearer separation of metadata (machine-readable YAML) from instructions
  (human-readable Markdown body).

### Negative
- Adds `pyyaml` as an optional dependency (graceful fallback to a crude
  key:value parser if PyYAML is missing).
- Two supported formats means the parser is more complex.

### Mitigations
- PyYAML is in the `tui` optional dependency group; most users will have it.
- The fallback parser handles the common case (flat key:value with inline
  lists) well enough for skill discovery to work without PyYAML.

## Alternatives Considered

- **JSON schema** — rejected: less human-readable, no comment support.
- **TOML** — rejected: no multi-line string support, awkward for long
  instruction bodies.
- **Custom format** — rejected: loses ecosystem compatibility.
