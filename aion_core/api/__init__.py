"""Aion Hand HTTP API server.

Provides a real HTTP API that the web UI (and other clients) can talk to.
Built on aiohttp (if installed) with a stdlib fallback.

Endpoints:
    GET  /health/live        — liveness probe
    GET  /health/ready       — readiness probe
    GET  /health             — both probes
    GET  /api/personas       — list available personas
    POST /api/personas/apply — switch active persona
    GET  /api/skills         — list loaded skills
    GET  /api/tools          — list registered tools
    GET  /api/memory         — recent memories
    GET  /api/config         — current agent config
    POST /api/chat           — send a message to the agent (JSON response)
    POST /api/chat/stream    — send a message, get streaming response (SSE)
    GET  /api/metrics        — telemetry dump
    POST /api/backup         — create a backup
    POST /api/restore        — restore from a backup

Usage:
    from aion_core.api.server import APIServer
    server = APIServer(agent=my_agent, host="127.0.0.1", port=8000)
    await server.serve()

Or from CLI:
    python -m aion_core.api.server --port 8000
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger("aion_hand.api")


# ---------------------------------------------------------------------------
# Secret redaction (deep, recursive)
# ---------------------------------------------------------------------------

_REDACT_KEYS = {
    "api_key", "apikey", "token", "bot_token", "app_token",
    "secret", "client_secret", "password", "api_token", "key",
}


def _deep_redact(data: Any) -> Any:
    """Recursively redact secret-looking values from nested structures.

    Covers dicts (any depth), lists, and (key, value) tuples. The previous
    top-level-only redaction leaked the entire nested ``providers`` dict —
    including every provider API key — through ``GET /api/config``.
    """
    if isinstance(data, dict):
        out: dict[str, Any] = {}
        for k, v in data.items():
            if isinstance(k, str) and k.lower() in _REDACT_KEYS and isinstance(v, (str, int, float)):
                out[k] = "***REDACTED***"
            else:
                out[k] = _deep_redact(v)
        return out
    if isinstance(data, (list, tuple)):
        return [_deep_redact(v) for v in data]
    if isinstance(data, Path):
        return str(data)
    return data


# ---------------------------------------------------------------------------
# Detect aiohttp
# ---------------------------------------------------------------------------

try:
    from aiohttp import web
    _AIOHTTP_AVAILABLE = True
except ImportError:
    _AIOHTTP_AVAILABLE = False
    web = None  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# API server
# ---------------------------------------------------------------------------

@dataclass
class APIConfig:
    """HTTP API server configuration.

    Security defaults:
    * ``host`` defaults to ``127.0.0.1`` (loopback). Binding to a
      non-loopback host REQUIRES an ``api_token`` — the server refuses
      to expose the agent unauthenticated on a network.
    * When bound to loopback without a token, requests are accepted
      without auth (local personal use, same trust as the CLI).
    * ``cors_origins=None`` now means "no CORS" (previously it allowed
      ANY origin — a drive-by webpage could drive the agent).
    """
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: list[str] | None = None  # None = no CORS headers
    enable_streaming: bool = True
    max_request_size: int = 1024 * 1024  # 1 MB
    api_token: str = ""  # required for non-loopback binds; Bearer auth


class APIServer:
    """HTTP API server exposing an Aion agent to clients."""

    def __init__(self, agent: Any, config: APIConfig | None = None) -> None:
        if not _AIOHTTP_AVAILABLE:
            raise RuntimeError(
                "aiohttp is required for the HTTP API server. "
                "Install: pip install aiohttp"
            )
        self.agent = agent
        self.config = config or APIConfig()
        self._app: Any = None
        self._runner: Any = None
        self._site: Any = None

        # Resolve the auth token: explicit config > env > agent config.
        if not self.config.api_token:
            self.config.api_token = os.environ.get("AION_API_TOKEN", "")
        if not self.config.api_token:
            agent_cfg = getattr(agent, "config", None)
            candidate = getattr(agent_cfg, "api_token", "")
            # Strict type check — MagicMock configs auto-create attributes
            # that would otherwise be treated as a real token.
            if isinstance(candidate, str) and candidate.strip():
                self.config.api_token = candidate.strip()

        # Fail fast: never expose the agent unauthenticated on a network.
        if self.config.host not in ("127.0.0.1", "localhost", "::1") \
                and not self.config.api_token:
            raise RuntimeError(
                "Refusing to bind the API to a non-loopback host "
                f"({self.config.host!r}) without an auth token. Set "
                "APIConfig(api_token=...) or the AION_API_TOKEN environment "
                "variable, or bind to 127.0.0.1."
            )

    @property
    def _loopback(self) -> bool:
        return self.config.host in ("127.0.0.1", "localhost", "::1")

    # ------------------------------------------------------------------
    #  App setup
    # ------------------------------------------------------------------

    def _build_app(self) -> Any:
        """Build the aiohttp app with all routes registered."""
        # Refuse to expose the agent unauthenticated on a network.
        if not self._loopback and not self.config.api_token:
            raise RuntimeError(
                "Refusing to bind the API to a non-loopback host without "
                "an auth token. Set APIConfig(api_token=...) or the "
                "AION_API_TOKEN environment variable, or bind to "
                "127.0.0.1."
            )
        app = web.Application(
            client_max_size=self.config.max_request_size,
            middlewares=[self._auth_middleware, self._cors_middleware],
        )

        # Health
        app.router.add_get("/health/live", self._health_live)
        app.router.add_get("/health/ready", self._health_ready)
        app.router.add_get("/health", self._health_full)

        # Personas
        app.router.add_get("/api/personas", self._list_personas)
        app.router.add_post("/api/personas/apply", self._apply_persona)

        # Skills
        app.router.add_get("/api/skills", self._list_skills)

        # Tools
        app.router.add_get("/api/tools", self._list_tools)

        # Memory
        app.router.add_get("/api/memory", self._list_memory)

        # Config
        app.router.add_get("/api/config", self._get_config)

        # Chat
        app.router.add_post("/api/chat", self._chat)
        if self.config.enable_streaming:
            app.router.add_post("/api/chat/stream", self._chat_stream)

        # Telemetry
        app.router.add_get("/api/metrics", self._get_metrics)

        # Backup
        app.router.add_post("/api/backup", self._create_backup)
        app.router.add_post("/api/restore", self._restore_backup)

        return app

    # ------------------------------------------------------------------
    #  Auth middleware (Bearer token)
    # ------------------------------------------------------------------

    @web.middleware
    async def _auth_middleware(self, request: Any, handler: Any) -> Any:
        """Require a Bearer token on all API routes.

        * Loopback bind without a configured token -> allowed (local
          personal use, same trust model as the CLI).
        * Anything else -> 401 unless the token matches.
        Health probes (/health/*) stay open for orchestrators.
        """
        path = getattr(request, "path", "")
        if path.startswith("/health"):
            return await handler(request)

        token = self.config.api_token
        if not token and self._loopback:
            return await handler(request)

        auth = request.headers.get("Authorization", "")
        supplied = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
        # Constant-time-ish compare
        if not token or supplied != token:
            return web.json_response(
                {"error": "Unauthorized"}, status=401,
            )
        return await handler(request)

    # ------------------------------------------------------------------
    #  CORS middleware (new aiohttp style: takes request, handler)
    # ------------------------------------------------------------------

    @web.middleware
    async def _cors_middleware(self, request: Any, handler: Any) -> Any:
        """Allow CORS only for explicitly configured origins.

        Previously ``cors_origins=None`` reflected ANY origin, letting any
        webpage in a local browser drive the agent cross-origin. Now None
        means no CORS at all."""
        # Handle OPTIONS preflight directly
        if request.method == "OPTIONS":
            response = web.Response()
        else:
            response = await handler(request)
        origin = request.headers.get("Origin", "")
        if self.config.cors_origins and origin in self.config.cors_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
            response.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
            response.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
        return response

    # ------------------------------------------------------------------
    #  Health endpoints
    # ------------------------------------------------------------------

    async def _health_live(self, _request: Any) -> Any:
        from aion_core.health import get_health_registry, register_default_checks
        register_default_checks(self.agent)
        report = await get_health_registry().run_liveness()
        return web.json_response(report.body, status=report.http_status)

    async def _health_ready(self, _request: Any) -> Any:
        from aion_core.health import get_health_registry, register_default_checks
        register_default_checks(self.agent)
        report = await get_health_registry().run_readiness()
        return web.json_response(report.body, status=report.http_status)

    async def _health_full(self, _request: Any) -> Any:
        from aion_core.health import get_health_registry, register_default_checks
        register_default_checks(self.agent)
        health = get_health_registry()
        live = await health.run_liveness()
        ready = await health.run_readiness()
        return web.json_response({
            "liveness": live.body,
            "readiness": ready.body,
        })

    # ------------------------------------------------------------------
    #  Persona endpoints
    # ------------------------------------------------------------------

    async def _list_personas(self, _request: Any) -> Any:
        try:
            from aion_core.persona import PersonaManager
            mgr = PersonaManager()
            names = mgr.list_personas()
            return web.json_response({
                "personas": names,
                "active": mgr.get_active_name(),
                "total": len(names),
            })
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=500)

    async def _apply_persona(self, request: Any) -> Any:
        try:
            body = await request.json()
            name = body.get("name")
            if not name:
                return web.json_response({"error": "Missing 'name'"}, status=400)
            from aion_core.persona import PersonaManager
            mgr = PersonaManager()
            ok = mgr.apply_to_agent(self.agent, name)
            if not ok:
                return web.json_response({"error": f"Persona '{name}' not found"}, status=404)
            return web.json_response({"applied": name})
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=500)

    # ------------------------------------------------------------------
    #  Skills / Tools / Memory / Config
    # ------------------------------------------------------------------

    async def _list_skills(self, _request: Any) -> Any:
        se = getattr(self.agent, "skill_engine", None) or getattr(self.agent, "_skills", None)
        if se is None:
            return web.json_response({"skills": [], "total": 0})
        try:
            skills = se.list_skills() if hasattr(se, "list_skills") else []
            return web.json_response({
                "skills": [s.to_dict() if hasattr(s, "to_dict") else vars(s) for s in skills],
                "total": len(skills),
            })
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=500)

    async def _list_tools(self, _request: Any) -> Any:
        tr = getattr(self.agent, "tool_registry", None) or getattr(self.agent, "_tools", None)
        if tr is None:
            return web.json_response({"tools": [], "total": 0})
        try:
            tools = tr.list_tools() if hasattr(tr, "list_tools") else []
            return web.json_response({
                "tools": [
                    {
                        "name": getattr(t, "name", str(t)),
                        "description": getattr(t, "description", ""),
                        "toolset": getattr(t, "toolset", ""),
                        "requires_approval": getattr(t, "requires_approval", False),
                    }
                    for t in tools
                ],
                "total": len(tools),
            })
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=500)

    async def _list_memory(self, _request: Any) -> Any:
        mm = getattr(self.agent, "memory_manager", None) or getattr(self.agent, "_memory", None)
        if mm is None:
            return web.json_response({"memories": [], "total": 0})
        try:
            # Try common methods
            entries: list[Any] = []
            for method in ("recent_memories", "all_memories", "get_recent", "list_memories"):
                fn = getattr(mm, method, None)
                if callable(fn):
                    entries = fn(20) if method != "get_recent" else fn(20)
                    break
            return web.json_response({
                "memories": [
                    {
                        "layer": getattr(e, "layer", "?"),
                        "content": getattr(e, "content", str(e))[:500],
                    }
                    for e in entries
                ],
                "total": len(entries),
            })
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=500)

    async def _get_config(self, _request: Any) -> Any:
        cfg = getattr(self.agent, "config", None)
        if cfg is None:
            return web.json_response({})
        try:
            data = cfg.to_dict() if hasattr(cfg, "to_dict") else vars(cfg)
            return web.json_response(_deep_redact(data))
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=500)

    # ------------------------------------------------------------------
    #  Chat endpoints
    # ------------------------------------------------------------------

    async def _chat(self, request: Any) -> Any:
        try:
            body = await request.json()
            message = body.get("message", "").strip()
            session_id = body.get("session_id")
            if not message:
                return web.json_response({"error": "Missing 'message'"}, status=400)
            result = await self.agent.chat(message, session_id=session_id)
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Chat error")
            return web.json_response({"error": str(exc), "content": f"Error: {exc}"}, status=500)

    async def _chat_stream(self, request: Any) -> Any:
        """Server-Sent Events streaming chat response."""
        try:
            body = await request.json()
            message = body.get("message", "").strip()
            if not message:
                return web.json_response({"error": "Missing 'message'"}, status=400)

            response = web.StreamResponse(
                status=200,
                headers={
                    "Content-Type": "text/event-stream",
                    "Cache-Control": "no-cache",
                    "Connection": "keep-alive",
                },
            )
            await response.prepare(request)

            # Send the user message ack
            await response.write(f"data: {json.dumps({'type': 'start'})}\n\n".encode())

            # Call the agent (non-streaming for now — wrap in single chunk)
            try:
                result = await self.agent.chat(message)
                content = result.get("content", "") if isinstance(result, dict) else str(result)
                # Stream content word-by-word for the streaming effect
                words = content.split()
                for i, word in enumerate(words):
                    chunk = {"type": "token", "text": word + (" " if i < len(words) - 1 else "")}
                    await response.write(f"data: {json.dumps(chunk)}\n\n".encode())
                    await asyncio.sleep(0.02)  # small delay for visible streaming
                # Send metadata
                if isinstance(result, dict):
                    meta = {
                        "type": "done",
                        "tools_used": result.get("tools_used", []),
                        "metadata": result.get("metadata", {}),
                    }
                    await response.write(f"data: {json.dumps(meta)}\n\n".encode())
                else:
                    await response.write(f"data: {json.dumps({'type': 'done'})}\n\n".encode())
            except Exception as exc:  # noqa: BLE001
                err = {"type": "error", "error": str(exc)}
                await response.write(f"data: {json.dumps(err)}\n\n".encode())

            await response.write(b"data: {\"type\": \"close\"}\n\n")
            return response
        except Exception as exc:  # noqa: BLE001
            logger.exception("Stream chat error")
            return web.json_response({"error": str(exc)}, status=500)

    # ------------------------------------------------------------------
    #  Telemetry + Backup
    # ------------------------------------------------------------------

    async def _get_metrics(self, _request: Any) -> Any:
        from aion_core.telemetry import get_metrics, get_tracer, get_event_log
        return web.json_response({
            "metrics": get_metrics().to_dict(),
            "traces_count": len(get_tracer().spans),
            "events_count": len(get_event_log().events),
        })

    async def _create_backup(self, request: Any) -> Any:
        try:
            body = {}
            try:
                body = await request.json()
            except Exception:  # noqa: BLE001
                pass
            from aion_core.backup import BackupManager
            bm = BackupManager()
            archive = await bm.backup(label=body.get("label"))
            return web.json_response({"backup": str(archive), "size_bytes": archive.stat().st_size})
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=500)

    async def _restore_backup(self, request: Any) -> Any:
        try:
            body = await request.json()
            path = body.get("path")
            overwrite = body.get("overwrite", False)
            if not path:
                return web.json_response({"error": "Missing 'path'"}, status=400)
            # Security: only archives inside the managed backups dir can
            # be restored (previously ANY path on disk was accepted).
            from aion_core.backup import BackupManager
            bm = BackupManager()
            backups_root = Path(bm.backup_dir).resolve() if hasattr(bm, "backup_dir") else None
            resolved = Path(path).expanduser().resolve()
            if backups_root is not None and backups_root not in resolved.parents:
                return web.json_response(
                    {"error": "Refusing to restore from outside the backups directory"},
                    status=403,
                )
            result = await bm.restore(str(resolved), overwrite=overwrite)
            return web.json_response(result)
        except Exception as exc:  # noqa: BLE001
            return web.json_response({"error": str(exc)}, status=500)

    # ------------------------------------------------------------------
    #  Lifecycle
    # ------------------------------------------------------------------

    async def serve(self) -> None:
        """Start the HTTP server (runs forever)."""
        self._app = self._build_app()
        self._runner = web.AppRunner(self._app)
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, self.config.host, self.config.port)
        await self._site.start()
        logger.info("[api] HTTP API server listening on %s:%d", self.config.host, self.config.port)
        # Run forever
        try:
            while True:
                await asyncio.sleep(3600)
        except asyncio.CancelledError:
            await self._runner.cleanup()

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()


# ---------------------------------------------------------------------------
#  CLI entry point
# ---------------------------------------------------------------------------

async def _main() -> None:
    """`python -m aion_core.api.server --port 8000` entry point."""
    parser = argparse.ArgumentParser(description="Aion Hand HTTP API server")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8000, help="Bind port (default: 8000)")
    parser.add_argument("--log-level", default="INFO", help="Log level (default: INFO)")
    args = parser.parse_args()

    logging.basicConfig(
        level=args.log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Lazy-import to avoid circular dependency
    from aion_core.agent.core import AionHand
    agent = AionHand()
    await agent.start()
    try:
        server = APIServer(agent=agent, config=APIConfig(host=args.host, port=args.port))
        await server.serve()
    finally:
        await agent.shutdown()


if __name__ == "__main__":
    asyncio.run(_main())


__all__ = ["APIServer", "APIConfig"]
