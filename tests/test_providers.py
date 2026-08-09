"""Tests for aion_core.providers.factory — ProviderFactory and ChatMessage."""

import unittest

from aion_core.providers.factory import ChatMessage, ProviderFactory


class TestChatMessage(unittest.TestCase):
    """ChatMessage dataclass works correctly."""

    def test_chat_message_creation(self):
        msg = ChatMessage(role="user", content="Hello, world!")
        self.assertEqual(msg.role, "user")
        self.assertEqual(msg.content, "Hello, world!")
        self.assertIsNone(msg.name)
        self.assertIsNone(msg.tool_calls)
        self.assertIsNone(msg.tool_call_id)

    def test_chat_message_to_openai_dict(self):
        msg = ChatMessage(
            role="assistant",
            content="Hi there!",
            name="bot",
            tool_calls=[{"id": "tc1", "type": "function"}],
        )
        d = msg.to_openai_dict()
        self.assertEqual(d["role"], "assistant")
        self.assertEqual(d["content"], "Hi there!")
        self.assertEqual(d["name"], "bot")
        self.assertIn("tool_calls", d)

    def test_chat_message_from_dict(self):
        d = {"role": "system", "content": "You are helpful."}
        msg = ChatMessage.from_dict(d)
        self.assertEqual(msg.role, "system")
        self.assertEqual(msg.content, "You are helpful.")


class TestProviderFactory(unittest.TestCase):
    """ProviderFactory registration and listing."""

    def test_factory_registration(self):
        """Register a mock provider and verify it appears in list."""
        from aion_core.providers.factory import BaseProvider

        class MockProvider(BaseProvider):
            PROVIDER_NAME = "mock_test_provider"

            async def chat(self, messages, **kwargs):
                from aion_core.providers.factory import ProviderResponse

                return ProviderResponse(content="ok")

        ProviderFactory.register_provider("mock_test", MockProvider)

        try:
            self.assertTrue(ProviderFactory.is_registered("mock_test"))
            self.assertIn("mock_test", ProviderFactory.list_providers())
        finally:
            from aion_core.providers import factory as f

            f._PROVIDER_REGISTRY.pop("mock_test", None)


if __name__ == "__main__":
    unittest.main()
