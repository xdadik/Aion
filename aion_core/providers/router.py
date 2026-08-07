"""Production multi-provider routing and failover.

Keeps provider selection out of the agent loop and gives Aion a single,
observable policy for retries, fallbacks, and provider health. API keys remain
owned by provider instances and are never persisted here.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Union

from .factory import BaseProvider, ChatMessage, ProviderFactory, ProviderResponse

logger = logging.getLogger(__name__)


@dataclass
class ProviderRoute:
    """One provider candidate in failover order."""

    name: str
    config: Dict[str, Any] = field(default_factory=dict)
    model: Optional[str] = None
    failures: int = 0
    cooldown_until: float = 0.0


@dataclass
class RouteResult:
    """Provider response plus routing metadata."""

    response: ProviderResponse
    provider: str
    attempts: int
    fallback_used: bool


class ProviderRouter:
    """Route requests across configured providers with bounded failover.

    The router never retries indefinitely. A provider is temporarily cooled
    down after repeated failures, while the next healthy route is attempted.
    """

    def __init__(
        self,
        routes: Sequence[ProviderRoute],
        *,
        failure_threshold: int = 2,
        cooldown_seconds: float = 30.0,
        max_attempts: Optional[int] = None,
    ) -> None:
        if not routes:
            raise ValueError("At least one provider route is required")
        if failure_threshold < 1:
            raise ValueError("failure_threshold must be >= 1")
        if cooldown_seconds < 0:
            raise ValueError("cooldown_seconds must be >= 0")
        self.routes = list(routes)
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self.max_attempts = max_attempts or len(self.routes)
        self._providers: Dict[str, BaseProvider] = {}
        self._lock = asyncio.Lock()

    @classmethod
    def from_config(cls, routes: Sequence[Dict[str, Any]], **kwargs: Any) -> "ProviderRouter":
        """Build a router from plain configuration dictionaries."""
        normalized = []
        for item in routes:
            name = str(item.get("provider", item.get("name", ""))).strip().lower()
            if not name:
                raise ValueError("Each provider route requires provider/name")
            config = dict(item.get("config") or {})
            model = item.get("model")
            normalized.append(ProviderRoute(name=name, config=config, model=model))
        return cls(normalized, **kwargs)

    def _get_provider(self, route: ProviderRoute) -> BaseProvider:
        key = route.name
        if key not in self._providers:
            self._providers[key] = ProviderFactory.create(
                route.name, route.config, default_model=route.model
            )
        return self._providers[key]

    async def _available_routes(self) -> List[ProviderRoute]:
        now = time.monotonic()
        async with self._lock:
            ready = [r for r in self.routes if r.cooldown_until <= now]
            if ready:
                return ready
            # If all are cooling down, allow the earliest route rather than
            # making the caller wait forever.
            return [min(self.routes, key=lambda r: r.cooldown_until)]

    async def _record_failure(self, route: ProviderRoute) -> None:
        async with self._lock:
            route.failures += 1
            if route.failures >= self.failure_threshold:
                route.cooldown_until = time.monotonic() + self.cooldown_seconds
                route.failures = 0

    async def _record_success(self, route: ProviderRoute) -> None:
        async with self._lock:
            route.failures = 0
            route.cooldown_until = 0.0

    async def chat(
        self,
        messages: List[Union[ChatMessage, Dict[str, Any]]],
        *,
        model: Optional[str] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> RouteResult:
        """Send a request using bounded provider failover."""
        routes = await self._available_routes()
        last_error: Optional[Exception] = None
        attempts = 0

        for route in routes[: self.max_attempts]:
            attempts += 1
            try:
                provider = self._get_provider(route)
                response = await provider.chat(
                    messages,
                    model=model or route.model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    tools=tools,
                    **kwargs,
                )
                await self._record_success(route)
                return RouteResult(
                    response=response,
                    provider=route.name,
                    attempts=attempts,
                    fallback_used=attempts > 1,
                )
            except (asyncio.CancelledError, KeyboardInterrupt):
                raise
            except Exception as exc:
                last_error = exc
                logger.warning("Provider %s failed: %s", route.name, exc)
                await self._record_failure(route)

        raise RuntimeError(
            f"All configured providers failed after {attempts} attempt(s): {last_error}"
        ) from last_error

    async def health(self) -> Dict[str, Dict[str, Any]]:
        """Return non-secret readiness information for every route."""
        result: Dict[str, Dict[str, Any]] = {}
        for route in self.routes:
            entry: Dict[str, Any] = {
                "provider": route.name,
                "model": route.model,
                "registered": ProviderFactory.is_registered(route.name),
                "cooling_down": route.cooldown_until > time.monotonic(),
            }
            if not entry["registered"]:
                entry["ready"] = False
                entry["error"] = "provider_not_registered"
                result[route.name] = entry
                continue
            try:
                provider = self._get_provider(route)
                models = await provider.list_models()
                entry["ready"] = True
                entry["model_count"] = len(models)
            except Exception as exc:
                entry["ready"] = False
                entry["error"] = type(exc).__name__
            result[route.name] = entry
        return result
