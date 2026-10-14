"""Fast deterministic validation of P50 analysis and Doppler waveform injection."""
import tempfile
import unittest
from pathlib import Path

import numpy as np
from scipy.io import wavfile
from scipy.signal import hilbert

from run_thresholds import chirp_wav, p50, stable_seed, wilson


class TestBench(unittest.TestCase):
    def test_seed(self):
        self.assertEqual(stable_seed("jtty", 3), stable_seed("jtty", 3))
        self.assertNotEqual(stable_seed("jtty", 3), stable_seed("ft4", 3))

    def test_wilson(self):
        self.assertLess(wilson(25, 50)[0], 0.5)
        self.assertGreater(wilson(25, 50)[1], 0.5)

    def test_threshold(self):
        rows = [{"snr_2500_db": x, "successes": y, "trials": 20}
                for x, y in [(-12, 0), (-10, 5), (-8, 15), (-6, 20)]]
        est = p50(rows, -12, -6)
        self.assertEqual(est["status"], "interpolated")
        self.assertAlmostEqual(est["p50_snr_2500_db"], -9, places=2)

    def test_censoring(self):
        rows = [{"snr_2500_db": x, "successes": 0, "trials": 20}
                for x in [-20., 10.]]
        self.assertEqual(p50(rows, -20., 10.)["status"],
                         "above_range_or_floor")

    def test_chirp_positive_drift(self):
        fs = 12000
        n = fs * 3
        t = np.arange(n) / fs
        pcm = np.rint(2000 * np.cos(2 * np.pi * 1500 * t)).astype(np.int16)
        with tempfile.TemporaryDirectory() as directory:
            wav = Path(directory) / "test.wav"
            wavfile.write(wav, fs, pcm)
            chirp_wav(wav, 8., 1.5)
            rate, shifted = wavfile.read(wav)
            self.assertEqual(rate, fs)
            phase = np.unwrap(np.angle(hilbert(shifted.astype(np.float64))))
            f = np.diff(phase) * fs / (2*np.pi)
            early = np.median(f[int(.5*fs):int(.7*fs)])
            late = np.median(f[int(2.3*fs):int(2.5*fs)])
            self.assertAlmostEqual(late-early, 8*(2.4-.6), delta=1.0)


if __name__ == "__main__":
    unittest.main()
