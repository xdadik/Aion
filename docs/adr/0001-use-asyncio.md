# ADR-0001: Use asyncio throughout the framework

Date: 2026-08-08
Status: Accepted

## Context

Aion Hand needs to perform many I/O-bound operations concurrently:
- LLM API calls (potentially long-running)
- MCP server communication (stdio + SSE)
- Web fetching (multiple URLs in parallel)
- Messaging platform polling (Telegram, Discord, etc.)
- Subagent orchestration (parallel execution branches)

A synchronous design would either block on every I/O call (slow) or
require manual thread management (complex, error-prone).

## Decision

Use `asyncio` as the concurrency model for the entire framework.
Every I/O-bound function is `async def` and uses `await` for I/O.

## Consequences

### Positive
- Clean, single-threaded concurrency — no GIL contention
- Compositional: `asyncio.gather()` for parallel work, `asyncio.create_task()` for background
- Cancellation propagates naturally through `asyncio.CancelledError`
- Stdlib `asyncio` is well-supported on all platforms

### Negative
- Async viral: callers must also be async (or use `asyncio.run()`)
- Harder to integrate with sync libraries (requires `run_in_executor`)
- Debugging stack traces can be confusing (coroutines, tasks)
- `pytest` requires `pytest-asyncio` plugin and `asyncio_mode = "auto"`

### Mitigations
- All blocking stdlib calls (`urllib.request.urlopen`, `subprocess`, file I/O
  on large files) are wrapped in `loop.run_in_executor(None, ...)` to avoid
  blocking the event loop.
- `pytest-asyncio` is in `requirements-dev.txt` and configured in `pyproject.toml`.
- Every async function has a docstring explaining its coroutine nature.

## Alternatives Considered

- **Threading** — rejected: GIL limits true parallelism for CPU work; race
  conditions are hard to debug.
- **Trio / AnyIO** — rejected: smaller ecosystem, asyncio is in stdlib.
- **Multiprocessing** — rejected: too heavy for I/O-bound work; serialization
  overhead. Used only where CPU parallelism is genuinely needed (none currently).
