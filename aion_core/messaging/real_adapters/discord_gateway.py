"""Discord Gateway bot adapter — REAL receiving + sending, stdlib only.

Discord has no REST polling for messages (unlike Telegram's getUpdates);
receiving requires the Gateway WebSocket. This module implements enough
of the protocol with the Python standard library only:

* :class:`MiniWebSocket` — a minimal RFC 6455 client (handshake via HTTP
  Upgrade over ``asyncio.open_connection`` + TLS, masked client frames,
  server frame parsing incl. fragmentation, ping/pong, close).
* :class:`RealDiscordBotAdapter` — the full gateway lifecycle:

  1. ``GET /gateway/bot``      → websocket URL + session limits
  2. connect, receive HELLO    → heartbeat interval
  3. IDENTIFY (op 2)           → token, intents, ``compress=false``
  4. wait for READY dispatch
  5. heartbeat task (op 1) at the negotiated interval
  6. read loop: MESSAGE_CREATE → filtered :class:`RealMessage` queue
  7. replies via REST ``POST /channels/{id}/messages`` (2000-char chunks)

Security (mirrors gateway hardening):
* ``allowed_user_ids`` is FAIL-CLOSED when provided — messages from other
  users are dropped before they ever reach the agent.
* The bot only responds when mentioned (guild) or in DMs (configurable).

Intents used (value 37377):
``GUILDS(1) | GUILD_MESSAGES(512) | DIRECT_MESSAGES(4096) | MESSAGE_CONTENT(32768)``
— MESSAGE_CONTENT is a *privileged* intent: it must be enabled in the
Discord Developer Portal → Bot → Privileged Gateway Intents, or guild
message text will arrive empty (DMs still work).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import ssl
import urllib.parse
from typing import Any

from aion_core.messaging.real_adapters import RealAdapter, RealMessage, _http_request

logger = logging.getLogger("aion_hand.messaging.discord_bot")

DISCORD_API = "https://discord.com/api/v10"
DISCORD_GATEWAY_PARAMS = "?v=10&encoding=json"

#: GUILDS | GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT
INTENTS = (1 << 0) | (1 << 9) | (1 << 12) | (1 << 15)  # = 37377

MAX_MESSAGE_LEN = 2000


# ═══════════════════════════════════════════════════════════════════════════
# Minimal RFC 6455 WebSocket client
# ═══════════════════════════════════════════════════════════════════════════

class MiniWebSocketError(Exception):
    """WebSocket protocol violation or connection failure."""


class MiniWebSocket:
    """Async WebSocket client implementing just enough RFC 6455 for the
    Discord gateway: text frames, fragmentation, ping/pong, close.

    Client→server frames are masked (required); server→client frames are
    not (per spec).
    """

    def __init__(self) -> None:
        self._reader: asyncio.StreamReader | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._closed = False

    # -- connection -------------------------------------------------------

    async def connect(self, url: str, *, timeout: float = 15.0) -> None:
        """Connect to a ``wss://`` URL and perform the upgrade handshake."""
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "wss":
            raise MiniWebSocketError(f"Only wss:// supported, got {parsed.scheme}")
        host = parsed.hostname
        port = parsed.port or 443
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query

        ctx = ssl.create_default_context()
        self._reader, self._writer = await asyncio.wait_for(
            asyncio.open_connection(host, port, ssl=ctx), timeout=timeout
        )

        key = base64.b64encode(os.urandom(16)).decode("ascii")
        request = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n"
            "\r\n"
        )
        self._writer.write(request.encode("ascii"))
        await self._writer.drain()

        # Read the response headers
        status_line = await self._reader.readline()
        status = status_line.decode("latin-1").strip()
        if " 101 " not in status:
            await self._close_transport()
            raise MiniWebSocketError(f"WebSocket handshake rejected: {status}")
        headers: dict[str, str] = {}
        while True:
            line = await self._reader.readline()
            if line in (b"\r\n", b"\n", b""):
                break
            name, _, value = line.decode("latin-1").partition(":")
            headers[name.strip().lower()] = value.strip()

        expected_accept = base64.b64encode(
            hashlib.sha1((key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
                         ).digest()
        ).decode("ascii")
        got_accept = headers.get("sec-websocket-accept", "")
        if got_accept != expected_accept:
            await self._close_transport()
            raise MiniWebSocketError(
                f"Bad Sec-WebSocket-Accept (expected {expected_accept!r}, got {got_accept!r})"
            )

    # -- sending ----------------------------------------------------------

    async def send_text(self, text: str) -> None:
        await self._send_frame(0x1, text.encode("utf-8"))

    async def ping(self, payload: bytes = b"") -> None:
        await self._send_frame(0x9, payload)

    async def _send_frame(self, opcode: int, payload: bytes) -> None:
        if self._writer is None or self._closed:
            raise MiniWebSocketError("WebSocket is not connected")
        mask = os.urandom(4)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        header = bytearray()
        header.append(0x80 | opcode)  # FIN + opcode
        length = len(payload)
        if length < 126:
            header.append(0x80 | length)
        elif length < (1 << 16):
            header.append(0x80 | 126)
            header.extend(length.to_bytes(2, "big"))
        else:
            header.append(0x80 | 127)
            header.extend(length.to_bytes(8, "big"))
        header.extend(mask)
        self._writer.write(bytes(header) + masked)
        await self._writer.drain()

    # -- receiving --------------------------------------------------------

    async def recv(self, *, timeout: float | None = None) -> str | None:
        """Receive the next complete message (re-assembling fragments).

        Returns ``None`` when the server closes the connection. Ping
        frames are answered transparently.
        """
        if self._reader is None or self._closed:
            raise MiniWebSocketError("WebSocket is not connected")
        fragments: list[bytes] = []
        message_opcode: int | None = None
        while True:
            fin, opcode, payload = await self._read_frame(timeout=timeout)
            if opcode == 0x8:  # close
                await self._send_frame(0x8, payload[:2] if len(payload) >= 2 else b"")
                await self._close_transport()
                return None
            if opcode == 0x9:  # ping → pong
                await self._send_frame(0xA, payload)
                continue
            if opcode == 0xA:  # pong
                continue
            if opcode in (0x1, 0x2):  # text / binary start
                message_opcode = opcode
                fragments = [payload]
            elif opcode == 0x0:  # continuation
                fragments.append(payload)
            else:
                raise MiniWebSocketError(f"Unsupported opcode {opcode:#x}")
            if fin:
                data = b"".join(fragments)
                return data.decode("utf-8", errors="replace") if message_opcode != 0x2 else None

    async def _read_exact(self, n: int) -> bytes:
        assert self._reader is not None
        return await self._reader.readexactly(n)

    async def _read_frame(self, *, timeout: float | None = None) -> tuple[bool, int, bytes]:
        """Read one server frame → (fin, opcode, payload)."""
        assert self._reader is not None
        head = await self._read_exact(2)
        fin = bool(head[0] & 0x80)
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        length = head[1] & 0x7F
        if length == 126:
            length = int.from_bytes(await self._read_exact(2), "big")
        elif length == 127:
            length = int.from_bytes(await self._read_exact(8), "big")
        if length > 1 << 22:  # 4 MiB sanity cap
            raise MiniWebSocketError(f"Frame too large: {length}")
        mask = await self._read_exact(4) if masked else b""
        payload = await self._read_exact(length) if length else b""
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return fin, opcode, payload

    # -- teardown ---------------------------------------------------------

    async def close(self) -> None:
        if not self._closed:
            try:
                await self._send_frame(0x8, b"\x03\xe8")  # 1000 normal
            except (MiniWebSocketError, OSError):
                pass
            await self._close_transport()

    async def _close_transport(self) -> None:
        self._closed = True
        if self._writer is not None:
            try:
                self._writer.close()
            except OSError:
                pass
            self._writer = None
            self._reader = None

    @property
    def closed(self) -> bool:
        return self._closed


# ═══════════════════════════════════════════════════════════════════════════
# Discord Gateway bot adapter
# ═══════════════════════════════════════════════════════════════════════════

class RealDiscordBotAdapter(RealAdapter):
    """Real Discord bot: gateway-receives, REST-sends. Stdlib only.

    Config (kwargs):
        token:            Discord bot token (required)
        allowed_user_ids: list[str] — if set, FAIL-CLOSED: only these users
                          are answered (mirrors gateway allowlist hardening)
        respond_to:       "mention" (default; guild msgs need an @bot mention,
                          DMs always answered) | "dm" | "all"
        send_typing:      bool (default True) — REST typing indicator
    """

    platform_name = "discord_bot"

    OP_DISPATCH = 0
    OP_HEARTBEAT = 1
    OP_IDENTIFY = 2
    OP_HELLO = 10
    OP_HEARTBEAT_ACK = 11

    def __init__(
        self,
        token: str = "",
        allowed_user_ids: list[str] | None = None,
        respond_to: str = "mention",
        send_typing: bool = True,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._token = token
        self._allowed_users = [str(u) for u in (allowed_user_ids or [])]
        self._respond_to = respond_to
        self._send_typing = send_typing
        self._ws: MiniWebSocket | None = None
        self._heartbeat_task: asyncio.Task | None = None
        self._read_task: asyncio.Task | None = None
        self._heartbeat_interval: float = 41.25
        self._last_seq: int | None = None
        self._bot_user_id: str = ""
        self._application_id: str = ""

    # -- auth headers -------------------------------------------------------

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bot {self._token}",
            "Content-Type": "application/json",
        }

    # -- connection ---------------------------------------------------------

    async def connect(self) -> None:
        if self._connected:
            return
        if not self._token:
            raise ValueError("Discord bot token is required")

        # 1. Resolve the gateway URL
        info = await _http_request(
            "GET", f"{DISCORD_API}/gateway/bot", headers=self._auth_headers()
        )
        if info.get("_status") not in (None, 200):
            raise RuntimeError(
                f"gateway/bot failed: {info.get('_status')} {info.get('message', info)}"
            )
        ws_url = info.get("url")
        if not ws_url:
            raise RuntimeError(f"No gateway URL in response: {info}")
        if info.get("shards"):
            logger.info("[discord_bot] shards=%s", info["shards"])

        # 2. Open the WebSocket
        ws = MiniWebSocket()
        await ws.connect(ws_url + DISCORD_GATEWAY_PARAMS)

        # 3. HELLO → heartbeat interval
        hello_raw = await ws.recv(timeout=15)
        if hello_raw is None:
            raise RuntimeError("Gateway closed before HELLO")
        hello = json.loads(hello_raw)
        if hello.get("op") != self.OP_HELLO:
            raise RuntimeError(f"Expected HELLO (op 10), got {hello.get('op')}")
        self._heartbeat_interval = float(hello["d"]["heartbeat_interval"]) / 1000.0

        # 4. IDENTIFY (no transport compression → plain text frames)
        identify = {
            "op": self.OP_IDENTIFY,
            "d": {
                "token": self._token,
                "intents": INTENTS,
                "properties": {
                    "os": "linux",
                    "browser": "aion-hand",
                    "device": "aion-hand",
                },
                "compress": False,
            },
        }
        await ws.send_text(json.dumps(identify))

        # 5. Wait for READY (dispatch t=READY) — skip everything else
        ready = None
        for _ in range(20):  # bounded wait
            raw = await ws.recv(timeout=15)
            if raw is None:
                raise RuntimeError("Gateway closed while waiting for READY")
            payload = json.loads(raw)
            if payload.get("op") == self.OP_DISPATCH and payload.get("t") == "READY":
                ready = payload["d"]
                break
        if ready is None:
            await ws.close()
            raise RuntimeError("READY not received from Discord gateway")

        self._bot_user_id = str(ready.get("user", {}).get("id", ""))
        self._application_id = str(ready.get("application", {}).get("id", ""))

        # 6. Background: heartbeat + read loop
        self._ws = ws
        self._connected = True
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="discord-bot-heartbeat"
        )
        self._read_task = asyncio.create_task(
            self._gateway_read_loop(), name="discord-bot-read"
        )
        logger.info(
            "[discord_bot] READY as user %s (%s users allowlisted, respond_to=%s)",
            self._bot_user_id, len(self._allowed_users) or "ALL", self._respond_to,
        )

    async def disconnect(self) -> None:
        if not self._connected and self._ws is None:
            return
        self._connected = False
        for task in (self._heartbeat_task, self._read_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        if self._ws is not None:
            await self._ws.close()
            self._ws = None
        # RealAdapter.disconnect also cancels _background_task (receive loop)
        await super().disconnect()
        logger.info("[discord_bot] disconnected")

    # -- gateway protocol loops ----------------------------------------------

    async def _heartbeat_loop(self) -> None:
        try:
            while self._connected and self._ws and not self._ws.closed:
                beat = json.dumps({"op": self.OP_HEARTBEAT, "d": self._last_seq})
                await self._ws.send_text(beat)
                await asyncio.sleep(self._heartbeat_interval)
        except asyncio.CancelledError:
            pass
        except (MiniWebSocketError, OSError) as exc:
            logger.error("[discord_bot] heartbeat failed: %s", exc)
            self._connected = False

    async def _gateway_read_loop(self) -> None:
        assert self._ws is not None
        try:
            while self._connected:
                raw = await self._ws.recv(timeout=60)
                if raw is None:  # server closed
                    logger.warning("[discord_bot] gateway closed by server")
                    self._connected = False
                    break
                payload = json.loads(raw)
                op = payload.get("op")
                if op == self.OP_HEARTBEAT_ACK:
                    continue
                if op == self.OP_DISPATCH:
                    self._last_seq = payload.get("s", self._last_seq)
                    event = payload.get("t")
                    if event == "MESSAGE_CREATE":
                        self._handle_message_create(payload.get("d", {}))
        except asyncio.CancelledError:
            pass
        except (MiniWebSocketError, OSError, json.JSONDecodeError) as exc:
            logger.error("[discord_bot] read loop died: %s", exc)
            self._connected = False

    # -- message handling ------------------------------------------------------

    def _handle_message_create(self, d: dict[str, Any]) -> None:
        """Filter + queue an incoming MESSAGE_CREATE payload."""
        author = d.get("author", {}) or {}
        author_id = str(author.get("id", ""))
        # Never answer bots (incl. ourselves) — prevents feedback loops.
        if author.get("bot") or author.get("system") or author_id == self._bot_user_id:
            return
        # Fail-closed user allowlist.
        if self._allowed_users and author_id not in self._allowed_users:
            logger.info(
                "[discord_bot] dropped message from non-allowlisted user %s",
                author_id,
            )
            return

        content = (d.get("content") or "").strip()
        if not content:
            return

        is_dm = not d.get("guild_id")
        mentioned = self._is_mentioned(d)

        if self._respond_to == "dm" and not is_dm:
            return
        if self._respond_to == "mention" and not (is_dm or mentioned):
            return

        cleaned = self._strip_bot_mention(content)
        if not cleaned:
            return

        msg = RealMessage(
            platform=self.platform_name,
            session_id=str(d.get("channel_id", "")),
            sender_id=author_id,
            sender_name=str(author.get("username", "unknown")),
            content=cleaned,
            message_id=str(d.get("id", "")),
            raw={"guild_id": d.get("guild_id"), "mentioned": mentioned, "is_dm": is_dm},
        )
        self._receive_queue.put_nowait(msg)
        logger.info(
            "[discord_bot] ← %s (%s): %s",
            msg.sender_name, msg.sender_id, cleaned[:80],
        )

    def _is_mentioned(self, d: dict[str, Any]) -> bool:
        for m in d.get("mentions", []) or []:
            if str(m.get("id", "")) == self._bot_user_id:
                return True
        # also catch raw <@ID> / <@!ID> that Discord may not expand for
        # stale caches
        if self._bot_user_id:
            content = d.get("content") or ""
            return (
                f"<@{self._bot_user_id}>" in content
                or f"<@!{self._bot_user_id}>" in content
            )
        return False

    def _strip_bot_mention(self, content: str) -> str:
        if not self._bot_user_id:
            return content.strip()
        cleaned = content.replace(f"<@{self._bot_user_id}>", "")
        cleaned = cleaned.replace(f"<@!{self._bot_user_id}>", "")
        return cleaned.strip()

    # -- sending (REST) ----------------------------------------------------------

    async def send_text(self, session_id: str, text: str, **kwargs: Any) -> bool:
        if not self._connected or not session_id:
            return False
        for chunk in split_discord_message(text):
            result = await _http_request(
                "POST",
                f"{DISCORD_API}/channels/{session_id}/messages",
                json_body={"content": chunk},
                headers=self._auth_headers(),
            )
            status = result.get("_status")
            if status not in (None, 200):
                logger.error(
                    "[discord_bot] sendMessage failed: %s %s",
                    status, result.get("message", result),
                )
                return False
        return True

    async def set_typing(self, session_id: str, typing: bool = True) -> None:  # type: ignore[override]
        """Trigger the typing indicator via REST (POST /channels/:id/typing)."""
        if typing and self._connected and session_id and self._send_typing:
            await _http_request(
                "POST",
                f"{DISCORD_API}/channels/{session_id}/typing",
                headers=self._auth_headers(),
            )

    async def get_me(self) -> dict[str, Any]:
        result = await _http_request(
            "GET", f"{DISCORD_API}/users/@me", headers=self._auth_headers()
        )
        if result.get("_status") in (None, 200):
            return {
                "platform": self.platform_name,
                "bot_id": result.get("id"),
                "username": result.get("username"),
                "connected": self._connected,
                "intents": INTENTS,
            }
        return {
            "platform": self.platform_name,
            "error": result.get("message", str(result)),
            "connected": self._connected,
        }


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def split_discord_message(text: str, limit: int = MAX_MESSAGE_LEN) -> list[str]:
    """Split a long message into Discord-sized chunks.

    Prefers newline boundaries, then word boundaries, then hard cuts.
    """
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    remaining = text
    while remaining:
        if len(remaining) <= limit:
            chunks.append(remaining)
            break
        window = remaining[:limit]
        cut = window.rfind("\n")
        if cut < limit // 2:
            cut = window.rfind(" ")
        if cut < limit // 2:
            cut = limit
        chunks.append(remaining[:cut].rstrip())
        remaining = remaining[cut:].lstrip()
    return [c for c in chunks if c]


__all__ = [
    "MiniWebSocket",
    "MiniWebSocketError",
    "RealDiscordBotAdapter",
    "INTENTS",
    "split_discord_message",
    "DISCORD_API",
]
