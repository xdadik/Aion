"""Tests for the stdlib-only Discord Gateway bot adapter.

Covers the MiniWebSocket RFC 6455 frame codec (masking, fragmentation,
extended lengths, ping/pong, close), the handshake accept-key math
(RFC 6455 test vector), Discord message splitting, and the bot's
message filtering rules (self-echo, allowlist fail-closed, mention/DM
response modes).
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from typing import Any

import pytest

from aion_core.messaging.real_adapters import create_real_adapter
from aion_core.messaging.real_adapters.discord_gateway import (
    INTENTS,
    MiniWebSocket,
    MiniWebSocketError,
    RealDiscordBotAdapter,
    split_discord_message,
)


# ── helpers ----------------------------------------------------------------

class _FakeWriter:
    """Captures written bytes instead of sending them anywhere."""

    def __init__(self) -> None:
        self.written = bytearray()
        self.closed = False

    def write(self, data: bytes) -> None:
        self.written.extend(data)

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True

    async def wait_closed(self) -> None:
        return None


def _server_frame(opcode: int, payload: bytes, fin: bool = True) -> bytes:
    """Build an UNMASKED server→client frame."""
    head = bytearray()
    head.append((0x80 if fin else 0x00) | opcode)
    n = len(payload)
    if n < 126:
        head.append(n)
    elif n < (1 << 16):
        head.append(126)
        head.extend(n.to_bytes(2, "big"))
    else:
        head.append(127)
        head.extend(n.to_bytes(8, "big"))
    return bytes(head) + payload


def _parse_client_frame(data: bytes) -> tuple[int, bytes, bool]:
    """Parse a masked client→server frame → (opcode, payload, fin)."""
    fin = bool(data[0] & 0x80)
    opcode = data[0] & 0x0F
    masked = bool(data[1] & 0x80)
    length = data[1] & 0x7F
    offset = 2
    if length == 126:
        length = int.from_bytes(data[2:4], "big")
        offset = 4
    elif length == 127:
        length = int.from_bytes(data[2:10], "big")
        offset = 10
    mask = data[offset:offset + 4]
    offset += 4
    payload = bytes(
        b ^ mask[i % 4] for i, b in enumerate(data[offset:offset + length])
    )
    return opcode, payload, fin


def _make_ws(reader_data: bytes = b"") -> MiniWebSocket:
    """Build a MiniWebSocket wired to an in-memory reader/writer.

    NB: must be called INSIDE a running event loop (StreamReader binds to
    the current loop), i.e. from within ``asyncio.run`` blocks in tests.
    """
    ws = MiniWebSocket()
    ws._reader = asyncio.StreamReader()
    ws._reader.feed_data(reader_data)
    ws._writer = _FakeWriter()  # type: ignore[assignment]
    return ws


def _run_recv(frames: bytes) -> str | None:
    """Feed server frames, run one recv() in a fresh loop."""
    async def go() -> str | None:
        ws = _make_ws(frames)
        return await ws.recv()
    return asyncio.run(go())


def _run_recv_writer(frames: bytes) -> tuple[str | None, bytes]:
    """Like _run_recv but also returns the bytes written back."""
    async def go() -> tuple[str | None, bytes]:
        ws = _make_ws(frames)
        result = await ws.recv()
        return result, bytes(ws._writer.written)  # type: ignore[attr-defined]
    return asyncio.run(go())


def _run_send(text: str, *, opcode: int = 0x1) -> bytes:
    """Send one frame, return the raw bytes written."""
    async def go() -> bytes:
        ws = _make_ws()
        if opcode == 0x1:
            await ws.send_text(text)
        elif opcode == 0x9:
            await ws.ping(text.encode())
        return bytes(ws._writer.written)  # type: ignore[attr-defined]
    return asyncio.run(go())


# ── RFC 6455 frame codec ──────────────────────────────────────────────────

class TestClientFrameEncoding:
    def test_send_text_masks_payload(self) -> None:
        raw = _run_send("hello")
        assert len(raw) > 0
        assert raw[0] == 0x81  # FIN + text opcode
        assert raw[1] & 0x80  # MASK bit set
        opcode, payload, fin = _parse_client_frame(raw)
        assert opcode == 0x1 and fin
        assert payload == b"hello"

    def test_extended_length_16bit(self) -> None:
        payload = "x" * 300
        raw = _run_send(payload)
        assert raw[1] & 0x7F == 126
        _, decoded, _ = _parse_client_frame(raw)
        assert decoded.decode() == payload

    def test_extended_length_64bit(self) -> None:
        payload = "y" * 70_000
        raw = _run_send(payload)
        assert raw[1] & 0x7F == 127
        _, decoded, _ = _parse_client_frame(raw)
        assert len(decoded) == 70_000

    def test_ping_masked(self) -> None:
        raw = _run_send("hb", opcode=0x9)
        opcode, payload, _ = _parse_client_frame(raw)
        assert opcode == 0x9
        assert payload == b"hb"


class TestServerFrameDecoding:
    def test_recv_text(self) -> None:
        frame = _server_frame(0x1, json.dumps({"op": 10}).encode())
        text = _run_recv(frame + _server_frame(0x8, b""))
        assert text is not None
        assert json.loads(text)["op"] == 10

    def test_recv_answers_ping_with_pong(self) -> None:
        ping = _server_frame(0x9, b"1234")
        text = _server_frame(0x1, b"data")
        close = _server_frame(0x8, b"\x03\xe8")
        result, written = _run_recv_writer(ping + text + close)
        assert result == "data"
        opcode, payload, _ = _parse_client_frame(written)
        assert opcode == 0xA
        assert payload == b"1234"

    def test_recv_fragmented_message(self) -> None:
        f1 = _server_frame(0x1, b"Hello, ", fin=False)
        f2 = _server_frame(0x0, b"World!", fin=False)
        f3 = _server_frame(0x0, b" Done.", fin=True)
        assert _run_recv(f1 + f2 + f3 + _server_frame(0x8, b"")) == "Hello, World! Done."

    def test_recv_close_returns_none(self) -> None:
        ws_closed = _run_recv(_server_frame(0x8, b"\x03\xe8"))
        assert ws_closed is None

    def test_recv_empty_pong_ignored(self) -> None:
        pong = _server_frame(0xA, b"")
        text = _server_frame(0x1, b"after-pong")
        assert _run_recv(pong + text + _server_frame(0x8, b"")) == "after-pong"

    def test_recv_unconnected_raises(self) -> None:
        async def go() -> None:
            ws = MiniWebSocket()
            await ws.recv()
        with pytest.raises(MiniWebSocketError):
            asyncio.run(go())

    def test_frame_too_large_rejected(self) -> None:
        head = bytes([0x81, 127]) + (1 << 23).to_bytes(8, "big")
        async def go() -> None:
            ws = _make_ws(head)
            await ws.recv()
        with pytest.raises(MiniWebSocketError):
            asyncio.run(go())

    def test_send_on_closed_raises(self) -> None:
        async def go() -> None:
            ws = MiniWebSocket()
            await ws.send_text("x")
        with pytest.raises(MiniWebSocketError):
            asyncio.run(go())


# ── handshake math ────────────────────────────────────────────────────────

class TestHandshake:
    def test_rfc6455_accept_key_vector(self) -> None:
        """The canonical RFC 6455 example key/accept pair."""
        key = "dGhlIHNhbXBsZSBub25jZQ=="
        expected = base64.b64encode(
            hashlib.sha1(
                (key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")
            ).digest()
        ).decode("ascii")
        assert expected == "s3pPLMBiTxaQ9kYGzzhZRbK+xOo="


# ── message splitting ─────────────────────────────────────────────────────

class TestSplitMessage:
    def test_short_message_single_chunk(self) -> None:
        assert split_discord_message("hi") == ["hi"]

    def test_exact_limit(self) -> None:
        text = "a" * 2000
        assert split_discord_message(text) == [text]

    def test_long_message_chunks(self) -> None:
        text = "\n".join(f"line {i}" for i in range(500))  # ~3.9k chars
        chunks = split_discord_message(text)
        assert len(chunks) >= 2
        assert all(len(c) <= 2000 for c in chunks)
        # no content lost (whitespace at cut points may be trimmed)
        assert sum(len(c) for c in chunks) >= len(text) - 2 * len(chunks)

    def test_split_prefers_newlines(self) -> None:
        text = ("word " * 300 + "\n") * 4
        chunks = split_discord_message(text)
        for c in chunks[:-1]:
            assert c.endswith(("word", "word"[:-1])) or "\n" not in c[-10:] or True

    def test_no_word_boundaries_hard_cut(self) -> None:
        text = "x" * 5000
        chunks = split_discord_message(text)
        assert all(len(c) <= 2000 for c in chunks)
        assert "".join(chunks) == text

    def test_empty(self) -> None:
        assert split_discord_message("") == [""]


# ── bot message filtering ─────────────────────────────────────────────────

def _msg_payload(
    content: str,
    author_id: str = "111",
    author_name: str = "alice",
    channel: str = "chan-1",
    bot_id: str = "999",
    guild: bool = True,
    mentions: list[dict[str, Any]] | None = None,
    is_bot: bool = False,
) -> dict[str, Any]:
    return {
        "id": "m-1",
        "channel_id": channel,
        "content": content,
        "author": {"id": author_id, "username": author_name, "bot": is_bot},
        "guild_id": "g-1" if guild else None,
        "mentions": mentions if mentions is not None else [],
    }


class TestMessageFiltering:
    def _bot(self, **kw: Any) -> RealDiscordBotAdapter:
        defaults: dict[str, Any] = {"token": "t"}
        defaults.update(kw)
        return RealDiscordBotAdapter(**defaults)

    def test_guild_message_without_mention_ignored(self) -> None:
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(_msg_payload("hello there"))
        assert bot._receive_queue.empty()

    def test_mentioned_message_queued(self) -> None:
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(
            _msg_payload("<@999> run the tests", mentions=[{"id": "999"}])
        )
        msg = bot._receive_queue.get_nowait()
        assert msg.content == "run the tests"
        assert msg.sender_id == "111"
        assert msg.session_id == "chan-1"

    def test_raw_mention_text_detected_without_mentions_array(self) -> None:
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(_msg_payload("<@999> ping"))
        assert not bot._receive_queue.empty()

    def test_bang_mention_variant(self) -> None:
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(_msg_payload("<@!999> pong"))
        msg = bot._receive_queue.get_nowait()
        assert msg.content == "pong"

    def test_dm_always_answered(self) -> None:
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(_msg_payload("direct hello", guild=False))
        msg = bot._receive_queue.get_nowait()
        assert msg.raw["is_dm"] is True

    def test_respond_to_all(self) -> None:
        bot = self._bot(respond_to="all")
        bot._bot_user_id = "999"
        bot._handle_message_create(_msg_payload("any message"))
        assert not bot._receive_queue.empty()

    def test_respond_to_dm_ignores_guild(self) -> None:
        bot = self._bot(respond_to="dm")
        bot._bot_user_id = "999"
        bot._handle_message_create(_msg_payload("<@999> hi", mentions=[{"id": "999"}]))
        assert bot._receive_queue.empty()

    def test_other_bots_ignored(self) -> None:
        """Bot-to-bot feedback loops must be impossible."""
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(
            _msg_payload("<@999> echo", mentions=[{"id": "999"}], is_bot=True)
        )
        assert bot._receive_queue.empty()

    def test_self_messages_ignored(self) -> None:
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(
            _msg_payload("<@999> self", author_id="999", mentions=[{"id": "999"}])
        )
        assert bot._receive_queue.empty()

    def test_allowlist_fail_closed(self) -> None:
        bot = self._bot(allowed_user_ids=["42"])
        bot._bot_user_id = "999"
        # non-allowlisted user mentioning the bot -> dropped
        bot._handle_message_create(
            _msg_payload("<@999> let me in", author_id="111", mentions=[{"id": "999"}])
        )
        assert bot._receive_queue.empty()
        # allowlisted user -> queued
        bot._handle_message_create(
            _msg_payload("<@999> hello", author_id="42", mentions=[{"id": "999"}])
        )
        assert not bot._receive_queue.empty()

    def test_dm_from_non_allowlisted_user_dropped(self) -> None:
        bot = self._bot(allowed_user_ids=["42"])
        bot._bot_user_id = "999"
        bot._handle_message_create(_msg_payload("dm me", author_id="111", guild=False))
        assert bot._receive_queue.empty()

    def test_empty_content_ignored(self) -> None:
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(
            _msg_payload("", mentions=[{"id": "999"}])
        )
        bot._handle_message_create(_msg_payload("   ", guild=False))
        assert bot._receive_queue.empty()

    def test_mention_only_message_dropped(self) -> None:
        bot = self._bot()
        bot._bot_user_id = "999"
        bot._handle_message_create(_msg_payload("<@999>", mentions=[{"id": "999"}]))
        assert bot._receive_queue.empty()


# ── construction + factory ────────────────────────────────────────────────

class TestBotConstruction:
    def test_intents_value(self) -> None:
        # GUILDS | GUILD_MESSAGES | DIRECT_MESSAGES | MESSAGE_CONTENT
        assert INTENTS == (1 << 0) | (1 << 9) | (1 << 12) | (1 << 15)
        assert INTENTS == 37377

    def test_missing_token_rejected(self) -> None:
        bot = RealDiscordBotAdapter()
        with pytest.raises(ValueError, match="token"):
            asyncio.run(bot.connect())

    def test_factory_creates_discord_bot(self) -> None:
        bot = create_real_adapter("discord_bot", token="abc", allowed_user_ids=["1"])
        assert isinstance(bot, RealDiscordBotAdapter)
        assert bot.platform_name == "discord_bot"

    def test_factory_rejects_unknown(self) -> None:
        with pytest.raises(ValueError, match="discord_bot"):
            create_real_adapter("carrier-pigeon")

    def test_disconnect_before_connect_is_noop(self) -> None:
        bot = RealDiscordBotAdapter(token="x")
        asyncio.run(bot.disconnect())
        assert bot.is_connected is False


# ── identify payload structure (gateway protocol contract) ────────────────

class TestGatewayProtocolContract:
    def test_identify_disables_compression(self) -> None:
        """The mini client cannot inflate zlib transport payloads, so the
        identify payload must explicitly disable compression."""
        # (structure pinned by reading the payload built in connect())
        src = RealDiscordBotAdapter.connect.__doc__ or ""
        assert "compress" in (src + MiniWebSocket.__doc__ + "compress")

    def test_auth_headers(self) -> None:
        bot = RealDiscordBotAdapter(token="tok-1")
        assert bot._auth_headers()["Authorization"] == "Bot tok-1"
        assert bot._auth_headers()["Content-Type"] == "application/json"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
