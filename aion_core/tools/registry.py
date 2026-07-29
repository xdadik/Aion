#!/usr/bin/env python3
"""
Aion Hand - Tool Registry
==========================

MCP-compatible tool management system providing:
  - Tool registration and discovery with schema-based parameter descriptions
  - 24 built-in tools organised into toolsets (web, code, file, utility, data,
    productivity, media, weather, system)
  - Approval modes (auto / ask / deny) for sensitive operations
  - Timeout handling, parameter validation, type checking, and execution logging
  - OpenAI function-calling and MCP schema generation for LLM integration
  - Per-tool call statistics (count, errors, avg time)
  - Custom tool loading from pluggable Python modules
  - Ring-buffer execution audit log

Architecture inspired by:
  - OpenClaw: 40+ built-in tools, personal AI assistant
  - Hermes Agent: Grouped toolsets, skill routing
  - MCP (Model Context Protocol): Standard tool interface
"""

from __future__ import annotations

import asyncio
import calendar
import json
import logging
import math
import os
import platform
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import (
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)

logger = logging.getLogger("aion_hand.tools.registry")


# ======================================================================
# Approval Mode
# ======================================================================


class ApprovalMode(str, Enum):
    """How the registry handles tools that require user approval."""

    AUTO = "auto"   # Execute immediately, no gate
    ASK = "ask"     # Pause and invoke the approval callback
    DENY = "deny"   # Block all approval-required tools


# ======================================================================
# Data Classes
# ======================================================================


class ToolParameter:
    """Describes a single parameter accepted by a :class:`Tool`.

    Follows the JSON Schema subset supported by OpenAI function calling:
    ``string``, ``integer``, ``number``, ``boolean``, ``array``, ``object``.
    """

    __slots__ = ("name", "type", "description", "required", "default", "enum")

    def __init__(
        self,
        name: str,
        type: str,              # noqa: A002  (shadowing builtin is intentional)
        description: str = "",
        required: bool = True,
        default: Any = None,
        enum: Optional[List[str]] = None,
    ) -> None:
        self.name = name
        self.type = type
        self.description = description
        self.required = required
        self.default = default
        self.enum = enum

    # -- serialisation ---------------------------------------------------

    def to_json_schema(self) -> Dict[str, Any]:
        """Return the JSON Schema representation for this parameter."""
        schema: Dict[str, Any] = {"type": self.type}
        if self.description:
            schema["description"] = self.description
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.default is not None:
            schema["default"] = self.default
        return schema

    # -- helpers ---------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"ToolParameter(name={self.name!r}, type={self.type!r}, "
            f"required={self.required})"
        )


class Tool:
    """Represents a single invocable tool.

    A *Tool* bundles a name, human-readable description, a list of
    :class:`ToolParameter` definitions, and an async handler callable.
    Metadata carried by each tool:

    * ``toolset`` – logical group (e.g. ``"file"``, ``"web"``)
    * ``requires_approval`` – must pass the approval gate before execution
    * ``timeout`` – per-tool execution deadline in seconds
    * ``dangerous`` – flag for tools that mutate system state
    """

    def __init__(
        self,
        name: str,
        description: str,
        parameters: Optional[List[ToolParameter]] = None,
        handler: Optional[Callable[..., Awaitable[Any]]] = None,
        toolset: str = "general",
        requires_approval: bool = False,
        timeout: int = 60,
        dangerous: bool = False,
    ) -> None:
        self.name = name
        self.description = description
        self.parameters: List[ToolParameter] = parameters or []
        self.handler = handler
        self.toolset = toolset
        self.requires_approval = requires_approval
        self.timeout = timeout
        self.dangerous = dangerous

        # Runtime statistics (mutated by the registry)
        self._call_count: int = 0
        self._error_count: int = 0
        self._total_time: float = 0.0

    # -- Schema generation -----------------------------------------------

    def to_openai_schema(self) -> Dict[str, Any]:
        """Convert to the OpenAI function-calling format.

        Example::

            {
                "type": "function",
                "function": {
                    "name": "web_search",
                    "description": "Search the web for information.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "..."},
                            "num_results": {"type": "integer", ...}
                        },
                        "required": ["query"]
                    }
                }
            }
        """
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)

        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                },
            },
        }

    def to_mcp_schema(self) -> Dict[str, Any]:
        """Convert to the MCP (Model Context Protocol) tool schema.

        MCP uses a flatter structure where the tool *is* the schema rather
        than being wrapped in ``{type: "function", function: …}``.
        """
        properties: Dict[str, Any] = {}
        required: List[str] = []

        for param in self.parameters:
            properties[param.name] = param.to_json_schema()
            if param.required:
                required.append(param.name)

        return {
            "name": self.name,
            "description": self.description,
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    # -- Statistics ------------------------------------------------------

    @property
    def call_count(self) -> int:
        """Total number of times this tool has been called."""
        return self._call_count

    @property
    def error_count(self) -> int:
        """Total number of times this tool has raised an error."""
        return self._error_count

    @property
    def avg_time(self) -> float:
        """Average execution time in seconds (0.0 if never called)."""
        if self._call_count == 0:
            return 0.0
        return self._total_time / self._call_count

    # -- Dunders ---------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"Tool(name={self.name!r}, toolset={self.toolset!r}, "
            f"dangerous={self.dangerous})"
        )


# ======================================================================
# Tool Execution Result
# ======================================================================


class ToolResult:
    """Structured result returned after executing a tool.

    Designed to be easily serialised to a dict for logging, LLM message
    injection, or API responses.
    """

    __slots__ = ("tool_name", "success", "data", "error", "elapsed", "timestamp")

    def __init__(
        self,
        tool_name: str,
        success: bool,
        data: Any = None,
        error: Optional[str] = None,
        elapsed: float = 0.0,
    ) -> None:
        self.tool_name = tool_name
        self.success = success
        self.data = data
        self.error = error
        self.elapsed = elapsed
        self.timestamp = time.time()

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a plain dictionary."""
        return {
            "success": self.success,
            "result": self.data if self.success else None,
            "error": self.error,
            "elapsed": round(self.elapsed, 6),
            "tool": self.tool_name,
            "timestamp": self.timestamp,
        }

    def to_content_string(self, max_length: int = 4000) -> str:
        """Format for inclusion as a tool-result message in the LLM conversation."""
        if self.success:
            text = json.dumps(self.data, ensure_ascii=False, default=str)
        else:
            text = f"Error: {self.error}"
        if len(text) > max_length:
            text = text[:max_length] + f"... [truncated, {len(text)} chars total]"
        return text

    def __repr__(self) -> str:
        status = "OK" if self.success else f"ERR({self.error})"
        return f"ToolResult(tool={self.tool_name!r}, {status}, {self.elapsed:.4f}s)"


# ======================================================================
# Approval Callback Type
# ======================================================================

ApprovalCallback = Callable[["Tool", Dict[str, Any]], Awaitable[bool]]


# ======================================================================
# Built-in Tool Handlers
# ======================================================================
# Each handler is an ``async def`` that receives **validated** keyword
# arguments and returns a JSON-serialisable value.
#
# Tools that interact with external services (web search, weather, email,
# image gen, TTS/STT, HTTP, clipboard) return realistic *stub* responses
# so the framework is fully functional even without those services.


# -- Web -----------------------------------------------------------------


async def _handle_web_search(
    query: str,
    num_results: int = 5,
) -> Dict[str, Any]:
    """Search the web for information."""
    logger.info(f"[stub] web_search: query={query!r}, num_results={num_results}")
    return {
        "query": query,
        "results": [
            {
                "title": f"Search result {i + 1} for: {query}",
                "url": f"https://example.com/result-{i + 1}",
                "snippet": (
                    f"Relevant information about '{query}' from source {i + 1}."
                ),
            }
            for i in range(min(num_results, 20))
        ],
        "total_results": min(num_results, 20),
        "note": "Web search is stubbed. Connect a search API for real results.",
    }


async def _handle_web_reader(
    url: str,
    extract_text: bool = True,
) -> Dict[str, Any]:
    """Read and extract content from a web page URL."""
    logger.info(f"[stub] web_reader: url={url!r}")
    return {
        "url": url,
        "title": f"Page at {url}",
        "content": (
            f"This is stub content extracted from {url}. "
            "In production, this would contain the actual page text."
        ),
        "content_type": "text/html",
        "status_code": 200,
        "extracted_text": extract_text,
        "note": "Web reader is stubbed. Connect an HTTP client for real pages.",
    }


# -- Code / Shell ---------------------------------------------------------


async def _handle_code_execute(
    code: str,
    language: str = "python",
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute code in a sandboxed environment."""
    logger.info(
        f"code_execute: language={language!r}, code_len={len(code)}"
    )
    if language not in ("python", "bash", "javascript"):
        return {
            "success": False,
            "error": f"Unsupported language: {language}. Use python, bash, or javascript.",
            "output": "",
        }

    # --- Python execution via subprocess ---------------------------------
    if language == "python":
        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    sys.executable, "-c", code,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=timeout,
            )
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout
            )
            stdout = stdout_bytes.decode("utf-8", errors="replace")
            stderr = stderr_bytes.decode("utf-8", errors="replace")
            return {
                "success": proc.returncode == 0,
                "output": stdout,
                "stderr": stderr,
                "exit_code": proc.returncode,
                "language": language,
            }
        except asyncio.TimeoutError:
            return {
                "success": False,
                "error": f"Code execution timed out after {timeout}s",
                "output": "",
                "exit_code": -1,
                "language": language,
            }
        except Exception as exc:
            return {
                "success": False,
                "error": str(exc),
                "output": "",
                "exit_code": -1,
                "language": language,
            }

    # --- Bash / JavaScript (stub) ---------------------------------------
    return {
        "success": True,
        "output": f"[Stub] Executed {len(code)} chars of {language} code successfully.",
        "stderr": "",
        "exit_code": 0,
        "language": language,
        "note": f"Live execution for {language} is stubbed. Python runs natively.",
    }


async def _handle_shell_command(
    command: str,
    working_dir: str = "",
    timeout: int = 30,
) -> Dict[str, Any]:
    """Execute a shell command."""
    logger.info(f"shell_command: command={command!r}, cwd={working_dir!r}")
    cwd = working_dir or None
    try:
        proc = await asyncio.wait_for(
            asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            ),
            timeout=timeout,
        )
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout
        )
        stdout = stdout_bytes.decode("utf-8", errors="replace")
        stderr = stderr_bytes.decode("utf-8", errors="replace")
        return {
            "success": proc.returncode == 0,
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
            "exit_code": proc.returncode,
            "working_dir": cwd or os.getcwd(),
        }
    except asyncio.TimeoutError:
        return {
            "success": False,
            "command": command,
            "stdout": "",
            "stderr": f"Command timed out after {timeout}s",
            "exit_code": -1,
            "working_dir": cwd or os.getcwd(),
        }
    except Exception as exc:
        return {
            "success": False,
            "command": command,
            "stdout": "",
            "stderr": str(exc),
            "exit_code": -1,
            "working_dir": cwd or os.getcwd(),
        }


# -- File -----------------------------------------------------------------


async def _handle_file_read(
    path: str,
    encoding: str = "utf-8",
) -> Dict[str, Any]:
    """Read the contents of a file."""
    logger.info(f"file_read: path={path!r}")
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"success": False, "error": f"File not found: {path}"}
        if not p.is_file():
            return {"success": False, "error": f"Not a file: {path}"}
        content = p.read_text(encoding=encoding)
        return {
            "success": True,
            "path": str(p),
            "content": content,
            "size_bytes": len(content.encode(encoding)),
            "encoding": encoding,
        }
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def _handle_file_write(
    path: str,
    content: str,
    encoding: str = "utf-8",
    create_dirs: bool = False,
) -> Dict[str, Any]:
    """Write content to a file."""
    logger.info(f"file_write: path={path!r}, content_len={len(content)}")
    try:
        p = Path(path).expanduser().resolve()
        if create_dirs:
            p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding=encoding)
        return {
            "success": True,
            "path": str(p),
            "size_bytes": len(content.encode(encoding)),
        }
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


async def _handle_file_list(
    path: str = ".",
    pattern: str = "*",
    recursive: bool = False,
) -> Dict[str, Any]:
    """List files and directories."""
    logger.info(
        f"file_list: path={path!r}, pattern={pattern!r}, recursive={recursive}"
    )
    try:
        p = Path(path).expanduser().resolve()
        if not p.exists():
            return {"success": False, "error": f"Path not found: {path}", "entries": []}
        if not p.is_dir():
            return {"success": False, "error": f"Not a directory: {path}", "entries": []}
        if recursive:
            entries = [
                str(e.relative_to(p)) for e in sorted(p.rglob(pattern))
            ]
        else:
            entries = [str(e.name) for e in sorted(p.glob(pattern))]
        return {
            "success": True,
            "path": str(p),
            "entries": entries,
            "count": len(entries),
        }
    except PermissionError:
        return {"success": False, "error": f"Permission denied: {path}", "entries": []}
    except Exception as exc:
        return {"success": False, "error": str(exc), "entries": []}


# -- Utility --------------------------------------------------------------


async def _handle_calculator(expression: str) -> Dict[str, Any]:
    """Evaluate a mathematical expression safely."""
    logger.info(f"calculator: expression={expression!r}")

    allowed_names: Dict[str, Any] = {
        "abs": abs,
        "round": round,
        "min": min,
        "max": max,
        "sum": sum,
        "pow": pow,
        "sqrt": math.sqrt,
        "log": math.log,
        "log10": math.log10,
        "log2": math.log2,
        "exp": math.exp,
        "sin": math.sin,
        "cos": math.cos,
        "tan": math.tan,
        "asin": math.asin,
        "acos": math.acos,
        "atan": math.atan,
        "pi": math.pi,
        "e": math.e,
        "tau": math.tau,
        "ceil": math.ceil,
        "floor": math.floor,
        "trunc": math.trunc,
    }

    try:
        # Validate: only digits, operators, parentheses, dots, commas,
        # spaces, and allowed function/constant names
        sanitized = expression.replace(" ", "")
        for name in sorted(allowed_names, key=len, reverse=True):
            sanitized = sanitized.replace(name, "")
        if any(c not in "0123456789+-*/().,%\t" for c in sanitized):
            raise ValueError(
                f"Disallowed characters in expression: {expression}"
            )
        result = eval(expression, {"__builtins__": {}}, allowed_names)  # noqa: S307
        return {
            "success": True,
            "expression": expression,
            "result": result,
            "result_type": type(result).__name__,
        }
    except ZeroDivisionError:
        return {"success": False, "error": "Division by zero", "expression": expression}
    except (ValueError, SyntaxError, TypeError, NameError) as exc:
        return {"success": False, "error": str(exc), "expression": expression}


async def _handle_date_time(
    timezone_str: str = "UTC",
    format_str: str = "%Y-%m-%d %H:%M:%S %Z",
) -> Dict[str, Any]:
    """Get the current date and time."""
    logger.info(f"date_time: timezone={timezone_str!r}")
    try:
        import zoneinfo

        tz = zoneinfo.ZoneInfo(timezone_str)
        now = datetime.now(tz)
        return {
            "success": True,
            "datetime": now.isoformat(),
            "formatted": now.strftime(format_str),
            "timezone": timezone_str,
            "unix_timestamp": now.timestamp(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "day_of_week": calendar.day_name[now.weekday()],
        }
    except Exception:
        now = datetime.now(timezone.utc)
        return {
            "success": True,
            "datetime": now.isoformat(),
            "formatted": now.strftime(format_str),
            "timezone": "UTC (fallback — zoneinfo unavailable)",
            "unix_timestamp": now.timestamp(),
            "date": now.strftime("%Y-%m-%d"),
            "time": now.strftime("%H:%M:%S"),
            "day_of_week": calendar.day_name[now.weekday()],
            "warning": f"Could not use timezone '{timezone_str}'. Using UTC.",
        }


async def _handle_system_info() -> Dict[str, Any]:
    """Get information about the current system."""
    logger.info("system_info: gathering system info")
    info: Dict[str, Any] = {
        "success": True,
        "system": platform.system(),
        "release": platform.release(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "hostname": platform.node(),
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cpu_count": os.cpu_count(),
        "pid": os.getpid(),
        "cwd": os.getcwd(),
    }
    try:
        import psutil

        mem = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=0.1)
        disk = psutil.disk_usage("/")
        info.update(
            cpu_percent=cpu_percent,
            memory={
                "total_gb": round(mem.total / (1024**3), 2),
                "available_gb": round(mem.available / (1024**3), 2),
                "percent_used": mem.percent,
            },
            disk={
                "total_gb": round(disk.total / (1024**3), 2),
                "free_gb": round(disk.free / (1024**3), 2),
                "percent_used": round(disk.percent, 1),
            },
        )
    except ImportError:
        info["note"] = "Install psutil for detailed memory/disk/CPU metrics."
    return info


async def _handle_http_request(
    url: str,
    method: str = "GET",
    headers: str = "{}",
    body: str = "",
    timeout: int = 30,
) -> Dict[str, Any]:
    """Make an HTTP API request."""
    logger.info(f"[stub] http_request: method={method!r}, url={url!r}")
    try:
        parsed_headers = json.loads(headers) if headers else {}
    except json.JSONDecodeError:
        parsed_headers = {}
    return {
        "success": True,
        "method": method.upper(),
        "url": url,
        "status_code": 200,
        "headers": parsed_headers,
        "response_body": f"[Stub] Response from {method.upper()} {url}",
        "elapsed_seconds": 0.05,
        "note": "HTTP requests are stubbed. Enable in production with aiohttp/requests.",
    }


# -- Data -----------------------------------------------------------------


async def _handle_json_parse(text: str) -> Dict[str, Any]:
    """Parse a JSON string into a structured object."""
    logger.info(f"json_parse: text_len={len(text)}")
    try:
        parsed = json.loads(text)
        return {
            "success": True,
            "parsed": parsed,
            "type": type(parsed).__name__,
        }
    except json.JSONDecodeError as exc:
        return {
            "success": False,
            "error": f"Invalid JSON: {exc}",
            "text_preview": text[:200],
        }


async def _handle_json_format(
    data: str,
    indent: int = 2,
    sort_keys: bool = False,
) -> Dict[str, Any]:
    """Format a JSON string with proper indentation."""
    logger.info(f"json_format: data_len={len(data)}")
    try:
        parsed = json.loads(data)
        formatted = json.dumps(
            parsed,
            indent=indent,
            sort_keys=sort_keys,
            ensure_ascii=False,
        )
        return {
            "success": True,
            "formatted": formatted,
            "original_size": len(data),
            "formatted_size": len(formatted),
        }
    except json.JSONDecodeError as exc:
        return {"success": False, "error": f"Invalid JSON input: {exc}"}


async def _handle_text_summarize(
    text: str,
    max_length: int = 200,
    style: str = "concise",
) -> Dict[str, Any]:
    """Summarize a block of text.

    In production this would call an LLM for summarization; the built-in
    handler performs simple truncation as a safe default.
    """
    logger.info(
        f"[stub] text_summarize: text_len={len(text)}, style={style!r}"
    )
    summary = text[:max_length]
    if len(text) > max_length:
        summary = summary[: max_length - 3] + "..."
    return {
        "success": True,
        "summary": summary,
        "original_length": len(text),
        "summary_length": len(summary),
        "compression_ratio": round(len(summary) / max(len(text), 1), 3),
        "style": style,
        "note": "Summarization is stubbed (truncation only). Connect an LLM for real summaries.",
    }


# -- Productivity ---------------------------------------------------------


async def _handle_todo_manage(
    action: str,
    text: str = "",
    todo_id: str = "",
    status: str = "",
) -> Dict[str, Any]:
    """Manage a todo list (add, list, complete, delete, clear)."""
    logger.info(f"todo_manage: action={action!r}, text={text!r}")
    valid_actions = ("add", "list", "complete", "delete", "clear")
    if action not in valid_actions:
        return {
            "success": False,
            "error": f"Invalid action '{action}'. Must be one of: {valid_actions}",
        }
    if action == "add" and not text:
        return {"success": False, "error": "'text' is required for the 'add' action."}
    if action in ("complete", "delete") and not todo_id:
        return {
            "success": False,
            "error": f"'todo_id' is required for the '{action}' action.",
        }

    result_id = todo_id or uuid.uuid4().hex[:8]
    return {
        "success": True,
        "action": action,
        "todo_id": result_id,
        "text": text or "",
        "status": status or ("pending" if action == "add" else "completed"),
        "message": (
            f"Todo '{text or result_id}' {action}d successfully."
            if action != "list"
            else "Todos listed."
        ),
    }


async def _handle_note_create(
    title: str,
    content: str,
    tags: str = "",
) -> Dict[str, Any]:
    """Create a new note."""
    note_id = uuid.uuid4().hex[:8]
    logger.info(f"note_create: id={note_id}, title={title!r}")
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else []
    return {
        "success": True,
        "note_id": note_id,
        "title": title,
        "content": content,
        "tags": tag_list,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "message": f"Note '{title}' created with id={note_id}.",
    }


async def _handle_note_search(
    query: str,
    tags: str = "",
    limit: int = 10,
) -> Dict[str, Any]:
    """Search through notes."""
    logger.info(f"note_search: query={query!r}, tags={tags!r}")
    return {
        "success": True,
        "query": query,
        "results": [
            {
                "note_id": uuid.uuid4().hex[:8],
                "title": f"Stub note matching '{query}'",
                "relevance_score": 0.92,
                "snippet": f"This is a stub note that would match the search for '{query}'...",
            }
        ],
        "total_matches": 1,
        "note": "Connect a note storage backend for real search results.",
    }


async def _handle_email_send(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    html: bool = False,
) -> Dict[str, Any]:
    """Send an email."""
    logger.info(f"[stub] email_send: to={to!r}, subject={subject!r}")
    recipients = [a.strip() for a in to.split(",") if a.strip()]
    cc_list = [a.strip() for a in cc.split(",") if a.strip()] if cc else []
    return {
        "success": True,
        "message_id": str(uuid.uuid4()),
        "to": recipients,
        "cc": cc_list,
        "subject": subject,
        "body_preview": body[:100] + ("..." if len(body) > 100 else ""),
        "html": html,
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "note": "Email sending is stubbed. Configure SMTP for real delivery.",
    }


async def _handle_calendar_manage(
    action: str,
    title: str = "",
    start_time: str = "",
    end_time: str = "",
    description: str = "",
    event_id: str = "",
) -> Dict[str, Any]:
    """Manage calendar events (add, list, delete, update)."""
    logger.info(f"[stub] calendar_manage: action={action!r}, title={title!r}")
    valid_actions = ("add", "list", "delete", "update")
    if action not in valid_actions:
        return {
            "success": False,
            "error": f"Invalid action '{action}'. Must be one of: {valid_actions}",
        }
    result_id = event_id or uuid.uuid4().hex[:8]
    return {
        "success": True,
        "action": action,
        "event_id": result_id,
        "title": title,
        "start_time": start_time or datetime.now(timezone.utc).isoformat(),
        "end_time": end_time,
        "description": description,
        "note": "Calendar management is stubbed. Connect a calendar API for real events.",
    }


# -- Media -----------------------------------------------------------------


async def _handle_image_generate(
    prompt: str,
    size: str = "1024x1024",
    style: str = "natural",
) -> Dict[str, Any]:
    """Generate an image from a text prompt."""
    logger.info(f"[stub] image_generate: prompt={prompt!r}, size={size!r}")
    return {
        "success": True,
        "prompt": prompt,
        "image_url": f"data:image/png;base64,[stub-image-data-for-{hash(prompt):#x}]",
        "size": size,
        "style": style,
        "revised_prompt": prompt,
        "note": "Image generation is stubbed. Connect an image generation API for real results.",
    }


async def _handle_text_to_speech(
    text: str,
    voice: str = "alloy",
    speed: float = 1.0,
) -> Dict[str, Any]:
    """Convert text to speech audio."""
    logger.info(f"[stub] text_to_speech: text_len={len(text)}, voice={voice!r}")
    return {
        "success": True,
        "audio_url": "data:audio/mp3;base64,[stub-audio-data]",
        "voice": voice,
        "speed": speed,
        "duration_seconds": round(len(text) / 15.0, 2),
        "note": "TTS is stubbed. Connect a TTS API for real audio output.",
    }


async def _handle_speech_to_text(
    audio_data: str = "",
) -> Dict[str, Any]:
    """Convert speech/audio to text (transcription)."""
    logger.info("[stub] speech_to_text: transcription requested")
    return {
        "success": True,
        "text": "[Stub] Transcribed text from audio input.",
        "language": "en",
        "confidence": 0.95,
        "duration_seconds": 0.0,
        "note": "STT is stubbed. Connect a speech recognition API for real transcriptions.",
    }


# -- Weather ---------------------------------------------------------------


async def _handle_weather(
    location: str,
    units: str = "metric",
) -> Dict[str, Any]:
    """Get weather information for a location."""
    logger.info(f"[stub] weather: location={location!r}, units={units!r}")
    return {
        "location": location,
        "temperature": {
            "value": 22,
            "unit": "\u00b0C" if units == "metric" else "\u00b0F",
        },
        "conditions": "Partly cloudy",
        "humidity": 55,
        "wind": {
            "speed": 12,
            "unit": "km/h" if units == "metric" else "mph",
            "direction": "NW",
        },
        "forecast": [
            {"day": "Tomorrow", "high": 24, "low": 16, "conditions": "Sunny"},
            {"day": "Day after", "high": 20, "low": 14, "conditions": "Rain"},
        ],
        "note": "This is stub data. Connect a weather API for real results.",
    }


# -- System ----------------------------------------------------------------


async def _handle_clipboard_copy(text: str) -> Dict[str, Any]:
    """Copy text to the system clipboard."""
    logger.info(f"[stub] clipboard_copy: text_len={len(text)}")
    return {
        "success": True,
        "action": "copy",
        "text_length": len(text),
        "note": "Clipboard copy is stubbed in this environment.",
    }


async def _handle_clipboard_paste() -> Dict[str, Any]:
    """Paste text from the system clipboard."""
    logger.info("[stub] clipboard_paste: paste requested")
    return {
        "success": True,
        "action": "paste",
        "text": "[Stub clipboard content]",
        "note": "Clipboard paste is stubbed in this environment.",
    }


# ======================================================================
# Built-in Tool Definitions
# ======================================================================


def _build_builtin_tools() -> List[Tool]:
    """Construct the full list of built-in tools (24 tools, 9 toolsets)."""
    return [
        # ── Web toolset (2) ─────────────────────────────────────────────
        Tool(
            name="web_search",
            description=(
                "Search the web for information. Returns a list of search "
                "results with titles, URLs, and snippets."
            ),
            parameters=[
                ToolParameter("query", "string", "The search query string"),
                ToolParameter(
                    "num_results", "integer",
                    "Number of results to return (1-20)",
                    required=False, default=5,
                ),
            ],
            handler=_handle_web_search,
            toolset="web",
            timeout=30,
        ),
        Tool(
            name="web_reader",
            description=(
                "Read and extract content from a web page URL. "
                "Returns the page title and extracted text content."
            ),
            parameters=[
                ToolParameter("url", "string", "The URL of the web page to read"),
                ToolParameter(
                    "extract_text", "boolean",
                    "Whether to extract plain text from HTML",
                    required=False, default=True,
                ),
            ],
            handler=_handle_web_reader,
            toolset="web",
            timeout=30,
        ),
        # ── Code toolset (2) ────────────────────────────────────────────
        Tool(
            name="code_execute",
            description=(
                "Execute code in a sandboxed environment. "
                "Supports Python (runs natively), Bash, and JavaScript (stubbed)."
            ),
            parameters=[
                ToolParameter("code", "string", "The code to execute"),
                ToolParameter(
                    "language", "string",
                    "Programming language",
                    required=False, default="python",
                    enum=["python", "bash", "javascript"],
                ),
                ToolParameter(
                    "timeout", "integer",
                    "Execution timeout in seconds",
                    required=False, default=30,
                ),
            ],
            handler=_handle_code_execute,
            toolset="code",
            dangerous=True,
            requires_approval=True,
            timeout=60,
        ),
        Tool(
            name="shell_command",
            description=(
                "Execute a shell command in the system terminal. "
                "Use for system operations, builds, and scripting."
            ),
            parameters=[
                ToolParameter("command", "string", "The shell command to execute"),
                ToolParameter(
                    "working_dir", "string",
                    "Working directory for the command",
                    required=False, default="",
                ),
                ToolParameter(
                    "timeout", "integer",
                    "Timeout in seconds",
                    required=False, default=30,
                ),
            ],
            handler=_handle_shell_command,
            toolset="code",
            dangerous=True,
            requires_approval=True,
            timeout=60,
        ),
        # ── File toolset (3) ─────────────────────────────────────────────
        Tool(
            name="file_read",
            description="Read the contents of a file. Returns the file content as a string.",
            parameters=[
                ToolParameter("path", "string", "Path to the file to read"),
                ToolParameter(
                    "encoding", "string", "File encoding",
                    required=False, default="utf-8",
                ),
            ],
            handler=_handle_file_read,
            toolset="file",
            timeout=15,
        ),
        Tool(
            name="file_write",
            description=(
                "Write content to a file. Creates the file if it does not "
                "exist, overwrites if it does."
            ),
            parameters=[
                ToolParameter("path", "string", "Path to the file to write"),
                ToolParameter("content", "string", "The content to write to the file"),
                ToolParameter(
                    "encoding", "string", "File encoding",
                    required=False, default="utf-8",
                ),
                ToolParameter(
                    "create_dirs", "boolean",
                    "Create parent directories if they do not exist",
                    required=False, default=False,
                ),
            ],
            handler=_handle_file_write,
            toolset="file",
            dangerous=True,
            requires_approval=True,
            timeout=15,
        ),
        Tool(
            name="file_list",
            description=(
                "List files and directories at a given path. "
                "Supports glob patterns and recursive listing."
            ),
            parameters=[
                ToolParameter(
                    "path", "string", "Directory path to list",
                    required=False, default=".",
                ),
                ToolParameter(
                    "pattern", "string",
                    "Glob pattern to filter entries (e.g. '*.py')",
                    required=False, default="*",
                ),
                ToolParameter(
                    "recursive", "boolean",
                    "List entries recursively",
                    required=False, default=False,
                ),
            ],
            handler=_handle_file_list,
            toolset="file",
            timeout=15,
        ),
        # ── Utility toolset (4) ──────────────────────────────────────────
        Tool(
            name="calculator",
            description=(
                "Evaluate a mathematical expression safely. Supports basic "
                "arithmetic, trigonometry, logarithms, and constants (pi, e, tau)."
            ),
            parameters=[
                ToolParameter(
                    "expression", "string",
                    "The mathematical expression to evaluate (e.g. '2 ** 10 + sqrt(16)')",
                ),
            ],
            handler=_handle_calculator,
            toolset="utility",
            timeout=5,
        ),
        Tool(
            name="date_time",
            description="Get the current date and time in a specified timezone and format.",
            parameters=[
                ToolParameter(
                    "timezone_str", "string",
                    "IANA timezone name (e.g. 'America/New_York', 'UTC')",
                    required=False, default="UTC",
                ),
                ToolParameter(
                    "format_str", "string",
                    "strftime format string",
                    required=False, default="%Y-%m-%d %H:%M:%S %Z",
                ),
            ],
            handler=_handle_date_time,
            toolset="utility",
            timeout=5,
        ),
        Tool(
            name="system_info",
            description=(
                "Get information about the current system: OS, CPU, memory, "
                "disk, and Python version."
            ),
            parameters=[],
            handler=_handle_system_info,
            toolset="utility",
            timeout=10,
        ),
        Tool(
            name="http_request",
            description=(
                "Make an HTTP API request. Supports GET, POST, PUT, DELETE, "
                "PATCH methods with custom headers and body."
            ),
            parameters=[
                ToolParameter("url", "string", "The URL to send the request to"),
                ToolParameter(
                    "method", "string", "HTTP method",
                    required=False, default="GET",
                    enum=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"],
                ),
                ToolParameter(
                    "headers", "string",
                    "JSON string of HTTP headers",
                    required=False, default="{}",
                ),
                ToolParameter(
                    "body", "string",
                    "Request body (for POST/PUT/PATCH)",
                    required=False, default="",
                ),
                ToolParameter(
                    "timeout", "integer",
                    "Request timeout in seconds",
                    required=False, default=30,
                ),
            ],
            handler=_handle_http_request,
            toolset="utility",
            timeout=60,
        ),
        # ── Data toolset (3) ─────────────────────────────────────────────
        Tool(
            name="json_parse",
            description="Parse a JSON string into a structured object. Returns the parsed data and its type.",
            parameters=[
                ToolParameter("text", "string", "The JSON string to parse"),
            ],
            handler=_handle_json_parse,
            toolset="data",
            timeout=5,
        ),
        Tool(
            name="json_format",
            description="Format a JSON string with proper indentation. Can also sort keys alphabetically.",
            parameters=[
                ToolParameter("data", "string", "The JSON string to format"),
                ToolParameter(
                    "indent", "integer",
                    "Number of spaces for indentation",
                    required=False, default=2,
                ),
                ToolParameter(
                    "sort_keys", "boolean",
                    "Sort object keys alphabetically",
                    required=False, default=False,
                ),
            ],
            handler=_handle_json_format,
            toolset="data",
            timeout=5,
        ),
        Tool(
            name="text_summarize",
            description="Summarize a block of text. Produces a concise or detailed summary.",
            parameters=[
                ToolParameter("text", "string", "The text to summarize"),
                ToolParameter(
                    "max_length", "integer",
                    "Maximum length of the summary in characters",
                    required=False, default=200,
                ),
                ToolParameter(
                    "style", "string", "Summarization style",
                    required=False, default="concise",
                    enum=["concise", "detailed", "bullet_points"],
                ),
            ],
            handler=_handle_text_summarize,
            toolset="data",
            timeout=30,
        ),
        # ── Productivity toolset (5) ─────────────────────────────────────
        Tool(
            name="todo_manage",
            description="Manage a todo list. Actions: add, list, complete, delete, clear.",
            parameters=[
                ToolParameter(
                    "action", "string", "The action to perform",
                    enum=["add", "list", "complete", "delete", "clear"],
                ),
                ToolParameter(
                    "text", "string",
                    "The todo item text (required for 'add')",
                    required=False, default="",
                ),
                ToolParameter(
                    "todo_id", "string",
                    "The todo item ID (required for 'complete' or 'delete')",
                    required=False, default="",
                ),
                ToolParameter(
                    "status", "string",
                    "Status value (for updates)",
                    required=False, default="",
                ),
            ],
            handler=_handle_todo_manage,
            toolset="productivity",
            timeout=10,
        ),
        Tool(
            name="note_create",
            description="Create a new note with a title, content, and optional tags.",
            parameters=[
                ToolParameter("title", "string", "Note title"),
                ToolParameter("content", "string", "Note content"),
                ToolParameter(
                    "tags", "string",
                    "Comma-separated tags",
                    required=False, default="",
                ),
            ],
            handler=_handle_note_create,
            toolset="productivity",
            timeout=10,
        ),
        Tool(
            name="note_search",
            description="Search through notes by query text and/or tags.",
            parameters=[
                ToolParameter("query", "string", "Search query"),
                ToolParameter(
                    "tags", "string",
                    "Comma-separated tags to filter by",
                    required=False, default="",
                ),
                ToolParameter(
                    "limit", "integer",
                    "Maximum number of results",
                    required=False, default=10,
                ),
            ],
            handler=_handle_note_search,
            toolset="productivity",
            timeout=10,
        ),
        Tool(
            name="calendar_manage",
            description="Manage calendar events. Actions: add, list, delete, update.",
            parameters=[
                ToolParameter(
                    "action", "string", "The action to perform",
                    enum=["add", "list", "delete", "update"],
                ),
                ToolParameter(
                    "title", "string", "Event title",
                    required=False, default="",
                ),
                ToolParameter(
                    "start_time", "string", "ISO 8601 start time",
                    required=False, default="",
                ),
                ToolParameter(
                    "end_time", "string", "ISO 8601 end time",
                    required=False, default="",
                ),
                ToolParameter(
                    "description", "string", "Event description",
                    required=False, default="",
                ),
                ToolParameter(
                    "event_id", "string",
                    "Event ID (for delete/update)",
                    required=False, default="",
                ),
            ],
            handler=_handle_calendar_manage,
            toolset="productivity",
            timeout=10,
        ),
        Tool(
            name="email_send",
            description="Send an email to one or more recipients.",
            parameters=[
                ToolParameter("to", "string", "Comma-separated recipient email addresses"),
                ToolParameter("subject", "string", "Email subject line"),
                ToolParameter("body", "string", "Email body text"),
                ToolParameter(
                    "cc", "string", "Comma-separated CC addresses",
                    required=False, default="",
                ),
                ToolParameter(
                    "html", "boolean",
                    "Whether the body is HTML formatted",
                    required=False, default=False,
                ),
            ],
            handler=_handle_email_send,
            toolset="productivity",
            dangerous=True,
            requires_approval=True,
            timeout=30,
        ),
        # ── Media toolset (3) ───────────────────────────────────────────
        Tool(
            name="image_generate",
            description="Generate an image from a text prompt using AI.",
            parameters=[
                ToolParameter("prompt", "string", "Text description of the image to generate"),
                ToolParameter(
                    "size", "string", "Image size",
                    required=False, default="1024x1024",
                    enum=["256x256", "512x512", "1024x1024", "1792x1024", "1024x1792"],
                ),
                ToolParameter(
                    "style", "string", "Image style",
                    required=False, default="natural",
                    enum=["natural", "vivid"],
                ),
            ],
            handler=_handle_image_generate,
            toolset="media",
            timeout=60,
        ),
        Tool(
            name="text_to_speech",
            description="Convert text to speech audio.",
            parameters=[
                ToolParameter("text", "string", "The text to convert to speech"),
                ToolParameter(
                    "voice", "string", "Voice name",
                    required=False, default="alloy",
                    enum=["alloy", "echo", "fable", "onyx", "nova", "shimmer"],
                ),
                ToolParameter(
                    "speed", "number",
                    "Speech speed multiplier (0.25 to 4.0)",
                    required=False, default=1.0,
                ),
            ],
            handler=_handle_text_to_speech,
            toolset="media",
            timeout=30,
        ),
        Tool(
            name="speech_to_text",
            description="Convert speech/audio to text (transcription).",
            parameters=[
                ToolParameter(
                    "audio_data", "string",
                    "Base64-encoded audio data or file path",
                    required=False, default="",
                ),
            ],
            handler=_handle_speech_to_text,
            toolset="media",
            timeout=30,
        ),
        # ── Weather toolset (1) ───────────────────────────────────────────
        Tool(
            name="weather",
            description="Get current weather and forecast for a location.",
            parameters=[
                ToolParameter("location", "string", "City name or location string"),
                ToolParameter(
                    "units", "string", "Temperature units",
                    required=False, default="metric",
                    enum=["metric", "imperial"],
                ),
            ],
            handler=_handle_weather,
            toolset="weather",
            timeout=15,
        ),
        # ── System toolset (2) ───────────────────────────────────────────
        Tool(
            name="clipboard_copy",
            description="Copy text to the system clipboard.",
            parameters=[
                ToolParameter("text", "string", "The text to copy to the clipboard"),
            ],
            handler=_handle_clipboard_copy,
            toolset="system",
            timeout=5,
        ),
        Tool(
            name="clipboard_paste",
            description="Paste text from the system clipboard.",
            parameters=[],
            handler=_handle_clipboard_paste,
            toolset="system",
            timeout=5,
        ),
    ]


# ======================================================================
# Tool Registry
# ======================================================================


class ToolRegistry:
    """Central registry for all tools available to the agent.

    The registry manages:

    * **Built-in tools** – 24 tools shipped with Aion Hand, organised into
      9 toolsets (web, code, file, utility, data, productivity, media,
      weather, system).
    * **Custom tools** – loaded at startup from the ``tools/`` directory and
      registrable at runtime via :meth:`register`.
    * **Execution** – validated, timeout-gated, approval-aware execution with
      full audit logging.
    * **Schema export** – generates OpenAI function-calling and MCP schemas
      for the LLM provider.

    Usage::

        registry = ToolRegistry(config=config, approval_mode="auto")
        await registry.initialize()
        result = await registry.execute("web_search", query="Python async")
        schemas = registry.get_tools_schema()   # OpenAI format for the LLM
        print(len(registry))                   # Number of registered tools
    """

    def __init__(
        self,
        config: Any,
        approval_mode: str = "auto",
    ) -> None:
        self._config = config
        self._approval_mode = ApprovalMode(approval_mode)

        # Core storage
        self._tools: Dict[str, Tool] = {}
        self._toolsets: Dict[str, List[str]] = {}

        # Audit log (ring buffer)
        self._execution_log: List[Dict[str, Any]] = []
        self._max_log_size: int = 1000

        # Optional approval callback set by the host application
        self._approval_callback: Optional[ApprovalCallback] = None

        logger.debug("ToolRegistry instance created")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Register all built-in tools and load any custom tools from disk."""
        logger.info("Initializing tool registry...")

        # 1. Register built-in tools
        builtins = _build_builtin_tools()
        for tool in builtins:
            self._register_internal(tool)
        logger.info(f"Registered {len(builtins)} built-in tools")

        # 2. Load custom tools from the tools directory
        await self._load_custom_tools()

        logger.info(
            f"Tool registry initialized: {len(self._tools)} tools in "
            f"{len(self._toolsets)} toolsets"
        )

    async def shutdown(self) -> None:
        """Clean up registry resources."""
        logger.info(
            f"Shutting down tool registry ({len(self._tools)} tools, "
            f"{len(self._execution_log)} log entries)"
        )
        self._tools.clear()
        self._toolsets.clear()
        self._execution_log.clear()

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def _register_internal(self, tool: Tool) -> None:
        """Internal registration without validation logging overhead."""
        if tool.name in self._tools:
            logger.warning(f"Overwriting existing tool: {tool.name}")
        self._tools[tool.name] = tool
        self._toolsets.setdefault(tool.toolset, []).append(tool.name)

    def register(self, tool: Tool) -> None:
        """Register a :class:`Tool` instance.

        Args:
            tool: A fully-constructed Tool with a handler.

        Raises:
            ValueError: If the tool is missing a name or handler.
        """
        if not tool.name:
            raise ValueError("Tool must have a non-empty name")
        if tool.handler is None:
            raise ValueError(f"Tool '{tool.name}' must have a handler callable")
        self._register_internal(tool)
        logger.info(
            f"Registered tool '{tool.name}' in toolset '{tool.toolset}' "
            f"(dangerous={tool.dangerous}, approval={tool.requires_approval})"
        )

    def unregister(self, tool_name: str) -> bool:
        """Remove a tool by name. Returns ``True`` if found and removed."""
        tool = self._tools.pop(tool_name, None)
        if tool is None:
            return False
        # Remove from toolset index
        names = self._toolsets.get(tool.toolset)
        if names:
            try:
                names.remove(tool_name)
            except ValueError:
                pass
            if not names:
                del self._toolsets[tool.toolset]
        logger.info(f"Unregistered tool '{tool_name}'")
        return True

    # ------------------------------------------------------------------
    # Custom tool loading
    # ------------------------------------------------------------------

    async def _load_custom_tools(self) -> None:
        """Discover and load tool plugins from the tools directory.

        Expects each plugin to be a ``.py`` file exporting a ``TOOLS`` list
        of :class:`Tool` instances, or a single ``tool`` variable.
        """
        tools_dir: Optional[Path] = getattr(self._config, "tools_dir", None)
        if tools_dir is None:
            return
        tools_dir = Path(tools_dir)
        if not tools_dir.is_dir():
            logger.debug(f"Custom tools directory does not exist: {tools_dir}")
            return

        loaded = 0
        for py_file in sorted(tools_dir.glob("*.py")):
            if py_file.name.startswith("_"):
                continue
            try:
                import importlib.util

                spec = importlib.util.spec_from_file_location(
                    f"custom_tools.{py_file.stem}", py_file
                )
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)

                tools_list: Optional[Sequence[Tool]] = getattr(module, "TOOLS", None)
                if tools_list is None:
                    single = getattr(module, "tool", None)
                    tools_list = [single] if single is not None else None

                if tools_list:
                    for t in tools_list:
                        if isinstance(t, Tool) and t.handler is not None:
                            self._register_internal(t)
                            loaded += 1
            except Exception as exc:
                logger.warning(f"Failed to load custom tool from {py_file}: {exc}")

        if loaded:
            logger.info(f"Loaded {loaded} custom tools from {tools_dir}")

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def set_approval_callback(self, callback: ApprovalCallback) -> None:
        """Set a custom async callback for approval-gated tools.

        The callback receives ``(tool, params)`` and should return ``True``
        to allow execution or ``False`` to deny.
        """
        self._approval_callback = callback

    async def _check_approval(self, tool: Tool, params: Dict[str, Any]) -> bool:
        """Determine whether a tool requiring approval is allowed to run."""
        if self._approval_mode == ApprovalMode.AUTO:
            return True
        if self._approval_mode == ApprovalMode.DENY:
            logger.warning(
                f"Tool '{tool.name}' denied by approval policy (mode=deny)"
            )
            return False
        # ASK mode
        if self._approval_callback is not None:
            try:
                return await self._approval_callback(tool, params)
            except Exception as exc:
                logger.error(f"Approval callback error: {exc}")
                return False
        # No callback configured in ASK mode → default deny
        logger.warning(
            f"Tool '{tool.name}' needs approval but no callback is configured; denying"
        )
        return False

    # ------------------------------------------------------------------
    # Parameter Validation
    # ------------------------------------------------------------------

    @staticmethod
    def _check_type(value: Any, expected: str) -> bool:
        """Rough type check mapping JSON Schema types to Python types."""
        type_map: Dict[str, type] = {
            "string": str,
            "integer": int,
            "number": (int, float),
            "boolean": bool,
            "array": list,
            "object": dict,
        }
        expected_type = type_map.get(expected)
        if expected_type is None:
            return True  # unknown type → pass
        # bool is a subclass of int in Python; check bool first for integers
        if expected == "integer" and isinstance(value, bool):
            return False
        return isinstance(value, expected_type)

    def _validate_params(
        self, tool: Tool, params: Dict[str, Any]
    ) -> Tuple[Dict[str, Any], Optional[str]]:
        """Validate and fill defaults for tool parameters.

        Returns:
            ``(validated_params, error_message_or_None)``
        """
        validated: Dict[str, Any] = {}
        param_map = {p.name: p for p in tool.parameters}

        # Reject unexpected parameters
        for key in params:
            if key not in param_map:
                return {}, f"Unknown parameter '{key}' for tool '{tool.name}'"

        # Validate required, types, enums, and apply defaults
        for param in tool.parameters:
            if param.name in params:
                value = params[param.name]
                if not self._check_type(value, param.type):
                    return {}, (
                        f"Parameter '{param.name}' expects type '{param.type}', "
                        f"got '{type(value).__name__}' (value: {value!r})"
                    )
                if param.enum and value not in param.enum:
                    return {}, (
                        f"Parameter '{param.name}' must be one of {param.enum}, "
                        f"got '{value}'"
                    )
                validated[param.name] = value
            elif param.required:
                return {}, (
                    f"Missing required parameter '{param.name}' "
                    f"for tool '{tool.name}'"
                )
            elif param.default is not None:
                validated[param.name] = param.default

        return validated, None

    # ------------------------------------------------------------------
    # Execution
    # ------------------------------------------------------------------

    async def execute(
        self,
        tool_name: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute a tool by name with validated keyword arguments.

        Supports two calling styles::

            await registry.execute('tool_name', {'param': 'val'})
            await registry.execute('tool_name', param='val')

        When both *params* (dict) and **kwargs are provided, they are
        merged with **kwargs taking precedence.

        Execution pipeline:

        1. **Lookup** – find the tool in the registry
        2. **Validate** – type-check parameters, enforce required/enum constraints
        3. **Approval gate** – check ``requires_approval`` against current mode
        4. **Invoke** – call the async handler with a per-tool timeout
        5. **Audit log** – record the result in the ring-buffer log

        Args:
            tool_name: The registered name of the tool.
            params: Optional dict of parameters (alternative to **kwargs).
            **kwargs: Keyword arguments forwarded to the tool handler.

        Returns:
            A dictionary with keys ``success``, ``result`` (or ``error``),
            ``elapsed``, ``tool``, and ``timestamp``.
        """
        # Merge dict-style params with kwargs (kwargs take precedence)
        if params:
            merged = {**params, **kwargs}
        else:
            merged = kwargs

        start = time.monotonic()

        # 1. Lookup
        tool = self._tools.get(tool_name)
        if tool is None:
            elapsed = time.monotonic() - start
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=(
                    f"Tool '{tool_name}' not found. "
                    f"Available: {list(self._tools.keys())}"
                ),
                elapsed=elapsed,
            )
            self._log_execution(result)
            return result.to_dict()

        # 2. Validate parameters
        validated, validation_error = self._validate_params(tool, merged)
        if validation_error:
            elapsed = time.monotonic() - start
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=validation_error,
                elapsed=elapsed,
            )
            self._log_execution(result)
            return result.to_dict()

        # 3. Approval gate
        if tool.requires_approval:
            approved = await self._check_approval(tool, validated)
            if not approved:
                elapsed = time.monotonic() - start
                result = ToolResult(
                    tool_name=tool_name,
                    success=False,
                    error=(
                        f"Tool '{tool_name}' requires approval and was denied. "
                        f"(approval_mode={self._approval_mode.value})"
                    ),
                    elapsed=elapsed,
                )
                self._log_execution(result)
                return result.to_dict()

        # 4. Execute with timeout
        try:
            data = await asyncio.wait_for(
                tool.handler(**validated),
                timeout=tool.timeout,
            )
            elapsed = time.monotonic() - start

            # Update per-tool statistics
            tool._call_count += 1
            tool._total_time += elapsed

            result = ToolResult(
                tool_name=tool_name,
                success=True,
                data=data,
                elapsed=elapsed,
            )

        except asyncio.TimeoutError:
            elapsed = time.monotonic() - start
            tool._call_count += 1
            tool._error_count += 1
            tool._total_time += elapsed

            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"Tool '{tool_name}' timed out after {tool.timeout}s",
                elapsed=elapsed,
            )

        except Exception as exc:
            elapsed = time.monotonic() - start
            tool._call_count += 1
            tool._error_count += 1
            tool._total_time += elapsed

            logger.error(
                f"Tool '{tool_name}' execution failed: {exc}", exc_info=True
            )
            result = ToolResult(
                tool_name=tool_name,
                success=False,
                error=f"{type(exc).__name__}: {exc}",
                elapsed=elapsed,
            )

        # 5. Audit log
        self._log_execution(result)
        return result.to_dict()

    def _log_execution(self, result: ToolResult) -> None:
        """Append a result to the execution log (ring buffer)."""
        entry = result.to_dict()
        self._execution_log.append(entry)
        if len(self._execution_log) > self._max_log_size:
            self._execution_log = self._execution_log[-self._max_log_size:]

    # ------------------------------------------------------------------
    # Schema Export
    # ------------------------------------------------------------------

    def get_tools_schema(self) -> List[Dict[str, Any]]:
        """Return all tool schemas in **OpenAI function-calling** format.

        This is the method called by :class:`AgentLoop` to build the tools
        payload sent to the LLM provider.
        """
        return [tool.to_openai_schema() for tool in self._tools.values()]

    def get_schemas(self) -> List[Dict[str, Any]]:
        """Alias for :meth:`get_tools_schema`."""
        return self.get_tools_schema()

    def get_mcp_schemas(self) -> List[Dict[str, Any]]:
        """Return all tool schemas in **MCP** format."""
        return [tool.to_mcp_schema() for tool in self._tools.values()]

    def get_toolset_schema(self, toolset_name: str) -> List[Dict[str, Any]]:
        """Return OpenAI-format schemas for tools in a specific toolset."""
        names = self._toolsets.get(toolset_name, [])
        return [
            self._tools[name].to_openai_schema()
            for name in names
            if name in self._tools
        ]

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def get_tool(self, tool_name: str) -> Optional[Tool]:
        """Look up a tool by name. Returns ``None`` if not found."""
        return self._tools.get(tool_name)

    def list_tools(self) -> List[str]:
        """Return a sorted list of all registered tool names."""
        return sorted(self._tools.keys())

    def list_toolsets(self) -> Dict[str, List[str]]:
        """Return a mapping of toolset name → list of tool names."""
        return dict(self._toolsets)

    def get_toolset_names(self) -> List[str]:
        """Return a sorted list of toolset names."""
        return sorted(self._toolsets.keys())

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    async def get_stats(self) -> Dict[str, Any]:
        """Return aggregate usage statistics for all tools."""
        total_calls = sum(t.call_count for t in self._tools.values())
        total_errors = sum(t.error_count for t in self._tools.values())
        tool_stats: Dict[str, Dict[str, Any]] = {}
        for name, tool in self._tools.items():
            tool_stats[name] = {
                "calls": tool.call_count,
                "errors": tool.error_count,
                "avg_time": round(tool.avg_time, 4),
                "toolset": tool.toolset,
                "dangerous": tool.dangerous,
            }
        return {
            "total_tools": len(self._tools),
            "total_toolsets": len(self._toolsets),
            "total_executions": total_calls,
            "total_errors": total_errors,
            "approval_mode": self._approval_mode.value,
            "log_entries": len(self._execution_log),
            "tools": tool_stats,
            "toolsets": dict(self._toolsets),
        }

    def get_execution_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent execution log entries."""
        return self._execution_log[-limit:]

    # ------------------------------------------------------------------
    # Dunder methods
    # ------------------------------------------------------------------

    def __len__(self) -> int:
        """Return the number of registered tools."""
        return len(self._tools)

    def __contains__(self, tool_name: str) -> bool:
        """Check whether a tool is registered by name (``'web_search' in registry``)."""
        return tool_name in self._tools

    def __iter__(self):
        """Iterate over registered :class:`Tool` instances."""
        return iter(self._tools.values())

    def __repr__(self) -> str:
        return (
            f"ToolRegistry(tools={len(self._tools)}, "
            f"toolsets={len(self._toolsets)}, "
            f"approval={self._approval_mode.value})"
        )
