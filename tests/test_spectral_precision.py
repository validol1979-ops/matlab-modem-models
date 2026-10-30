"""Independent spectral arithmetic, physical time geometry and honest quality gates."""
import copy
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
import spectral_precision as p
from regression_evidence import require_pass


class TestSpectralPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = p.report()

    def find(self, block, size, fixture):
        key = 'm' if block == 'pfb' else 'n'
        return next(r for r in self.result['records']
                    if r['block'] == block and r['parameters'][key] == size
                    and r['fixture'] == fixture)

    def test_complete_finite_measurement_scope_and_stress(self):
        records = self.result['records']
        self.assertEqual(len(records), 46)
        self.assertTrue(all(self.result['checks'].values()), self.result['checks'])
        self.assertEqual({r['block'] for r in records}, {'pfb', 'stft', 'ofdm', 'omlsa'})
        for row in records:
            self.assertTrue(p.geometry_valid(row))
            self.assertTrue(all(p.metric_valid(m) for m in row['metrics'].values()))
            self.assertTrue(p.record_quality_matches(row))
        self.assertEqual(sum(r['fixture'] == 'clipping' for r in records), 12)

    def test_quality_failures_remain_visible_on_measurement_pass(self):
        edge = self.find('stft', 256, 'impulse')
        sparse = self.find('ofdm', 1024, 'tones')
        self.assertFalse(edge['quality_budget_met'])
        self.assertFalse(edge['quality']['analysis_loaded']['budget_met'])
        self.assertLess(edge['metrics']['analysis_loaded']['sqnr_db'], 30)
        self.assertFalse(sparse['quality_budget_met'])
        self.assertFalse(sparse['quality']['rx_loaded']['budget_met'])
        self.assertLess(sparse['metrics']['rx_loaded']['sqnr_db'], 35)
        self.assertTrue(all(self.result['checks'].values()))
        noisy = self.find('ofdm', 64, 'noise')
        self.assertFalse(noisy['quality']['roundtrip_source']['budget_met'])
        self.assertTrue(noisy['quality']['rx_loaded']['budget_met'])
        self.assertGreater(noisy['input']['noise_power'], 0)

    def test_missing_duplicate_geometry_and_quality_poison_fail(self):
        records = self.result['records']
        for broken in (records[:-1], records + [records[0]]):
            self.assertFalse(all(p.check_records(broken).values()))
        broken = copy.deepcopy(records)
        row = next(r for r in broken if r['block'] == 'stft' and r['fixture'] == 'tones')
        row['geometry']['frame_starts'][1] += 1
        self.assertFalse(all(p.check_records(broken).values()))
        broken = copy.deepcopy(records)
        row = next(r for r in broken if r['block'] == 'ofdm' and r['parameters']['n'] == 1024 and r['fixture'] == 'tones')
        row['quality']['rx_loaded']['budget_met'] = True
        row['quality_budget_met'] = True
        self.assertFalse(all(p.check_records(broken).values()))
        broken = copy.deepcopy(records)
        broken[0]['metrics']['loaded']['samples'] += 1
        self.assertFalse(all(p.check_records(broken).values()))

    def test_metric_denominators_and_zero_signal_are_explicit(self):
        zero = p.metric([1, 2], [0, 0])
        self.assertFalse(zero['defined'])
        self.assertIsNone(zero['sqnr_db'])
        self.assertIsNone(zero['normalized_rms_evm'])
        self.assertTrue(p.metric_valid(zero))
        exact = p.metric([1j, 2], [1j, 2])
        self.assertTrue(exact['exact_match'])
        self.assertIsNone(exact['sqnr_db'])
        rotated = p.metric([1j, 2j], [1, 2])
        self.assertAlmostEqual(rotated['sqnr_db'], -10 * np.log10(2))
        self.assertEqual(rotated['max_error'], 2 * np.sqrt(2))
        bad = p.metric([1, 2], [2, 3])
        bad['sqnr_db'] = 100
        self.assertFalse(p.metric_valid(bad))
        bad['error_power'] = float('nan')
        self.assertFalse(p.metric_valid(bad))
        with self.assertRaises(ValueError):
            p.metric([1], [1, 2])
        with self.assertRaises(ValueError):
            p.metric([float('nan')], [1])

    def test_pfb_causal_time_and_phase_reindex_analytic(self):
        # At end=3 only tap3 has a sample: phase3 -> reindexed bin0.
        wave = np.array([1 + 2j, 0, 0, 0, 0, 0, 0])
        taps = np.array([0, 0, 0, .5, 0, 0, 0])
        result = p.pfb_float(wave, taps, 4, 3).reshape(-1, 4)
        np.testing.assert_allclose(result[0], 0, atol=1e-15)
        np.testing.assert_allclose(result[1], (1 + 2j) / 8, atol=1e-15)
        np.testing.assert_allclose(result[2], 0, atol=1e-15)
        # end=2/tap2 also maps its nonzero phase to bin0, with no fitted rotation.
        taps[2], taps[3] = .25, 0
        result = p.pfb_float(wave, taps, 4, 2).reshape(-1, 4)
        np.testing.assert_allclose(result[1], (1 + 2j) / 16, atol=1e-15)

    def test_stft_native_scaling_no_tail_pad_and_loaded_reciprocal(self):
        n, hop = 4, 1
        window = np.array([.25, .5, .75, 1.])
        wave = np.arange(8) + 1j * np.arange(8)[::-1]
        spectrum = p.stft_float(wave, n, hop, window)
        self.assertEqual(spectrum.shape, (5, 4))
        np.testing.assert_allclose(spectrum[0], np.fft.fft(wave[:n] * window) / n)
        # This arbitrary loaded LUT deliberately differs from 1/sum(window**2).
        reciprocals = np.full((hop, 16), 2.)
        one_frame = p.synthesis_float(spectrum[:1], n, hop, window, reciprocals)
        np.testing.assert_allclose(one_frame, wave[:n] * window**2 * 2)
        ideal = p.synthesis_float(spectrum[:1], n, hop, window)
        np.testing.assert_allclose(ideal, wave[:n])
        row = self.find('stft', 32, 'tones')
        self.assertEqual(row['geometry']['dropped_input_tail'], 7)
        self.assertEqual(row['geometry']['frame_starts'], list(range(0, 120, 8)))
        self.assertEqual(row['geometry']['interior_indices'], [24, 120])
        self.assertEqual(row['metrics']['interior_roundtrip_loaded']['samples'], 96)

    def test_floating_references_never_call_fixed_transforms_or_states(self):
        forbidden = AssertionError('Fixed arithmetic reused in float reference')
        words, _ = p.stimulus('tones', 80, p.SEED)
        wave = p.complex_of(words)
        window = np.asarray(p.stft.window(16)) / 2**17
        with patch.object(p.pfb, 'analyze', side_effect=forbidden), \
             patch.object(p.stft, 'analyze', side_effect=forbidden), \
             patch.object(p.stft, 'synthesize', side_effect=forbidden), \
             patch.object(p.fft, 'forward', side_effect=forbidden), \
             patch.object(p.fft, 'inverse', side_effect=forbidden), \
             patch.object(p.omlsa, 'enhance', side_effect=forbidden):
            self.assertEqual(len(p.pfb_float(wave, [.25, .5, .25], 4, 2)), 160)
            spectrum = p.stft_float(wave, 16, 4, window)
            np.testing.assert_allclose(p.synthesis_float(spectrum, 16, 4, window), wave, atol=1e-14)
            enhanced = p.omlsa_float(wave, 16, 4, 3, .92)
            self.assertEqual(len(enhanced), len(wave))
            self.assertTrue(np.all(np.isfinite(enhanced)))

    def test_ofdm_shared_quantization_cp_and_native_gain(self):
        original = p.quantize
        tx_original = p.ofdm.transmit
        tx_wave = []
        quantizer_input = []
        def capture_tx(*args, **kwargs):
            words = tx_original(*args, **kwargs)
            tx_wave.append(p.complex_of(words))
            return words
        def capture_quantize(wave, *args, **kwargs):
            quantizer_input.append(np.asarray(wave).copy())
            return original(wave, *args, **kwargs)
        with patch.object(p.ofdm, 'transmit', side_effect=capture_tx), \
             patch.object(p, 'quantize', side_effect=capture_quantize) as quantizer:
            row = p.ofdm_case(32, 8, 'tones')
        self.assertEqual(quantizer.call_count, 1)
        np.testing.assert_array_equal(quantizer_input[0], tx_wave[0])
        frames = tx_wave[0].reshape(4, 40)
        np.testing.assert_array_equal(frames[:, :8], frames[:, -8:])
        self.assertEqual(row['parameters']['shift_tx'], 18)
        self.assertEqual(row['parameters']['shift_rx'], 13)
        self.assertEqual(row['metrics']['tx_loaded']['samples'], 160)
        self.assertEqual(row['metrics']['rx_loaded']['samples'], 128)
        self.assertNotIn('ser', row['metrics'])

    def test_clipping_controls_cannot_be_removed(self):
        broken = copy.deepcopy(self.result['records'])
        row = next(r for r in broken if r['block'] == 'pfb' and r['fixture'] == 'clipping')
        row['clipping']['outer'] = row['clipping']['embedded'] = 0
        self.assertFalse(all(p.check_records(broken).values()))
        broken = copy.deepcopy(self.result['records'])
        row = next(r for r in broken if r['block'] == 'omlsa' and r['fixture'] == 'clipping')
        row['clipping']['numeric_ratio_caps'] = 0
        self.assertFalse(all(p.check_records(broken).values()))

    def test_nested_fft_observer_preserves_model_and_restores_on_error(self):
        forward, inverse = p.fft.forward, p.fft.inverse
        words = [(100, 200), (-300, 400), (500, -600), (700, 800)]
        expected = forward(words)
        stats = p.SatTrace()
        with p.trace_fft(stats):
            self.assertEqual(p.fft.forward(words), expected)
        self.assertIs(p.fft.forward, forward)
        self.assertIs(p.fft.inverse, inverse)
        with self.assertRaises(RuntimeError):
            with p.trace_fft(stats):
                raise RuntimeError('test unwind')
        self.assertIs(p.fft.forward, forward)
        self.assertIs(p.fft.inverse, inverse)

    def test_failure_writes_fail_and_raises(self):
        broken = copy.deepcopy(self.result)
        broken['checks']['forced_failure'] = False
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'result.json'
            with patch.object(p, 'report', return_value=broken), self.assertRaises(RuntimeError):
                p.main(['--output', str(target)])
            self.assertEqual(json.loads(target.read_text())['status'], 'FAIL')

    def test_cli_fresh_evidence_and_optimization_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'result.json'
            command = [sys.executable, str(ROOT / 'tools/spectral_precision.py'), '--output', str(target)]
            run = subprocess.run(command, capture_output=True, text=True, timeout=30)
            self.assertEqual(run.returncode, 0, run.stderr)
            evidence = json.loads(target.read_text())
            self.assertEqual(evidence['status'], 'PASS')
            self.assertFalse(evidence['rtl_verified'])
            require_pass(evidence, ROOT)
            self.assertIn('tools/spectral_precision.py', evidence['source_hashes'])
            self.assertIn('tests/test_spectral_precision.py', evidence['source_hashes'])
            stale = copy.deepcopy(evidence)
            stale['source_hashes']['tools/spectral_precision.py'] = '0' * 64
            with self.assertRaises(RuntimeError):
                require_pass(stale, ROOT)
            run = subprocess.run([sys.executable, '-O', *command[1:]], capture_output=True, text=True, timeout=30)
            self.assertNotEqual(run.returncode, 0)
            self.assertEqual(json.loads(target.read_text())['status'], 'FAIL')


if __name__ == '__main__':
    unittest.main()
