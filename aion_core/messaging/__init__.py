"""
aion_core.messaging — OpenClaw-inspired messaging gateway for multi-platform access.

Provides an abstraction layer over Telegram, Discord, Slack, and custom
platforms, allowing the agent to send and receive messages from a unified
interface.

Quick start::

    from aion_core.messaging import MessagingGateway, TelegramAdapter

    gateway = MessagingGateway(
        platforms={"telegram": {"token": "..."}},
        agent=agent,
    )
    await gateway.initialize()

    await gateway.send_message("telegram", user_id="12345", content="Hello!")
    results = await gateway.broadcast(["telegram", "discord"], "Update!")

    await gateway.shutdown()
"""

try:
    from .gateway import (
        DiscordAdapter,
        Message,
        MessagingGateway,
        PlatformAdapter,
        SlackAdapter,
        TelegramAdapter,
    )
except ImportError:
    DiscordAdapter = None  # type: ignore[assignment,misc]
    Message = None  # type: ignore[assignment,misc]
    MessagingGateway = None  # type: ignore[assignment,misc]
    PlatformAdapter = None  # type: ignore[assignment,misc]
    SlackAdapter = None  # type: ignore[assignment,misc]
    TelegramAdapter = None  # type: ignore[assignment,misc]
try:
    from .platforms import PlatformType, PlatformRegistry, create_platform
except ImportError:
    PlatformType = None  # type: ignore[assignment,misc]
    PlatformRegistry = None  # type: ignore[assignment,misc]
    create_platform = None  # type: ignore[assignment,misc]
try:
    from .platforms import PlatformAdapterFactory
except ImportError:
    PlatformAdapterFactory = None  # type: ignore[assignment,misc]

__all__ = [
    # Gateway
    "DiscordAdapter",
    "Message",
    "MessagingGateway",
    "PlatformAdapter",
    "SlackAdapter",
    "TelegramAdapter",
    # Platform abstraction
    "PlatformType",
    "PlatformRegistry",
    "create_platform",
    "PlatformAdapterFactory",
]
