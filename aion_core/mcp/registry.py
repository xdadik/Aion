#!/usr/bin/env python3
"""
Aion Hand - MCP Tool Registry
===============================
Discovers and manages available MCP tools from all connected servers.

Provides search, lookup, and statistical functions over the aggregate
tool set. Used by the agent loop and the bridge to understand what
external capabilities are available at any given time.

Usage::

    registry = MCPToolRegistry(mcp_client)
    await registry.refresh()

    # Search for file-related tools
    matches = registry.search_tools("file")
    for tool in matches:
        print(f"  {tool.name} ({tool.server_name}): {tool.description}")

    # Get statistics
    print(registry.get_stats())
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from aion_core.mcp.client import MCPClient, MCPTool

logger = logging.getLogger("aion_hand.mcp.registry")


class MCPToolRegistry:
    """Discovers and manages available MCP tools from all connected servers.

    Maintains an in-memory cache of all tools that is refreshed on demand.
    Provides search by name/description and per-server statistics.
    """

    def __init__(self, mcp_client: MCPClient) -> None:
        """
        Args:
            mcp_client: The MCP client with connected servers.
        """
        self._client = mcp_client
        self._tool_cache: dict[str, MCPTool] = {}
        # Key: qualified name ``server_name:tool_name``
        self._qualified_index: dict[str, str] = {}
        self._refreshed = False

    # ------------------------------------------------------------------
    # Refresh
    # ------------------------------------------------------------------

    async def refresh(self) -> int:
        """Refresh the tool list from all connected servers.

        Fetches updated tool lists from each server and rebuilds the
        cache and indexes.

        Returns:
            Total number of tools across all servers.
        """
        self._tool_cache.clear()
        self._qualified_index.clear()

        total = 0
        for server in self._client.list_connected_servers():
            try:
                count = await self._client.refresh_tools(server.name)
                total += count
                tools = self._client.get_server_tools(server.name)
                for tool in tools:
                    cache_key = f"{server.name}:{tool.name}"
                    self._tool_cache[cache_key] = tool
                    self._qualified_index[cache_key] = server.name
            except Exception as exc:
                logger.warning(
                    "Failed to refresh tools from server '%s': %s",
                    server.name,
                    exc,
                )

        self._refreshed = True
        logger.info(
            "MCP tool registry refreshed: %d tools from %d servers",
            total,
            len(self._client.list_connected_servers()),
        )
        return total

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    def search_tools(
        self,
        query: str,
        server_name: str | None = None,
        limit: int = 50,
    ) -> list[MCPTool]:
        """Search tools by name and description.

        Args:
            query: Search string (case-insensitive, substring match).
            server_name: If set, restrict search to this server.
            limit: Maximum number of results.

        Returns:
            Matching tools, sorted by relevance.
        """
        if not query:
            return list(self._tool_cache.values())[:limit]

        query_lower = query.lower()
        scored: list[tuple] = []

        for cache_key, tool in self._tool_cache.items():
            # Filter by server if specified
            if server_name and tool.server_name != server_name:
                continue

            name_lower = tool.name.lower()
            desc_lower = tool.description.lower()

            score = 0
            # Exact name match is highest
            if name_lower == query_lower:
                score = 100
            # Name starts with query
            elif name_lower.startswith(query_lower):
                score = 80
            # Name contains query
            elif query_lower in name_lower:
                score = 60
            # Description contains query
            elif query_lower in desc_lower:
                score = 40
            # Token overlap (each word in query matches somewhere)
            else:
                query_words = query_lower.split()
                matches = sum(
                    1 for w in query_words if w in name_lower or w in desc_lower
                )
                if matches > 0:
                    score = 20 * matches

            if score > 0:
                scored.append((score, cache_key, tool))

        # Sort by score descending
        scored.sort(key=lambda x: (-x[0], x[1]))

        return [item[2] for item in scored[:limit]]

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------

    def get_tool(self, name: str) -> MCPTool | None:
        """Get a tool by its unqualified name.

        If multiple servers have a tool with the same name, returns the
        first one found. For disambiguation, use
        :meth:`get_tool_qualified` with ``server_name:tool_name``.
        """
        for tool in self._tool_cache.values():
            if tool.name == name:
                return tool
        return None

    def get_tool_qualified(self, qualified_name: str) -> MCPTool | None:
        """Get a tool by its qualified name (``server_name:tool_name``)."""
        return self._tool_cache.get(qualified_name)

    def get_tools_for_server(self, server_name: str) -> list[MCPTool]:
        """Return all tools from a specific server."""
        return [t for t in self._tool_cache.values() if t.server_name == server_name]

    def get_all_tools(self) -> list[MCPTool]:
        """Return all cached tools."""
        return list(self._tool_cache.values())

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return tool statistics grouped by server.

        Example return value::

            {
                "total_tools": 42,
                "total_servers": 3,
                "by_server": {
                    "filesystem": {"count": 8, "tools": ["read", "write", ...]},
                    "github": {"count": 15, "tools": ["search", "create_issue", ...]},
                    "browser": {"count": 19, "tools": ["navigate", "screenshot", ...]},
                },
                "tool_names": ["read", "write", "search", ...],
                "refreshed": true,
            }
        """
        by_server: dict[str, dict[str, Any]] = defaultdict(
            lambda: {"count": 0, "tools": []}
        )

        for tool in self._tool_cache.values():
            entry = by_server[tool.server_name]
            entry["count"] += 1
            entry["tools"].append(tool.name)

        tool_names = sorted(set(t.name for t in self._tool_cache.values()))

        return {
            "total_tools": len(self._tool_cache),
            "total_servers": len(by_server),
            "by_server": dict(by_server),
            "tool_names": tool_names,
            "refreshed": self._refreshed,
        }

    def get_server_names(self) -> list[str]:
        """Return list of server names that have tools in the cache."""
        return sorted(set(t.server_name for t in self._tool_cache.values()))

    def count_tools(self) -> int:
        """Return total number of cached tools."""
        return len(self._tool_cache)

    def has_tools(self) -> bool:
        """Return True if at least one tool is cached."""
        return len(self._tool_cache) > 0

    @property
    def is_refreshed(self) -> bool:
        """Return True if the registry has been refreshed at least once."""
        return self._refreshed

    # ------------------------------------------------------------------
    # Schema Export
    # ------------------------------------------------------------------

    def get_openai_schemas(self) -> list[dict[str, Any]]:
        """Return all tools in OpenAI function-calling format.

        Convenience method that delegates to each tool's
        :meth:`MCPTool.to_openai_schema`.
        """
        return [t.to_openai_schema() for t in self._tool_cache.values()]

    # ------------------------------------------------------------------
    # Repr
    # ------------------------------------------------------------------

    def __repr__(self) -> str:
        return (
            f"MCPToolRegistry(tools={len(self._tool_cache)}, "
            f"servers={len(self.get_server_names())}, "
            f"refreshed={self._refreshed})"
        )
