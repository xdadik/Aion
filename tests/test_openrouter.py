"""Tests for the OpenRouter provider + router integration.

OpenRouter aggregates 400+ models behind one API key using the
OpenAI-compatible chat-completions format. These tests pin the contract:
headers (attribution), payload building, response/stream parsing,
factory registration, env-var resolution, and live-catalog hydration
for the ModelRouter.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from aion_core.providers.factory import (
    BaseProvider,
    ChatMessage,
    OpenRouterProvider,
    ProviderFactory,
    ProviderResponse,
)
from aion_core.router.router import ModelRouter


# ── helpers ──────────────────────────────────────────────────────────────

def _make_provider(**extra: Any) -> OpenRouterProvider:
    return OpenRouterProvider(api_key="sk-or-test-123", **extra)


def _openai_style_response(**overrides: Any) -> dict[str, Any]:
    raw: dict[str, Any] = {
        "id": "gen-123",
        "model": "meta-llama/llama-4-scout",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "Hello!"},
                "finish_reason": "stop",
            }
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }
    raw.update(overrides)
    return raw


# ── provider construction ────────────────────────────────────────────────

class TestOpenRouterProviderConstruction:
    def test_requires_api_key(self) -> None:
        with pytest.raises(ValueError, match="api_key"):
            OpenRouterProvider()

    def test_default_model(self) -> None:
        provider = _make_provider()
        assert provider.get_default_model() == "openai/gpt-4o"

    def test_custom_default_model(self) -> None:
        provider = _make_provider(default_model="deepseek/deepseek-chat")
        assert provider.default_model == "deepseek/deepseek-chat"

    def test_provider_name(self) -> None:
        assert OpenRouterProvider.PROVIDER_NAME == "openrouter"

    def test_base_url(self) -> None:
        assert OpenRouterProvider.BASE_URL == "https://openrouter.ai/api/v1"

    def test_is_base_provider(self) -> None:
        assert isinstance(_make_provider(), BaseProvider)


class TestOpenRouterHeaders:
    def test_auth_bearer(self) -> None:
        headers = _make_provider()._build_headers()
        assert headers["Authorization"] == "Bearer sk-or-test-123"

    def test_content_type(self) -> None:
        assert _make_provider()._build_headers()["Content-Type"] == "application/json"

    def test_attribution_headers_default(self) -> None:
        headers = _make_provider()._build_headers()
        # OpenRouter asks apps to identify themselves (HTTP-Referer/X-Title)
        assert headers["HTTP-Referer"] == "https://aion-hand.dev"
        assert headers["X-Title"] == "Aion Hand"

    def test_attribution_headers_custom(self) -> None:
        provider = _make_provider(site_url="https://example.com", app_name="MyApp")
        headers = provider._build_headers()
        assert headers["HTTP-Referer"] == "https://example.com"
        assert headers["X-Title"] == "MyApp"


# ── payload building ─────────────────────────────────────────────────────

class TestOpenRouterPayload:
    def test_minimal_payload(self) -> None:
        provider = _make_provider(default_model="deepseek/deepseek-chat")
        normalized = provider._normalize_messages(
            [{"role": "user", "content": "hi"}]
        )
        payload = {
            "model": provider.default_model,
            "messages": [m.to_openai_dict() for m in normalized],
        }
        assert payload["model"] == "deepseek/deepseek-chat"
        assert payload["messages"] == [{"role": "user", "content": "hi"}]

    def test_normalize_accepts_chatmessage_objects(self) -> None:
        provider = _make_provider()
        normalized = provider._normalize_messages(
            [ChatMessage(role="user", content="hello")]
        )
        assert len(normalized) == 1
        assert normalized[0].role == "user"

    def test_normalize_rejects_string_messages(self) -> None:
        """Plain strings are not valid messages — must raise, not crash."""
        provider = _make_provider()
        with pytest.raises(TypeError):
            provider._normalize_messages(["just a string"])


# ── response parsing ─────────────────────────────────────────────────────

class TestOpenRouterParsing:
    def test_parse_basic_response(self) -> None:
        provider = _make_provider()
        parsed = provider._parse_openai_response(
            _openai_style_response(), "meta-llama/llama-4-scout"
        )
        assert isinstance(parsed, ProviderResponse)
        assert parsed.content == "Hello!"
        assert parsed.finish_reason == "stop"
        assert parsed.model == "meta-llama/llama-4-scout"

    def test_parse_usage(self) -> None:
        provider = _make_provider()
        parsed = provider._parse_openai_response(
            _openai_style_response(), "m"
        )
        assert parsed.usage.prompt_tokens == 10
        assert parsed.usage.completion_tokens == 5
        assert parsed.usage.total_tokens == 15

    def test_parse_tool_calls(self) -> None:
        provider = _make_provider()
        raw = _openai_style_response()
        raw["choices"][0]["message"] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {
                        "name": "calculator",
                        "arguments": '{"expression": "6*7"}',
                    },
                }
            ],
        }
        raw["choices"][0]["finish_reason"] = "tool_calls"
        parsed = provider._parse_openai_response(raw, "m")
        assert parsed.tool_calls is not None
        assert parsed.tool_calls[0]["function"]["name"] == "calculator"

    def test_parse_empty_choices(self) -> None:
        provider = _make_provider()
        parsed = provider._parse_openai_response(
            {"choices": [], "usage": {}}, "m"
        )
        assert parsed.content == ""
        assert parsed.usage.prompt_tokens == 0

    def test_parse_model_fallback(self) -> None:
        """Response 'model' field wins; requested model is the fallback."""
        provider = _make_provider()
        parsed = provider._parse_openai_response(
            _openai_style_response(model="openai/gpt-4o"), "requested-model"
        )
        assert parsed.model == "openai/gpt-4o"
        parsed2 = provider._parse_openai_response(
            _openai_style_response(), "requested-model"
        )
        # _openai_style_response sets model=meta-llama/... by default
        assert parsed2.model == "meta-llama/llama-4-scout"


# ── streaming ────────────────────────────────────────────────────────────

class TestOpenRouterStreaming:
    def test_stream_yields_content_deltas(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()

        async def fake_stream(url: str, headers: dict, payload: dict, timeout: float):
            yield {"choices": [{"delta": {"content": "Hel"}}]}
            yield {"choices": [{"delta": {"content": "lo!"}}]}
            yield {"choices": [{"delta": {}}]}  # no content
            yield {"choices": []}  # empty choices

        import aion_core.providers.factory as factory
        monkeypatch.setattr(factory, "_http_post_stream", fake_stream)

        chunks = asyncio.run(_collect(provider.chat_stream([{"role": "user", "content": "hi"}])))
        assert chunks == ["Hel", "lo!"]

    def test_stream_payload_includes_stream_flag(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = _make_provider()
        captured: dict[str, Any] = {}

        async def fake_stream(url: str, headers: dict, payload: dict, timeout: float):
            captured.update(payload)
            captured["url"] = url
            if False:  # pragma: no cover
                yield

        import aion_core.providers.factory as factory
        monkeypatch.setattr(factory, "_http_post_stream", fake_stream)

        asyncio.run(_collect(provider.chat_stream([{"role": "user", "content": "hi"}])))
        assert captured["stream"] is True
        assert captured["model"] == "openai/gpt-4o"
        assert "/chat/completions" in captured["url"]


async def _collect(agen: Any) -> list[str]:
    out = []
    async for chunk in agen:
        out.append(chunk)
    return out


# ── chat end-to-end with mocked HTTP ─────────────────────────────────────

class TestOpenRouterChat:
    def test_chat_posts_and_parses(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider(default_model="deepseek/deepseek-chat")
        captured: dict[str, Any] = {}

        async def fake_post(url: str, headers: dict, payload: dict, timeout: float):
            captured["url"] = url
            captured["headers"] = headers
            captured["payload"] = payload
            return _openai_style_response(model="deepseek/deepseek-chat")

        import aion_core.providers.factory as factory
        monkeypatch.setattr(factory, "_http_post_json", fake_post)

        response = asyncio.run(
            provider.chat([{"role": "user", "content": "hi"}], temperature=0.2)
        )
        assert isinstance(response, ProviderResponse)
        assert response.content == "Hello!"
        assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
        assert captured["payload"]["model"] == "deepseek/deepseek-chat"
        assert captured["payload"]["temperature"] == 0.2
        assert captured["headers"]["Authorization"] == "Bearer sk-or-test-123"

    def test_chat_passes_tools(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()
        captured: dict[str, Any] = {}

        async def fake_post(url: str, headers: dict, payload: dict, timeout: float):
            captured.update(payload)
            return _openai_style_response()

        import aion_core.providers.factory as factory
        monkeypatch.setattr(factory, "_http_post_json", fake_post)

        tools = [{
            "type": "function",
            "function": {
                "name": "calculator",
                "description": "Do math",
                "parameters": {"type": "object", "properties": {}},
            },
        }]
        asyncio.run(provider.chat([{"role": "user", "content": "hi"}], tools=tools))
        assert captured["tools"] == tools


# ── list_models ──────────────────────────────────────────────────────────

class TestOpenRouterListModels:
    def test_list_models_parses_ids(self, monkeypatch: pytest.MonkeyPatch) -> None:
        provider = _make_provider()

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps({
                    "data": [
                        {"id": "openai/gpt-4o"},
                        {"id": "anthropic/claude-sonnet-5"},
                        {"id": "meta-llama/llama-4-scout"},
                    ]
                }).encode()

        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, timeout: FakeResponse()
        )

        models = asyncio.run(provider.list_models())
        assert models == [
            "anthropic/claude-sonnet-5", "meta-llama/llama-4-scout", "openai/gpt-4o"
        ]

    def test_list_models_failure_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        provider = _make_provider()

        def boom(req, timeout):
            raise OSError("network down")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", boom)

        models = asyncio.run(provider.list_models())
        assert models == []


# ── factory + env resolution ─────────────────────────────────────────────

class TestOpenRouterFactory:
    def test_registry_contains_openrouter(self) -> None:
        provider = ProviderFactory.create(
            "openrouter",
            config={"api_key": "sk-or-x", "default_model": "deepseek/deepseek-chat"},
        )
        assert isinstance(provider, OpenRouterProvider)

    def test_env_var_resolution(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-from-env")
        provider = ProviderFactory.from_env("openrouter")
        assert isinstance(provider, OpenRouterProvider)
        assert provider.api_key == "sk-or-from-env"

    def test_unknown_provider_lists_openrouter(self) -> None:
        with pytest.raises(ValueError, match="openrouter"):
            ProviderFactory.create("nonexistent-provider")

    def test_extra_config_passthrough(self) -> None:
        provider = ProviderFactory.create(
            "openrouter",
            config={
                "api_key": "sk-or-x",
                "site_url": "https://test.dev",
            },
        )
        assert provider._build_headers()["HTTP-Referer"] == "https://test.dev"


# ── router integration ───────────────────────────────────────────────────

class TestRouterOpenRouterProfiles:
    def test_default_profiles_include_openrouter(self) -> None:
        router = ModelRouter()
        or_models = [m for m in router.list_models() if m["provider"] == "openrouter"]
        assert len(or_models) >= 9
        names = {m["name"] for m in or_models}
        assert "meta-llama/llama-4-scout" in names
        assert "deepseek/deepseek-chat" in names
        assert "anthropic/claude-sonnet-5" in names

    def test_openrouter_models_are_cheapest_in_budget(self) -> None:
        """OpenRouter budget models should win cost-based selection."""
        router = ModelRouter()
        decision = router.route(
            "hello", force_tier="budget", preferred_provider="openrouter"
        )
        assert decision.provider == "openrouter"
        assert "/" in decision.model  # OpenRouter IDs are vendor-prefixed

    def test_openrouter_models_in_every_tier(self) -> None:
        router = ModelRouter()
        for tier in ("budget", "standard", "premium"):
            names = [
                m["name"] for m in router.list_models()
                if m["provider"] == "openrouter" and m["tier"] == tier
            ]
            assert names, f"no openrouter models in tier {tier}"


class TestRouterHydration:
    def _catalog(self) -> dict[str, Any]:
        return {
            "data": [
                {
                    "id": "deepseek/deepseek-r2",
                    "context_length": 163840,
                    "pricing": {"prompt": "1.4e-06", "completion": "5.6e-06"},
                    "supported_parameters": ["tools", "response_format"],
                    "architecture": {"input_modalities": ["text"]},
                    "reasoning": False,
                },
                {
                    "id": "openai/gpt-9-nova",
                    "context_length": 400000,
                    "pricing": {"prompt": "1e-05", "completion": "4e-05"},
                    "supported_parameters": ["tools"],
                    "architecture": {"input_modalities": ["text", "image"]},
                    "reasoning": True,
                },
                {
                    "id": "qwen/qwen-free:free",
                    "context_length": 32000,
                    "pricing": {"prompt": "0", "completion": "0"},
                    "supported_parameters": [],
                    "architecture": {"input_modalities": ["text"]},
                    "reasoning": False,
                },
                {
                    # batch variant -> must be skipped
                    "id": "openai/gpt-9-nova:batch",
                    "context_length": 400000,
                    "pricing": {"prompt": "5e-06", "completion": "2e-05"},
                },
                {
                    # non-curated vendor -> skipped
                    "id": "some-vendor/obscure-model",
                    "context_length": 8000,
                    "pricing": {"prompt": "1e-07", "completion": "2e-07"},
                },
            ]
        }

    def test_hydration_adds_models(self, monkeypatch: pytest.MonkeyPatch) -> None:
        router = ModelRouter()
        catalog = self._catalog()

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps(catalog).encode()

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, timeout: FakeResponse()
        )

        added = router.hydrate_from_openrouter()
        assert added == 3  # r2, nova, free — batch + obscure skipped
        names = {m["name"] for m in router.list_models()}
        assert "deepseek/deepseek-r2" in names
        assert "openai/gpt-9-nova" in names
        assert "qwen/qwen-free:free" in names
        assert "openai/gpt-9-nova:batch" not in names

    def test_hydration_tiering_and_pricing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        router = ModelRouter()
        catalog = self._catalog()

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps(catalog).encode()

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, timeout: FakeResponse()
        )

        router.hydrate_from_openrouter()
        models = {m["name"]: m for m in router.list_models()}
        # deepseek-r2: 5.6e-06/token -> 0.0056/1k output -> standard
        assert models["deepseek/deepseek-r2"]["tier"] == "standard"
        assert models["deepseek/deepseek-r2"]["cost_per_1k_input"] == 0.0014
        # gpt-9-nova: 4e-05 -> 0.04/1k out -> premium; vision + thinking caps
        assert models["openai/gpt-9-nova"]["tier"] == "premium"
        assert "vision" in models["openai/gpt-9-nova"]["capabilities"]
        assert "extended_thinking" in models["openai/gpt-9-nova"]["capabilities"]
        assert "function_calling" in models["openai/gpt-9-nova"]["capabilities"]
        # free variant -> budget, zero cost
        assert models["qwen/qwen-free:free"]["tier"] == "budget"
        assert models["qwen/qwen-free:free"]["cost_per_1k_input"] == 0.0

    def test_hydration_offline_returns_zero(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        router = ModelRouter()

        def boom(req, timeout):
            raise OSError("offline")

        import urllib.request
        monkeypatch.setattr(urllib.request, "urlopen", boom)

        before = len(router.list_models())
        added = router.hydrate_from_openrouter()
        assert added == 0
        assert len(router.list_models()) == before

    def test_hydration_respects_max_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        router = ModelRouter()
        catalog = self._catalog()

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps(catalog).encode()

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, timeout: FakeResponse()
        )

        added = router.hydrate_from_openrouter(max_models=1)
        assert added == 1

    def test_hydration_replaces_existing_not_duplicates(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hydrating twice must not duplicate profiles."""
        router = ModelRouter()
        catalog = self._catalog()

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps(catalog).encode()

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, timeout: FakeResponse()
        )

        router.hydrate_from_openrouter()
        first = len(router.list_models())
        added_again = router.hydrate_from_openrouter()
        assert added_again == 0
        assert len(router.list_models()) == first

    def test_hydration_skips_negative_pricing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """OpenRouter reports negative prices for unsupported modalities."""
        router = ModelRouter()
        catalog = {
            "data": [
                {
                    "id": "x-ai/grok-broken",
                    "context_length": 8000,
                    "pricing": {"prompt": "-1", "completion": "-1"},
                }
            ]
        }

        class FakeResponse:
            def read(self) -> bytes:
                return json.dumps(catalog).encode()

            def __enter__(self) -> "FakeResponse":
                return self

            def __exit__(self, *args: Any) -> None:
                pass

        import urllib.request
        monkeypatch.setattr(
            urllib.request, "urlopen", lambda req, timeout: FakeResponse()
        )

        assert router.hydrate_from_openrouter() == 0
