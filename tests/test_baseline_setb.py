"""Test for run_baseline_and_setb_score."""

import unittest
from ctx import metrics


class TestRunBaselineAndSetBScore(unittest.TestCase):
    def test_run_baseline_and_setb_score(self):
        score = metrics.run_baseline_and_setb_score()
        self.assertIsInstance(score, float)
        self.assertGreater(score, 0.0)
