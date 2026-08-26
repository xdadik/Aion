"""
Platform adapter system for the Aion Hand AI agent framework.

Provides 20+ messaging platform adapters as structural stubs with realistic
method signatures and logging.  Each adapter stores sent messages in a
``_message_buffer`` for testing and inspection.

Architecture::

    ┌──────────────────────────────────────────────────────────────┐
    │                     PlatformAdapter (ABC)                     │
    └──────────┬──────────────────────────────────────────────────┘
               │
    ┌──────────┼──────────┬──────────┬──────────┬──────────┐
    │ Telegram │ Discord  │  Slack   │ WhatsApp │  Signal  │ ... ×20
    └──────────┴──────────┴──────────┴──────────┴──────────┘
               │
       ┌───────┴───────┐
       │ PlatformRegistry│
       └───────────────┘

Usage::

    from aion_core.messaging.platforms import (
        PlatformType, PlatformAdapter, PlatformRegistry,
        create_platform, validate_platform_config,
    )

    adapter = create_platform(PlatformType.TELEGRAM, {"token": "..."})
    await adapter.connect()
    await adapter.send_text("12345", "Hello!")
    await adapter.disconnect()
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


# ============================================================================
# PlatformType enum
# ============================================================================

class PlatformType(Enum):
    """Enumeration of supported messaging platforms."""
    TELEGRAM = "telegram"
    DISCORD = "discord"
    SLACK = "slack"
    WHATSAPP = "whatsapp"
    SIGNAL = "signal"
    TEAMS = "teams"
    WECHAT = "wechat"
    QQ = "qq"
    FEISHU = "feishu"                 # Lark
    WEIXIN_WORK = "weixin_work"       # WeCom / Enterprise WeChat
    YUANBAO = "yuanbao"               # Tencent Yuanbao
    MATRIX = "matrix"
    IRC = "irc"
    MATTERMOST = "mattermost"
    LINE = "line"
    GOOGLE_CHAT = "google_chat"
    DINGTALK = "dingtalk"
    EMAIL = "email"
    NTFY = "ntfy"
    WEBHOOK = "webhook"


# ============================================================================
# Internal data classes
# ============================================================================

@dataclass
class _StoredMessage:
    """A message stored in the adapter's internal buffer for testing."""
    session_id: str
    msg_type: str          # text, image, file, audio, video, sticker, embed, block, etc.
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    extra: dict[str, Any] = field(default_factory=dict)
    message_id: str = ""


def _generate_message_id() -> str:
    """Generate a short deterministic-ish message ID for stub purposes."""
    raw = f"{time.time_ns()}-{id(asyncio.current_task() or 0)}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _truncate(text: str, max_len: int = 120) -> str:
    """Truncate *text* for log output."""
    return text[:max_len] + "\u2026" if len(text) > max_len else text


# ============================================================================
# PlatformAdapter ABC (extended)
# ============================================================================

class PlatformAdapter(ABC):
    """Abstract base class for all messaging platform adapters.

    Every concrete adapter must implement the abstract methods below.
    The base class provides shared state tracking (``_connected``,
    ``_message_buffer``) and common helper methods.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        self._config = config
        self._connected: bool = False
        self._message_buffer: list[_StoredMessage] = []
        self._receive_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self._background_task: asyncio.Task | None = None

    # -- lifecycle -----------------------------------------------------------

    @abstractmethod
    async def connect(self) -> None:
        """Establish the connection / session with the platform."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        ...

    # -- send operations -----------------------------------------------------

    async def send_text(self, session_id: str, text: str) -> bool:
        """Send a text message.  Returns ``True`` on success."""
        if not self._connected:
            logger.warning("[%s] send_text while disconnected", self.get_platform_name())
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="text", content=text, message_id=msg_id)
        )
        logger.info("[%s] send_text → session=%s  text=%s", self.get_platform_name(), session_id, _truncate(text))
        return True

    async def send_image(self, session_id: str, image_url: str, caption: str = "") -> bool:
        """Send an image with an optional caption."""
        if not self._connected:
            logger.warning("[%s] send_image while disconnected", self.get_platform_name())
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="image", content=image_url,
                           extra={"caption": caption}, message_id=msg_id)
        )
        logger.info("[%s] send_image → session=%s  url=%s  caption=%s",
                     self.get_platform_name(), session_id, _truncate(image_url, 80), _truncate(caption))
        return True

    async def send_file(self, session_id: str, file_path: str, filename: str = "") -> bool:
        """Send a file attachment."""
        if not self._connected:
            logger.warning("[%s] send_file while disconnected", self.get_platform_name())
            return False
        msg_id = _generate_message_id()
        name = filename or Path(file_path).name
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="file", content=file_path,
                           extra={"filename": name}, message_id=msg_id)
        )
        logger.info("[%s] send_file → session=%s  path=%s  filename=%s",
                     self.get_platform_name(), session_id, _truncate(file_path, 80), name)
        return True

    async def send_audio(self, session_id: str, audio_url: str) -> bool:
        """Send an audio message."""
        if not self._connected:
            logger.warning("[%s] send_audio while disconnected", self.get_platform_name())
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="audio", content=audio_url, message_id=msg_id)
        )
        logger.info("[%s] send_audio → session=%s  url=%s",
                     self.get_platform_name(), session_id, _truncate(audio_url, 80))
        return True

    async def send_video(self, session_id: str, video_url: str) -> bool:
        """Send a video message."""
        if not self._connected:
            logger.warning("[%s] send_video while disconnected", self.get_platform_name())
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="video", content=video_url, message_id=msg_id)
        )
        logger.info("[%s] send_video → session=%s  url=%s",
                     self.get_platform_name(), session_id, _truncate(video_url, 80))
        return True

    # -- query operations ----------------------------------------------------

    async def get_messages(self, session_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Retrieve recent messages for *session_id* from the buffer."""
        filtered = [m for m in self._message_buffer if m.session_id == session_id]
        return [
            {
                "message_id": m.message_id,
                "type": m.msg_type,
                "content": m.content,
                "timestamp": m.timestamp.isoformat(),
                "extra": m.extra,
            }
            for m in filtered[-limit:]
        ]

    async def delete_message(self, session_id: str, message_id: str) -> bool:
        """Delete a message by its ID."""
        before = len(self._message_buffer)
        self._message_buffer = [
            m for m in self._message_buffer
            if not (m.session_id == session_id and m.message_id == message_id)
        ]
        removed = before - len(self._message_buffer)
        logger.info("[%s] delete_message → session=%s  msg_id=%s  removed=%d",
                     self.get_platform_name(), session_id, message_id, removed)
        return removed > 0

    # -- identity ------------------------------------------------------------

    @abstractmethod
    def get_platform_name(self) -> str:
        """Return the canonical name of this platform (e.g. ``'telegram'``)."""
        ...

    @abstractmethod
    def get_platform_type(self) -> PlatformType:
        """Return the ``PlatformType`` enum member for this adapter."""
        ...

    def is_connected(self) -> bool:
        """Return whether the adapter is currently connected."""
        return self._connected

    # -- typing indicator ----------------------------------------------------

    async def set_typing(self, session_id: str, typing: bool = True) -> None:
        """Send or clear a typing indicator."""
        logger.info("[%s] set_typing → session=%s  typing=%s",
                     self.get_platform_name(), session_id, typing)

    # -- bot info ------------------------------------------------------------

    async def get_me(self) -> dict[str, Any]:
        """Return platform-specific bot/user info."""
        return {
            "platform": self.get_platform_name(),
            "connected": self._connected,
        }

    # -- helpers -------------------------------------------------------------

    def _cancel_background(self) -> None:
        """Cancel the background task if running."""
        if self._background_task and not self._background_task.done():
            self._background_task.cancel()

    def inject_message(self, session_id: str, content: str) -> None:
        """Push a synthetic message into the receive queue (for testing)."""
        self._receive_queue.put_nowait({
            "session_id": session_id,
            "content": content,
            "platform": self.get_platform_name(),
            "timestamp": datetime.now(UTC).isoformat(),
        })

    async def receive(self):
        """Yield incoming messages from the internal queue."""
        while self._connected:
            try:
                msg = await asyncio.wait_for(self._receive_queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break


# ============================================================================
# 1. TelegramAdapter
# ============================================================================

class TelegramAdapter(PlatformAdapter):
    """Telegram Bot API adapter.

    Expected config keys:
        token (str): Bot API token from @BotFather.
        chat_id (str, optional): Default chat ID.
        parse_mode (str, optional): ``"Markdown"`` or ``"HTML"`` (default ``"Markdown"``).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._token: str = config.get("token", "")
        self._default_chat_id: str = config.get("chat_id", "")
        self._parse_mode: str = config.get("parse_mode", "Markdown")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._token:
            raise RuntimeError("Telegram bot token is required")
        logger.info("[%s] Connecting to Telegram Bot API (token=%s…)",
                     self.get_platform_name(), self._token[:8])
        await asyncio.sleep(0.1)
        self._connected = True
        self._background_task = asyncio.create_task(self._poll_loop(), name="telegram-poll")
        logger.info("[%s] Connected and polling for updates", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "telegram"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.TELEGRAM

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "telegram",
            "bot_id": int(self._token.split(":")[0]) if ":" in self._token else 0,
            "is_bot": True,
            "parse_mode": self._parse_mode,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_sticker(self, session_id: str, sticker_file_id: str) -> bool:
        """Send a Telegram sticker."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="sticker",
                           content=sticker_file_id, message_id=msg_id)
        )
        logger.info("[%s] sendSticker → session=%s  file_id=%s",
                     self.get_platform_name(), session_id, sticker_file_id)
        return True

    async def send_reply_markup(self, session_id: str, text: str,
                                 reply_markup: dict[str, Any]) -> bool:
        """Send text with inline keyboard reply markup."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="text",
                           content=text, extra={"reply_markup": reply_markup}, message_id=msg_id)
        )
        logger.info("[%s] sendMessage (with markup) → session=%s  text=%s",
                     self.get_platform_name(), session_id, _truncate(text))
        return True

    async def _poll_loop(self) -> None:
        logger.info("[%s] getUpdates long-poll started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(5)
                logger.debug("[%s] getUpdates → [] (no new updates)", self.get_platform_name())
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Polling stopped", self.get_platform_name())


# ============================================================================
# 2. DiscordAdapter
# ============================================================================

class DiscordAdapter(PlatformAdapter):
    """Discord Bot adapter.

    Expected config keys:
        token (str): Bot token from the Discord Developer Portal.
        channel_id (str, optional): Default channel ID.
        intents (list, optional): Gateway intents to enable.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._token: str = config.get("token", "")
        self._default_channel_id: str = config.get("channel_id", "")
        self._intents: list[str] = config.get("intents", ["guilds", "messages"])

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._token:
            raise RuntimeError("Discord bot token is required")
        logger.info("[%s] Connecting to Discord Gateway (token=%s…)",
                     self.get_platform_name(), self._token[:8])
        await asyncio.sleep(0.15)
        self._connected = True
        self._background_task = asyncio.create_task(self._ws_loop(), name="discord-ws")
        logger.info("[%s] Gateway connected (intents=%s)", self.get_platform_name(), self._intents)

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Gateway disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "discord"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.DISCORD

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "discord",
            "bot_id": hashlib.sha256(self._token.encode()).hexdigest()[:16],
            "intents": self._intents,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_embed(self, session_id: str, embed: dict[str, Any]) -> bool:
        """Send a rich embed message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="embed",
                           content=json.dumps(embed), message_id=msg_id)
        )
        logger.info("[%s] createMessage (embed) → session=%s  title=%s",
                     self.get_platform_name(), session_id, embed.get("title", ""))
        return True

    async def add_reaction(self, session_id: str, message_id: str, emoji: str) -> bool:
        """Add a reaction to a message."""
        logger.info("[%s] addReaction → session=%s  msg=%s  emoji=%s",
                     self.get_platform_name(), session_id, message_id, emoji)
        return True

    async def create_thread(self, session_id: str, name: str,
                            initial_message: str = "") -> str | None:
        """Create a new thread in a channel. Returns thread ID."""
        thread_id = _generate_message_id()
        logger.info("[%s] createThread → session=%s  name=%s  thread_id=%s",
                     self.get_platform_name(), session_id, name, thread_id)
        return thread_id

    async def _ws_loop(self) -> None:
        logger.info("[%s] WS heartbeat loop started (interval=41.25s)", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(41.25)
                logger.debug("[%s] \u2764 heartbeat acknowledged", self.get_platform_name())
        except asyncio.CancelledError:
            pass
        logger.info("[%s] WS loop stopped", self.get_platform_name())


# ============================================================================
# 3. SlackAdapter
# ============================================================================

class SlackAdapter(PlatformAdapter):
    """Slack Bot adapter (Socket Mode).

    Expected config keys:
        bot_token (str): ``xoxb-…`` token.
        app_token (str): ``xapp-…`` token for Socket Mode.
        channel (str, optional): Default channel.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._bot_token: str = config.get("bot_token", "")
        self._app_token: str = config.get("app_token", "")
        self._default_channel: str = config.get("channel", "")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._bot_token or not self._app_token:
            raise RuntimeError("Slack bot_token and app_token are required")
        logger.info("[%s] Connecting via Socket Mode (app_token=%s…)",
                     self.get_platform_name(), self._app_token[:8])
        await asyncio.sleep(0.12)
        self._connected = True
        self._background_task = asyncio.create_task(self._ws_loop(), name="slack-ws")
        logger.info("[%s] Socket Mode connected", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Socket Mode disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "slack"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.SLACK

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "slack",
            "bot_token_prefix": self._bot_token[:6],
            "default_channel": self._default_channel,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_block(self, session_id: str, blocks: list[dict[str, Any]]) -> bool:
        """Send a message using Slack Block Kit."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="block",
                           content=json.dumps(blocks), message_id=msg_id)
        )
        logger.info("[%s] chat.postMessage (blocks) → session=%s  %d blocks",
                     self.get_platform_name(), session_id, len(blocks))
        return True

    async def add_reaction(self, session_id: str, message_id: str, emoji: str) -> bool:
        """Add a reaction emoji to a message."""
        logger.info("[%s] reactions.add → session=%s  msg=%s  emoji=%s",
                     self.get_platform_name(), session_id, message_id, emoji)
        return True

    async def create_thread(self, session_id: str, parent_message_id: str,
                            text: str = "") -> str | None:
        """Reply in thread. Returns thread timestamp."""
        ts = str(time.time())
        logger.info("[%s] chat.postMessage (thread) → session=%s  parent=%s",
                     self.get_platform_name(), session_id, parent_message_id)
        return ts

    async def _ws_loop(self) -> None:
        logger.info("[%s] Socket Mode WS loop started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(5)
                logger.debug("[%s] ping/pong acknowledged", self.get_platform_name())
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Socket Mode WS loop stopped", self.get_platform_name())


# ============================================================================
# 4. WhatsAppAdapter
# ============================================================================

class WhatsAppAdapter(PlatformAdapter):
    """WhatsApp Business Cloud API adapter.

    Expected config keys:
        phone_number_id (str): Phone number ID from Meta dashboard.
        access_token (str): Access token.
        verify_token (str, optional): Webhook verify token.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._phone_number_id: str = config.get("phone_number_id", "")
        self._access_token: str = config.get("access_token", "")
        self._verify_token: str = config.get("verify_token", "")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._phone_number_id or not self._access_token:
            raise RuntimeError("WhatsApp phone_number_id and access_token are required")
        logger.info("[%s] Connecting to WhatsApp Business API (phone_id=%s)",
                     self.get_platform_name(), self._phone_number_id[:8])
        await asyncio.sleep(0.1)
        self._connected = True
        logger.info("[%s] Connected", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "whatsapp"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.WHATSAPP

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "whatsapp",
            "phone_number_id": self._phone_number_id,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_template(self, session_id: str, template_name: str,
                            parameters: list[str]) -> bool:
        """Send a template message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="template",
                           content=template_name,
                           extra={"parameters": parameters}, message_id=msg_id)
        )
        logger.info("[%s] sendTemplate → session=%s  template=%s  params=%s",
                     self.get_platform_name(), session_id, template_name, parameters)
        return True

    async def send_interactive(self, session_id: str, body_text: str,
                               buttons: list[dict[str, str]]) -> bool:
        """Send an interactive message with reply buttons."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="interactive",
                           content=body_text, extra={"buttons": buttons}, message_id=msg_id)
        )
        logger.info("[%s] sendInteractive → session=%s  %d buttons",
                     self.get_platform_name(), session_id, len(buttons))
        return True


# ============================================================================
# 5. SignalAdapter
# ============================================================================

class SignalAdapter(PlatformAdapter):
    """Signal Messenger adapter (via signal-cli).

    Expected config keys:
        phone_number (str): Signal phone number.
        signal_cli_path (str, optional): Path to signal-cli binary.
        config_dir (str, optional): signal-cli config directory.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._phone_number: str = config.get("phone_number", "")
        self._signal_cli_path: str = config.get("signal_cli_path", "signal-cli")
        self._config_dir: str = config.get("config_dir", "")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._phone_number:
            raise RuntimeError("Signal phone_number is required")
        logger.info("[%s] Connecting via signal-cli (number=%s)",
                     self.get_platform_name(), self._phone_number)
        await asyncio.sleep(0.1)
        self._connected = True
        self._background_task = asyncio.create_task(self._receive_loop(), name="signal-rx")
        logger.info("[%s] Connected and listening", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "signal"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.SIGNAL

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "signal",
            "phone_number": self._phone_number,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_group_message(self, group_id: str, text: str) -> bool:
        """Send a message to a Signal group."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=group_id, msg_type="group_text",
                           content=text, message_id=msg_id)
        )
        logger.info("[%s] send to group=%s  text=%s",
                     self.get_platform_name(), group_id, _truncate(text))
        return True

    async def add_reaction(self, session_id: str, message_id: str, emoji: str) -> bool:
        """Send a reaction to a Signal message."""
        logger.info("[%s] sendReaction → session=%s  msg=%s  emoji=%s",
                     self.get_platform_name(), session_id, message_id, emoji)
        return True

    async def _receive_loop(self) -> None:
        logger.info("[%s] signal-cli receive loop started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(3)
        except asyncio.CancelledError:
            pass


# ============================================================================
# 6. TeamsAdapter
# ============================================================================

class TeamsAdapter(PlatformAdapter):
    """Microsoft Teams adapter (Bot Framework).

    Expected config keys:
        app_id (str): Microsoft App ID.
        app_secret (str): Microsoft App Secret.
        tenant_id (str): Azure AD tenant ID.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._app_id: str = config.get("app_id", "")
        self._app_secret: str = config.get("app_secret", "")
        self._tenant_id: str = config.get("tenant_id", "")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._app_id or not self._app_secret:
            raise RuntimeError("Teams app_id and app_secret are required")
        logger.info("[%s] Connecting to Bot Framework (app_id=%s…)",
                     self.get_platform_name(), self._app_id[:8])
        await asyncio.sleep(0.2)
        self._connected = True
        logger.info("[%s] Connected — OAuth2 token acquired", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "teams"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.TEAMS

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "teams",
            "app_id": self._app_id,
            "tenant_id": self._tenant_id,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_adaptive_card(self, session_id: str, card: dict[str, Any]) -> bool:
        """Send an Adaptive Card."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="adaptive_card",
                           content=json.dumps(card), message_id=msg_id)
        )
        logger.info("[%s] sendAdaptiveCard → session=%s", self.get_platform_name(), session_id)
        return True

    async def send_proactive(self, conversation_id: str, text: str) -> bool:
        """Send a proactive message to an existing conversation."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=conversation_id, msg_type="proactive",
                           content=text, message_id=msg_id)
        )
        logger.info("[%s] proactive message → conversation=%s", self.get_platform_name(), conversation_id)
        return True


# ============================================================================
# 7. WeChatAdapter
# ============================================================================

class WeChatAdapter(PlatformAdapter):
    """WeChat Official Account / Work adapter.

    Expected config keys:
        corp_id (str): WeChat Corp ID.
        secret (str): Application secret.
        agent_id (str, optional): Agent ID for work account.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._corp_id: str = config.get("corp_id", "")
        self._secret: str = config.get("secret", "")
        self._agent_id: str = config.get("agent_id", "")
        self._access_token: str = ""

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._corp_id or not self._secret:
            raise RuntimeError("WeChat corp_id and secret are required")
        logger.info("[%s] Connecting to WeChat API (corp_id=%s…)",
                     self.get_platform_name(), self._corp_id[:8])
        await asyncio.sleep(0.15)
        # Simulate access_token fetch
        self._access_token = hashlib.sha256(
            f"{self._corp_id}{self._secret}".encode()
        ).hexdigest()[:32]
        self._connected = True
        logger.info("[%s] Connected (access_token=%s…)",
                     self.get_platform_name(), self._access_token[:8])

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._access_token = ""
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "wechat"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.WECHAT

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "wechat",
            "corp_id": self._corp_id,
            "agent_id": self._agent_id,
            "has_access_token": bool(self._access_token),
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def upload_media(self, media_type: str, file_path: str) -> str | None:
        """Upload temporary media. Returns media_id."""
        media_id = hashlib.sha256(f"{media_type}{file_path}".encode()).hexdigest()[:16]
        logger.info("[%s] uploadMedia → type=%s  path=%s  media_id=%s",
                     self.get_platform_name(), media_type, file_path, media_id)
        return media_id

    async def send_news(self, session_id: str, articles: list[dict[str, str]]) -> bool:
        """Send a news (article) message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="news",
                           content=json.dumps(articles), message_id=msg_id)
        )
        logger.info("[%s] sendNews → session=%s  %d articles",
                     self.get_platform_name(), session_id, len(articles))
        return True


# ============================================================================
# 8. QQAdapter
# ============================================================================

class QQAdapter(PlatformAdapter):
    """QQ Bot adapter (QQ Official Bot / Guild API).

    Expected config keys:
        app_id (str): QQ App ID.
        token (str): QQ Bot token.
        sandbox (bool, optional): Use sandbox mode.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._app_id: str = config.get("app_id", "")
        self._token: str = config.get("token", "")
        self._sandbox: bool = config.get("sandbox", False)

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._app_id or not self._token:
            raise RuntimeError("QQ app_id and token are required")
        logger.info("[%s] Connecting to QQ Bot API (app_id=%s, sandbox=%s)",
                     self.get_platform_name(), self._app_id, self._sandbox)
        await asyncio.sleep(0.12)
        self._connected = True
        self._background_task = asyncio.create_task(self._ws_loop(), name="qq-ws")
        logger.info("[%s] Connected to %s", self.get_platform_name(),
                     "sandbox" if self._sandbox else "production")

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "qq"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.QQ

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "qq",
            "app_id": self._app_id,
            "sandbox": self._sandbox,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_to_guild(self, guild_id: str, channel_id: str, text: str) -> bool:
        """Send a message to a specific guild channel."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=channel_id, msg_type="guild_text",
                           content=text, extra={"guild_id": guild_id}, message_id=msg_id)
        )
        logger.info("[%s] guild message → guild=%s  channel=%s",
                     self.get_platform_name(), guild_id, channel_id)
        return True

    async def upload_chunked(self, session_id: str, file_path: str,
                             chunk_size: int = 1024 * 1024) -> str | None:
        """Upload a file using chunked upload. Returns file UUID."""
        file_uuid = hashlib.sha256(file_path.encode()).hexdigest()[:16]
        logger.info("[%s] chunked upload → session=%s  path=%s  chunk_size=%d  uuid=%s",
                     self.get_platform_name(), session_id, file_path, chunk_size, file_uuid)
        return file_uuid

    async def _ws_loop(self) -> None:
        logger.info("[%s] QQ WS event loop started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass


# ============================================================================
# 9. FeishuAdapter (Lark)
# ============================================================================

class FeishuAdapter(PlatformAdapter):
    """Feishu / Lark adapter.

    Expected config keys:
        app_id (str): Feishu App ID.
        app_secret (str): Feishu App Secret.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._app_id: str = config.get("app_id", "")
        self._app_secret: str = config.get("app_secret", "")
        self._tenant_token: str = ""

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._app_id or not self._app_secret:
            raise RuntimeError("Feishu app_id and app_secret are required")
        logger.info("[%s] Connecting to Feishu Open API (app_id=%s…)",
                     self.get_platform_name(), self._app_id[:8])
        await asyncio.sleep(0.12)
        self._tenant_token = hashlib.sha256(
            f"{self._app_id}{self._app_secret}".encode()
        ).hexdigest()[:32]
        self._connected = True
        self._background_task = asyncio.create_task(self._event_loop(), name="feishu-events")
        logger.info("[%s] Connected (tenant_token=%s…)",
                     self.get_platform_name(), self._tenant_token[:8])

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        self._tenant_token = ""
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "feishu"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.FEISHU

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "feishu",
            "app_id": self._app_id,
            "has_tenant_token": bool(self._tenant_token),
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_card(self, session_id: str, card: dict[str, Any]) -> bool:
        """Send an interactive card message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="card",
                           content=json.dumps(card), message_id=msg_id)
        )
        logger.info("[%s] sendCard → session=%s", self.get_platform_name(), session_id)
        return True

    async def create_meeting(self, title: str, start_time: str,
                             duration_minutes: int) -> str | None:
        """Create a Feishu meeting. Returns meeting URL."""
        meeting_id = hashlib.sha256(title.encode()).hexdigest()[:12]
        url = f"https://feishu.cn/meeting/{meeting_id}"
        logger.info("[%s] createMeeting → title=%s  duration=%dm  url=%s",
                     self.get_platform_name(), title, duration_minutes, url)
        return url

    async def _event_loop(self) -> None:
        logger.info("[%s] Event subscription loop started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass


# ============================================================================
# 10. WeixinWorkAdapter (WeCom)
# ============================================================================

class WeixinWorkAdapter(PlatformAdapter):
    """WeCom (Enterprise WeChat) adapter.

    Expected config keys:
        corp_id (str): Corp ID.
        secret (str): Agent secret.
        agent_id (str): Agent ID.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._corp_id: str = config.get("corp_id", "")
        self._secret: str = config.get("secret", "")
        self._agent_id: str = config.get("agent_id", "")
        self._access_token: str = ""

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._corp_id or not self._secret:
            raise RuntimeError("WeCom corp_id and secret are required")
        logger.info("[%s] Connecting to WeCom API (corp_id=%s…)",
                     self.get_platform_name(), self._corp_id[:8])
        await asyncio.sleep(0.12)
        self._access_token = hashlib.sha256(
            f"{self._corp_id}{self._secret}{self._agent_id}".encode()
        ).hexdigest()[:32]
        self._connected = True
        logger.info("[%s] Connected (agent_id=%s)", self.get_platform_name(), self._agent_id)

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._access_token = ""
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "weixin_work"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.WEIXIN_WORK

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "weixin_work",
            "corp_id": self._corp_id,
            "agent_id": self._agent_id,
            "has_access_token": bool(self._access_token),
            "connected": self._connected,
        }


# ============================================================================
# 11. YuanbaoAdapter (Tencent Yuanbao)
# ============================================================================

class YuanbaoAdapter(PlatformAdapter):
    """Tencent Yuanbao adapter.

    Expected config keys:
        app_id (str): Yuanbao App ID.
        api_key (str): Yuanbao API key.
        endpoint (str, optional): Custom API endpoint.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._app_id: str = config.get("app_id", "")
        self._api_key: str = config.get("api_key", "")
        self._endpoint: str = config.get("endpoint", "https://yuanbao.tencent.com/api")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._app_id or not self._api_key:
            raise RuntimeError("Yuanbao app_id and api_key are required")
        logger.info("[%s] Connecting to Yuanbao API (app_id=%s…)",
                     self.get_platform_name(), self._app_id[:8])
        await asyncio.sleep(0.1)
        self._connected = True
        logger.info("[%s] Connected (endpoint=%s)", self.get_platform_name(), self._endpoint)

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "yuanbao"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.YUANBAO

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "yuanbao",
            "app_id": self._app_id,
            "endpoint": self._endpoint,
            "connected": self._connected,
        }

    async def send_rich_text(self, session_id: str, content: str,
                            format_type: str = "markdown") -> bool:
        """Send a rich-text formatted message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="rich_text",
                           content=content, extra={"format": format_type}, message_id=msg_id)
        )
        logger.info("[%s] sendRichText → session=%s  format=%s",
                     self.get_platform_name(), session_id, format_type)
        return True


# ============================================================================
# 12. MatrixAdapter
# ============================================================================

class MatrixAdapter(PlatformAdapter):
    """Matrix protocol adapter.

    Expected config keys:
        homeserver_url (str): Matrix homeserver URL (e.g. ``https://matrix.org``).
        access_token (str): Matrix access token.
        user_id (str, optional): Matrix user ID (``@bot:example.org``).
        device_id (str, optional): Device ID.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._homeserver_url: str = config.get("homeserver_url", "https://matrix.org")
        self._access_token: str = config.get("access_token", "")
        self._user_id: str = config.get("user_id", "")
        self._device_id: str = config.get("device_id", "AION")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._access_token:
            raise RuntimeError("Matrix access_token is required")
        logger.info("[%s] Connecting to %s (user=%s)",
                     self.get_platform_name(), self._homeserver_url, self._user_id or "unknown")
        await asyncio.sleep(0.15)
        self._connected = True
        self._background_task = asyncio.create_task(self._sync_loop(), name="matrix-sync")
        logger.info("[%s] Connected — initial /sync completed", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "matrix"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.MATRIX

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "matrix",
            "user_id": self._user_id,
            "homeserver": self._homeserver_url,
            "device_id": self._device_id,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def join_room(self, room_id: str) -> bool:
        """Join a Matrix room."""
        logger.info("[%s] joinRoom → room=%s", self.get_platform_name(), room_id)
        return True

    async def send_encrypted(self, session_id: str, text: str) -> bool:
        """Send an end-to-end encrypted message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="encrypted_text",
                           content=text, message_id=msg_id)
        )
        logger.info("[%s] sendEncrypted → room=%s  (E2EE)", self.get_platform_name(), session_id)
        return True

    async def send_html(self, session_id: str, html_body: str, text_body: str = "") -> bool:
        """Send an HTML-formatted message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="html",
                           content=html_body, extra={"text_body": text_body}, message_id=msg_id)
        )
        logger.info("[%s] sendHtml → room=%s", self.get_platform_name(), session_id)
        return True

    async def _sync_loop(self) -> None:
        logger.info("[%s] /sync long-poll loop started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass


# ============================================================================
# 13. IRCAdapter
# ============================================================================

class IRCAdapter(PlatformAdapter):
    """IRC (Internet Relay Chat) adapter.

    Expected config keys:
        server (str): IRC server hostname.
        port (int, optional): Server port (default 6667).
        nick (str): Bot nickname.
        channels (list, optional): Channels to auto-join.
        ssl (bool, optional): Use TLS (default False).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._server: str = config.get("server", "")
        self._port: int = config.get("port", 6667)
        self._nick: str = config.get("nick", "aion-bot")
        self._channels: list[str] = config.get("channels", [])
        self._use_ssl: bool = config.get("ssl", False)

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._server or not self._nick:
            raise RuntimeError("IRC server and nick are required")
        logger.info("[%s] Connecting to %s:%d as %s (ssl=%s)",
                     self.get_platform_name(), self._server, self._port, self._nick, self._use_ssl)
        await asyncio.sleep(0.2)
        self._connected = True
        # Simulate joining channels
        for ch in self._channels:
            logger.info("[%s] JOIN %s", self.get_platform_name(), ch)
        self._background_task = asyncio.create_task(self._ping_loop(), name="irc-ping")
        logger.info("[%s] Connected", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        # Simulate QUIT
        for ch in self._channels:
            logger.info("[%s] PART %s", self.get_platform_name(), ch)
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        logger.info("[%s] QIT — Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "irc"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.IRC

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "irc",
            "server": self._server,
            "nick": self._nick,
            "channels": self._channels,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_action(self, session_id: str, action: str) -> bool:
        """Send a CTCP ACTION (/me)."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="action",
                           content=action, message_id=msg_id)
        )
        logger.info("[%s] ACTION %s :%s", self.get_platform_name(), session_id, action)
        return True

    async def send_notice(self, session_id: str, text: str) -> bool:
        """Send a NOTICE message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="notice",
                           content=text, message_id=msg_id)
        )
        logger.info("[%s] NOTICE %s :%s", self.get_platform_name(), session_id, text)
        return True

    async def join_channel(self, channel: str) -> bool:
        """Join an IRC channel."""
        logger.info("[%s] JOIN %s", self.get_platform_name(), channel)
        if channel not in self._channels:
            self._channels.append(channel)
        return True

    async def _ping_loop(self) -> None:
        logger.info("[%s] PING/PONG loop started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(60)
                logger.debug("[%s] PING → %s", self.get_platform_name(), self._server)
        except asyncio.CancelledError:
            pass


# ============================================================================
# 14. MattermostAdapter
# ============================================================================

class MattermostAdapter(PlatformAdapter):
    """Mattermost adapter.

    Expected config keys:
        url (str): Mattermost server URL.
        token (str): Personal access token or bot token.
        team_name (str, optional): Default team name.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._url: str = config.get("url", "").rstrip("/")
        self._token: str = config.get("token", "")
        self._team_name: str = config.get("team_name", "")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._url or not self._token:
            raise RuntimeError("Mattermost url and token are required")
        logger.info("[%s] Connecting to %s (team=%s)",
                     self.get_platform_name(), self._url, self._team_name or "default")
        await asyncio.sleep(0.1)
        self._connected = True
        self._background_task = asyncio.create_task(self._ws_loop(), name="mattermost-ws")
        logger.info("[%s] Connected — WebSocket established", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "mattermost"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.MATTERMOST

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "mattermost",
            "url": self._url,
            "team_name": self._team_name,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def add_reaction(self, session_id: str, message_id: str, emoji: str) -> bool:
        """Add a reaction to a post."""
        logger.info("[%s] addReaction → post=%s  emoji=%s",
                     self.get_platform_name(), message_id, emoji)
        return True

    async def send_slash_command(self, session_id: str, command: str) -> bool:
        """Execute a slash command."""
        logger.info("[%s] slashCommand → session=%s  cmd=%s",
                     self.get_platform_name(), session_id, command)
        return True

    async def _ws_loop(self) -> None:
        logger.info("[%s] Mattermost WebSocket loop started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass


# ============================================================================
# 15. LineAdapter
# ============================================================================

class LineAdapter(PlatformAdapter):
    """LINE Messaging API adapter.

    Expected config keys:
        channel_token (str): Channel access token.
        channel_secret (str): Channel secret.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._channel_token: str = config.get("channel_token", "")
        self._channel_secret: str = config.get("channel_secret", "")
        self._reply_tokens: dict[str, str] = {}

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._channel_token:
            raise RuntimeError("LINE channel_token is required")
        logger.info("[%s] Connecting to LINE Messaging API (token=%s…)",
                     self.get_platform_name(), self._channel_token[:8])
        await asyncio.sleep(0.1)
        self._connected = True
        logger.info("[%s] Connected", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._reply_tokens.clear()
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "line"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.LINE

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "line",
            "channel_token_prefix": self._channel_token[:8],
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def reply(self, reply_token: str, text: str) -> bool:
        """Reply to a specific event using a reply token."""
        if not self._connected:
            return False
        self._reply_tokens[reply_token] = text
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=reply_token, msg_type="reply",
                           content=text, message_id=msg_id)
        )
        logger.info("[%s] reply → token=%s  text=%s",
                     self.get_platform_name(), reply_token[:8], _truncate(text))
        return True

    async def send_flex_message(self, session_id: str, alt_text: str,
                                 contents: dict[str, Any]) -> bool:
        """Send a LINE Flex Message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="flex",
                           content=alt_text, extra={"contents": contents}, message_id=msg_id)
        )
        logger.info("[%s] sendFlex → session=%s  alt=%s",
                     self.get_platform_name(), session_id, alt_text)
        return True

    async def push_message(self, session_id: str, text: str) -> bool:
        """Push a message without waiting for a user event."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="push",
                           content=text, message_id=msg_id)
        )
        logger.info("[%s] push → session=%s  text=%s",
                     self.get_platform_name(), session_id, _truncate(text))
        return True


# ============================================================================
# 16. GoogleChatAdapter
# ============================================================================

class GoogleChatAdapter(PlatformAdapter):
    """Google Chat adapter (Bot via Google Workspace).

    Expected config keys:
        service_account_json (str): Path or JSON string for service account.
        project_id (str, optional): GCP project ID.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._service_account: str = config.get("service_account_json", "")
        self._project_id: str = config.get("project_id", "")
        self._access_token: str = ""

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._service_account:
            raise RuntimeError("Google Chat service_account_json is required")
        logger.info("[%s] Connecting to Google Chat API (project=%s)",
                     self.get_platform_name(), self._project_id or "unknown")
        await asyncio.sleep(0.2)
        self._access_token = hashlib.sha256(
            self._service_account.encode()
        ).hexdigest()[:32]
        self._connected = True
        logger.info("[%s] Connected — service account authenticated", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._access_token = ""
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "google_chat"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.GOOGLE_CHAT

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "google_chat",
            "project_id": self._project_id,
            "has_access_token": bool(self._access_token),
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_card(self, space_id: str, card: dict[str, Any]) -> bool:
        """Send a Google Chat card message to a space."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=space_id, msg_type="card",
                           content=json.dumps(card), message_id=msg_id)
        )
        logger.info("[%s] sendCard → space=%s", self.get_platform_name(), space_id)
        return True

    async def send_threaded_reply(self, thread_name: str, text: str) -> bool:
        """Reply within a Google Chat thread."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=thread_name, msg_type="thread_reply",
                           content=text, message_id=msg_id)
        )
        logger.info("[%s] threaded reply → thread=%s", self.get_platform_name(), thread_name)
        return True


# ============================================================================
# 17. DingTalkAdapter
# ============================================================================

class DingTalkAdapter(PlatformAdapter):
    """DingTalk (Ding) adapter.

    Expected config keys:
        app_key (str): DingTalk App Key.
        app_secret (str): DingTalk App Secret.
        robot_code (str, optional): Robot code for bot messages.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._app_key: str = config.get("app_key", "")
        self._app_secret: str = config.get("app_secret", "")
        self._robot_code: str = config.get("robot_code", "")
        self._access_token: str = ""

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._app_key or not self._app_secret:
            raise RuntimeError("DingTalk app_key and app_secret are required")
        logger.info("[%s] Connecting to DingTalk API (app_key=%s…)",
                     self.get_platform_name(), self._app_key[:8])
        await asyncio.sleep(0.12)
        self._access_token = hashlib.sha256(
            f"{self._app_key}{self._app_secret}".encode()
        ).hexdigest()[:32]
        self._connected = True
        self._background_task = asyncio.create_task(self._stream_loop(), name="dingtalk-stream")
        logger.info("[%s] Connected — stream established", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        self._cancel_background()
        try:
            if self._background_task:
                await self._background_task
        except asyncio.CancelledError:
            pass
        self._access_token = ""
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "dingtalk"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.DINGTALK

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "dingtalk",
            "app_key": self._app_key,
            "robot_code": self._robot_code,
            "has_access_token": bool(self._access_token),
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_action_card(self, session_id: str, title: str, text: str,
                                btn_title: str, btn_url: str) -> bool:
        """Send an action card message with a single button."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="action_card",
                           content=text, extra={"title": title, "btn_title": btn_title,
                                               "btn_url": btn_url}, message_id=msg_id)
        )
        logger.info("[%s] sendActionCard → session=%s  title=%s",
                     self.get_platform_name(), session_id, title)
        return True

    async def send_markdown(self, session_id: str, title: str, text: str) -> bool:
        """Send a markdown-formatted message."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=session_id, msg_type="markdown",
                           content=text, extra={"title": title}, message_id=msg_id)
        )
        logger.info("[%s] sendMarkdown → session=%s  title=%s",
                     self.get_platform_name(), session_id, title)
        return True

    async def _stream_loop(self) -> None:
        logger.info("[%s] DingTalk stream loop started", self.get_platform_name())
        try:
            while self._connected:
                await asyncio.sleep(5)
        except asyncio.CancelledError:
            pass


# ============================================================================
# 18. EmailAdapter
# ============================================================================

class EmailAdapter(PlatformAdapter):
    """Email adapter (SMTP send / IMAP receive).

    Expected config keys:
        smtp_host (str): SMTP server hostname.
        smtp_port (int, optional): SMTP port (default 587).
        smtp_user (str): SMTP username.
        smtp_password (str): SMTP password.
        imap_host (str, optional): IMAP server hostname.
        imap_port (int, optional): IMAP port (default 993).
        from_address (str, optional): Sender email address.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._smtp_host: str = config.get("smtp_host", "")
        self._smtp_port: int = config.get("smtp_port", 587)
        self._smtp_user: str = config.get("smtp_user", "")
        self._smtp_password: str = config.get("smtp_password", "")
        self._imap_host: str = config.get("imap_host", "")
        self._imap_port: int = config.get("imap_port", 993)
        self._from_address: str = config.get("from_address", self._smtp_user)

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._smtp_host or not self._smtp_user:
            raise RuntimeError("Email smtp_host and smtp_user are required")
        logger.info("[%s] Connecting to SMTP %s:%d (user=%s)",
                     self.get_platform_name(), self._smtp_host, self._smtp_port, self._smtp_user)
        await asyncio.sleep(0.2)
        self._connected = True
        if self._imap_host:
            logger.info("[%s] IMAP %s:%d also available",
                         self.get_platform_name(), self._imap_host, self._imap_port)
        logger.info("[%s] Connected", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "email"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.EMAIL

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "email",
            "from_address": self._from_address,
            "smtp_host": self._smtp_host,
            "has_imap": bool(self._imap_host),
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_email(self, to: str, subject: str, body: str,
                         html: str = "", attachments: list[str] | None = None) -> bool:
        """Send an email with optional HTML body and attachments."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=to, msg_type="email",
                           content=body, extra={"subject": subject, "html": html,
                                               "attachments": attachments or []},
                           message_id=msg_id)
        )
        logger.info("[%s] sendEmail → to=%s  subject=%s  attachments=%d",
                     self.get_platform_name(), to, subject, len(attachments or []))
        return True

    async def check_inbox(self, folder: str = "INBOX", limit: int = 10) -> list[dict[str, Any]]:
        """Check IMAP inbox for new messages."""
        logger.info("[%s] checkInbox → folder=%s  limit=%d",
                     self.get_platform_name(), folder, limit)
        return []


# ============================================================================
# 19. NtfyAdapter
# ============================================================================

class NtfyAdapter(PlatformAdapter):
    """Ntfy (self-hosted push notifications) adapter.

    Expected config keys:
        server_url (str): Ntfy server URL (default ``https://ntfy.sh``).
        topic (str): Ntfy topic name.
        auth_token (str, optional): Auth token for protected topics.
        priority (int, optional): Default priority 1-5 (default 3).
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._server_url: str = config.get("server_url", "https://ntfy.sh").rstrip("/")
        self._topic: str = config.get("topic", "")
        self._auth_token: str = config.get("auth_token", "")
        self._priority: int = config.get("priority", 3)

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._topic:
            raise RuntimeError("Ntfy topic is required")
        logger.info("[%s] Connecting to %s (topic=%s, priority=%d)",
                     self.get_platform_name(), self._server_url, self._topic, self._priority)
        await asyncio.sleep(0.05)
        self._connected = True
        logger.info("[%s] Connected", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "ntfy"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.NTFY

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "ntfy",
            "server_url": self._server_url,
            "topic": self._topic,
            "priority": self._priority,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def send_notification(self, title: str, body: str,
                                priority: int | None = None,
                                tags: list[str] | None = None,
                                click_url: str = "") -> bool:
        """Send a push notification with optional metadata."""
        if not self._connected:
            return False
        p = priority if priority is not None else self._priority
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=self._topic, msg_type="notification",
                           content=body, extra={"title": title, "priority": p,
                                               "tags": tags or [], "click_url": click_url},
                           message_id=msg_id)
        )
        logger.info("[%s] publish → topic=%s  title=%s  priority=%d  tags=%s",
                     self.get_platform_name(), self._topic, title, p, tags)
        return True

    async def send_with_actions(self, title: str, body: str,
                                actions: list[dict[str, str]]) -> bool:
        """Send a notification with action buttons."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=self._topic, msg_type="notification_actions",
                           content=body, extra={"title": title, "actions": actions},
                           message_id=msg_id)
        )
        logger.info("[%s] publish (actions) → topic=%s  %d actions",
                     self.get_platform_name(), self._topic, len(actions))
        return True


# ============================================================================
# 20. WebhookAdapter
# ============================================================================

class WebhookAdapter(PlatformAdapter):
    """Generic Webhook adapter.

    Expected config keys:
        url (str): Webhook URL.
        method (str, optional): HTTP method (default ``"POST"``).
        headers (dict, optional): Custom headers.
        auth_type (str, optional): Auth type (``"bearer"``, ``"basic"``, ``"none"``).
        auth_token (str, optional): Auth token/credentials.
    """

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)
        self._url: str = config.get("url", "")
        self._method: str = config.get("method", "POST").upper()
        self._headers: dict[str, str] = config.get("headers", {})
        self._auth_type: str = config.get("auth_type", "none")
        self._auth_token: str = config.get("auth_token", "")

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.get_platform_name())
            return
        if not self._url:
            raise RuntimeError("Webhook URL is required")
        logger.info("[%s] Configured → %s %s (auth=%s)",
                     self.get_platform_name(), self._method, self._url, self._auth_type)
        await asyncio.sleep(0.02)
        self._connected = True
        logger.info("[%s] Connected (ready to fire)", self.get_platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return
        self._connected = False
        logger.info("[%s] Disconnected", self.get_platform_name())

    def get_platform_name(self) -> str:
        return "webhook"

    def get_platform_type(self) -> PlatformType:
        return PlatformType.WEBHOOK

    async def get_me(self) -> dict[str, Any]:
        return {
            "platform": "webhook",
            "url": self._url,
            "method": self._method,
            "auth_type": self._auth_type,
            "connected": self._connected,
        }

    # -- platform-specific methods -------------------------------------------

    async def fire(self, payload: dict[str, Any],
                   override_url: str = "") -> bool:
        """Fire the webhook with a JSON payload."""
        if not self._connected:
            return False
        target = override_url or self._url
        msg_id = _generate_message_id()
        self._message_buffer.append(
            _StoredMessage(session_id=target, msg_type="webhook_fire",
                           content=json.dumps(payload), message_id=msg_id)
        )
        logger.info("[%s] fire → %s %s  payload=%s",
                     self.get_platform_name(), self._method, target,
                     _truncate(json.dumps(payload)))
        return True

    async def fire_raw(self, body: str, content_type: str = "application/json",
                       override_headers: dict[str, str] | None = None) -> bool:
        """Fire the webhook with a raw string body."""
        if not self._connected:
            return False
        msg_id = _generate_message_id()
        headers = {**self._headers, **(override_headers or {})}
        self._message_buffer.append(
            _StoredMessage(session_id=self._url, msg_type="webhook_raw",
                           content=body, extra={"content_type": content_type,
                                               "headers": headers}, message_id=msg_id)
        )
        logger.info("[%s] fire_raw → %s %s  content_type=%s  len=%d",
                     self.get_platform_name(), self._method, self._url, content_type, len(body))
        return True

    def _build_auth_headers(self) -> dict[str, str]:
        """Build authentication headers based on configured auth_type."""
        headers: dict[str, str] = {}
        if self._auth_type == "bearer" and self._auth_token:
            headers["Authorization"] = f"Bearer {self._auth_token}"
        elif self._auth_type == "basic" and self._auth_token:
            encoded = base64.b64encode(self._auth_token.encode()).decode()
            headers["Authorization"] = f"Basic {encoded}"
        return headers


# ============================================================================
# Platform Registry
# ============================================================================

class PlatformRegistry:
    """Registry that manages platform adapter instances.

    Usage::

        registry = PlatformRegistry()
        registry.register(PlatformType.TELEGRAM, {"token": "..."})
        adapter = registry.get(PlatformType.TELEGRAM)
        await registry.connect_all()
        await registry.disconnect_all()
    """

    def __init__(self) -> None:
        self._adapters: dict[PlatformType, PlatformAdapter] = {}

    def register(self, platform_type: PlatformType, config: dict[str, Any]) -> None:
        """Create and register an adapter for *platform_type* with *config*."""
        adapter = _ADAPTER_MAP[platform_type](config)
        self._adapters[platform_type] = adapter
        logger.info("PlatformRegistry: registered %s (%s)",
                     platform_type.value, type(adapter).__name__)

    def register_instance(self, platform_type: PlatformType,
                          adapter: PlatformAdapter) -> None:
        """Register a pre-created adapter instance."""
        self._adapters[platform_type] = adapter
        logger.info("PlatformRegistry: registered instance %s (%s)",
                     platform_type.value, type(adapter).__name__)

    def get(self, platform_type: PlatformType) -> PlatformAdapter | None:
        """Get the adapter for *platform_type*, or ``None``."""
        return self._adapters.get(platform_type)

    def get_required(self, platform_type: PlatformType) -> PlatformAdapter:
        """Get the adapter for *platform_type*, raising ``KeyError`` if absent."""
        adapter = self._adapters.get(platform_type)
        if adapter is None:
            raise KeyError(f"No adapter registered for {platform_type.value}")
        return adapter

    def list_platforms(self) -> list[PlatformType]:
        """Return a list of all registered platform types."""
        return list(self._adapters.keys())

    async def connect_all(self) -> dict[PlatformType, bool]:
        """Connect all registered adapters concurrently.

        Returns a mapping of platform type → success boolean.
        """
        results: dict[PlatformType, bool] = {}
        coros = {pt: adapter.connect() for pt, adapter in self._adapters.items()}
        outcomes = await asyncio.gather(*coros.values(), return_exceptions=True)
        for pt, outcome in zip(coros.keys(), outcomes):
            if isinstance(outcome, Exception):
                logger.error("PlatformRegistry: failed to connect %s — %s", pt.value, outcome)
                results[pt] = False
            else:
                results[pt] = True
        logger.info("PlatformRegistry: connect_all → %d/%d succeeded",
                     sum(results.values()), len(results))
        return results

    async def disconnect_all(self) -> None:
        """Disconnect all registered adapters concurrently."""
        coros = [adapter.disconnect() for adapter in self._adapters.values()]
        await asyncio.gather(*coros, return_exceptions=True)
        logger.info("PlatformRegistry: disconnect_all completed")

    def __len__(self) -> int:
        return len(self._adapters)

    def __contains__(self, platform_type: PlatformType) -> bool:
        return platform_type in self._adapters


# ============================================================================
# Adapter map (used by registry and factory)
# ============================================================================

_ADAPTER_MAP: dict[PlatformType, type[PlatformAdapter]] = {
    PlatformType.TELEGRAM:    TelegramAdapter,
    PlatformType.DISCORD:     DiscordAdapter,
    PlatformType.SLACK:       SlackAdapter,
    PlatformType.WHATSAPP:    WhatsAppAdapter,
    PlatformType.SIGNAL:      SignalAdapter,
    PlatformType.TEAMS:       TeamsAdapter,
    PlatformType.WECHAT:      WeChatAdapter,
    PlatformType.QQ:          QQAdapter,
    PlatformType.FEISHU:      FeishuAdapter,
    PlatformType.WEIXIN_WORK: WeixinWorkAdapter,
    PlatformType.YUANBAO:     YuanbaoAdapter,
    PlatformType.MATRIX:      MatrixAdapter,
    PlatformType.IRC:         IRCAdapter,
    PlatformType.MATTERMOST:  MattermostAdapter,
    PlatformType.LINE:        LineAdapter,
    PlatformType.GOOGLE_CHAT: GoogleChatAdapter,
    PlatformType.DINGTALK:    DingTalkAdapter,
    PlatformType.EMAIL:       EmailAdapter,
    PlatformType.NTFY:        NtfyAdapter,
    PlatformType.WEBHOOK:     WebhookAdapter,
}


# ============================================================================
# Factory function
# ============================================================================

def create_platform(platform_type: PlatformType,
                    config: dict[str, Any]) -> PlatformAdapter:
    """Factory function: create a platform adapter instance.

    Args:
        platform_type: The ``PlatformType`` enum member.
        config: Configuration dictionary for the adapter.

    Returns:
        A new ``PlatformAdapter`` instance.

    Raises:
        ValueError: If *platform_type* is not recognized.
    """
    cls = _ADAPTER_MAP.get(platform_type)
    if cls is None:
        raise ValueError(
            f"Unknown platform type: {platform_type!r}. "
            f"Valid types: {[p.value for p in PlatformType]}"
        )
    logger.info("create_platform: %s → %s", platform_type.value, cls.__name__)
    return cls(config)


# ============================================================================
# Config validation
# ============================================================================

# Required config keys per platform
_REQUIRED_KEYS: dict[PlatformType, list[str]] = {
    PlatformType.TELEGRAM:    ["token"],
    PlatformType.DISCORD:     ["token"],
    PlatformType.SLACK:       ["bot_token", "app_token"],
    PlatformType.WHATSAPP:    ["phone_number_id", "access_token"],
    PlatformType.SIGNAL:      ["phone_number"],
    PlatformType.TEAMS:       ["app_id", "app_secret"],
    PlatformType.WECHAT:      ["corp_id", "secret"],
    PlatformType.QQ:          ["app_id", "token"],
    PlatformType.FEISHU:      ["app_id", "app_secret"],
    PlatformType.WEIXIN_WORK: ["corp_id", "secret", "agent_id"],
    PlatformType.YUANBAO:     ["app_id", "api_key"],
    PlatformType.MATRIX:      ["homeserver_url", "access_token"],
    PlatformType.IRC:         ["server", "nick"],
    PlatformType.MATTERMOST:  ["url", "token"],
    PlatformType.LINE:        ["channel_token"],
    PlatformType.GOOGLE_CHAT: ["service_account_json"],
    PlatformType.DINGTALK:    ["app_key", "app_secret"],
    PlatformType.EMAIL:       ["smtp_host", "smtp_user"],
    PlatformType.NTFY:        ["topic"],
    PlatformType.WEBHOOK:     ["url"],
}


def validate_platform_config(platform_type: PlatformType,
                              config: dict[str, Any]) -> list[str]:
    """Validate a platform configuration dictionary.

    Args:
        platform_type: The ``PlatformType`` to validate against.
        config: The configuration dictionary.

    Returns:
        A list of error strings (empty if valid).
    """
    errors: list[str] = []

    if not isinstance(config, dict):
        errors.append(f"config must be a dict, got {type(config).__name__}")
        return errors

    required = _REQUIRED_KEYS.get(platform_type, [])
    for key in required:
        val = config.get(key)
        if val is None or (isinstance(val, str) and val.strip() == ""):
            errors.append(f"Missing or empty required key: '{key}'")

    # Type-specific extra validation
    if platform_type == PlatformType.EMAIL and "smtp_port" in config:
        port = config["smtp_port"]
        if not isinstance(port, int) or not (1 <= port <= 65535):
            errors.append(f"smtp_port must be an int in 1-65535, got {port!r}")

    if platform_type == PlatformType.IRC and "port" in config:
        port = config["port"]
        if not isinstance(port, int) or not (1 <= port <= 65535):
            errors.append(f"IRC port must be an int in 1-65535, got {port!r}")

    if platform_type == PlatformType.NTFY and "priority" in config:
        p = config["priority"]
        if not isinstance(p, int) or not (1 <= p <= 5):
            errors.append(f"Ntfy priority must be 1-5, got {p!r}")

    if platform_type == PlatformType.WEBHOOK and "method" in config:
        method = config["method"].upper()
        if method not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
            errors.append(f"Webhook method must be a valid HTTP method, got {method!r}")

    if platform_type == PlatformType.DISCORD and "intents" in config:
        intents = config["intents"]
        if not isinstance(intents, list):
            errors.append(f"Discord intents must be a list, got {type(intents).__name__}")

    if platform_type == PlatformType.WHATSAPP and "access_token" in config:
        token = config["access_token"]
        if isinstance(token, str) and len(token) < 10:
            errors.append("WhatsApp access_token seems too short")

    return errors
