#!/usr/bin/env python3
"""
Aion Hand - MCP Configuration
==============================
Manages MCP server configurations, loading from and saving to JSON config
files. Provides sensible defaults for common MCP servers (filesystem,
GitHub, browser, memory, database).

Configuration file location:
  ``<config_dir>/mcp_servers.json``

Example config file::

    {
        "servers": [
            {
                "name": "filesystem",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-filesystem", "/home/user/docs"],
                "env": {},
                "auto_connect": true,
                "enabled": true
            },
            {
                "name": "github",
                "transport": "stdio",
                "command": "npx",
                "args": ["-y", "@anthropic/mcp-github"],
                "env": {"GITHUB_TOKEN": ""},
                "auto_connect": false,
                "enabled": true
            },
            {
                "name": "remote-api",
                "transport": "sse",
                "url": "http://localhost:8080/sse",
                "auto_connect": true,
                "enabled": true
            }
        ]
    }

Usage::

    config = MCPConfig(config_dir="/home/user/.aion-hand")
    await config.load()

    for server in config.list_servers():
        print(server.name, server.transport, server.auto_connect)

    config.add_server(MCPServerConfig(name="custom", transport="sse", url="http://..."))
    await config.save()
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger("aion_hand.mcp.config")

# Config filename
CONFIG_FILENAME = "mcp_servers.json"


# ===================================================================
# Data Classes
# ===================================================================


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server.

    Attributes:
        name: Logical server name (must be unique).
        transport: Transport type — ``"stdio"`` or ``"sse"``.
        command: Executable command (for stdio transport).
        args: Arguments for the command.
        url: URL endpoint (for SSE transport).
        env: Extra environment variables for the subprocess.
        auto_connect: If True, the client should connect on startup.
        enabled: If False, the server is skipped entirely.
    """

    name: str = ""
    transport: str = "stdio"
    command: str | None = None
    args: list[str] = field(default_factory=list)
    url: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    auto_connect: bool = False
    enabled: bool = True
    description: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a JSON-serializable dict."""
        d = asdict(self)
        # Remove None values for cleaner JSON
        return {k: v for k, v in d.items() if v is not None and v != [] and v != {}}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MCPServerConfig:
        """Deserialize from a dict."""
        # Filter out unknown keys to stay forward-compatible
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)

    def __repr__(self) -> str:
        return (
            f"MCPServerConfig(name={self.name!r}, transport={self.transport!r}, "
            f"auto_connect={self.auto_connect}, enabled={self.enabled})"
        )


# ===================================================================
# Default Server Configurations
# ===================================================================


def _get_default_servers() -> list[MCPServerConfig]:
    """Return the built-in default MCP server configurations.

    These are well-known community MCP servers. They are pre-configured
    but set to ``auto_connect=False`` by default so users must explicitly
    opt in (and provide any required tokens).
    """
    return [
        MCPServerConfig(
            name="filesystem",
            transport="stdio",
            command="npx",
            args=["-y", "@anthropic/mcp-filesystem", "/tmp"],
            env={},
            auto_connect=False,
            enabled=True,
            description="Local filesystem read/write via Anthropic MCP Filesystem server",
        ),
        MCPServerConfig(
            name="github",
            transport="stdio",
            command="npx",
            args=["-y", "@anthropic/mcp-github"],
            env={"GITHUB_TOKEN": ""},
            auto_connect=False,
            enabled=True,
            description="GitHub API integration (requires GITHUB_TOKEN)",
        ),
        MCPServerConfig(
            name="browser",
            transport="stdio",
            command="npx",
            args=["-y", "@anthropic/mcp-browser"],
            env={},
            auto_connect=False,
            enabled=True,
            description="Browser automation via Anthropic MCP Browser server",
        ),
        MCPServerConfig(
            name="memory",
            transport="stdio",
            command="npx",
            args=["-y", "@anthropic/mcp-memory"],
            env={},
            auto_connect=False,
            enabled=True,
            description="Persistent key-value memory store",
        ),
        MCPServerConfig(
            name="database",
            transport="stdio",
            command="npx",
            args=["-y", "@anthropic/mcp-database"],
            env={"DATABASE_URL": ""},
            auto_connect=False,
            enabled=True,
            description="Database query tool (requires DATABASE_URL)",
        ),
    ]


# ===================================================================
# MCP Configuration Manager
# ===================================================================


class MCPConfig:
    """Manages MCP server configurations loaded from JSON config files.

    On first load, if no config file exists, the manager creates one with
    the default server definitions. Subsequent loads merge the file config
    with the defaults (user config takes precedence).
    """

    def __init__(self, config_dir: str | None = None) -> None:
        """
        Args:
            config_dir: Directory containing the config file.
                Defaults to ``~/.aion-hand``.
        """
        if config_dir is None:
            config_dir = os.path.join(
                os.path.expanduser("~"), ".aion-hand"
            )
        self._config_dir = Path(config_dir)
        self._config_path = self._config_dir / CONFIG_FILENAME
        self._servers: dict[str, MCPServerConfig] = {}
        self._loaded = False

    # ------------------------------------------------------------------
    # Load / Save
    # ------------------------------------------------------------------

    async def load(self) -> None:
        """Load configurations from the config file.

        If the file does not exist, it is created with default server
        definitions. If it exists, user configs are merged with defaults
        (user-defined entries override defaults).
        """
        # Ensure config directory exists
        self._config_dir.mkdir(parents=True, exist_ok=True)

        if not self._config_path.exists():
            logger.info(
                "No MCP config at %s, creating with defaults",
                self._config_path,
            )
            self._servers = {s.name: s for s in _get_default_servers()}
            await self.save()
            self._loaded = True
            return

        try:
            raw = self._config_path.read_text(encoding="utf-8")
            data = json.loads(raw)
        except (json.JSONDecodeError, OSError) as exc:
            logger.error(
                "Failed to read MCP config from %s: %s",
                self._config_path,
                exc,
            )
            self._servers = {s.name: s for s in _get_default_servers()}
            self._loaded = True
            return

        # Parse server configs from file
        file_servers: dict[str, MCPServerConfig] = {}
        for server_data in data.get("servers", []):
            try:
                config = MCPServerConfig.from_dict(server_data)
                if config.name:
                    file_servers[config.name] = config
            except Exception as exc:
                logger.warning(
                    "Skipping invalid server config: %s", exc
                )

        # Merge: defaults first, then user overrides
        defaults = _get_default_servers()
        merged: dict[str, MCPServerConfig] = {}

        for default in defaults:
            merged[default.name] = default

        for name, user_config in file_servers.items():
            merged[name] = user_config

        self._servers = merged
        self._loaded = True
        logger.info(
            "Loaded %d MCP server configs from %s",
            len(self._servers),
            self._config_path,
        )

    async def save(self) -> None:
        """Save the current configurations to the config file.

        Creates the config directory if it does not exist.
        """
        self._config_dir.mkdir(parents=True, exist_ok=True)

        # Filter out the 'description' field if present (it's not part of
        # the serialized config)
        servers_data = []
        for server in self._servers.values():
            d = server.to_dict()
            d.pop("description", None)
            servers_data.append(d)

        payload = {"version": 1, "servers": servers_data}

        try:
            self._config_path.write_text(
                json.dumps(payload, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            logger.info("Saved MCP config to %s", self._config_path)
        except OSError as exc:
            logger.error("Failed to save MCP config: %s", exc)
            raise

    # ------------------------------------------------------------------
    # Server Management
    # ------------------------------------------------------------------

    def add_server(self, config: MCPServerConfig) -> None:
        """Add or update a server configuration.

        Args:
            config: The server configuration to add.

        Raises:
            ValueError: If a server with the same name exists and you
                want to update it (just overwrite silently — matching
                the principle of least surprise for config management).
        """
        if not config.name:
            raise ValueError("Server config must have a non-empty name")
        self._servers[config.name] = config
        logger.info("Added/updated MCP server config: %s", config.name)

    def remove_server(self, name: str) -> bool:
        """Remove a server configuration by name.

        Returns True if found and removed, False otherwise.
        """
        if name in self._servers:
            del self._servers[name]
            logger.info("Removed MCP server config: %s", name)
            return True
        logger.warning(
            "Cannot remove MCP server '%s': not found", name
        )
        return False

    def get_server(self, name: str) -> MCPServerConfig | None:
        """Get a specific server configuration by name."""
        return self._servers.get(name)

    def list_servers(self) -> list[MCPServerConfig]:
        """Return all server configurations (enabled and disabled)."""
        return list(self._servers.values())

    def list_enabled_servers(self) -> list[MCPServerConfig]:
        """Return only enabled server configurations."""
        return [s for s in self._servers.values() if s.enabled]

    def get_auto_connect_servers(self) -> list[MCPServerConfig]:
        """Return servers that should auto-connect on startup.

        These are servers that are both enabled and have ``auto_connect=True``.
        """
        return [
            s
            for s in self._servers.values()
            if s.enabled and s.auto_connect
        ]

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def list_stdio_servers(self) -> list[MCPServerConfig]:
        """Return all stdio-transport server configs."""
        return [
            s for s in self._servers.values()
            if s.transport == "stdio" and s.enabled
        ]

    def list_sse_servers(self) -> list[MCPServerConfig]:
        """Return all SSE-transport server configs."""
        return [
            s for s in self._servers.values()
            if s.transport == "sse" and s.enabled
        ]

    def count_servers(self) -> int:
        """Return total number of configured servers."""
        return len(self._servers)

    def count_enabled_servers(self) -> int:
        """Return number of enabled servers."""
        return sum(1 for s in self._servers.values() if s.enabled)

    @property
    def config_path(self) -> Path:
        """Return the path to the config file."""
        return self._config_path

    @property
    def config_dir(self) -> Path:
        """Return the config directory path."""
        return self._config_dir

    @property
    def is_loaded(self) -> bool:
        """Return True if the config has been loaded."""
        return self._loaded

    # ------------------------------------------------------------------
    # Serialization helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Return the full config as a serializable dict."""
        servers = []
        for s in self._servers.values():
            d = s.to_dict()
            d.pop("description", None)
            servers.append(d)
        return {"version": 1, "servers": servers}

    def __repr__(self) -> str:
        enabled = sum(1 for s in self._servers.values() if s.enabled)
        auto = sum(
            1 for s in self._servers.values()
            if s.enabled and s.auto_connect
        )
        return (
            f"MCPConfig(path={self._config_path}, "
            f"servers={len(self._servers)}, "
            f"enabled={enabled}, auto_connect={auto})"
        )
