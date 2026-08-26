# Aion Hand — Cookbook

Practical recipes for common Aion Hand tasks.

## Table of contents

1. [Quick start — chat with Aion](#1-quick-start--chat-with-aion)
2. [Switch personas](#2-switch-personas)
3. [Run the TUI](#3-run-the-tui)
4. [Run the web UI](#4-run-the-web-ui)
5. [Run the HTTP API server](#5-run-the-http-api-server)
6. [Connect to Telegram](#6-connect-to-telegram)
7. [Backup and restore](#7-backup-and-restore)
8. [Write a custom skill](#8-write-a-custom-skill)
9. [Write a custom persona](#9-write-a-custom-persona)
10. [Write a plugin](#10-write-a-plugin)
11. [Use Aion as an MCP server](#11-use-aion-as-an-mcp-server)
12. [Run with Docker](#12-run-with-docker)
13. [Add a custom tool](#13-add-a-custom-tool)
14. [Schedule a recurring task](#14-schedule-a-recurring-task)
15. [Voice — text-to-speech + speech-to-text](#15-voice--text-to-speech--speech-to-text)
16. [Browser automation](#16-browser-automation)
17. [Run the benchmark suite](#17-run-the-benchmark-suite)
18. [Health check + observability](#18-health-check--observability)

---

## 1. Quick start — chat with Aion

```python
import asyncio
from aion_core.agent.core import AionHand

async def main():
    agent = AionHand()
    await agent.start()
    result = await agent.chat("Hello! What can you do?")
    print(result["content"])
    await agent.shutdown()

asyncio.run(main())
```

Or from the CLI:

```bash
aion-tui          # Beautiful Rich TUI (recommended)
aion-hand chat    # Classic CLI REPL
```

---

## 2. Switch personas

```python
from aion_core.persona import PersonaManager

mgr = PersonaManager()
print(mgr.list_personas())  # ['analyst', 'architect', 'assistant', 'coder', ...]
mgr.set_active("researcher")

# Apply to an agent
agent = ...
mgr.apply_to_agent(agent, "researcher")
```

In the TUI:

```
/persona researcher
```

---

## 3. Run the TUI

```bash
pip install -e ".[tui]"
aion-tui
```

Commands inside the TUI:
- `/help` — show all commands
- `/memory` — recent memories
- `/skills` — loaded skills
- `/tools` — available tools
- `/persona <name>` — switch persona
- `/benchmark` — run benchmark suite
- `/save` — save conversation
- `/quit` — exit

---

## 4. Run the web UI

```bash
cd aion_web
npm install
npm run dev
# Open http://localhost:3000
```

The web UI has two pages:
- `/` — dashboard (overview)
- `/chat` — interactive chat with config panel

To connect the web UI to a real agent, start the HTTP API server first
(see recipe 5), then set `NEXT_PUBLIC_API_URL=http://localhost:8000`.

---

## 5. Run the HTTP API server

```bash
python -m aion_core.api.server --host 0.0.0.0 --port 8000
```

Endpoints:
- `GET /health/live` — liveness probe
- `GET /health/ready` — readiness probe
- `GET /api/personas` — list personas
- `POST /api/personas/apply` — switch persona
- `POST /api/chat` — send a message
- `POST /api/chat/stream` — streaming chat (SSE)
- `GET /api/metrics` — telemetry dump

Example:

```bash
curl -X POST http://localhost:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "Hello!"}'
```

---

## 6. Connect to Telegram

```python
import asyncio
from aion_core.messaging.real_adapters import RealTelegramAdapter

async def main():
    adapter = RealTelegramAdapter(
        token="YOUR_BOT_TOKEN",
        chat_id="YOUR_CHAT_ID",
    )
    await adapter.connect()

    # Send a message
    await adapter.send_text("YOUR_CHAT_ID", "Hello from Aion!")

    # Receive messages
    async for msg in adapter.receive():
        print(f"From {msg.sender_name}: {msg.content}")
        await adapter.send_text(msg.session_id, f"You said: {msg.content}")

    await adapter.disconnect()

asyncio.run(main())
```

---

## 7. Backup and restore

```python
import asyncio
from aion_core.backup import BackupManager

async def main():
    bm = BackupManager()

    # Create a backup
    archive = await bm.backup(label="pre-deploy")
    print(f"Backup: {archive}")

    # List backups
    for entry in bm.list_backups():
        print(f"  {entry.path.name} — {entry.size_kb:.1f} KB — {entry.age_days:.1f} days old")

    # Restore from a backup
    result = await bm.restore(archive, overwrite=True)
    print(f"Restored: {len(result['extracted'])} items")

    # Clean up old backups
    deleted = bm.cleanup_old(keep=10)
    print(f"Deleted {deleted} old backups")

asyncio.run(main())
```

---

## 8. Write a custom skill

Save as `~/.aion-hand/skills/my-skill.md`:

```markdown
---
name: my-skill
description: A custom skill for my workflow
version: 1.0.0
tags: [custom, workflow]
---

# My Skill

## When to use
Use this skill when the user asks about X, Y, or Z.

## Instructions
1. First, do A
2. Then, do B
3. Finally, verify with C

## Examples
**User:** "Help me with X"
**You:** Follow steps 1-3 above.
```

Aion will auto-discover this on next start. Verify with `/skills` in the TUI.

---

## 9. Write a custom persona

Save as `~/.aion-hand/personas/my-persona.md`:

```markdown
---
name: my-persona
display_name: My Custom Persona
description: How this persona behaves
tags: [custom]
default_temperature: 0.5
---

# SOUL: My Custom Persona

## Identity
You are ...

## Voice & Tone
- ...

## Operating Principles
1. ...
2. ...

## Avoid
- ...
```

Switch to it in the TUI with `/persona my-persona`.

---

## 10. Write a plugin

Save as `~/.aion-hand/plugins/my_plugin.py`:

```python
from aion_core.plugins import PluginRegistry

def register(reg: PluginRegistry) -> None:
    """Register this plugin's contributions."""

    # Add a custom tool
    async def my_tool_handler(query: str) -> str:
        return f"Result for: {query}"

    from aion_core.tools.registry import Tool, ToolParameter
    reg.add_tool(Tool(
        name="my_tool",
        description="My custom tool",
        parameters=[ToolParameter(name="query", type="string", required=True)],
        handler=my_tool_handler,
        toolset="custom",
    ))

    # Add a system prompt extension
    reg.add_system_prompt_extension("Always be helpful and concise.")

    # Schedule a daily task
    reg.add_cron_task("0 9 * * *", lambda: print("Morning report!"))
```

Aion auto-loads plugins on startup.

---

## 11. Use Aion as an MCP server

Aion can BE an MCP server — other agents (Hermes, OpenClaw, Claude Desktop)
can call Aion's 25+ built-in tools.

Add to your other agent's MCP config:

```json
{
  "servers": {
    "aion-hand": {
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "aion_core.mcp.server"]
    }
  }
}
```

Now `aion-hand` will appear as an MCP server with all of Aion's tools available.

---

## 12. Run with Docker

```bash
# Build and run everything
docker-compose up

# Or just the agent
docker-compose up aion

# Or just the web UI
docker-compose up web
```

The web UI is at http://localhost:3000, the API at http://localhost:8000.

---

## 13. Add a custom tool

```python
from aion_core.tools.registry import Tool, ToolParameter

async def weather_handler(city: str) -> str:
    # ... call a weather API ...
    return f"Weather in {city}: sunny, 22°C"

weather_tool = Tool(
    name="get_weather",
    description="Get current weather for a city",
    parameters=[ToolParameter(name="city", type="string", required=True, description="City name")],
    handler=weather_handler,
    toolset="weather",
    requires_approval=False,
)

# Register with an agent
agent.tool_registry.register(weather_tool)
```

---

## 14. Schedule a recurring task

```python
from aion_core.cron.scheduler import CronScheduler, ScheduledTask

scheduler = CronScheduler()

# Run every day at 9 AM
scheduler.add_task(
    name="morning-report",
    schedule="0 9 * * *",
    callback=lambda: agent.chat("Give me my morning briefing"),
)

# Run every 5 minutes
scheduler.add_task(
    name="health-check",
    schedule="*/5 * * * *",
    callback=lambda: check_system_health(),
)

scheduler.start()
```

---

## 15. Voice — text-to-speech + speech-to-text

```python
import asyncio
from aion_core.voice import Voice

async def main():
    v = Voice()
    print(f"TTS backend: {v.tts_backend}")
    print(f"STT backend: {v.stt_backend}")

    # Speak aloud
    await v.speak("Hello, I am Aion.")

    # Save speech to a file
    await v.speak("Hello world", output_file="greeting.wav")

    # Transcribe an audio file (requires Whisper)
    text = await v.transcribe("meeting.wav")
    print(f"Transcribed: {text}")

asyncio.run(main())
```

---

## 16. Browser automation

```python
import asyncio
from aion_core.browser import Browser

async def main():
    b = Browser()
    print(f"Backend: {b.backend}")  # 'playwright' or 'urllib'

    # Fetch a page
    page = await b.fetch("https://example.com")
    print(f"Title: {page.title}")
    print(f"Text (first 500 chars): {page.text[:500]}")
    print(f"Links: {len(page.links)}")

    # Take a screenshot (Playwright only)
    if b.backend == "playwright":
        await b.screenshot("https://example.com", "example.png")

    await b.close()

asyncio.run(main())
```

---

## 17. Run the benchmark suite

```python
import asyncio
from aion_core.benchmark.runner import BenchmarkRunner

async def main():
    runner = BenchmarkRunner(agent=my_agent, agent_version="0.4.0")
    report = await runner.run_full_benchmark()
    print(f"Overall score: {report.overall_score:.2f}")
    print(f"Passed: {report.passed}/{report.total_tasks}")
    print(f"Avg time: {report.avg_time:.2f}s")
    print(f"Avg tokens: {report.avg_tokens:.0f}")

asyncio.run(main())
```

Or from the TUI:

```
/benchmark
```

---

## 18. Health check + observability

```python
import asyncio
from aion_core.health import HealthRegistry, register_default_checks
from aion_core.telemetry import get_metrics, get_tracer

# Register default health checks
agent = ...
health = register_default_checks(agent)

# Add a custom check
@health.liveness("my_service")
async def check_my_service():
    # ... verify your service ...
    return True  # or False, or (False, "reason")

# Run the HTTP health server
asyncio.create_task(health.serve(port=8080))

# Record metrics
metrics = get_metrics()
metrics.increment("agent.chat.turns", tags={"persona": "coder"})
metrics.observe("agent.chat.latency_seconds", 0.42)

# Start a trace span
tracer = get_tracer()
span = tracer.start_span("agent.chat", tags={"user_id": "42"})
# ... do work ...
span.end()

# Export everything to JSON for external observability backends
from aion_core.telemetry import export_all
export_all("/tmp/aion-telemetry.json")
```
