"""
Provider Factory System for Aion Hand AI Agent Framework.

Enables provider-agnostic LLM access through a unified interface.
Inspired by NullClaw's provider agnosticism, OpenClaw's multi-provider
system, and Hermes Agent's model switching.

Providers:
    - OpenAI (GPT-4o, GPT-4, GPT-3.5-turbo)
    - Anthropic (Claude 3.5 Sonnet, Claude 3 Opus)
    - Google (Gemini Pro, Gemini Ultra)
    - OpenRouter (300+ models)
    - Ollama (local models)
    - Custom (any OpenAI-compatible endpoint)
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import (
    Any,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Data Models
# ============================================================================


@dataclass
class ChatMessage:
    """Represents a single message in a chat conversation."""

    role: str  # system, user, assistant, tool
    content: str
    name: str | None = None
    tool_calls: list[dict[str, Any]] | None = None
    tool_call_id: str | None = None

    def to_openai_dict(self) -> dict[str, Any]:
        """Convert to OpenAI-compatible API dict."""
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        if self.name is not None:
            d["name"] = self.name
        if self.tool_calls is not None:
            d["tool_calls"] = self.tool_calls
        if self.tool_call_id is not None:
            d["tool_call_id"] = self.tool_call_id
        return d

    def to_anthropic_dict(self) -> dict[str, Any]:
        """Convert to Anthropic-compatible API dict.

        Anthropic uses 'content' as a list of blocks and separates
        system messages from the messages array.
        """
        if self.role == "system":
            return {"role": "user", "content": self.content}
        d: dict[str, Any] = {"role": self.role, "content": self.content}
        return d

    def to_google_dict(self) -> dict[str, Any]:
        """Convert to Google Gemini-compatible API dict."""
        role_map = {"assistant": "model"}
        role = role_map.get(self.role, self.role)
        return {"role": role, "parts": [{"text": self.content}]}

    @classmethod
    def from_openai_dict(cls, d: dict[str, Any]) -> ChatMessage:
        """Create ChatMessage from OpenAI API response dict."""
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            name=d.get("name"),
            tool_calls=d.get("tool_calls"),
            tool_call_id=d.get("tool_call_id"),
        )

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ChatMessage:
        """Create ChatMessage from a generic dict."""
        return cls(
            role=d.get("role", "user"),
            content=d.get("content", ""),
            name=d.get("name"),
            tool_calls=d.get("tool_calls"),
            tool_call_id=d.get("tool_call_id"),
        )


@dataclass
class UsageInfo:
    """Token usage information for an API call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> UsageInfo:
        return cls(
            prompt_tokens=d.get("prompt_tokens", 0),
            completion_tokens=d.get("completion_tokens", 0),
            total_tokens=d.get("total_tokens", 0),
        )


@dataclass
class ProviderResponse:
    """Unified response from any LLM provider."""

    content: str
    tool_calls: list[dict[str, Any]] | None = None
    usage: UsageInfo = field(default_factory=UsageInfo)
    model: str = ""
    raw_response: dict[str, Any] | None = None
    finish_reason: str | None = None


# ============================================================================
# Retry and Rate-Limiting Utilities
# ============================================================================


class RetryHandler:
    """Exponential backoff retry logic with configurable parameters."""

    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_status_codes: tuple[int, ...] | None = None,
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_status_codes = retryable_status_codes or (
            429,  # Rate limited
            500,  # Internal server error
            502,  # Bad gateway
            503,  # Service unavailable
            504,  # Gateway timeout
        )

    def _compute_delay(self, attempt: int) -> float:
        """Compute delay for a given retry attempt."""
        delay = self.base_delay * (self.exponential_base ** attempt)
        # Add jitter: 0.5x to 1.5x the computed delay
        import random

        jitter = random.uniform(0.5, 1.5)
        return min(delay * jitter, self.max_delay)

    def is_retryable(self, status_code: int) -> bool:
        """Check if a status code is retryable."""
        return status_code in self.retryable_status_codes

    async def execute(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Execute a function with retry logic.

        The function should return a tuple of (status_code, result) or
        raise an exception. On retryable errors, it will be retried.
        """
        last_exception: Exception | None = None

        for attempt in range(self.max_retries + 1):
            try:
                result = await func(*args, **kwargs)
                return result
            except _RetryableError as exc:
                last_exception = exc
                if attempt < self.max_retries:
                    delay = self._compute_delay(attempt)
                    logger.warning(
                        "Retryable error on attempt %d/%d for %s: %s. "
                        "Retrying in %.1fs...",
                        attempt + 1,
                        self.max_retries + 1,
                        getattr(func, "__name__", str(func)),
                        exc,
                        delay,
                    )
                    await asyncio.sleep(delay)
                else:
                    logger.error(
                        "Max retries (%d) exceeded for %s",
                        self.max_retries,
                        getattr(func, "__name__", str(func)),
                    )
            except Exception as exc:
                last_exception = exc
                logger.error(
                    "Non-retryable error for %s: %s",
                    getattr(func, "__name__", str(func)),
                    exc,
                )
                break

        if last_exception is not None:
            raise last_exception
        raise RuntimeError("RetryHandler: unexpected state")


class _RetryableError(Exception):
    """Internal exception to signal a retryable failure."""

    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}: {message}")


class RateLimiter:
    """Token-bucket rate limiter for API calls."""

    def __init__(self, requests_per_minute: float = 60.0, burst: int = 10):
        self.rate = requests_per_minute / 60.0  # requests per second
        self.burst = burst
        self._tokens: float = float(burst)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available."""
        async with self._lock:
            self._refill()
            if self._tokens < 1.0:
                wait_time = (1.0 - self._tokens) / self.rate
                await asyncio.sleep(wait_time)
                self._refill()
            self._tokens -= 1.0

    def _refill(self) -> None:
        """Refill tokens based on elapsed time."""
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self.burst, self._tokens + elapsed * self.rate)
        self._last_refill = now


# ============================================================================
# HTTP Client Utility
# ============================================================================


async def _http_post_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float = 120.0,
) -> dict[str, Any]:
    """Make an async HTTP POST with JSON body.

    Uses the 'aiohttp' library if available, otherwise falls back to
    asyncio + urllib.request. Returns the parsed JSON response.
    """
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )

    loop = asyncio.get_event_loop()
    try:
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=timeout),
            ),
            timeout=timeout + 5,
        )
        raw = response.read().decode("utf-8")
        return json.loads(raw)
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            error_body = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            error_body = {"error": {"message": raw}}
        if exc.code in (429, 500, 502, 503, 504):
            raise _RetryableError(exc.code, str(error_body)) from exc
        raise
    except Exception:
        raise


async def _http_post_stream(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    timeout: float = 120.0,
) -> AsyncIterator[dict[str, Any]]:
    """Make an async HTTP POST and yield server-sent event chunks.

    Returns an async iterator of parsed JSON delta objects.
    """
    import urllib.error
    import urllib.request

    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={**headers, "Content-Type": "application/json"},
        method="POST",
    )

    loop = asyncio.get_event_loop()

    try:
        response = await asyncio.wait_for(
            loop.run_in_executor(
                None,
                lambda: urllib.request.urlopen(req, timeout=timeout),
            ),
            timeout=timeout + 5,
        )
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        if exc.code in (429, 500, 502, 503, 504):
            raise _RetryableError(exc.code, raw) from exc
        raise

    buffer = ""
    while True:
        chunk = await asyncio.wait_for(
            loop.run_in_executor(None, lambda: response.read(4096)),
            timeout=timeout + 5,
        )
        if not chunk:
            break
        buffer += chunk.decode("utf-8", errors="replace")

        while "\n" in buffer:
            line, buffer = buffer.split("\n", 1)
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    return
                try:
                    yield json.loads(data_str)
                except json.JSONDecodeError:
                    logger.debug("Skipping malformed SSE line: %s", line)
                    continue


# ============================================================================
# Base Provider
# ============================================================================


class BaseProvider(ABC):
    """Abstract base class for all LLM providers."""

    def __init__(
        self,
        api_key: str | None = None,
        default_model: str | None = None,
        base_url: str | None = None,
        max_retries: int = 3,
        rate_limit_rpm: float = 60.0,
        timeout: float = 120.0,
        **kwargs: Any,
    ):
        self.api_key = api_key
        self.default_model = default_model or self.get_default_model()
        self.base_url = (base_url or self.BASE_URL).rstrip("/")
        self.timeout = timeout
        self.retry_handler = RetryHandler(max_retries=max_retries)
        self.rate_limiter = RateLimiter(requests_per_minute=rate_limit_rpm)
        self._extra_config = kwargs

    BASE_URL: str = ""
    PROVIDER_NAME: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        """Send a chat completion request and return a unified response."""
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens as an async iterator."""
        ...  # type: ignore[misc]

    @abstractmethod
    async def list_models(self) -> list[str]:
        """List available models for this provider."""
        ...

    @abstractmethod
    def get_default_model(self) -> str:
        """Return the default model identifier."""
        ...

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _normalize_messages(
        self,
        messages: list[ChatMessage | dict[str, Any]],
    ) -> list[ChatMessage]:
        """Ensure all entries are ChatMessage instances."""
        result: list[ChatMessage] = []
        for m in messages:
            if isinstance(m, ChatMessage):
                result.append(m)
            elif isinstance(m, dict):
                result.append(ChatMessage.from_dict(m))
            else:
                raise TypeError(f"Unsupported message type: {type(m)}")
        return result

    async def _with_retry(self, func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute a callable with rate limiting and retry logic."""
        await self.rate_limiter.acquire()
        return await self.retry_handler.execute(func, *args, **kwargs)


# ============================================================================
# OpenAI Provider
# ============================================================================


class OpenAIProvider(BaseProvider):
    """Provider for the OpenAI API.

    Supported models: GPT-4o, GPT-4, GPT-4 Turbo, GPT-3.5-turbo, and
    any other model available through the OpenAI API.
    """

    BASE_URL = "https://api.openai.com/v1"
    PROVIDER_NAME = "openai"

    _KNOWN_MODELS: list[str] = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4-turbo-preview",
        "gpt-4",
        "gpt-4-32k",
        "gpt-3.5-turbo",
        "gpt-3.5-turbo-16k",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not self.api_key:
            raise ValueError("OpenAI provider requires an 'api_key' configuration.")

    def get_default_model(self) -> str:
        return "gpt-4o"

    def _build_headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_openai_dict() for m in messages],
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        return payload

    async def chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload = self._build_payload(
            normalized, model, temperature, max_tokens, tools, **kwargs
        )

        async def _do_request() -> ProviderResponse:
            url = f"{self.base_url}/chat/completions"
            raw = await _http_post_json(
                url, self._build_headers(), payload, timeout=self.timeout
            )
            return self._parse_response(raw, model)

        return await self._with_retry(_do_request)

    async def chat_stream(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload = self._build_payload(
            normalized, model, temperature, max_tokens, tools, stream=True, **kwargs
        )

        url = f"{self.base_url}/chat/completions"
        await self.rate_limiter.acquire()

        async for chunk in _http_post_stream(
            url, self._build_headers(), payload, timeout=self.timeout
        ):
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content

    async def list_models(self) -> list[str]:
        """List available models from the OpenAI API."""
        try:
            import urllib.request

            url = f"{self.base_url}/models"
            req = urllib.request.Request(
                url,
                headers=self._build_headers(),
                method="GET",
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=self.timeout)
            )
            data = json.loads(response.read().decode("utf-8"))
            models = [m["id"] for m in data.get("data", [])]
            models.sort()
            return models
        except Exception as exc:
            logger.warning("Failed to list OpenAI models: %s", exc)
            return list(self._KNOWN_MODELS)

    def _parse_response(self, raw: dict[str, Any], model: str) -> ProviderResponse:
        """Parse the OpenAI API response into a ProviderResponse."""
        # NB: `or [{}]` (not `get` default) — providers can return an EMPTY
        # choices list (content filter / safety refusal) which would crash
        # with IndexError otherwise.
        choice = (raw.get("choices") or [{}])[0]
        message = choice.get("message", {})
        usage_data = raw.get("usage", {})

        return ProviderResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            usage=UsageInfo.from_dict(usage_data),
            model=raw.get("model", model),
            raw_response=raw,
            finish_reason=choice.get("finish_reason"),
        )


# ============================================================================
# Anthropic Provider
# ============================================================================


class AnthropicProvider(BaseProvider):
    """Provider for the Anthropic Claude API.

    Supported models: Claude 3.5 Sonnet, Claude 3 Opus, Claude 3 Sonnet,
    Claude 3 Haiku, and any other Anthropic model.
    """

    BASE_URL = "https://api.anthropic.com/v1"
    PROVIDER_NAME = "anthropic"

    _KNOWN_MODELS: list[str] = [
        "claude-sonnet-4-20250514",
        "claude-opus-4-20250514",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-latest",
        "claude-3-5-haiku-20241022",
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
    ]

    # Anthropic uses a specific API version header.
    _ANTHROPIC_VERSION = "2023-06-01"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not self.api_key:
            raise ValueError(
                "Anthropic provider requires an 'api_key' configuration."
            )

    def get_default_model(self) -> str:
        return "claude-3-5-sonnet-20241022"

    def _build_headers(self) -> dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": self._ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }

    def _build_payload(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        # Anthropic separates system messages from the messages array.
        system_content: str = ""
        api_messages: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_content += msg.content + "\n"
            else:
                api_messages.append(msg.to_anthropic_dict())

        payload: dict[str, Any] = {
            "model": model,
            "messages": api_messages,
            "max_tokens": max_tokens or 4096,
            "stream": stream,
        }

        if system_content.strip():
            payload["system"] = system_content.strip()

        if temperature is not None:
            payload["temperature"] = temperature

        if tools:
            anthropic_tools = []
            for tool in tools:
                at = {
                    "name": tool["function"]["name"],
                    "description": tool["function"].get("description", ""),
                    "input_schema": tool["function"].get("parameters", {}),
                }
                anthropic_tools.append(at)
            payload["tools"] = anthropic_tools

        payload.update(kwargs)
        return payload

    async def chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload = self._build_payload(
            normalized, model, temperature, max_tokens, tools, **kwargs
        )

        async def _do_request() -> ProviderResponse:
            url = f"{self.base_url}/messages"
            raw = await _http_post_json(
                url, self._build_headers(), payload, timeout=self.timeout
            )
            return self._parse_response(raw, model)

        return await self._with_retry(_do_request)

    async def chat_stream(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload = self._build_payload(
            normalized, model, temperature, max_tokens, tools,
            stream=True, **kwargs
        )

        url = f"{self.base_url}/messages"
        await self.rate_limiter.acquire()

        async for chunk in _http_post_stream(
            url, self._build_headers(), payload, timeout=self.timeout
        ):
            event_type = chunk.get("type", "")

            if event_type == "content_block_delta":
                delta = chunk.get("delta", {})
                if delta.get("type") == "text_delta":
                    text = delta.get("text", "")
                    if text:
                        yield text

            # Handle tool-use blocks in streaming.
            elif event_type == "content_block_start":
                content_block = chunk.get("content_block", {})
                if content_block.get("type") == "tool_use":
                    # Emit tool call info as JSON string.
                    yield json.dumps({
                        "__tool_call_start__": True,
                        "id": content_block.get("id", ""),
                        "name": content_block.get("name", ""),
                    })

            elif event_type == "content_block_stop":
                pass

    async def list_models(self) -> list[str]:
        """Anthropic doesn't have a public models list endpoint.
        Return known models.
        """
        return list(self._KNOWN_MODELS)

    def _parse_response(self, raw: dict[str, Any], model: str) -> ProviderResponse:
        """Parse the Anthropic API response into a ProviderResponse."""
        content_text = ""
        tool_calls: list[dict[str, Any]] = []

        for block in raw.get("content", []):
            if block.get("type") == "text":
                content_text += block.get("text", "")
            elif block.get("type") == "tool_use":
                tool_calls.append({
                    "id": block.get("id", ""),
                    "type": "function",
                    "function": {
                        "name": block.get("name", ""),
                        "arguments": json.dumps(block.get("input", {})),
                    },
                })

        usage_data = raw.get("usage", {})
        usage = UsageInfo(
            prompt_tokens=usage_data.get("input_tokens", 0),
            completion_tokens=usage_data.get("output_tokens", 0),
            total_tokens=(
                usage_data.get("input_tokens", 0)
                + usage_data.get("output_tokens", 0)
            ),
        )

        stop_reason = raw.get("stop_reason")
        # Map Anthropic stop reasons to OpenAI-style finish reasons.
        finish_reason_map = {
            "end_turn": "stop",
            "max_tokens": "length",
            "tool_use": "tool_calls",
            "stop_sequence": "stop",
        }

        return ProviderResponse(
            content=content_text,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            model=raw.get("model", model),
            raw_response=raw,
            finish_reason=finish_reason_map.get(stop_reason),
        )


# ============================================================================
# Google (Gemini) Provider
# ============================================================================


class GoogleProvider(BaseProvider):
    """Provider for the Google Gemini API.

    Supported models: Gemini Pro, Gemini Ultra, Gemini Flash.
    """

    BASE_URL = "https://generativelanguage.googleapis.com/v1beta"
    PROVIDER_NAME = "google"

    _KNOWN_MODELS: list[str] = [
        "gemini-2.5-pro-preview-06-05",
        "gemini-2.5-flash-preview-05-20",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
        "gemini-1.5-flash",
        "gemini-1.0-pro",
    ]

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not self.api_key:
            raise ValueError(
                "Google provider requires an 'api_key' configuration."
            )

    def get_default_model(self) -> str:
        return "gemini-2.0-flash"

    def _build_url(self, model: str, stream: bool = False) -> str:
        action = "streamGenerateContent" if stream else "generateContent"
        return (
            f"{self.base_url}/models/{model}:{action}"
            f"?key={self.api_key}"
        )

    def _build_payload(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        system_instruction = None
        gemini_contents: list[dict[str, Any]] = []

        for msg in messages:
            if msg.role == "system":
                system_instruction = {"parts": [{"text": msg.content}]}
            else:
                gemini_contents.append(msg.to_google_dict())

        payload: dict[str, Any] = {
            "contents": gemini_contents,
        }

        if system_instruction:
            payload["systemInstruction"] = system_instruction

        generation_config: dict[str, Any] = {}
        if temperature is not None:
            generation_config["temperature"] = temperature
        if max_tokens is not None:
            generation_config["maxOutputTokens"] = max_tokens
        if generation_config:
            payload["generationConfig"] = generation_config

        # Convert OpenAI-style tools to Gemini function declarations.
        if tools:
            function_decls = []
            for tool in tools:
                func = tool.get("function", tool)
                function_decls.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "parameters": func.get("parameters", {}),
                })
            payload["tools"] = [{"functionDeclarations": function_decls}]

        payload.update(kwargs)
        return payload

    async def chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload = self._build_payload(
            normalized, model, temperature, max_tokens, tools, **kwargs
        )

        async def _do_request() -> ProviderResponse:
            url = self._build_url(model)
            raw = await _http_post_json(
                url, {}, payload, timeout=self.timeout
            )
            return self._parse_response(raw, model)

        return await self._with_retry(_do_request)

    async def chat_stream(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload = self._build_payload(
            normalized, model, temperature, max_tokens, tools, **kwargs
        )

        url = self._build_url(model, stream=True)
        await self.rate_limiter.acquire()

        async for chunk in _http_post_stream(
            url, {}, payload, timeout=self.timeout
        ):
            candidates = chunk.get("candidates", [])
            if candidates:
                parts = candidates[0].get("content", {}).get("parts", [])
                for part in parts:
                    text = part.get("text", "")
                    if text:
                        yield text

    async def list_models(self) -> list[str]:
        """List available Gemini models."""
        try:
            import urllib.request

            url = f"{self.base_url}/models?key={self.api_key}"
            req = urllib.request.Request(url, method="GET")
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=self.timeout)
            )
            data = json.loads(response.read().decode("utf-8"))
            models = [
                m["name"].replace("models/", "")
                for m in data.get("models", [])
                if "generateContent" in m.get("supportedGenerationMethods", [])
            ]
            models.sort()
            return models
        except Exception as exc:
            logger.warning("Failed to list Google models: %s", exc)
            return list(self._KNOWN_MODELS)

    def _parse_response(self, raw: dict[str, Any], model: str) -> ProviderResponse:
        """Parse the Google Gemini API response into a ProviderResponse."""
        candidates = raw.get("candidates", [])
        content_text = ""
        tool_calls: list[dict[str, Any]] | None = None
        finish_reason = None

        if candidates:
            candidate = candidates[0]
            parts = candidate.get("content", {}).get("parts", [])
            for part in parts:
                if "text" in part:
                    content_text += part["text"]
                elif "functionCall" in part:
                    if tool_calls is None:
                        tool_calls = []
                    fc = part["functionCall"]
                    tool_calls.append({
                        "id": str(uuid.uuid4()),
                        "type": "function",
                        "function": {
                            "name": fc.get("name", ""),
                            "arguments": json.dumps(fc.get("args", {})),
                        },
                    })

            reason = candidate.get("finishReason", "")
            reason_map = {
                "STOP": "stop",
                "MAX_TOKENS": "length",
                "SAFETY": "content_filter",
            }
            finish_reason = reason_map.get(reason)

        usage_meta = raw.get("usageMetadata", {})
        usage = UsageInfo(
            prompt_tokens=usage_meta.get("promptTokenCount", 0),
            completion_tokens=usage_meta.get("candidatesTokenCount", 0),
            total_tokens=usage_meta.get("totalTokenCount", 0),
        )

        return ProviderResponse(
            content=content_text,
            tool_calls=tool_calls,
            usage=usage,
            model=raw.get("modelVersion", model),
            raw_response=raw,
            finish_reason=finish_reason,
        )


# ============================================================================
# OpenRouter Provider
# ============================================================================


class OpenRouterProvider(BaseProvider):
    """Provider for the OpenRouter API.

    OpenRouter aggregates 300+ models from multiple providers into a
    single unified API. Uses the OpenAI-compatible chat completions format.
    """

    BASE_URL = "https://openrouter.ai/api/v1"
    PROVIDER_NAME = "openrouter"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        if not self.api_key:
            raise ValueError(
                "OpenRouter provider requires an 'api_key' configuration."
            )

    def get_default_model(self) -> str:
        return "openai/gpt-4o"

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": self._extra_config.get(
                "site_url", "https://aion-hand.dev"
            ),
            "X-Title": self._extra_config.get(
                "app_name", "Aion Hand"
            ),
        }
        return headers

    async def chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_openai_dict() for m in normalized],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)

        async def _do_request() -> ProviderResponse:
            url = f"{self.base_url}/chat/completions"
            raw = await _http_post_json(
                url, self._build_headers(), payload, timeout=self.timeout
            )
            # OpenRouter uses the same format as OpenAI.
            return self._parse_openai_response(raw, model)

        return await self._with_retry(_do_request)

    async def chat_stream(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_openai_dict() for m in normalized],
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)

        url = f"{self.base_url}/chat/completions"
        await self.rate_limiter.acquire()

        async for chunk in _http_post_stream(
            url, self._build_headers(), payload, timeout=self.timeout
        ):
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content

    async def list_models(self) -> list[str]:
        """List models available on OpenRouter."""
        try:
            import urllib.request

            url = f"{self.base_url}/models"
            req = urllib.request.Request(
                url, headers=self._build_headers(), method="GET"
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=self.timeout)
            )
            data = json.loads(response.read().decode("utf-8"))
            models = [m["id"] for m in data.get("data", [])]
            models.sort()
            return models
        except Exception as exc:
            logger.warning("Failed to list OpenRouter models: %s", exc)
            return []

    def _parse_openai_response(
        self, raw: dict[str, Any], model: str
    ) -> ProviderResponse:
        """Parse OpenAI-format response (shared by OpenRouter)."""
        # `or [{}]`: an empty choices list (content filter) must not crash.
        choice = (raw.get("choices") or [{}])[0]
        message = choice.get("message", {})
        usage_data = raw.get("usage", {})

        return ProviderResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            usage=UsageInfo.from_dict(usage_data),
            model=raw.get("model", model),
            raw_response=raw,
            finish_reason=choice.get("finish_reason"),
        )


# ============================================================================
# Ollama Provider
# ============================================================================


class OllamaProvider(BaseProvider):
    """Provider for locally-running Ollama models.

    Ollama exposes an OpenAI-compatible API at /v1/chat/completions as
    well as its native API at /api/chat and /api/tags.
    """

    BASE_URL = "http://localhost:11434"
    PROVIDER_NAME = "ollama"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Ollama typically doesn't require an API key.

    def get_default_model(self) -> str:
        return "llama3"

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _build_payload(
        self,
        messages: list[ChatMessage],
        model: str,
        temperature: float | None,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        stream: bool = False,
        **kwargs: Any,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_openai_dict() for m in messages],
            "stream": stream,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        elif "num_predict" not in kwargs:
            payload["num_predict"] = 4096
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)
        return payload

    async def chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload = self._build_payload(
            normalized, model, temperature, max_tokens, tools, **kwargs
        )

        async def _do_request() -> ProviderResponse:
            # Prefer the native Ollama API for richer response data.
            url = f"{self.base_url}/api/chat"
            raw = await _http_post_json(
                url, self._build_headers(), payload, timeout=self.timeout
            )
            return self._parse_response(raw, model)

        return await self._with_retry(_do_request)

    async def chat_stream(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload = self._build_payload(
            normalized, model, temperature, max_tokens, tools, stream=True, **kwargs
        )

        url = f"{self.base_url}/api/chat"
        await self.rate_limiter.acquire()

        async for chunk in _http_post_stream(
            url, self._build_headers(), payload, timeout=self.timeout
        ):
            # Ollama native streaming returns {"message": {"content": "..."}}
            message = chunk.get("message", {})
            content = message.get("content", "")
            if content:
                yield content

            if chunk.get("done", False):
                break

    async def list_models(self) -> list[str]:
        """List locally available Ollama models."""
        try:
            import urllib.request

            url = f"{self.base_url}/api/tags"
            req = urllib.request.Request(url, method="GET")
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=10)
            )
            data = json.loads(response.read().decode("utf-8"))
            models = [m["name"] for m in data.get("models", [])]
            models.sort()
            return models
        except Exception as exc:
            logger.warning("Failed to list Ollama models: %s", exc)
            return ["llama3"]

    def _parse_response(self, raw: dict[str, Any], model: str) -> ProviderResponse:
        """Parse the Ollama native API response."""
        message = raw.get("message", {})
        content = message.get("content", "")

        tool_calls = message.get("tool_calls")

        eval_count = raw.get("eval_count", 0)
        prompt_eval_count = raw.get("prompt_eval_count", 0)
        usage = UsageInfo(
            prompt_tokens=prompt_eval_count,
            completion_tokens=eval_count,
            total_tokens=prompt_eval_count + eval_count,
        )

        return ProviderResponse(
            content=content,
            tool_calls=tool_calls if tool_calls else None,
            usage=usage,
            model=raw.get("model", model),
            raw_response=raw,
            finish_reason="stop" if raw.get("done") else None,
        )


# ============================================================================
# Custom (OpenAI-compatible) Provider
# ============================================================================


class CustomProvider(BaseProvider):
    """Provider for any OpenAI-compatible custom endpoint.

    This allows connecting to self-hosted LLM servers, vLLM, TGI,
    LiteLLM proxy, or any service that implements the OpenAI chat
    completions API format.
    """

    BASE_URL = "http://localhost:8000/v1"
    PROVIDER_NAME = "custom"

    def __init__(self, **kwargs: Any) -> None:
        if "base_url" not in kwargs and not kwargs.get("base_url"):
            # Allow base_url to be set via the config dict.
            config = kwargs.get("config", {})
            if "base_url" in config:
                kwargs["base_url"] = config["base_url"]
        super().__init__(**kwargs)

    def get_default_model(self) -> str:
        return self._extra_config.get(
            "default_model", "default"
        )

    def _build_headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        # Allow extra headers from config.
        extra_headers = self._extra_config.get("headers", {})
        headers.update(extra_headers)
        return headers

    async def chat(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> ProviderResponse:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_openai_dict() for m in normalized],
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)

        async def _do_request() -> ProviderResponse:
            url = f"{self.base_url}/chat/completions"
            raw = await _http_post_json(
                url, self._build_headers(), payload, timeout=self.timeout
            )
            return self._parse_response(raw, model)

        return await self._with_retry(_do_request)

    async def chat_stream(
        self,
        messages: list[ChatMessage | dict[str, Any]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        normalized = self._normalize_messages(messages)
        model = model or self.default_model

        payload: dict[str, Any] = {
            "model": model,
            "messages": [m.to_openai_dict() for m in normalized],
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        payload.update(kwargs)

        url = f"{self.base_url}/chat/completions"
        await self.rate_limiter.acquire()

        async for chunk in _http_post_stream(
            url, self._build_headers(), payload, timeout=self.timeout
        ):
            choices = chunk.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content")
                if content:
                    yield content

    async def list_models(self) -> list[str]:
        """Try to list models from the custom endpoint."""
        try:
            import urllib.request

            url = f"{self.base_url}/models"
            req = urllib.request.Request(
                url, headers=self._build_headers(), method="GET"
            )
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None, lambda: urllib.request.urlopen(req, timeout=10)
            )
            data = json.loads(response.read().decode("utf-8"))
            models = [m["id"] for m in data.get("data", [])]
            models.sort()
            return models
        except Exception as exc:
            logger.warning("Failed to list custom provider models: %s", exc)
            return []

    def _parse_response(self, raw: dict[str, Any], model: str) -> ProviderResponse:
        """Parse OpenAI-format response from custom endpoint."""
        choice = raw.get("choices", [{}])[0]
        message = choice.get("message", {})
        usage_data = raw.get("usage", {})

        return ProviderResponse(
            content=message.get("content", ""),
            tool_calls=message.get("tool_calls"),
            usage=UsageInfo.from_dict(usage_data),
            model=raw.get("model", model),
            raw_response=raw,
            finish_reason=choice.get("finish_reason"),
        )


# ============================================================================
# Provider Registry & Factory
# ============================================================================


# Registry mapping provider names (lowercase) to provider classes.
_PROVIDER_REGISTRY: dict[str, type[BaseProvider]] = {
    "openai": OpenAIProvider,
    "anthropic": AnthropicProvider,
    "google": GoogleProvider,
    "gemini": GoogleProvider,  # Alias
    "openrouter": OpenRouterProvider,
    "ollama": OllamaProvider,
    "custom": CustomProvider,
}


class ProviderFactory:
    """Factory for creating LLM provider instances.

    Usage examples::

        # Create from a config dict (OpenClaw-style snake_case config):
        provider = ProviderFactory.create(
            provider_name="openai",
            config={"api_key": "sk-...", "default_model": "gpt-4o"},
        )
        response = await provider.chat([
            ChatMessage(role="user", content="Hello!")
        ])

        # Switch models (Hermes-style):
        response = await provider.chat(messages, model="gpt-4")

        # Create from environment:
        provider = ProviderFactory.from_env("openai")
    """

    @staticmethod
    def create(
        provider_name: str,
        config: dict[str, Any] | None = None,
        default_model: str | None = None,
    ) -> BaseProvider:
        """Create a provider instance by name.

        Args:
            provider_name: The provider identifier (e.g. "openai",
                "anthropic", "google", "openrouter", "ollama", "custom").
            config: Configuration dict with keys like ``api_key``,
                ``base_url``, ``max_retries``, ``rate_limit_rpm``,
                ``timeout``, and any provider-specific options.
            default_model: Override the provider's default model.

        Returns:
            An initialized ``BaseProvider`` subclass instance.

        Raises:
            ValueError: If the provider name is unknown or required
                configuration is missing.
        """
        config = config or {}
        name_key = provider_name.lower().strip()

        provider_cls = _PROVIDER_REGISTRY.get(name_key)
        if provider_cls is None:
            available = ", ".join(sorted(_PROVIDER_REGISTRY.keys()))
            raise ValueError(
                f"Unknown provider '{provider_name}'. "
                f"Available providers: {available}"
            )

        # Build the kwargs for the provider constructor.
        kwargs: dict[str, Any] = {}

        # Standard config keys.
        standard_keys = {
            "api_key", "base_url", "max_retries", "rate_limit_rpm",
            "timeout", "default_model",
        }
        for key in standard_keys:
            if key in config:
                kwargs[key] = config[key]

        # Override default_model if explicitly passed.
        if default_model is not None:
            kwargs["default_model"] = default_model

        # Pass through any extra config that might be provider-specific.
        for key, value in config.items():
            if key not in standard_keys and key not in kwargs:
                kwargs[key] = value

        try:
            instance = provider_cls(**kwargs)
            logger.info(
                "Created %s provider (model=%s)",
                provider_cls.PROVIDER_NAME,
                instance.default_model,
            )
            return instance
        except Exception as exc:
            raise ValueError(
                f"Failed to create provider '{provider_name}': {exc}"
            ) from exc

    @staticmethod
    def from_env(provider_name: str) -> BaseProvider:
        """Create a provider using environment variables.

        Looks for ``<PROVIDER>_API_KEY`` and optionally
        ``<PROVIDER>_BASE_URL`` environment variables.

        Provider name mapping for env vars:
            - openai -> OPENAI_API_KEY
            - anthropic -> ANTHROPIC_API_KEY
            - google -> GOOGLE_API_KEY
            - openrouter -> OPENROUTER_API_KEY
            - ollama -> OLLAMA_API_KEY (optional)
            - custom -> CUSTOM_API_KEY, CUSTOM_BASE_URL
        """
        import os

        name_key = provider_name.lower().strip()
        env_prefix_map = {
            "openai": "OPENAI",
            "anthropic": "ANTHROPIC",
            "google": "GOOGLE",
            "gemini": "GOOGLE",
            "openrouter": "OPENROUTER",
            "ollama": "OLLAMA",
            "custom": "CUSTOM",
        }
        prefix = env_prefix_map.get(name_key, name_key.upper())

        config: dict[str, Any] = {}

        api_key = os.environ.get(f"{prefix}_API_KEY")
        if api_key and name_key != "ollama":
            config["api_key"] = api_key

        base_url = os.environ.get(f"{prefix}_BASE_URL")
        if base_url:
            config["base_url"] = base_url

        return ProviderFactory.create(provider_name, config)

    @staticmethod
    def register_provider(
        name: str,
        provider_cls: type[BaseProvider],
    ) -> None:
        """Register a custom provider class.

        This allows third-party code to extend the factory with new
        provider implementations.

        Args:
            name: The provider name to register (lowercased).
            provider_cls: A subclass of ``BaseProvider``.

        Raises:
            TypeError: If ``provider_cls`` is not a ``BaseProvider`` subclass.
        """
        if not (isinstance(provider_cls, type) and issubclass(provider_cls, BaseProvider)):
            raise TypeError(
                f"provider_cls must be a BaseProvider subclass, "
                f"got {provider_cls!r}"
            )
        _PROVIDER_REGISTRY[name.lower().strip()] = provider_cls
        logger.info("Registered provider: %s -> %s", name, provider_cls.__name__)

    @staticmethod
    def list_providers() -> list[str]:
        """Return a sorted list of all registered provider names."""
        return sorted(_PROVIDER_REGISTRY.keys())

    @staticmethod
    def is_registered(name: str) -> bool:
        """Check if a provider name is registered."""
        return name.lower().strip() in _PROVIDER_REGISTRY


# ======================================================================
# Provider fallback chain (Hermes fallback_providers parity)
# ======================================================================


class ProviderChain:
    """Try providers in order; on rate-limit / server errors, fail over.

    Hermes ships ``fallback_providers`` config so a 429/5xx on the primary
    model transparently retries on the next provider. This is Aion's port:
    wrap any set of instantiated providers and expose the BaseProvider
    ``chat`` surface.

    Usage::

        chain = ProviderChain(
            primary=openai_provider,
            fallbacks=[anthropic_provider, ollama_provider],
        )
        response = await chain.chat(messages)   # automatic failover
    """

    # Error substrings that justify failing over to the next provider.
    _TRANSIENT_MARKERS = (
        "429", "rate limit", "rate_limit", "too many requests",
        "500", "502", "503", "504", "server error", "overloaded",
        "timeout", "timed out", "connection", "temporarily",
        "401", "403", "unauthorized", "quota", "insufficient",
    )

    def __init__(
        self,
        primary: BaseProvider,
        fallbacks: list[BaseProvider] | None = None,
    ) -> None:
        self._providers: list[BaseProvider] = [primary, *(fallbacks or [])]
        self._last_provider: BaseProvider | None = None
        self._failover_count: int = 0

    @property
    def last_provider(self) -> BaseProvider | None:
        return self._last_provider

    @property
    def failover_count(self) -> int:
        return self._failover_count

    def _is_transient(self, error_text: str) -> bool:
        lowered = error_text.lower()
        return any(marker in lowered for marker in self._TRANSIENT_MARKERS)

    async def chat(
        self,
        messages: list[Any],
        **kwargs: Any,
    ) -> "ProviderResponse":
        """Chat with automatic failover across the chain."""
        last_error: Exception | None = None
        for provider in self._providers:
            try:
                response = await provider.chat(messages, **kwargs)
                self._last_provider = provider
                return response
            except Exception as exc:
                last_error = exc
                text = str(exc)
                if self._is_transient(text):
                    self._failover_count += 1
                    logger.warning(
                        "Provider %s failed (%s); failing over",
                        getattr(provider, "PROVIDER_NAME", provider.__class__.__name__),
                        text[:120],
                    )
                    continue
                # Non-transient error: raise immediately
                raise
        raise RuntimeError(
            f"All providers in chain failed. Last error: {last_error}"
        ) from last_error

    def __repr__(self) -> str:
        names = [
            getattr(p, "PROVIDER_NAME", p.__class__.__name__)
            for p in self._providers
        ]
        return f"ProviderChain({names})"
