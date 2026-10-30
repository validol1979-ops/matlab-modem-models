"""Same-input independent RX, split OQPSK phases, and MRC noise conventions."""
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
import oqpsk_mrc_precision as p
from regression_evidence import require_pass


class TestOqpskMrcPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = p.report()

    def test_required_cases_clean_ser_and_noise_controls(self):
        self.assertEqual(len(self.data['records']), 11)
        self.assertEqual({r['kind'] for r in self.data['records']}, {'oqpsk', 'mrc'})
        self.assertTrue(all(self.data['checks'].values()), {k: v for k, v in self.data['checks'].items() if not v})
        for row in self.data['records']:
            for receiver in ('fixed', 'floating'):
                self.assertEqual(row[receiver]['payload_symbols'], 320)
                if row['case'] not in ('noisy', 'low_snr'):
                    self.assertEqual(row[receiver]['errors'], 0)
        for receiver in ('fixed', 'floating'):
            self.assertGreater(sum(r[receiver]['errors'] for r in self.data['records'] if r['kind'] == 'mrc' and r['case'] == 'noisy'), 0)
        oq = next(r for r in self.data['records'] if r['kind'] == 'oqpsk' and r['case'] == 'nominal')
        self.assertFalse(oq['fixed_agc'])
        self.assertNotIn('gain', oq['nodes'])
        missing = [r for r in self.data['records'] if r['kind'] == 'mrc']
        self.assertFalse(p.check_records(missing)['complete_coverage'])
        truth = deepcopy(self.data['records'])
        for row in truth:
            if row['case'] in ('noisy', 'low_snr'):
                for receiver in ('fixed', 'floating'):
                    row[receiver]['errors'] = 0
        self.assertFalse(all(p.check_records(truth).values()))

    def test_noise_power_and_inverse_variance_weights(self):
        branches, meta = p.make_branches(np.zeros(10000, complex), np.array([1+0j, 1+0j]), (1, 4), .3)
        for branch, variance, metadata in zip(branches, (1, 4), meta):
            expected_component = .3**2*variance
            self.assertAlmostEqual(metadata['expected_complex_noise_power'], 2*expected_component)
            self.assertLess(abs(np.var(branch.real)/expected_component-1), .05)
            self.assertLess(abs(np.var(branch.imag)/expected_component-1), .05)
            self.assertLess(abs(np.mean(abs(branch)**2)/(2*expected_component)-1), .05)
        np.testing.assert_allclose(p.float_weights(np.array([.2+.3j, 1-.4j]), (1, 4)),
                                   np.array([10/21-5j/7, 25/42+5j/21]), rtol=0, atol=1e-15)
        np.testing.assert_allclose(p.float_weights(np.array([1., 1.]), (1, 4)), [.8, .2])
        for variances in [(0, 1), (1, 65536), (1.5, 1), (float('nan'), 1), (1,)]:
            with self.subTest(variances=variances), self.assertRaises(ValueError):
                p.make_branches(np.ones(8), np.ones(2), variances, .3)
        for sigma in [-1, float('nan'), float('inf'), 1j, [1]]:
            with self.subTest(sigma=sigma), self.assertRaises(ValueError):
                p.make_branches(np.ones(8), np.ones(2), (1, 1), sigma)

    def test_oqpsk_half_symbol_phase_and_fraction_nodes(self):
        cfg = p.real.load_config(ROOT/'modems'/p.OQ_CONFIG/'config.json')
        labels = np.random.default_rng(p.LABEL_SEED).integers(0, 4, p.COUNT)
        tx = p.complex_samples(p.oq.transmit(labels))
        rows, _ = p.quantized(p.real.channel(cfg, tx, seed=p.CHANNEL_SEED, **p.OQ_CASES['nominal']))
        result = p.oq.receive(rows, labels[:p.PREAMBLE], p.COUNT, observe=True)
        phases_i, phases_q = p.oq_phases(result['nodes'], result['acquisition'])
        offset = 4*result['acquisition']['frequency']*2*np.pi/2**32
        np.testing.assert_allclose(np.exp(1j*phases_q), np.exp(1j*(phases_i+offset)), rtol=0, atol=1e-14)
        actual_q = p.complex_samples([node['rQ'] for node in result['nodes']])
        upstream_q = p.complex_samples([node['zQ'] for node in result['nodes']])
        correct = p.metric(actual_q, upstream_q*np.exp(-1j*phases_q))
        wrong = p.metric(actual_q, upstream_q*np.exp(-1j*phases_i))
        self.assertGreater(correct['sqnr_db'], p.OQ_LIMITS['rotation_q'])
        self.assertLess(wrong['sqnr_db'], p.OQ_LIMITS['rotation_q'])
        # Modular wrap is essential when the half-symbol offset crosses pi.
        fake_i, fake_q = p.oq_phases([dict(thetaI=(1 << 31)-2)], dict(frequency=2))
        self.assertLess(fake_q[0], 0)
        np.testing.assert_allclose(np.exp(1j*fake_q), np.exp(1j*(fake_i+8*2*np.pi/2**32)), atol=1e-15)

    def test_oqpsk_quantized_once_and_receivers_only_preamble(self):
        with patch.object(p.oq, 'quantize', wraps=p.oq.quantize) as quantizer, patch.object(p.oq, 'receive', wraps=p.oq.receive) as fixed, patch.object(p.real, 'receive', wraps=p.real.receive) as floating:
            row = p.measure_oq('nominal', p.OQ_CASES['nominal'])
        self.assertEqual(quantizer.call_count, 1)
        np.testing.assert_array_equal(p.complex_samples(fixed.call_args.args[0]), floating.call_args.args[1])
        self.assertEqual(len(fixed.call_args.args[1]), p.PREAMBLE)
        self.assertEqual(len(floating.call_args.args[2]), p.PREAMBLE)
        self.assertEqual(row['fixed']['errors'], 0)

    def test_mrc_branches_quantized_once_and_floating_combiner_independent(self):
        with patch.object(p.psk, 'quantize', wraps=p.psk.quantize) as quantizer, patch.object(p.mrc, 'combine', wraps=p.mrc.combine) as combine, patch.object(p.psk, 'receive', wraps=p.psk.receive) as fixed, patch.object(p.real, 'maximal_ratio_combine', wraps=p.real.maximal_ratio_combine) as floating_combine, patch.object(p.real, 'receive', wraps=p.real.receive) as floating:
            row = p.measure_mrc('nominal', (1, 4), *p.MRC_CASES['nominal'])
        self.assertEqual(quantizer.call_count, 2)
        for index in (0, 1):
            np.testing.assert_array_equal(p.complex_samples(combine.call_args.args[index]), floating_combine.call_args.args[0][index])
        np.testing.assert_array_equal(p.complex_samples(row['gains_q15']), floating_combine.call_args.args[1])
        self.assertEqual(tuple(floating_combine.call_args.args[2]), (1, 4))
        self.assertEqual(len(fixed.call_args.args[2]), p.PREAMBLE)
        self.assertEqual(len(floating.call_args.args[2]), p.PREAMBLE)
        self.assertEqual(row['fixed']['errors'], 0)
        # Disabling the fixed full receiver cannot change the independent float RX.
        with patch.object(p.psk, 'receive', side_effect=ValueError('injected fixed acquisition failure')):
            failed = p.measure_mrc('nominal', (1, 4), *p.MRC_CASES['nominal'])
        self.assertEqual(failed['fixed']['status'], 'failed')
        self.assertEqual(failed['floating']['status'], 'decoded')
        self.assertEqual(failed['floating']['errors'], 0)
        self.assertFalse(all(p.check_records([failed]).values()))

    def test_pass_fail_evidence_and_optimization_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder)/'results.json'
            with patch.object(p, 'report', return_value=self.data), contextlib.redirect_stdout(io.StringIO()):
                p.main(['--output', str(target)])
            require_pass(json.loads(target.read_text()))
            broken = deepcopy(self.data)
            broken['records'][0]['fixed']['errors'] = 1
            broken['checks'] = p.check_records(broken['records'])
            with patch.object(p, 'report', return_value=broken), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'zero_ser'):
                    p.main(['--output', str(target)])
            self.assertEqual(json.loads(target.read_text())['status'], 'FAIL')
            target.write_text(json.dumps(dict(status='PASS')))
            child = subprocess.run([sys.executable, '-O', str(ROOT/'tools/oqpsk_mrc_precision.py'), '--output', str(target)], capture_output=True, text=True)
            self.assertNotEqual(child.returncode, 0)
            self.assertIn('without Python optimization', child.stderr)
            failed = json.loads(target.read_text())
            self.assertEqual(failed['status'], 'FAIL')
            with self.assertRaises(RuntimeError):
                require_pass(failed)


if __name__ == '__main__':
    unittest.main()
