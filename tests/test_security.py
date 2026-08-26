"""Tests for aion_core.security.sandbox — CommandValidator and SecurityManager."""

import unittest

from aion_core.security.sandbox import CommandValidator, SecurityManager


class TestCommandValidatorDangerous(unittest.TestCase):
    """Dangerous commands are blocked by the default blacklist."""

    def setUp(self):
        self.validator = CommandValidator()

    def test_command_validator_blocks_dangerous(self):
        safe, reason = self.validator.validate("rm -rf /")
        self.assertFalse(safe)
        self.assertIn("blacklisted", reason)

    def test_command_validator_blocks_format(self):
        safe, _ = self.validator.validate("mkfs /dev/sda1")
        self.assertFalse(safe)


class TestCommandValidatorSafe(unittest.TestCase):
    """Safe commands pass validation."""

    def setUp(self):
        self.validator = CommandValidator()

    def test_command_validator_allows_safe(self):
        safe, reason = self.validator.validate("echo hello")
        self.assertTrue(safe)

    def test_command_validator_allows_ls(self):
        safe, _ = self.validator.validate("ls -la /tmp")
        self.assertTrue(safe)

    def test_empty_command_rejected(self):
        safe, _ = self.validator.validate("")
        self.assertFalse(safe)


class TestSecurityManagerCommandCheck(unittest.IsolatedAsyncioTestCase):
    """SecurityManager.check_command delegates to CommandValidator."""

    async def test_check_command_blocks_dangerous(self):
        sm = SecurityManager()
        safe, reason = await sm.check_command("rm -rf /")
        self.assertFalse(safe)

    async def test_check_command_allows_safe(self):
        sm = SecurityManager()
        safe, reason = await sm.check_command("echo hello")
        self.assertTrue(safe)


if __name__ == "__main__":
    unittest.main()
