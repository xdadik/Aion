"""Real working messaging platform adapters.

Unlike the stub adapters in `aion_core.messaging.platforms` (which only
store messages in a buffer for testing), these adapters actually call
the real platform APIs.

Currently implemented:
    - RealTelegramAdapter — full Telegram Bot API via urllib (no aiohttp dep)
    - RealDiscordAdapter  — Discord webhook (simple, no gateway)
    - RealSlackAdapter    — Slack webhook (incoming-webhook based)
    - RealWebhookAdapter  — generic HTTP webhook (POST JSON to a URL)

All adapters use only the Python standard library (urllib.request via
asyncio executor). If `aiohttp` is installed, it's used for true async I/O.

Usage:
    from aion_core.messaging.real_adapters import RealTelegramAdapter

    adapter = RealTelegramAdapter(token="123:abc", chat_id="456")
    await adapter.connect()
    await adapter.send_text("456", "Hello from Aion!")
    async for msg in adapter.receive():
        print(msg)
"""

from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any

logger = logging.getLogger("aion_hand.messaging.real")


# ---------------------------------------------------------------------------
# Detect aiohttp for true async I/O
# ---------------------------------------------------------------------------

try:
    import aiohttp  # type: ignore[import-not-found]
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False


# ---------------------------------------------------------------------------
# Message type
# ---------------------------------------------------------------------------

@dataclass
class RealMessage:
    """A real incoming message from a platform."""
    platform: str
    session_id: str          # chat_id / channel_id / etc.
    sender_id: str
    sender_name: str
    content: str
    message_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    raw: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "platform": self.platform,
            "session_id": self.session_id,
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "content": self.content,
            "message_id": self.message_id,
            "timestamp": self.timestamp,
            "raw": self.raw,
        }


# ---------------------------------------------------------------------------
# HTTP helper (stdlib urllib via executor, or aiohttp if available)
# ---------------------------------------------------------------------------

async def _http_request(
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Make an HTTP request, return parsed JSON. Uses aiohttp if available,
    else falls back to urllib in an executor."""
    if _AIOHTTP_AVAILABLE:
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=timeout)) as session:
                async with session.request(
                    method, url, json=json_body, headers=headers,
                ) as resp:
                    text = await resp.text()
                    try:
                        return json.loads(text) if text else {}
                    except json.JSONDecodeError:
                        return {"_status": resp.status, "_text": text}
        except aiohttp.ClientError as exc:
            return {"_status": 0, "_error": f"{type(exc).__name__}: {exc}"}
    # Fallback: urllib in executor
    def _do() -> dict[str, Any]:
        data = json.dumps(json_body).encode("utf-8") if json_body else None
        hdrs = {"Content-Type": "application/json"}
        if headers:
            hdrs.update(headers)
        req = urllib.request.Request(url, data=data, headers=hdrs, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310
                body = resp.read().decode("utf-8", errors="replace")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            try:
                return json.loads(body) if body else {"_status": exc.code, "_error": str(exc)}
            except json.JSONDecodeError:
                return {"_status": exc.code, "_error": str(exc), "_text": body}
        except (urllib.error.URLError, OSError) as exc:
            # DNS resolution failure, connection refused, etc.
            return {"_status": 0, "_error": f"{type(exc).__name__}: {exc}"}

    return await asyncio.get_event_loop().run_in_executor(None, _do)


# ---------------------------------------------------------------------------
# Abstract base for real adapters
# ---------------------------------------------------------------------------

class RealAdapter(ABC):
    """Base class for real platform adapters that actually call APIs."""

    platform_name: str = "abstract"

    def __init__(self, **config: Any) -> None:
        self._config = config
        self._connected = False
        self._receive_queue: asyncio.Queue[RealMessage] = asyncio.Queue()
        self._background_task: asyncio.Task | None = None

    @abstractmethod
    async def connect(self) -> None:
        ...

    async def disconnect(self) -> None:
        self._connected = False
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()
            try:
                await self._background_task
            except asyncio.CancelledError:
                pass

    @abstractmethod
    async def send_text(self, session_id: str, text: str, **kwargs: Any) -> bool:
        ...

    async def receive(self):  # type: ignore[override]
        """Yield incoming messages from the platform."""
        while self._connected:
            try:
                msg = await asyncio.wait_for(self._receive_queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    @property
    def is_connected(self) -> bool:
        return self._connected


# ---------------------------------------------------------------------------
# Telegram (REAL implementation)
# ---------------------------------------------------------------------------

class RealTelegramAdapter(RealAdapter):
    """Real Telegram Bot API adapter.

    Uses the Telegram Bot API via HTTPS. Supports:
        - getMe (verify token)
        - sendMessage (send text)
        - sendPhoto / sendDocument (send media)
        - getUpdates (long-polling for incoming messages)
        - setWebhook / deleteWebhook (webhook mode)

    Config:
        token:    Bot API token from @BotFather
        chat_id:  Default chat ID (optional)
        parse_mode: "Markdown", "HTML", or "" (plain text)
        timeout:  Long-poll timeout in seconds (default 30)
    """

    platform_name = "telegram"
    API_BASE = "https://api.telegram.org/bot"

    def __init__(
        self,
        token: str,
        chat_id: str = "",
        parse_mode: str = "Markdown",
        timeout: float = 30.0,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        if not token:
            raise ValueError("Telegram bot token is required")
        self._token = token
        self._default_chat_id = chat_id
        self._parse_mode = parse_mode
        self._timeout = timeout
        self._bot_info: dict[str, Any] = {}
        self._last_update_id: int = 0

    async def connect(self) -> None:
        if self._connected:
            return
        # Verify the token with getMe
        result = await _http_request("GET", f"{self.API_BASE}{self._token}/getMe")
        if not result.get("ok"):
            raise RuntimeError(f"Telegram getMe failed: {result}")
        self._bot_info = result.get("result", {})
        logger.info(
            "[telegram] Connected as @%s (id=%s)",
            self._bot_info.get("username", "?"),
            self._bot_info.get("id", "?"),
        )
        self._connected = True
        # Start long-polling
        self._background_task = asyncio.create_task(self._poll_loop(), name="telegram-poll")

    async def send_text(
        self,
        session_id: str,
        text: str,
        *,
        parse_mode: str | None = None,
        reply_to_message_id: int | None = None,
        disable_web_page_preview: bool = False,
        **kwargs: Any,
    ) -> bool:
        if not self._connected:
            logger.error("[telegram] send_text called before connect()")
            return False
        chat_id = session_id or self._default_chat_id
        if not chat_id:
            logger.error("[telegram] No chat_id provided")
            return False
        body: dict[str, Any] = {
            "chat_id": chat_id,
            "text": text,
        }
        # parse_mode: explicit param > adapter default
        pm = parse_mode if parse_mode is not None else self._parse_mode
        if pm:
            body["parse_mode"] = pm
        if reply_to_message_id is not None:
            body["reply_to_message_id"] = reply_to_message_id
        if disable_web_page_preview:
            body["disable_web_page_preview"] = True

        result = await _http_request(
            "POST", f"{self.API_BASE}{self._token}/sendMessage", json_body=body,
        )
        if not result.get("ok"):
            logger.error("[telegram] sendMessage failed: %s", result.get("description"))
            return False
        logger.info("[telegram] sendMessage → chat=%s msg_id=%s", chat_id, result["result"]["message_id"])
        return True

    async def send_photo(self, chat_id: str, photo_url: str, caption: str = "") -> bool:
        """Send a photo by URL."""
        if not self._connected:
            return False
        body = {"chat_id": chat_id, "photo": photo_url}
        if caption:
            body["caption"] = caption
        result = await _http_request(
            "POST", f"{self.API_BASE}{self._token}/sendPhoto", json_body=body,
        )
        return bool(result.get("ok"))

    async def send_document(self, chat_id: str, document_url: str, caption: str = "") -> bool:
        """Send a document by URL."""
        if not self._connected:
            return False
        body = {"chat_id": chat_id, "document": document_url}
        if caption:
            body["caption"] = caption
        result = await _http_request(
            "POST", f"{self.API_BASE}{self._token}/sendDocument", json_body=body,
        )
        return bool(result.get("ok"))

    async def send_chat_action(self, chat_id: str, action: str = "typing") -> bool:
        """Send a chat action indicator (e.g. 'typing')."""
        if not self._connected:
            return False
        result = await _http_request(
            "POST", f"{self.API_BASE}{self._token}/sendChatAction",
            json_body={"chat_id": chat_id, "action": action},
        )
        return bool(result.get("ok"))

    async def get_me(self) -> dict[str, Any]:
        """Return the bot's identity."""
        return self._bot_info

    async def get_updates(self, limit: int = 100, timeout: int | None = None) -> list[dict[str, Any]]:
        """Fetch pending updates (messages) from Telegram."""
        body: dict[str, Any] = {"limit": limit}
        if self._last_update_id:
            body["offset"] = self._last_update_id + 1
        if timeout is not None:
            body["timeout"] = timeout
        result = await _http_request(
            "POST", f"{self.API_BASE}{self._token}/getUpdates",
            json_body=body, timeout=max(60.0, (timeout or 0) + 30),
        )
        if not result.get("ok"):
            return []
        updates = result.get("result", [])
        if updates:
            self._last_update_id = max(u["update_id"] for u in updates)
        return updates

    async def set_webhook(self, url: str) -> bool:
        """Set a webhook URL to receive updates (instead of long-polling)."""
        result = await _http_request(
            "POST", f"{self.API_BASE}{self._token}/setWebhook",
            json_body={"url": url},
        )
        return bool(result.get("ok"))

    async def delete_webhook(self) -> bool:
        """Delete the webhook (revert to long-polling)."""
        result = await _http_request(
            "POST", f"{self.API_BASE}{self._token}/deleteWebhook",
        )
        return bool(result.get("ok"))

    async def _poll_loop(self) -> None:
        """Long-poll getUpdates in a background task."""
        logger.info("[telegram] Long-polling started")
        try:
            while self._connected:
                try:
                    updates = await self.get_updates(timeout=int(self._timeout))
                except Exception as exc:  # noqa: BLE001
                    logger.warning("[telegram] getUpdates error: %s", exc)
                    await asyncio.sleep(5)
                    continue
                for update in updates:
                    msg = self._parse_update(update)
                    if msg is not None:
                        await self._receive_queue.put(msg)
        except asyncio.CancelledError:
            pass
        logger.info("[telegram] Long-polling stopped")

    def _parse_update(self, update: dict[str, Any]) -> RealMessage | None:
        """Convert a Telegram update dict into a RealMessage."""
        msg = update.get("message") or update.get("edited_message") or update.get("channel_post")
        if not msg:
            return None
        chat = msg.get("chat", {})
        sender = msg.get("from", {})
        text = msg.get("text", "")
        return RealMessage(
            platform="telegram",
            session_id=str(chat.get("id", "")),
            sender_id=str(sender.get("id", "")),
            sender_name=sender.get("first_name", "") or sender.get("username", ""),
            content=text,
            message_id=str(msg.get("message_id", "")),
            timestamp=datetime.fromtimestamp(msg.get("date", 0), UTC).isoformat() if msg.get("date") else "",
            raw=msg,
        )


# ---------------------------------------------------------------------------
# Discord (webhook-based — simple, no gateway bot)
# ---------------------------------------------------------------------------

class RealDiscordAdapter(RealAdapter):
    """Real Discord adapter using webhooks.

    Note: this uses Discord's incoming-webhook feature for SENDING.
    For receiving, you'd need the Discord gateway (WebSocket) which is
    more complex — out of scope for the stdlib-only adapter.

    Config:
        webhook_url: Discord channel webhook URL
        username:    Display name (optional, defaults to webhook setting)
        avatar_url:  Avatar URL (optional)
    """

    platform_name = "discord"

    def __init__(
        self,
        webhook_url: str = "",
        username: str = "",
        avatar_url: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._webhook_url = webhook_url
        self._username = username
        self._avatar_url = avatar_url

    async def connect(self) -> None:
        if not self._webhook_url:
            raise ValueError("Discord webhook URL is required")
        # Discord webhooks don't require an explicit connect — just verify URL format
        if "discord.com/api/webhooks" not in self._webhook_url:
            raise ValueError("Invalid Discord webhook URL")
        self._connected = True
        logger.info("[discord] Webhook ready")

    async def send_text(self, session_id: str, text: str, **kwargs: Any) -> bool:
        if not self._connected:
            return False
        body: dict[str, Any] = {"content": text[:2000]}  # Discord limit
        if self._username:
            body["username"] = self._username
        if self._avatar_url:
            body["avatar_url"] = self._avatar_url
        result = await _http_request("POST", self._webhook_url, json_body=body)
        # Discord returns 204 No Content (empty) on success
        if result.get("_status") == 204 or not result:
            logger.info("[discord] sendMessage ok")
            return True
        logger.error("[discord] sendMessage failed: %s", result)
        return False


# ---------------------------------------------------------------------------
# Slack (webhook-based)
# ---------------------------------------------------------------------------

class RealSlackAdapter(RealAdapter):
    """Real Slack adapter using incoming webhooks.

    Config:
        webhook_url: Slack incoming-webhook URL
        channel:     Default channel (optional, overrides webhook default)
        username:    Display name (optional)
        icon_emoji:  Emoji icon (e.g. ":robot_face:")
    """

    platform_name = "slack"

    def __init__(
        self,
        webhook_url: str = "",
        channel: str = "",
        username: str = "",
        icon_emoji: str = "",
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._webhook_url = webhook_url
        self._channel = channel
        self._username = username
        self._icon_emoji = icon_emoji

    async def connect(self) -> None:
        if not self._webhook_url:
            raise ValueError("Slack webhook URL is required")
        if "hooks.slack.com" not in self._webhook_url:
            raise ValueError("Invalid Slack webhook URL")
        self._connected = True
        logger.info("[slack] Webhook ready")

    async def send_text(self, session_id: str, text: str, **kwargs: Any) -> bool:
        if not self._connected:
            return False
        body: dict[str, Any] = {"text": text}
        if self._channel:
            body["channel"] = self._channel
        if self._username:
            body["username"] = self._username
        if self._icon_emoji:
            body["icon_emoji"] = self._icon_emoji
        result = await _http_request("POST", self._webhook_url, json_body=body)
        if result.get("_text") == "ok" or not result:
            logger.info("[slack] sendMessage ok")
            return True
        logger.error("[slack] sendMessage failed: %s", result)
        return False


# ---------------------------------------------------------------------------
# Generic HTTP webhook
# ---------------------------------------------------------------------------

class RealWebhookAdapter(RealAdapter):
    """Generic HTTP webhook adapter — POST JSON to any URL.

    Config:
        url:         Webhook endpoint URL
        secret:      Optional bearer token / shared secret
        method:      HTTP method (default POST)
        headers:     Extra headers (dict)
    """

    platform_name = "webhook"

    def __init__(
        self,
        url: str = "",
        secret: str = "",
        method: str = "POST",
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._url = url
        self._secret = secret
        self._method = method
        self._headers = headers or {}

    async def connect(self) -> None:
        if not self._url:
            raise ValueError("Webhook URL is required")
        self._connected = True
        logger.info("[webhook] Ready → %s", self._url)

    async def send_text(self, session_id: str, text: str, **kwargs: Any) -> bool:
        if not self._connected:
            return False
        body = {
            "session_id": session_id,
            "text": text,
            "platform": "webhook",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        headers = dict(self._headers)
        if self._secret:
            headers["Authorization"] = f"Bearer {self._secret}"
        result = await _http_request(
            self._method, self._url, json_body=body, headers=headers,
        )
        # Consider 2xx success
        status = result.get("_status", 200)
        if 200 <= status < 300 or not result:
            logger.info("[webhook] sendMessage ok")
            return True
        logger.error("[webhook] sendMessage failed: %s", result)
        return False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def create_real_adapter(platform: str, **config: Any) -> RealAdapter:
    """Create a real adapter by platform name.

    Supported platforms:
        - "telegram" → RealTelegramAdapter
        - "discord"  → RealDiscordAdapter
        - "slack"    → RealSlackAdapter
        - "webhook"  → RealWebhookAdapter
    """
    platform = platform.lower().strip()
    if platform == "telegram":
        return RealTelegramAdapter(**config)
    if platform == "discord":
        return RealDiscordAdapter(**config)
    if platform == "slack":
        return RealSlackAdapter(**config)
    if platform == "webhook":
        return RealWebhookAdapter(**config)
    raise ValueError(f"Unknown platform: {platform}. Supported: telegram, discord, slack, webhook")


__all__ = [
    "RealMessage",
    "RealAdapter",
    "RealTelegramAdapter",
    "RealDiscordAdapter",
    "RealSlackAdapter",
    "RealWebhookAdapter",
    "create_real_adapter",
]
