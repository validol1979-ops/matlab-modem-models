"""Independent metrics and explicit ambiguity checks for the precision report."""
from pathlib import Path
import contextlib
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import sync_precision as p
from regression_evidence import require_pass


class TestSyncPrecision(unittest.TestCase):
    def test_invalid_measurement_inputs(self):
        for output, reference in [([], []), ([1, 2], [1]), ([[1]], [[1]]), ([np.nan], [1]), ([1], [np.inf])]:
            with self.subTest(sqnr=(output, reference)), self.assertRaises(ValueError):
                p.sqnr_db(output, reference)
        good = dict(output=np.ones(2), phases=np.zeros(2), labels=np.zeros(2, int), true_phase=np.zeros(2))
        for key, value in [('output', [1]), ('phases', [np.nan, 0]), ('true_phase', [0, np.inf]),
                           ('labels', [0., 1.]), ('labels', [0, 4]), ('labels', [-1, 0])]:
            with self.subTest(receiver=(key, value)), self.assertRaises(ValueError):
                p.receiver_metrics(**dict(good, **{key: value}))
        for arguments in [dict(count=0), dict(count=10.5), dict(steady_start=4096),
                          dict(steady_start=.5), dict(esn0_db=np.nan), dict(esn0_db=np.inf),
                          dict(cfo_rad_per_symbol=np.nan)]:
            with self.subTest(waveform=arguments), self.assertRaises(ValueError):
                p.waveform(**arguments)

    def test_sqnr_known_values_no_alignment(self):
        expected = np.ones(8, complex)
        metrics = p.sqnr_db(.9*expected, expected)
        self.assertAlmostEqual(metrics['sqnr_db'], 20)
        self.assertAlmostEqual(p.sqnr_db(1j*expected, expected)['sqnr_db'], -10*np.log10(2))
        self.assertTrue(p.sqnr_db(expected, expected)['exact_match'])

    def test_quadrant_is_not_corrected_by_truth(self):
        labels = np.tile(np.arange(4), 10)
        metric = p.receiver_metrics(p.CONSTELLATION[labels]*1j, np.full(40, -np.pi/2), labels, np.zeros(40))
        self.assertEqual(metric['raw_ser'], 1)
        self.assertAlmostEqual(metric['true_phase_rms_deg'], 90)
        self.assertAlmostEqual(metric['modulo90_phase_rms_deg'], 0)
        self.assertEqual(metric['dominant_quadrant'], 3)
        self.assertEqual(metric['quadrant_histogram'], [0, 0, 0, 40])

    def test_wrapped_true_phase_not_unwrapped_distance(self):
        labels = np.zeros(2, int)
        phases = np.deg2rad([361, -359])
        metric = p.receiver_metrics(p.CONSTELLATION[labels], phases, labels, np.zeros(2))
        self.assertAlmostEqual(metric['true_phase_rms_deg'], 1)

    def test_waveform_reproducibility_snr_and_quantization(self):
        first = p.waveform(8)
        second = p.waveform(8)
        self.assertEqual(first[0], second[0])
        self.assertEqual(first[4], second[4])
        self.assertLess(abs(first[4]['measured_esn0_db']-8), .3)
        np.testing.assert_array_equal(first[1], p.complex_of(first[0]))
        self.assertEqual(first[4]['input_rail_excursions'], 0)
        quiet = p.waveform()
        self.assertEqual(quiet[4]['noise_power'], 0)
        np.testing.assert_array_equal(first[2], quiet[2])

    def test_floating_algorithm_independent_of_fixed(self):
        rows, wave, *_ = p.waveform(count=32, steady_start=8)
        expected = p.research_core.run('costas', [.08, .001], wave)
        fake = ([(0, 0)]*32, [0]*32)
        with patch.object(p.fixed, 'costas', return_value=fake), patch.object(p.research_core, 'run', wraps=p.research_core.run) as spy:
            loops = p.run_loops(rows)
        np.testing.assert_array_equal(loops['enabled']['float_output'], expected[:32])
        np.testing.assert_array_equal(loops['enabled']['float_phase'], expected[32:].real)
        np.testing.assert_array_equal(spy.call_args_list[0].args[2], wave)
        self.assertEqual(loops['enabled']['float_phase'][0], 0)
        self.assertTrue(np.all(loops['enabled']['fixed_output'] == 0))

    def test_default_cases_and_disabled_same_wave_control(self):
        cases = [p.measure_case('quiet')]
        cases += [p.measure_case(f'esn0_{snr}db', snr) for snr in (20, 12, 8)]
        cases += [p.measure_case('quadrant_ambiguity', phase_rad=np.deg2rad(100))]
        checks = p.check_cases(cases)
        self.assertTrue(all(checks.values()), {k: ok for k, ok in checks.items() if not ok})
        rows, wave, labels, phase, meta = p.waveform()
        raw = p.receiver_metrics(wave[512:], np.zeros(len(wave)-512), labels[512:], phase[512:])
        self.assertEqual(cases[0]['disabled']['float'], raw)
        broken = [dict(cases[0], enabled=cases[0]['disabled'])]
        self.assertFalse(all(p.check_cases(broken).values()))

    def test_report_pass_and_failed_gate_evidence(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'results.json'
            with contextlib.redirect_stdout(io.StringIO()):
                p.main(['--output', str(target)])
            report = json.loads(target.read_text())
            require_pass(report)
            self.assertEqual(len(report['cases']), 5)
            self.assertIn('source_hashes', report)
            with patch.object(p, 'check_cases', return_value={'injected_failure': False}), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'injected_failure'):
                    p.main(['--output', str(target)])
            failed = json.loads(target.read_text())
            self.assertEqual(failed['status'], 'FAIL')
            with self.assertRaises(RuntimeError):
                require_pass(failed)


if __name__ == '__main__':
    unittest.main()
