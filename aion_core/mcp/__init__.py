"""
Aion Hand - MCP (Model Context Protocol) Client Runtime
==========================================================
Complete MCP client runtime providing external tool integration.

Modules:
    client   - MCPClient: JSON-RPC 2.0 wire protocol (stdio + SSE transports)
    bridge   - MCPBridge: integrates MCP tools into Aion Hand's ToolRegistry
    config   - MCPConfig: server configuration management with defaults
    registry - MCPToolRegistry: discovery, search, and statistics

Quick start::

    from aion_core.mcp import MCPClient, MCPBridge, MCPConfig, MCPToolRegistry

    # Load configuration
    config = MCPConfig()
    await config.load()

    # Connect to servers
    client = MCPClient()
    for server_cfg in config.get_auto_connect_servers():
        if server_cfg.transport == "stdio":
            await client.connect_stdio(
                server_cfg.name,
                server_cfg.command,
                server_cfg.args,
                server_cfg.env,
            )
        elif server_cfg.transport == "sse":
            await client.connect_sse(server_cfg.name, server_cfg.url)

    # Bridge MCP tools into native registry
    bridge = MCPBridge(client, tool_registry)
    await bridge.bridge_all()

    # All MCP tools are now available as native tools!
"""

from aion_core.mcp.client import (
    MCPClient,
    MCPTool,
    MCPServer,
    MCPError,
    _StdioConnection,
    _SSEConnection,
)
from aion_core.mcp.bridge import MCPBridge
from aion_core.mcp.config import (
    MCPServerConfig,
    MCPConfig,
    _get_default_servers,
)
from aion_core.mcp.registry import MCPToolRegistry

__all__ = [
    # Client
    "MCPClient",
    "MCPTool",
    "MCPServer",
    "MCPError",
    # Bridge
    "MCPBridge",
    # Config
    "MCPServerConfig",
    "MCPConfig",
    # Registry
    "MCPToolRegistry",
]

__version__ = "0.1.0"
