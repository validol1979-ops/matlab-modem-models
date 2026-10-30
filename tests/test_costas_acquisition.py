"""QPSK Costas acquisition grid (tools/costas_acquisition.py) on the sync_fixed.costas model."""
from pathlib import Path
import json
import copy
import contextlib
import io
import tempfile
from unittest.mock import patch
import subprocess
import sys
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
sys.path.insert(0, str(ROOT / 'tools'))
import costas_acquisition as ac

_GRID = None


def grid():
    global _GRID
    if _GRID is None:
        _GRID = ac.run_grid()
    return _GRID


def case(phase_deg, cfo, state):
    for entry in grid():
        if entry['phase_deg'] == phase_deg and entry['cfo_rad_per_sample'] == cfo:
            return entry[state]
    raise KeyError((phase_deg, cfo))


class DeterministicStimulus(unittest.TestCase):
    def test_symbols_are_deterministic_unit_qpsk(self):
        first, second = ac.symbols(), ac.symbols()
        np.testing.assert_array_equal(first, second)
        np.testing.assert_allclose(np.abs(first), 1.0)
        angles = np.degrees(np.angle(first)) % 90.0
        np.testing.assert_allclose(angles, 45.0, atol=1e-9)

    def test_reference_is_the_known_phase_plus_cfo_times_n(self):
        ref = ac.reference(70, 0.006)
        np.testing.assert_allclose(ref, np.deg2rad(70) + 0.006 * np.arange(ac.N))

    def test_quantized_payload_is_in_rtl_input_range(self):
        pairs = ac.quantize(ac.symbols() * np.exp(1j * ac.reference(160, 0.3)))
        self.assertEqual(len(pairs), ac.N)
        for re, im in pairs:
            self.assertTrue(-131072 <= re <= 131071 and -131072 <= im <= 131071)


class MetricsAndClassification(unittest.TestCase):
    def test_final_windows_are_two_non_overlapping_tail_windows(self):
        (a0, a1), (b0, b1) = ac.WINDOWS
        self.assertEqual((a0, a1, b0, b1), (1600, 2000, 2000, 2400))
        self.assertLessEqual(b1, ac.N)

    def test_window_metrics_on_a_constant_180_degree_error(self):
        metrics = ac.window_metrics(np.full(400, 180.0), 0, 400)
        self.assertAlmostEqual(metrics['true_angular_error_rms_deg'], 180.0)
        self.assertAlmostEqual(metrics['modulo90_residual_rms_deg'], 0.0)
        self.assertEqual(metrics['quadrant_offset_deg'], 180)  # explicit magnitude
        self.assertEqual(metrics['signed_offset_deg'], 180)
        self.assertEqual(metrics['quadrant_stability'], 1.0)
        self.assertEqual(ac.classify(metrics), ac.ADJACENT_LOCK)

    def test_window_metrics_on_a_wandering_phase(self):
        error = np.linspace(0.0, 1800.0, 400)
        metrics = ac.window_metrics(error, 0, 400)
        self.assertGreater(metrics['modulo90_residual_rms_deg'], ac.LOCK_RESIDUAL_MAX_DEG)
        self.assertLess(metrics['quadrant_stability'], ac.LOCK_STABILITY_MIN)
        self.assertEqual(ac.classify(metrics), ac.UNLOCKED)

    def test_small_residual_at_ninety_is_adjacent_not_true(self):
        metrics = ac.window_metrics(np.full(400, 89.9), 0, 400)
        self.assertEqual(metrics['quadrant_offset_deg'], 90)
        self.assertEqual(ac.classify(metrics), ac.ADJACENT_LOCK)
        metrics = ac.window_metrics(np.full(400, 0.4), 0, 400)
        self.assertEqual(ac.classify(metrics), ac.TRUE_LOCK)
        metrics = ac.window_metrics(np.full(400, 1.1), 0, 400)
        self.assertEqual(ac.classify(metrics), ac.UNLOCKED)


class AcquisitionGrid(unittest.TestCase):
    def test_zero_and_small_offset_carry_lock_to_the_true_quadrant(self):
        for cfo in (0.0, 0.006):
            for phase in (0, 20):
                result = case(phase, cfo, 'enabled')
                self.assertEqual(result['classification'], ac.TRUE_LOCK, (phase, cfo))
                self.assertEqual(result['quadrant_offset_deg'], 0)
                for metrics in result['windows']:
                    self.assertLess(metrics['true_angular_error_rms_deg'], 1.0)
                    self.assertGreater(metrics['quadrant_stability'], 0.999)

    def test_large_initial_phase_locks_to_the_adjacent_quadrant(self):
        for cfo in (0.0, 0.006):
            self.assertEqual(case(70, cfo, 'enabled')['classification'], ac.ADJACENT_LOCK)
        adjacent = case(160, 0.006, 'enabled')
        self.assertEqual(adjacent['classification'], ac.ADJACENT_LOCK)
        self.assertEqual(adjacent['quadrant_offset_deg'], 180)  # 180 also adjacent
        self.assertEqual(adjacent['signed_offset_deg'], 180)    # ... with explicit magnitude
        for metrics in adjacent['windows']:
            self.assertLess(metrics['modulo90_residual_rms_deg'], 1.0)
            self.assertGreater(metrics['quadrant_stability'], 0.999)
        self.assertEqual(case(70, 0.0, 'enabled')['quadrant_offset_deg'], 270)

    def test_untrackable_carry_offset_leaves_the_loop_unlocked(self):
        for phase in ac.PHASES_DEG:
            result = case(phase, 0.3, 'enabled')
            self.assertEqual(result['classification'], ac.UNLOCKED, phase)
            self.assertIsNone(result['quadrant_offset_deg'])
            for metrics in result['windows']:
                self.assertGreater(metrics['modulo90_residual_rms_deg'], 20.0)

    def test_disabled_gain_control_never_grabs_the_carry(self):
        for phase in ac.PHASES_DEG:
            for cfo in ac.CFOS:
                off = case(phase, cfo, 'disabled')
                if (phase, cfo) == (0, 0.0):
                    continue  # constant zero reference: nothing the loop could grab
                self.assertEqual(off['classification'], ac.UNLOCKED, (phase, cfo))
                for metrics in off['windows']:
                    self.assertGreater(metrics['modulo90_residual_rms_deg'], 15.0)

    def test_locks_beat_the_disabled_control_by_a_wide_margin(self):
        for phase in (0, 20, 70, 160):
            for cfo in (0.0, 0.006):
                if (phase, cfo) == (0, 0.0):
                    continue  # zero reference: the disabled control sits at zero too
                on = sorted(m['modulo90_residual_rms_deg'] for m in case(phase, cfo, 'enabled')['windows'])
                off = sorted(m['modulo90_residual_rms_deg'] for m in case(phase, cfo, 'disabled')['windows'])
                self.assertLess(on[-1], 1.0)
                self.assertGreater(off[0], 15.0)

    def test_grid_exercises_exactly_the_three_classifications_and_is_stable(self):
        classes = {entry['enabled']['classification'] for entry in grid()}
        self.assertEqual(classes, {ac.TRUE_LOCK, ac.ADJACENT_LOCK, ac.UNLOCKED})
        for entry in grid():
            for state in ('enabled', 'disabled'):
                result = entry[state]
                window_classes = {ac.classify(m) for m in result['windows']}
                self.assertEqual(len(window_classes), 1, (entry['phase_deg'], entry['cfo_rad_per_sample'], state))
                if result['classification'] != ac.UNLOCKED:
                    offsets = {m['quadrant_offset_deg'] for m in result['windows']}
                    self.assertEqual(len(offsets), 1)
        self.assertEqual(ac.evaluate(grid()), [])


class NegativeControls(unittest.TestCase):
    def test_missing_grid_point_cannot_pass_with_all_three_classes(self):
        self.assertTrue(ac.evaluate(copy.deepcopy(grid())[1:]))

    def test_cached_classification_cannot_hide_bad_window_metrics(self):
        changed = copy.deepcopy(grid())
        for metrics in changed[0]['enabled']['windows']:
            metrics['modulo90_residual_rms_deg'] = 20.0
        self.assertTrue(ac.evaluate(changed))

    def test_quadrant_change_between_tail_windows_is_unlocked(self):
        # Both windows have exactly zero modulo90 error, but different quadrants.
        phases = [0] * ac.N
        phases[2000:] = [2**30] * 400
        with patch.object(ac.sync_fixed, 'costas', return_value=([], phases)):
            result = ac.run_case(0, 0, ac.GAINS)
        self.assertEqual(result['classification'], ac.UNLOCKED)
        self.assertIsNone(result['quadrant_offset_deg'])
        self.assertEqual([m['modulo90_residual_rms_deg'] for m in result['windows']], [0., 0.])

    def test_failed_grid_writes_fail_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'results.json'
            with patch.object(ac, 'TARGET', target), patch.object(ac, 'run_grid', return_value=[]):
                with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
                    code = ac.main()
            self.assertNotEqual(code, 0)
            self.assertEqual(json.loads(target.read_text())['status'], 'FAIL')


class CommandLine(unittest.TestCase):
    def test_cli_reports_the_grid_as_json_and_passes(self):
        run = subprocess.run([sys.executable, str(ROOT / 'tools/costas_acquisition.py')],
                             capture_output=True, text=True, timeout=60)
        self.assertEqual(run.returncode, 0, run.stdout[-2000:] + run.stderr[-2000:])
        report = json.loads(run.stdout)
        self.assertEqual(report['status'], 'PASS')
        self.assertFalse(report['rtl_verified'])
        self.assertEqual(report['failures'], [])
        self.assertEqual(sorted(report['classes_observed']), sorted([ac.ADJACENT_LOCK, ac.TRUE_LOCK, ac.UNLOCKED]))
        self.assertEqual(report['parameters']['stream']['samples'], ac.N)
        self.assertEqual(report['parameters']['windows'], [[1600, 2000], [2000, 2400]])
        self.assertEqual(len(report['cases']), len(ac.PHASES_DEG) * len(ac.CFOS))
        for entry in report['cases']:
            self.assertEqual(len(entry['enabled']['windows']), 2)
        self.assertTrue(report['completed_at_utc'].endswith('+00:00'))
        artifact = json.loads((ROOT / 'build/rtl/costas_acquisition/results.json').read_text())
        self.assertEqual(artifact['status'], 'PASS')
        self.assertEqual(artifact['parameters'], report['parameters'])


if __name__ == '__main__':
    unittest.main()
