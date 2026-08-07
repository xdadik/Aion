import pytest

from aion_core.providers.factory import BaseProvider, ProviderResponse, UsageInfo
from aion_core.providers.router import ProviderRoute, ProviderRouter


class FakeProvider(BaseProvider):
    PROVIDER_NAME = "fake"

    def get_default_model(self):
        return "fake-model"

    async def chat(self, messages, model=None, temperature=None, max_tokens=None, tools=None, **kwargs):
        return ProviderResponse(content="ok", model=model or self.default_model, usage=UsageInfo())

    async def chat_stream(self, messages, model=None, temperature=None, max_tokens=None, tools=None, **kwargs):
        yield "ok"

    async def list_models(self):
        return [self.default_model]


def test_router_requires_routes():
    with pytest.raises(ValueError):
        ProviderRouter([])


def test_router_config_normalizes_routes():
    router = ProviderRouter.from_config([
        {"provider": "fake", "model": "test", "config": {"api_key": "x"}},
    ])
    assert router.routes[0].name == "fake"
    assert router.routes[0].model == "test"


@pytest.mark.asyncio
async def test_router_health_does_not_expose_credentials():
    from aion_core.providers.factory import ProviderFactory

    ProviderFactory.register_provider("fake", FakeProvider)
    router = ProviderRouter([
        ProviderRoute("fake", {"api_key": "super-secret"}, "fake-model"),
    ])
    health = await router.health()
    assert health["fake"]["ready"] is True
    assert "super-secret" not in str(health)


@pytest.mark.asyncio
async def test_router_chat_uses_registered_provider():
    from aion_core.providers.factory import ProviderFactory

    ProviderFactory.register_provider("fake", FakeProvider)
    router = ProviderRouter([ProviderRoute("fake")])
    result = await router.chat([{"role": "user", "content": "hello"}])
    assert result.response.content == "ok"
    assert result.provider == "fake"
    assert result.attempts == 1
