<p align="center">
  <img src="assets/banner.png" alt="Aion Hand Banner" width="100%">
</p>

<div align="center">

# 🤖 AION HAND

**Open-source autonomous AI agent framework**

Build, automate, orchestrate, and run AI agents with tools, memory, providers, security controls, and workflows.

[![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)

</div>

---

## ⚡ One-command installation

### Linux / macOS

From a terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/xdadik/Aion/main/bootstrap.sh | bash
```

The bootstrapper checks Python, clones/updates Aion, creates an isolated virtual environment, installs the project and dependencies, performs an import smoke test, and installs the `aion-hand` command under `~/.aion-hand/bin`.

### Windows PowerShell

```powershell
irm https://raw.githubusercontent.com/xdadik/Aion/main/bootstrap.ps1 | iex
```

The Windows bootstrapper performs the same setup using a user-local virtual environment.

### From an existing checkout

```bash
./bootstrap.sh
```

No system-wide Python packages are required. Your API keys stay outside the repository.

---

## 🔑 Configure a model

Aion supports provider-specific environment variables. Put real credentials in your local environment or a secrets manager — **never commit them**.

```bash
export OPENAI_API_KEY="..."
export ANTHROPIC_API_KEY="..."
export GOOGLE_API_KEY="..."
export OPENROUTER_API_KEY="..."
```

For a local Ollama installation, no hosted API key is required.

Then verify the CLI:

```bash
aion-hand --help
```

---

## 🧠 Core capabilities

- Autonomous task execution with retry, timeout, cancellation, and verification
- Multi-provider model routing and failover
- Tool registry and secure execution controls
- Memory and context management
- Subagent orchestration
- MCP-compatible integration architecture
- Scheduler and background automation
- CLI and web interface components
- Security sandbox and execution auditing
- Async runtime and configurable concurrency
- Tests, coverage, static checks, and CI

> Feature claims are being validated continuously as the project moves toward production readiness. Do not treat every advertised integration as production-ready until its integration tests pass.

## 🏗️ Architecture

```text
Goal
  │
  ▼
Agent / Planner
  │
  ├── Provider Router ──► OpenAI / Anthropic / Google / OpenRouter / Ollama / compatible APIs
  │
  ├── Memory ───────────► context + persistence + retrieval
  │
  ├── Tools ────────────► policy → approval → sandbox → execution
  │
  ├── Subagents ────────► bounded parallel work + verification
  │
  └── Scheduler/MCP ────► automation + integrations
  │
  ▼
Observe → Verify → Recover / Retry → Result
```

## 🛡️ Security

Never paste API keys into source files, issues, PRs, or chat. Use environment variables or your deployment secret store. Autonomous shell/code execution should be treated as privileged functionality and run with explicit isolation and approval policies.

## 🧪 Development

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[all,dev]'
pytest -q
```

On Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
python -m pip install -e ".[all,dev]"
pytest -q
```

## 📦 Project status

Aion Hand is under active development. Production readiness is measured by passing tests, verified integrations, security review, and reliable end-to-end execution — not by feature count alone.
