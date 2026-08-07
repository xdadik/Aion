"""Real integration tests for the Telegram adapter.

These tests ACTUALLY call the Telegram Bot API. They require a real bot
token set in the TG_BOT_TOKEN environment variable, and a TG_CHAT_ID
for the chat to send test messages to.

If the env vars are not set, all tests in this file are SKIPPED — they
never fail in CI without credentials.

To run locally:
    export TG_BOT_TOKEN="123456:ABC-DEF..."
    export TG_CHAT_ID="987654321"   # your own user ID
    pytest tests/test_telegram_integration.py -v
"""

from __future__ import annotations

import asyncio
import os
import time

import pytest

# Skip the entire module if no token is available
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

pytestmark = pytest.mark.skipif(
    not TG_BOT_TOKEN or not TG_CHAT_ID,
    reason="Set TG_BOT_TOKEN and TG_CHAT_ID env vars to run real Telegram tests",
)


# ---------------------------------------------------------------------------
# Import after the skip check so we don't fail collection without a token
# ---------------------------------------------------------------------------

from aion_core.messaging.real_adapters import RealTelegramAdapter, RealMessage  # noqa: E402


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestTelegramConnect:
    """Connection / getMe tests."""

    @pytest.mark.asyncio
    async def test_connect_with_valid_token(self):
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN)
        await adapter.connect()
        assert adapter.is_connected is True
        info = await adapter.get_me()
        assert info.get("username"), "Bot should have a username"
        assert info.get("is_bot") is True
        await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_connect_with_invalid_token_raises(self):
        adapter = RealTelegramAdapter(token="000000000:AAAAAAA-invalid")
        with pytest.raises(RuntimeError, match="getMe failed"):
            await adapter.connect()

    @pytest.mark.asyncio
    async def test_connect_with_empty_token_raises(self):
        with pytest.raises(ValueError, match="token is required"):
            RealTelegramAdapter(token="")


class TestTelegramSendMessage:
    """sendMessage tests."""

    @pytest.mark.asyncio
    async def test_send_text_message(self):
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN)
        await adapter.connect()
        try:
            ok = await adapter.send_text(
                TG_CHAT_ID,
                f"🧪 Aion test: send_text_message at {time.time()}",
            )
            assert ok is True
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_send_markdown_message(self):
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN, parse_mode="Markdown")
        await adapter.connect()
        try:
            ok = await adapter.send_text(
                TG_CHAT_ID,
                f"*Aion Test* — _markdown_ at `{time.time()}`",
            )
            assert ok is True
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_send_html_message(self):
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN, parse_mode="HTML")
        await adapter.connect()
        try:
            ok = await adapter.send_text(
                TG_CHAT_ID,
                f"<b>Aion Test</b> — <i>HTML</i> at <code>{time.time()}</code>",
            )
            assert ok is True
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_send_to_invalid_chat_returns_false(self):
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN)
        await adapter.connect()
        try:
            ok = await adapter.send_text("0", "this should fail")
            assert ok is False
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_send_chat_action_typing(self):
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN)
        await adapter.connect()
        try:
            ok = await adapter.send_chat_action(TG_CHAT_ID, "typing")
            assert ok is True
        finally:
            await adapter.disconnect()


class TestTelegramGetUpdates:
    """getUpdates tests."""

    @pytest.mark.asyncio
    async def test_get_updates_returns_list(self):
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN)
        await adapter.connect()
        try:
            updates = await adapter.get_updates(limit=10, timeout=0)
            assert isinstance(updates, list)
        finally:
            await adapter.disconnect()

    @pytest.mark.asyncio
    async def test_receive_yields_real_messages(self):
        """This test verifies the receive() generator works. We can't
        guarantee a real incoming message within the test window, so we
        just verify the generator doesn't crash for a few seconds."""
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN)
        await adapter.connect()
        try:
            # Try to receive for up to 3 seconds
            received = []
            async def _collect():
                async for msg in adapter.receive():
                    received.append(msg)
                    if len(received) >= 1:
                        return
            try:
                await asyncio.wait_for(_collect(), timeout=3.0)
            except TimeoutError:
                pass  # no message arrived in 3s, that's OK
            # Whatever we got (possibly nothing), the test passes as long as no exception
        finally:
            await adapter.disconnect()


class TestTelegramPhotoAndDocument:
    """sendPhoto / sendDocument tests."""

    @pytest.mark.asyncio
    async def test_send_photo_by_url(self):
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN)
        await adapter.connect()
        try:
            # Use a public-domain test image
            ok = await adapter.send_photo(
                TG_CHAT_ID,
                "https://upload.wikimedia.org/wikipedia/commons/thumb/4/4a/Commons-logo.svg/240px-Commons-logo.svg.png",
                caption="🧪 Aion test image",
            )
            assert ok is True
        finally:
            await adapter.disconnect()


class TestTelegramWebhook:
    """Webhook management tests (no actual webhook server)."""

    @pytest.mark.asyncio
    async def test_delete_webhook(self):
        """Just verify we can call deleteWebhook without error."""
        adapter = RealTelegramAdapter(token=TG_BOT_TOKEN)
        await adapter.connect()
        try:
            # Don't actually set a webhook (would need a public URL)
            # Just verify deleteWebhook works
            ok = await adapter.delete_webhook()
            # Telegram returns ok=True even if no webhook was set
            assert ok is True
        finally:
            await adapter.disconnect()
