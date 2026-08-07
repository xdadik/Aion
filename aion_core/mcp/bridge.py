#!/usr/bin/env python3
"""
Aion Hand - MCP Bridge
=======================
Bridges MCP server tools into Aion Hand's native :class:`ToolRegistry`.

After connecting to an MCP server via :class:`MCPClient`, use this bridge
to register each MCP tool as a first-class :class:`Tool` in the native
registry. The handler for each bridged tool simply forwards the call to
the MCP server via ``mcp_client.call_tool()``.

This means that from the agent's perspective, MCP tools are indistinguishable
from built-in tools — they show up in tool lists, can be auto-approved or
require approval, and participate in the same execution pipeline.

Usage::

    client = MCPClient()
    await client.connect_stdio("filesystem", "npx", ["-y", "@anthropic/mcp-filesystem", "/tmp"])

    bridge = MCPBridge(client, tool_registry)
    count = await bridge.bridge_server("filesystem")
    print(f"Bridged {count} tools from filesystem server")

    # The tools now appear in tool_registry and are callable by the agent
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from aion_core.mcp.client import MCPClient, MCPTool

logger = logging.getLogger("aion_hand.mcp.bridge")

# Prefix added to bridged tool names to avoid collisions with built-in tools.
# The full qualified name is ``mcp__<server>__<tool>`` while the display
# name (used for LLM matching) retains the original tool name.
BRIDGE_PREFIX = "mcp__"
BRIDGE_SEPARATOR = "__"


class MCPBridge:
    """Bridges MCP server tools into Aion Hand's native :class:`ToolRegistry`.

    Attributes:
        _client: The MCP client used to communicate with servers.
        _registry: Aion Hand's native tool registry.
        _bridged_tools: Maps qualified name ``mcp__<server>__<tool>`` → server name.
        _qualified_to_original: Maps qualified name → original tool name.
        _original_to_qualified: Maps ``<server>:<tool>`` → qualified name.
    """

    def __init__(
        self,
        mcp_client: MCPClient,
        tool_registry: Any,
    ) -> None:
        """
        Args:
            mcp_client: The :class:`MCPClient` instance with connected servers.
            tool_registry: An instance of :class:`aion_core.tools.registry.ToolRegistry`.
        """
        self._client = mcp_client
        self._registry = tool_registry
        self._bridged_tools: Dict[str, str] = {}
        self._qualified_to_original: Dict[str, str] = {}
        self._original_to_qualified: Dict[str, str] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def bridge_server(self, server_name: str) -> int:
        """Bridge all tools from a specific MCP server into the registry.

        For each tool exposed by the server, this method:
        1. Creates a unique qualified name (``mcp__<server>__<tool>``).
        2. Builds a :class:`Tool` with the original description and schema.
        3. The handler calls ``mcp_client.call_tool(server, tool, args)``.
        4. Registers the tool in the native registry.

        Args:
            server_name: The logical name of a connected MCP server.

        Returns:
            The number of tools successfully bridged.

        Raises:
            ConnectionError: If the server is not connected.
            ValueError: If the registry doesn't support the expected API.
        """
        server = self._client.get_server(server_name)
        if server is None or server.status != "connected":
            raise ConnectionError(
                f"Cannot bridge server '{server_name}': not connected"
            )

        tools = self._client.get_server_tools(server_name)
        if not tools:
            logger.info("Server '%s' has no tools to bridge", server_name)
            return 0

        bridged = 0
        for tool in tools:
            try:
                self._register_bridged_tool(server_name, tool)
                bridged += 1
            except Exception as exc:
                logger.error(
                    "Failed to bridge tool '%s' from '%s': %s",
                    tool.name,
                    server_name,
                    exc,
                    exc_info=True,
                )

        logger.info(
            "Bridged %d/%d tools from MCP server '%s'",
            bridged,
            len(tools),
            server_name,
        )
        return bridged

    async def bridge_all(self) -> Dict[str, int]:
        """Bridge tools from all connected MCP servers.

        Returns:
            A dict mapping server name to the number of tools bridged.
        """
        results: Dict[str, int] = {}
        for server in self._client.list_connected_servers():
            try:
                count = await self.bridge_server(server.name)
                results[server.name] = count
            except Exception as exc:
                logger.error(
                    "Failed to bridge server '%s': %s", server.name, exc
                )
                results[server.name] = -1
        return results

    async def unbridge_server(self, server_name: str) -> int:
        """Remove all bridged tools for a specific server from the registry.

        Returns:
            The number of tools removed.
        """
        to_remove = [
            qname
            for qname, sname in self._bridged_tools.items()
            if sname == server_name
        ]

        removed = 0
        for qname in to_remove:
            try:
                if self._registry_has_method("unregister"):
                    self._registry.unregister(qname)
                elif self._registry_has_method("remove"):
                    self._registry.remove(qname)
                self._bridged_tools.pop(qname, None)
                self._qualified_to_original.pop(qname, None)
                removed += 1
            except Exception as exc:
                logger.warning(
                    "Failed to unbridge tool '%s': %s", qname, exc
                )

        # Clean up mapping
        keys_to_remove = [
            k for k, v in self._original_to_qualified.items()
            if v in to_remove
        ]
        for k in keys_to_remove:
            del self._original_to_qualified[k]

        logger.info(
            "Unbridged %d tools from server '%s'", removed, server_name
        )
        return removed

    async def unbridge_all(self) -> int:
        """Remove all bridged tools from the registry.

        Returns:
            Total number of tools removed.
        """
        total = 0
        for server_name in list(self._bridged_tools.values()):
            total += await self.unbridge_server(server_name)
        return total

    def get_bridged_tools(self) -> Dict[str, str]:
        """Return mapping of qualified tool name → server name."""
        return dict(self._bridged_tools)

    def get_bridged_tool_names(self) -> List[str]:
        """Return list of all bridged qualified tool names."""
        return list(self._bridged_tools.keys())

    def is_tool_bridged(self, qualified_name: str) -> bool:
        """Check if a qualified tool name is currently bridged."""
        return qualified_name in self._bridged_tools

    def get_server_for_tool(self, qualified_name: str) -> Optional[str]:
        """Get the server name that owns a bridged tool."""
        return self._bridged_tools.get(qualified_name)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _register_bridged_tool(
        self, server_name: str, mcp_tool: MCPTool
    ) -> None:
        """Create a native Tool from an MCPTool and register it."""
        qualified_name = self._make_qualified_name(server_name, mcp_tool.name)

        # Build description with server provenance
        description = mcp_tool.description
        if not description:
            description = f"MCP tool '{mcp_tool.name}' from server '{server_name}'"
        description = f"[MCP:{server_name}] {description}"

        # Build the async handler that calls the MCP server
        client = self._client
        _server = server_name
        _tool_name = mcp_tool.name

        async def _tool_handler(**kwargs) -> Any:
            """Bridge handler: forwards call to MCP server."""
            result = await client.call_tool(_server, _tool_name, kwargs)
            return result

        # Attempt to construct a Tool object using the registry's Tool class
        try:
            # Try importing Tool from the tools registry
            from aion_core.tools.registry import Tool

            # Convert MCP input_schema to ToolParameter list
            params = self._schema_to_parameters(mcp_tool.input_schema)

            tool = Tool(
                name=qualified_name,
                description=description,
                parameters=params,
                handler=_tool_handler,
                toolset=f"mcp_{server_name}",
                requires_approval=True,  # MCP tools require approval by default
                timeout=120,
                dangerous=False,
            )
            self._registry.register(tool)

        except (ImportError, TypeError) as exc:
            # Fallback: register using the registry's generic register method
            # if it accepts (name, handler, ...) positional args
            logger.debug(
                "Using fallback registration for tool '%s': %s",
                qualified_name,
                exc,
            )
            self._registry.register_tool(
                name=qualified_name,
                description=description,
                handler=_tool_handler,
                schema=mcp_tool.input_schema,
            )

        # Track the mapping
        self._bridged_tools[qualified_name] = server_name
        self._qualified_to_original[qualified_name] = mcp_tool.name
        self._original_to_qualified[
            f"{server_name}:{mcp_tool.name}"
        ] = qualified_name

        logger.debug(
            "Bridged tool: %s -> %s (server: %s)",
            mcp_tool.name,
            qualified_name,
            server_name,
        )

    def _make_qualified_name(self, server_name: str, tool_name: str) -> str:
        """Build a qualified tool name that avoids namespace collisions.

        Format: ``mcp__<server_name>__<tool_name>``
        Both components are sanitized to contain only alphanumeric chars
        and underscores.
        """
        safe_server = _sanitize_name(server_name)
        safe_tool = _sanitize_name(tool_name)
        return f"{BRIDGE_PREFIX}{safe_server}{BRIDGE_SEPARATOR}{safe_tool}"

    @staticmethod
    def _schema_to_parameters(
        input_schema: Dict[str, Any]
    ) -> List[Any]:
        """Convert a JSON Schema input_schema to ToolParameter list.

        Handles the standard MCP tool schema format:
        ``{"type": "object", "properties": {...}, "required": [...]}``
        """
        try:
            from aion_core.tools.registry import ToolParameter
        except ImportError:
            return []

        params = []
        properties = input_schema.get("properties", {})
        required = set(input_schema.get("required", []))

        for param_name, param_schema in properties.items():
            param_type = param_schema.get("type", "string")
            param_desc = param_schema.get("description", "")
            param_required = param_name in required
            param_default = param_schema.get("default")
            param_enum = param_schema.get("enum")

            # Map JSON Schema types to ToolParameter types
            type_map = {
                "string": "string",
                "integer": "integer",
                "number": "number",
                "boolean": "boolean",
                "array": "array",
                "object": "object",
                "null": "string",
            }
            mapped_type = type_map.get(param_type, "string")

            params.append(
                ToolParameter(
                    name=param_name,
                    type=mapped_type,
                    description=param_desc,
                    required=param_required,
                    default=param_default,
                    enum=param_enum,
                )
            )

        return params

    def _registry_has_method(self, method_name: str) -> bool:
        """Check if the registry has a specific method."""
        return callable(getattr(self._registry, method_name, None))


# ===================================================================
# Helpers
# ===================================================================


def _sanitize_name(name: str) -> str:
    """Sanitize a name to contain only alphanumeric chars and underscores.

    Preserves readability by collapsing runs of non-alphanumeric chars
    into a single underscore.
    """
    import re
    sanitized = re.sub(r"[^a-zA-Z0-9]", "_", name)
    sanitized = re.sub(r"_+", "_", sanitized)
    return sanitized.strip("_")
