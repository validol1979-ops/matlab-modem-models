"""Independent targeted tests for common/python/ext_advanced_radar.py."""
import math
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common' / 'python'))
import ext_advanced_radar as radar  # noqa: E402


def direct_dft(values):
    n = len(values)
    return np.array([
        sum(values[t] * np.exp(-2j * np.pi * k * t / n) for t in range(n)) / n
        for k in range(n)
    ])


def qround(num, den):
    return (2 * num + den) // (2 * den)


class ChirpTests(unittest.TestCase):
    def test_dds_constant_frequency_dependency(self):
        from ext_signal_core import DDS
        step=round(.125*2**32);dds=DDS(step,lut_bits=12)
        expected=np.array([dds.next() for _ in range(64)])
        got=np.array(radar.chirp_fixed(64,1,.125,0,lut_bits=12))
        self.assertLessEqual(np.max(abs(got-expected)),2)

    def test_float_formula_phase_frequency_and_sweeps(self):
        n, fs, f0, slope, amp, phase = 257, 1000.0, -20.0, 30.0, 0.7, 0.31
        y = radar.chirp(n, fs, f0, slope, amp, phase)
        t = np.arange(n) / fs
        oracle = amp * np.exp(1j * (phase + 2 * np.pi * (f0 * t + 0.5 * slope * t * t)))
        np.testing.assert_allclose(y, oracle, rtol=0, atol=2e-15)
        self.assertAlmostEqual(abs(y[0]), amp)
        self.assertAlmostEqual(np.angle(y[0]), phase)
        inst = np.angle(y[1:] * np.conj(y[:-1])) * fs / (2 * np.pi)
        expected = f0 + slope * (np.arange(n - 1) + 0.5) / fs
        np.testing.assert_allclose(inst, expected, atol=2e-12)
        down = radar.chirp(64, 1024.0, 0.0, -80.0)
        down_freq = np.angle(down[1:] * np.conj(down[:-1])) * 1024.0 / (2 * np.pi)
        self.assertTrue(np.all(down_freq < 0))
        flat = radar.chirp(16, 800.0, 0.0, 0.0)
        np.testing.assert_allclose(flat, np.ones(16))

    def test_chirp_validation(self):
        for args in [(0, 1, 0, 0), (4097, 1, 0, 0), (True, 1, 0, 0),
                     (4, 0, 0, 0), (4, 1, 0, 0, 1.1), (4, 1, 0.5, 0),
                     (4, 1, 0, 2), (4, 1, 0, float('nan'))]:
            with self.assertRaises(ValueError):
                radar.chirp(*args)
        # Nyquist boundary is rejected, not silently accepted.
        with self.assertRaises(ValueError):
            radar.chirp(2, 1.0, 0.5, 0)

    def test_fixed_accumulator_matches_integer_recurrence(self):
        n, fs, f0, slope, amp, phase = 73, 4096.0, -80.0, 20.0, 1.0, 0.2
        out = radar.chirp_fixed(n, fs, f0, slope, amp, phase, lut_bits=12)
        init = math.floor(phase / (2 * math.pi) * (1 << 32) + 0.5)
        step = math.floor((f0 / fs + slope / (2 * fs * fs)) * (1 << 32) + 0.5)
        delta = math.floor(slope / fs ** 2 * (1 << 32) + 0.5)
        iphase, istep = init & 0xffffffff, step
        def half_up(v):
            return math.floor(v + 0.5)
        for sample in out:
            index = iphase >> 20
            expected = (max(-131072, min(131071, half_up(math.cos(2 * math.pi * index / 4096) * 131072))),
                        max(-131072, min(131071, half_up(math.sin(2 * math.pi * index / 4096) * 131072))))
            self.assertEqual(sample, expected)
            iphase = (iphase + istep) & 0xffffffff
            istep += delta
        self.assertEqual(iphase, (init + n * step + (n * (n - 1) // 2) * delta) & 0xffffffff)
        # The phase increment itself follows the exact integer step recurrence.
        fixed_samples = np.array([a + 1j * b for a, b in out]) / 131072
        float_y = radar.chirp(n, fs, f0, slope, amp, phase)
        self.assertLess(np.max(np.abs(fixed_samples - float_y)), 4e-3)


class EchoTests(unittest.TestCase):
    def test_absolute_doppler_time_and_default_length(self):
        s = np.array([1, 2, 3, 4], dtype=complex)
        y = radar.echo(s, [2], [0.5 + 0.25j], [0.25])
        self.assertEqual(len(y), 6)
        n = np.arange(6)
        oracle = np.where(n >= 2, (0.5 + 0.25j) * np.r_[np.zeros(2), s] * np.exp(2j * np.pi * 0.25 * n), 0)
        np.testing.assert_allclose(y, oracle)
        # A local-time (n-delay) Doppler would differ at the tail.
        self.assertGreater(abs(y[5] - (0.5 + 0.25j) * 4 * np.exp(2j * np.pi * .25 * 3)), 1e-3)
        self.assertEqual(len(radar.echo(s, [1, 5], [1, 1], [0, 0], length=3)), 3)

    def test_echo_validation(self):
        s = np.ones(3, complex)
        for delays, gains, dop in [([-1], [1], [0]), ([0], [1], [.5]),
                                   ([0], [np.nan], [0]), ([0], [1], [0, 0])]:
            with self.assertRaises(ValueError):
                radar.echo(s, delays, gains, dop)

    def test_fixed_echo_saturation_at_rails(self):
        wave = [(131071, 131071)]
        got = radar.echo_fixed(wave, [0, 0], [(131071, 131071), (131071, 131071)],
                               [0, 0], length=1)
        # (1+j)*(1+j) is purely imaginary; two coherent targets saturate that axis.
        self.assertEqual(got, [(0, 131071)])

    def test_fixed_echo_integer_oracle(self):
        wave = [(1000, -2000), (3000, 4000)]
        got = radar.echo_fixed(wave, [1], [(2000, -1000)], [32768], length=3)
        def sat(v):
            return max(-131072, min(131071, math.floor(v + 0.5)))
        lut = [(sat(math.cos(2 * math.pi * k / 131072) * 131072),
                sat(math.sin(2 * math.pi * k / 131072) * 131072)) for k in range(131072)]
        oracle = []
        for n in range(3):
            if n < 1:
                oracle.append((0, 0)); continue
            re, im = wave[n - 1]
            gr, gi = 2000, -1000
            br, bi = re * gr - im * gi, re * gi + im * gr
            lr, li = lut[(n * 32768) & 131071]
            rr, ri = br * lr - bi * li, br * li + bi * lr
            oracle.append((qround(rr, 1 << 34), qround(ri, 1 << 34)))
        self.assertEqual(got, oracle)


class PulseCompressionTests(unittest.TestCase):
    def test_direct_fft_full_tail_and_peak(self):
        ref = radar.chirp(37, 500.0, -30.0, 25.0)
        x = np.r_[np.zeros(5), ref, np.zeros(9)]
        for method in ('direct', 'fft'):
            y = radar.pulse_compress(x, ref, method=method)
            self.assertEqual(len(y), len(x) + len(ref) - 1)
            peak = 5 + len(ref) - 1
            self.assertEqual(int(np.argmax(np.abs(y))), peak)
            self.assertAlmostEqual(y[peak].real, 1.0, places=12)
            # Full linear tail is present (no circular wrap); compare with independent sum.
            tail = 5 + len(ref) - 1 + 3
            independent = sum(x[i] * np.conj(ref[len(ref) - 1 - (tail - i)])
                              for i in range(max(0, tail - len(ref) + 1), tail + 1)) / np.sum(np.abs(ref) ** 2)
            self.assertAlmostEqual(y[tail].real, independent.real, places=11)
            self.assertAlmostEqual(y[tail].imag, independent.imag, places=11)
        np.testing.assert_allclose(radar.pulse_compress(x, ref, 'direct'),
                                   radar.pulse_compress(x, ref, 'fft'), atol=1e-12)
        self.assertEqual(radar.pulse_compress([], ref).size, 0)
        with self.assertRaises(ValueError):
            radar.pulse_compress(x, np.zeros(4))
        with self.assertRaises(ValueError):
            radar.pulse_compress(x, ref, method='circular')

    def test_fixed_exact_oracle_and_conjugate_edge(self):
        x = [(3, -2), (5, 7), (-11, 13)]
        ref = [(-131072, 131071), (7, -9)]
        got = radar.pulse_compress_fixed(x, ref)
        h = [(r, -i) for r, i in reversed(ref)]
        energy = sum(r * r + i * i for r, i in ref)
        oracle = []
        for k in range(len(x) + len(h) - 1):
            rr = ri = 0
            for i in range(max(0, k - len(h) + 1), min(len(x) - 1, k) + 1):
                a, b = x[i]; c, d = h[k - i]
                rr += a * c - b * d
                ri += a * d + b * c
            oracle.append((max(-131072, min(131071, qround(rr * 131072, energy))),
                           max(-131072, min(131071, qround(ri * 131072, energy)))))
        self.assertEqual(got, oracle)
        raw = radar.pulse_compress_fixed(x, ref, normalize=False)
        # At lag zero h[0] is conj(ref[-1]); this checks the raw (un-normalized) scale.
        first_raw_re = 3 * 7 - (-2) * 9
        first_raw_im = 3 * 9 + (-2) * 7
        self.assertEqual(raw[0], (qround(first_raw_re, 131072), qround(first_raw_im, 131072)))
        # The -2**17 reference corner is conjugated intentionally, not overflowed.
        self.assertIn(131072, [abs(ref[0][0])])

    def test_fixed_normalize_zero_energy(self):
        with self.assertRaises(ValueError):
            radar.pulse_compress_fixed([(1, 1)], [(0, 0)])
        self.assertEqual(radar.pulse_compress_fixed([], [(-131072, -131072)]), [])


class RangeDopplerTests(unittest.TestCase):
    def test_all_lengths_mti_windows_against_direct_dft(self):
        rng = np.random.default_rng(4)
        for npulse in (16, 32, 64):
            data = rng.normal(size=(3, npulse)) + 1j * rng.normal(size=(3, npulse))
            for mti in (0, 1, 2):
                for window in ('hamming', 'rectangular'):
                    got, hz = radar.range_doppler(data, 1 / 800.0, mti, window)
                    nvalid = npulse - mti
                    coeff = np.hamming(nvalid) if window == 'hamming' else np.ones(nvalid)
                    for row in range(3):
                        valid = np.diff(data[row], n=mti) if mti else data[row]
                        dft = direct_dft(np.r_[valid * coeff, np.zeros(mti)])
                        np.testing.assert_allclose(np.fft.fftshift(dft), got[row], atol=1e-12)
                    np.testing.assert_allclose(hz, np.fft.fftshift(np.fft.fftfreq(npulse, 1 / 800.0)))

    def test_stationary_clutter_removed_by_mti(self):
        rng = np.random.default_rng(8)
        npulse = 32
        clutter = np.ones((1, npulse))
        moving = np.exp(2j * np.pi * 0.125 * np.arange(npulse))[None, :]
        data = clutter + 0.1 * moving + 0.001 * (rng.normal(size=(1, npulse)) + 1j * rng.normal(size=(1, npulse)))
        spec, _ = radar.range_doppler(data, 1e-3, mti=1, window='rectangular')
        self.assertLess(abs(spec[0, npulse // 2]), 0.05)
        # Positive Doppler appears in the upper half after fftshift.
        self.assertEqual(int(np.argmax(np.abs(spec[0, npulse // 2:]))), 4)

    def test_fixed_against_float_and_direct_dft(self):
        rng = np.random.default_rng(11)
        for npulse in (16, 32, 64):
            data = rng.integers(-2000, 2001, size=(2, npulse, 2))
            for mti in (0, 1, 2):
                for window in ('hamming', 'rectangular'):
                    fixed, hz = radar.range_doppler_fixed(data, 1 / 500.0, mti, window)
                    floating, hz2 = radar.range_doppler(
                        data[:, :, 0] + 1j * data[:, :, 1], 1 / 500.0, mti, window)
                    np.testing.assert_allclose(hz, hz2)
                    got = fixed[:, :, 0] + 1j * fixed[:, :, 1]
                    # Integers already carry Q17 scale; fixed FFT/N is directly comparable.
                    self.assertLess(np.max(np.abs(got - floating)), 15.0)

    def test_parameters_and_invalid_pri(self):
        data = np.zeros((1, 16))
        for pri in (0, -1, float('inf'), float('nan')):
            with self.assertRaises(ValueError):
                radar.range_doppler(data, pri)
        with self.assertRaises(ValueError):
            radar.range_doppler(np.zeros((1, 15)), 1)
        with self.assertRaises(ValueError):
            radar.range_doppler(np.zeros((1, 16)), 1, mti=16)
        with self.assertRaises(ValueError):
            radar.range_doppler_fixed(np.zeros((1, 16, 2)), 1, window='blackman')


class CFARTests(unittest.TestCase):
    def test_independent_ca_oracle_and_edges(self):
        rng = np.random.default_rng(3)
        power = rng.exponential(size=(2, 41))
        T, G, pfa = 8, 2, 1e-2
        det, thr, valid = radar.ca_cfar(power, T, G, pfa)
        alpha = T * math.expm1(-math.log(pfa) / T)
        half = T // 2
        edge = half + G
        self.assertFalse(valid[:, :edge].any() or valid[:, -edge:].any())
        self.assertTrue(np.isnan(thr[~valid]).all())
        for row in range(2):
            for cut in range(edge, 41 - edge):
                cells = list(range(cut - G - half, cut - G)) + list(range(cut + G + 1, cut + G + 1 + half))
                noise = sum(power[row, c] for c in cells) / T
                self.assertAlmostEqual(thr[row, cut], alpha * noise)
                self.assertEqual(det[row, cut], power[row, cut] > thr[row, cut])

    def test_fixed_exact_rational_selected_windows(self):
        rng = np.random.default_rng(19)
        power = rng.integers(0, 100000, size=(3, 30))
        T, G, pfa, frac = 16, 2, 1e-3, 20
        det, thr, valid = radar.ca_cfar_fixed(power, T, G, pfa, frac)
        # Independent alpha from the exponential-noise derivation.
        alpha = T * math.expm1(-math.log(pfa) / T)
        alpha_q = math.floor(alpha * (1 << frac) + 0.5)
        half, edge = T // 2, T // 2 + G
        for row in range(3):
            for cut in range(edge, 30 - edge):
                cells = list(range(cut - G - half, cut - G)) + list(range(cut + G + 1, cut + G + 1 + half))
                total = sum(int(power[row, c]) for c in cells)
                expected_det = int(power[row, cut]) * T * (1 << frac) > alpha_q * total
                expected_thr = -((-alpha_q * total) // (T * (1 << frac)))
                self.assertEqual(det[row, cut], expected_det)
                self.assertEqual(thr[row, cut], expected_thr)
                self.assertGreaterEqual(expected_thr, alpha_q * total / (T * (1 << frac)))
                self.assertLess(expected_thr - alpha_q * total / (T * (1 << frac)), 1)

    def test_target_plus_noise_and_guard_exclusion(self):
        rng = np.random.default_rng(13)
        noise = rng.exponential(size=(1, 41))
        power = noise.copy()
        power[0, 20] = 50.0
        det, thr, valid = radar.ca_cfar(power, 16, 2, 1e-3)
        self.assertTrue(valid[0, 20])
        self.assertTrue(det[0, 20])
        # A high CUT inside the guard ring must not raise the CUT's own threshold.
        before = thr[0, 19].copy()
        power[0, 20] = 1e9
        det2, thr2, _ = radar.ca_cfar(power, 16, 2, 1e-3)
        self.assertAlmostEqual(before, thr2[0, 19], places=5)
        self.assertTrue(valid[0, 20])

    def test_false_fixed_threshold_is_not_scale_invariant(self):
        rng = np.random.default_rng(21)
        x = rng.exponential(size=500) + 0.6
        fixed_hits = int(np.sum(x > 2.0))
        fixed_hits_scaled = int(np.sum(10 * x > 2.0))
        self.assertGreater(fixed_hits_scaled, fixed_hits)
        det1, _, _ = radar.ca_cfar(x, 16, 2, 1e-2)
        det2, _, _ = radar.ca_cfar(10 * x, 16, 2, 1e-2)
        np.testing.assert_array_equal(det1, det2)

    def test_validation_and_empty(self):
        for args in [(15, 2, 1e-3), (66, 2, 1e-3), (16, -1, 1e-3), (16, 9, 1e-3),
                     (16, 2, 0), (16, 2, 1), (16, 2, float('nan'))]:
            with self.assertRaises(ValueError):
                radar.ca_cfar(np.ones(40), *args)
        with self.assertRaises(ValueError):
            radar.ca_cfar(np.array([1.0, -1.0]), 4, 0, .1)
        with self.assertRaises(ValueError):
            radar.ca_cfar_fixed(np.array([True, False]), 2, 0, .1)
        det, thr, valid = radar.ca_cfar_fixed(np.zeros((2, 0), dtype=int), 4, 1, .1)
        self.assertEqual(det.shape, (2, 0))
        self.assertEqual(thr.shape, (2, 0))
        self.assertEqual(valid.shape, (2, 0))

    def test_monte_carlo_pfa_100k_windows_each_profile(self):
        from scipy.stats import binom
        rng = np.random.default_rng(2026)
        M = 100_001
        for training in (16, 32):
            for guard in (1, 2, 4):
                for pfa in (1e-2, 1e-3):
                    edge = training // 2 + guard
                    width = 2 * edge + 1
                    # Independent windows: one CUT and disjoint training cells per row.
                    noise = rng.exponential(size=(M, width))
                    cut = noise[:, edge]
                    cells = np.r_[0:edge - guard, edge + guard + 1:width]
                    total = noise[:, cells].sum(axis=1)
                    alpha = training * math.expm1(-math.log(pfa) / training)
                    independent = cut > alpha * total / training
                    actual,threshold,valid=radar.ca_cfar(noise,training,guard,pfa)
                    detections=actual[:,edge]
                    np.testing.assert_array_equal(detections,independent)
                    self.assertTrue(valid[:,edge].all())
                    count = int(detections.sum())
                    lo, hi = binom.interval(0.999, M, pfa)
                    self.assertGreaterEqual(count, int(lo),
                                            msg=f'T={training} G={guard} pfa={pfa}: {count}')
                    self.assertLessEqual(count, int(hi),
                                         msg=f'T={training} G={guard} pfa={pfa}: {count}')


if __name__ == '__main__':
    unittest.main()
