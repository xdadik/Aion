"""Tests for error classification system."""
import sys
import unittest
from pathlib import Path
from unittest import TestCase

sys.path.insert(0, str(Path(__file__).parent.parent))
try:
    from aion_core.agent.error_classifier import (
        ClassifiedError,
        ErrorBudget,
        ErrorRecoveryStrategy,
        ErrorTracker,
        FailoverReason,
        classify_error,
        get_recovery_strategy,
    )
    HAS_MODULE = True
except ImportError:
    HAS_MODULE = False

@unittest.skipUnless(HAS_MODULE, "error_classifier not available")
class TestErrorClassifier(TestCase):
    def test_classify_timeout(self):
        err = classify_error(TimeoutError("request timed out"))
        self.assertIsNotNone(err)
        self.assertIsInstance(err.reason, FailoverReason)

    def test_classify_connection_error(self):
        err = classify_error(ConnectionError("connection refused"))
        self.assertIsNotNone(err)

    def test_all_reasons_have_recovery(self):
        for reason in FailoverReason:
            strategy = get_recovery_strategy(reason)
            self.assertIsInstance(strategy, ErrorRecoveryStrategy)

    def test_error_tracker_record(self):
        tracker = ErrorTracker()
        err = ClassifiedError(reason=FailoverReason.TIMEOUT, message="test", retryable=True)
        tracker.record(err)
        counts = tracker.get_error_counts()
        self.assertTrue(len(counts) > 0)

    def test_error_budget_check(self):
        budget = ErrorBudget(default_budget=5)
        self.assertTrue(budget.check("test_provider"))

    def test_error_budget_consume(self):
        budget = ErrorBudget(default_budget=2)
        budget.consume("test_provider")
        budget.consume("test_provider")
        self.assertFalse(budget.check("test_provider"))

if __name__ == "__main__":
    unittest.main()
