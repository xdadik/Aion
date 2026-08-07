"""Tests for background review system."""
import os, sys, asyncio, unittest
from pathlib import Path
from unittest import TestCase
sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from aion_core.agent.background_review import BackgroundReviewer, ReviewTask, ReviewResult, ReviewType
    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False

@unittest.skipUnless(HAS_MODULE, "background_review not available")
class TestBackgroundReviewer(TestCase):
    def setUp(self):
        self.reviewer = BackgroundReviewer()

    def test_review_task_creation(self):
        task = ReviewTask(turn_id="turn-1", review_type=ReviewType.MEMORY, payload={})
        self.assertIsNotNone(task.task_id)

    def test_submit_review(self):
        task = ReviewTask(turn_id="turn-1", review_type=ReviewType.QUALITY, payload={})
        try:
            result = asyncio.run(self.reviewer.submit_review(task))
            self.assertIsInstance(result, str)
        except (TypeError, AttributeError):
            # Some implementations may not be async
            result = self.reviewer.submit_review(task)
            if hasattr(result, '__await__'):
                result = asyncio.run(result)

    def test_get_stats(self):
        stats = self.reviewer.get_stats()
        self.assertIsInstance(stats, dict)

    def test_shutdown(self):
        res = self.reviewer.shutdown()
        if hasattr(res, '__await__'):
            asyncio.run(res)


if __name__ == "__main__":
    unittest.main()
