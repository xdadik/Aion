# Frequently Asked Questions

## General

### What is Aion Hand?

Aion Hand is an open-source, self-improving autonomous AI agent framework.
It combines the best ideas from OpenClaw (personas, MEMORY.md), Hermes
Agent (skills, self-improvement), NullClaw (provider-agnostic), CrewAI
(multi-agent), AutoGPT (autonomous loops), and LangGraph (graph-based
orchestration) into a single, coherent framework.

### Is Aion Hand free?

Yes — Aion Hand is MIT licensed. You can use it commercially, modify it,
and distribute it freely. See [LICENSE](./LICENSE).

### Does Aion Hand call out to any external servers?

**No.** Aion Hand is local-first. The core framework runs entirely on
your machine. The only external calls are:
- LLM API calls (to OpenAI/Anthropic/etc.) — only if you configure them
- Web searches — only when you call the `web_search` tool
- Messaging platforms — only if you connect a bot

There is NO phone-home, NO telemetry collection, NO analytics. The
telemetry module exists for *your* use (shipping metrics to *your*
observability backend) — it's local-only by default.

### How does Aion compare to Hermes Agent / OpenClaw?

See the comparison table in [README.md](./README.md). Short answer:
Aion matches both on core capabilities, beats them on architectural
depth (pipeline + critic + verifiers + multi-agent DAG + knowledge
graph + model router), and matches Hermes on native desktop.

---

## Installation

### What Python versions are supported?

Python 3.11, 3.12, and 3.13. Python 3.10 may work but is not tested in CI.

### What operating systems are supported?

macOS, Linux, and Windows. CI runs on all three.

### Do I need to install Rust for the desktop app?

Only if you want to build the desktop app from source. Pre-built
binaries (planned for v0.5.0) won't require Rust.

### Can I use Aion without an OpenAI API key?

Yes! Aion is provider-agnostic. You can use:
- **Ollama** (local, free, no API key) — `aion-hand config set default_provider ollama`
- **Anthropic Claude** — set `ANTHROPIC_API_KEY`
- **Groq** — set `GROQ_API_KEY`
- **Any OpenAI-compatible API** — set `OPENAI_API_KEY` and `OPENAI_BASE_URL`

### How do I install optional features?

```bash
pip install -e ".[tui]"        # Rich TUI
pip install -e ".[messaging]"  # aiohttp for messaging
pip install -e ".[all]"        # everything
pip install -e ".[dev]"        # dev tools (pytest, ruff, etc.)
```

---

## Usage

### How do I switch personas?

In the TUI: `/persona researcher`
Via API: `POST /api/personas/apply` with body `{"name": "researcher"}`
Via Python: `PersonaManager().apply_to_agent(agent, "researcher")`

### How do I add my own skill?

Drop a `.md` file (with YAML frontmatter) into `~/.aion-hand/skills/`.
See [COOKBOOK.md](./docs/examples/COOKBOOK.md#8-write-a-custom-skill)
for the format.

### How do I add my own persona?

Drop a `.md` file into `~/.aion-hand/personas/`. User personas shadow
built-in ones (same name → user wins).

### Can I use Aion as an MCP server for Claude Desktop / Hermes / OpenClaw?

Yes! See [COOKBOOK.md](./docs/examples/COOKBOOK.md#11-use-aion-as-an-mcp-server).
Aion is the only framework that's both an MCP client AND server.

### How do I run the web UI?

```bash
cd aion_web
npm install
npm run dev   # http://localhost:3000
```

For production: `npm run build && npm start`

### How do I run the HTTP API server?

```bash
aion-hand serve --port 8000
# or
python -m aion_core.api.server --port 8000
```

### How do I back up my agent state?

```bash
aion-hand backup --create --label "pre-deploy"
aion-hand backup --list
aion-hand backup --restore /path/to/backup.tar.gz
aion-hand backup --cleanup 10   # keep newest 10
```

---

## Privacy & security

### Does Aion Hand store my conversations?

Yes, locally. Conversations are stored in `~/.aion-hand/memories/` and
`~/.aion-hand/conversation.md`. Nothing leaves your machine unless you
explicitly configure an external service.

### How does the security sandbox work?

See [SECURITY.md](./SECURITY.md). Short version:
- All tool calls go through a validator (regex blacklist + optional whitelist)
- Tools marked `requires_approval=True` prompt the user before running
- Three approval modes: `auto`, `ask`, `deny`
- Per-tool timeouts prevent runaway execution
- All tool calls are logged to a ring-buffer audit log

### Can Aion Hand execute arbitrary code?

Yes — that's the point of an autonomous agent. BUT:
- The `execute_code` tool runs in a sandbox with restricted builtins
- The `run_shell` tool requires approval by default
- You can set `tool_approval_mode=deny` to block all dangerous tools

### What if I find a security vulnerability?

See [SECURITY.md](./SECURITY.md) for the reporting process. Please
DON'T open a public issue — report privately to the maintainers.

---

## Development

### How do I run the tests?

```bash
pytest --tb=short -q
```

For coverage:
```bash
pytest --cov=aion_core --cov-report=html
open htmlcov/index.html
```

### How do I run only one test file?

```bash
pytest tests/test_rl.py -v
```

### How do I run the real Telegram integration tests?

```bash
export TG_BOT_TOKEN="your-bot-token"
export TG_CHAT_ID="your-chat-id"
pytest tests/test_telegram_integration.py -v
```

Without these env vars, the tests are skipped.

### The tests fail with "no running event loop" — what's wrong?

You're probably calling an async function from a sync context. Use
`asyncio.run(my_async_func())` or, in Jupyter, `await my_async_func()`.

---

## Comparison with competitors

### Why should I use Aion instead of just using OpenAI's API directly?

If you just want to chat with an LLM, use the OpenAI API directly.
Aion is for building **autonomous agents** that:
- Use tools (web search, file I/O, code execution, etc.)
- Remember past interactions
- Plan multi-step tasks
- Verify their own work
- Improve over time
- Run on multiple messaging platforms

### Why should I use Aion instead of LangChain?

LangChain is a library of primitives; Aion is a complete framework.
Aion gives you: memory, skills, personas, tools, pipeline, orchestration,
messaging, security, backup, telemetry, health, RL training, desktop app.
With LangChain you'd build all that yourself.

### Why should I use Aion instead of Hermes Agent?

Hermes is great and we borrowed many ideas from it. Aion wins on:
- Architectural depth (pipeline + critic + 5 verifiers)
- HTTP API + web UI + desktop app (Hermes has desktop but no web API)
- MCP server (Aion exposes its tools to other agents)
- Plugin system
- Telemetry + health probes
- 20+ messaging adapters (Hermes has fewer)
- Knowledge graph + model router
- Zero hard dependencies

Hermes wins on:
- Community size (Nous Research backing)
- Skill ecosystem depth (200+ community skills)
- Native desktop polish (more mature)

### Why should I use Aion instead of OpenClaw?

OpenClaw is great for personal-assistant use cases. Aion wins on:
- Multi-agent orchestration (DAGs, subagents, MoA)
- Pipeline + critic + repair loop
- Voice, browser, computer use, backup, plugins, telemetry
- Knowledge graph + model router
- MCP server
- Benchmark harness
- RL training loop (matches OpenClaw-RL)

OpenClaw wins on:
- Persona ecosystem (205 community templates vs. Aion's 26 built-in)
- RL training polish (OpenClaw-RL is more mature)

---

## Troubleshooting

### `aion-tui` says "command not found"

Install the TUI extras: `pip install -e ".[tui]"`

### The web UI shows "Failed to fetch"

The HTTP API server isn't running. Start it: `aion-hand serve`

### Tests fail with "ModuleNotFoundError: No module named 'aion_core'"

Install Aion in editable mode: `pip install -e .`

### The Telegram bot doesn't respond

1. Verify the bot token: `curl https://api.telegram.org/bot<TOKEN>/getMe`
2. Make sure you've messaged the bot at least once (bots can't initiate)
3. Check the chat_id is correct (use `getUpdates` to find it)

### Memory usage keeps growing

The memory manager has a `MAX_STORED_LESSONS` cap (default 1000). You
can lower it in config. Also run `aion-hand backup --cleanup 10` to
limit backup growth.

---

## Still have questions?

- 🐛 [Open an issue](https://github.com/xdadik/Aion/issues) for bugs
- 💬 [Start a discussion](https://github.com/xdadik/Aion/discussions) for questions
- 📧 Email: coming soon
