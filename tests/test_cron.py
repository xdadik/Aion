"""Tests for aion_core.cron.scheduler — CronScheduler and parsing."""

import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from aion_core.cron.scheduler import parse_cron_expression, CronScheduler


class TestCronParsing(unittest.TestCase):
    """Cron expression parsing produces correct allowed-value sets."""

    def test_parse_simple_cron(self):
        fields = parse_cron_expression("0 * * * *")
        self.assertEqual(len(fields), 5)
        # minute 0 only
        self.assertEqual(fields[0], {0})
        # hour: all 0-23
        self.assertEqual(fields[1], set(range(24)))
        # day of month: all 1-31
        self.assertEqual(fields[2], set(range(1, 32)))
        # month: all 1-12
        self.assertEqual(fields[3], set(range(1, 13)))
        # day of week: all 0-6
        self.assertEqual(fields[4], set(range(7)))

    def test_parse_invalid_cron(self):
        with self.assertRaises(ValueError):
            parse_cron_expression("0 0 0")


class TestCronSchedulerTasks(unittest.IsolatedAsyncioTestCase):
    """Add and list tasks without starting the tick loop."""

    async def test_add_and_list_tasks(self):
        mock_agent = AsyncMock()
        scheduler = CronScheduler(agent=mock_agent)

        task_id = await scheduler.add_task(
            task="Check the weather",
            schedule="0 9 * * *",
        )

        self.assertIsInstance(task_id, str)
        self.assertGreater(len(task_id), 0)

        tasks = await scheduler.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0].task, "Check the weather")
        self.assertEqual(tasks[0].schedule, "0 9 * * *")
        self.assertTrue(tasks[0].enabled)
        self.assertIsNotNone(tasks[0].next_run)

        # Cleanup (no shutdown needed since tick loop was never started)


if __name__ == "__main__":
    unittest.main()
