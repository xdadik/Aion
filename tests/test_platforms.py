"""Tests for platform messaging adapters."""
import asyncio
import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from aion_core.messaging.platforms import (
        PlatformRegistry,
        PlatformType,
        create_platform,
        validate_platform_config,
    )
    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False

@unittest.skipUnless(HAS_MODULE, "platforms not available")
class TestPlatformAdapters(TestCase):
    def test_platform_type_count(self):
        self.assertTrue(len(PlatformType) >= 20)

    def test_platform_type_values(self):
        names = [p.name for p in PlatformType]
        for expected in ["TELEGRAM", "DISCORD", "SLACK", "WHATSAPP", "SIGNAL", "TEAMS", "EMAIL", "WEBHOOK"]:
            self.assertIn(expected, names)

    def test_create_telegram(self):
        adapter = create_platform(PlatformType.TELEGRAM, {"token": "123456:ABC-test-token-for-testing"})
        self.assertIsNotNone(adapter)
        self.assertEqual(adapter.get_platform_type(), PlatformType.TELEGRAM)

    def test_telegram_connect_send(self):
        adapter = create_platform(PlatformType.TELEGRAM, {"token": "123456:ABC-test-token-for-testing", "chat_id": "456"})
        asyncio.run(adapter.connect())
        self.assertTrue(adapter.is_connected())
        asyncio.run(adapter.send_text("session-1", "Hello!"))
        msgs = asyncio.run(adapter.get_messages("session-1"))
        self.assertTrue(len(msgs) >= 1)
        asyncio.run(adapter.disconnect())

    def test_registry_register_get(self):
        registry = PlatformRegistry()
        adapter = create_platform(PlatformType.TELEGRAM, {"token": "test-token"})
        registry.register_instance(PlatformType.TELEGRAM, adapter)
        retrieved = registry.get(PlatformType.TELEGRAM)
        self.assertIsNotNone(retrieved)

    def test_validate_config_missing(self):
        errors = validate_platform_config(PlatformType.TELEGRAM, {})
        self.assertTrue(len(errors) > 0)

if __name__ == "__main__":
    unittest.main()
