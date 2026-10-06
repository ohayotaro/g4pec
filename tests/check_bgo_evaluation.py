"""Check evaluation ROI accounting/ambiguity, independently of detector outcomes."""
from pathlib import Path
import sys
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'studies'))
from bgo_response import accumulate_roi, select_candidates, summary, wilson


class EvaluationTests(unittest.TestCase):
    def test_partial_bins_and_separate_events(self):
        charges = [0., 0.]
        accumulate_roi(charges, 1006.5, 1007.5, 2, 1)
        accumulate_roi(charges, 4006.5, 4007.5, 2, 1)
        accumulate_roi(charges, 5000, 6000, 99, 1)
        accumulate_roi(charges, 11006.5, 11007.5, 4, 1)
        self.assertEqual(charges, [2., 2.])

    def test_preexisting_gate_and_half_open_selection(self):
        source = 1007
        rows = [dict(time_ns=900,gate_end_ns=1500), dict(time_ns=1006,gate_end_ns=1200),
                dict(time_ns=4007,gate_end_ns=4100), dict(time_ns=800,gate_end_ns=1007)]
        selected, preceding = select_candidates(rows, source)
        self.assertEqual(selected, [rows[1]])
        self.assertEqual(preceding, [rows[0]])

    def test_empty_timing_and_finite_sample_occupancy(self):
        self.assertIsNone(summary([])['mean'])
        self.assertEqual(summary([1,3])['mean'], 2)
        interval = wilson(32,32)['wilson95']
        self.assertLess(interval[0], 1)
        self.assertAlmostEqual(interval[1], 1)


if __name__ == '__main__':
    unittest.main()
