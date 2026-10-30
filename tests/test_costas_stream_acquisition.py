"""Checks for the finite Costas acquisition experiment and its scoring rule."""
import math
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import costas_stream_acquisition as study


def phase_codes(values):
    return np.rint(np.asarray(values) / (2 * math.pi) * 2**32).astype(np.int64)


class CostasStreamAcquisition(unittest.TestCase):
    def test_clean_acquisition_and_zero_gain_control(self):
        active = study.run_case(.6, .012, None, 0)
        off = study.run_case(.6, .012, None, 0, gains=(0., 0.))
        self.assertIsNotNone(active['acquired_window'])
        self.assertTrue(active['last_two_windows_good'])
        self.assertEqual(active['quadrant_changes'], [])
        self.assertIsNone(off['acquired_window'])
        self.assertFalse(off['last_two_windows_good'])

    def test_measure_detects_quadrant_change_through_bad_window(self):
        window = 128
        # A ramp is neither in lock nor a discontinuity; it connects two stable branches.
        error = np.r_[np.zeros(2 * window), np.linspace(0, math.pi / 2, window),
                      np.full(2 * window, math.pi / 2)]
        result = study.measure(phase_codes(-error), np.zeros(len(error)), window)
        self.assertEqual(result['acquired_window'], 0)
        self.assertEqual(result['bad_windows_after_acquisition'], 1)
        self.assertEqual(result['quadrant_changes'], [{'from_window': 1, 'to_window': 3,
                                                       'quadrant_delta': 1, 'intervening_bad_windows': 1}])

    def test_seeded_signal_is_reproducible_and_awgn_definition(self):
        data, carrier, clipped = study.signal(.1, .002, 12., 5, 4096)
        repeat_data, repeat_carrier, repeat_clipped = study.signal(.1, .002, 12., 5, 4096)
        self.assertEqual((data, carrier.tolist(), clipped),
                         (repeat_data, repeat_carrier.tolist(), repeat_clipped))
        clean, _, _ = study.signal(.1, .002, None, 5, 4096)
        noise = (np.asarray(data) - np.asarray(clean)) / 32768
        self.assertLess(abs(float(np.mean(np.sum(noise * noise, axis=1))) - 10**(-1.2)), .004)

    def test_invalid_measurement_inputs(self):
        with self.assertRaises(ValueError):
            study.measure([0] * 256, [0] * 255)
        with self.assertRaises(ValueError):
            study.measure([0] * 100, [0] * 100)


if __name__ == '__main__':
    unittest.main()
