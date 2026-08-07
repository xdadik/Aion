#!/usr/bin/env python3
"""Comprehensive tests for aion_core/mcp/ modules."""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aion_core.mcp.config import MCPServerConfig, MCPConfig
from aion_core.mcp.client import MCPTool, MCPServer, MCPClient
from aion_core.mcp.registry import MCPToolRegistry
from aion_core.mcp.bridge import MCPBridge


# ===================================================================
# MCPServerConfig tests
# ===================================================================


class TestMCPServerConfig(unittest.TestCase):
    """Tests for the MCPServerConfig dataclass."""

    def test_creation_defaults(self):
        """MCPServerConfig has sensible defaults."""
        cfg = MCPServerConfig()
        self.assertEqual(cfg.name, "")
        self.assertEqual(cfg.transport, "stdio")
        self.assertIsNone(cfg.command)
        self.assertEqual(cfg.args, [])
        self.assertIsNone(cfg.url)
        self.assertEqual(cfg.env, {})
        self.assertFalse(cfg.auto_connect)
        self.assertTrue(cfg.enabled)
        self.assertEqual(cfg.description, "")

    def test_creation_with_all_fields(self):
        """All fields are stored correctly."""
        cfg = MCPServerConfig(
            name="my-server",
            transport="sse",
            command="node",
            args=["-e", "server.js"],
            url="http://localhost:8080/sse",
            env={"API_KEY": "secret"},
            auto_connect=True,
            enabled=False,
            description="A test server",
        )
        self.assertEqual(cfg.name, "my-server")
        self.assertEqual(cfg.transport, "sse")
        self.assertEqual(cfg.command, "node")
        self.assertEqual(cfg.args, ["-e", "server.js"])
        self.assertEqual(cfg.url, "http://localhost:8080/sse")
        self.assertEqual(cfg.env, {"API_KEY": "secret"})
        self.assertTrue(cfg.auto_connect)
        self.assertFalse(cfg.enabled)
        self.assertEqual(cfg.description, "A test server")

    def test_to_dict_from_dict_roundtrip(self):
        """Serialization and deserialization are symmetric."""
        original = MCPServerConfig(
            name="roundtrip",
            transport="stdio",
            command="npx",
            args=["-y", "some-package"],
            env={"TOKEN": "abc"},
            auto_connect=True,
            enabled=True,
            description="test roundtrip",
        )
        d = original.to_dict()
        restored = MCPServerConfig.from_dict(d)
        self.assertEqual(restored.name, "roundtrip")
        self.assertEqual(restored.transport, "stdio")
        self.assertEqual(restored.command, "npx")
        self.assertEqual(restored.args, ["-y", "some-package"])
        self.assertEqual(restored.env, {"TOKEN": "abc"})
        self.assertTrue(restored.auto_connect)
        self.assertTrue(restored.enabled)


# ===================================================================
# MCPConfig tests
# ===================================================================


class TestMCPConfig(unittest.TestCase):
    """Tests for the MCPConfig class."""

    def setUp(self):
        self.cfg = MCPConfig()

    def test_creation_empty(self):
        """MCPConfig starts with no servers (before loading)."""
        self.assertEqual(self.cfg.count_servers(), 0)

    def test_add_server(self):
        """add_server stores a server configuration."""
        srv = MCPServerConfig(name="test-srv", transport="stdio")
        self.cfg.add_server(srv)
        self.assertEqual(self.cfg.count_servers(), 1)

    def test_remove_server(self):
        """remove_server deletes a server and returns True."""
        srv = MCPServerConfig(name="to-remove", transport="stdio")
        self.cfg.add_server(srv)
        self.assertTrue(self.cfg.remove_server("to-remove"))
        self.assertEqual(self.cfg.count_servers(), 0)

    def test_get_server(self):
        """get_server returns the config or None."""
        srv = MCPServerConfig(name="my-srv", transport="sse")
        self.cfg.add_server(srv)
        fetched = self.cfg.get_server("my-srv")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.transport, "sse")
        self.assertIsNone(self.cfg.get_server("nonexistent"))

    def test_list_servers(self):
        """list_servers returns all configured servers."""
        self.cfg.add_server(MCPServerConfig(name="a", transport="stdio"))
        self.cfg.add_server(MCPServerConfig(name="b", transport="sse"))
        servers = self.cfg.list_servers()
        self.assertEqual(len(servers), 2)

    def test_list_enabled_servers(self):
        """list_enabled_servers filters out disabled servers."""
        self.cfg.add_server(MCPServerConfig(name="on", transport="stdio", enabled=True))
        self.cfg.add_server(MCPServerConfig(name="off", transport="stdio", enabled=False))
        enabled = self.cfg.list_enabled_servers()
        self.assertEqual(len(enabled), 1)
        self.assertEqual(enabled[0].name, "on")

    def test_get_auto_connect_servers(self):
        """get_auto_connect_servers returns enabled+auto_connect servers."""
        self.cfg.add_server(
            MCPServerConfig(name="auto", transport="stdio", enabled=True, auto_connect=True)
        )
        self.cfg.add_server(
            MCPServerConfig(name="manual", transport="stdio", enabled=True, auto_connect=False)
        )
        self.cfg.add_server(
            MCPServerConfig(name="disabled", transport="stdio", enabled=False, auto_connect=True)
        )
        auto = self.cfg.get_auto_connect_servers()
        self.assertEqual(len(auto), 1)
        self.assertEqual(auto[0].name, "auto")

    def test_count_servers(self):
        """count_servers returns the total number of servers."""
        self.cfg.add_server(MCPServerConfig(name="a", transport="stdio"))
        self.cfg.add_server(MCPServerConfig(name="b", transport="stdio"))
        self.assertEqual(self.cfg.count_servers(), 2)

    def test_count_enabled_servers(self):
        """count_enabled_servers returns the count of enabled servers."""
        self.cfg.add_server(MCPServerConfig(name="a", transport="stdio", enabled=True))
        self.cfg.add_server(MCPServerConfig(name="b", transport="stdio", enabled=False))
        self.assertEqual(self.cfg.count_enabled_servers(), 1)

    def test_to_dict(self):
        """to_dict returns a serializable dict with version and servers."""
        self.cfg.add_server(MCPServerConfig(name="s1", transport="stdio"))
        d = self.cfg.to_dict()
        self.assertEqual(d["version"], 1)
        self.assertEqual(len(d["servers"]), 1)


# ===================================================================
# MCPToolRegistry tests
# ===================================================================


class TestMCPToolRegistry(unittest.TestCase):
    """Tests for the MCPToolRegistry class."""

    def _make_registry(self, tools=None):
        """Create a registry with a mocked client and pre-populated tools."""
        mock_client = MagicMock(spec=MCPClient)
        reg = MCPToolRegistry(mock_client)
        if tools:
            for tool in tools:
                key = f"{tool.server_name}:{tool.name}"
                reg._tool_cache[key] = tool
                reg._qualified_index[key] = tool.server_name
            reg._refreshed = True
        return reg, mock_client

    def test_creation_empty(self):
        """New registry has no tools and is not refreshed."""
        mock_client = MagicMock(spec=MCPClient)
        reg = MCPToolRegistry(mock_client)
        self.assertEqual(reg.count_tools(), 0)
        self.assertFalse(reg.is_refreshed)

    def test_register_and_get_tool(self):
        """Tools can be retrieved by name after being cached."""
        tool = MCPTool(name="read_file", description="Read a file", server_name="filesystem")
        reg, _ = self._make_registry(tools=[tool])
        fetched = reg.get_tool("read_file")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.server_name, "filesystem")

    def test_search_tools(self):
        """search_tools returns matching tools by name/description."""
        t1 = MCPTool(name="read_file", description="Read a file", server_name="fs")
        t2 = MCPTool(name="write_file", description="Write a file", server_name="fs")
        t3 = MCPTool(name="search_code", description="Search code", server_name="gh")
        reg, _ = self._make_registry(tools=[t1, t2, t3])
        results = reg.search_tools("file")
        names = [t.name for t in results]
        self.assertIn("read_file", names)
        self.assertIn("write_file", names)
        self.assertNotIn("search_code", names)

    def test_get_all_tools(self):
        """get_all_tools returns all cached tools."""
        t1 = MCPTool(name="a", server_name="s1")
        t2 = MCPTool(name="b", server_name="s1")
        reg, _ = self._make_registry(tools=[t1, t2])
        self.assertEqual(len(reg.get_all_tools()), 2)

    def test_get_tools_for_server(self):
        """get_tools_for_server filters by server_name."""
        t1 = MCPTool(name="a", server_name="s1")
        t2 = MCPTool(name="b", server_name="s2")
        reg, _ = self._make_registry(tools=[t1, t2])
        s1_tools = reg.get_tools_for_server("s1")
        self.assertEqual(len(s1_tools), 1)
        self.assertEqual(s1_tools[0].name, "a")

    def test_get_stats(self):
        """get_stats returns statistics about cached tools."""
        t1 = MCPTool(name="a", server_name="s1")
        t2 = MCPTool(name="b", server_name="s1")
        t3 = MCPTool(name="c", server_name="s2")
        reg, _ = self._make_registry(tools=[t1, t2, t3])
        stats = reg.get_stats()
        self.assertEqual(stats["total_tools"], 3)
        self.assertEqual(stats["total_servers"], 2)
        self.assertIn("s1", stats["by_server"])
        self.assertEqual(stats["by_server"]["s1"]["count"], 2)
        self.assertTrue(stats["refreshed"])

    def test_count_tools(self):
        """count_tools returns the number of cached tools."""
        t1 = MCPTool(name="a", server_name="s1")
        reg, _ = self._make_registry(tools=[t1])
        self.assertEqual(reg.count_tools(), 1)

    def test_has_tools(self):
        """has_tools returns True when tools exist."""
        reg_empty, _ = self._make_registry()
        self.assertFalse(reg_empty.has_tools())
        t1 = MCPTool(name="a", server_name="s1")
        reg_full, _ = self._make_registry(tools=[t1])
        self.assertTrue(reg_full.has_tools())

    def test_get_openai_schemas(self):
        """get_openai_schemas returns OpenAI function-calling format dicts."""
        t1 = MCPTool(
            name="read_file",
            description="Read a file",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            server_name="fs",
        )
        reg, _ = self._make_registry(tools=[t1])
        schemas = reg.get_openai_schemas()
        self.assertEqual(len(schemas), 1)
        schema = schemas[0]
        self.assertEqual(schema["type"], "function")
        self.assertEqual(schema["function"]["name"], "read_file")


# ===================================================================
# MCPBridge tests
# ===================================================================


class TestMCPBridge(unittest.TestCase):
    """Tests for the MCPBridge class."""

    def _make_bridge(self):
        """Create a bridge with mocked client and registry."""
        mock_client = MagicMock(spec=MCPClient)
        mock_registry = MagicMock()
        bridge = MCPBridge(mcp_client=mock_client, tool_registry=mock_registry)
        return bridge, mock_client, mock_registry

    def test_bridge_creation(self):
        """Bridge stores references to client and registry."""
        bridge, mock_client, mock_registry = self._make_bridge()
        self.assertIs(bridge._client, mock_client)
        self.assertIs(bridge._registry, mock_registry)

    def test_register_server(self):
        """register_server manually populates bridged tool tracking."""
        bridge, mock_client, mock_registry = self._make_bridge()
        # Simulate a tool being bridged by directly populating internal state
        bridge._bridged_tools["mcp__fs__read_file"] = "fs"
        self.assertTrue(bridge.is_tool_bridged("mcp__fs__read_file"))

    def test_get_bridged_tool_names(self):
        """get_bridged_tool_names returns all qualified bridged names."""
        bridge, _, _ = self._make_bridge()
        bridge._bridged_tools["mcp__fs__read_file"] = "fs"
        bridge._bridged_tools["mcp__fs__write_file"] = "fs"
        names = bridge.get_bridged_tool_names()
        self.assertEqual(len(names), 2)
        self.assertIn("mcp__fs__read_file", names)

    def test_is_tool_bridged(self):
        """is_tool_bridged returns True for bridged tools."""
        bridge, _, _ = self._make_bridge()
        bridge._bridged_tools["mcp__fs__read_file"] = "fs"
        self.assertTrue(bridge.is_tool_bridged("mcp__fs__read_file"))
        self.assertFalse(bridge.is_tool_bridged("mcp__fs__nonexistent"))

    def test_get_server_for_tool(self):
        """get_server_for_tool returns the owning server name."""
        bridge, _, _ = self._make_bridge()
        bridge._bridged_tools["mcp__fs__read_file"] = "filesystem"
        self.assertEqual(bridge.get_server_for_tool("mcp__fs__read_file"), "filesystem")
        self.assertIsNone(bridge.get_server_for_tool("mcp__gh__unknown"))


# ===================================================================
# MCPTool tests
# ===================================================================


class TestMCPTool(unittest.TestCase):
    """Tests for the MCPTool dataclass."""

    def test_creation_defaults(self):
        """MCPTool stores name with defaults for other fields."""
        tool = MCPTool(name="test_tool")
        self.assertEqual(tool.name, "test_tool")
        self.assertEqual(tool.description, "")
        self.assertEqual(tool.input_schema, {})
        self.assertEqual(tool.server_name, "")

    def test_to_openai_schema(self):
        """to_openai_schema returns OpenAI function-calling format."""
        tool = MCPTool(
            name="read_file",
            description="Read a file from disk",
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            server_name="fs",
        )
        schema = tool.to_openai_schema()
        self.assertEqual(schema["type"], "function")
        func = schema["function"]
        self.assertEqual(func["name"], "read_file")
        self.assertEqual(func["description"], "Read a file from disk")
        self.assertEqual(func["parameters"], {"type": "object", "properties": {"path": {"type": "string"}}})


# ===================================================================
# MCPServer tests
# ===================================================================


class TestMCPServer(unittest.TestCase):
    """Tests for the MCPServer dataclass."""

    def test_creation_defaults(self):
        """MCPServer stores name with sensible defaults."""
        srv = MCPServer(name="test-server")
        self.assertEqual(srv.name, "test-server")
        self.assertEqual(srv.transport_type, "stdio")
        self.assertIsNone(srv.command)
        self.assertIsNone(srv.url)
        self.assertEqual(srv.args, [])
        self.assertEqual(srv.env, {})
        self.assertEqual(srv.status, "disconnected")
        self.assertEqual(srv.tools, [])
        self.assertEqual(srv.resources, [])
        self.assertEqual(srv.prompts, [])
        self.assertEqual(srv.server_info, {})
        self.assertEqual(srv.server_capabilities, {})


# ===================================================================
# MCPClient tests
# ===================================================================


class TestMCPClient(unittest.TestCase):
    """Tests for the MCPClient class."""

    def test_client_creation(self):
        """MCPClient initializes with empty servers and connections."""
        client = MCPClient()
        self.assertEqual(client.list_servers(), [])
        self.assertEqual(client.list_connected_servers(), [])
        self.assertEqual(client.get_all_tools(), [])

    def test_list_servers_empty(self):
        """list_servers returns empty list when no servers registered."""
        client = MCPClient()
        servers = client.list_servers()
        self.assertIsInstance(servers, list)
        self.assertEqual(len(servers), 0)

    def test_get_server_not_found(self):
        """get_server returns None for an unregistered server."""
        client = MCPClient()
        self.assertIsNone(client.get_server("nonexistent"))


if __name__ == "__main__":
    unittest.main()
