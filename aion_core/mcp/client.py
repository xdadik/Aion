#!/usr/bin/env python3
"""
Aion Hand - MCP Client Runtime
===============================
Full MCP (Model Context Protocol) client implementation using JSON-RPC 2.0.

Supports:
  - stdio transport (subprocess communication via stdin/stdout)
  - SSE transport (Server-Sent Events over HTTP, using urllib + asyncio executor)
  - Tool discovery, invocation, resource listing, and prompt listing
  - Automatic reconnection with configurable retry policy
  - Request/response correlation by JSON-RPC id
  - Graceful disconnect lifecycle

Wire protocol reference: https://spec.modelcontextprotocol.io/
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aion_hand.mcp.client")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MCP_PROTOCOL_VERSION = "2024-11-05"
MCP_IMPLEMENTATION_NAME = "aion-hand"
MCP_IMPLEMENTATION_VERSION = "0.1.0"

# Defaults for stdio transport
STDIO_INIT_TIMEOUT = 30       # seconds to wait for server init response
STDIO_CALL_TIMEOUT = 120      # seconds per tool call
STDIO_READ_BUF_SIZE = 65536  # bytes per stdout read chunk

# Defaults for SSE transport
SSE_CONNECT_TIMEOUT = 15      # seconds to establish SSE connection
SSE_MESSAGE_TIMEOUT = 120     # seconds to wait for next SSE event

# Reconnection
RECONNECT_BASE_DELAY = 1.0   # seconds, doubled on each retry
RECONNECT_MAX_DELAY = 30.0
RECONNECT_MAX_RETRIES = 5


# ===================================================================
# Data Classes
# ===================================================================


@dataclass
class MCPTool:
    """A tool exposed by a connected MCP server."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    server_name: str = ""
    protocol_version: str = MCP_PROTOCOL_VERSION

    def to_openai_schema(self) -> dict[str, Any]:
        """Convert to OpenAI function-calling format."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.input_schema,
            },
        }

    def __repr__(self) -> str:
        return (
            f"MCPTool(name={self.name!r}, server={self.server_name!r}, "
            f"desc={self.description[:60]!r})"
        )


@dataclass
class MCPServer:
    """Represents a connected (or previously connected) MCP server."""

    name: str
    transport_type: str = "stdio"  # stdio | sse | websocket
    command: str | None = None   # for stdio
    url: str | None = None       # for sse / websocket
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    status: str = "disconnected"    # connected | disconnected | error
    tools: list[MCPTool] = field(default_factory=list)
    resources: list[dict[str, Any]] = field(default_factory=list)
    prompts: list[dict[str, Any]] = field(default_factory=list)
    server_info: dict[str, Any] = field(default_factory=dict)
    server_capabilities: dict[str, Any] = field(default_factory=dict)

    # Reconnection state
    _reconnect_attempts: int = field(default=0, repr=False)

    def __repr__(self) -> str:
        return (
            f"MCPServer(name={self.name!r}, transport={self.transport_type!r}, "
            f"status={self.status!r}, tools={len(self.tools)})"
        )


# ===================================================================
# JSON-RPC Message Helpers
# ===================================================================


def _jsonrpc_request(method: str, params: dict | None = None, rid: int = 0) -> str:
    """Build a JSON-RPC 2.0 request string."""
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "id": rid,
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, separators=(",", ":")) + "\n"


def _jsonrpc_notification(method: str, params: dict | None = None) -> str:
    """Build a JSON-RPC 2.0 notification (no id, no response expected)."""
    msg: dict[str, Any] = {
        "jsonrpc": "2.0",
        "method": method,
    }
    if params is not None:
        msg["params"] = params
    return json.dumps(msg, separators=(",", ":")) + "\n"


def _parse_jsonrpc_message(raw: str) -> dict[str, Any] | None:
    """Parse a single JSON-RPC message. Returns None on blank/invalid."""
    stripped = raw.strip()
    if not stripped:
        return None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError:
        logger.warning("Failed to parse JSON-RPC message: %.200s", stripped)
        return None


# ===================================================================
# Stdio Connection Handler
# ===================================================================


class _StdioConnection:
    """Manages a subprocess-based stdio transport to an MCP server.

    The MCP stdio protocol sends newline-delimited JSON-RPC messages.
    We write requests to the process stdin and read responses from stdout.
    """

    def __init__(self, command: str, args: list[str], env: dict[str, str]):
        self.command = command
        self.args = args
        self.env = env
        self.process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        # Response queue: maps request id -> Future[response_dict]
        self._pending: dict[int, asyncio.Future] = {}
        self._notification_handlers: list = []
        self._lock = asyncio.Lock()
        self._closed = False

    async def connect(self) -> None:
        """Launch the subprocess."""
        merged_env = {**os.environ, **self.env}
        cmd = [self.command] + self.args
        logger.info("Launching stdio MCP server: %s", " ".join(cmd))
        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=merged_env,
        )
        if self.process.stdout is None:
            raise RuntimeError("Failed to create subprocess stdout pipe")
        # Start background reader that dispatches responses to futures
        self._reader_task = asyncio.create_task(self._read_loop())
        logger.info(
            "Stdio MCP server started (pid=%d)", self.process.pid or 0
        )

    async def _read_loop(self) -> None:
        """Continuously read stdout lines and dispatch to pending futures."""
        assert self.process is not None
        assert self.process.stdout is not None
        try:
            buffer = b""
            while not self._closed:
                chunk = await self.process.stdout.read(STDIO_READ_BUF_SIZE)
                if not chunk:
                    logger.info("Stdio server closed stdout (EOF)")
                    break
                buffer += chunk
                # Split on newlines — each line is a JSON-RPC message
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    text = line.decode("utf-8", errors="replace")
                    msg = _parse_jsonrpc_message(text)
                    if msg is None:
                        continue
                    rid = msg.get("id")
                    if rid is not None:
                        # This is a response to a pending request
                        fut = self._pending.pop(rid, None)
                        if fut and not fut.done():
                            fut.set_result(msg)
                    else:
                        # Notification from server
                        self._handle_notification(msg)
        except asyncio.CancelledError:
            pass
        except Exception as exc:
            logger.error("Stdio read loop error: %s", exc, exc_info=True)
        finally:
            # Reject all pending futures so callers don't hang
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("Stdio connection closed"))
            self._pending.clear()

    def _handle_notification(self, msg: dict[str, Any]) -> None:
        """Handle incoming server notifications."""
        method = msg.get("method", "")
        params = msg.get("params", {})
        logger.debug("Server notification: %s params=%s", method, params)
        for handler in self._notification_handlers:
            try:
                handler(msg)
            except Exception:
                pass

    def on_notification(self, handler) -> None:
        """Register a callback for server notifications."""
        self._notification_handlers.append(handler)

    async def send_request(
        self, method: str, params: dict | None = None, timeout: float = STDIO_CALL_TIMEOUT
    ) -> dict[str, Any]:
        """Send a JSON-RPC request and wait for the response."""
        async with self._lock:
            if self._closed or self.process is None or self.process.stdin is None:
                raise ConnectionError("Stdio connection is not open")

            rid = id(params) ^ int(time.time() * 1e6)  # simple unique id
            # Use incrementing counter for true uniqueness
            if not hasattr(self, "_next_id"):
                self._next_id = 1
            rid = self._next_id
            self._next_id += 1

            request_str = _jsonrpc_request(method, params, rid)
            self.process.stdin.write(request_str.encode("utf-8"))
            await self.process.stdin.drain()

            loop = asyncio.get_running_loop()
            fut: asyncio.Future = loop.create_future()
            self._pending[rid] = fut

        try:
            response = await asyncio.wait_for(fut, timeout=timeout)
            if "error" in response:
                err = response["error"]
                raise MCPError(
                    err.get("code", -1),
                    err.get("message", "Unknown MCP error"),
                    err.get("data"),
                )
            return response.get("result", {})
        except TimeoutError:
            self._pending.pop(rid, None)
            raise TimeoutError(
                f"MCP request '{method}' timed out after {timeout}s"
            )

    async def send_notification(
        self, method: str, params: dict | None = None
    ) -> None:
        """Send a JSON-RPC notification (fire-and-forget)."""
        async with self._lock:
            if self._closed or self.process is None or self.process.stdin is None:
                raise ConnectionError("Stdio connection is not open")
            notif_str = _jsonrpc_notification(method, params)
            self.process.stdin.write(notif_str.encode("utf-8"))
            await self.process.stdin.drain()

    async def close(self) -> None:
        """Terminate the subprocess gracefully."""
        self._closed = True
        if self._reader_task:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
        if self.process:
            try:
                if self.process.stdin:
                    self.process.stdin.close()
                    await self.process.stdin.wait_closed()
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5)
            except TimeoutError:
                logger.warning("Stdio process did not terminate, killing")
                self.process.kill()
                await self.process.wait()
            except Exception as exc:
                logger.debug("Error during stdio close: %s", exc)
            logger.info("Stdio MCP server stopped (pid=%d)", self.process.pid or 0)

    @property
    def is_alive(self) -> bool:
        """Check if the subprocess is still running."""
        if self.process is None:
            return False
        return self.process.returncode is None


# ===================================================================
# SSE Connection Handler
# ===================================================================


class _SSEConnection:
    """Manages an SSE (Server-Sent Events) based connection to an MCP server.

    Uses urllib for HTTP (stdlib only, no aiohttp dependency) with an
    asyncio executor for non-blocking I/O.
    """

    def __init__(self, url: str):
        self.url = url
        self._session_id: str | None = None
        self._endpoint_url: str | None = None
        self._closed = False
        self._lock = asyncio.Lock()
        self._notification_handlers: list = []

    def on_notification(self, handler) -> None:
        """Register a callback for server notifications."""
        self._notification_handlers.append(handler)

    async def connect(self) -> None:
        """Connect to the SSE endpoint.

        The MCP SSE transport requires two steps:
        1. GET the SSE endpoint — server sends an 'endpoint' event with the
           URL where we should POST JSON-RPC messages.
        2. POST JSON-RPC requests to that endpoint URL.
        """
        logger.info("Connecting to SSE MCP server at %s", self.url)

        loop = asyncio.get_running_loop()

        def _do_connect() -> str:
            """Blocking urllib call to establish SSE connection."""
            req = urllib.request.Request(self.url, method="GET")
            req.add_header("Accept", "text/event-stream")

            try:
                resp = urllib.request.urlopen(req, timeout=SSE_CONNECT_TIMEOUT)
            except urllib.error.URLError as exc:
                raise ConnectionError(
                    f"Failed to connect to SSE server at {self.url}: {exc}"
                ) from exc

            # Read initial SSE events to find the endpoint URL.
            # The server sends: event: endpoint\ndata: <url>\n\n
            endpoint = ""
            buf = ""
            while True:
                chunk = resp.read(1)
                if not chunk:
                    break
                decoded = chunk.decode("utf-8", errors="replace")
                buf += decoded
                if buf.endswith("\n\n"):
                    # Parse SSE event
                    lines = buf.strip().split("\n")
                    event_type = ""
                    data = ""
                    for line in lines:
                        if line.startswith("event:"):
                            event_type = line[len("event:"):].strip()
                        elif line.startswith("data:"):
                            data = line[len("data:"):].strip()
                    buf = ""
                    if event_type == "endpoint" and data:
                        endpoint = data
                        break

            resp.close()
            return endpoint

        try:
            self._endpoint_url = await asyncio.wait_for(
                loop.run_in_executor(None, _do_connect),
                timeout=SSE_CONNECT_TIMEOUT,
            )
        except TimeoutError:
            raise TimeoutError(
                f"SSE connection to {self.url} timed out after {SSE_CONNECT_TIMEOUT}s"
            )

        if not self._endpoint_url:
            raise ConnectionError(
                f"SSE server at {self.url} did not provide an endpoint URL"
            )

        logger.info("SSE MCP server connected, POST endpoint: %s", self._endpoint_url)

    async def send_request(
        self, method: str, params: dict | None = None, timeout: float = SSE_MESSAGE_TIMEOUT
    ) -> dict[str, Any]:
        """Send a JSON-RPC request to the MCP server via HTTP POST."""
        if self._closed or not self._endpoint_url:
            raise ConnectionError("SSE connection is not open")

        rid = int(time.time() * 1e6)
        request_body = {
            "jsonrpc": "2.0",
            "id": rid,
            "method": method,
        }
        if params is not None:
            request_body["params"] = params

        loop = asyncio.get_running_loop()

        def _do_post() -> dict[str, Any]:
            """Blocking HTTP POST to the SSE message endpoint."""
            data = json.dumps(request_body).encode("utf-8")
            req = urllib.request.Request(
                self._endpoint_url,
                data=data,
                method="POST",
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
            )
            if self._session_id:
                req.add_header("Mcp-Session-Id", self._session_id)

            try:
                resp = urllib.request.urlopen(req, timeout=timeout)
                response_data = resp.read().decode("utf-8")
                content_type = resp.headers.get("Content-Type", "")

                resp_headers = dict(resp.headers)

                # The response might be SSE or direct JSON
                if "text/event-stream" in content_type:
                    # Parse SSE response
                    for event_block in response_data.split("\n\n"):
                        lines = event_block.strip().split("\n")
                        for line in lines:
                            if line.startswith("data:"):
                                json_str = line[len("data:"):].strip()
                                if json_str:
                                    return json.loads(json_str)
                    return {}
                else:
                    return json.loads(response_data)

            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
                raise MCPError(
                    exc.code,
                    f"HTTP error from SSE server: {exc.reason}",
                    body,
                ) from exc
            except urllib.error.URLError as exc:
                raise ConnectionError(f"SSE request failed: {exc}") from exc
            except json.JSONDecodeError as exc:
                raise MCPError(-32700, "Invalid JSON response from SSE server") from exc

        async with self._lock:
            try:
                raw_response = await asyncio.wait_for(
                    loop.run_in_executor(None, _do_post),
                    timeout=timeout,
                )
            except TimeoutError:
                raise TimeoutError(
                    f"SSE request '{method}' timed out after {timeout}s"
                )

        # Extract session ID from response headers if available
        # (We'd need to thread this through from the blocking function)
        if isinstance(raw_response, dict):
            if "error" in raw_response:
                err = raw_response["error"]
                raise MCPError(
                    err.get("code", -1),
                    err.get("message", "Unknown MCP error"),
                    err.get("data"),
                )
            return raw_response.get("result", {})
        return raw_response

    async def send_notification(
        self, method: str, params: dict | None = None
    ) -> None:
        """Send a notification via the SSE endpoint."""
        await self.send_request(method, params)

    async def close(self) -> None:
        """Close the SSE connection."""
        self._closed = True
        self._endpoint_url = None
        self._session_id = None
        logger.info("SSE MCP server disconnected")


# ===================================================================
# Exceptions
# ===================================================================


class MCPError(Exception):
    """Error returned by an MCP server (JSON-RPC error object)."""

    def __init__(
        self,
        code: int,
        message: str,
        data: Any = None,
    ):
        self.code = code
        self.message = message
        self.data = data
        super().__init__(f"[MCP {code}] {message}")


# ===================================================================
# MCP Client
# ===================================================================


class MCPClient:
    """MCP Client that connects to MCP servers and exposes their tools.

    Supports both stdio (subprocess) and SSE (HTTP) transports. Each
    server connection is managed independently with its own lifecycle.

    Usage::

        client = MCPClient()

        # Connect to a stdio server
        server = await client.connect_stdio(
            "filesystem",
            "npx",
            ["-y", "@anthropic/mcp-filesystem", "/home/user/docs"],
        )

        # List tools
        for tool in client.get_all_tools():
            print(tool.name, tool.description)

        # Call a tool
        result = await client.call_tool("filesystem", "read_file", {
            "path": "/home/user/docs/notes.txt"
        })

        # Disconnect
        await client.disconnect_all()
    """

    def __init__(self):
        self._servers: dict[str, MCPServer] = {}
        self._connections: dict[str, Any] = {}  # _StdioConnection | _SSEConnection
        self._request_id = 0

    # ------------------------------------------------------------------
    # Connection: stdio
    # ------------------------------------------------------------------

    async def connect_stdio(
        self,
        server_name: str,
        command: str,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
    ) -> MCPServer:
        """Launch an MCP server as a subprocess and perform the handshake.

        Args:
            server_name: Logical name for this server.
            command: Executable command (e.g. ``"npx"`` or ``"python"``).
            args: Arguments passed to the command.
            env: Extra environment variables for the subprocess.

        Returns:
            The :class:`MCPServer` descriptor with populated tools/resources.

        Raises:
            ConnectionError: If the subprocess cannot be started or handshake
                fails within the timeout.
            TimeoutError: If initialization does not complete in time.
        """
        # If a previous connection exists, disconnect it first
        await self._safe_disconnect(server_name)

        args = list(args or [])
        env = dict(env or {})

        server = MCPServer(
            name=server_name,
            transport_type="stdio",
            command=command,
            args=args,
            env=env,
            status="connecting",
        )

        conn = _StdioConnection(command, args, env)

        try:
            await conn.connect()
        except Exception as exc:
            server.status = "error"
            self._servers[server_name] = server
            raise ConnectionError(
                f"Failed to launch stdio MCP server '{server_name}': {exc}"
            ) from exc

        self._connections[server_name] = conn
        self._servers[server_name] = server

        # Perform MCP initialization handshake
        try:
            await self._initialize_handshake(server_name, conn)
        except Exception:
            server.status = "error"
            await self._safe_disconnect(server_name)
            raise

        server.status = "connected"
        logger.info(
            "Connected to stdio MCP server '%s' with %d tools",
            server_name,
            len(server.tools),
        )
        return server

    # ------------------------------------------------------------------
    # Connection: SSE
    # ------------------------------------------------------------------

    async def connect_sse(
        self,
        server_name: str,
        url: str,
    ) -> MCPServer:
        """Connect to an MCP server via SSE (Server-Sent Events).

        Args:
            server_name: Logical name for this server.
            url: URL of the SSE endpoint.

        Returns:
            The :class:`MCPServer` descriptor with populated tools.
        """
        await self._safe_disconnect(server_name)

        server = MCPServer(
            name=server_name,
            transport_type="sse",
            url=url,
            status="connecting",
        )

        conn = _SSEConnection(url)

        try:
            await conn.connect()
        except Exception as exc:
            server.status = "error"
            self._servers[server_name] = server
            raise ConnectionError(
                f"Failed to connect to SSE MCP server '{server_name}': {exc}"
            ) from exc

        self._connections[server_name] = conn
        self._servers[server_name] = server

        try:
            await self._initialize_handshake(server_name, conn)
        except Exception:
            server.status = "error"
            await self._safe_disconnect(server_name)
            raise

        server.status = "connected"
        logger.info(
            "Connected to SSE MCP server '%s' with %d tools",
            server_name,
            len(server.tools),
        )
        return server

    # ------------------------------------------------------------------
    # MCP Initialization Handshake
    # ------------------------------------------------------------------

    async def _initialize_handshake(
        self,
        server_name: str,
        conn: Any,  # _StdioConnection | _SSEConnection
    ) -> None:
        """Perform the full MCP initialization handshake.

        Steps:
        1. Send ``initialize`` request with client capabilities.
        2. Receive server capabilities and info.
        3. Send ``initialized`` notification (server considers handshake done).
        4. Fetch tool list, resource list, and prompt list.
        """
        server = self._servers.get(server_name)
        if server is None:
            raise RuntimeError(f"Server '{server_name}' not registered")

        # Step 1: Send initialize request
        init_params = {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {
                "tools": {"listChanged": True},
                "resources": {"subscribe": True, "listChanged": True},
                "prompts": {"listChanged": True},
            },
            "clientInfo": {
                "name": MCP_IMPLEMENTATION_NAME,
                "version": MCP_IMPLEMENTATION_VERSION,
            },
        }

        result = await conn.send_request(
            "initialize", init_params, timeout=STDIO_INIT_TIMEOUT
        )

        # Step 2: Parse server response
        server.server_capabilities = result.get("capabilities", {})
        server.server_info = result.get("serverInfo", {})
        protocol_version = result.get("protocolVersion", MCP_PROTOCOL_VERSION)
        logger.info(
            "MCP server '%s' initialized: protocol=%s, server=%s %s",
            server_name,
            protocol_version,
            server.server_info.get("name", "?"),
            server.server_info.get("version", "?"),
        )

        # Step 3: Send initialized notification
        await conn.send_notification("notifications/initialized", {})

        # Step 4: Fetch tools, resources, prompts
        server.tools = await self._fetch_tools(server_name, conn, protocol_version)
        server.resources = await self._fetch_resources(server_name, conn)
        server.prompts = await self._fetch_prompts(server_name, conn)

    async def _fetch_tools(
        self,
        server_name: str,
        conn: Any,
        protocol_version: str = MCP_PROTOCOL_VERSION,
    ) -> list[MCPTool]:
        """Fetch the tool list from a connected server."""
        try:
            result = await conn.send_request("tools/list", {}, timeout=15)
            raw_tools = result.get("tools", [])
            tools = []
            for t in raw_tools:
                tool = MCPTool(
                    name=t.get("name", ""),
                    description=t.get("description", ""),
                    input_schema=t.get("inputSchema", {"type": "object", "properties": {}}),
                    server_name=server_name,
                    protocol_version=protocol_version,
                )
                tools.append(tool)
            logger.debug(
                "Server '%s' reported %d tools", server_name, len(tools)
            )
            return tools
        except Exception as exc:
            logger.warning("Failed to fetch tools from '%s': %s", server_name, exc)
            return []

    async def _fetch_resources(
        self, server_name: str, conn: Any
    ) -> list[dict[str, Any]]:
        """Fetch the resource list from a connected server."""
        try:
            result = await conn.send_request("resources/list", {}, timeout=15)
            return result.get("resources", [])
        except Exception as exc:
            logger.warning("Failed to fetch resources from '%s': %s", server_name, exc)
            return []

    async def _fetch_prompts(
        self, server_name: str, conn: Any
    ) -> list[dict[str, Any]]:
        """Fetch the prompt list from a connected server."""
        try:
            result = await conn.send_request("prompts/list", {}, timeout=15)
            return result.get("prompts", [])
        except Exception as exc:
            logger.warning("Failed to fetch prompts from '%s': %s", server_name, exc)
            return []

    # ------------------------------------------------------------------
    # Tool Invocation
    # ------------------------------------------------------------------

    async def call_tool(
        self,
        server_name: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Any:
        """Call a tool on a connected MCP server.

        Args:
            server_name: The logical name of the connected server.
            tool_name: Name of the tool to invoke.
            arguments: Parameters to pass to the tool.
            timeout: Override the default call timeout.

        Returns:
            The tool's result content (typically a list of content blocks).

        Raises:
            ConnectionError: If the server is not connected.
            MCPError: If the server returns an error.
            TimeoutError: If the call times out.
        """
        conn = self._connections.get(server_name)
        if conn is None:
            raise ConnectionError(
                f"No connection to MCP server '{server_name}'. "
                f"Call connect_stdio() or connect_sse() first."
            )

        server = self._servers.get(server_name)
        if server is None or server.status != "connected":
            # Attempt reconnection
            reconnected = await self._try_reconnect(server_name)
            if not reconnected:
                raise ConnectionError(
                    f"MCP server '{server_name}' is not connected and "
                    f"reconnection failed"
                )
            conn = self._connections[server_name]

        effective_timeout = timeout or STDIO_CALL_TIMEOUT
        arguments = arguments or {}

        logger.info(
            "Calling tool '%s' on server '%s' with args: %s",
            tool_name,
            server_name,
            list(arguments.keys()),
        )

        try:
            result = await conn.send_request(
                "tools/call",
                {
                    "name": tool_name,
                    "arguments": arguments,
                },
                timeout=effective_timeout,
            )
            logger.debug(
                "Tool '%s' on '%s' returned: %s",
                tool_name,
                server_name,
                _truncate(str(result), 500),
            )
            return result
        except TimeoutError:
            logger.error(
                "Tool '%s' on '%s' timed out after %ss",
                tool_name,
                server_name,
                effective_timeout,
            )
            raise
        except MCPError:
            raise
        except Exception as exc:
            logger.error(
                "Error calling tool '%s' on '%s': %s",
                tool_name,
                server_name,
                exc,
            )
            # Mark server as errored
            if server:
                server.status = "error"
            raise ConnectionError(
                f"Tool call failed: {exc}"
            ) from exc

    # ------------------------------------------------------------------
    # Resources
    # ------------------------------------------------------------------

    async def list_resources(self, server_name: str) -> list[dict[str, Any]]:
        """List resources from a connected MCP server."""
        conn = self._connections.get(server_name)
        if conn is None:
            raise ConnectionError(f"No connection to server '{server_name}'")
        result = await conn.send_request("resources/list", {}, timeout=15)
        resources = result.get("resources", [])
        # Update cached list
        server = self._servers.get(server_name)
        if server:
            server.resources = resources
        return resources

    async def read_resource(
        self, server_name: str, uri: str
    ) -> dict[str, Any]:
        """Read a specific resource from a connected MCP server."""
        conn = self._connections.get(server_name)
        if conn is None:
            raise ConnectionError(f"No connection to server '{server_name}'")
        return await conn.send_request(
            "resources/read", {"uri": uri}, timeout=30
        )

    # ------------------------------------------------------------------
    # Prompts
    # ------------------------------------------------------------------

    async def list_prompts(self, server_name: str) -> list[dict[str, Any]]:
        """List prompts from a connected MCP server."""
        conn = self._connections.get(server_name)
        if conn is None:
            raise ConnectionError(f"No connection to server '{server_name}'")
        result = await conn.send_request("prompts/list", {}, timeout=15)
        prompts = result.get("prompts", [])
        server = self._servers.get(server_name)
        if server:
            server.prompts = prompts
        return prompts

    async def get_prompt(
        self,
        server_name: str,
        prompt_name: str,
        arguments: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Get a specific prompt with optional arguments."""
        conn = self._connections.get(server_name)
        if conn is None:
            raise ConnectionError(f"No connection to server '{server_name}'")
        params: dict[str, Any] = {"name": prompt_name}
        if arguments:
            params["arguments"] = arguments
        return await conn.send_request("prompts/get", params, timeout=30)

    # ------------------------------------------------------------------
    # Disconnection
    # ------------------------------------------------------------------

    async def disconnect(self, server_name: str) -> None:
        """Disconnect a specific MCP server."""
        await self._safe_disconnect(server_name)

    async def disconnect_all(self) -> None:
        """Disconnect all connected MCP servers."""
        names = list(self._connections.keys())
        logger.info("Disconnecting %d MCP servers: %s", len(names), names)
        for name in names:
            await self._safe_disconnect(name)

    async def _safe_disconnect(self, server_name: str) -> None:
        """Disconnect a server, swallowing errors."""
        conn = self._connections.pop(server_name, None)
        server = self._servers.get(server_name)
        if conn is not None:
            try:
                await conn.close()
            except Exception as exc:
                logger.warning(
                    "Error disconnecting server '%s': %s", server_name, exc
                )
        if server is not None:
            server.status = "disconnected"
            server.tools.clear()
            server.resources.clear()
            server.prompts.clear()

    # ------------------------------------------------------------------
    # Reconnection
    # ------------------------------------------------------------------

    async def _try_reconnect(self, server_name: str) -> bool:
        """Attempt to reconnect a server using its stored config.

        Uses exponential backoff with a maximum retry count.
        """
        server = self._servers.get(server_name)
        if server is None:
            return False

        if server._reconnect_attempts >= RECONNECT_MAX_RETRIES:
            logger.warning(
                "Server '%s' exceeded max reconnection attempts (%d)",
                server_name,
                RECONNECT_MAX_RETRIES,
            )
            return False

        delay = min(
            RECONNECT_BASE_DELAY * (2 ** server._reconnect_attempts),
            RECONNECT_MAX_DELAY,
        )
        server._reconnect_attempts += 1

        logger.info(
            "Reconnecting server '%s' (attempt %d/%d, delay=%.1fs)",
            server_name,
            server._reconnect_attempts,
            RECONNECT_MAX_RETRIES,
            delay,
        )
        await asyncio.sleep(delay)

        try:
            if server.transport_type == "stdio" and server.command:
                await self.connect_stdio(
                    server_name,
                    server.command,
                    server.args,
                    server.env,
                )
            elif server.transport_type == "sse" and server.url:
                await self.connect_sse(server_name, server.url)
            else:
                return False

            server._reconnect_attempts = 0
            return True
        except Exception as exc:
            logger.warning(
                "Reconnection attempt %d for '%s' failed: %s",
                server._reconnect_attempts,
                server_name,
                exc,
            )
            server.status = "error"
            return False

    # ------------------------------------------------------------------
    # Tool Queries
    # ------------------------------------------------------------------

    def get_all_tools(self) -> list[MCPTool]:
        """Return all tools from all connected servers."""
        tools: list[MCPTool] = []
        for server in self._servers.values():
            if server.status == "connected":
                tools.extend(server.tools)
        return tools

    def get_tools_schema(self) -> list[dict[str, Any]]:
        """Return all MCP tools in OpenAI function-calling format.

        This is the key integration point: the returned list can be
        appended directly to the agent's ``tools`` parameter when
        constructing LLM API calls, making MCP tools indistinguishable
        from native tools.
        """
        return [tool.to_openai_schema() for tool in self.get_all_tools()]

    def get_server_tools(self, server_name: str) -> list[MCPTool]:
        """Return tools from a specific server."""
        server = self._servers.get(server_name)
        if server and server.status == "connected":
            return list(server.tools)
        return []

    def get_server(self, server_name: str) -> MCPServer | None:
        """Return the server descriptor, or None if not registered."""
        return self._servers.get(server_name)

    def list_servers(self) -> list[MCPServer]:
        """Return all registered servers (connected or not)."""
        return list(self._servers.values())

    def list_connected_servers(self) -> list[MCPServer]:
        """Return only connected servers."""
        return [
            s for s in self._servers.values() if s.status == "connected"
        ]

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    async def health_check(self, server_name: str) -> dict[str, Any]:
        """Check if a server is alive by sending a ping.

        Returns a dict with ``status``, ``latency_ms``, and ``error``.
        """
        conn = self._connections.get(server_name)
        server = self._servers.get(server_name)

        if conn is None or server is None:
            return {
                "server": server_name,
                "status": "disconnected",
                "latency_ms": None,
                "error": "No connection exists",
            }

        t0 = time.monotonic()
        try:
            await conn.send_request("ping", {}, timeout=10)
            latency = (time.monotonic() - t0) * 1000
            return {
                "server": server_name,
                "status": "healthy",
                "latency_ms": round(latency, 1),
                "error": None,
            }
        except TimeoutError:
            return {
                "server": server_name,
                "status": "timeout",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "error": "Ping timed out",
            }
        except Exception as exc:
            server.status = "error"
            return {
                "server": server_name,
                "status": "error",
                "latency_ms": round((time.monotonic() - t0) * 1000, 1),
                "error": str(exc),
            }

    async def health_check_all(self) -> dict[str, dict[str, Any]]:
        """Run health checks on all registered servers."""
        results = {}
        for name in self._servers:
            results[name] = await self.health_check(name)
        return results

    # ------------------------------------------------------------------
    # Refresh tool lists
    # ------------------------------------------------------------------

    async def refresh_tools(self, server_name: str) -> int:
        """Re-fetch the tool list from a connected server.

        Returns the updated tool count.
        """
        conn = self._connections.get(server_name)
        server = self._servers.get(server_name)
        if conn is None or server is None:
            raise ConnectionError(f"No connection to server '{server_name}'")
        tools = await self._fetch_tools(server_name, conn, MCP_PROTOCOL_VERSION)
        server.tools = tools
        return len(tools)

    async def refresh_all_tools(self) -> dict[str, int]:
        """Refresh tool lists from all connected servers."""
        counts: dict[str, int] = {}
        for name, conn in list(self._connections.items()):
            server = self._servers.get(name)
            if server and server.status == "connected":
                try:
                    counts[name] = await self.refresh_tools(name)
                except Exception as exc:
                    logger.warning(
                        "Failed to refresh tools for '%s': %s", name, exc
                    )
                    counts[name] = -1
        return counts


# ===================================================================
# Helpers
# ===================================================================


def _truncate(s: str, max_len: int = 200) -> str:
    """Truncate a string for logging."""
    if len(s) <= max_len:
        return s
    return s[: max_len - 3] + "..."
