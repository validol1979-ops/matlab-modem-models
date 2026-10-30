"""Independent references, native FFT units, and finite preclamp observations."""
from copy import deepcopy
from pathlib import Path
import contextlib
import io
import json
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
import fft_fir_precision as p
from regression_evidence import require_pass


class TestFftFirPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = p.report()

    def test_required_profiles_and_separate_clipping(self):
        self.assertEqual(len(self.data['records']), 36)
        self.assertTrue(all(self.data['checks'].values()), {k: v for k, v in self.data['checks'].items() if not v})
        for row in self.data['records']:
            if row['classification'] == 'clean':
                self.assertEqual(row['preclamp']['events'], 0)
            else:
                self.assertGreater(row['preclamp']['events'], 0)
            self.assertIn('not a width guarantee', row['preclamp']['scope'])
        incomplete = self.data['records'][1:]
        self.assertFalse(p.check_records(incomplete)['complete_coverage'])
        negative = next(r for r in self.data['records'] if r['kind'] == 'fft' and r['n'] == 4 and r['fixture'] == 'extreme_negative')
        self.assertEqual(negative['preclamp']['minimum_signed_bits_for_observed_range'], 20)
        self.assertGreater(negative['preclamp']['events'], 0)

    def test_fft_analytic_impulse_convention_and_display_rescaling(self):
        for n in p.SIZES:
            rows = p.fft_input(n, 'forward', 'impulse')
            forward = p.as_complex(p.fft.transform(rows, False))
            inverse = p.as_complex(p.fft.transform(rows, True))
            np.testing.assert_array_equal(forward, np.full(n, (2-1j)/n))
            np.testing.assert_array_equal(inverse, np.full(n, 2-1j))
            for direction in ('forward', 'inverse'):
                row = next(r for r in self.data['records'] if r['kind'] == 'fft' and r['n'] == n and r['direction'] == direction and r['fixture'] == 'impulse')
                self.assertTrue(row['native_metrics']['exact_match'])
                self.assertEqual(row['representations']['scaled']['post_native_factor'], 1 if direction == 'forward' else 1/n)
                self.assertEqual(row['representations']['unscaled']['post_native_factor'], n if direction == 'forward' else 1)

    def test_common_integer_inputs_and_independent_float_references(self):
        original_fft = p.fft.transform
        def zero_fft(rows, *args, **kwargs):
            original_fft(rows, *args, **kwargs)  # retain real observer evaluations
            return [(0, 0)]*len(rows)
        with patch.object(p.fft, 'transform', side_effect=zero_fft), patch.object(p.np.fft, 'fft', wraps=np.fft.fft) as reference:
            row = p.fft_case(32, 'forward', 'random')
        np.testing.assert_array_equal(reference.call_args.args[0], p.as_complex(p.fft_input(32, 'forward', 'random')))
        self.assertAlmostEqual(row['native_metrics']['normalized_rms_evm'], 1)
        self.assertAlmostEqual(row['native_metrics']['sqnr_db'], 0)
        original_fir = p.fir.filter
        def zero_fir(rows, taps, **kwargs):
            values = original_fir(rows, taps, **kwargs)
            return [(0, 0)]*len(values)
        with patch.object(p.fir, 'filter', side_effect=zero_fir), patch.object(p.np, 'convolve', wraps=np.convolve) as reference:
            row = p.fir_case('wsinc')
        rows, taps, ideal = p.fir_fixture('wsinc')
        self.assertEqual(reference.call_count, 2)
        for call in reference.call_args_list:
            np.testing.assert_array_equal(call.args[0], p.as_complex(rows))
        np.testing.assert_array_equal(reference.call_args_list[0].args[1], p.as_complex(taps, 17))
        np.testing.assert_array_equal(reference.call_args_list[1].args[1], ideal)
        self.assertAlmostEqual(row['loaded_taps_metrics']['normalized_rms_evm'], 1)
        self.assertAlmostEqual(row['ideal_taps_metrics']['normalized_rms_evm'], 1)

    def test_observed_bits_and_exact_rail_event_semantics(self):
        for low, high, bits in [(0, 0, 1), (-1, 0, 1), (-8, 7, 4), (-9, 7, 5), (-8, 8, 5)]:
            self.assertEqual(p.minimum_signed_bits(low, high), bits)
        symmetric = p.ObservedTrace(4, 'sym')
        self.assertEqual(symmetric.record('clamp', -8, 7, clamp='sym'), -7)
        self.assertEqual(symmetric.record('clamp', 7, 7, clamp='sym'), 7)
        measured = symmetric.report()
        self.assertEqual(measured['events'], 1)
        self.assertEqual(measured['minimum_signed_bits_for_observed_range'], 4)
        asymmetric = p.ObservedTrace(4, 'asym')
        self.assertEqual(asymmetric.record('clamp', -8, 7), -8)
        self.assertEqual(asymmetric.total(), 0)

    def test_metric_evm_sqnr_and_invalid_shapes(self):
        metric = p.metrics([.9, .9], [1., 1.])
        self.assertAlmostEqual(metric['sqnr_db'], 20)
        self.assertAlmostEqual(metric['normalized_rms_evm'], .1)
        self.assertAlmostEqual(metric['rms_evm_percent'], 10)
        self.assertAlmostEqual(metric['sqnr_db'], -20*np.log10(metric['normalized_rms_evm']))
        for actual, expected in [([], []), ([1], [1, 2]), ([[1]], [[1]]), ([np.nan], [1]), ([1], [np.inf]), ([0], [0])]:
            with self.subTest(samples=(actual, expected)), self.assertRaises(ValueError):
                p.metrics(actual, expected)
        for bad in [[[1., 0.]], [[1]], []]:
            with self.subTest(raw=bad), self.assertRaises(ValueError):
                p.as_complex(bad)

    def test_fir_impulse_loaded_taps_and_coefficient_quantization(self):
        rows, taps, ideal = p.fir_fixture('impulse')
        values = p.fir.filter(rows, taps)
        self.assertEqual(values[:3], [(8192, -4096), (16384, -8192), (8192, -4096)])
        row = next(r for r in self.data['records'] if r['kind'] == 'fir' and r['fixture'] == 'impulse')
        self.assertTrue(row['loaded_taps_metrics']['exact_match'])
        wsinc = next(r for r in self.data['records'] if r['kind'] == 'fir' and r['fixture'] == 'wsinc')
        self.assertGreater(wsinc['coefficient_metrics']['error_power'], 0)
        self.assertNotEqual(wsinc['loaded_taps_metrics']['error_power'], wsinc['ideal_taps_metrics']['error_power'])

    def test_report_status_hashes_and_optimization_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'results.json'
            with patch.object(p, 'report', return_value=self.data), contextlib.redirect_stdout(io.StringIO()):
                p.main(['--output', str(target)])
            completed = json.loads(target.read_text()); require_pass(completed)
            self.assertIn('source_hashes', completed)
            broken = deepcopy(self.data)
            broken['records'][0]['native_metrics'].update(exact_match=False, sqnr_db=0)
            broken['checks'] = p.check_records(broken['records'])
            with patch.object(p, 'report', return_value=broken), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'native_precision'):
                    p.main(['--output', str(target)])
            self.assertEqual(json.loads(target.read_text())['status'], 'FAIL')
            target.write_text(json.dumps(dict(status='PASS')))
            child = subprocess.run([sys.executable, '-O', str(ROOT/'tools/fft_fir_precision.py'), '--output', str(target)], capture_output=True, text=True)
            self.assertNotEqual(child.returncode, 0)
            self.assertIn('without Python optimization', child.stderr)
            self.assertEqual(json.loads(target.read_text())['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
