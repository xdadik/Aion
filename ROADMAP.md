# Aion Hand — Roadmap

This document describes the planned direction for Aion Hand. It's a living
document — dates and priorities may shift based on community feedback.

## Status legend

- ✅ **Done** — shipped
- 🚧 **In progress** — actively being worked on
- 📋 **Planned** — accepted, will be done
- 💡 **Proposed** — under discussion
- ❌ **Rejected** — decided against (with reason)

---

## v0.4.0 (current — 2026-08-08)

### ✅ Done
- Rich TUI (`aion-tui`)
- SOUL.md persona system (26 built-in personas)
- Skill marketplace (HTTP/git/local install)
- 93 skills ported from Hermes + 11 Aion-original
- HTTP API server (14 endpoints + SSE streaming + CORS)
- Real messaging adapters (Telegram verified end-to-end, Discord, Slack, Webhook)
- Telemetry module (counters, gauges, histograms, traces)
- Health probes (liveness + readiness, K8s-friendly)
- Voice module (TTS + STT, multi-backend)
- Browser automation (Playwright + urllib fallback)
- Backup/restore system
- Computer use (screen/mouse/keyboard)
- Plugin system
- Memory consolidator (background task)
- MCP server (Aion exposes tools to other agents)
- RL training loop (reward model, trajectory collector, PPO-style optimizer)
- Native desktop app (Tauri — macOS/Windows/Linux)
- Docker setup (multi-stage Dockerfile + docker-compose)
- GitHub Actions (CI matrix, release, codeql)
- ADRs, CHANGELOG, COOKBOOK, INSTALL guide
- Code of Conduct, Contributing guide, Issue/PR templates
- 600+ passing tests

---

## v0.5.0 — Polishing & performance (planned: Q4 2026)

### 📋 Planned
- **Auto-update for desktop app** — Tauri updater plugin
- **Skill versioning** — semver for skills, dependency resolution
- **Streaming responses in TUI** — token-by-token rendering
- **Conversation branching** — fork a conversation at any point
- **Multi-user support** — per-user memory isolation
- **Audit log UI** — view/filter the execution audit log in web UI
- **Better error messages** — actionable, with links to docs
- **Performance pass** — profile hot paths, optimize memory manager

### 🚧 In progress
- Tighten lint (E501 line-length, ~500 remaining issues)
- More skill ports from Hermes (target: 150+)
- More real adapter integration tests (Discord, Slack with live tokens)

---

## v0.6.0 — Learning & intelligence (planned: Q1 2027)

### 💡 Proposed
- **Real RLHF** — integrate with HuggingFace TRL for actual fine-tuning
- **Skill evolution** — automatically refine skills based on usage outcomes
- **Cross-session memory graph** — visualize entity relationships
- **Tool composition** — chain tools into reusable workflows
- **Plan caching** — reuse plans for similar past tasks
- **Multi-modal inputs** — image, audio, video understanding
- **Local model support** — first-class Ollama + LM Studio integration

---

## v1.0.0 — Production-ready (planned: Q2 2027)

### 📋 Planned
- **API stability** — no breaking changes without major version bump
- **Comprehensive docs** — every public API documented with examples
- **Performance benchmarks** — published comparison vs. Hermes/OpenClaw
- **Security audit** — third-party audit, publish report
- **Long-term support** — security fixes for 12 months minimum

---

## Rejected ideas (with reasons)

### ❌ Build our own LLM
Aion is an agent framework, not a model. Users should be able to plug in
any LLM (OpenAI, Anthropic, Ollama, etc.). Building our own LLM would
violate the provider-agnostic principle.

### ❌ Reinvent MCP
MCP is becoming the standard tool-calling protocol. Aion implements it
both as client (use others' tools) and server (expose our tools). No
need for a custom protocol.

### ❌ Cloud-only mode
Aion is local-first. We will never require a cloud account. Cloud
integrations are optional and self-hostable.

### ❌ Tracking / telemetry by default
The telemetry module exists, but it's local-only (no phone-home).
Users must opt in to any external metric shipping.

---

## How to influence the roadmap

1. **Open an issue** with the `proposal` label
2. **Upvote existing proposals** with 👍 reactions
3. **Join Discussions** for design conversations
4. **Contribute** — PRs that implement roadmap items are very welcome

## Past releases

See [CHANGELOG.md](./CHANGELOG.md) for the full history.
