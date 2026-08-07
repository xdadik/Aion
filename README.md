<p align="center">
  <img src="assets/banner.png" alt="Aion Hand Banner" width="100%">
</p>

<!--
  ╔══════════════════════════════════════════════════════════════╗
  ║  AION HAND — The Ultimate Autonomous AI Agent Framework     ║
  ║  Combining OpenClaw · Hermes · NullClaw · CrewAI · AutoGPT  ║
  ╚══════════════════════════════════════════════════════════════╝
-->

<div align="center">

```
   ██████╗ ██╗      █████╗  ██████╗██╗  ██╗ █████╗ ██████╗ ███████╗██╗  ██╗
  ██╔════╝ ██║     ██╔══██╗██╔════╝██║ ██╔╝██╔══██╗██╔══██╗██╔════╝██║  ██║
  ██║  ███╗██║     ███████║██║     █████╔╝ ███████║██████╔╝█████╗  ██████║
  ██║   ██║██║     ██╔══██║██║     ██╔═██╗ ██╔══██║██╔══██╗██╔══╝  ██╔══██║
  ╚██████╔╝███████╗██║  ██║╚██████╗██║  ██╗██║  ██║██║  ██║███████╗██║  ██║
   ╚═════╝ ╚══════╝╚═╝  ╚═╝ ╚═════╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
```

### 🤖 AION HAND

**The Ultimate Open-Source Autonomous AI Agent Framework**
Combining the best of OpenClaw, Hermes Agent, NullClaw, CrewAI, AutoGPT & LangGraph

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Version 0.4.0](https://img.shields.io/badge/Version-0.4.0-orange.svg)](https://github.com/xdadik/Aion/releases)
[![Tests](https://img.shields.io/badge/Tests-600%2B-brightgreen.svg)](https://github.com/xdadik/Aion/actions)
[![Skills](https://img.shields.io/badge/Skills-93-blueviolet.svg)](skills/library/)
[![Personas](https://img.shields.io/badge/Personas-26-ff69b4.svg)](aion_core/persona/templates/)
[![Status-Alpha](https://img.shields.io/badge/Status-Alpha-yellow.svg)]()
[![Discord](https://img.shields.io/badge/Discord-coming_soon-7289da.svg)](https://github.com/xdadik/Aion/discussions)

[Features](#-features) · [Quick Start](#-quick-start) · [Architecture](#-architecture) · [Configuration](#-configuration) · [Documentation](#-core-modules) · [Roadmap](./ROADMAP.md) · [FAQ](./docs/FAQ.md)

</div>

---

## ✨ Features

> 30+ powerful capabilities packed into a single, modular framework.

### 🧠 Intelligence & Memory
- 🧠 **6-Layer Memory System** — Working → Session → Episodic → Semantic → Procedural → UserProfile (Hermes FTS5 + OpenClaw MEMORY.md)
- 📚 **Self-Improving Skills** — Hermes-compatible learning loop with auto-creation & refinement
- 🔍 **Full-Text Search** — SQLite FTS5 powered semantic memory retrieval
- 💡 **Memory Nudging** — Periodic background consolidation of working memory
- 📝 **Automatic Summaries** — Conversation summarization for episodic memory
- 👤 **User Profile Learning** — Automatically tracks preferences, patterns & identity

### 🔧 Tools & Actions
- 🔧 **25+ Built-in Tools** — MCP-compatible tool registry with schema validation
- 🖥️ **Shell Execution** — Sandboxed command execution with approval modes
- 🌐 **Web Search & Scraping** — Real-time web information retrieval
- 📁 **File Operations** — Read, write, list, and manage files
- 🧮 **Calculator** — Mathematical expression evaluation
- 📧 **Email Sending** — Automated email dispatch
- 🌤️ **Weather** — Real-time weather data
- 🗓️ **Calendar Management** — Event creation and management
- ✅ **Todo Management** — Task tracking and organization
- 📝 **Note Taking** — Create and search notes
- 🖼️ **Image Generation** — AI-powered image creation
- 🔊 **Text-to-Speech** — Convert text to spoken audio
- 🎤 **Speech-to-Text** — Transcribe audio to text
- 📋 **Clipboard** — Copy/paste operations
- 📊 **JSON Utilities** — Parse and format JSON data
- ⏰ **Date & Time** — Timezone-aware date utilities
- 💻 **System Info** — Hardware and OS information
- 🌐 **HTTP Requests** — Custom API calls
- 📝 **Text Summarization** — Condense long texts
- 💻 **Code Execution** — Run Python code snippets

### 🤝 Multi-Agent & Orchestration
- 🤝 **Multi-Agent Orchestration** — CrewAI + NullBoiler inspired subagent system
- 🔄 **Dynamic Agent Spawning** — Create isolated subagents for parallel tasks
- 📋 **Workflow Engine** — Define and execute complex agent workflows
- ⏱️ **Subagent Timeouts** — Configurable timeout per subagent task
- 🧩 **Role-Based Agents** — Assign different personalities and tools per agent

### 🔌 Providers & Integration
- 🔄 **Provider Agnostic** — NullClaw-inspired: works with any LLM (OpenAI, Anthropic, Ollama, etc.)
- 💬 **Streaming Support** — Real-time token streaming for responsive output
- 📡 **MCP Compatible** — Model Context Protocol for standard tool interfaces
- 🌐 **OpenAI Function Calling** — Native function-calling schema generation

### 💬 Messaging & Automation
- 💬 **Messaging Gateway** — OpenClaw-inspired multi-platform messaging (Telegram, Discord, Slack)
- ⏰ **Cron Scheduler** — Hermes-inspired automated task scheduling
- 🔔 **Platform Routing** — Route tasks to specific messaging platforms
- 📅 **Recurring Tasks** — Define cron expressions for periodic execution

### 🛡️ Security & Control
- 🛡️ **Security Sandbox** — Command validation, whitelists, and approval modes
- ✅ **Three Approval Modes** — Auto, Ask (prompt user), Deny
- 🚫 **Command Whitelisting** — Restrict allowed shell commands
- 👥 **User Access Control** — Allowed users list for messaging platforms
- 📋 **Execution Audit Log** — Ring-buffer log of all tool executions
- ⏱️ **Per-Tool Timeouts** — Prevent runaway tool executions

### 🖥️ Interface & Developer Experience
- 📊 **Web Dashboard** — Next.js + Tailwind CSS real-time monitoring UI (verified to build cleanly)
- 🎨 **Rich TUI** — beautiful interactive terminal UI with markdown rendering, tool-call panels, command palette (`/help`, `/memory`, `/skills`, `/tools`, `/persona`, `/benchmark`, …)
- 🖥️ **Full CLI with REPL** — Hermes-style TUI with colors, spinners, and readline history
- 🎭 **SOUL.md Persona System** — OpenClaw-inspired persona templates; 5 built-in (default, researcher, coder, assistant, analyst); user personas shadow built-ins
- 📦 **Zero Hard Dependencies** — Core runs on Python stdlib; extras are optional
- ⚡ **Lightweight Mode** — NullClaw-inspired minimal footprint mode
- 🧪 **Comprehensive Tests** — 419 passing tests across 24 test files (pytest + asyncio)
- 🎨 **ANSI Colored Output** — Beautiful terminal output everywhere
- 🔄 **Async Throughout** — Fully async/await architecture
- 📁 **Pluggable Architecture** — Drop-in custom tools, skills, and providers
- 🤖 **CI/CD** — GitHub Actions matrix testing on Python 3.11/3.12/3.13 across Ubuntu/macOS/Windows

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           🤖 AION HAND v0.1.0                              │
│                    The Ultimate AI Agent Framework                          │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────┐  ┌──────────────┐  ┌─────────────┐  ┌──────────────────┐  │
│  │   CLI (REPL)│  │ Web Dashboard│  │  Messaging  │  │  Cron Scheduler  │  │
│  │  aion_hand_ │  │  Next.js +   │  │  Gateway     │  │  (Hermes-style)  │  │
│  │    cli      │  │  Tailwind    │  │  (Telegram,  │  │                  │  │
│  │             │  │              │  │  Discord,    │  │                  │  │
│  │             │  │              │  │  Slack)      │  │                  │  │
│  └──────┬──────┘  └──────┬───────┘  └──────┬──────┘  └────────┬─────────┘  │
│         │                │                 │                   │             │
│  ┌──────┴────────────────┴─────────────────┴───────────────────┴─────────┐  │
│  │                     🧠 Agent Core (AionHand)                        │  │
│  │                                                                      │  │
│  │  ┌─────────────────────────────────────────────────────────────┐     │  │
│  │  │                    Agent Loop (Think→Act→Observe)           │     │  │
│  │  └──────────┬──────────┬──────────┬──────────┬─────────────────┘     │  │
│  │             │          │          │          │                        │  │
│  │  ┌──────────▼──┐ ┌─────▼──────┐ ┌▼──────────▼┐ ┌──────────────┐     │  │
│  │  │  🧠 Memory  │ │ 🔧 Tools  │ │ 📚 Skills  │ │ 🔄 Provider  │     │  │
│  │  │   Manager   │ │  Registry  │ │  Engine    │ │  Factory     │     │  │
│  │  │             │ │            │ │            │ │              │     │  │
│  │  │ • Working   │ │ • 25+ built│ │ • Auto     │ │ • OpenAI     │     │  │
│  │  │ • Session   │ │ • MCP      │ │   create   │ │ • Anthropic  │     │  │
│  │  │ • Episodic  │ │   compat.  │ │ • Self-    │ │ • Ollama     │     │  │
│  │  │ • Semantic  │ │ • Approval │ │   improve  │ │ • Any LLM    │     │  │
│  │  │ • Procedural│ │   modes    │ │ • Hub sync │ │              │     │  │
│  │  │ • UserProf  │ │ • Audit    │ │            │ │              │     │  │
│  │  │             │ │   log      │ │ • SKILL.md │ │ • Streaming  │     │  │
│  │  │ • FTS5      │ │ • Custom   │ │   format   │ │ • Fallbacks  │     │  │
│  │  │   search    │ │   tools    │ │            │ │              │     │  │
│  │  │ • MEMORY.md │ │ • Timeout  │ │            │ │              │     │  │
│  │  │ • USER.md   │ │   control  │ │            │ │              │     │  │
│  │  └─────────────┘ └────────────┘ └────────────┘ └──────────────┘     │  │
│  │                                                                      │  │
│  │  ┌──────────────────────┐  ┌──────────────────────────────────────┐  │  │
│  │  │ 🤝 Orchestration     │  │ 🛡️ Security Sandbox                 │  │  │
│  │  │    Engine             │  │                                      │  │  │
│  │  │ • Subagent spawning  │  │ • Command validation & whitelisting  │  │  │
│  │  │ • Workflow execution  │  │ • Approval modes (auto/ask/deny)    │  │  │
│  │  │ • Role assignment    │  │ • User access control               │  │  │
│  │  │ • Parallel tasks     │  │ • Per-tool timeouts                 │  │  │
│  │  │ • NullBoiler compat. │  │ • Execution audit log               │  │  │
│  │  └──────────────────────┘  └──────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🆚 Aion vs. Hermes vs. OpenClaw

How does Aion Hand stack up against the frameworks it's inspired by?
Every row is a feature you can verify in this repo today.

| Capability | Aion Hand | Hermes Agent (Nous) | OpenClaw |
|---|:---:|:---:|:---:|
| **Language** | Python 3.11+ | TypeScript / Rust | TypeScript |
| **License** | MIT | Open-source | Open-source |
| **Self-hosted / local-first** | ✅ | ✅ | ✅ |
| **6-layer memory hierarchy** | ✅ | ✅ | ❌ (MEMORY.md only) |
| **MEMORY.md + USER.md** (human-readable) | ✅ | ✅ | ✅ |
| **FTS5 semantic memory search** | ✅ | ✅ | ❌ |
| **Self-improving skill auto-creation** | ✅ | ✅ | ❌ |
| **SKILL.md format compatibility** | ✅ | ✅ (native) | ❌ |
| **SOUL.md persona system** | ✅ (5 built-in templates) | ❌ | ✅ (signature feature) |
| **Tool registry + schema validation** | ✅ (25+ built-in) | ✅ | ✅ |
| **MCP (Model Context Protocol)** | ✅ | ✅ (native) | ✅ |
| **Multi-agent orchestration (DAG)** | ✅ | ❌ | ❌ |
| **Dynamic subagent spawning** | ✅ | ❌ | ❌ |
| **Mixture-of-Agents (MoA) loop** | ✅ | ❌ | ❌ |
| **Pipeline: plan → execute → verify → critique → repair** | ✅ | partial | ❌ |
| **Critic + 5-verifier pipeline** | ✅ | ❌ | ❌ |
| **Runtime learning (TaskLesson)** | ✅ | ✅ | ❌ |
| **Model router with cost/latency optimiser** | ✅ | ❌ | ❌ |
| **Knowledge graph (entity/relation)** | ✅ | ❌ | ❌ |
| **Cron scheduler** | ✅ | ✅ | ✅ |
| **20+ messaging platform adapters** | ✅ | ❌ | partial |
| **Telegram / Discord / Slack** | ✅ | ✅ | ✅ |
| **WeChat / QQ / Feishu / DingTalk / Line** | ✅ | ❌ | ❌ |
| **Security sandbox + approval modes** | ✅ | ✅ | ✅ |
| **Command whitelist + path-traversal guard** | ✅ | partial | partial |
| **Provider-agnostic (OpenAI / Anthropic / Ollama / …)** | ✅ | ✅ | ✅ |
| **Streaming responses** | ✅ | ✅ | ✅ |
| **Beautiful Rich TUI** | ✅ (new) | ✅ | ✅ |
| **Next.js web dashboard** | ✅ | ✅ (desktop) | ✅ |
| **Zero hard dependencies (stdlib-only core)** | ✅ | ❌ | ❌ |
| **Pluggable architecture (tools/skills/providers/verifiers)** | ✅ | ✅ | ✅ |
| **Built-in benchmark harness** | ✅ | ❌ | ❌ |
| **Cross-platform CI (Py 3.11/3.12/3.13, ubuntu/macos/win)** | ✅ | ✅ | ✅ |
| **Voice (TTS + STT) module** | ✅ | ✅ | ❌ |
| **Browser automation (Playwright + stdlib fallback)** | ✅ | ✅ | ❌ |
| **Backup / restore system (tar.gz + manifest)** | ✅ | ❌ | ❌ |
| **Skill marketplace (HTTP/git/local install)** | ✅ | partial (agentskills.io) | ❌ |
| **Computer use (screen/mouse/keyboard)** | ✅ | partial | ❌ |
| **Plugin system (drop-in Python files)** | ✅ | ❌ | ❌ |
| **Background memory consolidation (real async task)** | ✅ | partial | partial |
| **Aion as MCP server (not just client)** | ✅ | ❌ | ❌ |
| **Architecture Decision Records (docs/adr/)** | ✅ | ❌ | ❌ |

### Where Aion pulls ahead

1. **Pipeline + Critic + 5 verifiers** — Hermes and OpenClaw don't have a structured critic/repair loop; Aion scores every result and auto-repairs low-scoring outputs.
2. **70+ skills out of the box** — ported from Hermes's MIT-licensed skill collection + 11 Aion-original starter skills.
3. **21 SOUL.md personas** — OpenClaw's signature feature; Aion ships with 21 (default, researcher, coder, assistant, analyst, writer, tutor, devops, pm, sales, chef, finance, fitness, travel, doctor, lawyer, therapist, gaming, sre, architect, philosopher).
4. **Aion as MCP server** — other agents (Hermes, OpenClaw, Claude Desktop) can call Aion's 25+ tools. Aion is the only framework that's both an MCP client AND server.
5. **Voice module** — TTS + STT with multi-backend (pyttsx3, say, espeak, Whisper) and graceful fallback. Hermes has voice; OpenClaw doesn't.
6. **Browser automation** — Playwright + stdlib fallback. Hermes has browser; OpenClaw doesn't.
7. **Backup/restore system** — full agent state backup to tar.gz with manifest. Neither Hermes nor OpenClaw has this.
8. **Skill marketplace** — install skills from HTTP URLs, git repos, or local directories. Aion's marketplace client is more flexible than Hermes's agentskills.io-only approach.
9. **Computer use** — screen/mouse/keyboard with multi-backend. Hermes has computer-use; OpenClaw doesn't.
10. **Plugin system** — drop Python files into `~/.aion-hand/plugins/` to add tools, skills, personas, providers, cron tasks at runtime. Neither Hermes nor OpenClaw has this.
11. **Background memory consolidation** — real async task that promotes durable facts, extracts user attributes, updates MEMORY.md/USER.md, triggers skill auto-creation every 5 minutes.
12. **20+ messaging adapters** — Telegram, Discord, Slack, WhatsApp, Signal, Teams, WeChat, QQ, Feishu, WeixinWork, Yuanbao, Matrix, IRC, Mattermost, Line, GoogleChat, DingTalk, Email, Ntfy, Webhook.
13. **Knowledge graph + entity/relation reasoner** — structured world knowledge neither Hermes nor OpenClaw has.
14. **Model router with cost/latency optimiser** — auto-pick the cheapest model that meets a quality bar.
15. **Zero hard dependencies** — the core runs on the Python stdlib; rich/yaml/aiohttp are all optional.
16. **Built-in benchmark harness** — actually measure Aion vs. baselines on a fixed task suite.
17. **Architecture Decision Records (ADRs)** — `docs/adr/` documents every major design decision with tradeoffs and alternatives considered.

### Where Aion can still improve (honest gaps)

- **Native desktop app** — Hermes has a native macOS/Windows/Linux app; Aion is terminal + web only for now.
- **Skill ecosystem depth** — Hermes has 200+ community-published skills with deep domain expertise (ComfyUI workflows, MLOps integrations). Aion's 70 skills are well-curated but smaller.
- **OpenClaw-RL training** — OpenClaw has a reinforcement-learning training loop; Aion doesn't.

---

## 🚀 Quick Start

### 1️⃣ Install

```bash
# Clone the repository
git clone https://github.com/aion-hand/aion-hand.git
cd aion-hand

# Install with all optional dependencies
pip install -e ".[all]"

# Or install minimal (core only — zero hard deps)
pip install -e .
```

### 2️⃣ Configure

```bash
# Set your LLM provider API key
export OPENAI_API_KEY="sk-..."

# Or use any provider (Ollama, Anthropic, etc.)
aion-hand config set default_provider ollama
aion-hand config set default_model llama3
```

### 3️⃣ Run

```bash
# Launch the beautiful Rich TUI (recommended)
aion-tui
# Then type /help to see all commands, /persona researcher to switch persona

# Or launch the classic CLI REPL
aion-hand chat

# Or use the Python API
python -c "
import asyncio
from aion_core.agent.core import AionHand

async def main():
    agent = AionHand()
    await agent.start()
    result = await agent.chat('Hello! What can you do?')
    print(result['content'])
    await agent.shutdown()

asyncio.run(main())
"
```

> 💡 **That's it!** Aion Hand is now running with full memory, tools, skills, and security enabled.

---

## 📊 Comparison Table

| Feature | 🤖 **Aion Hand** | OpenClaw | Hermes | NullClaw | CrewAI | AutoGPT | LangGraph |
|:---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| **Memory** | 6-Layer FTS5 | File-based | FTS5 | Session | Basic | Vector DB | Checkpointer |
| **Skills** | ✅ Self-improving | ❌ | ✅ Learning loop | ❌ | ❌ | ❌ | ❌ |
| **Multi-Agent** | ✅ Subagents | ❌ | ✅ Basic | ❌ | ✅ Crews | ❌ | ✅ Graph |
| **Tools** | 25+ MCP compat | 40+ | Grouped | Minimal | Plugins | Plugins | Custom nodes |
| **Speed** | ⚡ Async native | ⚡ Fast | ⚡ Async | 🚀 Fast | 🐢 Slow | 🐢 Slow | ⚡ Async |
| **Learning Loop** | ✅ Auto-create | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Provider Support** | Any LLM | OpenAI | OpenAI | Any LLM | OpenAI | OpenAI | Any LLM |
| **Messaging** | Telegram/Discord/Slack | Telegram/Discord | ❌ | ❌ | ❌ | ❌ | ❌ |
| **Cron Scheduler** | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |
| **Security Sandbox** | ✅ 3-mode | Basic | ❌ | ❌ | ❌ | ❌ | ❌ |
| **CLI** | ✅ Full REPL | ✅ Basic | ✅ TUI | ✅ Minimal | ❌ | ✅ Basic | ❌ |
| **Web UI** | ✅ Next.js | ❌ | ❌ | ❌ | ❌ | ✅ Basic | ❌ |
| **Language** | Python | Python | Python | Python | Python | Python | Python |
| **Binary Size** | ~50KB core | ~200KB | ~150KB | ~30KB | ~500KB | ~300KB | ~80KB |
| **Self-Improving** | ✅ | ❌ | ✅ | ❌ | ❌ | ❌ | ❌ |

> 🏆 **Aion Hand** combines the strengths of all frameworks into one unified, modular system.

---

## 🧩 Core Modules

### 🔄 Agent Loop

The heart of Aion Hand — a Think → Act → Observe cycle inspired by Hermes Agent's control loop.

```python
from aion_core.agent.core import AionHand

agent = AionHand()
await agent.start()
result = await agent.chat("Analyze the latest market data and create a report")
# Result includes: content, tools_used, metadata, elapsed_seconds
await agent.shutdown()
```

**Lifecycle states:** `UNINITIALIZED → INITIALIZING → IDLE → THINKING → EXECUTING → WAITING → RESPONDING → SHUTDOWN`

### 🧠 Memory System

See [Memory System](#-memory-system-1) below for the full 6-layer breakdown.

### 🔧 Tools

See [Tools](#-tools-1) below for the full tool catalog.

### 📚 Skills System

See [Skills System](#-skills-system-1) below for self-improving details.

### 🔄 Providers

Provider-agnostic LLM integration via the factory pattern. Works with any provider.

```python
from aion_core.providers.factory import ProviderFactory

# OpenAI (default)
provider = ProviderFactory.create("openai", {"api_key": "sk-..."}, default_model="gpt-4o")

# Ollama (local)
provider = ProviderFactory.create("ollama", {"base_url": "http://localhost:11434"}, default_model="llama3")

# Anthropic
provider = ProviderFactory.create("anthropic", {"api_key": "sk-ant-..."}, default_model="claude-3-opus")
```

### 🤝 Orchestration Engine

Multi-agent coordination with dynamic subagent spawning.

```python
# Spawn a research subagent
result = await agent.spawn_subagent(
    task="Research competitor pricing strategies",
    tools=["web_search", "web_reader", "note_create"],
    personality="You are a thorough market research analyst.",
    timeout=120,
)
```

### 💬 Messaging Gateway

Multi-platform messaging integration (Telegram, Discord, Slack).

```json
{
  "platforms": {
    "telegram": {"bot_token": "...", "allowed_users": ["user_id"]},
    "discord": {"bot_token": "...", "guild_id": "..."},
    "slack": {"bot_token": "...", "channels": ["#general"]}
  }
}
```

### ⏰ Cron Scheduler

Automated task scheduling with standard cron expressions.

```python
# Schedule a daily summary
await agent.schedule_task(
    task="Generate a daily productivity summary and send to Telegram",
    schedule="0 9 * * *",  # Every day at 9 AM
    platforms=["telegram"],
)
```

### 🛡️ Security Sandbox

Multi-layer security with three approval modes.

| Mode | Behavior |
|:-----|:---------|
| `auto` | Execute all tools immediately (fastest) |
| `ask` | Prompt user for approval on sensitive/dangerous tools |
| `deny` | Block all tools that require approval (safest) |

---

## 📋 CLI Commands

| Command | Description |
|:--------|:------------|
| `aion-hand chat` | 🗣️ Launch interactive REPL chat session |
| `aion-hand model list` | 📋 List available LLM models |
| `aion-hand model set <provider>` | 🔧 Set default LLM provider |
| `aion-hand tools list` | 🔧 List all registered tools |
| `aion-hand tools enable <tool>` | ✅ Enable a specific tool |
| `aion-hand tools disable <tool>` | ❌ Disable a specific tool |
| `aion-hand skills list` | 📚 List installed skills |
| `aion-hand skills create <name>` | ✨ Create a new skill |
| `aion-hand skills show <name>` | 📖 Show skill details |
| `aion-hand memory search <query>` | 🔍 Search memory (FTS5) |
| `aion-hand memory stats` | 📊 Show memory statistics |
| `aion-hand memory export` | 💾 Export memory to file |
| `aion-hand schedule list` | ⏰ List cron tasks |
| `aion-hand schedule add` | ➕ Add a cron task |
| `aion-hand schedule remove <id>` | 🗑️ Remove a cron task |
| `aion-hand gateway start` | 🚀 Start messaging gateway |
| `aion-hand gateway setup` | 🔧 Configure messaging platforms |
| `aion-hand config get <key>` | 📖 Get a config value |
| `aion-hand config set <key> <val>` | ✏️ Set a config value |
| `aion-hand config update` | 🔄 Reload configuration |
| `aion-hand doctor` | 🩺 Run diagnostics check |
| `aion-hand update` | ⬆️ Update Aion Hand |
| `aion-hand info` | ℹ️ Show system information |
| `aion-hand spawn <task>` | 🤝 Spawn a subagent for a task |

---

## ⚙️ Configuration

Configuration is managed via `~/.aion-hand/config.json`:

```json
{
  "name": "Aion Hand",
  "version": "0.1.0",
  "default_provider": "openai",
  "default_model": "gpt-4o",
  "max_turns": 50,
  "max_tokens": 4096,
  "temperature": 0.7,
  "context_window": 128000,
  "memory_enabled": true,
  "memory_persist": true,
  "memory_nudge_interval": 300,
  "memory_max_entries": 10000,
  "skills_enabled": true,
  "skills_auto_create": true,
  "skills_auto_improve": true,
  "skills_hub_url": "https://agentskills.io",
  "tools_enabled": true,
  "mcp_enabled": true,
  "tool_approval_mode": "auto",
  "max_subagents": 5,
  "subagent_timeout": 300,
  "workflow_enabled": true,
  "cron_enabled": true,
  "cron_timezone": "UTC",
  "messaging_enabled": false,
  "platforms": {},
  "sandbox_enabled": true,
  "command_whitelist": [],
  "allowed_users": [],
  "lightweight_mode": false,
  "streaming_enabled": true
}
```

### Environment Variables

| Variable | Description | Default |
|:---------|:------------|:--------|
| `OPENAI_API_KEY` | OpenAI API key | — |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `OLLAMA_BASE_URL` | Ollama server URL | `http://localhost:11434` |
| `AION_HAND_HOME` | Custom config directory | `~/.aion-hand` |
| `AION_HAND_LOG_LEVEL` | Logging level | `INFO` |

---

## 🧠 Memory System

Aion Hand implements a **6-layer hierarchical memory architecture** combining the best of
Hermes Agent's FTS5 full-text search and OpenClaw's file-based persistence.

```
  ┌─────────────────────────────────────────────────────────────┐
  │                    MEMORY ARCHITECTURE                      │
  ├─────────────────────────────────────────────────────────────┤
  │                                                             │
  │   L1 ┌──────────────┐   ⚡ Volatile · Seconds               │
  │      │   WORKING     │   Current conversation context,       │
  │      │   MEMORY      │   active reasoning state.             │
  │      └──────┬───────┘                                      │
  │             │ auto-consolidate                              │
  │   L2 ┌──────▼───────┐   🔄 Session · Minutes-Hours          │
  │      │   SESSION     │   Facts gathered during current       │
  │      │   MEMORY      │   session (cleared on new session).   │
  │      └──────┬───────┘                                      │
  │             │ summarize on session end                      │
  │   L3 ┌──────▼───────┐   📖 Episodic · Days-Weeks            │
  │      │   EPISODIC    │   Past conversation summaries,        │
  │      │   MEMORY      │   key events and outcomes.            │
  │      └──────┬───────┘                                      │
  │             │ extract facts                                │
  │   L4 ┌──────▼───────┐   🧠 Semantic · Long-term             │
  │      │   SEMANTIC    │   General knowledge, facts, entities.  │
  │      │   MEMORY      │   Searchable via FTS5.                │
  │      └──────┬───────┘                                      │
  │             │ distill procedures                            │
  │   L5 ┌──────▼───────┐   🔧 Procedural · Permanent           │
  │      │   PROCEDURAL  │   How-to knowledge, workflows,        │
  │      │   MEMORY      │   learned procedures and recipes.     │
  │      └──────┬───────┘                                      │
  │             │ track preferences                            │
  │   L6 ┌──────▼───────┐   👤 UserProfile · Persistent         │
  │      │   USER        │   User preferences, patterns,         │
  │      │   PROFILE     │   identity, communication style.      │
  │      └──────────────┘                                      │
  │                                                             │
  │   💾 Persistence: MEMORY.md + USER.md (OpenClaw)            │
  │   🔍 Search:     SQLite FTS5 (Hermes)                       │
  │   ⏰ Nudge:       Background consolidation every 10 min      │
  └─────────────────────────────────────────────────────────────┘
```

### How Memory Works

1. **Incoming message** is placed in **L1 Working Memory**
2. **Memory Nudge** (every 300s by default) consolidates L1 → L2
3. **Session end** summarizes L2 → L3 Episodic Memory
4. **Fact extraction** promotes key facts to **L4 Semantic Memory** (FTS5 indexed)
5. **Procedure distillation** creates **L5 Procedural Memory** entries
6. **User patterns** are continuously tracked in **L6 UserProfile**

```python
# Search across all memory layers
results = await agent.search_memory("project deadline", limit=10)

# Get memory statistics
stats = await agent.get_insights(days=7)
# Returns: agent info, memory stats, skills stats, tools stats
```

---

## 📚 Skills System

The **self-improving skills engine** is inspired by Hermes Agent's learning loop and is
compatible with the [agentskills.io](https://agentskills.io) hub format.

### How It Works

```
  ┌────────────┐     ┌──────────────┐     ┌──────────────┐     ┌────────────┐
  │  Agent     │────▶│  Evaluate    │────▶│  Create /    │────▶│  Refine &  │
  │  performs  │     │  for skill   │     │  Update      │     │  Improve   │
  │  task      │     │  opportunity │     │  SKILL.md    │     │  existing  │
  └────────────┘     └──────────────┘     └──────────────┘     └────────────┘
                            │                     │                     │
                            ▼                     ▼                     ▼
                     Pattern detected     New skill file       Better prompts,
                     in tool usage         created in           fewer steps,
                     & responses           ~/.aion-hand/skills/  higher accuracy
```

### Skill File Format (SKILL.md)

```markdown
# Skill: research_report

## Description
Generate comprehensive research reports on any topic.

## Trigger
When the user asks for research, analysis, or a report on a topic.

## Steps
1. Use web_search to find relevant sources
2. Use web_reader to read top 3-5 sources
3. Synthesize findings into structured report
4. Use file_write to save the report

## Tools Required
- web_search
- web_reader
- text_summarize
- file_write

## Created
2025-01-15T10:30:00Z

## Improved
2025-01-16T14:20:00Z - Added source citation format
```

### Key Features

| Feature | Description |
|:--------|:------------|
| **Auto-Create** | Automatically detects patterns and creates new skills |
| **Auto-Improve** | Refines existing skills based on execution feedback |
| **Hub Sync** | Download/share skills from agentskills.io |
| **Tool Binding** | Skills declare required tools for routing |
| **Trigger Matching** | NLP-based trigger detection for skill activation |

---

## 🔧 Tools

### 25+ Built-in Tools (MCP Compatible)

| Category | Tool | Description |
|:---------|:-----|:------------|
| **🌐 Web** | `web_search` | Search the web for information |
| | `web_reader` | Read and extract content from web pages |
| | `http_request` | Make custom HTTP/REST API calls |
| **📁 File** | `file_read` | Read file contents |
| | `file_write` | Write content to files |
| | `file_list` | List directory contents |
| **💻 System** | `shell_command` | Execute shell commands (sandboxed) ⚠️ |
| | `system_info` | Get OS and hardware information |
| | `code_execute` | Run Python code snippets |
| | `date_time` | Get current date/time with timezone support |
| **🧮 Utility** | `calculator` | Evaluate mathematical expressions |
| | `json_parse` | Parse JSON strings into objects |
| | `json_format` | Format/beautify JSON data |
| | `text_summarize` | Condense long texts into summaries |
| **📋 Productivity** | `todo_manage` | Create, list, complete, and delete todos |
| | `note_create` | Create and organize notes |
| | `note_search` | Search through stored notes |
| | `calendar_manage` | Create and manage calendar events |
| | `email_send` | Send emails via SMTP |
| **🌤️ Data** | `weather` | Get real-time weather information |
| **🎨 Media** | `image_generate` | Generate images from text descriptions |
| | `text_to_speech` | Convert text to spoken audio |
| | `speech_to_text` | Transcribe audio to text |
| **🔧 System** | `clipboard_copy` | Copy content to system clipboard |
| | `clipboard_paste` | Paste content from system clipboard |

> ⚠️ `shell_command` and other dangerous tools are gated by the **approval mode** setting.

### Tool Architecture

```
  Tool Definition          →  Schema Generation        →  Execution
  ┌──────────────┐         ┌──────────────────┐        ┌───────────────┐
  │ Name         │────────▶│ OpenAI Function  │───────▶│ Validation    │
  │ Description  │         │ Calling Format   │        │ Type Checking │
  │ Parameters   │         │                  │        │               │
  │ Toolset      │         │ MCP Schema       │        │ Approval Gate │
  │ Approval Req │         │                  │        │               │
  │ Timeout      │         │ JSON Schema      │        │ Handler Exec  │
  │ Dangerous?   │         │                  │        │               │
  └──────────────┘         └──────────────────┘        │ Audit Log    │
                                                      └───────────────┘
```

### Adding Custom Tools

```python
from aion_core.tools.registry import Tool, ToolParameter, ToolRegistry

async def my_custom_handler(query: str, limit: int = 5) -> dict:
    # Your custom logic here
    return {"results": [...]}

tool = Tool(
    name="my_custom_tool",
    description="Does something custom",
    parameters=[
        ToolParameter("query", "string", "Search query"),
        ToolParameter("limit", "integer", "Max results", required=False, default=5),
    ],
    handler=my_custom_handler,
    toolset="custom",
    requires_approval=False,
    timeout=30,
)
```

---

## 🤝 Multi-Agent Orchestration

Aion Hand's orchestration engine enables complex multi-agent workflows, inspired by
CrewAI's crew system and Hermes Agent's subagent architecture.

### Spawning Subagents

```python
# Research agent
research = await agent.spawn_subagent(
    task="Find and analyze the top 10 competitors in the AI market",
    tools=["web_search", "web_reader", "note_create"],
    personality="You are a meticulous market researcher.",
    timeout=120,
)

# Writing agent (runs in parallel)
writer = await agent.spawn_subagent(
    task="Write a blog post about AI trends based on research notes",
    tools=["note_search", "text_summarize", "file_write"],
    personality="You are an engaging technical writer.",
    timeout=90,
)
```

### Key Capabilities

- **Isolated Context** — Each subagent has its own conversation history and tool access
- **Parallel Execution** — Spawn multiple subagents concurrently
- **Timeout Control** — Per-agent configurable timeouts prevent runaway tasks
- **Role-Based Personalities** — Assign custom personalities per subagent
- **Tool Scoping** — Restrict which tools each subagent can access
- **Result Aggregation** — Collect and merge results from all subagents

---

## 📊 Web Dashboard

A real-time monitoring dashboard built with **Next.js** and **Tailwind CSS**.

```
aion-web/
├── app/
│   ├── layout.tsx      # Root layout with metadata
│   ├── page.tsx        # Main dashboard page
│   ├── page.css        # Dashboard styles
│   └── globals.css     # Global styles + Tailwind
├── next.config.ts      # Next.js configuration
├── tsconfig.json       # TypeScript configuration
├── postcss.config.mjs  # PostCSS + Tailwind
└── package.json        # Dependencies
```

### Building the Dashboard

```bash
cd aion-web
npm install
npm run build    # Static export to out/
npm run dev     # Development server on localhost:3000
```

---

## 📁 Project Structure

```
aion-hand/
├── 📄 README.md                   # This file
├── 📄 LICENSE                      # MIT License
├── 📄 pyproject.toml               # Python project config (hatchling)
├── 📄 setup.py                    # Legacy setup entry point
├── 📄 setup.cfg                   # Setup configuration
├── 📄 Makefile                    # Dev automation targets
├── 📄 requirements.txt            # Core dependencies
├── 📄 requirements-dev.txt        # Dev/test dependencies
├── 🐍 aion_hand.py               # Quick-start script
│
├── 📦 aion_core/                 # Core framework package
│   ├── __init__.py
│   ├── 🤖 agent/                  # Agent core
│   │   ├── __init__.py
│   │   ├── core.py               # AionHand class (main orchestrator)
│   │   └── loop.py               # Agent loop (Think→Act→Observe)
│   ├── 🧠 memory/                 # 6-layer memory system
│   │   ├── __init__.py
│   │   └── manager.py            # MemoryManager (FTS5 + file persistence)
│   ├── 🔧 tools/                  # Tool registry (25+ tools)
│   │   ├── __init__.py
│   │   └── registry.py           # ToolRegistry, Tool, ToolResult
│   ├── 📚 skills/                 # Skills engine
│   │   └── (engine.py)           # SkillEngine, auto-create/improve
│   ├── 🔄 providers/              # LLM provider factory
│   │   ├── __init__.py
│   │   └── factory.py            # ProviderFactory (OpenAI, Ollama, etc.)
│   ├── 🤝 orchestration/          # Multi-agent orchestration
│   │   ├── __init__.py
│   │   └── engine.py             # OrchestrationEngine, subagent spawning
│   ├── 💬 messaging/              # Messaging gateway
│   │   ├── __init__.py
│   │   └── gateway.py            # MessagingGateway (Telegram, Discord, Slack)
│   ├── ⏰ cron/                   # Cron scheduler
│   │   ├── __init__.py
│   │   └── scheduler.py          # CronScheduler (cron expressions)
│   └── 🛡️ security/               # Security sandbox
│       ├── __init__.py
│       └── sandbox.py            # Command validation, approval modes
│
├── 🖥️ aion_hand_cli/             # CLI package
│   ├── __init__.py
│   └── cli.py                    # Full CLI with REPL, colors, spinners
│
├── 🌐 aion_web/                   # Web dashboard (Next.js)
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx
│   │   ├── page.css
│   │   └── globals.css
│   ├── out/                      # Built static export
│   ├── next.config.ts
│   ├── tsconfig.json
│   ├── postcss.config.mjs
│   └── package.json
│
└── 🧪 tests/                     # Test suite
    ├── __init__.py
    ├── test_core.py              # Agent core tests
    ├── test_memory.py            # Memory system tests
    ├── test_tools.py             # Tool registry tests
    ├── test_skills.py            # Skills engine tests
    ├── test_providers.py         # Provider factory tests
    ├── test_orchestration.py     # Orchestration tests
    ├── test_cron.py              # Cron scheduler tests
    └── test_security.py          # Security sandbox tests
```

---

## 🛠️ Development

### Prerequisites

- **Python 3.11+** (3.11, 3.12, 3.13 supported)
- **Node.js 18+** (for web dashboard only)
- **Git**

### Dev Setup

```bash
# Clone and enter the project
git clone https://github.com/aion-hand/aion-hand.git
cd aion-hand

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# .venv\Scripts\activate   # Windows

# Install with dev dependencies
pip install -e ".[dev]"

# Or install everything
pip install -e ".[all,dev]"
```

### Running Tests

```bash
# Run all tests
make test
# or
pytest

# Run with coverage
pytest --cov=aion_core --cov-report=term-missing

# Run specific test module
pytest tests/test_memory.py -v

# Run with async support (auto-configured via pytest-asyncio)
pytest -x --tb=short
```

### Code Quality

```bash
# Format code
make format
# or
black aion_core/ aion_hand_cli/ tests/

# Lint
make lint
# or
ruff check aion_core/ aion_hand_cli/ tests/

# Type checking
make typecheck
# or
mypy aion_core/
```

### Makefile Targets

```bash
make install     # Install editable with all extras
make test        # Run pytest
make lint        # Run ruff linter
make format      # Run black formatter
make typecheck   # Run mypy
make clean       # Remove build artifacts
```

### Contributing

1. 🍴 Fork the repository
2. 🌿 Create a feature branch: `git checkout -b feature/my-feature`
3. ✏️ Make your changes with tests
4. ✅ Ensure all tests pass: `pytest`
5. 🎨 Format code: `black . && ruff check --fix .`
6. 📤 Push and open a Pull Request

> 💡 All contributions are welcome! Please open an issue first to discuss major changes.

---

## 🗺️ Roadmap

### v0.1.0 (Current — Alpha)
- [x] 🤖 Core agent loop with Think→Act→Observe cycle
- [x] 🧠 6-layer memory system with FTS5 search
- [x] 🔧 25+ built-in MCP-compatible tools
- [x] 📚 Self-improving skills engine
- [x] 🔄 Provider-agnostic LLM factory
- [x] 🤝 Multi-agent orchestration with subagent spawning
- [x] 💬 Messaging gateway (Telegram, Discord, Slack)
- [x] ⏰ Cron scheduler
- [x] 🛡️ Security sandbox with 3 approval modes
- [x] 🖥️ Full CLI with REPL
- [x] 📊 Web dashboard (Next.js + Tailwind)
- [x] 🧪 Comprehensive test suite

### v0.2.0 (Planned)
- [ ] 🔌 Native MCP server/client implementation
- [ ] 📊 Real-time streaming dashboard with WebSocket
- [ ] 🧠 Vector embedding memory layer (RAG)
- [ ] 📚 Skill marketplace / hub integration
- [ ] 🐳 Docker containerization
- [ ] 📖 Interactive documentation site

### v0.3.0 (Planned)
- [ ] 🌐 Plugin system for community extensions
- [ ] 🔄 Workflow DSL for complex agent pipelines
- [ ] 📱 Mobile companion app
- [ ] ☁️ Cloud deployment templates (AWS, GCP, Azure)
- [ ] 🔗 LangChain / LlamaIndex bridge

### v1.0.0 (Future)
- [ ] 🎯 Production-ready stability
- [ ] 🏢 Enterprise features (SSO, audit logs, RBAC)
- [ ] 📈 Performance benchmarks & optimization
- [ ] 🌍 Multi-language SDK (TypeScript, Go, Rust)
- [ ] 📚 Published skill library with 100+ skills

---

## 🤝 Acknowledgments

Aion Hand stands on the shoulders of these amazing projects:

| Project | Contribution |
|:--------|:-------------|
| **OpenClaw** | Personal assistant architecture, 40+ tools, MEMORY.md, messaging gateway |
| **Hermes Agent** | FTS5 memory, self-improving skills, learning loop, cron system, TUI |
| **NullClaw** | Provider-agnostic design, lightweight execution model |
| **NullBoiler** | Multi-agent orchestration patterns |
| **CrewAI** | Crew-based multi-agent coordination |
| **AutoGPT** | Autonomous agent pioneering concepts |
| **LangGraph** | Graph-based agent workflow patterns |
| **MCP** | Model Context Protocol for standard tool interfaces |

---

## 📄 License

This project is licensed under the **MIT License**.

```
MIT License

Copyright (c) 2025 Aion Hand Contributors

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

---

<div align="center">

**Built with 🤖 by the Aion Hand Contributors**

*Combining the best of OpenClaw · Hermes · NullClaw · CrewAI · AutoGPT · LangGraph*

</div>
