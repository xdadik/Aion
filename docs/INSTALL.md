# Aion Hand — Installation Guide

Aion Hand runs on **Python 3.11+** on macOS, Linux, and Windows.

## Quick install

```bash
git clone https://github.com/xdadik/Aion.git
cd Aion
pip install -e ".[all]"
```

This installs:
- Core framework (no hard dependencies — Python stdlib only)
- `rich` (for the beautiful TUI)
- `prompt_toolkit` (for TUI input history)
- `pyyaml` (for SKILL.md / SOUL.md parsing)
- `aiohttp` (for messaging platform integrations)

## Choose your install profile

### Minimal (zero hard deps)

```bash
pip install -e .
```

Just the Python stdlib. No TUI, no YAML, no messaging. Useful for
embedding Aion in another app or running headless.

### TUI only

```bash
pip install -e ".[tui]"
```

Adds `rich`, `prompt_toolkit`, `pyyaml`. Gets you the beautiful
interactive terminal UI but no messaging integrations.

### With messaging

```bash
pip install -e ".[messaging]"
```

Adds `aiohttp` for Telegram / Discord / Slack adapter support.

### Everything (recommended)

```bash
pip install -e ".[all]"
```

All optional dependencies. Use this if you're not sure.

## Optional extras (install separately as needed)

### Voice (TTS + STT)

```bash
pip install pyttsx3 openai-whisper
```

Then on Linux, also install system TTS:
```bash
sudo apt install espeak-ng       # Debian/Ubuntu
# or
sudo dnf install espeak-ng       # Fedora
```

### Browser automation (full JS rendering)

```bash
pip install playwright
playwright install chromium
```

Without Playwright, Aion falls back to stdlib urllib (no JS execution).

### Computer use (screen/mouse/keyboard)

```bash
pip install pillow pynput
```

On Linux, also:
```bash
sudo apt install xdotool scrot
```

### Development

```bash
pip install -e ".[dev]"
```

Adds `pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`, `black`, `mypy`.

## Verify installation

```bash
# Run the test suite
pytest

# Launch the TUI
aion-tui
# Then type /help to see all commands

# Launch the classic CLI
aion-hand chat
```

## Set your LLM provider

```bash
# OpenAI
export OPENAI_API_KEY="sk-..."

# Or Anthropic
export ANTHROPIC_API_KEY="sk-ant-..."

# Or local Ollama (no API key needed)
# Install Ollama: https://ollama.ai
ollama serve &
aion-hand config set default_provider ollama
aion-hand config set default_model llama3
```

## Configure skills and personas

Skills live in `~/.aion-hand/skills/` and personas in
`~/.aion-hand/personas/`. Both directories are created automatically
on first run.

Aion ships with 70+ built-in skills (in `skills/library/`) and 21
built-in personas (in `aion_core/persona/templates/`). To make them
available to the agent, copy them to your user directory:

```bash
mkdir -p ~/.aion-hand/skills
cp skills/library/*.md ~/.aion-hand/skills/

mkdir -p ~/.aion-hand/personas
cp aion_core/persona/templates/*.md ~/.aion-hand/personas/
```

Or install skills from the marketplace:

```python
from aion_core.skills.marketplace import SkillMarketplace

mp = SkillMarketplace()
await mp.install_from_url("https://example.com/skills/my-skill.md")
```

## Configure MCP servers

Edit `~/.aion-hand/mcp_servers.json`:

```json
{
  "servers": [
    {
      "name": "filesystem",
      "transport": "stdio",
      "command": "npx",
      "args": ["-y", "@anthropic/mcp-filesystem", "/home/user/docs"],
      "auto_connect": false
    }
  ]
}
```

Set `auto_connect: true` for servers you want Aion to connect to on startup.

## Run Aion as an MCP server (for other agents to use Aion's tools)

Add to your other agent's MCP config:

```json
{
  "name": "aion-hand",
  "transport": "stdio",
  "command": "python",
  "args": ["-m", "aion_core.mcp.server"]
}
```

Now Hermes, OpenClaw, Claude Desktop, etc. can call any of Aion's
25+ built-in tools.

## Backup your agent state

```python
from aion_core.backup import BackupManager

bm = BackupManager()
archive = await bm.backup(label="pre-major-change")
# → ~/.aion-hand/backups/aion-2026-08-08_143000-pre-major-change.tar.gz

# Restore later
await bm.restore(archive, overwrite=True)

# Clean up old backups, keep newest 10
bm.cleanup_old(keep=10)
```

## Troubleshooting

### `ModuleNotFoundError: No module named 'rich'`
Install the TUI extras: `pip install -e ".[tui]"`

### `asyncio.run() cannot be called from a running event loop`
You're calling an async function from within Jupyter or another async
context. Use `await agent.chat(...)` instead of `asyncio.run(agent.chat(...))`.

### Tests fail with `RuntimeError: no running event loop`
Make sure `pytest-asyncio` is installed and `asyncio_mode = "auto"` is set
in `pyproject.toml` (it is, by default).

### `pyttsx3` not found on Linux
Install: `pip install pyttsx3` and `sudo apt install espeak-ng`.

### Next.js web UI fails to build
Make sure you're using Node.js 18+: `node --version`. The web UI is in
`aion_web/` — `cd aion_web && npm install && npm run build`.

## Getting help

- Open an issue: https://github.com/xdadik/Aion/issues
- Read the architecture: [ARCHITECTURE.md](../ARCHITECTURE.md)
- Read the changelog: [CHANGELOG.md](../CHANGELOG.md)
