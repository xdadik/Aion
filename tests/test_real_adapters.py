"""Tests for the real messaging adapters."""

from __future__ import annotations

import pytest

from aion_core.messaging.real_adapters import (
    RealAdapter,
    RealTelegramAdapter,
    RealDiscordAdapter,
    RealSlackAdapter,
    RealWebhookAdapter,
    RealMessage,
    create_real_adapter,
    _http_request,
)


class TestRealMessage:
    def test_to_dict(self):
        m = RealMessage(
            platform="telegram",
            session_id="123",
            sender_id="456",
            sender_name="Alice",
            content="hello",
            message_id="789",
        )
        d = m.to_dict()
        assert d["platform"] == "telegram"
        assert d["session_id"] == "123"
        assert d["content"] == "hello"
        assert "timestamp" in d


class TestCreateRealAdapter:
    def test_create_telegram(self):
        a = create_real_adapter("telegram", token="123:abc")
        assert isinstance(a, RealTelegramAdapter)

    def test_create_discord(self):
        a = create_real_adapter("discord", webhook_url="https://discord.com/api/webhooks/123/abc")
        assert isinstance(a, RealDiscordAdapter)

    def test_create_slack(self):
        a = create_real_adapter("slack", webhook_url="https://hooks.slack.com/services/xxx/yyy")
        assert isinstance(a, RealSlackAdapter)

    def test_create_webhook(self):
        a = create_real_adapter("webhook", url="https://example.com/hook")
        assert isinstance(a, RealWebhookAdapter)

    def test_unknown_platform_raises(self):
        with pytest.raises(ValueError, match="Unknown platform"):
            create_real_adapter("nonexistent")


class TestTelegramAdapterInit:
    def test_init_requires_token(self):
        with pytest.raises(ValueError, match="token is required"):
            RealTelegramAdapter(token="")

    def test_init_with_options(self):
        a = RealTelegramAdapter(
            token="123:abc",
            chat_id="456",
            parse_mode="HTML",
            timeout=60.0,
        )
        assert a._token == "123:abc"
        assert a._default_chat_id == "456"
        assert a._parse_mode == "HTML"
        assert a._timeout == 60.0


class TestTelegramAdapterParseUpdate:
    def test_parse_text_message(self):
        a = RealTelegramAdapter(token="123:abc")
        update = {
            "update_id": 1,
            "message": {
                "message_id": 100,
                "from": {"id": 111, "first_name": "Alice"},
                "chat": {"id": 222, "type": "private"},
                "date": 1786132340,
                "text": "hello world",
            },
        }
        msg = a._parse_update(update)
        assert msg is not None
        assert msg.platform == "telegram"
        assert msg.session_id == "222"
        assert msg.sender_id == "111"
        assert msg.sender_name == "Alice"
        assert msg.content == "hello world"
        assert msg.message_id == "100"

    def test_parse_non_message_update_returns_none(self):
        a = RealTelegramAdapter(token="123:abc")
        update = {"update_id": 1, "callback_query": {"id": "cb1"}}
        msg = a._parse_update(update)
        assert msg is None

    def test_parse_edited_message(self):
        a = RealTelegramAdapter(token="123:abc")
        update = {
            "update_id": 2,
            "edited_message": {
                "message_id": 200,
                "from": {"id": 111, "username": "bob"},
                "chat": {"id": 222},
                "date": 1786132340,
                "text": "edited text",
            },
        }
        msg = a._parse_update(update)
        assert msg is not None
        assert msg.content == "edited text"
        assert msg.sender_name == "bob"  # username fallback


class TestTelegramAdapterWithoutConnection:
    @pytest.mark.asyncio
    async def test_send_text_before_connect_returns_false(self):
        a = RealTelegramAdapter(token="123:abc")
        ok = await a.send_text("123", "hello")
        assert ok is False

    @pytest.mark.asyncio
    async def test_get_me_before_connect_returns_empty(self):
        a = RealTelegramAdapter(token="123:abc")
        info = await a.get_me()
        assert info == {}


class TestDiscordAdapter:
    @pytest.mark.asyncio
    async def test_connect_requires_webhook_url(self):
        a = RealDiscordAdapter(webhook_url="")
        with pytest.raises(ValueError, match="webhook URL is required"):
            await a.connect()

    @pytest.mark.asyncio
    async def test_connect_rejects_bad_url(self):
        a = RealDiscordAdapter(webhook_url="https://example.com/not-discord")
        with pytest.raises(ValueError, match="Invalid Discord webhook URL"):
            await a.connect()

    @pytest.mark.asyncio
    async def test_send_text_before_connect_returns_false(self):
        a = RealDiscordAdapter(webhook_url="https://discord.com/api/webhooks/123/abc")
        ok = await a.send_text("123", "hello")
        assert ok is False


class TestSlackAdapter:
    @pytest.mark.asyncio
    async def test_connect_requires_webhook_url(self):
        a = RealSlackAdapter(webhook_url="")
        with pytest.raises(ValueError, match="webhook URL is required"):
            await a.connect()

    @pytest.mark.asyncio
    async def test_connect_rejects_bad_url(self):
        a = RealSlackAdapter(webhook_url="https://example.com/not-slack")
        with pytest.raises(ValueError, match="Invalid Slack webhook URL"):
            await a.connect()


class TestWebhookAdapter:
    @pytest.mark.asyncio
    async def test_connect_requires_url(self):
        a = RealWebhookAdapter(url="")
        with pytest.raises(ValueError, match="Webhook URL is required"):
            await a.connect()

    @pytest.mark.asyncio
    async def test_init_with_options(self):
        a = RealWebhookAdapter(
            url="https://example.com/hook",
            secret="my-secret",
            method="PUT",
            headers={"X-Custom": "yes"},
        )
        assert a._url == "https://example.com/hook"
        assert a._secret == "my-secret"
        assert a._method == "PUT"
        assert a._headers == {"X-Custom": "yes"}


class TestHTTPHelper:
    @pytest.mark.asyncio
    async def test_http_request_to_invalid_url_returns_error(self):
        # Use a deliberately bad URL
        result = await _http_request("GET", "https://this-domain-does-not-exist-12345.com/api")
        # Should return an error dict, not raise
        assert isinstance(result, dict)
