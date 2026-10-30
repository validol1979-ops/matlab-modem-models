"""Full profile fixtures, independent receiver inputs and arithmetic metric gates."""
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
import psk_precision as p
from regression_evidence import require_pass


class TestPskPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = p.report()

    def test_all_profiles_nominal_ser_and_noise_control(self):
        self.assertEqual(len(self.data['coverage']), 14)
        self.assertEqual(len(self.data['records']), 42)
        self.assertEqual({row['profile'] for row in self.data['coverage']}, {prof.name for prof in p.fixed.PROFILES})
        self.assertTrue(all(self.data['checks'].values()), {k: v for k, v in self.data['checks'].items() if not v})
        for row in self.data['records']:
            with self.subTest(profile=row['profile'], case=row['case']):
                for receiver in ('fixed', 'floating'):
                    self.assertEqual(row[receiver]['payload_symbols'], 320)
                    if row['case'] != 'low_snr':
                        self.assertEqual(row[receiver]['errors'], 0)

    def test_profile_matching_and_explicit_simo_scope(self):
        reps = p.representatives()
        for prof, cfg, coverage in reps:
            self.assertIs(p.fixed.profile_for(cfg), prof)
            for name in coverage['matched_config_names']:
                original = p.real.load_config(ROOT/'modems'/name/'config.json')
                self.assertIs(p.fixed.profile_for(original), prof)
        derived = next(c for _, _, c in reps if c['profile'] == 'qpsk_diff')
        self.assertEqual(derived['matched_config_names'], [])
        self.assertEqual(derived['derived']['override'], dict(diversity_branches=1))
        self.assertIn('excludes SIMO', derived['derived']['scope'])

    def test_metric_formula_shapes_and_payload_boundary(self):
        self.assertAlmostEqual(p.metric([.9, .9], [1., 1.])['sqnr_db'], 20)
        self.assertAlmostEqual(p.metric([1j, 1j], [1., 1.])['sqnr_db'], -10*np.log10(2))
        self.assertTrue(p.metric([1], [1])['exact_match'])
        for a, b in [([], []), ([1], [1, 2]), ([[1]], [[1]]), ([np.nan], [1]), ([1], [np.inf])]:
            with self.subTest(metric=(a, b)), self.assertRaises(ValueError):
                p.metric(a, b)
        # An error before the boundary is excluded; the first payload error counts.
        self.assertEqual(p.payload_score(np.array([1, 0, 1]), np.zeros(3, int), preamble=2)['errors'], 1)
        for decoded, labels in [(np.array([0, 4]), np.zeros(2, int)), (np.array([-.1, 0]), np.zeros(2, int)),
                                (np.zeros(2, int), np.array([0, -1])), (np.zeros(1, int), np.zeros(2, int))]:
            with self.subTest(labels=(decoded, labels)), self.assertRaises(ValueError):
                p.payload_score(decoded, labels, preamble=0, alphabet=4)

    def test_qam64_fir_scaling_is_not_silently_normalized(self):
        row = next(r for r in self.data['records'] if r['profile'] == 'qam64' and r['case'] == 'nominal')
        coverage = next(c for c in self.data['coverage'] if c['profile'] == 'qam64')
        self.assertEqual((coverage['tx_shift'], coverage['rx_shift'], coverage['tx_amplitude']), (16, 19, 16384))
        self.assertEqual(coverage['rx_fir_scale'], .25)
        self.assertGreater(row['nodes']['tx_rrc']['sqnr_db'], 90)
        self.assertGreater(row['nodes']['rx_rrc']['sqnr_db'], 90)
        prof, cfg, _ = next(t for t in p.representatives() if t[0] is p.fixed.QAM64)
        labels = np.random.default_rng(p.LABEL_SEED).integers(0, prof.alphabet, p.COUNT)
        wave = p.complex_samples(p.fixed.transmit(prof, labels))
        rows = p.fixed.quantize(p.real.channel(cfg, wave, **p.CHANNELS['nominal']))
        filtered = p.complex_samples(p.fixed.fir(rows, prof.rx_shift))
        unscaled = np.convolve(p.complex_samples(rows), p.real.rrc_taps(8, 32, 1))
        self.assertLess(p.metric(filtered, unscaled)['sqnr_db'], 3)

    def test_eq_output_has_separate_scope_and_pre_gain(self):
        for profile in ('qam16_eq', 'qam16_dfe'):
            row = next(r for r in self.data['records'] if r['profile'] == profile and r['case'] == 'nominal')
            self.assertIn('pre_eq_gain', row['nodes'])
            self.assertNotIn('gain', row['nodes'])
            self.assertIn('excludes coefficient adaptation', row['nodes']['eq_arithmetic']['scope'])
            self.assertGreater(row['nodes']['eq_arithmetic']['sqnr_db'], 85)

    def test_receivers_share_waveform_and_only_preamble(self):
        prof, cfg, _ = p.representatives([p.fixed.QPSK])[0]
        labels = np.random.default_rng(p.LABEL_SEED).integers(0, prof.alphabet, p.COUNT)
        tx = p.fixed.transmit(prof, labels); ref = p.real.transmit(cfg, labels)['waveform']
        with patch.object(p.fixed, 'receive', wraps=p.fixed.receive) as integer, patch.object(p.real, 'receive', wraps=p.real.receive) as floating:
            row = p.measure_case(prof, cfg, labels, 'nominal', p.CHANNELS['nominal'], tx, ref)
        np.testing.assert_array_equal(p.complex_samples(integer.call_args.args[1]), floating.call_args.args[1])
        self.assertEqual(len(integer.call_args.args[2]), p.PREAMBLE)
        self.assertEqual(len(floating.call_args.args[2]), p.PREAMBLE)
        self.assertEqual(row['fixed']['errors'], 0)
        with patch.object(p.fixed, 'receive', side_effect=ValueError('injected acquisition failure')):
            failed = p.measure_case(prof, cfg, labels, 'nominal', p.CHANNELS['nominal'], tx, ref)
        self.assertEqual(failed['fixed']['status'], 'failed')
        self.assertIn('injected acquisition failure', failed['fixed']['error'])
        self.assertEqual(failed['floating']['status'], 'decoded')
        self.assertFalse(all(p.check_records([failed], [prof.name]).values()))

    def test_report_evidence_failure_and_optimization_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'results.json'
            with patch.object(p, 'report', return_value=self.data), contextlib.redirect_stdout(io.StringIO()):
                p.main(['--output', str(target)])
            require_pass(json.loads(target.read_text()))
            broken = deepcopy(self.data)
            broken['records'][0]['fixed']['errors'] = 1
            broken['checks'] = p.check_records(broken['records'], [prof.name for prof in p.fixed.PROFILES])
            with patch.object(p, 'report', return_value=broken), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'zero_ser'):
                    p.main(['--output', str(target)])
            failed = json.loads(target.read_text())
            self.assertEqual(failed['status'], 'FAIL')
            with self.assertRaises(RuntimeError):
                require_pass(failed)
            target.write_text(json.dumps(dict(status='PASS')))
            optimized = subprocess.run([sys.executable, '-O', str(ROOT/'tools/psk_precision.py'), '--output', str(target)], capture_output=True, text=True)
            self.assertNotEqual(optimized.returncode, 0)
            self.assertIn('without Python optimization', optimized.stderr)
            self.assertEqual(json.loads(target.read_text())['status'], 'FAIL')
            self.assertIn('without Python optimization', json.loads(target.read_text())['error'])


if __name__ == '__main__':
    unittest.main()
