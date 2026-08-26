"""
Messaging Gateway for the Aion Hand AI agent framework.

OpenClaw-inspired abstraction over multiple messaging platforms (Telegram,
Discord, Slack) so the agent can send and receive messages from a single
unified interface.

Architecture::

    ┌───────────────┐     ┌───────────────┐     ┌───────────────┐
    │ TelegramAdapter│    │ DiscordAdapter │    │  SlackAdapter  │
    └───────┬───────┘    └───────┬───────┘    └───────┬───────┘
            │                    │                    │
            └────────────────────┼────────────────────┘
                                 │
                        ┌────────┴────────┐
                        │ MessagingGateway│
                        └────────┬────────┘
                                 │
                          ┌──────┴──────┐
                          │  Aion Agent  │
                          └─────────────┘

Each adapter is a thin async wrapper around its platform's API.  The included
Telegram and Discord adapters are realistic stubs that log all operations —
swap them for production implementations by subclassing ``PlatformAdapter``.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, UTC
from typing import Any
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message data model
# ---------------------------------------------------------------------------

@dataclass
class Message:
    """A message received from or destined for a messaging platform.

    Attributes:
        platform:  Name of the originating platform (e.g. ``"telegram"``).
        user_id:   Platform-specific user identifier.
        content:   Text body of the message.
        timestamp: When the message was created/received.
        reply_to:  ID of another message this is replying to, if any.
    """

    platform: str = ""
    user_id: str = ""
    content: str = ""
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    reply_to: str | None = None


# ---------------------------------------------------------------------------
# PlatformAdapter ABC
# ---------------------------------------------------------------------------

class PlatformAdapter(ABC):
    """Abstract base class for messaging platform integrations.

    Every adapter must implement ``connect``, ``disconnect``, ``send``,
    ``receive``, and ``platform_name``.  The gateway calls ``connect`` during
    ``initialize`` and ``disconnect`` during ``shutdown``.
    """

    @abstractmethod
    async def connect(self) -> None:
        """Establish the connection / session with the platform."""
        ...

    @abstractmethod
    async def disconnect(self) -> None:
        """Gracefully close the connection."""
        ...

    @abstractmethod
    async def send(self, user_id: str, content: str) -> bool:
        """Send a text message to a specific user.

        Args:
            user_id: Platform-specific user identifier.
            content: Message body.

        Returns:
            ``True`` if delivery was acknowledged.
        """
        ...

    @abstractmethod
    async def receive(self) -> AsyncIterator[Message]:
        """Yield incoming messages as an async iterator.

        The iterator should block until the next message arrives or the
        connection is closed.
        """
        ...  # pragma: no cover — yielded values are the contract

    @abstractmethod
    def platform_name(self) -> str:
        """Return the canonical name of this platform (e.g. ``"telegram"``)."""
        ...


# ---------------------------------------------------------------------------
# TelegramAdapter (realistic stub)
# ---------------------------------------------------------------------------

class TelegramAdapter(PlatformAdapter):
    """Telegram Bot API adapter.

    This is a **realistic stub** that simulates connection handshake and
    message handling through structured logging.  Replace the internals with
    calls to ``python-telegram-bot`` or ``aiogram`` for production use.

    Expected ``config`` keys:
        token (str): Bot API token from @BotFather.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._connected: bool = False
        self._token: str = self._config.get("token", "")
        self._receive_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._poll_task: asyncio.Task | None = None

    # -- ABC implementation ------------------------------------------------

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.platform_name())
            return

        if not self._token:
            logger.error(
                "[%s] No bot token configured — set platforms.telegram.token "
                "in your config",
                self.platform_name(),
            )
            raise RuntimeError("Telegram bot token is required")

        # Simulate connection handshake
        logger.info(
            "[%s] Connecting to Telegram Bot API (token=%s…)",
            self.platform_name(),
            self._token[:8],
        )
        await asyncio.sleep(0.1)  # simulate network latency
        self._connected = True

        # Start background polling
        self._poll_task = asyncio.create_task(
            self._poll_loop(), name="telegram-poll"
        )
        logger.info("[%s] Connected and polling for updates", self.platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return

        self._connected = False
        if self._poll_task and not self._poll_task.done():
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("[%s] Disconnected", self.platform_name())

    async def send(self, user_id: str, content: str) -> bool:
        if not self._connected:
            logger.warning("[%s] send() called while disconnected", self.platform_name())
            return False

        logger.info(
            "[%s] sendMessage → chat_id=%s  content=%s",
            self.platform_name(),
            user_id,
            content[:100] + "…" if len(content) > 100 else content,
        )
        # In production: await bot.send_message(chat_id=user_id, text=content)
        return True

    async def receive(self) -> AsyncIterator[Message]:
        """Yield messages from the internal queue (populated by ``_poll_loop``)."""
        while self._connected:
            try:
                msg = await asyncio.wait_for(self._receive_queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def platform_name(self) -> str:
        return "telegram"

    # -- Internal helpers ---------------------------------------------------

    async def _poll_loop(self) -> None:
        """Simulate long-polling getUpdates.

        In production this would call ``bot.get_updates(timeout=30)`` and
        enqueue each ``Update`` as a ``Message``.
        """
        logger.info("[%s] Polling started (getUpdates long-poll)", self.platform_name())
        try:
            while self._connected:
                await asyncio.sleep(5)
                logger.debug("[%s] getUpdates → [] (no new updates)", self.platform_name())
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Polling stopped", self.platform_name())

    # -- Public helper (useful for testing) ---------------------------------

    def inject_message(self, user_id: str, content: str) -> None:
        """Push a synthetic message into the receive queue (for testing)."""
        self._receive_queue.put_nowait(
            Message(
                platform=self.platform_name(),
                user_id=user_id,
                content=content,
            )
        )


# ---------------------------------------------------------------------------
# DiscordAdapter (realistic stub)
# ---------------------------------------------------------------------------

class DiscordAdapter(PlatformAdapter):
    """Discord Bot adapter.

    This is a **realistic stub** that simulates gateway WebSocket handshake
    and message handling.  Replace with ``discord.py`` for production use.

    Expected ``config`` keys:
        token (str): Bot token from the Discord Developer Portal.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._connected: bool = False
        self._token: str = self._config.get("token", "")
        self._receive_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._ws_task: asyncio.Task | None = None

    # -- ABC implementation ------------------------------------------------

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.platform_name())
            return

        if not self._token:
            logger.error(
                "[%s] No bot token configured — set platforms.discord.token "
                "in your config",
                self.platform_name(),
            )
            raise RuntimeError("Discord bot token is required")

        # Simulate Discord gateway handshake
        logger.info(
            "[%s] Connecting to Discord Gateway (token=%s…)",
            self.platform_name(),
            self._token[:8],
        )
        await asyncio.sleep(0.15)  # simulate WS handshake
        self._connected = True

        self._ws_task = asyncio.create_task(
            self._ws_loop(), name="discord-ws"
        )
        logger.info(
            "[%s] Connected to Discord Gateway (heartbeat OK)",
            self.platform_name(),
        )

    async def disconnect(self) -> None:
        if not self._connected:
            return

        self._connected = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        logger.info(
            "[%s] Sent WS close, gateway disconnected", self.platform_name()
        )

    async def send(self, user_id: str, content: str) -> bool:
        if not self._connected:
            logger.warning("[%s] send() called while disconnected", self.platform_name())
            return False

        logger.info(
            "[%s] createMessage → channel=%s  content=%s",
            self.platform_name(),
            user_id,
            content[:100] + "…" if len(content) > 100 else content,
        )
        # In production: await channel.send(content)
        return True

    async def receive(self) -> AsyncIterator[Message]:
        """Yield messages from the internal queue (populated by ``_ws_loop``)."""
        while self._connected:
            try:
                msg = await asyncio.wait_for(self._receive_queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def platform_name(self) -> str:
        return "discord"

    # -- Internal helpers ---------------------------------------------------

    async def _ws_loop(self) -> None:
        """Simulate the Discord Gateway WebSocket heartbeat / dispatch loop."""
        logger.info(
            "[%s] WS loop started — sending heartbeat every 41.25s",
            self.platform_name(),
        )
        heartbeat_interval = 41.25
        try:
            while self._connected:
                await asyncio.sleep(heartbeat_interval)
                logger.debug("[%s] ❤ heartbeat acknowledged", self.platform_name())
        except asyncio.CancelledError:
            pass
        logger.info("[%s] WS loop stopped", self.platform_name())

    # -- Public helper (useful for testing) ---------------------------------

    def inject_message(self, user_id: str, content: str) -> None:
        """Push a synthetic message into the receive queue (for testing)."""
        self._receive_queue.put_nowait(
            Message(
                platform=self.platform_name(),
                user_id=user_id,
                content=content,
            )
        )


# ---------------------------------------------------------------------------
# SlackAdapter (realistic stub)
# ---------------------------------------------------------------------------

class SlackAdapter(PlatformAdapter):
    """Slack Bot adapter.

    This is a **realistic stub** that simulates the Socket Mode WebSocket
    connection.  Replace with ``slack_bolt`` for production use.

    Expected ``config`` keys:
        bot_token (str): ``xoxb-…`` token from your Slack app.
        app_token (str): ``xapp-…`` token for Socket Mode.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self._config = config or {}
        self._connected: bool = False
        self._bot_token: str = self._config.get("bot_token", "")
        self._app_token: str = self._config.get("app_token", "")
        self._receive_queue: asyncio.Queue[Message] = asyncio.Queue()
        self._ws_task: asyncio.Task | None = None

    # -- ABC implementation ------------------------------------------------

    async def connect(self) -> None:
        if self._connected:
            logger.warning("[%s] Already connected", self.platform_name())
            return

        if not self._bot_token or not self._app_token:
            logger.error(
                "[%s] Missing bot_token and/or app_token — "
                "set platforms.slack.bot_token and platforms.slack.app_token",
                self.platform_name(),
            )
            raise RuntimeError("Slack bot_token and app_token are required")

        logger.info(
            "[%s] Connecting via Socket Mode (app_token=%s…)",
            self.platform_name(),
            self._app_token[:8],
        )
        await asyncio.sleep(0.12)
        self._connected = True

        self._ws_task = asyncio.create_task(
            self._ws_loop(), name="slack-ws"
        )
        logger.info("[%s] Socket Mode connected", self.platform_name())

    async def disconnect(self) -> None:
        if not self._connected:
            return

        self._connected = False
        if self._ws_task and not self._ws_task.done():
            self._ws_task.cancel()
            try:
                await self._ws_task
            except asyncio.CancelledError:
                pass
        logger.info("[%s] Socket Mode disconnected", self.platform_name())

    async def send(self, user_id: str, content: str) -> bool:
        if not self._connected:
            logger.warning("[%s] send() called while disconnected", self.platform_name())
            return False

        logger.info(
            "[%s] chat.postMessage → channel=%s  text=%s",
            self.platform_name(),
            user_id,
            content[:100] + "…" if len(content) > 100 else content,
        )
        return True

    async def receive(self) -> AsyncIterator[Message]:
        """Yield messages from the internal queue."""
        while self._connected:
            try:
                msg = await asyncio.wait_for(self._receive_queue.get(), timeout=1.0)
                yield msg
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    def platform_name(self) -> str:
        return "slack"

    # -- Internal helpers ---------------------------------------------------

    async def _ws_loop(self) -> None:
        """Simulate Slack Socket Mode keep-alive."""
        logger.info(
            "[%s] Socket Mode WS loop started (hello acknowledged)",
            self.platform_name(),
        )
        try:
            while self._connected:
                await asyncio.sleep(5)
                logger.debug("[%s] ping/pong acknowledged", self.platform_name())
        except asyncio.CancelledError:
            pass
        logger.info("[%s] Socket Mode WS loop stopped", self.platform_name())

    def inject_message(self, user_id: str, content: str) -> None:
        """Push a synthetic message into the receive queue (for testing)."""
        self._receive_queue.put_nowait(
            Message(
                platform=self.platform_name(),
                user_id=user_id,
                content=content,
            )
        )


# ---------------------------------------------------------------------------
# Adapter registry — maps platform name → class
# ---------------------------------------------------------------------------

_ADAPTER_REGISTRY: dict[str, type[PlatformAdapter]] = {
    "telegram": TelegramAdapter,
    "discord": DiscordAdapter,
    "slack": SlackAdapter,
}


def register_adapter(name: str, cls: type[PlatformAdapter]) -> None:
    """Register a custom adapter class for a platform name.

    Example::

        from aion_core.messaging.gateway import register_adapter, PlatformAdapter
        register_adapter("whatsapp", MyWhatsAppAdapter)
    """
    _ADAPTER_REGISTRY[name] = cls
    logger.info("Registered adapter '%s' → %s", name, cls.__name__)


# ---------------------------------------------------------------------------
# MessagingGateway
# ---------------------------------------------------------------------------

class MessagingGateway:
    """Unified messaging interface over one or more platform adapters.

    Inspired by OpenClaw's gateway design: the agent sends/receives through
    a single object, while each platform runs its own async connection.

    Usage::

        gateway = MessagingGateway(
            platforms={
                "telegram": {"token": "..."},
                "discord":  {"token": "..."},
            },
            agent=agent,
        )
        await gateway.initialize()

        # Send a message
        ok = await gateway.send_message("telegram", "12345", "Hello!")

        # Broadcast to multiple platforms
        results = await gateway.broadcast(["telegram", "discord"], "Big news!")

        await gateway.shutdown()
    """

    def __init__(
        self,
        platforms: dict[str, dict[str, Any]],
        agent: Any,
    ) -> None:
        self._adapters: dict[str, PlatformAdapter] = {}
        self._agent = agent
        self._running: bool = False
        self._receive_tasks: dict[str, asyncio.Task] = {}

        # Sender allowlist (fail-closed). Sources, in priority order:
        #   1. gateway config "allowed_users" (per-gateway override)
        #   2. agent.config.allowed_users (AgentConfig field)
        # An empty allowlist blocks ALL incoming messages.
        self._allowed_users: set[str] = set()
        gw_cfg = {}
        if isinstance(platforms, dict):
            gw_cfg = platforms.get("gateway", {}) or {}
        if isinstance(gw_cfg, dict):
            self._allowed_users.update(
                str(u) for u in gw_cfg.get("allowed_users", []) or []
            )
        agent_cfg = getattr(agent, "config", None)
        agent_allowed = getattr(agent_cfg, "allowed_users", None) or []
        self._allowed_users.update(str(u) for u in agent_allowed)

        # Instantiate adapters from the registry
        for name, config in platforms.items():
            adapter_cls = _ADAPTER_REGISTRY.get(name)
            if adapter_cls is None:
                logger.warning(
                    "No adapter registered for platform '%s' — skipping", name
                )
                continue
            self._adapters[name] = adapter_cls(config=config)

        if self._adapters:
            logger.info(
                "MessagingGateway created with %d adapter(s): %s",
                len(self._adapters),
                ", ".join(self._adapters.keys()),
            )
        else:
            logger.warning("MessagingGateway created with no valid adapters")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> None:
        """Connect all registered platform adapters and start receiving."""
        if self._running:
            logger.warning("MessagingGateway is already running")
            return

        self._running = True

        # Connect adapters concurrently
        connect_coros = {
            name: adapter.connect() for name, adapter in self._adapters.items()
        }
        results = await asyncio.gather(
            *connect_coros.values(), return_exceptions=True
        )

        for name, result in zip(connect_coros.keys(), results):
            if isinstance(result, Exception):
                logger.error("[%s] Failed to connect: %s", name, result)
            else:
                # Spawn a receive loop for each connected adapter
                self._receive_tasks[name] = asyncio.create_task(
                    self._dispatch_loop(name), name=f"dispatch-{name}"
                )

        active = sum(1 for t in self._receive_tasks.values() if not t.done())
        logger.info(
            "MessagingGateway started — %d/%d adapters active",
            active,
            len(self._adapters),
        )

    async def shutdown(self) -> None:
        """Disconnect all adapters and stop receive loops."""
        self._running = False

        # Cancel dispatch loops first
        for name, task in self._receive_tasks.items():
            if not task.done():
                task.cancel()
        for name, task in self._receive_tasks.items():
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._receive_tasks.clear()

        # Disconnect adapters concurrently
        disconnect_coros = [
            adapter.disconnect() for adapter in self._adapters.values()
        ]
        await asyncio.gather(*disconnect_coros, return_exceptions=True)

        logger.info("MessagingGateway shut down")

    # ------------------------------------------------------------------
    # Send / Broadcast
    # ------------------------------------------------------------------

    async def send_message(
        self, platform: str, user_id: str, content: str
    ) -> bool:
        """Send a message on a specific platform.

        Args:
            platform: Platform name (must be registered).
            user_id:   Recipient identifier.
            content:   Message text.

        Returns:
            ``True`` if the adapter accepted the message.
        """
        adapter = self._adapters.get(platform)
        if adapter is None:
            logger.error("No adapter for platform '%s'", platform)
            return False

        success = await adapter.send(user_id, content)
        if not success:
            logger.warning(
                "[%s] send failed for user_id=%s", platform, user_id
            )
        return success

    async def broadcast(
        self, platforms: list[str], content: str
    ) -> dict[str, bool]:
        """Send the same content to multiple platforms concurrently.

        Returns:
            A mapping of ``platform_name → success``.
        """
        coros = {
            name: self.send_message(name, "", content) for name in platforms
        }
        results = await asyncio.gather(*coros.values(), return_exceptions=True)

        outcome: dict[str, bool] = {}
        for name, result in zip(coros.keys(), results):
            if isinstance(result, Exception):
                logger.error("[%s] broadcast error: %s", name, result)
                outcome[name] = False
            else:
                outcome[name] = result
        return outcome

    # ------------------------------------------------------------------
    # Receive dispatch
    # ------------------------------------------------------------------

    async def _dispatch_loop(self, platform_name: str) -> None:
        """Pull messages from an adapter and route them to the agent."""
        adapter = self._adapters.get(platform_name)
        if adapter is None:
            return

        logger.info("[%s] Dispatch loop started", platform_name)

        try:
            async for message in adapter.receive():
                if not self._running:
                    break
                logger.info(
                    "[%s] Incoming message from %s: %s",
                    message.platform,
                    message.user_id,
                    message.content[:100] + "…" if len(message.content) > 100 else message.content,
                )
                # Route to agent
                try:
                    await self._handle_incoming(message)
                except Exception:
                    logger.exception(
                        "[%s] Error handling message from %s",
                        platform_name,
                        message.user_id,
                    )
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("[%s] Dispatch loop crashed", platform_name)

        logger.info("[%s] Dispatch loop stopped", platform_name)

    def _sender_allowed(self, message: Message) -> bool:
        """Return True iff the sender is allowlisted (fail-closed).

        Matching is by user id (exact, string-compared). An empty
        allowlist rejects everyone — gateway operators must explicitly
        list the users who may drive the agent.
        """
        if not self._allowed_users:
            return False
        uid = str(getattr(message, "user_id", "") or "")
        return uid in self._allowed_users

    async def _handle_incoming(self, message: Message) -> None:
        """Delegate an incoming message to the agent's chat interface.

        Security: the sender must be in the configured allowlist. The check
        is fail-closed — an empty allowlist rejects everyone (previously
        ANY user who found the bot could drive the agent, including its
        shell/file tools).
        """
        if not self._sender_allowed(message):
            logger.warning(
                "[%s] REJECTED message from unauthorized user %s "
                "(allowlist: %s)",
                message.platform,
                message.user_id,
                self._allowed_users or "(empty - all rejected)",
            )
            return
        # Build agent context from the message
        if hasattr(self._agent, "chat"):
            # Per-platform-user session id keeps gateway users' contexts
            # isolated from each other (and from the owner's CLI session).
            session_id = f"{message.platform}:{message.user_id}"
            response = await self._agent.chat(
                message.content, session_id=session_id
            )
            reply_content = response.get("content", "")

            # Send the reply back to the same platform / user
            if reply_content:
                await self.send_message(
                    message.platform, message.user_id, reply_content
                )
        else:
            logger.warning(
                "Agent has no 'chat' method — cannot handle incoming message "
                "from %s on %s",
                message.user_id,
                message.platform,
            )
