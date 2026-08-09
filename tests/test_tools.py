"""Tests for aion_core.tools.registry — ToolRegistry and Tool."""

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from aion_core.tools.registry import Tool, ToolParameter, ToolRegistry


class TestToolSchemaFormat(unittest.TestCase):
    """Verify Tool.to_openai_schema produces valid OpenAI format."""

    def test_tool_schema_format(self):
        tool = Tool(
            name="web_search",
            description="Search the web for information.",
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="The search query",
                    required=True,
                ),
                ToolParameter(
                    name="num_results",
                    type="integer",
                    description="Number of results to return",
                    required=False,
                    default=5,
                ),
            ],
            handler=AsyncMock(),
        )

        schema = tool.to_openai_schema()

        # Top-level keys
        self.assertEqual(schema["type"], "function")
        self.assertIn("function", schema)

        func = schema["function"]
        self.assertEqual(func["name"], "web_search")
        self.assertEqual(func["description"], "Search the web for information.")

        # Parameters structure
        params = func["parameters"]
        self.assertEqual(params["type"], "object")
        self.assertIn("properties", params)
        self.assertIn("required", params)
        self.assertIn("query", params["required"])
        self.assertNotIn("num_results", params["required"])
        self.assertIn("query", params["properties"])
        self.assertIn("num_results", params["properties"])


class TestToolRegistryInit(unittest.IsolatedAsyncioTestCase):
    """ToolRegistry initializes and loads built-in tools."""

    async def test_registry_init(self):
        mock_config = SimpleNamespace(
            tools_dir=None,
            tool_approval_mode="auto",
        )
        registry = ToolRegistry(config=mock_config, approval_mode="auto")
        self.assertEqual(len(registry), 0)

        # Patch _build_builtin_tools to return empty list so we
        # don't depend on external dependencies during tests.
        with patch("aion_core.tools.registry._build_builtin_tools", return_value=[]):
            await registry.initialize()

        # After initialize with no builtins and no custom tools dir,
        # registry should still be empty (no tools_dir configured).
        self.assertIsInstance(registry.list_tools(), list)
        await registry.shutdown()


if __name__ == "__main__":
    unittest.main()
