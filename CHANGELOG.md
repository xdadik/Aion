# Changelog

All notable changes to Aion Hand will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added — Phase 3 (2026-08-08)

#### New core modules
- **`aion_core/voice/`** — Text-to-speech + speech-to-text with multi-backend
  support (pyttsx3, macOS `say`, Linux `espeak`, OpenAI Whisper). Graceful
  fallback when no backend is available. `Voice.speak()`, `Voice.transcribe()`,
  `Voice.transcribe_microphone()`.
- **`aion_core/browser/`** — Web automation with Playwright (if installed) and
  stdlib urllib fallback. `Browser.fetch()`, `Browser.screenshot()`,
  `Browser.click()`, `Browser.fill_form()`. Returns parsed `Page` objects with
  title, text, links, meta.
- **`aion_core/backup/`** — Full backup/restore of agent state
  (`~/.aion-hand/`) to a single tar.gz archive. `BackupManager.backup()`,
  `BackupManager.restore()`, `BackupManager.list_backups()`,
  `BackupManager.cleanup_old()`. Includes MANIFEST.json with version + items.
- **`aion_core/computer_use/`** — Screen capture + mouse + keyboard automation
  with multi-backend support (PIL/pynput, macOS screencapture, Linux xdotool).
  Graceful fallback when no backend is available.
- **`aion_core/plugins/`** — Runtime-loadable Python plugins from
  `~/.aion-hand/plugins/`. Each plugin defines `register(registry)` and can
  add tools, skills, personas, providers, cron tasks, and system prompt
  extensions.
- **`aion_core/mcp/server.py`** — Aion as an MCP **server** (not just client).
  Exposes Aion's tools to other MCP clients (Hermes, OpenClaw, Claude Desktop)
  over stdio using JSON-RPC 2.0. Entry point: `python -m aion_core.mcp.server`.
- **`aion_core/memory/consolidator.py`** — Real background consolidation task
  that runs every 5 minutes (configurable). Promotes durable facts to
  long-term memory, extracts user attributes (name, location, job),
  updates MEMORY.md and USER.md, triggers skill auto-creation.
- **`aion_core/skills/marketplace.py`** — Skill marketplace client.
  Install skills from HTTP URLs, git repos, or local directories.
  `SkillMarketplace.install_from_url()`, `install_from_git()`,
  `install_from_directory()`, `install_from_catalog()`, `uninstall()`.

#### Skills
- Ported **59 skills** from Hermes Agent's skill collection (with permission;
  same MIT license). Aion now ships with **70 skills** total (was 11).
  Categories: Apple ecosystem, email, productivity, GitHub, creative,
  research, OSINT, media, social, core, devops, autonomous agents,
  computer use, smart home, note-taking, MLOps, themes, plugins.

#### Personas
- Added **16 new SOUL.md persona templates** (total 21): writer, tutor,
  devops, pm, sales, chef, finance, fitness, travel, doctor, lawyer,
  therapist, gaming, sre, architect, philosopher.

#### Skill engine improvements
- `Skill.from_markdown()` now parses YAML frontmatter (Hermes/OpenClaw format)
  in addition to the legacy plain-markdown format. Supports leading HTML
  comments before the frontmatter delimiter.

#### Tests
- Added **69 new tests** across 8 new test files (total 488 passing):
  - `tests/test_voice.py` — TTS/STT backend detection, fallback, list_voices
  - `tests/test_browser.py` — stdlib HTML parsers, Page dataclass, live fetch
  - `tests/test_backup.py` — backup/restore roundtrip, manifest, cleanup
  - `tests/test_marketplace.py` — install from URL/dir, uninstall, list
  - `tests/test_computer_use.py` — backend detection, unavailable raises
  - `tests/test_plugins.py` — registry, loader, failed plugin isolation
  - `tests/test_mcp_server.py` — JSON-RPC, initialize, tools/list, tools/call
  - `tests/test_memory_consolidator.py` — fact extraction, MEMORY.md update

### Changed
- `Skill.from_markdown()` is now YAML-frontmatter-aware (was plain-markdown only).

### Fixed
- `tarfile.extract()` now uses the `filter="data"` argument on Python 3.12+
  to prevent path-traversal and other tar-based attacks (Python 3.14 deprecation).
- Skill parser no longer returns "unnamed" for skills with YAML frontmatter
  that don't have an H1 heading.

---

## [0.3.0] — 2026-08-08 (Phase 1+2)

### Added
- **`aion_core/tui/`** — Rich-based interactive terminal UI with markdown
  rendering, tool-call panels, 16-command palette (`/help`, `/memory`,
  `/skills`, `/tools`, `/persona`, `/benchmark`, …). Entry point: `aion-tui`.
- **`aion_core/persona/`** — SOUL.md persona system (OpenClaw-inspired).
  5 built-in personas (default, researcher, coder, assistant, analyst).
  User personas shadow built-ins. `PersonaManager.apply_to_agent()`.
- **11 starter skills** in `skills/library/`: plan, TDD, systematic-debugging,
  code-review, web-research, git-workflow, documentation, simplify-code,
  api-design, security-hardening, performance-optimization.
- **GitHub Actions CI** (`.github/workflows/ci.yml`): matrix test on
  Python 3.11/3.12/3.13 across Ubuntu/macOS/Windows + web UI build.
- **`tests/test_benchmark.py`** (13 tests), **`tests/test_messaging_platforms.py`**
  (13 tests), **`tests/test_learning_loop.py`** (16 tests).

### Fixed
- 2 failing tests (`asyncio.get_event_loop().run_until_complete` → `asyncio.run`)
- All `datetime.utcnow()` deprecations (replaced with `datetime.now(UTC)`)
- 249 ruff lint issues auto-fixed
- `.gitignore` now excludes `.next/`, `node_modules/`, `*.tsbuildinfo`

---

## [0.2.0] — 2026-08-07 (pre-phase-0 baseline)

- Initial public baseline: 97 Python files, 34K LOC, 24 test files.
- Existing modules: agent, security, providers, memory, tools, skills,
  pipeline, orchestration, mcp (client only), knowledge, messaging,
  cron, dynamic, router, benchmark, config.
- Existing CLI: `aion-hand` (2589-line argparse-based REPL).
- Existing web UI: Next.js 15 + Tailwind 4 dashboard.
