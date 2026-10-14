"""Statistical checks for the QEX-inspired refined sweep."""
import unittest
import numpy as np
from refined_thresholds import analyze, conditions, interpolate_crossing, isotonic, MESSAGES


def row(snr, success, trials=200):
    return {"snr_2500_db":snr,"successes":success,"trials":trials}


class RefinedStatistics(unittest.TestCase):
    def test_weighted_pava(self):
        y=isotonic(np.array([0.,10.,3.,20.]),np.array([20.,20.,20.,20.]))
        self.assertTrue(np.all(np.diff(y)>=0))
        self.assertAlmostEqual(y[1],13/40)
        self.assertAlmostEqual(y[2],13/40)

    def test_interpolation(self):
        self.assertAlmostEqual(interpolate_crossing(
            np.array([-20.,-18.]),np.array([.25,.75])),-19.)

    def test_interval_and_threshold(self):
        rows=[row(-21,0),row(-20,18),row(-19,52),row(-18,150),
              row(-17,190),row(-16,200)]
        out=analyze(rows,20261015,bootstrap=250)
        self.assertEqual(out["status"],"estimated")
        self.assertGreater(out["p50_snr_2500_db"],-19)
        self.assertLess(out["p50_snr_2500_db"],-18)
        self.assertEqual(len(out["p50_model_interval_95_db"]),2)

    def test_floor_is_not_a_threshold(self):
        rows=[row(-30,0),row(-20,0),row(-10,20),row(0,44),row(20,50)]
        out=analyze(rows,31,bootstrap=150)
        self.assertEqual(out["status"],"no_P50_error_floor")
        self.assertIsNone(out["p50_snr_2500_db"])

    def test_message_ensemble_and_models(self):
        self.assertEqual(len(conditions("spread")),6)
        self.assertEqual(len(conditions("drift-low")),10)
        self.assertEqual(len(conditions("drift-high")),9)
        for mode,messages in MESSAGES.items():
            self.assertEqual(len(messages),3)
            self.assertEqual(len(set(messages)),3)


if __name__=="__main__":
    unittest.main()
