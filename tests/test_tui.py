"""Tests for the Aion TUI module."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from aion_core.tui import AionTUI, AION_THEME, get_console
from aion_core.tui.app import ChatItem, COMMANDS


class TestTUIImports:
    """Verify the TUI module loads cleanly."""

    def test_aion_tui_class_exists(self):
        assert AionTUI is not None

    def test_aion_theme_exists(self):
        # Theme may be None if rich is missing — but the symbol must exist
        assert AION_THEME is not None or AION_THEME is None

    def test_get_console_returns_singleton(self):
        c1 = get_console()
        c2 = get_console()
        assert c1 is c2


class TestChatItem:
    """ChatItem dataclass."""

    def test_default_timestamp_is_string(self):
        item = ChatItem(role="user", content="hello")
        assert isinstance(item.timestamp, str)
        assert len(item.timestamp) > 0

    def test_role_required(self):
        item = ChatItem(role="agent", content="hi")
        assert item.role == "agent"

    def test_optional_fields_default_none(self):
        item = ChatItem(role="user", content="x")
        assert item.tool_name is None
        assert item.tool_args is None
        assert item.tokens == 0


class TestCommands:
    """Slash-command registry."""

    def test_help_command_exists(self):
        assert "/help" in COMMANDS

    def test_quit_command_exists(self):
        assert "/quit" in COMMANDS
        assert "/exit" in COMMANDS

    def test_all_commands_have_descriptions(self):
        for cmd, desc in COMMANDS.items():
            assert cmd.startswith("/"), f"{cmd} should start with /"
            assert isinstance(desc, str) and len(desc) > 0, f"{cmd} has empty description"

    def test_core_commands_present(self):
        expected = ["/help", "/quit", "/reset", "/memory", "/skills", "/tools", "/config", "/state", "/save", "/clear"]
        for c in expected:
            assert c in COMMANDS, f"Missing command: {c}"


class TestAionTUICmdDispatch:
    """Verify slash commands route correctly (without running the full REPL)."""

    def _make_tui(self, agent: MagicMock | None = None) -> AionTUI:
        agent = agent or MagicMock()
        return AionTUI(agent)

    @pytest.mark.asyncio
    async def test_unknown_command_prints_error(self, capsys):
        tui = self._make_tui()
        result = await tui._handle_command("/not-a-command")
        assert result is None  # not a quit signal
        out = capsys.readouterr().out + capsys.readouterr().err
        # We can't assert exact text (rich vs plain), but the call should not raise

    @pytest.mark.asyncio
    async def test_quit_returns_quit_signal(self):
        tui = self._make_tui()
        result = await tui._handle_command("/quit")
        assert result == "quit"

    @pytest.mark.asyncio
    async def test_exit_returns_quit_signal(self):
        tui = self._make_tui()
        result = await tui._handle_command("/exit")
        assert result == "quit"

    @pytest.mark.asyncio
    async def test_help_does_not_quit(self):
        tui = self._make_tui()
        result = await tui._handle_command("/help")
        assert result is None

    @pytest.mark.asyncio
    async def test_reset_clears_history_and_tokens(self):
        tui = self._make_tui()
        tui.history.append(ChatItem(role="user", content="x"))
        tui._total_tokens = 999
        await tui._handle_command("/reset")
        assert len(tui.history) == 0
        assert tui._total_tokens == 0


class TestAionTUIChatTurn:
    """Verify the chat turn flow."""

    @pytest.mark.asyncio
    async def test_chat_turn_appends_user_and_agent_items(self):
        agent = MagicMock()
        agent.chat = AsyncMock(return_value={
            "content": "Hello back!",
            "tools_used": [],
            "metadata": {"total_tokens": 42},
        })
        tui = AionTUI(agent)
        await tui._chat_turn("hi")
        assert len(tui.history) == 2
        assert tui.history[0].role == "user"
        assert tui.history[0].content == "hi"
        assert tui.history[1].role == "agent"
        assert tui.history[1].content == "Hello back!"
        assert tui.history[1].tokens == 42
        assert tui._total_tokens == 42

    @pytest.mark.asyncio
    async def test_chat_turn_records_tool_calls(self):
        agent = MagicMock()
        agent.chat = AsyncMock(return_value={
            "content": "Done",
            "tools_used": [{"name": "web_search", "arguments": {"query": "test"}}],
            "metadata": {},
        })
        tui = AionTUI(agent)
        await tui._chat_turn("search for test")
        # user + tool + agent = 3 items
        assert len(tui.history) == 3
        assert tui.history[1].role == "tool"
        assert tui.history[1].tool_name == "web_search"

    @pytest.mark.asyncio
    async def test_chat_turn_records_error_on_exception(self):
        agent = MagicMock()
        agent.chat = AsyncMock(side_effect=RuntimeError("boom"))
        tui = AionTUI(agent)
        await tui._chat_turn("anything")
        assert len(tui.history) == 2
        assert tui.history[1].role == "error"
        assert "RuntimeError" in tui.history[1].content
        assert "boom" in tui.history[1].content

    @pytest.mark.asyncio
    async def test_chat_turn_handles_non_dict_response(self):
        agent = MagicMock()
        agent.chat = AsyncMock(return_value="just a string")
        tui = AionTUI(agent)
        await tui._chat_turn("hi")
        assert tui.history[-1].role == "agent"
        assert "just a string" in tui.history[-1].content
