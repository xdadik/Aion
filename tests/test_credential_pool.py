"""Tests for credential pool system."""

import os
import sys
import tempfile
import unittest
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from aion_core.agent.credential_pool import (
        CredentialPool,
        CredentialSource,
        PooledCredential,
        RotationStrategy,
    )

    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False


@unittest.skipUnless(HAS_MODULE, "credential_pool not available")
class TestCredentialPool(TestCase):
    def setUp(self):
        self.pool = CredentialPool()

    def _make_cred(self, provider="openai", key="sk-test", expired=False):
        if expired:
            expires = datetime.now(UTC) - timedelta(hours=1)
        else:
            expires = datetime.now(UTC) + timedelta(hours=1)
        return PooledCredential(
            id=str(uuid.uuid4())[:8],
            provider=provider,
            api_key=key,
            source=CredentialSource.CUSTOM,
            expires_at=expires,
        )

    def test_add_and_get_all(self):
        self.pool.add_credential(self._make_cred("openai", "sk-1"))
        creds = self.pool.get_all("openai")
        self.assertTrue(len(creds) >= 1)

    def test_rotate_round_robin(self):
        self.pool.add_credential(self._make_cred("openai", "sk-1"))
        self.pool.add_credential(self._make_cred("openai", "sk-2"))
        first = self.pool.rotate("openai", strategy=RotationStrategy.ROUND_ROBIN)
        self.assertIsNotNone(first)

    def test_mark_exhausted(self):
        self.pool.add_credential(self._make_cred("openai", "sk-exh"))
        cred = self.pool.rotate("openai")
        self.assertIsNotNone(cred)
        result = self.pool.mark_exhausted(cred.id)
        self.assertTrue(result)

    def test_mark_rate_limited(self):
        self.pool.add_credential(self._make_cred("openai", "sk-lim"))
        cred = self.pool.rotate("openai")
        self.assertIsNotNone(cred)
        result = self.pool.mark_rate_limited(cred.id, cooldown=60)
        self.assertTrue(result)

    def test_cleanup_expired(self):
        self.pool.add_credential(self._make_cred("openai", "sk-expired", expired=True))
        self.pool.add_credential(self._make_cred("openai", "sk-valid", expired=False))
        removed = self.pool.cleanup_expired()
        self.assertTrue(removed >= 1)

    def test_save_and_load(self):
        self.pool.add_credential(self._make_cred("anthropic", "sk-ant-123"))
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            path = f.name
        try:
            self.pool.save_to_file(path)
            new_pool = CredentialPool()
            loaded = new_pool.load_from_file(path)
            self.assertTrue(loaded >= 1)
        finally:
            os.unlink(path)

    def test_get_stats(self):
        self.pool.add_credential(self._make_cred("openai", "sk-1"))
        stats = self.pool.get_stats()
        self.assertIsInstance(stats, dict)


if __name__ == "__main__":
    unittest.main()
