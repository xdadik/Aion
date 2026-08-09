"""Aion Hand TUI — main interactive application.

Usage:
    from aion_core.tui import AionTUI
    from aion_core.agent.core import AionHand

    agent = AionHand()
    await agent.start()
    await AionTUI(agent).run()
    await agent.shutdown()

Or from the CLI:
    python -m aion_core.tui
"""

from __future__ import annotations

import asyncio
import os
import shlex
import sys
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from .theme import get_console

# Optional rich imports — guarded so the module loads even without rich.
try:
    from rich.align import Align
    from rich.columns import Columns
    from rich.live import Live
    from rich.markdown import Markdown
    from rich.panel import Panel
    from rich.prompt import Prompt
    from rich.rule import Rule
    from rich.table import Table
    from rich.text import Text

    _RICH = True
except ImportError:  # pragma: no cover
    _RICH = False
    Panel = None  # type: ignore[assignment]
    Markdown = None  # type: ignore[assignment]
    Table = None  # type: ignore[assignment]
    Text = None  # type: ignore[assignment]
    Rule = None  # type: ignore[assignment]
    Align = None  # type: ignore[assignment]
    Columns = None  # type: ignore[assignment]
    Live = None  # type: ignore[assignment]
    Prompt = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# BANNER
# ---------------------------------------------------------------------------

BANNER = r"""
   █████╗ ██╗  ██╗ █████╗ ██████╗ ███████╗██╗  ██╗
  ██╔══██╗██║ ██╔╝██╔══██╗██╔══██╗██╔════╝██║  ██║
  ███████║████╔╝ ███████║██████╔╝█████╗  ██████║
  ██╔══██║██╔═██╗ ██╔══██║██╔══██╗██╔══╝  ██╔══██║
  ██║  ██║██║  ██╗██║  ██║██║  ██║███████╗██║  ██║
  ╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚═╝  ╚═╝╚══════╝╚═╝  ╚═╝
"""


# ---------------------------------------------------------------------------
# CHAT HISTORY ITEM
# ---------------------------------------------------------------------------


@dataclass
class ChatItem:
    """One item in the visible chat history."""

    role: str  # "user" | "agent" | "tool" | "system" | "error"
    content: str
    tool_name: str | None = None
    tool_args: dict[str, Any] | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))
    tokens: int = 0


# ---------------------------------------------------------------------------
# COMMANDS
# ---------------------------------------------------------------------------

COMMANDS: dict[str, str] = {
    "/help": "Show this help",
    "/quit": "Exit Aion (also: /exit, Ctrl-D)",
    "/exit": "Alias for /quit",
    "/reset": "Clear conversation history (memory is preserved)",
    "/memory": "Show recent long-term memories",
    "/skills": "List loaded skills",
    "/tools": "List available tools",
    "/config": "Show current agent configuration",
    "/state": "Show agent state machine status",
    "/save": "Save current conversation to ~/.aion-hand/conversation.md",
    "/persona": "Show / switch active persona (SOUL.md)",
    "/platforms": "List messaging platform adapters",
    "/cron": "List scheduled cron tasks",
    "/clear": "Clear the screen",
    "/cost": "Show cumulative token usage this session",
    "/benchmark": "Run the built-in benchmark suite",
}


# ---------------------------------------------------------------------------
# MAIN TUI
# ---------------------------------------------------------------------------


class AionTUI:
    """Interactive Rich-based TUI for an AionHand agent.

    The TUI is intentionally tolerant: every optional feature degrades
    gracefully. If `rich` is missing, output falls back to plain text.
    If the agent has no `memory_manager` / `skill_engine` / etc., the
    relevant panels simply say "not loaded".
    """

    def __init__(self, agent: Any, *, prompt_prefix: str = "You"):
        self.agent = agent
        self.console = get_console()
        self.prompt_prefix = prompt_prefix
        self.history: list[ChatItem] = []
        self._total_tokens: int = 0
        self._running: bool = False

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main loop. Returns when user types /quit or sends EOF."""
        self._running = True
        self._print_banner()
        self._print_help_short()

        while self._running:
            try:
                user_input = await self._read_input()
            except (EOFError, KeyboardInterrupt):
                self._print_system("Goodbye.")
                break

            if not user_input.strip():
                continue

            # Slash command?
            if user_input.startswith("/"):
                handled = await self._handle_command(user_input.strip())
                if handled == "quit":
                    break
                continue

            # Otherwise: chat with the agent
            await self._chat_turn(user_input)

    # ------------------------------------------------------------------
    #  Input
    # ------------------------------------------------------------------

    async def _read_input(self) -> str:
        """Read one user input line. Multi-line if input ends with '\\'.
        Uses prompt_toolkit if available for history + emacs/vi editing;
        falls back to builtin input()."""
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.history import FileHistory

            history_path = os.path.expanduser("~/.aion-hand/tui_history")
            os.makedirs(os.path.dirname(history_path), exist_ok=True)
            if not hasattr(self, "_prompt_session"):
                self._prompt_session = PromptSession(history=FileHistory(history_path))
            text = await self._prompt_session.prompt_async(
                "\n[bold #FBBF24]You[/] > ",
                multiline=False,
            )
        except ImportError:
            # Fall back to builtin input — runs in executor to stay async-safe.
            loop = asyncio.get_event_loop()
            text = await loop.run_in_executor(None, input, "\nYou > ")

        # Allow explicit multi-line with trailing backslash
        while text.endswith("\\"):
            more = (
                await asyncio.get_event_loop().run_in_executor(None, input, "... ")
                if "prompt_toolkit" not in sys.modules
                else await self._prompt_session.prompt_async("... ")
            )
            text = text[:-1] + "\n" + more

        return text

    # ------------------------------------------------------------------
    #  Chat
    # ------------------------------------------------------------------

    async def _chat_turn(self, user_message: str) -> None:
        """One user -> agent exchange."""
        self.history.append(ChatItem(role="user", content=user_message))
        self._print_user(user_message)

        # Spinner / status while thinking
        with self.console.status("[aion.brand]Aion is thinking…[/]", spinner="dots"):
            try:
                result = await self.agent.chat(user_message)
            except Exception as exc:  # noqa: BLE001 - surface to user
                self.history.append(
                    ChatItem(role="error", content=f"{type(exc).__name__}: {exc}")
                )
                self._print_error(f"{type(exc).__name__}: {exc}")
                return

        if not isinstance(result, dict):
            result = {"content": str(result)}

        content = result.get("content", "") or "(no response)"
        tools_used = result.get("tools_used", [])
        metadata = result.get("metadata", {}) or {}
        tokens = int(metadata.get("total_tokens", 0) or 0)
        self._total_tokens += tokens

        # Show tool calls (if any) as collapsible panels
        for tc in tools_used:
            name = tc.get("name", "?") if isinstance(tc, dict) else str(tc)
            args = tc.get("arguments", {}) if isinstance(tc, dict) else {}
            self._print_tool_call(name, args)
            self.history.append(
                ChatItem(role="tool", content="", tool_name=name, tool_args=args)
            )

        # Render the agent response as markdown
        self._print_agent(content, tokens)
        self.history.append(ChatItem(role="agent", content=content, tokens=tokens))

    # ------------------------------------------------------------------
    #  Commands
    # ------------------------------------------------------------------

    async def _handle_command(self, raw: str) -> str | None:
        """Handle a /command. Returns 'quit' to terminate, None otherwise."""
        try:
            parts = shlex.split(raw)
        except ValueError:
            parts = raw.split()
        cmd = parts[0].lower()
        args = parts[1:]

        if cmd in ("/quit", "/exit"):
            return "quit"
        if cmd == "/help":
            self._print_help_full()
        elif cmd == "/reset":
            self._reset_conversation()
        elif cmd == "/clear":
            os.system("clear" if os.name != "nt" else "cls")
        elif cmd == "/memory":
            await self._show_memory()
        elif cmd == "/skills":
            await self._show_skills()
        elif cmd == "/tools":
            await self._show_tools()
        elif cmd == "/config":
            self._show_config()
        elif cmd == "/state":
            self._show_state()
        elif cmd == "/save":
            self._save_conversation()
        elif cmd == "/persona":
            await self._show_persona(args)
        elif cmd == "/platforms":
            self._show_platforms()
        elif cmd == "/cron":
            self._show_cron()
        elif cmd == "/cost":
            self._print_system(
                f"Total tokens this session: [bold]{self._total_tokens:,}[/]"
            )
        elif cmd == "/benchmark":
            await self._run_benchmark()
        else:
            self._print_error(f"Unknown command: {cmd}. Type /help for the list.")
        return None

    # ------------------------------------------------------------------
    #  Command implementations
    # ------------------------------------------------------------------

    def _print_help_full(self) -> None:
        if not _RICH:
            for k, v in COMMANDS.items():
                print(f"  {k:14} {v}")
            return
        tbl = Table(
            title="Aion Commands",
            border_style="aion.border",
            show_header=True,
            header_style="aion.brand",
        )
        tbl.add_column("Command", style="aion.tag", no_wrap=True)
        tbl.add_column("Description", style="white")
        for k, v in COMMANDS.items():
            tbl.add_row(k, v)
        self.console.print(tbl)

    def _print_help_short(self) -> None:
        self._print_system(
            "Type a message to chat. Type [aion.tag]/help[/] for commands. "
            "[aion.meta]Ctrl-D or /quit to exit.[/]"
        )

    def _reset_conversation(self) -> None:
        self.history.clear()
        self._total_tokens = 0
        # If the agent has a context_engine, reset its working memory
        ctx = getattr(self.agent, "context_engine", None)
        if ctx is not None and hasattr(ctx, "reset"):
            try:
                ctx.reset()
            except Exception:  # noqa: BLE001
                pass
        self._print_system("Conversation reset. Long-term memory preserved.")

    async def _show_memory(self) -> None:
        mm = getattr(self.agent, "memory_manager", None)
        if mm is None:
            self._print_system("Memory manager not loaded.")
            return
        try:
            # Try several common method names; memory APIs vary across versions.
            entries: list[Any] = []
            for method in (
                "recent_memories",
                "all_memories",
                "get_recent",
                "list_memories",
            ):
                fn = getattr(mm, method, None)
                if callable(fn):
                    entries = fn(10) if method != "get_recent" else fn(10)
                    break
        except Exception as exc:  # noqa: BLE001
            self._print_error(f"Could not load memories: {exc}")
            return

        if not entries:
            self._print_system("No long-term memories yet.")
            return

        if not _RICH:
            for e in entries[:10]:
                print(f"  - {e}")
            return
        tbl = Table(
            title="Recent Memories",
            border_style="aion.border",
            header_style="aion.brand",
        )
        tbl.add_column("Layer", style="aion.tag", width=8)
        tbl.add_column("Content", style="white", overflow="fold")
        for e in entries[:10]:
            layer = getattr(e, "layer", getattr(e, "type", "?"))
            text = getattr(e, "content", getattr(e, "text", str(e)))[:200]
            tbl.add_row(str(layer), text)
        self.console.print(tbl)

    async def _show_skills(self) -> None:
        se = getattr(self.agent, "skill_engine", None)
        if se is None:
            self._print_system("Skill engine not loaded.")
            return
        try:
            skills = se.list_skills() if hasattr(se, "list_skills") else []
        except Exception as exc:  # noqa: BLE001
            self._print_error(f"Could not list skills: {exc}")
            return
        if not skills:
            self._print_system(
                "No skills loaded. Add SKILL.md files to ~/.aion-hand/skills/"
            )
            return
        if not _RICH:
            for s in skills:
                print(f"  - {s}")
            return
        tbl = Table(
            title=f"Loaded Skills ({len(skills)})",
            border_style="aion.border",
            header_style="aion.brand",
        )
        tbl.add_column("Name", style="aion.tag")
        tbl.add_column("Status", style="white", width=10)
        tbl.add_column("Uses", style="aion.number", justify="right", width=6)
        tbl.add_column("Success", style="aion.success", justify="right", width=10)
        for s in skills:
            name = getattr(s, "name", str(s))
            status = getattr(s, "status", "?")
            uses = getattr(s, "usage_count", 0)
            sr = getattr(s, "success_rate", 0.0)
            tbl.add_row(name, str(status), str(uses), f"{sr:.0%}")
        self.console.print(tbl)

    async def _show_tools(self) -> None:
        tr = getattr(self.agent, "tool_registry", None)
        if tr is None:
            self._print_system("Tool registry not loaded.")
            return
        try:
            tools = tr.list_tools() if hasattr(tr, "list_tools") else []
        except Exception as exc:  # noqa: BLE001
            self._print_error(f"Could not list tools: {exc}")
            return
        if not tools:
            self._print_system("No tools registered.")
            return
        if not _RICH:
            for t in tools:
                print(f"  - {t}")
            return
        tbl = Table(
            title=f"Available Tools ({len(tools)})",
            border_style="aion.border",
            header_style="aion.brand",
        )
        tbl.add_column("Name", style="aion.tool")
        tbl.add_column("Toolset", style="aion.tag", width=12)
        tbl.add_column("Approval", style="aion.warning", width=10)
        tbl.add_column("Description", style="white", overflow="fold")
        for t in tools[:50]:
            name = getattr(t, "name", str(t))
            toolset = getattr(t, "toolset", "-")
            appr = "yes" if getattr(t, "requires_approval", False) else "no"
            desc = (getattr(t, "description", "") or "")[:80]
            tbl.add_row(name, str(toolset), appr, desc)
        self.console.print(tbl)

    def _show_config(self) -> None:
        cfg = getattr(self.agent, "config", None)
        if cfg is None:
            self._print_system("No config object on agent.")
            return
        try:
            data = cfg.to_dict() if hasattr(cfg, "to_dict") else vars(cfg)
        except Exception:  # noqa: BLE001
            data = {"<error>": "could not serialise config"}
        if not _RICH:
            for k, v in data.items():
                print(f"  {k} = {v}")
            return
        tbl = Table(
            title="Agent Configuration",
            border_style="aion.border",
            header_style="aion.brand",
        )
        tbl.add_column("Key", style="aion.tag")
        tbl.add_column("Value", style="white", overflow="fold")
        for k, v in sorted(data.items()):
            tbl.add_row(k, str(v)[:120])
        self.console.print(tbl)

    def _show_state(self) -> None:
        state = getattr(self.agent, "state", None)
        if state is None:
            self._print_system("Agent state unavailable.")
            return
        self._print_system(f"Agent state: [aion.tag]{state}[/]")

    def _save_conversation(self) -> None:
        path = os.path.expanduser("~/.aion-hand/conversation.md")
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"# Aion Conversation — {datetime.now().isoformat()}\n\n")
            for item in self.history:
                f.write(f"## [{item.timestamp}] {item.role}\n\n{item.content}\n\n")
        self._print_system(f"Conversation saved to {path}")

    async def _show_persona(self, args: list[str]) -> None:
        try:
            from aion_core.persona import PersonaManager
        except ImportError:
            self._print_system("Persona module not available.")
            return
        mgr = PersonaManager()
        if not args:
            current = mgr.get_active_name()
            all_personas = mgr.list_personas()
            self._print_system(f"Active persona: [aion.tag]{current}[/]")
            if all_personas:
                self._print_system("Available: " + ", ".join(all_personas))
            return
        # Switch
        name = args[0]
        ok = mgr.set_active(name)
        if ok:
            self._print_system(f"Switched persona to [aion.tag]{name}[/]")
        else:
            self._print_error(f"No such persona: {name}")

    def _show_platforms(self) -> None:
        try:
            from aion_core.messaging.platforms import PlatformType
        except ImportError:
            self._print_system("Messaging module not available.")
            return
        if not _RICH:
            for p in PlatformType:
                print(f"  - {p.value}")
            return
        tbl = Table(
            title="Messaging Platform Adapters",
            border_style="aion.border",
            header_style="aion.brand",
        )
        tbl.add_column("Platform", style="aion.tool")
        tbl.add_column("Adapter Class", style="aion.meta")
        for p in PlatformType:
            tbl.add_row(p.value, p.name)
        self.console.print(tbl)

    def _show_cron(self) -> None:
        cs = getattr(self.agent, "cron_scheduler", None)
        if cs is None:
            self._print_system("Cron scheduler not loaded.")
            return
        try:
            tasks = cs.list_tasks() if hasattr(cs, "list_tasks") else []
        except Exception as exc:  # noqa: BLE001
            self._print_error(f"Could not list cron tasks: {exc}")
            return
        if not tasks:
            self._print_system("No scheduled tasks.")
            return
        if not _RICH:
            for t in tasks:
                print(f"  - {t}")
            return
        tbl = Table(
            title="Scheduled Tasks",
            border_style="aion.border",
            header_style="aion.brand",
        )
        tbl.add_column("Name", style="aion.tag")
        tbl.add_column("Schedule", style="white")
        tbl.add_column("Next Run", style="aion.meta")
        for t in tasks:
            tbl.add_row(
                getattr(t, "name", "?"),
                getattr(t, "schedule", "?"),
                str(getattr(t, "next_run", "?")),
            )
        self.console.print(tbl)

    async def _run_benchmark(self) -> None:
        self._print_system("Running benchmark suite… (this may take a moment)")
        try:
            from aion_core.benchmark.runner import BenchmarkRunner

            runner = BenchmarkRunner(agent=self.agent)
            # run_full_benchmark is the canonical name; fall back to run_all if patched
            if hasattr(runner, "run_full_benchmark"):
                report = await runner.run_full_benchmark()
            elif hasattr(runner, "run_all"):
                report = await runner.run_all()
            else:
                self._print_error("BenchmarkRunner has no run method")
                return
            # report is a BenchmarkReport, not a list
            results = getattr(report, "task_results", []) or []
            if not _RICH:
                print(
                    f"Score: {getattr(report, 'overall_score', 0):.2f}  Passed: {getattr(report, 'passed', 0)}/{getattr(report, 'total_tasks', 0)}"
                )
                for r in results:
                    print(f"  {r}")
                return
            tbl = Table(
                title=f"Benchmark Report (score: {getattr(report, 'overall_score', 0):.2f})",
                border_style="aion.border",
                header_style="aion.brand",
            )
            tbl.add_column("Task", style="aion.tag")
            tbl.add_column("Score", style="aion.number", justify="right")
            tbl.add_column("Time (s)", style="white", justify="right")
            tbl.add_column("Tokens", style="aion.meta", justify="right")
            for r in results:
                tbl.add_row(
                    str(r.get("task_name", r.get("task_id", "?"))),
                    f"{r.get('score', 0):.2f}",
                    f"{r.get('time_elapsed', 0):.2f}",
                    str(r.get("tokens_used", 0)),
                )
            self.console.print(tbl)
        except Exception as exc:  # noqa: BLE001
            self._print_error(f"Benchmark failed: {exc}")

    # ------------------------------------------------------------------
    #  Rendering helpers
    # ------------------------------------------------------------------

    def _print_banner(self) -> None:
        if not _RICH:
            print(BANNER)
            return
        self.console.print(Align.center(Text(BANNER, style="aion.brand")))
        self.console.print(
            Align.center(
                Text(
                    "The self-improving autonomous AI agent framework",
                    style="aion.meta",
                )
            )
        )
        self.console.print(
            Align.center(
                Text(
                    "Combining OpenClaw · Hermes · NullClaw · CrewAI · AutoGPT · LangGraph",
                    style="aion.muted",
                )
            )
        )
        self.console.print(Rule(style="aion.border"))

    def _print_user(self, text: str) -> None:
        if not _RICH:
            print(f"\n[You] {text}")
            return
        self.console.print(
            Panel(
                Text(text),
                title="[aion.user]You[/]",
                border_style="aion.user",
                title_align="left",
                padding=(0, 1),
            )
        )

    def _print_agent(self, text: str, tokens: int = 0) -> None:
        if not _RICH:
            print(f"\n[Aion] {text}")
            return
        body = Markdown(text) if "```" in text or text.startswith("#") else Text(text)
        title = "[aion.agent]Aion[/]"
        if tokens:
            title += f" [aion.meta]· {tokens:,} tokens[/]"
        self.console.print(
            Panel(
                body,
                title=title,
                border_style="aion.agent",
                title_align="left",
                padding=(0, 1),
            )
        )

    def _print_tool_call(self, name: str, args: dict[str, Any]) -> None:
        if not _RICH:
            print(f"\n[tool] {name}({args})")
            return
        args_str = ", ".join(f"{k}={v!r}" for k, v in (args or {}).items())
        if len(args_str) > 200:
            args_str = args_str[:200] + "…"
        self.console.print(
            Panel(
                Text(f"{name}({args_str})", style="aion.tool"),
                title="[aion.tool]tool call[/]",
                border_style="aion.tool",
                title_align="left",
                padding=(0, 1),
            )
        )

    def _print_system(self, text: str) -> None:
        if not _RICH:
            print(f"[system] {text}")
            return
        self.console.print(Text(text, style="aion.system"))

    def _print_error(self, text: str) -> None:
        if not _RICH:
            print(f"[ERROR] {text}", file=sys.stderr)
            return
        self.console.print(
            Panel(
                Text(text, style="aion.error"),
                title="[aion.error]error[/]",
                border_style="aion.error",
                title_align="left",
                padding=(0, 1),
            )
        )


# ---------------------------------------------------------------------------
#  Module entry point
# ---------------------------------------------------------------------------


async def _main() -> None:
    """`python -m aion_core.tui` entry point."""
    from aion_core.agent.core import AionHand

    agent = AionHand()
    await agent.start()
    try:
        await AionTUI(agent).run()
    finally:
        await agent.shutdown()


if __name__ == "__main__":
    asyncio.run(_main())
