"""End-to-end full Gardner precision evidence and negative controls."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
import timing_precision as precision


class TestTimingPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records = precision.report()

    def test_full_independent_trajectories_and_disabled_control(self):
        precision.check_acceptance(self.records)
        for record in self.records:
            self.assertEqual(record['input_clamps']['total_clamps'], 0)
            self.assertEqual(record['disabled_gains'], [0, 0])
            self.assertEqual(record['disabled']['position_max_discrepancy_samples'], 0)
            if record['requested_snr_db'] is None:
                self.assertGreater(record['enabled']['output_sqnr_db'], 70)
                self.assertGreater(record['enabled']['position_rms_discrepancy_samples'], 1e-5)
                for implementation in ('fixed', 'floating'):
                    self.assertEqual(record['enabled'][implementation]['symbol_errors'], 0)
                    self.assertLess(record['enabled'][implementation]['symbol_rms_error'],
                                    .2 * record['disabled'][implementation]['symbol_rms_error'])

    def test_loop_interface_uses_quantized_input_and_no_labels(self):
        # Capture the independent reference call; it receives the quantized samples, not truth
        # labels or the fixed loop's positions. Then its independently returned history is used.
        wave = np.exp(1j * np.arange(8000) * .013)
        rows, quantized, _ = precision.quantize(wave)
        reference = np.r_[np.full(precision.COUNT, .2 + .3j),
                          precision.POSITION + precision.SPS * np.arange(precision.COUNT) + .1]
        with patch.object(precision, 'floating_run', return_value=reference) as floating:
            fixed, positions, output, history = precision.run_loops(rows, quantized, (0, 0))
        operation, parameters, passed_input = floating.call_args.args
        self.assertEqual(operation, 'timing')
        self.assertEqual(parameters, [8, precision.COUNT, 32, 0, 0])
        np.testing.assert_array_equal(passed_input, quantized)
        np.testing.assert_array_equal(history, reference[precision.COUNT:].real)
        self.assertTrue(np.all(abs(history - positions - .1) < 1e-9))

    def test_ser_uses_declared_constellation_without_truth_compensation(self):
        constellation = np.asarray([1+1j, 1-1j, -1+1j, -1-1j])
        labels = np.arange(4)
        rotated = constellation[labels] * 1j
        metrics = precision.score_outputs(rotated, labels, constellation)
        self.assertEqual(metrics['symbol_errors'], 4)
        self.assertEqual(metrics['ser'], 1)
        self.assertGreater(metrics['symbol_rms_error'], 1)

    def test_awgn_energy_and_input_clamps_are_observed(self):
        noisy = [r for r in self.records if r['requested_snr_db'] is not None]
        self.assertEqual(len(noisy), 3)
        for record in noisy:
            measured = 10 * np.log10(record['signal_energy'] / record['complex_noise_energy'])
            self.assertAlmostEqual(record['measured_snr_db'], measured)
            self.assertLess(abs(measured - record['requested_snr_db']), .5)
            self.assertEqual(record['energy_sample_stop'] - record['energy_sample_start'], 7200)
        rows, _, stats = precision.quantize([5+5j, -5-5j, 131071/32768 + 0j])
        self.assertEqual(stats['positive_clamps'], 2)
        self.assertEqual(stats['negative_clamps'], 2)
        self.assertEqual(stats['total_clamps'], 4)
        self.assertEqual(rows[-1][0], 131071)  # Exactly on the rail is not a clamp event.

    def test_rejects_divergence_missing_cases_and_disabled_as_enabled(self):
        with self.assertRaises(RuntimeError):
            precision.check_acceptance(self.records[:-1])
        for mutate in ('divergence', 'disabled'):
            bad = deepcopy(self.records)
            if mutate == 'divergence':
                bad[0]['enabled']['position_rms_discrepancy_samples'] = .5
            else:
                bad[0]['enabled'] = deepcopy(bad[0]['disabled'])
                bad[0]['enabled']['output_sqnr_db'] = 90  # Still fails quiet tracking control.
            with self.subTest(mutate=mutate):
                with self.assertRaises(RuntimeError):
                    precision.check_acceptance(bad)

    def test_json_lifecycle_and_failure_exit(self):
        with tempfile.TemporaryDirectory() as work:
            output = Path(work) / 'results.json'
            with patch.object(precision, 'report', return_value=self.records):
                self.assertEqual(precision.main(['--output', str(output)]), 0)
            result = json.loads(output.read_text())
            self.assertEqual(result['status'], 'PASS')
            self.assertIn('completed_at_utc', result)
            self.assertTrue(result['source_hashes'])
            failing = Path(work) / 'failure.json'
            script = ("import sys;sys.path.insert(0,'tools');import timing_precision as p;"
                      "p.report=lambda: [];p.main(['--output',sys.argv[1]])")
            process = subprocess.run([sys.executable, '-c', script, str(failing)],
                                     cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(process.returncode, 0)
            failure = json.loads(failing.read_text())
            self.assertEqual(failure['status'], 'FAIL')
            self.assertIn('completed_at_utc', failure)
            optimized = subprocess.run([sys.executable, '-O', str(ROOT / 'tools/timing_precision.py'),
                                        '--output', str(Path(work) / 'optimized.json')],
                                       cwd=ROOT, capture_output=True, text=True)
            self.assertNotEqual(optimized.returncode, 0)
            self.assertIn('without Python optimization', optimized.stderr)
            self.assertFalse((Path(work) / 'optimized.json').exists())


if __name__ == '__main__':
    unittest.main()
