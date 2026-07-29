# API Reference

Complete Python SDK reference for Aion Hand. All public classes,
methods, and data structures are documented here with usage examples.

---

## AionHand

**Module:** `aion_core.agent.core`

The central agent orchestrator. This is the main entry point for
programmatic usage.

```python
from aion_core import AionHand
from aion_core.agent.core import AgentConfig

agent = AionHand()
await agent.start()
```

### Constructor

```python
AionHand(
    config: Optional[AgentConfig] = None,
    personality: Optional[str] = None,
)
```

| Parameter    | Type           | Default | Description                    |
|--------------|----------------|---------|--------------------------------|
| `config`     | `AgentConfig`  | `None`  | Configuration object. If `None`, uses defaults. |
| `personality` | `str`         | `None`  | Custom system prompt. If `None`, uses `DEFAULT_PERSONALITY`. |

### Methods

#### `async start() -> None`

Initialises all subsystems in order: provider → memory → tools →
skills → agent loop → orchestration → cron → messaging. Creates
data directories if they don't exist. Saves config to disk.

```python
agent = AionHand()
await agent.start()  # initializes everything
```

#### `async chat(message, session_id=None) -> Dict[str, Any]`

Send a message and receive a response. Searches memory for relevant
context, matches skills, runs the agent loop, persists the
conversation, and evaluates for skill creation opportunities.

```python
result = await agent.chat("What is the capital of France?")
print(result["content"])           # "Paris"
print(result["tools_used"])       # [] (no tools needed)
print(result["metadata"]["elapsed_seconds"])  # ~1.2
```

| Return key      | Type   | Description                                   |
|------------------|--------|-----------------------------------------------|
| `content`        | `str`  | The agent's response text.                   |
| `tools_used`     | `list` | Names of tools called during this turn.      |
| `error`          | `str`  | Error message if something went wrong.       |
| `metadata`       | `dict` | `elapsed_seconds`, `tokens_used`, `turns`, etc. |

#### `async spawn_subagent(task, tools=None, personality=None, timeout=None) -> Dict[str, Any]`

Spawn an isolated subagent for a task. The subagent gets its own
conversation context and optional tool restrictions.

```python
result = await agent.spawn_subagent(
    task="Research React vs Vue performance benchmarks",
    tools=["web_search", "web_fetch"],
    timeout=120,
)
print(result["content"])
```

#### `async schedule_task(task, schedule, platforms=None) -> str`

Schedule a recurring cron task. Returns the task ID.

```python
task_id = await agent.schedule_task(
    task="Give me a weather briefing",
    schedule="0 9 * * *",     # daily at 9am
    platforms=["telegram"],  # deliver results to Telegram
)
```

#### `async execute_tool(tool_name, **kwargs) -> Any`

Execute a tool directly, bypassing the agent loop.

```python
result = await agent.execute_tool("calculator", expression="2 ** 10")
# → 1024
```

#### `async create_skill(name, content) -> None`

Create a new skill in Hermes `SKILL.md` format.

```python
await agent.create_skill("summarizer", """
---
name: summarizer
description: Summarize text
trigger: summarize, condense
---
# Summarizer Skill
## Instructions
1. Read the input text
2. Extract key points
3. Write a concise summary
""")
```

#### `async search_memory(query, limit=10) -> List[Dict]`

Full-text search over all memory layers using FTS5.

```python
memories = await agent.search_memory("Python async patterns", limit=5)
for m in memories:
    print(f"[{m['layer']}] {m['content'][:100]}")
```

#### `async get_insights(days=7) -> Dict[str, Any]`

Usage analytics: agent state, uptime, memory stats, skill stats,
tool stats.

```python
insights = await agent.get_insights()
print(f"Uptime: {insights['agent']['uptime']:.0f}s")
print(f"Memory entries: {insights['memory']['total_entries']}")
```

#### `async shutdown() -> None`

Graceful shutdown. Stops subsystems in reverse order of initialisation.

```python
await agent.shutdown()
```

#### Properties

| Property     | Type   | Description                               |
|-------------|--------|-------------------------------------------|
| `uptime`    | `float` | Seconds since `start()` was called.      |
| `session_id`| `str`  | Auto-generated session identifier.          |
| `state`     | `AgentState` | Current lifecycle state.               |
| `config`    | `AgentConfig` | Active configuration.                  |

### Async context manager

```python
async with AionHand() as agent:
    result = await agent.chat("Hello!")
```

---

## AgentConfig

**Module:** `aion_core.agent.core`

Central configuration dataclass. All fields have sensible defaults.

```python
config = AgentConfig(
    default_provider="openai",
    default_model="gpt-4o",
    max_turns=50,
    tool_approval_mode="ask",
    memory_enabled=True,
)
agent = AionHand(config=config)
```

### Key fields

| Field                  | Type  | Default             | Description                         |
|------------------------|-------|---------------------|-------------------------------------|
| `default_provider`     | `str` | `"openai"`          | LLM provider name                   |
| `default_model`        | `str` | `"gpt-4o"`          | LLM model name                      |
| `max_turns`            | `int` | `50`                | Max loop iterations per chat        |
| `max_tokens`           | `int` | `4096`              | Max tokens per LLM response        |
| `temperature`          | `float`| `0.7`              | LLM temperature                    |
| `context_window`       | `int` | `128000`            | LLM context window size            |
| `memory_enabled`       | `bool`| `True`             | Enable 6-layer memory system       |
| `memory_persist`       | `bool`| `True`             | Persist memories to disk            |
| `memory_max_entries`   | `int` | `10000`             | Max stored memory entries           |
| `skills_enabled`       | `bool`| `True`             | Enable skills engine               |
| `skills_auto_create`   | `bool`| `True`             | Auto-create skills from patterns   |
| `tool_approval_mode`   | `str` | `"auto"`            | `"auto"`, `"ask"`, or `"deny"`     |
| `mcp_enabled`          | `bool`| `True`             | Enable MCP integration             |
| `sandbox_enabled`      | `bool`| `True`             | Enable execution sandbox           |
| `max_subagents`        | `int` | `5`                 | Max concurrent subagents            |
| `subagent_timeout`     | `int` | `300`               | Subagent timeout in seconds        |
| `cron_enabled`         | `bool`| `True`             | Enable cron scheduler               |

### Methods

```python
config.save()                    # Write to ~/.aion-hand/config.json
AgentConfig.load(path)           # Load from JSON file
```

---

## MemoryManager

**Module:** `aion_core.memory.manager`

6-layer memory system with FTS5 full-text search.

```python
from aion_core.memory.manager import MemoryManager

memory = MemoryManager(
    memory_dir=Path("~/.aion-hand/memory"),
    persist=True,
    max_entries=10000,
)
await memory.initialize()
```

### Key methods

| Method                          | Description                                    |
|----------------------------------|------------------------------------------------|
| `async initialize()`            | Create FTS5 database, load persisted memories |
| `async store(entry, layer)`     | Store a memory entry at a specific layer       |
| `async search(query, limit)`     | FTS5 full-text search across all layers       |
| `async search_relevant(query)`   | Search + format for system prompt injection    |
| `async store_conversation(...)` | Store a (user, agent) pair as L3 episodic     |
| `async get_stats()`             | Return memory statistics                       |
| `async nudge()`                 | Return relevant memories for proactive context |
| `async shutdown()`              | Persist all layers, close DB                  |

---

## ToolRegistry

**Module:** `aion_core.tools.registry`

MCP-compatible tool management with 24 built-in tools.

```python
from aion_core.tools.registry import ToolRegistry

registry = ToolRegistry(config=config, approval_mode="auto")
await registry.initialize()
print(f"Loaded {len(registry)} tools")
```

### Key methods

| Method                          | Description                                   |
|----------------------------------|-----------------------------------------------|
| `async initialize()`            | Register all built-in tools                   |
| `async execute(name, **kwargs)`  | Validate, approve, execute, and return result |
| `register(tool)`                | Register a custom `Tool` object              |
| `get_tool(name) -> Tool`        | Look up a tool by name                        |
| `list_tools() -> List[Tool]`     | List all registered tools                     |
| `get_openai_schemas()`          | Get all tools in OpenAI function-calling format |
| `get_stats()`                   | Per-tool call counts, errors, avg time       |

---

## MCPClient

**Module:** `aion_core.mcp.client`

Full MCP client with stdio and SSE transports.

```python
from aion_core.mcp.client import MCPClient

client = MCPClient()

# Connect via stdio (subprocess)
await client.connect_stdio(
    name="filesystem",
    command="npx",
    args=["-y", "@anthropic/mcp-filesystem", "/home/user/docs"],
)

# Connect via SSE (HTTP)
await client.connect_sse(
    name="remote-api",
    url="http://localhost:8080/sse",
)

# List connected servers
for server in client.list_connected_servers():
    print(f"{server.name} ({server.transport})")
```

### Key methods

| Method                              | Description                                   |
|--------------------------------------|-----------------------------------------------|
| `connect_stdio(name, command, args)` | Launch MCP server as subprocess              |
| `connect_sse(name, url)`             | Connect to SSE MCP endpoint                   |
| `disconnect(name)`                   | Gracefully disconnect a server                 |
| `call_tool(server, tool, args)`       | Call a tool on a specific server              |
| `list_tools(server)`                 | List tools on a server                       |
| `list_resources(server)`             | List resources on a server                    |
| `list_connected_servers()`           | List all connected server info               |

---

## SecurityManager

**Module:** `aion_core.security.sandbox`

Central security facade combining validation, approval, and sandboxing.

```python
from aion_core.security import SecurityManager

security = SecurityManager(config)

# Validate a command
is_safe, reason = await security.check_command("ls -la /tmp")

# Request approval (in "ask" mode, this blocks for human input)
approved = await security.request_tool_approval(
    tool_name="file_delete",
    params={"path": "/tmp/old_data"},
    reason="Cleanup task",
)

# Execute code in sandbox
result = await security.execute_sandboxed("import math; print(math.pi)")
```

### Key methods

| Method                              | Description                                   |
|--------------------------------------|-----------------------------------------------|
| `check_command(cmd)`                 | Validate against blacklist/whitelist          |
| `request_tool_approval(name, params, reason)` | Request human approval (or auto/deny) |
| `execute_sandboxed(code, timeout)`  | Run Python in sandboxed subprocess             |
| `execute_shell(command, timeout)`    | Run shell command with validation             |
| `get_audit_log()`                    | Ring-buffer of all security events            |
| `get_stats()`                        | Execution counts, durations, mode             |

---

## OrchestrationEngine

**Module:** `aion_core.orchestration.engine`

Multi-agent orchestration with DAG-based workflows.

```python
from aion_core.orchestration.engine import OrchestrationEngine

engine = OrchestrationEngine(
    agent=agent,
    max_subagents=5,
    timeout=300,
)
await engine.initialize()

# Spawn a subagent
result = await engine.spawn_subagent(
    task="Analyze this dataset and produce a chart",
    tools=["web_search", "execute_code"],
    personality="You are a data scientist.",
    timeout=120,
)
```

---

## BenchmarkRunner

**Module:** `aion_core.benchmark`

Structured benchmark suite for measuring agent performance.

```python
from aion_core.benchmark import BenchmarkRunner, get_tasks_by_category

runner = BenchmarkRunner(agent=agent, output_dir="./bench_results")

# Run all benchmarks
report = await runner.run_full_benchmark()

# Run specific category
reasoning_tasks = get_tasks_by_category("reasoning")
report = await runner.run_tasks(reasoning_tasks)

# Generate report
markdown = await runner.generate_report_markdown(report)
```

### Key classes

| Class              | Description                                   |
|--------------------|-----------------------------------------------|
| `BenchmarkTask`    | A single benchmark task (input, expected, evaluator) |
| `BenchmarkRunner`  | Orchestrates running tasks and collecting results  |
| `BenchmarkEvaluator` | Scores task results against expectations    |
| `BenchmarkReport`  | Aggregated scores, timing, and per-category breakdown |
| `MetricsTracker`   | Real-time token/time tracking across tasks      |

---

## DynamicManager

**Module:** `aion_core.dynamic.agent_factory`

Runtime agent creation for dynamic, context-specific agents.

```python
from aion_core.dynamic.agent_factory import DynamicManager

dm = DynamicManager(agent=agent)

# Create a specialised agent at runtime
specialist = dm.create_agent(
    name="code_reviewer",
    personality="You are a senior code reviewer.",
    tools=["read_file", "lint_code"],
    config_override={"max_turns": 10},
)

result = await specialist.chat("Review this code: ...")
```

---

## ModelRouter (ProviderFactory)

**Module:** `aion_core.providers.factory`

Provider-agnostic LLM access through a unified interface.

```python
from aion_core.providers.factory import ProviderFactory, ChatMessage

# Create a provider
provider = ProviderFactory.create(
    name="openai",
    config={"api_key": "sk-..."},
    default_model="gpt-4o",
)

# Chat
response = await provider.chat(
    messages=[
        ChatMessage(role="system", content="You are helpful."),
        ChatMessage(role="user", content="Hello!"),
    ],
    tools=[...],  # optional tool schemas
)

# Stream
async for token in provider.stream(messages):
    print(token, end="", flush=True)
```

### Supported providers

| Provider   | Env var key              | Notes                              |
|------------|--------------------------|-------------------------------------|
| `openai`   | `OPENAI_API_KEY`        | GPT-4o, GPT-4, GPT-3.5-turbo      |
| `anthropic`| `ANTHROPIC_API_KEY`     | Claude 3.5 Sonnet, Claude 3 Opus    |
| `google`   | `GOOGLE_API_KEY`        | Gemini Pro, Gemini Ultra            |
| `ollama`   | *(none needed)*          | Any local model via Ollama         |
| `openrouter`| `OPENROUTER_API_KEY`    | 300+ models via single API         |
| `custom`   | *(user-defined)*          | Any OpenAI-compatible endpoint      |

---

## Top-level imports

```python
# Everything is re-exported from aion_core for convenience
from aion_core import (
    AionHand,           # Central agent orchestrator
    AgentLoop,          # Core control loop
    MemoryManager,      # 6-layer memory system
    ToolRegistry,        # Tool management
    SkillEngine,         # Skill creation & routing
    ProviderFactory,     # Provider-agnostic LLM access
)
```

---

## Quick reference card

```python
# Minimal example
from aion_core import AionHand

agent = AionHand()
await agent.start()

# Chat
r = await agent.chat("Hello!")
print(r["content"])

# Use a tool directly
r = await agent.execute_tool("web_search", query="Aion Hand")

# Spawn a subagent
r = await agent.spawn_subagent("Write a Python sorting algorithm")

# Schedule a task
tid = await agent.schedule_task("Daily weather", "0 8 * * *")

# Search memory
memories = await agent.search_memory("previous projects")

# Get analytics
stats = await agent.get_insights()

# Done
await agent.shutdown()
```
