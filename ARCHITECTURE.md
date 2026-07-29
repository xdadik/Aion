# Architecture

Aion Hand is a modular autonomous AI agent framework that combines
best-of-breed ideas from OpenClaw, Hermes Agent, NullClaw, CrewAI,
AutoGen, and LangGraph into a single, coherent architecture.

This document explains how the pieces fit together, how data flows
through the system, and where extension points exist for customisation.

---

## 1. System Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          Aion Hand                                      │
│                                                                          │
│  ┌─────────────┐   ┌──────────────────────────────────────────────┐    │
│  │   CLI /     │──▶│              Agent Core                       │    │
│  │   Web UI    │   │  (AionHand class — central orchestrator)     │    │
│  └─────────────┘   │                                              │    │
│                     │  ┌──────────┐   ┌────────────────────────┐ │    │
│  ┌─────────────┐    │  │  Agent   │──▶│     Agent Loop          │ │    │
│  │  Messaging  │◀──▶│  │  State   │   │  think → tool → respond  │ │    │
│  │  Gateway    │    │  │ Machine  │   └────────────────────────┘ │    │
│  │ (Telegram,  │    │  └──────────┘                              │    │
│  │ Discord,    │    │                                            │    │
│  │  Slack)     │    │  ┌──────────────────────────────────────┐ │    │
│  └─────────────┘    │  │         Subsystems                    │ │    │
│                     │  │                                      │ │    │
│  ┌─────────────┐    │  │  ┌──────────┐  ┌──────────────────┐  │ │    │
│  │  MCP        │◀──▶│  │  │ Provider │  │  Tool Registry    │  │ │    │
│  │  Servers    │    │  │  │ Factory  │  │  (24 built-in)     │  │ │    │
│  │ (filesystem,│    │  │  │ (OpenAI, │  │  + MCP Bridge      │  │ │    │
│  │  github,    │    │  │  Anthropic,│  │  + Custom tools    │  │ │    │
│  │  browser…)  │    │  │  Ollama…) │  │                    │  │ │    │
│  └─────────────┘    │  │  └──────────┘  └──────────────────┘  │ │    │
│                     │  │                                      │ │    │
│                     │  │  ┌──────────┐  ┌──────────────────┐  │ │    │
│                     │  │  │  Memory   │  │  Skills Engine     │  │ │    │
│                     │  │  │ Manager  │  │  (Hermes SKILL.md) │  │ │    │
│                     │  │  │ (6-layer)│  │  + agentskills.io  │  │ │    │
│                     │  │  └──────────┘  └──────────────────┘  │ │    │
│                     │  │                                      │ │    │
│                     │  │  ┌──────────┐  ┌──────────────────┐  │ │    │
│                     │  │  │ Security │  │  Orchestration    │  │ │    │
│                     │  │  │ Manager  │  │  Engine           │  │ │    │
│                     │  │  │ (sandbox │  │  (subagents,       │  │ │    │
│                     │  │  │  + valid │  │   DAG workflows)   │  │ │    │
│                     │  │  │  + appr) │  └──────────────────┘  │ │    │
│                     │  │  └──────────┘                        │ │    │
│                     │  │                                      │ │    │
│                     │  │  ┌──────────┐  ┌──────────────────┐  │ │    │
│                     │  │  │   Cron   │  │  Pipeline         │  │ │    │
│                     │  │  │Scheduler │  │  (mission analyze │  │ │    │
│                     │  │  │          │  │   → plan → execute │  │ │    │
│                     │  │  └──────────┘  │   → verify)       │  │ │    │
│                     │  │                └──────────────────┘  │ │    │
│                     │  └──────────────────────────────────────┘ │    │
│                     └──────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Module Dependency Graph

```
aion_hand.py                     # Entry point (quick-start script)
aion_hand_cli/cli.py             # CLI (argparse, async event loop)

aion_core/
├── agent/
│   ├── core.py                  # AionHand, AgentConfig, AgentState
│   └── loop.py                  # AgentLoop, LoopState, ContextCompressor
│
├── security/
│   └── sandbox.py               # SecurityManager, Sandbox, CommandValidator,
│                                #   ApprovalManager
│
├── providers/
│   └── factory.py               # ProviderFactory, BaseProvider,
│                                #   OpenAIProvider, AnthropicProvider, etc.
│
├── memory/
│   └── manager.py               # MemoryManager (L1-L6 layers), FTS5 search
│
├── tools/
│   └── registry.py              # ToolRegistry, Tool, ToolParameter,
│                                #   ApprovalMode, 24 built-in tools
│
├── skills/
│   └── engine.py                 # SkillEngine (SKILL.md, agentskills.io)
│
├── pipeline/
│   ├── mission.py               # MissionAnalyzer, MissionAnalysis
│   ├── planner.py               # DynamicPlanner, PlanNode, ExecutionPlan
│   ├── executor.py              # ParallelExecutor, ExecutionResult
│   ├── verification.py          # VerificationPipeline, 5 Verifier classes
│   └── critic.py               # Critic, CritiqueResult
│
├── orchestration/
│   └── engine.py                # OrchestrationEngine, SubAgent, Workflow, WorkflowNode
│
├── mcp/
│   ├── config.py                # MCPConfig, MCPServerConfig
│   ├── client.py                # MCPClient (stdio + SSE), JSON-RPC 2.0
│   ├── registry.py              # MCPToolRegistry
│   └── bridge.py                # MCPBridge (mcp → native ToolRegistry)
│
├── knowledge/
│   └── graph.py                 # KnowledgeManager (entity/relationship graph)
│
├── messaging/
│   └── gateway.py              # MessagingGateway, PlatformAdapter (Telegram/Discord/Slack)
│
├── cron/
│   └── scheduler.py            # CronScheduler, ScheduledTask
│
└── dynamic/
    └── agent_factory.py         # DynamicManager (runtime agent creation)
```

**Import rules:**
- `agent.core` may import from any subsystem.
- Subsystems may import from `agent.core` types (`AgentConfig`, `AgentState`)
  but never from `agent.loop` (to avoid circular imports).
- `pipeline/*` uses the agent via an `Any` reference passed at construction
  time, not direct imports.
- `mcp/*` is self-contained; `mcp.bridge` imports `tools.registry.Tool`
  lazily inside methods to avoid hard coupling.

---

## 3. Data Flow

### Chat request flow

```
User sends message
       │
       ▼
  AionHand.chat(message)
       │
       ├─▶ MemoryManager.search_relevant(message)
       │       └──▶ SQLite FTS5 query → top-N relevant memories
       │
       ├─▶ SkillEngine.find_relevant(message)
       │       └──▶ SKILL.md pattern matching → skill context
       │
       ├─▶ AgentLoop.run(user_message, system_context)
       │       │
       │       ├─▶ ContextCompressor.needs_compression(history)
       │       │       └──▶ Truncate old messages if over budget
       │       │
       │       ├─▶ Provider.chat(messages, tools)
       │       │       └──▶ LLM API call → response + tool_calls
       │       │
       │       ├─▶ [if tool_calls] ToolRegistry.execute(name, **params)
       │       │       │
       │       │       ├─▶ SecurityManager.request_tool_approval()
       │       │       ├─▶ Tool handler function(**params)
       │       │       └─▶ ToolCallResult → append to history
       │       │
       │       └─▶ Loop: repeat until LLM returns text (max_turns)
       │
       ├─▶ MemoryManager.store_conversation(user_msg, response)
       │
       ├─▶ SkillEngine.evaluate_for_creation(conversation, response)
       │
       └─▶ Return { content, tools_used, metadata }
```

### Pipeline execution flow

For complex tasks, the agent enters the full pipeline:

```
Task string
     │
     ▼
  MissionAnalyzer.analyze(task)
     │  └──▶ LLM analysis → MissionAnalysis (intent, goals, risks,
     │          complexity, capabilities_needed)
     │
     ▼
  DynamicPlanner.plan(mission, lessons)
     │  └──▶ If simple: deterministic linear plan
     │      If complex: LLM-generated DAG (parallel branches, conditions)
     │
     ▼
  ParallelExecutor.execute(plan)
     │  ├──▶ Topological sort
     │  ├──▶ Semaphore-bounded worker pool
     │  ├──▶ Per-node: agent node / tool node / condition / merge / verify
     │  └──▶ On failure: DynamicPlanner.replan(plan, failure_point, error)
     │
     ▼
  VerificationPipeline.verify(task, result, mission)
     │  └──▶ 5 verifiers in parallel (Logic, Fact, Code, Security, Completeness)
     │
     ▼
  Critic.critique(task, result, verifications)
     │  └──▶ Score 0.0–1.0; if < threshold → trigger repair
     │
     ▼
  Final result (or repair loop)
```

---

## 4. Memory System Design

Aion Hand uses a **6-layer memory hierarchy** inspired by cognitive
science and Hermes Agent's architecture:

```
Layer 6: UserProfile    ◄── Long-lived user preferences, patterns, identity
Layer 5: Procedural      ◄── How-to knowledge (recipes, workflows)
Layer 4: Semantic        ◄── General facts and knowledge (entity graph)
Layer 3: Episodic        ◄── Past conversation summaries
Layer 2: Session         ◄── Current-session facts (lives for one session)
Layer 1: Working         ◄── Current conversation context (short-lived)
```

### Storage backends

| Layer      | Backend                | Persistence      |
|------------|------------------------|------------------|
| L1         | In-memory dict         | No               |
| L2         | In-memory dict         | Session          |
| L3–L5      | JSON files + SQLite    | Permanent        |
| L6         | JSON + USER.md         | Permanent        |

### Search

- **FTS5 full-text search** over all memory entries via SQLite.
- Relevance scoring with keyword matching.
- `search_relevant(query)` returns the top-N entries injected into
  the system prompt for each chat turn.
- **MEMORY.md** — a human-readable Markdown file (OpenClaw-inspired)
  that persists a structured summary of all long-term memories.
- **USER.md** — user preferences and identity, updated with each
  interaction pattern learned.

### Nudge system

The memory manager periodically nudges the agent with relevant past
memories (`memory_nudge_interval`, default 300s). This enables the agent
to proactively bring up past context without being explicitly asked.

---

## 5. Tool System Design

```
┌──────────────────────────────────────────────────────────┐
│                    ToolRegistry                           │
│                                                          │
│  ┌─────────────────┐  ┌──────────────────────────────┐ │
│  │  Built-in Tools  │  │  MCP-Bridged Tools           │ │
│  │  (24 tools)      │  │  (mcp__<server>__<tool>)     │ │
│  │                  │  │                              │ │
│  │  web:            │  │  ┌────────┐  ┌───────────┐ │ │
│  │  - web_search    │  │  │MCP     │  │ MCP        │ │ │
│  │  - web_fetch     │  │  │Client  │──│ Bridge     │ │ │
│  │                  │  │  └────────┘  │            │ │ │
│  │  code:           │  │              │ Forward    │ │ │
│  │  - execute_code  │  │              │ calls to   │ │ │
│  │  - run_shell     │  │              │ MCP server │ │ │
│  │                  │  │              └───────────┘ │ │
│  │  file:           │  └──────────────────────────────┘ │
│  │  - read_file      │                                     │
│  │  - write_file     │  ┌──────────────────────────────┐ │
│  │  - list_dir       │  │  Custom Tools                │ │
│  │                  │  │  (loaded from ~/.aion-hand/tools)│
│  │  utility:        │  └──────────────────────────────┘ │
│  │  - calculator     │                                     │
│  │  - datetime       │  Every tool has:                   │
│  │  - uuid_generator │  • name, description, parameters  │
│  │  ...              │  • handler function (async)        │
│  └─────────────────┘  • toolset (for grouping)          │
│                        • requires_approval flag         │
│                        • timeout                          │
│                        • per-call statistics              │
└──────────────────────────────────────────────────────────┘
```

### Built-in toolsets

| Toolset      | Tools                                           |
|--------------|-------------------------------------------------|
| `web`        | `web_search`, `web_fetch`, `web_scrape`          |
| `code`       | `execute_code`, `run_shell`, `lint_code`         |
| `file`       | `read_file`, `write_file`, `list_dir`, `glob`    |
| `utility`    | `calculator`, `datetime`, `uuid`, `echo`         |
| `data`       | `json_parse`, `json_format`, `csv_read`          |
| `productivity`| `todo_add`, `todo_list`, `todo_done`            |
| `media`      | `generate_image`, `speak_text`                   |
| `weather`    | `get_weather`, `forecast`                         |
| `system`     | `system_info`, `process_list`, `disk_usage`      |

### Tool execution flow

1. LLM returns a `tool_call` with `name` and `arguments`.
2. `ToolRegistry.execute()` validates parameter types.
3. If `requires_approval=True` → `SecurityManager.request_tool_approval()`.
4. If command-type tool → `CommandValidator.validate()` first.
5. Handler function runs with timeout enforcement.
6. Result captured, logged in ring-buffer audit log.
7. `ToolCallResult` returned to the agent loop.

---

## 6. MCP Integration

The Model Context Protocol (MCP) integration allows Aion Hand to use
external tools provided by MCP servers.

### Architecture

```
Aion Hand
    │
    ├── MCPClient (JSON-RPC 2.0 over stdio or SSE)
    │       │
    │       ├── stdio transport ──── subprocess stdin/stdout
    │       └── SSE transport ────── HTTP Server-Sent Events
    │
    ├── MCPToolRegistry ──── discovers and caches all server tools
    │
    └── MCPBridge ──────── bridges MCP tools into native ToolRegistry
                            (mcp__<server>__<tool> naming)
```

### Configuration

MCP servers are configured in `~/.aion-hand/mcp_servers.json`:
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

Default servers (filesystem, GitHub, browser, memory, database) are
pre-configured but `auto_connect=false` — users must opt in.

### Transport details

- **stdio:** `MCPClient.connect_stdio(name, command, args)` — launches
  the server as a subprocess, communicates via stdin/stdout.
- **SSE:** `MCPClient.connect_sse(name, url)` — connects to an HTTP
  endpoint, receives events via `urllib` + asyncio executor.

Both transports support automatic reconnection with exponential
backoff (base 1s, max 30s, max retries configurable).

---

## 7. Security Model

See [`SECURITY.md`](SECURITY.md) for the full, honest treatment.
Here is the architectural summary:

```
Tool request
     │
     ▼
CommandValidator.validate(command)     ◄── regex blacklist + optional whitelist
     │
     ├── BLOCKED → return { validation_error }
     │
     ▼
ApprovalManager.request_approval()   ◄── auto / ask / deny mode
     │
     ├── DENIED → return { approval_denied }
     │
     ▼
Sandbox.execute_python / execute_shell   ◄── subprocess + restricted env
     │                                        + module deny-list
     │                                        + restricted builtins
     │
     ▼
VerificationPipeline.verify()         ◄── 5 verifiers (Logic, Fact, Code,
     │                                        Security, Completeness)
     ▼
Critic.critique()                    ◄── quality score; repair if needed
```

---

## 8. Configuration System

### `AgentConfig` (dataclass)

All configuration is centralised in a single dataclass defined in
`agent/core.py`. Key groups:

| Group            | Prefix              | Examples                            |
|------------------|---------------------|-------------------------------------|
| Identity         | —                   | `name`, `version`                   |
| Paths            | `*_dir`, `*_file`   | `home_dir`, `memory_dir`, `config_file` |
| Provider         | `default_*`         | `default_provider`, `default_model`  |
| Agent            | `max_*`             | `max_turns`, `max_tokens`, `max_subagents` |
| Memory           | `memory_*`          | `memory_enabled`, `memory_persist`, `memory_max_entries` |
| Skills           | `skills_*`          | `skills_auto_create`, `skills_hub_url` |
| Tools            | `tools_*`, `mcp_*`  | `tools_enabled`, `tool_approval_mode` |
| Security         | `sandbox_*`, `command_*` | `sandbox_enabled`, `command_whitelist` |
| Messaging        | `messaging_*`, `platforms` | `messaging_enabled`, `platforms` |
| Cron             | `cron_*`            | `cron_enabled`, `cron_timezone`    |

### Loading order

1. Hard-coded defaults (in `AgentConfig.__init__`).
2. `~/.aion-hand/config.json` (via `AgentConfig.load()`).
3. Environment variables: `AION_HAND_DEFAULT_PROVIDER`, `AION_HAND_TOOL_APPROVAL_MODE`, etc.
4. Runtime overrides (passed to `AionHand(config=...)`).

### Persistence

`AgentConfig.save()` writes to `~/.aion-hand/config.json` as JSON.
Paths are serialised as strings. The config is saved on `start()`.

---

## 9. Extension Points

### Custom providers

Implement `BaseProvider` (abstract class in `providers/factory.py`):
```python
class MyProvider(BaseProvider):
    async def chat(self, messages, tools=None, **kwargs) -> ChatResponse:
        ...
    async def stream(self, messages, tools=None, **kwargs) -> AsyncIterator[str]:
        ...
```

Register via `ProviderFactory.register("my_provider", MyProvider)`.

### Custom tools

Create a Python module in `~/.aion-hand/tools/my_tool.py`:
```python
from aion_core.tools.registry import Tool

async def my_handler(query: str, limit: int = 10) -> str:
    return f"Results for {query}"

TOOL = Tool(
    name="my_search",
    description="Search my database",
    parameters=[...],
    handler=my_handler,
    toolset="custom",
)
```

The tool registry auto-discovers modules in the tools directory.

### Custom verifiers

Implement the `Verifier` ABC from `pipeline/verification.py`:
```python
class MyVerifier(Verifier):
    name = "my_verifier"

    async def verify(self, task, result, context) -> VerificationResult:
        ...
```

Register via `VerificationPipeline.add_verifier(MyVerifier())`.

### Custom platforms (messaging)

Subclass `PlatformAdapter` from `messaging/gateway.py`:
```python
class WhatsAppAdapter(PlatformAdapter):
    async def send(self, chat_id, text): ...
    async def receive_stream(self) -> AsyncIterator[Message]: ...
```

Register via `MessagingGateway.register_adapter("whatsapp", WhatsAppAdapter(...))`.

### Custom skills

Write a `SKILL.md` file (Hermes-compatible format) in `~/.aion-hand/skills/`:
```markdown
---
name: my_skill
description: What this skill does
trigger: search query, calculate
---

# Skill: My Skill

## When to use
...

## Instructions
...

## Examples
...
```

The skill engine auto-discovers and loads these files.

---

## 10. Agent State Machine

```
                    ┌─────────────┐
                    │ UNINITIALIZED│
                    └──────┬──────┘
                           │ start()
                           ▼
                    ┌─────────────┐
                    │ INITIALIZING │
                    └──────┬──────┘
                           │
              ┌────────────┼────────────┐
              │ success    │            │ error
              ▼            │            ▼
        ┌──────────┐      │     ┌────────┐
        │   IDLE    │◀─────┘     │ ERROR  │
        └────┬─────┘            └────────┘
             │
    ┌────────┼──────────────────┐
    │ chat() │ schedule_task()  │ spawn_subagent()
    ▼        ▼                  ▼
┌───────────┐ ┌──────────┐ ┌───────────┐
│ THINKING  │ │ WAITING  │ │ EXECUTING │
└─────┬─────┘ └────┬─────┘ └─────┬─────┘
      │            │             │
      ▼            ▼             ▼
┌───────────┐                ┌───────────┐
│RESPONDING │                │ EXECUTING │
└─────┬─────┘                └─────┬─────┘
      │                            │
      └──────────┬─────────────────┘
                 ▼
           ┌──────────┐
           │   IDLE   │
           └──────────┘
                 │ shutdown()
                 ▼
           ┌───────────────┐
           │ SHUTTING_DOWN │
           └───────┬───────┘
                   ▼
           ┌──────────┐
           │ SHUTDOWN │
           └──────────┘
```

The state machine drives the agent lifecycle. All subsystems are
initialised during `INITIALIZING` and shut down in reverse order during
`SHUTTING_DOWN`. The agent loop transitions through `THINKING →
EXECUTING → RESPONDING` for each chat turn.

---

*This document reflects the architecture at v0.1.0. As the system
evolves, this file is updated alongside the code.*
