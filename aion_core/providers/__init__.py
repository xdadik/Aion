"""Aion Hand Provider Factory System.

Provides provider-agnostic LLM access through a unified interface.
Supports OpenAI, Anthropic, Google, OpenRouter, Ollama, and custom
OpenAI-compatible endpoints.

Quick start::

    from aion_core.providers import ProviderFactory, ChatMessage

    provider = ProviderFactory.create(
        provider_name="openai",
        config={"api_key": "sk-..."},
    )
    response = await provider.chat([
        ChatMessage(role="user", content="Hello!"),
    ])
    print(response.content)
"""

from aion_core.providers.factory import (
    AnthropicProvider,
    BaseProvider,
    ChatMessage,
    CustomProvider,
    GoogleProvider,
    OllamaProvider,
    OpenAIProvider,
    OpenRouterProvider,
    ProviderFactory,
    ProviderResponse,
    UsageInfo,
)

__all__ = [
    # Data models
    "ChatMessage",
    "UsageInfo",
    "ProviderResponse",
    # Abstract base
    "BaseProvider",
    # Concrete providers
    "OpenAIProvider",
    "AnthropicProvider",
    "GoogleProvider",
    "OpenRouterProvider",
    "OllamaProvider",
    "CustomProvider",
    # Factory
    "ProviderFactory",
]
