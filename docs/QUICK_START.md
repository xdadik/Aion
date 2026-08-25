# Quick Start Guide

Get Aion Hand running in 5 minutes. This guide covers the three
installation methods and walks you through your first chat, tool call,
skill creation, and benchmark run.

---

## Prerequisites

| Requirement   | Minimum version | Notes                              |
|---------------|----------------|-------------------------------------|
| Python        | 3.11+          | 3.12 and 3.13 also supported        |
| pip           | latest         | `python -m pip install --upgrade pip` |
| LLM provider  | Any            | OpenAI, Anthropic, Ollama, OpenRouter |
| Git           | 2.30+          | Only for source installs             |

You will need an API key from at least one LLM provider. For local,
offline use, [Ollama](https://ollama.ai/) with any model works — no
API key needed.

---

## Install (choose one)

### Option 1: pip (recommended)

```bash
pip install aion-hand
```

With optional extras:

```bash
# Full install (web UI + messaging + dev tools)
pip install "aion-hand[all,dev]"

# Just the web interface
pip install "aion-hand[web]"

# Just messaging platforms
pip install "aion-hand[messaging]"
```

### Option 2: curl | bash (one-liner)

```bash
curl -fsSL https://raw.githubusercontent.com/xdadik/Aion/main/install.sh | bash
```

This script:
1. Detects your Python version.
2. Creates a virtual environment in `~/.aion-hand/venv`.
3. Installs `aion-hand[all]`.
4. Adds `aion-hand` to your PATH.
5. Runs the setup wizard.

On Windows:

```powershell
irm https://raw.githubusercontent.com/xdadik/Aion/main/install.ps1 | iex
```

### Option 3: Docker

```bash
# Pull from Docker Hub (when available)
docker pull aionhand/aion-hand:latest
docker run -it --rm \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v aion-data:/home/aion/.aion-hand \
  aionhand/aion-hand

# Or build from source
git clone https://github.com/xdadik/Aion.git
cd aion-hand
docker build -t aion-hand .
docker run -it --rm \
  -e OPENAI_API_KEY=$OPENAI_API_KEY \
  -v aion-data:/home/aion/.aion-hand \
  aion-hand
```

---

## Configure

### Set your provider API key

```bash
# OpenAI (default)
export OPENAI_API_KEY="sk-..."

# Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# OpenRouter
export OPENROUTER_API_KEY="sk-or-..."

# Ollama (local, no key needed)
export AION_HAND_DEFAULT_PROVIDER="ollama"
export AION_HAND_DEFAULT_MODEL="llama3"
```

### Create `.env` (recommended for persistent config)

Create `~/.aion-hand/.env` with your keys:

```env
# Provider
AION_HAND_DEFAULT_PROVIDER=openai
AION_HAND_DEFAULT_MODEL=gpt-4o
OPENAI_API_KEY=sk-your-key-here

# Security
AION_HAND_TOOL_APPROVAL_MODE=auto
AION_HAND_SANDBOX_ENABLED=true

# Memory
AION_HAND_MEMORY_ENABLED=true
AION_HAND_MEMORY_PERSIST=true
```

Or use the setup wizard:

```bash
aion-hand setup
```

---

## First Chat

### Interactive mode (CLI)

```bash
aion-hand chat
```

```
╭─────────────────────────────────────────╮
│  Aion Hand v0.1.0 — The AI Agent Framework │
│  Provider: openai · Model: gpt-4o        │
╰─────────────────────────────────────────╯

You: Hello! What can you do?

Aion: Hello! I'm Aion Hand, an autonomous AI assistant. I can:
  • Search the web and fetch content
  • Read, write, and manage files
  • Execute code and shell commands
  • Manage tasks and to-do lists
  • Set up scheduled tasks
  • Learn new skills from our interactions
  • Coordinate subagents for complex workflows
  ... and much more. What would you like help with?
```

### Python SDK

```python
import asyncio
from aion_core import AionHand

async def main():
    agent = AionHand()
    await agent.start()

    response = await agent.chat("What is 42 * 73?")
    print(response["content"])
    # → "42 × 73 = 3,066"

    await agent.shutdown()

asyncio.run(main())
```

---

## First Tool Use

Tools are available automatically. Just ask:

```
You: Search the web for "Aion Hand AI agent"

Aion: [searching the web...]
```

The agent will invoke `web_search`, display results, and optionally
follow up with `web_fetch` to read the most relevant links.

To see available tools:

```bash
aion-hand tools list
```

```
Built-in tools (24):
  web:       web_search, web_fetch, web_scrape
  code:      execute_code, run_shell, lint_code
  file:      read_file, write_file, list_dir, glob
  utility:   calculator, datetime, uuid, echo
  data:      json_parse, json_format, csv_read
  productivity: todo_add, todo_list, todo_done
  media:     generate_image, speak_text
  weather:   get_weather, forecast
  system:    system_info, process_list, disk_usage
```

---

## First Skill

Skills are auto-created from repeated patterns. But you can also
create one manually:

```python
from aion_core import AionHand

agent = AionHand()
await agent.start()

await agent.create_skill(
    name="code_review",
    content="""
---
name: code_review
description: Review code for bugs, style, and security
trigger: review code, check code, code review
---

# Code Review Skill

## Instructions
1. Parse the code using AST
2. Check for common bugs (off-by-one, null checks)
3. Check style (naming, docstrings, type hints)
4. Run security patterns (eval, exec, hardcoded secrets)
5. Provide a score (0-10) and specific improvements

## Output format
Score: X/10
Issues: ...
Suggestions: ...
"""
)
```

Skills are stored as `SKILL.md` files in `~/.aion-hand/skills/` and
are automatically matched to relevant queries during chat.

---

## First Benchmark

Aion Hand includes a built-in benchmark suite to measure performance
across reasoning, coding, search, and multi-step tasks:

```bash
# Run the full benchmark suite
aion-hand benchmark run

# Run a specific category
aion-hand benchmark run --category reasoning

# Run with a specific difficulty
aion-hand benchmark run --difficulty hard

# Generate a markdown report
aion-hand benchmark report --output benchmark_results.md
```

Or via the Python SDK:

```python
from aion_core.benchmark import BenchmarkRunner

runner = BenchmarkRunner(agent=agent, output_dir="./results")
report = await runner.run_full_benchmark()
print(f"Overall score: {report.overall_score:.1%}")
print(f"Tasks completed: {report.completed}/{report.total}")
```

---

## First Scheduled Task

Set up a cron task to run periodically:

```bash
aion-hand cron add \
  --schedule "0 9 * * *" \
  --task "Give me a weather briefing for today" \
  --platform telegram
```

Or via Python:

```python
task_id = await agent.schedule_task(
    task="Summarise yesterday's todo list",
    schedule="0 8 * * 1-5",  # weekdays at 8am
)
print(f"Scheduled task ID: {task_id}")
```

---

## Next Steps

| What                  | Where to go                                               |
|------------------------|-----------------------------------------------------------|
| Full API reference     | [`docs/API.md`](API.md)                                  |
| Architecture deep-dive | [`ARCHITECTURE.md`](../ARCHITECTURE.md)                 |
| Security model         | [`SECURITY.md`](../SECURITY.md)                          |
| Contributing          | [`CONTRIBUTING.md`](../CONTRIBUTING.md)                 |
| Configuration options | `aion-hand config --help`                               |
| MCP server setup       | [`aion_core/mcp/`](../aion_core/mcp/config.py)           |
| All CLI commands       | `aion-hand --help`                                       |
| Discord community      | [discord.gg/aion-hand](https://discord.gg/aion-hand)    |
| GitHub                 | [github.com/xdadik/Aion](https://github.com/xdadik/Aion) |

---

## Troubleshooting

| Problem                              | Solution                                          |
|--------------------------------------|---------------------------------------------------|
| `ModuleNotFoundError: aion_core`     | Run `pip install -e .` from the project root      |
| `openai.AuthenticationError`       | Set `OPENAI_API_KEY` in your environment          |
| "Sandbox restriction: importing os" | Expected — the sandbox blocks `os`. Use the tool system instead |
| `aion-hand: command not found`       | Ensure `~/.local/bin` is in your `$PATH`          |
| Timeout errors                      | Increase `max_tokens` or `sandbox_timeout` in config |

For anything else, open an issue or join the Discord.
