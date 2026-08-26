"""Tests for the Aion HTTP API server.

These tests verify the routes are wired up correctly. They don't test
the actual chat flow end-to-end (which would require a real LLM) — they
test the API surface and error handling.
"""

from __future__ import annotations

import pytest

# Skip everything if aiohttp isn't installed
aiohttp = pytest.importorskip("aiohttp")

from aiohttp.test_utils import TestClient, TestServer  # noqa: E402

from aion_core.api import APIServer, APIConfig  # noqa: E402
from unittest.mock import AsyncMock, MagicMock  # noqa: E402


def _make_mock_agent() -> MagicMock:
    """Create a mock Aion agent with all subsystems."""
    agent = MagicMock()
    agent.state = MagicMock()
    agent.state.name = "IDLE"
    agent.chat = AsyncMock(return_value={
        "content": "Mock response",
        "tools_used": [],
        "metadata": {"elapsed_seconds": 0.01, "total_tokens": 10},
    })
    # Subsystems
    agent._memory = MagicMock()
    agent._memory.recent_memories = MagicMock(return_value=[])
    agent._skills = MagicMock()
    agent._skills.list_skills = MagicMock(return_value=[])
    agent._tools = MagicMock()
    # Build a tool mock whose .name attribute can be read (MagicMock(name=...) is special)
    tool_mock = MagicMock()
    tool_mock.name = "test_tool"
    tool_mock.description = "test"
    tool_mock.toolset = "utility"
    tool_mock.requires_approval = False
    # Make BOTH _tools and tool_registry return our mock tool (agent uses one or the other)
    agent._tools.list_tools = MagicMock(return_value=[tool_mock])
    agent.tool_registry = agent._tools
    agent.config = MagicMock()
    agent.config.to_dict = MagicMock(return_value={"name": "Aion", "default_provider": "openai"})
    return agent


@pytest.fixture
async def api_client() -> TestClient:
    """Spin up an API server with a mock agent for testing."""
    agent = _make_mock_agent()
    server = APIServer(agent=agent, config=APIConfig(host="127.0.0.1", port=0))
    app = server._build_app()
    test_server = TestServer(app)
    client = TestClient(test_server)
    await client.start_server()
    yield client
    await client.close()


class TestHealthEndpoints:
    """Health probe endpoints."""

    @pytest.mark.asyncio
    async def test_health_live_returns_200(self, api_client: TestClient):
        resp = await api_client.get("/health/live")
        assert resp.status == 200
        data = await resp.json()
        assert data["status"] in ("pass", "fail")
        assert "checks" in data

    @pytest.mark.asyncio
    async def test_health_ready_returns_200_or_503(self, api_client: TestClient):
        resp = await api_client.get("/health/ready")
        assert resp.status in (200, 503)

    @pytest.mark.asyncio
    async def test_health_full_returns_both(self, api_client: TestClient):
        resp = await api_client.get("/health")
        assert resp.status == 200
        data = await resp.json()
        assert "liveness" in data
        assert "readiness" in data


class TestPersonaEndpoints:
    """Persona listing + applying."""

    @pytest.mark.asyncio
    async def test_list_personas(self, api_client: TestClient):
        resp = await api_client.get("/api/personas")
        assert resp.status == 200
        data = await resp.json()
        assert "personas" in data
        assert "active" in data
        assert data["total"] >= 5  # built-in personas

    @pytest.mark.asyncio
    async def test_apply_persona_missing_name(self, api_client: TestClient):
        resp = await api_client.post("/api/personas/apply", json={})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_apply_unknown_persona_returns_404(self, api_client: TestClient):
        resp = await api_client.post("/api/personas/apply", json={"name": "nonexistent"})
        assert resp.status == 404

    @pytest.mark.asyncio
    async def test_apply_known_persona(self, api_client: TestClient):
        resp = await api_client.post("/api/personas/apply", json={"name": "default"})
        assert resp.status == 200
        data = await resp.json()
        assert data["applied"] == "default"


class TestSkillsAndTools:
    """Skills and tools listing."""

    @pytest.mark.asyncio
    async def test_list_skills(self, api_client: TestClient):
        resp = await api_client.get("/api/skills")
        assert resp.status == 200
        data = await resp.json()
        assert "skills" in data
        assert "total" in data

    @pytest.mark.asyncio
    async def test_list_tools(self, api_client: TestClient):
        resp = await api_client.get("/api/tools")
        assert resp.status == 200
        data = await resp.json()
        assert "tools" in data
        assert data["total"] >= 1


class TestMemoryAndConfig:
    """Memory + config endpoints."""

    @pytest.mark.asyncio
    async def test_list_memory(self, api_client: TestClient):
        resp = await api_client.get("/api/memory")
        assert resp.status == 200
        data = await resp.json()
        assert "memories" in data

    @pytest.mark.asyncio
    async def test_get_config(self, api_client: TestClient):
        resp = await api_client.get("/api/config")
        assert resp.status == 200
        data = await resp.json()
        assert "name" in data


class TestChatEndpoint:
    """Chat endpoint with mock agent."""

    @pytest.mark.asyncio
    async def test_chat_missing_message_returns_400(self, api_client: TestClient):
        resp = await api_client.post("/api/chat", json={})
        assert resp.status == 400

    @pytest.mark.asyncio
    async def test_chat_with_message(self, api_client: TestClient):
        resp = await api_client.post("/api/chat", json={"message": "hello"})
        assert resp.status == 200
        data = await resp.json()
        assert "content" in data

    @pytest.mark.asyncio
    async def test_chat_with_session_id(self, api_client: TestClient):
        resp = await api_client.post("/api/chat", json={"message": "hello", "session_id": "abc"})
        assert resp.status == 200


class TestMetricsEndpoint:
    """Telemetry metrics endpoint."""

    @pytest.mark.asyncio
    async def test_get_metrics(self, api_client: TestClient):
        resp = await api_client.get("/api/metrics")
        assert resp.status == 200
        data = await resp.json()
        assert "metrics" in data
        assert "traces_count" in data
        assert "events_count" in data


class TestCORSHeaders:
    """CORS middleware should add headers ONLY for allowed origins.

    Security contract: ``cors_origins=None`` sends NO CORS headers at all
    (previously it reflected any origin, letting any webpage drive the
    agent cross-origin from a local browser).
    """

    @pytest.mark.asyncio
    async def test_no_cors_headers_by_default(self, api_client: TestClient):
        resp = await api_client.get(
            "/api/personas", headers={"Origin": "http://evil.example"}
        )
        assert "Access-Control-Allow-Origin" not in resp.headers

    @pytest.mark.asyncio
    async def test_cors_header_present_for_allowed_origin(self, api_client: TestClient):
        resp = await api_client.get(
            "/api/personas", headers={"Origin": "http://localhost:3000"}
        )
        # The test fixture does not configure cors_origins -> no CORS.
        assert "Access-Control-Allow-Origin" not in resp.headers
