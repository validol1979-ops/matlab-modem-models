"""Independent contract tests for the CIC-compensation and rational models.

Run from this directory with:  python -m unittest -v test_filter_models
The production modules are imported lazily inside the tests; their arithmetic is
never used to derive an expected value.
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from fractions import Fraction

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
MODEL_DIR = os.path.join(ROOT, "common", "python")
for _path in (ROOT, MODEL_DIR):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import filter_references as ref  # noqa: E402


def comp():
    import cic_compensation
    return cic_compensation


def rat():
    import rational_model
    return rational_model


def collect_push(model, samples):
    out = []
    for s in samples:
        out.extend(model.push(s))
    return out


def as_pairs(seq):
    return [tuple(p) for p in seq]


def cplx_close(test, got, expected, tol=1e-11):
    got = np.asarray(got, dtype=complex)
    expected = np.asarray(expected, dtype=complex)
    test.assertEqual(got.shape, expected.shape)
    test.assertLessEqual(float(np.max(np.abs(got - expected), initial=0.0)), tol)


class TestCicCompensation(unittest.TestCase):
    def test_cic_response_matches_finite_boxcar_dtft(self):
        for R, N, M in [(1, 1, 1), (4, 3, 1), (10, 5, 2), (32, 3, 1)]:
            box = np.ones(R * M)
            poly = np.ones(1)
            for _ in range(N):
                poly = np.convolve(poly, box)
            for f in [0.0, 0.031, 0.16, 0.32, 0.5]:
                k = np.arange(poly.size)
                mag = abs(np.sum(poly * np.exp(-2j * np.pi * (f / R) * k)) /
                          (R * M) ** N)
                got = comp().cic_response(f, R, N, M)
                self.assertAlmostEqual(float(got), float(mag), places=13)

    def test_cic_response_shape_dc_and_zero(self):
        mod = comp()
        x = np.array([0.0, 0.1, 0.5])
        y = mod.cic_response(x, 4, 3, 1)
        self.assertIsInstance(y, np.ndarray)
        self.assertEqual(y.shape, x.shape)
        self.assertAlmostEqual(float(mod.cic_response(0.0, 10, 5, 2)), 1.0, places=15)
        self.assertLess(abs(float(mod.cic_response(0.5, 4, 3, 2))), 1e-12)
        self.assertAlmostEqual(float(mod.cic_response(0.23, 7, 2, 2)),
                               float(ref.cic_response(0.23, 7, 2, 2)), places=14)

    def test_cic_response_rejects_bad_parameters(self):
        mod = comp()
        for args in [(0.1, 0), (0.1, 33), (0.1, 4, 0), (0.1, 4, 6),
                     (0.1, 4, 3, 0), (0.1, 4, 3, 3), (0.6, 4), (float("nan"), 4),
                     (0.1, True), (0.1, 4, 3.0), (0.1, 4, 3, 1.0)]:
            with self.assertRaises((TypeError, ValueError), msg=repr(args)):
                mod.cic_response(*args)

    def test_design_response_dc_symmetry_and_objective(self):
        # The production LS samples each band separately, so do not compare
        # coefficients to a full 0..0.5-grid oracle.  Instead evaluate the
        # returned filter independently with scipy.signal.freqz and check the
        # contract properties plus the weighted LS objective.
        from scipy.signal import freqz
        mod = comp()
        pb, sb, weight = .16, .32, 10.0
        fpb = np.linspace(0.0, pb, 512)
        fsb = np.linspace(sb, 0.5, 512)
        f = np.concatenate([fpb, fsb])
        w = np.concatenate([np.full(fpb.size, weight), np.ones(fsb.size)])
        for R, N, L in [(4, 3, 31), (10, 5, 63), (32, 3, 31)]:
            h = np.asarray(mod.design(R, N, 1, L, pb, sb, 512, weight))
            self.assertEqual(h.shape, (L,))
            self.assertTrue(np.all(np.isfinite(h)))
            np.testing.assert_allclose(h, h[::-1], rtol=0.0, atol=1e-13)
            self.assertAlmostEqual(float(np.sum(h)), 1.0, places=13)
            _, H = freqz(h, worN=2.0 * np.pi * f)
            # Symmetric h has linear phase exp(-j*w*m); remove it to compare
            # the real zero-phase amplitude response.
            H = (H * np.exp(1j * 2.0 * np.pi * f * ((L - 1) // 2))).real
            desired = np.concatenate([1.0 / ref.cic_response(fpb, R, N, 1),
                                      np.zeros(fsb.size)])
            # DC is exact by the h[m] = 1 - 2 sum(c) construction.
            self.assertAlmostEqual(float(H[0]), 1.0, places=12)
            # Passband tracks the inverse CIC; stopband is strongly attenuated.
            self.assertLessEqual(float(np.max(np.abs(H[:fpb.size] -
                                                  desired[:fpb.size]))), 2e-3)
            self.assertLessEqual(float(np.max(np.abs(H[fpb.size:]))), 2e-3)
            # Weighted LS residual must be far below that of the trivial
            # unit-impulse (delta) filter, independently evaluated here.
            residual = w * (H - desired)
            residual_delta = w * (1.0 - desired)
            self.assertLessEqual(float(residual @ residual),
                                 1e-5 * float(residual_delta @ residual_delta))

    def test_design_validation(self):
        mod = comp()
        bad = [
            dict(rate=0), dict(rate=4, stages=0), dict(rate=4, delay=3),
            dict(rate=4, numtaps=30), dict(rate=4, numtaps=129),
            dict(rate=4, passband=0.0), dict(rate=4, passband=.3, stopband=.3),
            dict(rate=4, stopband=.5), dict(rate=4, grid=10),
            dict(rate=4, grid=9000), dict(rate=4, pass_weight=0.0),
            dict(rate=4, pass_weight=float("nan")), dict(rate=True),
        ]
        for kw in bad:
            with self.assertRaises((TypeError, ValueError), msg=repr(kw)):
                mod.design(**kw)

    def test_quantize_reference_and_export_contract(self):
        mod = comp()
        h = mod.design(10, 5, 1, 63, .16, .32, 512, 10.0)
        got = mod.quantize(h)
        expected = ref.quantize_q17_reference(h)
        self.assertEqual(got, expected)
        q = [int(v) for v, _ in got]
        self.assertEqual(sum(q), 131072)
        self.assertEqual(q, q[::-1])
        self.assertTrue(all(-131072 <= v <= 131071 for v in q))
        self.assertTrue(all(frac == 0 for _, frac in got))
        with self.assertRaises(ValueError):
            mod.quantize([0.1, 0.2, 0.3])
        with self.assertRaises(ValueError):
            mod.quantize([0.1, float("nan"), 0.1])
        with self.assertRaises(ValueError):
            mod.quantize([])
        with self.assertRaises((ValueError, OverflowError)):
            mod.quantize([2.0, 2.0, 2.0])

    def test_metrics_match_direct_dtft(self):
        mod = comp()
        h = mod.design(10, 3, 1, 31)
        got = mod.metrics(h, 10)
        exp = ref.metrics_reference(h, 10)
        self.assertEqual(set(got), set(exp))
        for k in exp:
            self.assertAlmostEqual(float(got[k]), float(exp[k]), places=10,
                                   msg=k)

    def test_frozen_quality_matrix_float_and_quantized(self):
        mod = comp()
        for R in (4, 10, 32):
            for N in (3, 5):
                for L in (31, 63):
                    h = mod.design(R, N, 1, L, .16, .32, 512, 10.0)
                    q = mod.quantize(h)
                    fixed = np.array([v for v, _ in q], dtype=float) / 131072.0
                    for taps, quantized in ((h, False), (fixed, True)):
                        m = mod.metrics(taps, R, N, 1, .16, .32, 8193)
                        self.assertLessEqual(m["passband_ripple_db"], .05, (R, N, L))
                        self.assertLessEqual(m["passband_max_error_db"], .05, (R, N, L))
                        self.assertLessEqual(m["fir_stopband_db"], -50.0, (R, N, L))
                        self.assertGreaterEqual(m["cascade_stopband_db"], -300.0)
                        if quantized:
                            self.assertEqual(sum(v for v, _ in q), 131072)
                        else:
                            self.assertAlmostEqual(m["dc_gain"], 1.0, places=12)

    def test_cascade_existing_models_against_exact_convolution(self):
        mod = comp()
        taps = ref.quantize_q17_reference(
            mod.design(4, 2, 1, 7, .16, .32, 512, 10.0))
        samples = [(4, -8), (6, 2), (-2, 10), (0, 4),
                   (8, -6), (2, 0), (-4, 12), (10, -2)]
        got = as_pairs(mod.cascade_fixed(samples, 2, 2, taps, 1))
        exp = ref.cascade_reference(samples, 2, 2, taps, 1)
        self.assertEqual(got, exp)
        self.assertEqual(mod.cascade_fixed([], 2, 2, taps, 1), [])
        with self.assertRaises((TypeError, ValueError)):
            mod.cascade_fixed([(1, 2)], 2, 2, taps, 1)
        with self.assertRaises((TypeError, ValueError)):
            mod.cascade_fixed([True, (1, 2)], 2, 2, taps, 1)
        with self.assertRaises((TypeError, ValueError)):
            mod.cascade_fixed([(1, 2)], 2, 2, [(1, 0), (2, 1)], 1)
        with self.assertRaises((TypeError, ValueError)):
            mod.cascade_fixed([(1, 2)], 0, 2, taps, 1)


class TestRationalFloat(unittest.TestCase):
    def test_matrix_explicit_upsample_convolve(self):
        mod = rat()
        rng = np.random.default_rng(7)
        for P, Q in [(5, 3), (3, 5), (12, 5), (1, 2), (2, 1),
                     (1, 1), (2, 7), (1, 32), (32, 1)]:
            for L in (1, max(1, P - 1), P + 1, 17, 63):
                taps = rng.normal(size=L)
                x = rng.normal(size=5) + 1j * rng.normal(size=5)
                got = mod.resample_float(x, P, Q, taps, tail=True)
                exp = ref.rational_float_reference(x, P, Q, taps, tail=True)
                cplx_close(self, got, exp, 1e-11)
                got_nt = mod.resample_float(x, P, Q, taps, tail=False)
                exp_nt = ref.rational_float_reference(x, P, Q, taps, tail=False)
                cplx_close(self, got_nt, exp_nt, 1e-11)
                self.assertEqual(len(got), math.ceil((5 * P + L - 1) / Q))
                self.assertEqual(len(got_nt), math.ceil(5 * P / Q))

    def test_push_prefix_and_counts(self):
        mod = rat()
        taps = np.array([1., 2., -1., .5])
        m = mod.RationalFloat(5, 3, taps)
        got = []
        for n in range(1, 8):
            got.extend(m.push(complex(n, -n)))
            k = math.ceil(n * 5 / 3)
            exp = ref.rational_float_reference(
                [complex(j, -j) for j in range(1, n + 1)], 5, 3, taps, tail=False)
            cplx_close(self, got, exp[:k], 1e-11)

    def test_phase_schedule_and_properties(self):
        mod = rat()
        m = mod.RationalFloat(5, 3, [1.0])
        self.assertEqual((m.phase, m.input_index), (0, 0))
        # next_output_index is ceil(N*P/Q); the two properties must agree.
        for n in range(1, 12):
            m.push(complex(n, n))
            k = math.ceil(n * 5 / 3)
            self.assertEqual(m.phase, (k * 3) % 5)
            self.assertEqual(m.input_index, (k * 3) // 5)
        self.assertEqual(m.up, 5)
        self.assertEqual(m.down, 3)
        with self.assertRaises(AttributeError):
            m.phase = 2

    def test_flush_counts_close_and_empty(self):
        mod = rat()
        taps = [1., -2., 3., .25, 2.]
        for P, Q in [(5, 3), (3, 5), (1, 2), (2, 7), (32, 1)]:
            m = mod.RationalFloat(P, Q, taps)
            self.assertEqual(m.flush(tail=True), [])
            self.assertEqual(m.flush(tail=True), [])
            m.reset()
            for _ in range(4):
                m.push(1 + 0j)
            tail = m.flush(True)
            with self.assertRaises(Exception):
                m.push(1 + 0j)
            with self.assertRaises((TypeError, ValueError)):
                m.flush(1)
            m.reset()
            self.assertIsInstance(m.push(2 + 0j), list)
            m.flush(False)
            self.assertEqual(m.flush(False), [])

    def test_invalid_inputs_are_atomic(self):
        mod = rat()
        m = mod.RationalFloat(5, 3, [1.0, 2.0])
        before = (m.phase, m.input_index)
        # A two-element numeric sequence is the documented I/Q convenience
        # form, so it is valid, not an atomicity failure.
        for bad in [float("nan"), float("inf"), True, "x", None, [1, 2, 3]]:
            with self.assertRaises((TypeError, ValueError), msg=repr(bad)):
                m.push(bad)
            self.assertEqual((m.phase, m.input_index), before)
        for args in [(0, 3, [1.]), (5, 0, [1.]), (4, 2, [1.]),
                     (33, 1, [1.]), (True, 3, [1.]), (5, 3, []),
                     (5, 3, [1, 2 + 1j]), (5, 3, [float("nan")]),
                     (5, 3, ["x"])]:
            with self.assertRaises((TypeError, ValueError), msg=repr(args)):
                m.configure(*args)
            self.assertEqual((m.up, m.down, m.phase, m.input_index), (5, 3, *before))
        m.push(1 + 0j)
        with self.assertRaises((RuntimeError, ValueError)):
            m.configure(3, 5, [1.0])

    def test_reset_and_reconfigure_frames(self):
        mod = rat()
        taps = [1., .5, -.25]
        m = mod.RationalFloat(5, 3, taps)
        x = [1 + 2j, 3 - 1j, -2 + 0j]
        a = collect_push(m, x) + m.flush(True)
        m.reset()
        b = collect_push(m, x) + m.flush(True)
        cplx_close(self, a, b, 0.0)
        m.configure(3, 5, taps)
        self.assertEqual((m.up, m.down), (3, 5))
        c = collect_push(m, x) + m.flush(True)
        cplx_close(self, c, ref.rational_float_reference(x, 3, 5, taps), 1e-12)
        with self.assertRaises((TypeError, ValueError)):
            mod.resample_float(x, 5, 3, taps, tail="yes")
        self.assertEqual(mod.resample_float([], 5, 3, taps, tail=False), [])


class TestRationalFixed(unittest.TestCase):
    def test_fixed_exact_reference_and_saturation(self):
        mod = rat()
        cases = [
            (5, 3, [1, -2, 3, -4, 5], 17, 18, [(3, -4), (5, 6), (-7, 8)]),
            (3, 5, [131071, -131072, 17], 17, 18, [(131071, -131072)] * 3),
            (1, 32, [65536, 1], 17, 18, [(1, -1), (2, 3), (-7, 9)]),
            (32, 1, [1] * 31, 0, 8, [(100, -100), (127, -128)]),
            (2, 7, [131071], 3, 6, [(7, -8), (31, -32), (0, 1)]),
        ]
        for P, Q, taps, frac, width, samples in cases:
            got = as_pairs(mod.resample_fixed(
                samples, P, Q, taps, tail=True,
                coeff_frac=frac, output_width=width))
            exp = ref.rational_fixed_reference(
                samples, P, Q, taps, coeff_frac=frac, output_width=width, tail=True)
            self.assertEqual(got, exp, (P, Q, frac, width))
            got_nt = as_pairs(mod.resample_fixed(
                samples, P, Q, taps, tail=False,
                coeff_frac=frac, output_width=width))
            exp_nt = ref.rational_fixed_reference(
                samples, P, Q, taps, coeff_frac=frac, output_width=width, tail=False)
            self.assertEqual(got_nt, exp_nt, (P, Q, frac, width))

    def test_fixed_full_rails_and_width_validation(self):
        mod = rat()
        nmax, nmin = 131071, -131072
        rails = [(nmax, nmin), (nmin, nmax)] * 3
        got = as_pairs(mod.resample_fixed(
            rails, 5, 3, [nmax, nmin, nmax], tail=False,
            coeff_frac=17, output_width=18))
        exp = ref.rational_fixed_reference(rails, 5, 3, [nmax, nmin, nmax],
                                           coeff_frac=17, output_width=18,
                                           tail=False)
        self.assertEqual(got, exp)
        for kw in [dict(coeff_frac=-1), dict(coeff_frac=31),
                   dict(input_width=1), dict(input_width=33),
                   dict(output_width=1), dict(output_width=33)]:
            with self.assertRaises((TypeError, ValueError), msg=repr(kw)):
                mod.resample_fixed([], 5, 3, [1], **kw)
        for bad in [(131072, 0), (-131073, 0), (1,), (1, 2, 3), (True, 0),
                    (1.0, 0), ("1", 0)]:
            with self.assertRaises((TypeError, ValueError), msg=repr(bad)):
                mod.RationalFixed(5, 3, [1], input_width=18).push(bad)

    def test_fixed_push_matches_reference_prefix(self):
        mod = rat()
        taps = [1000, -2000, 3000, -4000, 5000]
        m = mod.RationalFixed(5, 3, taps, coeff_frac=17, output_width=18)
        got = []
        samples = [(100, -200), (-300, 400), (500, -600), (700, -800)]
        for i, s in enumerate(samples, 1):
            got.extend(as_pairs(m.push(s)))
            exp = ref.rational_fixed_reference(
                samples[:i], 5, 3, taps, coeff_frac=17, output_width=18,
                tail=False)
            self.assertEqual(got, exp[:math.ceil(i * 5 / 3)])

    def test_accumulator_width_exact_bound(self):
        mod = rat()
        for taps, P in [([1], 1), ([131071], 5), ([-131072], 3),
                        ([131071, -131072, 17, -3, 999], 5),
                        ([1] * 64, 32)]:
            self.assertEqual(mod.accumulator_width(taps, P),
                             ref.accumulator_width_reference(taps, P), (taps, P))
        with self.assertRaises((TypeError, ValueError)):
            mod.accumulator_width([1], 0)
        with self.assertRaises((TypeError, ValueError)):
            mod.accumulator_width([1.5], 2)
        with self.assertRaises((TypeError, ValueError)):
            mod.accumulator_width([131072], 2)


if __name__ == "__main__":
    unittest.main()
