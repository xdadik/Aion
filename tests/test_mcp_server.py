"""Tests for the MCP Server module."""

from __future__ import annotations

import json

import pytest

from aion_core.mcp.server import JSONRPCRequest, JSONRPCResponse, MCPServer


class TestJSONRPCTypes:
    """JSON-RPC 2.0 dataclass behaviour."""

    def test_request_from_dict(self):
        req = JSONRPCRequest.from_dict({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {},
        })
        assert req.id == 1
        assert req.method == "initialize"

    def test_response_to_dict_with_result(self):
        resp = JSONRPCResponse(id=1, result={"hello": "world"})
        d = resp.to_dict()
        assert d["jsonrpc"] == "2.0"
        assert d["id"] == 1
        assert d["result"] == {"hello": "world"}
        assert "error" not in d

    def test_response_to_dict_with_error(self):
        resp = JSONRPCResponse(id=1, error={"code": -32601, "message": "not found"})
        d = resp.to_dict()
        assert "error" in d
        assert "result" not in d
        assert d["error"]["code"] == -32601


class TestMCPServerInitialize:
    """initialize handshake."""

    @pytest.mark.asyncio
    async def test_initialize_returns_protocol_info(self):
        server = MCPServer()
        req = JSONRPCRequest(id=1, method="initialize")
        resp = await server.handle_request(req)
        assert resp.error is None
        result = resp.result
        assert "protocolVersion" in result
        assert "capabilities" in result
        assert "serverInfo" in result
        assert result["serverInfo"]["name"] == "aion-hand-mcp"

    @pytest.mark.asyncio
    async def test_initialized_notification_sets_flag(self):
        server = MCPServer()
        assert server._initialized is False
        req = JSONRPCRequest(id=None, method="notifications/initialized")
        resp = await server.handle_request(req)
        assert server._initialized is True


class TestMCPServerToolsList:
    """tools/list endpoint."""

    @pytest.mark.asyncio
    async def test_tools_list_returns_list(self):
        # Use a mock registry
        from unittest.mock import MagicMock
        mock_tool = MagicMock()
        mock_tool.name = "test_tool"
        mock_tool.description = "A test"
        mock_tool.parameters = []

        mock_reg = MagicMock()
        mock_reg.list_tools.return_value = [mock_tool]

        server = MCPServer(tool_registry=mock_reg)
        req = JSONRPCRequest(id=2, method="tools/list")
        resp = await server.handle_request(req)
        assert resp.error is None
        tools = resp.result["tools"]
        assert len(tools) == 1
        assert tools[0]["name"] == "test_tool"
        assert "inputSchema" in tools[0]

    @pytest.mark.asyncio
    async def test_tools_list_with_no_registry_returns_empty(self):
        server = MCPServer(tool_registry=None)
        req = JSONRPCRequest(id=3, method="tools/list")
        resp = await server.handle_request(req)
        assert resp.error is None
        assert resp.result["tools"] == []


class TestMCPServerToolsCall:
    """tools/call endpoint."""

    @pytest.mark.asyncio
    async def test_tools_call_executes_tool(self):
        from unittest.mock import AsyncMock, MagicMock
        mock_reg = MagicMock()
        mock_reg.execute = AsyncMock(return_value={"output": "tool result text"})

        server = MCPServer(tool_registry=mock_reg)
        req = JSONRPCRequest(
            id=4,
            method="tools/call",
            params={"name": "test_tool", "arguments": {"x": 1}},
        )
        resp = await server.handle_request(req)
        assert resp.error is None
        assert resp.result["isError"] is False
        assert "tool result text" in resp.result["content"][0]["text"]
        mock_reg.execute.assert_awaited_once_with("test_tool", x=1)

    @pytest.mark.asyncio
    async def test_tools_call_missing_name_returns_error(self):
        from unittest.mock import MagicMock
        mock_reg = MagicMock()
        server = MCPServer(tool_registry=mock_reg)
        req = JSONRPCRequest(id=5, method="tools/call", params={})
        resp = await server.handle_request(req)
        assert resp.error is not None
        assert resp.error["code"] == -32602

    @pytest.mark.asyncio
    async def test_tools_call_tool_raises_returns_iserror(self):
        from unittest.mock import AsyncMock, MagicMock
        mock_reg = MagicMock()
        mock_reg.execute = AsyncMock(side_effect=RuntimeError("boom"))
        server = MCPServer(tool_registry=mock_reg)
        req = JSONRPCRequest(id=6, method="tools/call", params={"name": "broken", "arguments": {}})
        resp = await server.handle_request(req)
        assert resp.result["isError"] is True
        assert "boom" in resp.result["content"][0]["text"]


class TestMCPServerMethodNotFound:
    """Unknown methods return -32601."""

    @pytest.mark.asyncio
    async def test_unknown_method_returns_error(self):
        server = MCPServer()
        req = JSONRPCRequest(id=7, method="some/unknown/method")
        resp = await server.handle_request(req)
        assert resp.error is not None
        assert resp.error["code"] == -32601

    @pytest.mark.asyncio
    async def test_ping_returns_empty_result(self):
        server = MCPServer()
        req = JSONRPCRequest(id=8, method="ping")
        resp = await server.handle_request(req)
        assert resp.error is None
        assert resp.result == {}
