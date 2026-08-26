"""
Aion Hand CLI - Command Line Interface

A full-featured CLI for the Aion Hand autonomous AI agent framework.
Provides interactive REPL, subcommands for all subsystems, and
comprehensive configuration management.

Uses only Python standard library: argparse, asyncio, sys, os, readline, datetime, json.
Imports from aion_core with graceful fallback when modules are unavailable.
"""

import argparse
import asyncio
import contextlib
import importlib
import json
import logging
import os
import sys
import textwrap
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

try:
    import readline  # noqa: F401 - imported for history support
except ImportError:
    readline = None  # Windows: plain input() without history support

from . import __version__

# ═══════════════════════════════════════════════════════════════════════════════
#  ANSI COLOR CODES
# ═══════════════════════════════════════════════════════════════════════════════

class Colors:
    """ANSI escape code constants for terminal coloring."""
    RESET   = "\033[0m"
    BOLD    = "\033[1m"
    DIM     = "\033[2m"
    UNDERLINE = "\033[4m"

    BLACK   = "\033[30m"
    RED     = "\033[31m"
    GREEN   = "\033[32m"
    YELLOW  = "\033[33m"
    BLUE    = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN    = "\033[36m"
    WHITE   = "\033[37m"

    BRIGHT_BLACK   = "\033[90m"
    BRIGHT_RED     = "\033[91m"
    BRIGHT_GREEN   = "\033[92m"
    BRIGHT_YELLOW  = "\033[93m"
    BRIGHT_BLUE    = "\033[94m"
    BRIGHT_MAGENTA = "\033[95m"
    BRIGHT_CYAN    = "\033[96m"
    BRIGHT_WHITE   = "\033[97m"

    BG_BLACK   = "\033[40m"
    BG_RED     = "\033[41m"
    BG_GREEN   = "\033[42m"
    BG_YELLOW  = "\033[43m"
    BG_BLUE    = "\033[44m"
    BG_MAGENTA = "\033[45m"
    BG_CYAN    = "\033[46m"
    BG_WHITE   = "\033[47m"


# ═══════════════════════════════════════════════════════════════════════════════
#  STREAM SPINNER
# ═══════════════════════════════════════════════════════════════════════════════

class StreamSpinner:
    """Displays a spinning indicator while the agent is processing."""

    FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
    INTERVAL = 0.08

    def __init__(self, message: str = "Thinking"):
        self.message = message
        self._running = False
        self._task = None

    def _spin(self):
        """Spin loop - writes over the same line."""
        idx = 0
        while self._running:
            frame = self.FRAMES[idx % len(self.FRAMES)]
            sys.stdout.write(f"\r  {Colors.CYAN}{Colors.BOLD}{frame}{Colors.RESET} {self.message}...")
            sys.stdout.flush()
            idx += 1
            time.sleep(self.INTERVAL)
        # Clear the line
        sys.stdout.write("\r" + " " * 60 + "\r")
        sys.stdout.flush()

    def start(self):
        """Start the spinner in a background thread."""
        self._running = True
        self._task = threading.Thread(target=self._spin, daemon=True)
        self._task.start()

    def stop(self):
        """Stop the spinner."""
        self._running = False
        if self._task is not None:
            self._task.join(timeout=1.0)
            self._task = None


# ═══════════════════════════════════════════════════════════════════════════════
#  REPL HISTORY
# ═══════════════════════════════════════════════════════════════════════════════

_HISTORY_FILE = os.path.expanduser("~/.aion_hand_history")


def _load_history():
    """Load REPL command history from disk."""
    if readline is None:
        return
    if os.path.exists(_HISTORY_FILE):
        with contextlib.suppress(OSError):
            readline.read_history_file(_HISTORY_FILE)
    readline.set_history_length(2000)


def _save_history():
    """Persist REPL command history to disk."""
    if readline is None:
        return
    with contextlib.suppress(OSError):
        readline.write_history_file(_HISTORY_FILE)


# ═══════════════════════════════════════════════════════════════════════════════
#  CONFIG PATHS & HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

_CONFIG_DIR = os.path.expanduser("~/.aion_hand")
_CONFIG_FILE = os.path.join(_CONFIG_DIR, "config.json")
_MEMORY_FILE = os.path.join(_CONFIG_DIR, "MEMORY.md")
_CRON_FILE = os.path.join(_CONFIG_DIR, "cron.json")
_MCP_FILE = os.path.join(_CONFIG_DIR, "mcp_servers.json")


def _ensure_config_dir():
    """Ensure the config directory exists."""
    os.makedirs(_CONFIG_DIR, exist_ok=True)


def _load_config() -> dict:
    """Load configuration from disk."""
    _ensure_config_dir()
    if os.path.exists(_CONFIG_FILE):
        try:
            with open(_CONFIG_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _save_config(config: dict):
    """Save configuration to disk."""
    _ensure_config_dir()
    with open(_CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, sort_keys=True)


def _get_nested(obj: dict, dotted_key: str, default=None):
    """Retrieve a nested dict value using dot-notation key."""
    keys = dotted_key.split(".")
    current = obj
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return default
    return current


def _set_nested(obj: dict, dotted_key: str, value):
    """Set a nested dict value using dot-notation key."""
    keys = dotted_key.split(".")
    current = obj
    for key in keys[:-1]:
        if key not in current or not isinstance(current[key], dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value


# ═══════════════════════════════════════════════════════════════════════════════
#  KNOWN PROVIDERS, TOOLS & SKILLS (fallback defaults)
# ═══════════════════════════════════════════════════════════════════════════════

_KNOWN_PROVIDERS = [
    ("openai",           "gpt-4o",              True),
    ("openai",           "gpt-4o-mini",         True),
    ("anthropic",        "claude-sonnet-4-20250514", True),
    ("anthropic",        "claude-haiku-4-20250414",  True),
    ("google",           "gemini-2.5-pro",      True),
    ("google",           "gemini-2.5-flash",     True),
    ("ollama",           "llama3",               False),
    ("ollama",           "mistral",              False),
    ("ollama",           "codellama",            False),
]

_KNOWN_TOOLS = [
    ("web_search",    "Search the web for information",                "core"),
    ("file_read",     "Read file contents",                            "core"),
    ("file_write",    "Write or create files",                         "core"),
    ("file_edit",     "Edit existing files with search/replace",       "core"),
    ("shell",         "Execute shell commands",                         "core"),
    ("code_execute",  "Run Python / JavaScript code in sandbox",        "core"),
    ("memory_store",  "Store information in long-term memory",         "memory"),
    ("memory_recall", "Recall information from memory",                  "memory"),
    ("calendar",      "Manage calendar events",                        "core"),
    ("email",         "Send and read emails",                          "extended"),
    ("browser",       "Automate web browser interactions",             "extended"),
    ("image_gen",     "Generate images from text prompts",             "extended"),
    ("knowledge_store", "Store facts in knowledge graph",               "knowledge"),
    ("knowledge_query", "Query knowledge graph",                        "knowledge"),
]

_KNOWN_TOOLSETS = sorted({t[2] for t in _KNOWN_TOOLS})

_KNOWN_SKILLS = [
    ("research",      "Deep research and report generation"),
    ("code_review",   "Analyze and review code for quality"),
    ("debugging",     "Systematic debugging assistant"),
    ("writing",       "Content creation and editing"),
    ("data_analysis", "Data analysis and visualization"),
    ("planning",      "Task planning and decomposition"),
]

_BENCHMARK_CATEGORIES = [
    "all", "planning", "tool_use", "code", "recovery", "memory", "multi_step",
]


# ═══════════════════════════════════════════════════════════════════════════════
#  CLI CLASS
# ═══════════════════════════════════════════════════════════════════════════════

class AionHandCLI:
    """Main CLI class for Aion Hand — comprehensive command-line interface."""

    def __init__(self):
        self.parser = self._build_parser()
        self._agent = None
        self._moa_enabled = False  # Mixture-of-agents toggle for next turn

    # ── Parser Construction ──────────────────────────────────────────────

    def _build_parser(self) -> argparse.ArgumentParser:
        """Build the full argparse hierarchy with all subcommands."""
        parser = argparse.ArgumentParser(
            prog="aion-hand",
            description=(
                "Aion Hand — The Ultimate Autonomous AI Agent Framework\n\n"
                "Provides interactive REPL, mission pipelines, benchmarks,\n"
                "knowledge graphs, MCP servers, dynamic agents, and more."
            ),
            epilog=(
                "Examples:\n"
                "  aion-hand                      Start interactive REPL\n"
                "  aion-hand chat                 Start chat session\n"
                "  aion-hand config --show        Show configuration\n"
                "  aion-hand pipeline \"build API\"  Run pipeline\n"
                "  aion-hand status               System status\n"
                "  aion-hand --help               Show all commands"
            ),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        parser.add_argument(
            "-v", "--version", action="version",
            version=f"%(prog)s {__version__}",
        )

        subparsers = parser.add_subparsers(dest="command", metavar="COMMAND")

        # ── chat ───────────────────────────────────────────────────────
        chat_p = subparsers.add_parser(
            "chat",
            help="Start interactive chat with agent (REPL)",
            description="Open an interactive REPL session to chat with the Aion Hand agent.",
        )
        chat_p.add_argument(
            "-m", "--model", type=str, default=None,
            help="Override model for this session (provider:model)",
        )
        chat_p.add_argument(
            "--no-stream", action="store_true",
            help="Disable streaming output",
        )
        chat_p.set_defaults(func=self._cmd_chat)

        # ── config ──────────────────────────────────────────────────────
        config_p = subparsers.add_parser(
            "config",
            help="Show/edit configuration",
            description="View or modify Aion Hand configuration settings.",
        )
        config_p.add_argument(
            "--set", type=str, default=None, metavar="KEY=VALUE",
            help="Set a config value (e.g. --set default_model=openai:gpt-4o)",
        )
        config_p.add_argument(
            "--show", action="store_true",
            help="Show current configuration",
        )
        config_p.add_argument(
            "--profile", type=str, default=None, metavar="NAME",
            help="Switch to named configuration profile",
        )
        config_p.set_defaults(func=self._cmd_config)

        # ── setup ───────────────────────────────────────────────────────
        setup_p = subparsers.add_parser(
            "setup",
            help="Run first-time setup wizard",
            description="Interactive setup wizard for initial configuration.",
        )
        setup_p.add_argument(
            "--skip-gateway", action="store_true",
            help="Skip messaging gateway setup",
        )
        setup_p.set_defaults(func=self._cmd_setup)

        # ── status ──────────────────────────────────────────────────────
        status_p = subparsers.add_parser(
            "status",
            help="Show system status (all subsystems)",
            description="Display health and status of every subsystem in Aion Hand.",
        )
        status_p.add_argument(
            "--json", action="store_true",
            help="Output as JSON",
        )
        status_p.set_defaults(func=self._cmd_status)

        # ── pipeline ───────────────────────────────────────────────────
        pipeline_p = subparsers.add_parser(
            "pipeline",
            help="Run mission through execution pipeline",
            description="Execute a mission through the full planning/execution/verification pipeline.",
        )
        pipeline_p.add_argument(
            "mission", type=str, nargs="?", default=None,
            help="Mission text to execute",
        )
        pipeline_p.add_argument(
            "-s", "--steps", type=str, default=None,
            help="Comma-separated list of pipeline steps to run",
        )
        pipeline_p.add_argument(
            "-v", "--verbose", action="store_true",
            help="Show detailed step-by-step output",
        )
        pipeline_p.set_defaults(func=self._cmd_pipeline)

        # ── benchmark ────────────────────────────────────────────────────
        bench_p = subparsers.add_parser(
            "benchmark",
            help="Run benchmark suite",
            description="Evaluate agent performance across multiple categories.",
        )
        bench_p.add_argument(
            "--category", type=str, default="all",
            choices=_BENCHMARK_CATEGORIES,
            help="Benchmark category (default: all)",
        )
        bench_p.add_argument(
            "--runs", type=int, default=1,
            help="Number of benchmark runs (default: 1)",
        )
        bench_p.add_argument(
            "-o", "--output", type=str, default=None,
            help="Output file for results (JSON)",
        )
        bench_p.set_defaults(func=self._cmd_benchmark)

        # ── knowledge ────────────────────────────────────────────────────
        knowledge_p = subparsers.add_parser(
            "knowledge",
            help="Knowledge graph operations",
            description="Query, search, and manage the knowledge graph.",
        )
        knowledge_p.add_argument(
            "--search", type=str, default=None, metavar="QUERY",
            help="Search the knowledge graph",
        )
        knowledge_p.add_argument(
            "--stats", action="store_true",
            help="Show knowledge graph statistics",
        )
        knowledge_p.add_argument(
            "--export", type=str, default=None, metavar="FILE",
            help="Export knowledge graph to file",
        )
        knowledge_p.set_defaults(func=self._cmd_knowledge)

        # ── mcp ────────────────────────────────────────────────────────
        mcp_p = subparsers.add_parser(
            "mcp",
            help="MCP (Model Context Protocol) server operations",
            description="Manage MCP servers for tool extension.",
        )
        mcp_p.add_argument(
            "--list", action="store_true",
            help="List configured MCP servers",
        )
        mcp_p.add_argument(
            "--add", type=str, nargs=2, metavar=("NAME", "COMMAND"),
            help="Add an MCP server (name and command)",
        )
        mcp_p.add_argument(
            "--remove", type=str, default=None, metavar="NAME",
            help="Remove an MCP server by name",
        )
        mcp_p.set_defaults(func=self._cmd_mcp)

        # ── dynamic ──────────────────────────────────────────────────────
        dynamic_p = subparsers.add_parser(
            "dynamic",
            help="Dynamic agent operations",
            description="Execute tasks with dynamically composed agent teams.",
        )
        dynamic_p.add_argument(
            "task", type=str, nargs="?", default=None,
            help="Task description for dynamic execution",
        )
        dynamic_p.add_argument(
            "--complexity", type=int, default=5,
            help="Task complexity level 1-10 (default: 5)",
        )
        dynamic_p.add_argument(
            "--plan", type=str, default=None, metavar="TASK",
            help="Show execution plan without executing",
        )
        dynamic_p.add_argument(
            "--stats", action="store_true",
            help="Show dynamic agent statistics",
        )
        dynamic_p.set_defaults(func=self._cmd_dynamic)

        # ── gateway ────────────────────────────────────────────────────
        gateway_p = subparsers.add_parser(
            "gateway",
            help="Start messaging gateway",
            description="Connect Aion Hand to messaging platforms (Telegram, Discord, Slack, etc.).",
        )
        gateway_p.add_argument(
            "--platform", type=str, default=None,
            choices=["telegram", "discord", "slack", "webhook", "matrix"],
            help="Start a specific platform gateway",
        )
        gateway_p.add_argument(
            "--all", action="store_true",
            help="Start all configured platform gateways",
        )
        gateway_p.add_argument(
            "-p", "--port", type=int, default=8080,
            help="Port for the gateway server (default: 8080)",
        )
        gateway_p.set_defaults(func=self._cmd_gateway)

        # ── memory ─────────────────────────────────────────────────────
        memory_p = subparsers.add_parser(
            "memory",
            help="Memory operations",
            description="Search, manage, and export agent long-term memory.",
        )
        memory_p.add_argument(
            "--search", type=str, default=None, metavar="QUERY",
            help="Search memory for a query",
        )
        memory_p.add_argument(
            "--stats", action="store_true",
            help="Show memory statistics",
        )
        memory_p.add_argument(
            "--export", action="store_true",
            help="Export memory to MEMORY.md",
        )
        memory_p.add_argument(
            "--nudge", action="store_true",
            help="Force a memory consolidation nudge",
        )
        memory_p.set_defaults(func=self._cmd_memory)

        # ── skills ──────────────────────────────────────────────────────
        skills_p = subparsers.add_parser(
            "skills",
            help="Skill management",
            description="List, create, and evaluate agent skills.",
        )
        skills_p.add_argument(
            "--list", action="store_true",
            help="List all skills",
        )
        skills_p.add_argument(
            "--create", type=str, default=None, metavar="NAME",
            help="Create a new skill",
        )
        skills_p.add_argument(
            "--evaluate", action="store_true",
            help="Evaluate all skills",
        )
        skills_p.set_defaults(func=self._cmd_skills)

        # ── cron ────────────────────────────────────────────────────────
        cron_p = subparsers.add_parser(
            "cron",
            help="Cron / scheduled task management",
            description="Manage scheduled recurring tasks.",
        )
        cron_p.add_argument(
            "--list", action="store_true",
            help="List cron jobs",
        )
        cron_p.add_argument(
            "--add", type=str, nargs=2, metavar=("EXPR", "COMMAND"),
            help="Add a cron job (cron expression and command)",
        )
        cron_p.add_argument(
            "--remove", type=str, default=None, metavar="ID",
            help="Remove a cron job by ID",
        )
        cron_p.set_defaults(func=self._cmd_cron)

        # ── security ─────────────────────────────────────────────────────
        security_p = subparsers.add_parser(
            "security",
            help="Security operations",
            description="Run security audits, scan for secrets, and check file safety.",
        )
        security_p.add_argument(
            "--audit", action="store_true",
            help="Run security audit",
        )
        security_p.add_argument(
            "--scan-secrets", type=str, default=None, metavar="FILE",
            help="Scan a file for leaked secrets/API keys",
        )
        security_p.add_argument(
            "--check-file", type=str, default=None, metavar="PATH",
            help="Check if a file path is safe to access",
        )
        security_p.set_defaults(func=self._cmd_security)

        # ── tools ───────────────────────────────────────────────────────
        tools_p = subparsers.add_parser(
            "tools",
            help="Tool operations",
            description="List, search, and manage agent tools.",
        )
        tools_p.add_argument(
            "--list", action="store_true",
            help="List all tools",
        )
        tools_p.add_argument(
            "--toolset", type=str, default=None, metavar="NAME",
            help="Filter tools by toolset name",
        )
        tools_p.add_argument(
            "--search", type=str, default=None, metavar="QUERY",
            help="Search tools by name or description",
        )
        tools_p.add_argument(
            "--stats", action="store_true",
            help="Show tool usage statistics",
        )
        tools_p.set_defaults(func=self._cmd_tools)

        # ── providers ───────────────────────────────────────────────────
        providers_p = subparsers.add_parser(
            "providers",
            help="Provider management",
            description="List, test, and configure LLM providers.",
        )
        providers_p.add_argument(
            "--list", action="store_true",
            help="List all providers",
        )
        providers_p.add_argument(
            "--test", type=str, default=None, metavar="PROVIDER",
            help="Test a provider connection",
        )
        providers_p.add_argument(
            "--set", type=str, nargs=2, default=None, metavar=("PROVIDER", "MODEL"),
            help="Set active provider and model",
        )
        providers_p.set_defaults(func=self._cmd_providers)

        # ── doctor ───────────────────────────────────────────────────────
        doctor_p = subparsers.add_parser(
            "doctor",
            help="Diagnose Aion installation health",
            description="Run a series of health checks on your Aion installation: Python version, dependencies, config, providers, MCP servers, skills, personas.",
        )
        doctor_p.add_argument("--fix", action="store_true", help="Attempt to fix detected issues")
        doctor_p.set_defaults(func=self._cmd_doctor)

        # ── backup ───────────────────────────────────────────────────────
        backup_p = subparsers.add_parser(
            "backup",
            help="Backup / restore agent state",
            description="Create a backup archive of ~/.aion-hand/ or restore from one.",
        )
        backup_p.add_argument("--create", action="store_true", help="Create a new backup")
        backup_p.add_argument("--restore", type=str, default=None, metavar="PATH", help="Restore from archive")
        backup_p.add_argument("--list", action="store_true", help="List existing backups")
        backup_p.add_argument("--cleanup", type=int, default=None, metavar="KEEP", help="Delete old backups, keep newest N")
        backup_p.add_argument("--label", type=str, default="", help="Label for the backup")
        backup_p.set_defaults(func=self._cmd_backup)

        # ── serve ────────────────────────────────────────────────────────
        serve_p = subparsers.add_parser(
            "serve",
            help="Start the HTTP API server",
            description="Run the Aion HTTP API server for the web UI and external clients.",
        )
        serve_p.add_argument("--host", default="0.0.0.0", help="Bind host (default: 0.0.0.0)")
        serve_p.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
        serve_p.add_argument("--log-level", default="INFO", help="Log level (default: INFO)")
        serve_p.set_defaults(func=self._cmd_serve)

        # ── Default: no command → interactive REPL ─────────────────────
        parser.set_defaults(func=self._cmd_chat)

        return parser

    # ── Entry Point ──────────────────────────────────────────────────────

    def run(self):
        """Main entry point — parse args and execute."""
        args = self.parser.parse_args()
        try:
            asyncio.run(self._execute(args))
        except KeyboardInterrupt:
            self._print_colored("\nInterrupted.\n", Colors.YELLOW)
            sys.exit(130)

    async def _execute(self, args: argparse.Namespace):
        """Route parsed arguments to the appropriate async handler."""
        handler = getattr(args, "func", None)
        if handler is None:
            self.parser.print_help()
            return
        await handler(args)

    # ══════════════════════════════════════════════════════════════════════
    #  COMMAND HANDLERS — Main Subcommands
    # ══════════════════════════════════════════════════════════════════════

    # ── chat ──────────────────────────────────────────────────────────────

    async def _cmd_chat(self, args: argparse.Namespace):
        """Start interactive chat REPL."""
        await self._interactive_repl(args)

    # ── config ───────────────────────────────────────────────────────────

    async def _cmd_config(self, args: argparse.Namespace):
        """Show, edit, or switch configuration."""
        if args.profile:
            await self._config_switch_profile(args.profile)
            return

        if args.set:
            await self._config_set_value(args.set)
            return

        if args.show or (not args.set and not args.profile):
            await self._config_show()

    async def _config_show(self):
        """Display the current configuration."""
        config = _load_config()
        self._print_colored(
            f"\n  {Colors.BOLD}Configuration{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)
        if config:
            for key, value in config.items():
                if isinstance(value, dict):
                    self._print_colored(
                        f"  {Colors.BRIGHT_WHITE}{key}:{Colors.RESET}\n"
                    )
                    for k, v in value.items():
                        val_str = json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                        self._print_colored(
                            f"    {Colors.DIM}{k:<22}{Colors.RESET} {val_str}\n"
                        )
                elif isinstance(value, list):
                    self._print_colored(
                        f"  {Colors.BRIGHT_WHITE}{key}:{Colors.RESET} {json.dumps(value)}\n"
                    )
                else:
                    self._print_colored(
                        f"  {Colors.BRIGHT_WHITE}{key:<24}{Colors.RESET} {value}\n"
                    )
        else:
            self._print_colored(f"  {Colors.DIM}No configuration set. Run 'aion-hand setup' to begin.{Colors.RESET}\n")
        self._print_colored(f"\n  {Colors.DIM}Config file: {_CONFIG_FILE}{Colors.RESET}\n\n")

    async def _config_set_value(self, key_value: str):
        """Set a configuration value (KEY=VALUE format)."""
        if "=" not in key_value:
            self._print_colored(
                f"  {Colors.RED}Error: Use --set key=value format{Colors.RESET}\n"
            )
            return
        key, value = key_value.split("=", 1)
        # Try JSON parse for complex values
        try:
            parsed = json.loads(value)
            value = parsed
        except (json.JSONDecodeError, TypeError):
            pass

        config = _load_config()
        _set_nested(config, key, value)
        _save_config(config)
        display_val = json.dumps(value) if not isinstance(value, str) else value
        self._print_colored(
            f"  {Colors.GREEN}✔{Colors.RESET} Set {Colors.CYAN}{key}{Colors.RESET} = "
            f"{Colors.BRIGHT_WHITE}{display_val}{Colors.RESET}\n"
        )

    async def _config_switch_profile(self, name: str):
        """Switch to a named configuration profile."""
        config = _load_config()
        profiles = config.get("profiles", {})

        if name not in profiles:
            self._print_colored(
                f"  {Colors.RED}Error: Profile '{name}' not found.{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}Available profiles: {', '.join(profiles.keys()) or 'none'}{Colors.RESET}\n"
            )
            return

        config["active_profile"] = name
        # Merge profile settings into top-level config
        profile_settings = profiles[name]
        for k, v in profile_settings.items():
            if isinstance(v, dict) and k in config and isinstance(config[k], dict):
                config[k].update(v)
            else:
                config[k] = v
        _save_config(config)

        self._print_colored(
            f"  {Colors.GREEN}✔{Colors.RESET} Switched to profile "
            f"{Colors.BRIGHT_CYAN}{name}{Colors.RESET}\n"
        )

    # ── setup ────────────────────────────────────────────────────────────

    async def _cmd_setup(self, args: argparse.Namespace):
        """Run first-time setup wizard."""
        self._print_colored(
            f"\n  {Colors.BOLD}{Colors.BRIGHT_CYAN}╔═══════════════════════════════════════╗{Colors.RESET}\n"
        )
        self._print_colored(
            f"  {Colors.BOLD}{Colors.BRIGHT_CYAN}║     Aion Hand Setup Wizard          ║{Colors.RESET}\n"
        )
        self._print_colored(
            f"  {Colors.BOLD}{Colors.BRIGHT_CYAN}╚═══════════════════════════════════════╝{Colors.RESET}\n\n"
        )
        config = _load_config()

        # Step 1: Provider selection
        self._print_colored(f"  {Colors.BOLD}Step 1: LLM Provider{Colors.RESET}\n", Colors.CYAN)
        self._print_colored("  Available providers: openai, anthropic, google, ollama\n", Colors.DIM)
        self._print_colored(f"  {Colors.WHITE}Enter provider name{Colors.RESET} [openai]: ", Colors.RESET)
        try:
            provider = input().strip() or "openai"
        except (EOFError, KeyboardInterrupt):
            self._print_colored(f"\n  {Colors.YELLOW}Setup cancelled.{Colors.RESET}\n")
            return
        config["provider"] = provider

        # Step 2: Model selection
        self._print_colored(f"\n  {Colors.BOLD}Step 2: Model{Colors.RESET}\n", Colors.CYAN)
        models = [m for p, m, _ in _KNOWN_PROVIDERS if p == provider]
        if models:
            for m in models:
                self._print_colored(f"    {Colors.GREEN}▸{Colors.RESET} {m}\n")
        self._print_colored(f"  {Colors.WHITE}Enter model name{Colors.RESET}: ", Colors.RESET)
        try:
            model = input().strip()
        except (EOFError, KeyboardInterrupt):
            self._print_colored(f"\n  {Colors.YELLOW}Setup cancelled.{Colors.RESET}\n")
            return
        config["default_model"] = f"{provider}:{model}" if model else None

        # Step 3: API Key
        env_key = f"{provider.upper()}_API_KEY"
        if os.environ.get(env_key):
            self._print_colored(
                f"\n  {Colors.GREEN}✔{Colors.RESET} API key found in environment variable {env_key}\n"
            )
        else:
            self._print_colored(f"\n  {Colors.BOLD}Step 3: API Key{Colors.RESET}\n", Colors.CYAN)
            self._print_colored(f"  {Colors.WHITE}Enter API key (or press Enter to skip){Colors.RESET}: ", Colors.RESET)
            try:
                api_key = input().strip()
                if api_key:
                    if "api_keys" not in config:
                        config["api_keys"] = {}
                    config["api_keys"][provider] = api_key
                    self._print_colored(
                        f"  {Colors.GREEN}✔{Colors.RESET} API key saved (stored locally only)\n"
                    )
            except (EOFError, KeyboardInterrupt):
                pass

        # Step 4: Gateway (optional)
        if not args.skip_gateway:
            self._print_colored(f"\n  {Colors.BOLD}Step 4: Messaging Gateway (optional){Colors.RESET}\n", Colors.CYAN)
            self._print_colored(f"  {Colors.WHITE}Configure messaging platform?{Colors.RESET} (y/n) [n]: ", Colors.RESET)
            try:
                answer = input().strip().lower()
                if answer == "y":
                    self._print_colored(f"  {Colors.DIM}Platforms: telegram, discord, slack, webhook, matrix{Colors.RESET}\n")
                    self._print_colored(f"  {Colors.WHITE}Enter platform{Colors.RESET}: ", Colors.RESET)
                    platform = input().strip().lower()
                    self._print_colored(f"  {Colors.WHITE}Enter {platform} token/key{Colors.RESET}: ", Colors.RESET)
                    token = input().strip()
                    if platform and token:
                        if "gateway" not in config:
                            config["gateway"] = {}
                        config["gateway"][f"{platform}_token"] = token
                        self._print_colored(
                            f"  {Colors.GREEN}✔{Colors.RESET} {platform.capitalize()} configured.\n"
                        )
            except (EOFError, KeyboardInterrupt):
                pass

        _save_config(config)
        self._print_colored(
            f"\n  {Colors.GREEN}{Colors.BOLD}✔ Setup complete!{Colors.RESET}\n"
        )
        self._print_colored(
            f"  Run {Colors.CYAN}aion-hand chat{Colors.RESET} to start, "
            f"or {Colors.CYAN}aion-hand status{Colors.RESET} to verify.\n\n"
        )

    # ── status ───────────────────────────────────────────────────────────

    async def _cmd_status(self, args: argparse.Namespace):
        """Show system status for all subsystems."""
        config = _load_config()
        output_json = getattr(args, "json", False)

        subsystems = []

        # Core
        subsystems.append(("Agent Core", self._check_module("aion_core.agent")))
        subsystems.append(("Memory", self._check_module("aion_core.memory")))
        subsystems.append(("Tools", self._check_module("aion_core.tools")))
        subsystems.append(("Pipeline", self._check_module("aion_core.pipeline")))
        subsystems.append(("Knowledge Graph", self._check_module("aion_core.knowledge")))
        subsystems.append(("MCP", self._check_module("aion_core.mcp")))
        subsystems.append(("Dynamic Agents", self._check_module("aion_core.dynamic")))
        subsystems.append(("Orchestration", self._check_module("aion_core.orchestration")))
        subsystems.append(("Benchmark", self._check_module("aion_core.benchmark")))
        subsystems.append(("Router", self._check_module("aion_core.router")))
        subsystems.append(("Messaging Gateway", self._check_module("aion_core.messaging")))
        subsystems.append(("Cron Scheduler", self._check_module("aion_core.cron")))
        subsystems.append(("Security", self._check_module("aion_core.security")))
        subsystems.append(("Config Manager", self._check_module("aion_core.config")))
        subsystems.append(("Providers", self._check_module("aion_core.providers")))

        if output_json:
            result = {name: status for name, status in subsystems}
            result["version"] = __version__
            result["python"] = sys.version.split()[0]
            result["platform"] = sys.platform
            result["config_dir"] = _CONFIG_DIR
            result["default_model"] = config.get("default_model", "not set")
            self._print_colored(json.dumps(result, indent=2) + "\n")
            return

        self._print_colored(
            f"\n  {Colors.BOLD}Aion Hand System Status{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored("  " + "─" * 56 + "\n", Colors.DIM)

        for name, status in subsystems:
            if status == "ok":
                icon = f"{Colors.GREEN}✔{Colors.RESET}"
            elif status == "warn":
                icon = f"{Colors.YELLOW}⚠{Colors.RESET}"
            else:
                icon = f"{Colors.RED}✘{Colors.RESET}"
            self._print_colored(f"  {icon} {name:<28} {Colors.DIM}{status}{Colors.RESET}\n")

        self._print_colored(f"\n  {Colors.DIM}Version: {__version__}  |  Python: {sys.version.split()[0]}  |  Platform: {sys.platform}{Colors.RESET}\n")
        model = config.get("default_model", "not set")
        self._print_colored(f"  {Colors.DIM}Model: {model}{Colors.RESET}\n\n")

    def _check_module(self, module_path: str) -> str:
        """Check if a module can be imported. Returns 'ok', 'warn', or 'error'."""
        try:
            __import__(module_path)
            return "ok"
        except ImportError:
            return "not installed"
        except Exception:
            return "error"

    # ── pipeline ─────────────────────────────────────────────────────────

    async def _cmd_pipeline(self, args: argparse.Namespace):
        """Run a mission through the execution pipeline."""
        mission = getattr(args, "mission", None)

        if not mission:
            self._print_colored(
                f"  {Colors.YELLOW}Usage: aion-hand pipeline \"mission text\"{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}Run a mission through the planning/execution/verification pipeline.{Colors.RESET}\n"
            )
            return

        verbose = getattr(args, "verbose", False)
        steps = getattr(args, "steps", None)

        self._print_colored(
            f"\n  {Colors.BOLD}Execution Pipeline{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  Mission: {Colors.BRIGHT_WHITE}{mission}{Colors.RESET}\n")
        if steps:
            self._print_colored(f"  Steps:   {Colors.BRIGHT_CYAN}{steps}{Colors.RESET}\n")
        self._print_colored(f"  {Colors.DIM}Initializing pipeline...{Colors.RESET}\n\n")

        spinner = StreamSpinner("Pipeline executing")
        spinner.start()

        try:
            from aion_core.pipeline.engine import PipelineEngine
            engine = PipelineEngine(verbose=verbose)
            step_list = [s.strip() for s in steps.split(",")] if steps else None
            result = await engine.run(mission, steps=step_list)
            spinner.stop()
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Pipeline complete.\n"
            )
            if isinstance(result, dict):
                for k, v in result.items():
                    self._print_colored(f"    {Colors.BRIGHT_WHITE}{k}:{Colors.RESET} {v}\n")
            else:
                self._print_colored(f"  {Colors.BRIGHT_WHITE}{result}{Colors.RESET}\n")
        except ImportError:
            spinner.stop()
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Pipeline module not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}Install aion_core.pipeline to use this command.{Colors.RESET}\n"
            )
        except Exception as exc:
            spinner.stop()
            self._print_colored(f"  {Colors.RED}Error running pipeline:{Colors.RESET} {exc}\n")
        self._print_colored("")

    # ── benchmark ────────────────────────────────────────────────────────

    async def _cmd_benchmark(self, args: argparse.Namespace):
        """Run benchmarks."""
        category = getattr(args, "category", "all")
        runs = getattr(args, "runs", 1)
        output = getattr(args, "output", None)

        self._print_colored(
            f"\n  {Colors.BOLD}Benchmark Suite{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  Category: {Colors.BRIGHT_WHITE}{category}{Colors.RESET}\n")
        self._print_colored(f"  Runs:     {Colors.BRIGHT_WHITE}{runs}{Colors.RESET}\n")
        self._print_colored(f"  {Colors.DIM}Running benchmarks...{Colors.RESET}\n\n")

        spinner = StreamSpinner("Benchmarking")
        spinner.start()

        try:
            from aion_core.benchmark.runner import BenchmarkRunner
            runner = BenchmarkRunner()
            results = await runner.run(
                categories=[category] if category != "all" else None,
                num_runs=runs,
            )
            spinner.stop()

            if isinstance(results, dict):
                self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} Benchmarks complete.\n\n")
                for name, score in results.items():
                    self._print_colored(
                        f"    {Colors.BRIGHT_WHITE}{name:<30}{Colors.RESET} {score}\n"
                    )
            elif isinstance(results, list):
                for r in results:
                    self._print_colored(f"    {r}\n")
            else:
                self._print_colored(f"  {results}\n")

            if output:
                _ensure_config_dir()
                data = results if isinstance(results, (dict, list)) else {"result": str(results)}
                with open(output, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
                self._print_colored(
                    f"  {Colors.GREEN}✔{Colors.RESET} Results saved to {output}\n"
                )
        except ImportError:
            spinner.stop()
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Benchmark module not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        except Exception as exc:
            spinner.stop()
            self._print_colored(f"  {Colors.RED}Error running benchmarks:{Colors.RESET} {exc}\n")
        self._print_colored("")

    # ── knowledge ─────────────────────────────────────────────────────────

    async def _cmd_knowledge(self, args: argparse.Namespace):
        """Knowledge graph operations."""
        search = getattr(args, "search", None)
        stats = getattr(args, "stats", False)
        export_file = getattr(args, "export", None)

        if search:
            await self._knowledge_search(search)
        elif export_file:
            await self._knowledge_export(export_file)
        elif stats:
            await self._knowledge_stats()
        else:
            # Default: show stats
            await self._knowledge_stats()

    async def _knowledge_search(self, query: str):
        """Search the knowledge graph."""
        self._print_colored(
            f"\n  {Colors.BOLD}Knowledge Graph Search{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  Query: {Colors.BRIGHT_WHITE}{query}{Colors.RESET}\n\n")

        try:
            from aion_core.knowledge.graph import KnowledgeGraph
            kg = KnowledgeGraph()
            results = await kg.search(query, limit=10)
            if results:
                for i, item in enumerate(results, 1):
                    if isinstance(item, dict):
                        title = item.get("title", item.get("name", ""))
                        content = item.get("content", item.get("text", ""))[:200]
                        self._print_colored(
                            f"  {Colors.BRIGHT_GREEN}{i}.{Colors.RESET} "
                            f"{Colors.BOLD}{title}{Colors.RESET}\n"
                        )
                        self._print_colored(f"     {Colors.DIM}{content}{Colors.RESET}\n")
                    else:
                        self._print_colored(f"  {Colors.BRIGHT_GREEN}{i}.{Colors.RESET} {item}\n")
            else:
                self._print_colored(f"  {Colors.DIM}No results found.{Colors.RESET}\n")
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Knowledge graph not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        self._print_colored("")

    async def _knowledge_stats(self):
        """Show knowledge graph statistics."""
        self._print_colored(
            f"\n  {Colors.BOLD}Knowledge Graph Statistics{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)

        try:
            from aion_core.knowledge.manager import KnowledgeManager
            km = KnowledgeManager()
            stats = await km.get_stats()
            for key, value in stats.items():
                self._print_colored(
                    f"  {Colors.BRIGHT_WHITE}{key:<24}{Colors.RESET} {value}\n"
                )
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Knowledge graph not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        self._print_colored("")

    async def _knowledge_export(self, filepath: str):
        """Export knowledge graph to a file."""
        self._print_colored(f"  Exporting knowledge graph to {filepath}...\n")

        try:
            from aion_core.knowledge.manager import KnowledgeManager
            km = KnowledgeManager()
            content = await km.export(format="json")
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Exported to {filepath}\n"
            )
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Knowledge graph not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        self._print_colored("")

    # ── mcp ──────────────────────────────────────────────────────────────

    async def _cmd_mcp(self, args: argparse.Namespace):
        """MCP server operations."""
        list_servers = getattr(args, "list", False)
        add_server = getattr(args, "add", None)
        remove_name = getattr(args, "remove", None)

        if list_servers:
            await self._mcp_list()
        elif add_server:
            await self._mcp_add(add_server[0], add_server[1])
        elif remove_name:
            await self._mcp_remove(remove_name)
        else:
            await self._mcp_list()

    async def _mcp_list(self):
        """List MCP servers."""
        self._print_colored(
            f"\n  {Colors.BOLD}MCP Servers{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)

        # Load from config file
        servers = []
        if os.path.exists(_MCP_FILE):
            try:
                with open(_MCP_FILE, encoding="utf-8") as f:
                    servers = json.load(f)
            except (OSError, json.JSONDecodeError):
                pass

        # Also try live listing
        try:
            from aion_core.mcp.registry import MCPRegistry
            registry = MCPRegistry()
            live_servers = registry.list_servers()
            for s in live_servers:
                name = s.get("name", s) if isinstance(s, dict) else s
                status = s.get("status", "connected") if isinstance(s, dict) else "connected"
                self._print_colored(
                    f"  {Colors.GREEN}●{Colors.RESET} {Colors.BRIGHT_WHITE}{name}{Colors.RESET}"
                    f"  {Colors.DIM}({status}){Colors.RESET}\n"
                )
        except ImportError:
            pass

        if not servers and not os.path.exists(_MCP_FILE):
            self._print_colored(f"  {Colors.DIM}No MCP servers configured.{Colors.RESET}\n")
            self._print_colored(
                f"  {Colors.DIM}Use {Colors.CYAN}aion-hand mcp --add name command{Colors.RESET} "
                f"to add one.{Colors.RESET}\n"
            )
        else:
            for server in servers:
                name = server.get("name", server) if isinstance(server, dict) else server
                cmd = server.get("command", "") if isinstance(server, dict) else ""
                self._print_colored(
                    f"  {Colors.BRIGHT_CYAN}▸{Colors.RESET} {Colors.BRIGHT_WHITE}{name}{Colors.RESET}"
                )
                if cmd:
                    self._print_colored(f"  {Colors.DIM}({cmd}){Colors.RESET}")
                self._print_colored("\n")
        self._print_colored("")

    async def _mcp_add(self, name: str, command: str):
        """Add an MCP server."""
        _ensure_config_dir()
        servers = []
        if os.path.exists(_MCP_FILE):
            try:
                with open(_MCP_FILE, encoding="utf-8") as f:
                    servers = json.load(f)
            except (OSError, json.JSONDecodeError):
                servers = []

        # Check for duplicates
        for s in servers:
            if isinstance(s, dict) and s.get("name") == name:
                self._print_colored(
                    f"  {Colors.YELLOW}⚠{Colors.RESET} Server '{name}' already exists. "
                    f"Use --remove first, then add again.{Colors.RESET}\n"
                )
                return

        servers.append({"name": name, "command": command, "added": datetime.now().isoformat()})
        with open(_MCP_FILE, "w", encoding="utf-8") as f:
            json.dump(servers, f, indent=2)

        self._print_colored(
            f"  {Colors.GREEN}✔{Colors.RESET} MCP server {Colors.BRIGHT_CYAN}{name}{Colors.RESET} added.\n"
        )

    async def _mcp_remove(self, name: str):
        """Remove an MCP server."""
        if not os.path.exists(_MCP_FILE):
            self._print_colored(
                f"  {Colors.RED}Error: No MCP servers configured.{Colors.RESET}\n"
            )
            return

        try:
            with open(_MCP_FILE, encoding="utf-8") as f:
                servers = json.load(f)
        except (OSError, json.JSONDecodeError):
            self._print_colored(f"  {Colors.RED}Error reading MCP config.{Colors.RESET}\n")
            return

        original = len(servers)
        servers = [s for s in servers if not (isinstance(s, dict) and s.get("name") == name)]

        if len(servers) < original:
            with open(_MCP_FILE, "w", encoding="utf-8") as f:
                json.dump(servers, f, indent=2)
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} MCP server {Colors.BRIGHT_CYAN}{name}{Colors.RESET} removed.\n"
            )
        else:
            self._print_colored(
                f"  {Colors.RED}Error: MCP server '{name}' not found.{Colors.RESET}\n"
            )

    # ── dynamic ──────────────────────────────────────────────────────────

    async def _cmd_dynamic(self, args: argparse.Namespace):
        """Dynamic agent operations."""
        task = getattr(args, "task", None)
        plan = getattr(args, "plan", None)
        stats = getattr(args, "stats", False)
        complexity = getattr(args, "complexity", 5)

        if stats:
            await self._dynamic_stats()
        elif plan:
            await self._dynamic_plan(plan, complexity)
        elif task:
            await self._dynamic_execute(task, complexity)
        else:
            self._print_colored(
                f"  {Colors.DIM}Usage: aion-hand dynamic \"task\" [--complexity N]{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}       aion-hand dynamic --plan \"task\"{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}       aion-hand dynamic --stats{Colors.RESET}\n"
            )

    async def _dynamic_execute(self, task: str, complexity: int):
        """Execute a task with dynamic agents."""
        self._print_colored(
            f"\n  {Colors.BOLD}Dynamic Agent Execution{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  Task:       {Colors.BRIGHT_WHITE}{task}{Colors.RESET}\n")
        self._print_colored(f"  Complexity: {Colors.BRIGHT_CYAN}{complexity}/10{Colors.RESET}\n\n")

        spinner = StreamSpinner("Dynamic agents working")
        spinner.start()

        try:
            from aion_core.dynamic.manager import DynamicAgentManager
            manager = DynamicAgentManager()
            result = await manager.execute(task, complexity=complexity)
            spinner.stop()
            self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} Dynamic execution complete.\n")
            self._print_colored(f"  {Colors.BRIGHT_WHITE}{result}{Colors.RESET}\n")
        except ImportError:
            spinner.stop()
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Dynamic agents not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        except Exception as exc:
            spinner.stop()
            self._print_colored(f"  {Colors.RED}Error:{Colors.RESET} {exc}\n")
        self._print_colored("")

    async def _dynamic_plan(self, task: str, complexity: int):
        """Show execution plan without executing."""
        self._print_colored(
            f"\n  {Colors.BOLD}Dynamic Execution Plan{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  Task:       {Colors.BRIGHT_WHITE}{task}{Colors.RESET}\n")
        self._print_colored(f"  Complexity: {Colors.BRIGHT_CYAN}{complexity}/10{Colors.RESET}\n\n")

        try:
            from aion_core.dynamic.manager import DynamicAgentManager
            manager = DynamicAgentManager()
            plan = await manager.plan(task, complexity=complexity)
            if isinstance(plan, dict):
                for step_name, step_info in plan.items():
                    self._print_colored(
                        f"  {Colors.BRIGHT_GREEN}▸{Colors.RESET} {Colors.BOLD}{step_name}{Colors.RESET}\n"
                    )
                    self._print_colored(
                        f"    {Colors.DIM}{step_info}{Colors.RESET}\n"
                    )
            elif isinstance(plan, list):
                for step in plan:
                    self._print_colored(
                        f"  {Colors.BRIGHT_GREEN}▸{Colors.RESET} {step}\n"
                    )
            else:
                self._print_colored(f"  {plan}\n")
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Dynamic agents not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        self._print_colored("")

    async def _dynamic_stats(self):
        """Show dynamic agent statistics."""
        self._print_colored(
            f"\n  {Colors.BOLD}Dynamic Agent Statistics{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)

        try:
            from aion_core.dynamic.manager import DynamicAgentManager
            manager = DynamicAgentManager()
            stats = await manager.get_stats()
            for key, value in stats.items():
                self._print_colored(
                    f"  {Colors.BRIGHT_WHITE}{key:<24}{Colors.RESET} {value}\n"
                )
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Dynamic agents not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        self._print_colored("")

    # ── gateway ──────────────────────────────────────────────────────────

    async def _cmd_gateway(self, args: argparse.Namespace):
        """Start messaging gateway."""
        platform = getattr(args, "platform", None)
        start_all = getattr(args, "all", False)
        port = getattr(args, "port", 8080)

        if start_all:
            await self._gateway_start_all(port)
        elif platform:
            await self._gateway_start_platform(platform, port)
        else:
            # Show gateway status and instructions
            config = _load_config()
            gw_config = config.get("gateway", {})
            platforms = ["telegram", "discord", "slack", "webhook", "matrix"]

            self._print_colored(
                f"\n  {Colors.BOLD}Messaging Gateway{Colors.RESET}\n", Colors.CYAN
            )
            self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)

            for p in platforms:
                token = gw_config.get(f"{p}_token", "")
                status = f"{Colors.GREEN}configured{Colors.RESET}" if token else f"{Colors.DIM}not set{Colors.RESET}"
                self._print_colored(f"  {p.capitalize():<12} {status}\n")

            self._print_colored(
                f"\n  {Colors.DIM}Use --platform <name> to start a specific platform{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}Use --all to start all configured platforms{Colors.RESET}\n\n"
            )

    async def _gateway_start_platform(self, platform: str, port: int):
        """Start a specific platform gateway."""
        self._print_colored(
            f"\n  {Colors.BOLD}Starting {platform.upper()} Gateway{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  {Colors.DIM}Press Ctrl+C to stop{Colors.RESET}\n\n")

        try:
            from aion_core.messaging.gateway import Gateway
            gw = Gateway(port=port)
            await gw.start(platform=platform)
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Messaging gateway not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}Would start {platform} gateway on port {port}.{Colors.RESET}\n"
            )
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                pass
        except Exception as exc:
            self._print_colored(f"  {Colors.RED}Error:{Colors.RESET} {exc}\n")

    async def _gateway_start_all(self, port: int):
        """Start all configured platform gateways."""
        config = _load_config()
        gw_config = config.get("gateway", {})
        platforms = ["telegram", "discord", "slack", "webhook", "matrix"]
        configured = [p for p in platforms if gw_config.get(f"{p}_token")]

        if not configured:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} No platforms configured. "
                f"Run 'aion-hand setup' first.{Colors.RESET}\n"
            )
            return

        self._print_colored(
            f"\n  {Colors.BOLD}Starting All Gateways{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(
            f"  Platforms: {', '.join(configured)}\n"
        )
        self._print_colored(f"  {Colors.DIM}Press Ctrl+C to stop{Colors.RESET}\n\n")

        try:
            from aion_core.messaging.gateway import Gateway
            gw = Gateway(port=port)
            await gw.start_all(platforms=configured)
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Messaging gateway not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        except Exception as exc:
            self._print_colored(f"  {Colors.RED}Error:{Colors.RESET} {exc}\n")

    # ── memory ──────────────────────────────────────────────────────────

    async def _cmd_memory(self, args: argparse.Namespace):
        """Memory operations."""
        search = getattr(args, "search", None)
        stats = getattr(args, "stats", False)
        export = getattr(args, "export", False)
        nudge = getattr(args, "nudge", False)

        if search:
            await self._memory_search(search)
        elif nudge:
            await self._memory_nudge()
        elif export:
            await self._memory_export()
        elif stats:
            await self._memory_stats()
        else:
            await self._memory_stats()

    async def _memory_search(self, query: str):
        """Search memory."""
        self._print_colored(
            f"\n  {Colors.BOLD}Memory Search{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  Query: {Colors.BRIGHT_WHITE}{query}{Colors.RESET}\n\n")

        try:
            from aion_core.memory.manager import MemoryManager
            mgr = MemoryManager()
            results = await mgr.search(query, limit=10)
            if results:
                for i, r in enumerate(results, 1):
                    content = r.get("content", str(r))
                    score = r.get("score", 1.0) if isinstance(r, dict) else 1.0
                    self._print_colored(
                        f"  {Colors.BRIGHT_GREEN}{i}.{Colors.RESET} "
                        f"{Colors.BRIGHT_WHITE}[{score:.2f}]{Colors.RESET} {content}\n"
                    )
            else:
                self._print_colored(f"  {Colors.DIM}No results found.{Colors.RESET}\n")
        except ImportError:
            # Fallback: search MEMORY.md
            if os.path.exists(_MEMORY_FILE):
                with open(_MEMORY_FILE, encoding="utf-8") as f:
                    content = f.read()
                q_lower = query.lower()
                found = False
                for line in content.splitlines():
                    if q_lower in line.lower() and line.strip():
                        self._print_colored(f"  {Colors.DIM}{line.strip()}{Colors.RESET}\n")
                        found = True
                if not found:
                    self._print_colored(f"  {Colors.DIM}No matches in MEMORY.md.{Colors.RESET}\n")
            else:
                self._print_colored(f"  {Colors.DIM}No memory data found.{Colors.RESET}\n")
        self._print_colored("")

    async def _memory_stats(self):
        """Show memory statistics."""
        self._print_colored(
            f"\n  {Colors.BOLD}Memory Statistics{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored("  " + "─" * 46 + "\n", Colors.DIM)

        try:
            from aion_core.memory.manager import MemoryManager
            mgr = MemoryManager()
            stats = await mgr.stats()
            for key, value in stats.items():
                self._print_colored(
                    f"  {Colors.BRIGHT_WHITE}{key:<20}{Colors.RESET} {value}\n"
                )
        except ImportError:
            if os.path.exists(_MEMORY_FILE):
                stat = os.stat(_MEMORY_FILE)
                with open(_MEMORY_FILE, encoding="utf-8") as f:
                    content = f.read()
                lines = [line for line in content.splitlines() if line.strip()]
                self._print_colored(f"  {Colors.BRIGHT_WHITE}{'File':<20}{Colors.RESET} {_MEMORY_FILE}\n")
                self._print_colored(f"  {Colors.BRIGHT_WHITE}{'Size':<20}{Colors.RESET} {stat.st_size:,} bytes\n")
                self._print_colored(f"  {Colors.BRIGHT_WHITE}{'Lines':<20}{Colors.RESET} {len(lines)}\n")
                self._print_colored(f"  {Colors.BRIGHT_WHITE}{'Words':<20}{Colors.RESET} {len(content.split()):,}\n")
            else:
                self._print_colored(f"  {Colors.DIM}No memory data found.{Colors.RESET}\n")
        self._print_colored("")

    async def _memory_export(self):
        """Export memory to file."""
        output_path = _MEMORY_FILE
        _ensure_config_dir()

        try:
            from aion_core.memory.manager import MemoryManager
            mgr = MemoryManager()
            content = await mgr.export_markdown()
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(content)
        except ImportError:
            if os.path.exists(_MEMORY_FILE):
                self._print_colored(
                    f"  {Colors.DIM}Memory file already exists at {_MEMORY_FILE}{Colors.RESET}\n"
                )
            else:
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(f"# Aion Hand Memory\n\nExported: {datetime.now().isoformat()}\n\n")

        self._print_colored(
            f"  {Colors.GREEN}✔{Colors.RESET} Memory exported to {Colors.BRIGHT_CYAN}{output_path}{Colors.RESET}\n"
        )

    async def _memory_nudge(self):
        """Force a memory consolidation nudge."""
        self._print_colored(
            f"\n  {Colors.BOLD}Memory Nudge{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  {Colors.DIM}Consolidating memories...{Colors.RESET}\n\n")

        try:
            from aion_core.memory.manager import MemoryManager
            mgr = MemoryManager()
            result = await mgr.nudge()
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Memory nudge complete.\n"
            )
            if result:
                self._print_colored(f"  {Colors.DIM}{result}{Colors.RESET}\n")
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Memory manager not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        self._print_colored("")

    # ── skills ──────────────────────────────────────────────────────────

    async def _cmd_skills(self, args: argparse.Namespace):
        """Skill management."""
        list_skills = getattr(args, "list", False)
        create_name = getattr(args, "create", None)
        evaluate = getattr(args, "evaluate", False)

        if create_name:
            await self._skills_create(create_name)
        elif evaluate:
            await self._skills_evaluate()
        elif list_skills:
            await self._skills_list()
        else:
            await self._skills_list()

    async def _skills_list(self):
        """List all skills."""
        config = _load_config()
        custom_skills = config.get("custom_skills", {})

        self._print_colored(f"\n  {Colors.BOLD}Skills{Colors.RESET}\n", Colors.CYAN)
        self._print_colored("  " + "─" * 56 + "\n", Colors.DIM)

        self._print_colored(f"  {Colors.BOLD}Built-in:{Colors.RESET}\n", Colors.WHITE)
        for name, desc in _KNOWN_SKILLS:
            self._print_colored(
                f"    {Colors.BRIGHT_GREEN}▸{Colors.RESET} {name:<18} {Colors.DIM}{desc}{Colors.RESET}\n"
            )

        if custom_skills:
            self._print_colored(f"\n  {Colors.BOLD}Custom:{Colors.RESET}\n", Colors.WHITE)
            for name, info in custom_skills.items():
                desc = info.get("description", "")
                self._print_colored(
                    f"    {Colors.BRIGHT_MAGENTA}▸{Colors.RESET} {name:<18} {Colors.DIM}{desc}{Colors.RESET}\n"
                )

        total = len(_KNOWN_SKILLS) + len(custom_skills)
        self._print_colored(f"\n  Total: {total} skills\n\n")

    async def _skills_create(self, name: str):
        """Create a new skill."""
        self._print_colored(
            f"  {Colors.CYAN}Enter skill description (or press Enter to skip):{Colors.RESET} "
        )
        try:
            description = input().strip()
        except (EOFError, KeyboardInterrupt):
            self._print_colored(f"\n  {Colors.YELLOW}Cancelled.{Colors.RESET}\n")
            return

        config = _load_config()
        if "custom_skills" not in config:
            config["custom_skills"] = {}
        config["custom_skills"][name] = {
            "description": description,
            "created": datetime.now().isoformat(),
        }
        _save_config(config)
        self._print_colored(
            f"  {Colors.GREEN}✔{Colors.RESET} Skill {Colors.BRIGHT_CYAN}{name}{Colors.RESET} created.\n"
        )

    async def _skills_evaluate(self):
        """Evaluate all skills."""
        self._print_colored(
            f"\n  {Colors.BOLD}Skill Evaluation{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  {Colors.DIM}Evaluating skills...{Colors.RESET}\n\n")

        try:
            from aion_core.agent.core import AionHandAgent
            config = _load_config()
            agent = AionHandAgent(model=config.get("default_model"))
            results = await agent.evaluate_skills()
            for skill_name, score in results.items():
                bar_len = 20
                filled = int(score * bar_len)
                bar = "█" * filled + "░" * (bar_len - filled)
                color = Colors.GREEN if score >= 0.7 else Colors.YELLOW if score >= 0.4 else Colors.RED
                self._print_colored(
                    f"  {skill_name:<20} {color}{bar}{Colors.RESET} {score:.1%}\n"
                )
        except ImportError:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Skill evaluation not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        self._print_colored("")

    # ── cron ────────────────────────────────────────────────────────────

    async def _cmd_cron(self, args: argparse.Namespace):
        """Cron management."""
        list_jobs = getattr(args, "list", False)
        add_job = getattr(args, "add", None)
        remove_id = getattr(args, "remove", None)

        if add_job:
            await self._cron_add(add_job[0], add_job[1])
        elif remove_id:
            await self._cron_remove(remove_id)
        elif list_jobs:
            await self._cron_list()
        else:
            await self._cron_list()

    async def _cron_list(self):
        """List cron jobs."""
        jobs = _load_cron_jobs()

        self._print_colored(f"\n  {Colors.BOLD}Cron Jobs{Colors.RESET}\n", Colors.CYAN)
        self._print_colored("  " + "─" * 62 + "\n", Colors.DIM)

        if not jobs:
            self._print_colored(f"  {Colors.DIM}No cron jobs scheduled.{Colors.RESET}\n")
            self._print_colored(
                f"  {Colors.DIM}Use {Colors.CYAN}aion-hand cron --add \"*/5 * * * *\" \"command\"{Colors.RESET}\n"
            )
        else:
            for job in jobs:
                jid = job.get("id", "?")
                expr = job.get("cron", "")
                cmd = job.get("command", "")
                enabled = job.get("enabled", True)
                status = f"{Colors.GREEN}ON{Colors.RESET}" if enabled else f"{Colors.RED}OFF{Colors.RESET}"
                self._print_colored(
                    f"  {status} {Colors.DIM}[{jid}]{Colors.RESET} "
                    f"{Colors.CYAN}{expr}{Colors.RESET}\n"
                )
                self._print_colored(f"       {Colors.BRIGHT_WHITE}{cmd}{Colors.RESET}\n")
        self._print_colored(f"\n  Total: {len(jobs)} jobs\n\n")

    async def _cron_add(self, expr: str, command: str):
        """Add a cron job."""
        jobs = _load_cron_jobs()
        new_job = {
            "id": str(uuid.uuid4())[:8],
            "cron": expr,
            "command": command,
            "enabled": True,
            "created": datetime.now().isoformat(),
        }
        jobs.append(new_job)
        _save_cron_jobs(jobs)

        self._print_colored(
            f"  {Colors.GREEN}✔{Colors.RESET} Cron job added:\n"
        )
        self._print_colored(f"    {Colors.DIM}ID:      {new_job['id']}{Colors.RESET}\n")
        self._print_colored(f"    {Colors.DIM}Schedule: {expr}{Colors.RESET}\n")
        self._print_colored(f"    {Colors.DIM}Command:  {command}{Colors.RESET}\n\n")

    async def _cron_remove(self, job_id: str):
        """Remove a cron job."""
        jobs = _load_cron_jobs()
        original = len(jobs)
        jobs = [j for j in jobs if j.get("id") != job_id]

        if len(jobs) < original:
            _save_cron_jobs(jobs)
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Cron job {Colors.BRIGHT_CYAN}{job_id}{Colors.RESET} removed.\n"
            )
        else:
            self._print_colored(
                f"  {Colors.RED}Error: No cron job with ID '{job_id}'{Colors.RESET}\n"
            )

    # ── security ─────────────────────────────────────────────────────────

    async def _cmd_security(self, args: argparse.Namespace):
        """Security operations."""
        audit = getattr(args, "audit", False)
        scan_secrets = getattr(args, "scan_secrets", None)
        check_file = getattr(args, "check_file", None)

        if audit:
            await self._security_audit()
        elif scan_secrets:
            await self._security_scan_secrets(scan_secrets)
        elif check_file:
            await self._security_check_file(check_file)
        else:
            self._print_colored(
                f"  {Colors.DIM}Usage: aion-hand security --audit{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}       aion-hand security --scan-secrets <file>{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}       aion-hand security --check-file <path>{Colors.RESET}\n"
            )

    async def _security_audit(self):
        """Run security audit."""
        self._print_colored(
            f"\n  {Colors.BOLD}Security Audit{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)

        checks = []

        # Check for exposed API keys in config
        config = _load_config()
        api_keys = config.get("api_keys", {})
        for provider, key in api_keys.items():
            if key and not key.startswith("$"):
                checks.append((f"{provider} API key in config", "exposed", "warn"))

        # Check for secrets in environment
        for env_var in ["OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GOOGLE_API_KEY"]:
            if os.environ.get(env_var):
                checks.append((f"{env_var}", "set in env", "ok"))

        # Check for sensitive files
        for path in [".env", ".env.local", "secrets.json", "credentials.json"]:
            if os.path.exists(path):
                checks.append((f"Sensitive file: {path}", "found", "warn"))

        # Check security module
        checks.append(
            ("Sandbox module",
             "available" if importlib.util.find_spec("aion_core.security.sandbox") else "not available",
             "ok" if importlib.util.find_spec("aion_core.security.sandbox") else "warn")
        )

        checks.append(
            ("Secret redaction",
             "available" if importlib.util.find_spec("aion_core.security.redact") else "not available",
             "ok" if importlib.util.find_spec("aion_core.security.redact") else "warn")
        )

        checks.append(
            ("File safety checker",
             "available" if importlib.util.find_spec("aion_core.security.filesafety") else "not available",
             "ok" if importlib.util.find_spec("aion_core.security.filesafety") else "warn")
        )

        for name, value, status in checks:
            icon = f"{Colors.GREEN}✔{Colors.RESET}" if status == "ok" else f"{Colors.YELLOW}⚠{Colors.RESET}"
            self._print_colored(f"  {icon} {name:<36} {Colors.DIM}{value}{Colors.RESET}\n")

        warnings = sum(1 for _, _, s in checks if s == "warn")
        if warnings == 0:
            self._print_colored(
                f"\n  {Colors.GREEN}{Colors.BOLD}All checks passed!{Colors.RESET}\n\n"
            )
        else:
            self._print_colored(
                f"\n  {Colors.YELLOW}{warnings} warning(s) found. Review above.{Colors.RESET}\n\n"
            )

    async def _security_scan_secrets(self, filepath: str):
        """Scan a file for leaked secrets."""
        if not os.path.exists(filepath):
            self._print_colored(
                f"  {Colors.RED}Error: File '{filepath}' not found.{Colors.RESET}\n"
            )
            return

        self._print_colored(
            f"\n  {Colors.BOLD}Secret Scanner{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  Scanning: {filepath}\n\n")

        try:
            from aion_core.security.redact import SecretRedactor
            redactor = SecretRedactor()
            with open(filepath, encoding="utf-8") as f:
                content = f.read()
            findings = redactor.scan(content)

            if findings:
                self._print_colored(
                    f"  {Colors.RED}⚠ Found {len(findings)} potential secret(s):{Colors.RESET}\n\n"
                )
                for finding in findings:
                    line = finding.get("line", "?")
                    kind = finding.get("type", "unknown")
                    self._print_colored(
                        f"    {Colors.RED}▸{Colors.RESET} Line {line}: {kind}\n"
                    )
            else:
                self._print_colored(
                    f"  {Colors.GREEN}✔{Colors.RESET} No secrets found.\n"
                )
        except ImportError:
            # Simple regex-based fallback
            import re
            patterns = [
                (r'(?:sk|pk|api)[_-]?[a-zA-Z0-9]{20,}', "API Key"),
                (r'-----BEGIN (?:RSA |EC |DSA )?PRIVATE KEY-----', "Private Key"),
                (r'eyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}', "JWT Token"),
            ]
            with open(filepath, encoding="utf-8") as f:
                lines = f.readlines()

            found = False
            for i, line in enumerate(lines, 1):
                for pattern, kind in patterns:
                    if re.search(pattern, line):
                        self._print_colored(
                            f"  {Colors.RED}▸{Colors.RESET} Line {i}: {kind}\n"
                        )
                        found = True
            if not found:
                self._print_colored(
                    f"  {Colors.GREEN}✔{Colors.RESET} No secrets found.\n"
                )
        self._print_colored("")

    async def _security_check_file(self, filepath: str):
        """Check if a file path is safe to access."""
        self._print_colored(
            f"\n  {Colors.BOLD}File Safety Check{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  Path: {filepath}\n\n")

        try:
            from aion_core.security.filesafety import FileSafetyChecker
            checker = FileSafetyChecker()
            result = await checker.check(filepath)

            if result.get("safe", False):
                self._print_colored(
                    f"  {Colors.GREEN}✔{Colors.RESET} File is safe to access.\n"
                )
            else:
                reason = result.get("reason", "unknown risk")
                self._print_colored(
                    f"  {Colors.RED}✘{Colors.RESET} File is NOT safe: {reason}\n"
                )
        except ImportError:
            # Basic fallback check
            resolved = os.path.abspath(filepath)
            home = os.path.expanduser("~")
            if resolved.startswith(home) or "/tmp" in resolved:
                self._print_colored(
                    f"  {Colors.GREEN}✔{Colors.RESET} Path appears safe (basic check).\n"
                )
            else:
                self._print_colored(
                    f"  {Colors.YELLOW}⚠{Colors.RESET} Cannot verify safety. Install security module.\n"
                )
        self._print_colored("")

    # ── tools ──────────────────────────────────────────────────────────

    async def _cmd_tools(self, args: argparse.Namespace):
        """Tool operations."""
        list_tools = getattr(args, "list", False)
        toolset = getattr(args, "toolset", None)
        search = getattr(args, "search", None)
        stats = getattr(args, "stats", False)

        if search:
            await self._tools_search(search)
        elif stats:
            await self._tools_stats()
        elif list_tools or toolset:
            await self._tools_list(toolset)
        else:
            await self._tools_list(None)

    async def _tools_list(self, toolset_filter: str = None):
        """List all tools, optionally filtered by toolset."""
        config = _load_config()
        disabled_tools = set(config.get("disabled_tools", []))

        self._print_colored(f"\n  {Colors.BOLD}Tools{Colors.RESET}\n", Colors.CYAN)
        self._print_colored("  " + "─" * 62 + "\n", Colors.DIM)

        current_set = None
        count = 0
        for name, desc, toolset in _KNOWN_TOOLS:
            if toolset_filter and toolset != toolset_filter:
                continue
            enabled = name not in disabled_tools
            status = f"{Colors.GREEN}ON {Colors.RESET}" if enabled else f"{Colors.RED}OFF{Colors.RESET}"

            if toolset != current_set:
                current_set = toolset
                self._print_colored(
                    f"\n  {Colors.BOLD}{Colors.WHITE}{toolset.upper()}:{Colors.RESET}\n"
                )
            self._print_colored(
                f"    {status} {Colors.BRIGHT_WHITE}{name:<18}{Colors.RESET} "
                f"{Colors.DIM}{desc}{Colors.RESET}\n"
            )
            count += 1

        self._print_colored(f"\n  Total: {count} tools")
        if toolset_filter:
            self._print_colored(f" (toolset: {toolset_filter})")
        self._print_colored("\n\n")

    async def _tools_search(self, query: str):
        """Search tools by name or description."""
        self._print_colored(
            f"\n  {Colors.BOLD}Tool Search: {query}{Colors.RESET}\n\n", Colors.CYAN
        )

        q = query.lower()
        for name, desc, toolset in _KNOWN_TOOLS:
            if q in name.lower() or q in desc.lower() or q in toolset.lower():
                self._print_colored(
                    f"  {Colors.BRIGHT_GREEN}▸{Colors.RESET} "
                    f"{Colors.BRIGHT_WHITE}{name}{Colors.RESET} "
                    f"({Colors.DIM}{toolset}{Colors.RESET})\n"
                )
                self._print_colored(
                    f"    {Colors.DIM}{desc}{Colors.RESET}\n\n"
                )

    async def _tools_stats(self):
        """Show tool usage statistics."""
        self._print_colored(
            f"\n  {Colors.BOLD}Tool Usage Statistics{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)

        try:
            from aion_core.tools.registry import ToolRegistry
            registry = ToolRegistry()
            stats = registry.get_usage_stats()
            for name, count in stats.items():
                self._print_colored(
                    f"  {Colors.BRIGHT_WHITE}{name:<24}{Colors.RESET} {count} calls\n"
                )
        except ImportError:
            config = _load_config()
            disabled = set(config.get("disabled_tools", []))
            enabled = len(_KNOWN_TOOLS) - len(disabled)
            self._print_colored(
                f"  {Colors.BRIGHT_WHITE}{'Total tools':<24}{Colors.RESET} {len(_KNOWN_TOOLS)}\n"
            )
            self._print_colored(
                f"  {Colors.BRIGHT_WHITE}{'Enabled':<24}{Colors.RESET} {enabled}\n"
            )
            self._print_colored(
                f"  {Colors.BRIGHT_WHITE}{'Disabled':<24}{Colors.RESET} {len(disabled)}\n"
            )
        self._print_colored("")

    # ── providers ───────────────────────────────────────────────────────

    async def _cmd_providers(self, args: argparse.Namespace):
        """Provider management."""
        list_providers = getattr(args, "list", False)
        test_provider = getattr(args, "test", None)
        set_provider = getattr(args, "set", None)

        if test_provider:
            await self._providers_test(test_provider)
        elif set_provider:
            await self._providers_set(set_provider[0], set_provider[1])
        elif list_providers:
            await self._providers_list()
        else:
            await self._providers_list()

    async def _providers_list(self):
        """List all providers."""
        config = _load_config()
        default_model = config.get("default_model", "")

        self._print_colored(f"\n  {Colors.BOLD}Providers{Colors.RESET}\n", Colors.CYAN)
        self._print_colored("  " + "─" * 62 + "\n", Colors.DIM)

        current_provider = None
        for provider, model, available in _KNOWN_PROVIDERS:
            if provider != current_provider:
                current_provider = provider
                self._print_colored(
                    f"\n  {Colors.BOLD}{Colors.WHITE}{provider.upper()}{Colors.RESET}\n"
                )
            marker = "●" if available else "○"
            color = Colors.GREEN if available else Colors.DIM
            full_id = f"{provider}:{model}"
            is_default = full_id == default_model
            default_tag = f" {Colors.GREEN}(default){Colors.RESET}" if is_default else ""
            self._print_colored(
                f"    {color}{marker}{Colors.RESET}  {model:40s}{default_tag}\n"
            )

        self._print_colored(
            f"\n  {Colors.DIM}● cloud  ○ local  |  Default: {default_model or 'not set'}{Colors.RESET}\n\n"
        )

    async def _providers_test(self, provider_name: str):
        """Test a provider connection."""
        self._print_colored(
            f"\n  {Colors.BOLD}Testing Provider: {provider_name}{Colors.RESET}\n", Colors.CYAN
        )
        self._print_colored(f"  {Colors.DIM}Connecting...{Colors.RESET}\n")

        spinner = StreamSpinner("Testing connection")
        spinner.start()

        try:
            from aion_core.providers.factory import ProviderFactory
            factory = ProviderFactory()
            result = await factory.test_provider(provider_name)
            spinner.stop()

            if result.get("success", False):
                self._print_colored(
                    f"\n  {Colors.GREEN}✔{Colors.RESET} Provider {Colors.BRIGHT_CYAN}{provider_name}{Colors.RESET} "
                    f"is working.\n"
                )
                model = result.get("model", "unknown")
                latency = result.get("latency_ms", "?")
                self._print_colored(f"    Model:  {model}\n")
                self._print_colored(f"    Latency: {latency}ms\n")
            else:
                self._print_colored(
                    f"\n  {Colors.RED}✘{Colors.RESET} Provider test failed.\n"
                )
                error = result.get("error", "unknown error")
                self._print_colored(f"    Error: {error}\n")
        except ImportError:
            spinner.stop()
            self._print_colored(
                f"\n  {Colors.YELLOW}⚠{Colors.RESET} Provider module not available. "
                f"Requires configuration.{Colors.RESET}\n"
            )
        except Exception as exc:
            spinner.stop()
            self._print_colored(f"\n  {Colors.RED}Error:{Colors.RESET} {exc}\n")
        self._print_colored("")

    async def _providers_set(self, provider: str, model: str):
        """Set active provider and model."""
        full_id = f"{provider}:{model}"
        config = _load_config()
        config["default_model"] = full_id
        _save_config(config)

        self._print_colored(
            f"  {Colors.GREEN}✔{Colors.RESET} Active provider/model set to "
            f"{Colors.BRIGHT_CYAN}{full_id}{Colors.RESET}\n"
        )

    # ══════════════════════════════════════════════════════════════════════
    #  DOCTOR / BACKUP / SERVE
    # ══════════════════════════════════════════════════════════════════════

    async def _cmd_doctor(self, args: argparse.Namespace):
        """Diagnose Aion installation health."""
        self._print_colored(f"\n  {Colors.BOLD}Aion Hand Doctor{Colors.RESET}\n", Colors.CYAN)
        self._print_colored("  " + "─" * 62 + "\n", Colors.DIM)

        checks_passed = 0
        checks_failed = 0
        warnings = 0

        # Check 1: Python version
        import sys as _sys
        py_ok = _sys.version_info >= (3, 11)
        status = f"{Colors.GREEN}✔{Colors.RESET}" if py_ok else f"{Colors.RED}✘{Colors.RESET}"
        self._print_colored(f"  {status} Python {_sys.version.split()[0]} (>= 3.11 required)\n")
        checks_passed += int(py_ok); checks_failed += int(not py_ok)

        # Check 2: Aion importable
        try:
            import aion_core  # noqa: F401
            self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} aion_core importable\n")
            checks_passed += 1
        except ImportError as exc:
            self._print_colored(f"  {Colors.RED}✘{Colors.RESET} aion_core not importable: {exc}\n")
            checks_failed += 1

        # Check 3: Optional deps
        for dep_name, dep_module in [
            ("rich", "rich"),
            ("pyyaml", "yaml"),
            ("aiohttp", "aiohttp"),
            ("prompt_toolkit", "prompt_toolkit"),
        ]:
            try:
                __import__(dep_module)
                self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} optional dep: {dep_name}\n")
                checks_passed += 1
            except ImportError:
                self._print_colored(f"  {Colors.YELLOW}⚠{Colors.RESET} optional dep missing: {dep_name}\n")
                warnings += 1

        # Check 4: Config dir
        home_dir = Path.home() / ".aion-hand"
        if home_dir.is_dir():
            self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} config dir: {home_dir}\n")
            checks_passed += 1
        else:
            self._print_colored(f"  {Colors.YELLOW}⚠{Colors.RESET} config dir not created yet: {home_dir}\n")
            if getattr(args, "fix", False):
                home_dir.mkdir(parents=True, exist_ok=True)
                self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} created config dir\n")
                checks_passed += 1
            else:
                warnings += 1

        # Check 5: Skills
        skills_dir = home_dir / "skills"
        n_skills = len(list(skills_dir.glob("*.md"))) if skills_dir.is_dir() else 0
        if n_skills > 0:
            self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} {n_skills} skills in {skills_dir}\n")
            checks_passed += 1
        else:
            self._print_colored(f"  {Colors.YELLOW}⚠{Colors.RESET} no user skills installed (use 'aion-hand skills --list')\n")
            warnings += 1

        # Check 6: Personas
        try:
            from aion_core.persona import PersonaManager
            mgr = PersonaManager()
            n_personas = len(mgr.list_personas())
            self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} {n_personas} personas available (active: {mgr.get_active_name()})\n")
            checks_passed += 1
        except Exception as exc:  # noqa: BLE001
            self._print_colored(f"  {Colors.RED}✘{Colors.RESET} persona system error: {exc}\n")
            checks_failed += 1

        # Check 7: API key (any provider)
        has_key = any(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GROQ_API_KEY"))
        if has_key:
            self._print_colored(f"  {Colors.GREEN}✔{Colors.RESET} LLM API key found in env\n")
            checks_passed += 1
        else:
            self._print_colored(f"  {Colors.YELLOW}⚠{Colors.RESET} no LLM API key in env (set OPENAI_API_KEY etc.)\n")
            warnings += 1

        # Summary
        self._print_colored("  " + "─" * 62 + "\n", Colors.DIM)
        summary_color = Colors.GREEN if checks_failed == 0 else Colors.RED
        self._print_colored(
            f"  {summary_color}{checks_passed} passed{Colors.RESET}, "
            f"{Colors.RED if checks_failed else Colors.DIM}{checks_failed} failed{Colors.RESET}, "
            f"{Colors.YELLOW if warnings else Colors.DIM}{warnings} warnings{Colors.RESET}\n\n"
        )

        if checks_failed > 0 and not getattr(args, "fix", False):
            self._print_colored(
                f"  {Colors.DIM}Run with --fix to attempt automatic fixes.\n\n",
                Colors.DIM,
            )

    async def _cmd_backup(self, args: argparse.Namespace):
        """Backup / restore agent state."""
        try:
            from aion_core.backup import BackupManager
        except ImportError as exc:
            self._print_colored(f"  {Colors.RED}✘{Colors.RESET} backup module not available: {exc}\n")
            return

        bm = BackupManager()

        if args.create:
            self._print_colored(f"\n  {Colors.BOLD}Creating backup…{Colors.RESET}\n", Colors.CYAN)
            archive = await bm.backup(label=args.label)
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Backup created: {archive}\n"
                f"  {Colors.DIM}Size: {archive.stat().st_size / 1024:.1f} KB\n\n",
                Colors.DIM,
            )
            return

        if args.restore:
            self._print_colored(f"\n  {Colors.BOLD}Restoring from {args.restore}…{Colors.RESET}\n", Colors.CYAN)
            result = await bm.restore(args.restore, overwrite=True)
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Restored {len(result['extracted'])} items, "
                f"skipped {len(result['skipped'])}\n\n"
            )
            return

        if args.cleanup is not None:
            deleted = bm.cleanup_old(keep=args.cleanup)
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Deleted {deleted} old backups (kept newest {args.cleanup})\n\n"
            )
            return

        # Default: list
        entries = bm.list_backups()
        if not entries:
            self._print_colored(f"\n  {Colors.DIM}No backups found. Use 'aion-hand backup --create' to create one.\n\n")
            return
        self._print_colored(f"\n  {Colors.BOLD}Backups{Colors.RESET}\n", Colors.CYAN)
        self._print_colored("  " + "─" * 62 + "\n", Colors.DIM)
        for e in entries:
            size_kb = e.size_bytes / 1024
            self._print_colored(
                f"  {Colors.WHITE}{e.path.name:50s}{Colors.RESET} "
                f"{Colors.DIM}{size_kb:8.1f} KB  {e.age_days:6.1f} days old{Colors.RESET}\n"
            )
        self._print_colored("\n")

    async def _cmd_serve(self, args: argparse.Namespace):
        """Start the HTTP API server."""
        try:
            from aion_core.api.server import APIServer, APIConfig
        except ImportError as exc:
            self._print_colored(f"  {Colors.RED}✘{Colors.RESET} API module not available: {exc}\n")
            self._print_colored(
                f"  {Colors.DIM}Install with: pip install aiohttp{Colors.RESET}\n"
            )
            return

        logging.basicConfig(
            level=args.log_level.upper(),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )

        self._print_colored(
            f"\n  {Colors.BOLD}Starting Aion HTTP API server{Colors.RESET}\n"
            f"  {Colors.DIM}Host: {args.host}  Port: {args.port}{Colors.RESET}\n\n",
            Colors.CYAN,
        )

        from aion_core.agent.core import AionHand
        agent = AionHand()
        await agent.start()
        try:
            server = APIServer(agent=agent, config=APIConfig(host=args.host, port=args.port))
            await server.serve()
        finally:
            await agent.shutdown()

    # ══════════════════════════════════════════════════════════════════════
    #  INTERACTIVE REPL
    # ══════════════════════════════════════════════════════════════════════

    async def _interactive_repl(self, args: argparse.Namespace = None):
        """Interactive REPL with slash commands, multi-line input, and streaming."""
        self._print_banner()
        _load_history()

        # Try to initialize agent
        agent = None
        model_override = getattr(args, "model", None) if args else None
        config = _load_config()
        model = model_override or config.get("default_model")

        try:
            from aion_core.agent.core import AionHandAgent
            agent = AionHandAgent(model=model)
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Agent initialized"
                f"{f' (model: {Colors.BRIGHT_CYAN}{model}{Colors.RESET})' if model else ''}\n"
            )
        except Exception as exc:
            self._print_colored(
                f"  {Colors.YELLOW}⚠{Colors.RESET} Agent not available: {exc}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}Running in standalone CLI mode. "
                f"Type /help for available commands.{Colors.RESET}\n"
            )

        self._print_colored(
            f"  {Colors.DIM}Type your message and press Enter twice (empty line) to send.\n"
            f"  Type {Colors.CYAN}/help{Colors.DIM} for slash commands.\n\n"
        )

        # Conversation state
        conversation = []
        message_lines = []
        message_count = 0

        try:
            while True:
                # Build prompt
                if message_lines:
                    prompt = f"  {Colors.DIM}│{Colors.RESET} "
                else:
                    prompt = f"{Colors.BRIGHT_GREEN}❯{Colors.RESET} "

                try:
                    line = input(prompt)
                except EOFError:
                    break
                except KeyboardInterrupt:
                    self._print_colored("\n  Use /quit to exit.\n", Colors.YELLOW)
                    message_lines = []
                    continue

                if readline is not None:
                    readline.add_history(line)

                # Slash commands (only on first input line)
                if line.strip().startswith("/") and not message_lines:
                    should_exit = await self._handle_slash_command(
                        line.strip(), agent, conversation
                    )
                    if should_exit:
                        break
                    continue

                # Empty line submits multi-line message
                if line.strip() == "":
                    if message_lines:
                        user_message = "\n".join(message_lines)
                        message_lines = []
                        message_count += 1
                        await self._process_user_message(
                            user_message, agent, conversation, message_count
                        )
                    continue

                # Accumulate multi-line input
                message_lines.append(line)

        finally:
            _save_history()
            self._print_colored(f"\n  {Colors.CYAN}Goodbye!{Colors.RESET}\n")

    async def _process_user_message(
        self, message: str, agent, conversation: list, message_count: int
    ):
        """Send a user message to the agent and display the response."""
        conversation.append({"role": "user", "content": message})

        spinner = StreamSpinner("Thinking")
        spinner.start()

        if agent:
            try:
                kwargs = {"history": conversation[:-1]}
                if self._moa_enabled:
                    kwargs["moa"] = True
                    self._moa_enabled = False

                response = await agent.chat(message, **kwargs)
                spinner.stop()

                self._print_colored(
                    f"\n  {Colors.BRIGHT_MAGENTA}🤖 Aion:{Colors.RESET}\n"
                )
                self._print_wrapped(response, indent=4)
                self._print_colored("")
                conversation.append({"role": "assistant", "content": response})
            except Exception as exc:
                spinner.stop()
                self._print_colored(f"\n  {Colors.RED}Error:{Colors.RESET} {exc}\n")
        else:
            await asyncio.sleep(0.3)
            spinner.stop()
            self._print_colored(
                f"\n  {Colors.BRIGHT_MAGENTA}🤖 Aion (standalone):{Colors.RESET}\n"
            )
            self._print_colored(
                f"  {Colors.DIM}Received {len(message)} characters. "
                f"Connect an agent for full functionality. "
                f"Type /help for commands.{Colors.RESET}\n\n"
            )
            conversation.append(
                {"role": "assistant", "content": "(standalone mode)"}
            )

    async def _handle_slash_command(
        self, command: str, agent, conversation: list
    ) -> bool:
        """Process REPL slash commands. Returns True if should exit."""
        parts = command.split(maxsplit=1)
        cmd = parts[0].lower()
        arg = parts[1].strip() if len(parts) > 1 else ""

        # ── /help ────────────────────────────────────────────────────────
        if cmd == "/help":
            self._print_repl_help()

        # ── /quit /exit /q ────────────────────────────────────────────────
        elif cmd in ("/quit", "/exit", "/q"):
            return True

        # ── /status ──────────────────────────────────────────────────────
        elif cmd == "/status":
            await self._cmd_status(argparse.Namespace(json=False))

        # ── /config ──────────────────────────────────────────────────────
        elif cmd == "/config":
            if arg:
                await self._config_set_value(arg)
            else:
                await self._config_show()

        # ── /memory ───────────────────────────────────────────────────────
        elif cmd == "/memory":
            if arg.startswith("search "):
                await self._memory_search(arg[7:].strip())
            elif arg.startswith("stats") or arg == "stats":
                await self._memory_stats()
            else:
                self._print_colored(
                    f"  {Colors.DIM}Usage: /memory search <query> or /memory stats{Colors.RESET}\n"
                )

        # ── /knowledge ────────────────────────────────────────────────────
        elif cmd == "/knowledge":
            if arg.startswith("search "):
                await self._knowledge_search(arg[7:].strip())
            else:
                await self._knowledge_stats()

        # ── /pipeline ────────────────────────────────────────────────────
        elif cmd == "/pipeline":
            if arg:
                await self._cmd_pipeline(
                    argparse.Namespace(mission=arg, steps=None, verbose=False)
                )
            else:
                self._print_colored(
                    f"  {Colors.DIM}Usage: /pipeline \"mission text\"{Colors.RESET}\n"
                )

        # ── /benchmark ──────────────────────────────────────────────────
        elif cmd == "/benchmark":
            await self._cmd_benchmark(
                argparse.Namespace(category="all", runs=1, output=None)
            )

        # ── /mcp ──────────────────────────────────────────────────────────
        elif cmd == "/mcp":
            if arg.startswith("list"):
                await self._mcp_list()
            else:
                await self._mcp_list()

        # ── /dynamic ─────────────────────────────────────────────────────
        elif cmd == "/dynamic":
            if arg:
                await self._dynamic_execute(arg, complexity=5)
            else:
                self._print_colored(
                    f"  {Colors.DIM}Usage: /dynamic \"task\"{Colors.RESET}\n"
                )

        # ── /tools ───────────────────────────────────────────────────────
        elif cmd == "/tools":
            await self._tools_list(None)

        # ── /providers ───────────────────────────────────────────────────
        elif cmd == "/providers":
            await self._providers_list()

        # ── /provider ───────────────────────────────────────────────────
        elif cmd == "/provider":
            if arg.startswith("set "):
                p = arg[4:].strip().split(maxsplit=1)
                if len(p) == 2:
                    await self._providers_set(p[0], p[1])
                else:
                    self._print_colored(
                        f"  {Colors.DIM}Usage: /provider set provider model{Colors.RESET}\n"
                    )
            else:
                await self._providers_list()

        # ── /model ──────────────────────────────────────────────────────
        elif cmd == "/model":
            config = _load_config()
            model = config.get("default_model", "not set")
            self._print_colored(
                f"  Current model: {Colors.BRIGHT_CYAN}{model}{Colors.RESET}\n"
            )
            if arg:
                config["default_model"] = arg.strip()
                _save_config(config)
                self._print_colored(
                    f"  {Colors.GREEN}✔{Colors.RESET} Model changed to "
                    f"{Colors.BRIGHT_CYAN}{arg.strip()}{Colors.RESET}\n"
                )

        # ── /clear ────────────────────────────────────────────────────────
        elif cmd == "/clear":
            conversation.clear()
            self._print_colored(
                f"\n  {Colors.GREEN}✔{Colors.RESET} Conversation cleared.\n\n"
            )

        # ── /history ─────────────────────────────────────────────────────
        elif cmd == "/history":
            self._print_colored(
                f"\n  {Colors.BOLD}Conversation History{Colors.RESET}\n", Colors.CYAN
            )
            self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)
            if not conversation:
                self._print_colored(f"  {Colors.DIM}No messages yet.{Colors.RESET}\n")
            else:
                for i, msg in enumerate(conversation, 1):
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    if role == "user":
                        self._print_colored(
                            f"  {Colors.BRIGHT_GREEN}{i}. You:{Colors.RESET} "
                            f"{content[:80]}{'...' if len(content) > 80 else ''}\n"
                        )
                    else:
                        self._print_colored(
                            f"  {Colors.BRIGHT_MAGENTA}{i}. Aion:{Colors.RESET} "
                            f"{content[:80]}{'...' if len(content) > 80 else ''}\n"
                        )
            self._print_colored(
                f"\n  {Colors.DIM}Total: {len(conversation)} messages{Colors.RESET}\n\n"
            )

        # ── /export ─────────────────────────────────────────────────────
        elif cmd == "/export":
            if not conversation:
                self._print_colored(
                    f"  {Colors.DIM}Nothing to export — conversation is empty.{Colors.RESET}\n"
                )
            else:
                export_path = os.path.join(_CONFIG_DIR, f"conversation_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
                _ensure_config_dir()
                with open(export_path, "w", encoding="utf-8") as f:
                    json.dump(conversation, f, indent=2, ensure_ascii=False)
                self._print_colored(
                    f"  {Colors.GREEN}✔{Colors.RESET} Conversation exported to "
                    f"{Colors.BRIGHT_CYAN}{export_path}{Colors.RESET}\n"
                )

        # ── /security ────────────────────────────────────────────────────
        elif cmd == "/security":
            if arg.startswith("audit"):
                await self._security_audit()
            else:
                await self._security_audit()

        # ── /skills ──────────────────────────────────────────────────────
        elif cmd == "/skills":
            if arg.startswith("list"):
                await self._skills_list()
            else:
                await self._skills_list()

        # ── /cron ────────────────────────────────────────────────────────
        elif cmd == "/cron":
            if arg.startswith("list"):
                await self._cron_list()
            else:
                await self._cron_list()

        # ── /compact ─────────────────────────────────────────────────────
        elif cmd == "/compact":
            self._print_colored(
                f"\n  {Colors.CYAN}Compressing conversation context...{Colors.RESET}\n"
            )
            if agent and hasattr(agent, "compress_context"):
                try:
                    await agent.compress_context()
                    self._print_colored(
                        f"  {Colors.GREEN}✔{Colors.RESET} Context compressed.\n\n"
                    )
                except Exception as exc:
                    self._print_colored(
                        f"  {Colors.RED}Error: {exc}{Colors.RESET}\n\n"
                    )
            else:
                self._print_colored(
                    f"  {Colors.YELLOW}⚠{Colors.RESET} Context compression requires an agent.\n\n"
                )

        # ── /moa ─────────────────────────────────────────────────────────
        elif cmd == "/moa":
            self._moa_enabled = True
            self._print_colored(
                f"  {Colors.GREEN}✔{Colors.RESET} Mixture-of-agents enabled for next turn.\n"
            )

        # ── /version ────────────────────────────────────────────────────
        elif cmd == "/version":
            self._print_colored(
                f"  Aion Hand version: {Colors.BRIGHT_CYAN}{__version__}{Colors.RESET}\n"
            )

        # ── /goal — autonomous goal loop (Hermes parity) ────────────────
        elif cmd == "/goal":
            if not arg:
                self._print_colored(
                    f"  {Colors.DIM}Usage: /goal <description of the goal>{Colors.RESET}\n"
                )
            elif agent is None:
                self._print_colored(
                    f"  {Colors.YELLOW}⚠{Colors.RESET} Agent required for goal loop.\n"
                )
            else:
                self._print_colored(
                    f"\n  {Colors.BRIGHT_CYAN}▶ Autonomous goal loop{Colors.RESET}\n"
                    f"  {Colors.DIM}Working until the goal is judged complete...{Colors.RESET}\n",
                    Colors.CYAN,
                )
                try:
                    result = await agent.run_goal_loop(arg, max_iterations=10)
                    status = (
                        f"{Colors.GREEN}✔ ACHIEVED{Colors.RESET}"
                        if result.get("achieved")
                        else f"{Colors.YELLOW}● MAX ITERATIONS{Colors.RESET}"
                    )
                    self._print_colored(
                        f"\n  {status} after "
                        f"{len(result.get('iterations', []))} iteration(s).\n\n"
                    )
                except Exception as exc:
                    self._print_colored(f"  {Colors.RED}Goal loop error: {exc}{Colors.RESET}\n\n")

        # ── /loop — re-run a prompt on a timer (Hermes parity) ──────────
        elif cmd == "/loop":
            import re as _re

            m = _re.match(r"(\d+[smh])\s+(.*)", arg)
            if not m or agent is None:
                self._print_colored(
                    f"  {Colors.DIM}Usage: /loop <30s|10m|2h> <prompt to re-run>{Colors.RESET}\n"
                )
            else:
                interval_str, prompt = m.group(1), m.group(2)
                mult = {"s": 1, "m": 60, "h": 3600}
                interval = int(interval_str[:-1]) * mult[interval_str[-1]]
                self._print_colored(
                    f"\n  {Colors.BRIGHT_CYAN}▶ Loop{Colors.RESET}: every "
                    f"{interval_str} — {prompt[:60]}\n"
                    f"  {Colors.DIM}(Ctrl+C to stop){Colors.RESET}\n\n",
                    Colors.CYAN,
                )
                try:
                    while True:
                        result = await agent.chat(prompt)
                        content = result.get("content", "")
                        self._print_colored(
                            f"  {Colors.BRIGHT_MAGENTA}Aion:{Colors.RESET} "
                            f"{content[:300]}\n\n"
                        )
                        await asyncio.sleep(interval)
                except KeyboardInterrupt:
                    self._print_colored(f"  {Colors.DIM}Loop stopped.{Colors.RESET}\n\n")

        # ── /heartbeat — recurring in-session pulse (Hermes parity) ─────
        elif cmd == "/heartbeat":
            import re as _re

            m = _re.match(r"(\d+[smh])\s*(.*)", arg)
            if not m or agent is None:
                self._print_colored(
                    f"  {Colors.DIM}Usage: /heartbeat <30s|10m|2h> [what to check on]{Colors.RESET}\n"
                )
            else:
                interval_str, topic = m.group(1), (m.group(2) or "anything new").strip()
                mult = {"s": 1, "m": 60, "h": 3600}
                interval = int(interval_str[:-1]) * mult[interval_str[-1]]
                self._print_colored(
                    f"\n  {Colors.BRIGHT_CYAN}▶ Heartbeat{Colors.RESET}: every "
                    f"{interval_str}, watching: {topic}\n"
                    f"  {Colors.DIM}(Ctrl+C to stop){Colors.RESET}\n\n",
                    Colors.CYAN,
                )
                try:
                    while True:
                        await asyncio.sleep(interval)
                        result = await agent.chat(
                            f"[heartbeat] Check on: {topic}. "
                            "Report only if something changed."
                        )
                        content = result.get("content", "")
                        if content and "nothing" not in content.lower()[:60]:
                            self._print_colored(
                                f"  {Colors.BRIGHT_MAGENTA}♥{Colors.RESET} "
                                f"{content[:300]}\n\n"
                            )
                except KeyboardInterrupt:
                    self._print_colored(f"  {Colors.DIM}Heartbeat stopped.{Colors.RESET}\n\n")

        # ── /sessions — browse past conversations (Hermes parity) ───────
        elif cmd == "/sessions":
            try:
                from aion_core.state import SessionStore

                store = SessionStore()
                store.initialize()
                sessions = store.list_sessions(limit=15)
                self._print_colored(
                    f"\n  {Colors.BOLD}Recent Sessions{Colors.RESET}\n", Colors.CYAN
                )
                self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)
                if not sessions:
                    self._print_colored(f"  {Colors.DIM}No sessions yet.{Colors.RESET}\n")
                for s in sessions:
                    self._print_colored(
                        f"  {Colors.BRIGHT_CYAN}{s['id']}{Colors.RESET} "
                        f"[{s.get('platform', '?')}] {s.get('message_count', 0)} msgs — "
                        f"{Colors.DIM}{(s.get('updated_at') or '')[:16]}{Colors.RESET}\n"
                    )
                self._print_colored("\n")
            except Exception as exc:
                self._print_colored(f"  {Colors.RED}Sessions error: {exc}{Colors.RESET}\n\n")

        # ── /search — search ALL past conversations (Hermes parity) ─────
        elif cmd == "/search":
            if not arg:
                self._print_colored(
                    f"  {Colors.DIM}Usage: /search <query across all past conversations>{Colors.RESET}\n"
                )
            else:
                try:
                    from aion_core.state import SessionStore

                    store = SessionStore()
                    store.initialize()
                    hits = store.search(arg, limit=10)
                    self._print_colored(
                        f"\n  {Colors.BOLD}Session Search: '{arg}'{Colors.RESET} "
                        f"— {len(hits)} hit(s)\n",
                        Colors.CYAN,
                    )
                    self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)
                    for h in hits:
                        self._print_colored(
                            f"  [{h.get('platform', '?')}] "
                            f"{Colors.BRIGHT_GREEN if h.get('role') == 'user' else Colors.BRIGHT_MAGENTA}"
                            f"{(h.get('content') or '')[:90]}{Colors.RESET}\n"
                            f"  {Colors.DIM}{(h.get('created_at') or '')[:16]} "
                            f"— session {h.get('session_id')}{Colors.RESET}\n"
                        )
                    self._print_colored("\n")
                except Exception as exc:
                    self._print_colored(f"  {Colors.RED}Search error: {exc}{Colors.RESET}\n\n")

        # ── /rollback — undo file changes (Hermes parity) ───────────────
        elif cmd == "/rollback":
            try:
                from aion_core.checkpoints import CheckpointManager

                mgr = CheckpointManager()
                if not arg:
                    checkpoints = mgr.list_checkpoints(limit=10)
                    self._print_colored(
                        f"\n  {Colors.BOLD}Checkpoints{Colors.RESET}\n", Colors.CYAN
                    )
                    self._print_colored("  " + "─" * 52 + "\n", Colors.DIM)
                    if not checkpoints:
                        self._print_colored(f"  {Colors.DIM}No checkpoints yet.{Colors.RESET}\n")
                    for c in checkpoints:
                        self._print_colored(
                            f"  {Colors.BRIGHT_CYAN}{c['id']}{Colors.RESET} "
                            f"{len(c.get('files', []))} file(s) — "
                            f"{Colors.DIM}{c.get('reason', '')[:50]}{Colors.RESET}\n"
                        )
                    self._print_colored(
                        f"\n  {Colors.DIM}Usage: /rollback <checkpoint_id>{Colors.RESET}\n\n"
                    )
                else:
                    result = mgr.rollback(arg.strip())
                    if result.get("success"):
                        self._print_colored(
                            f"  {Colors.GREEN}✔{Colors.RESET} Restored "
                            f"{len(result.get('restored', []))} file(s), "
                            f"removed {len(result.get('removed_new_files', []))} new file(s).\n\n"
                        )
                    else:
                        self._print_colored(
                            f"  {Colors.RED}{result.get('error', 'Rollback failed')}{Colors.RESET}\n\n"
                        )
            except Exception as exc:
                self._print_colored(f"  {Colors.RED}Rollback error: {exc}{Colors.RESET}\n\n")

        # ── Unknown ───────────────────────────────────────────────────────
        else:
            self._print_colored(
                f"  {Colors.YELLOW}Unknown command: {cmd}{Colors.RESET}\n"
                f"  Type {Colors.CYAN}/help{Colors.RESET} for available commands.\n"
            )

        return False

    # ── Banner & Help ─────────────────────────────────────────────────

    def _print_banner(self):
        """Display the ASCII art banner."""
        banner = textwrap.dedent(f"""\

             ╔══════════════════════════════════════════╗
             ║     🤖  AION HAND  🤖                   ║
             ║   The Ultimate Autonomous AI Agent       ║
             ║   v{__version__} | MIT License              ║
             ╚══════════════════════════════════════════╝

        """)
        self._print_colored(banner, Colors.BRIGHT_CYAN)

    def _print_repl_help(self):
        """Display comprehensive REPL help."""
        help_text = textwrap.dedent(f"""\
        {Colors.BOLD}  Slash Commands{Colors.RESET}
        {Colors.DIM}  ───────────────────────────────────────────────────────────────{Colors.RESET}

        {Colors.CYAN}  /help{Colors.RESET}                          Show this help message
        {Colors.CYAN}  /status{Colors.RESET}                         Show system status
        {Colors.CYAN}  /config{Colors.RESET} [key=value]             View or edit configuration
        {Colors.CYAN}  /model{Colors.RESET} [model]                  Show or change current model
        {Colors.CYAN}  /memory{Colors.RESET} search <query>          Search memory
        {Colors.CYAN}  /memory{Colors.RESET} stats                   Memory statistics
        {Colors.CYAN}  /knowledge{Colors.RESET} search <query>         Search knowledge graph
        {Colors.CYAN}  /pipeline{Colors.RESET} "mission"              Run execution pipeline
        {Colors.CYAN}  /benchmark{Colors.RESET}                       Run benchmark suite
        {Colors.CYAN}  /mcp{Colors.RESET} list                       List MCP servers
        {Colors.CYAN}  /dynamic{Colors.RESET} "task"                 Dynamic agent execution
        {Colors.CYAN}  /tools{Colors.RESET}                           List all tools
        {Colors.CYAN}  /providers{Colors.RESET}                       List providers
        {Colors.CYAN}  /provider{Colors.RESET} set <name> <model>     Switch provider/model
        {Colors.CYAN}  /skills{Colors.RESET} list                     List skills
        {Colors.CYAN}  /cron{Colors.RESET} list                      List cron jobs
        {Colors.CYAN}  /security{Colors.RESET} audit                 Run security audit
        {Colors.CYAN}  /clear{Colors.RESET}                          Clear conversation
        {Colors.CYAN}  /history{Colors.RESET}                        Show conversation history
        {Colors.CYAN}  /export{Colors.RESET}                         Export conversation to JSON
        {Colors.CYAN}  /compact{Colors.RESET}                        Compress conversation context
        {Colors.CYAN}  /moa{Colors.RESET}                            Enable mixture-of-agents for next turn
        {Colors.CYAN}  /version{Colors.RESET}                       Show version
        {Colors.CYAN}  /quit{Colors.RESET} or /exit                 Exit the session

        {Colors.BOLD}  Memory & Recovery{Colors.RESET}
        {Colors.DIM}  ───────────────────────────────────────────────────────────────{Colors.RESET}
        {Colors.CYAN}  /sessions{Colors.RESET}                       Browse past sessions (all platforms)
        {Colors.CYAN}  /search{Colors.RESET} <query>                 Search ALL past conversations
        {Colors.CYAN}  /rollback{Colors.RESET} [id]                  List/restore file checkpoints
        {Colors.CYAN}  /goal{Colors.RESET} <description>             Autonomous goal loop
        {Colors.CYAN}  /loop{Colors.RESET} <30s|10m|2h> <prompt>     Re-run a prompt on a timer
        {Colors.CYAN}  /heartbeat{Colors.RESET}                      Keep the agent alive periodically

        {Colors.DIM}  ───────────────────────────────────────────────────────────────{Colors.RESET}
        {Colors.DIM}  Input: Type your message, press Enter on empty line to submit.{Colors.RESET}
        {Colors.DIM}  Use ↑/↓ arrows for history. Multi-line: keep typing, empty line sends.{Colors.RESET}

        """)
        self._print_colored(help_text)

    # ══════════════════════════════════════════════════════════════════════
    #  OUTPUT UTILITIES
    # ══════════════════════════════════════════════════════════════════════

    def _print_colored(self, text: str, color: str = ""):
        """Print text with optional ANSI color codes."""
        if color:
            sys.stdout.write(f"{color}{text}{Colors.RESET}")
        else:
            sys.stdout.write(text)
        sys.stdout.flush()

    def _print_wrapped(self, text: str, indent: int = 4, width: int = 72):
        """Print text wrapped to a given width with indentation."""
        prefix = " " * indent
        paragraphs = text.split("\n")
        for para in paragraphs:
            if not para.strip():
                sys.stdout.write("\n")
                continue
            words = para.split()
            current_line = prefix
            current_len = indent
            for word in words:
                word_len = len(word)
                if current_len + word_len + 1 > width and current_len > indent:
                    sys.stdout.write(current_line + "\n")
                    current_line = prefix + word
                    current_len = indent + word_len
                else:
                    if current_len > indent:
                        current_line += " "
                        current_len += 1
                    current_line += word
                    current_len += word_len
            if current_line.strip():
                sys.stdout.write(current_line + "\n")
        sys.stdout.flush()


# ═══════════════════════════════════════════════════════════════════════════════
#  CRON JOB HELPERS
# ═══════════════════════════════════════════════════════════════════════════════

def _load_cron_jobs() -> list:
    """Load cron jobs from config file."""
    _ensure_config_dir()
    if os.path.exists(_CRON_FILE):
        try:
            with open(_CRON_FILE, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return []
    return []


def _save_cron_jobs(jobs: list):
    """Save cron jobs to config file."""
    _ensure_config_dir()
    with open(_CRON_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, sort_keys=True)


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point for the aion-hand CLI."""
    cli = AionHandCLI()
    cli.run()


if __name__ == "__main__":
    main()
