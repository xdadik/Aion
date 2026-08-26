"""Aion Hand as an MCP Server.

Exposes Aion's own tools to OTHER MCP clients (Hermes, OpenClaw, Claude
Desktop, etc.) over stdio using the Model Context Protocol (JSON-RPC 2.0).

This means: any MCP-compatible agent can use Aion's 25+ built-in tools
(web_search, read_file, execute_code, etc.) plus any tools registered
via plugins — without writing any integration code.

Usage (start as subprocess from another agent):
    {
      "name": "aion-mcp",
      "transport": "stdio",
      "command": "python",
      "args": ["-m", "aion_core.mcp.server"]
    }

Or programmatically:
    from aion_core.mcp.server import MCPServer
    server = MCPServer(tool_registry=my_registry)
    await server.run_stdio()
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger("aion_hand.mcp.server")


# ---------------------------------------------------------------------------
# JSON-RPC 2.0 types
# ---------------------------------------------------------------------------

@dataclass
class JSONRPCRequest:
    """A parsed JSON-RPC 2.0 request."""
    id: int | str | None
    method: str
    params: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "JSONRPCRequest":
        return cls(
            id=data.get("id"),
            method=str(data.get("method", "")),
            params=data.get("params") or {},
        )


@dataclass
class JSONRPCResponse:
    """A JSON-RPC 2.0 response."""
    id: int | str | None
    result: Any = None
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"jsonrpc": "2.0", "id": self.id}
        if self.error is not None:
            d["error"] = self.error
        else:
            d["result"] = self.result
        return d


# ---------------------------------------------------------------------------
# MCP Server
# ---------------------------------------------------------------------------

class MCPServer:
    """Aion's MCP server. Exposes a ToolRegistry to MCP clients over stdio.

    Implements the MCP protocol's `initialize`, `tools/list`, and
    `tools/call` methods. Other MCP methods return a "not implemented"
    error — they're not needed for the core tool-use flow.
    """

    PROTOCOL_VERSION = "2024-11-05"
    SERVER_INFO = {
        "name": "aion-hand-mcp",
        "version": "0.1.0",
    }
    CAPABILITIES = {
        "tools": {"listChanged": False},
    }

    def __init__(self, tool_registry: Any = None, *, name: str = "aion-hand") -> None:
        self.name = name
        self._tool_registry = tool_registry
        self._initialized = False

    def _get_registry(self) -> Any:
        """Lazily create a default tool registry if none was provided."""
        if self._tool_registry is not None:
            return self._tool_registry
        try:
            from aion_core.tools.registry import ToolRegistry
            self._tool_registry = ToolRegistry()
            return self._tool_registry
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Could not create default ToolRegistry: {exc}")
            return None

    # ------------------------------------------------------------------
    #  Protocol methods
    # ------------------------------------------------------------------

    async def handle_request(self, request: JSONRPCRequest) -> JSONRPCResponse:
        """Dispatch a JSON-RPC request to the appropriate handler."""
        method = request.method
        try:
            if method == "initialize":
                return self._handle_initialize(request)
            if method == "initialized" or method == "notifications/initialized":
                # Notification — no response needed, but we return one anyway for safety
                self._initialized = True
                return JSONRPCResponse(id=request.id, result={})
            if method == "tools/list":
                return await self._handle_tools_list(request)
            if method == "tools/call":
                return await self._handle_tools_call(request)
            if method == "ping":
                return JSONRPCResponse(id=request.id, result={})
            return JSONRPCResponse(
                id=request.id,
                error={"code": -32601, "message": f"Method not found: {method}"},
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(f"Error handling {method}: {exc}")
            return JSONRPCResponse(
                id=request.id,
                error={"code": -32603, "message": f"Internal error: {exc}"},
            )

    def _handle_initialize(self, request: JSONRPCRequest) -> JSONRPCResponse:
        return JSONRPCResponse(
            id=request.id,
            result={
                "protocolVersion": self.PROTOCOL_VERSION,
                "capabilities": self.CAPABILITIES,
                "serverInfo": self.SERVER_INFO,
            },
        )

    async def _handle_tools_list(self, request: JSONRPCRequest) -> JSONRPCResponse:
        reg = self._get_registry()
        if reg is None:
            return JSONRPCResponse(id=request.id, result={"tools": []})

        tools_list: list[dict[str, Any]] = []
        try:
            for tool in reg.list_tools():
                tools_list.append(self._tool_to_mcp_schema(tool))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Could not list tools: {exc}")

        return JSONRPCResponse(id=request.id, result={"tools": tools_list})

    async def _handle_tools_call(self, request: JSONRPCRequest) -> JSONRPCResponse:
        reg = self._get_registry()
        if reg is None:
            return JSONRPCResponse(
                id=request.id,
                error={"code": -32603, "message": "No tool registry available"},
            )

        params = request.params
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if not name:
            return JSONRPCResponse(
                id=request.id,
                error={"code": -32602, "message": "Missing 'name' in params"},
            )

        try:
            result = await reg.execute(name, **arguments)
            # MCP expects {"content": [{"type": "text", "text": "..."}], "isError": bool}
            text = ""
            if hasattr(result, "output"):
                text = str(result.output)
            elif hasattr(result, "result"):
                text = str(result.result)
            elif isinstance(result, dict):
                text = result.get("output") or result.get("result") or json.dumps(result, default=str)
            else:
                text = str(result)
            return JSONRPCResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": text}], "isError": False},
            )
        except Exception as exc:  # noqa: BLE001
            return JSONRPCResponse(
                id=request.id,
                result={"content": [{"type": "text", "text": f"Error: {exc}"}], "isError": True},
            )

    # ------------------------------------------------------------------
    #  Schema
    # ------------------------------------------------------------------

    def _tool_to_mcp_schema(self, tool: Any) -> dict[str, Any]:
        """Convert an Aion Tool to the MCP tool schema."""
        # Aion's Tool has: name, description, parameters (list of ToolParameter),
        # toolset, requires_approval, timeout
        parameters = getattr(tool, "parameters", []) or []
        properties: dict[str, Any] = {}
        required: list[str] = []
        for p in parameters:
            prop: dict[str, Any] = {"type": p.type if hasattr(p, "type") else "string"}
            if hasattr(p, "description") and p.description:
                prop["description"] = p.description
            if hasattr(p, "default") and p.default is not None:
                prop["default"] = p.default
            name = getattr(p, "name", "arg")
            properties[name] = prop
            if getattr(p, "required", False):
                required.append(name)
        return {
            "name": getattr(tool, "name", "unnamed"),
            "description": getattr(tool, "description", "") or "",
            "inputSchema": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }

    # ------------------------------------------------------------------
    #  Stdio transport
    # ------------------------------------------------------------------

    async def run_stdio(self) -> None:
        """Main stdio loop. Reads JSON-RPC from stdin, writes to stdout."""
        logger.info(f"MCP server '{self.name}' starting on stdio")
        reader = asyncio.StreamReader()
        protocol = asyncio.StreamReaderProtocol(reader)
        await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin)

        while True:
            try:
                line = await reader.readline()
                if not line:
                    break  # EOF
                line_text = line.decode("utf-8", errors="replace").strip()
                if not line_text:
                    continue
                try:
                    data = json.loads(line_text)
                except json.JSONDecodeError as exc:
                    logger.warning(f"Invalid JSON: {exc}")
                    continue
                request = JSONRPCRequest.from_dict(data)
                response = await self.handle_request(request)
                # Notifications (no id) don't get a response
                if request.id is not None:
                    out = json.dumps(response.to_dict()) + "\n"
                    sys.stdout.write(out)
                    sys.stdout.flush()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.exception(f"Error in stdio loop: {exc}")
                break

        logger.info(f"MCP server '{self.name}' shutting down")


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    """`python -m aion_core.mcp.server` entry point."""
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    server = MCPServer()
    await server.run_stdio()


if __name__ == "__main__":
    asyncio.run(_main())


__all__ = ["MCPServer", "JSONRPCRequest", "JSONRPCResponse"]
