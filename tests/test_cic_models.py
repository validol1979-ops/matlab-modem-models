"""Contract tests for the CIC decimator/interpolator and independent reference."""
import math
import os
import random
import sys
import unittest
from fractions import Fraction

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "common", "python")))

from cic_model import (CICDecimator, CICInterpolator, cic_gain, decimate,
                       interpolate, quantize, register_width)
import cic_reference as ref

IW = 18
LO, HI = -(1 << (IW - 1)), (1 << (IW - 1)) - 1
BAD = (ValueError, TypeError, RuntimeError)


def wrap(v, width):
    lo = -(1 << (width - 1))
    return (v - lo) % (1 << width) + lo


def q(v, divisor, width):
    # Independent exact rational rounding: nearest integer, ties toward +inf.
    rounded = math.floor(Fraction(v, divisor) + Fraction(1, 2))
    return max(-(1 << (width - 1)), min((1 << (width - 1)) - 1, rounded))


def wrapped(raw, width):
    return [(wrap(a, width), wrap(b, width)) for a, b in raw]


def dec_run(model, samples, rate, frames=None):
    frames = frames or [len(samples)]
    out, pos = [], 0
    for n in frames:
        chunk = samples[pos:pos + n]
        pos += n
        for j, s in enumerate(chunk):
            out.extend(model.push(s, last=(j == len(chunk) - 1)))
    return out


def int_run(model, samples, frames=None):
    frames = frames or [len(samples)]
    out, pos = [], 0
    for n in frames:
        chunk = samples[pos:pos + n]
        pos += n
        for j, s in enumerate(chunk):
            out.extend(model.push(s, last=(j == len(chunk) - 1)))
    return out


def wave(kind, n, seed):
    rng = random.Random(seed)
    if kind == "impulse":
        return [(1000, -1000)] + [(0, 0)] * (n - 1) if n else []
    if kind == "dc":
        return [(1234, -5678)] * n
    if kind == "alternating":
        return [(HI, LO) if i % 2 else (LO, HI) for i in range(n)]
    if kind == "rails":
        return [(HI, LO), (LO, HI), (HI, HI), (LO, LO)] * (n // 4 + 1)
    return [(rng.randint(LO, HI), rng.randint(LO, HI)) for _ in range(n)]


def cases():
    for rate in range(1, 33):
        for stages in (1, 2, 3, 5):
            for delay in (1, 2):
                yield rate, stages, delay


class TestPrimitives(unittest.TestCase):
    def test_gain_width_quantize(self):
        self.assertEqual(cic_gain(3, 2, 1, "decimate"), 9)
        self.assertEqual(cic_gain(3, 2, 1, "interpolate"), 3)
        self.assertEqual(cic_gain(1, 1, 1), 1)
        for rate, n, m in cases():
            gd = cic_gain(rate, n, m, "decimate")
            gi = cic_gain(rate, n, m, "interpolate")
            self.assertEqual(gd, (rate * m) ** n)
            self.assertEqual(gi, (rate * m) ** n // rate)
            self.assertEqual(register_width(7, rate, n, m, "decimate"),
                             7 + (gd - 1).bit_length())
            self.assertEqual(register_width(7, rate, n, m, "interpolate"),
                             7 + (gi - 1).bit_length())
        self.assertEqual(quantize(5, 2, 8), 3)       # 2.5 ties upward
        self.assertEqual(quantize(-5, 2, 8), -2)     # -2.5 ties upward
        self.assertEqual(quantize(1000, 8, 8), 125)
        self.assertEqual(quantize(-1000, 8, 8), -125)
        self.assertEqual(quantize(2000, 8, 8), 127)   # real saturation
        self.assertEqual(quantize(-2000, 8, 8), -128)

    def test_boxcar(self):
        for rate, n, m in [(1, 1, 1), (3, 2, 1), (4, 3, 2), (7, 5, 2)]:
            k = ref.boxcar_kernel(rate, n, m)
            self.assertEqual(len(k), n * (rate * m - 1) + 1)
            self.assertEqual(sum(k), (rate * m) ** n)


class TestAgainstReference(unittest.TestCase):
    def test_full_matrix_decimate(self):
        modes = ("random", "impulse", "dc", "alternating", "rails")
        for rate, n, m in cases():
            kind = modes[(rate + n + m) % len(modes)]
            samples = wave(kind, 2 * rate, rate * 100 + n * 10 + m)[:2 * rate]
            with self.subTest(rate=rate, stages=n, delay=m, kind=kind):
                width = register_width(IW, 32, n, m, "decimate")
                expected = wrapped(ref.decimate_reference(samples, rate, n, m), width)
                got = dec_run(CICDecimator(rate, n, m), samples, rate)
                self.assertEqual([p for p, _ in got], expected)
                self.assertEqual([bool(f) for _, f in got],
                                 [i == len(expected) - 1 for i in range(len(expected))])

    def test_full_matrix_interpolate(self):
        modes = ("random", "impulse", "dc", "alternating", "rails")
        for rate, n, m in cases():
            kind = modes[(rate + n + m) % len(modes)]
            samples = wave(kind, 4, rate * 100 + n * 10 + m)[:4]
            with self.subTest(rate=rate, stages=n, delay=m, kind=kind):
                width = register_width(IW, 32, n, m, "interpolate")
                expected = wrapped(ref.interpolate_reference(samples, rate, n, m), width)
                got = int_run(CICInterpolator(rate, n, m), samples)
                self.assertEqual([p for p, _ in got], expected)
                self.assertEqual(len(got), len(samples) * rate)
                flags = [bool(f) for _, f in got]
                self.assertEqual(sum(flags), 1)
                self.assertTrue(flags[-1])

    def test_identity_single_stage(self):
        samples = [(0, 0), (1, -1), (LO, HI), (HI, LO)]
        d = CICDecimator(1, 1, 1)
        self.assertEqual([p for p, _ in dec_run(d, samples, 1)], samples)
        i = CICInterpolator(1, 1, 1)
        self.assertEqual([p for p, _ in int_run(i, samples)], samples)

    def test_normalized(self):
        for rate, n, m in [(3, 1, 2), (5, 2, 1), (7, 3, 2), (10, 5, 1)]:
            samples = wave("random", 2 * rate, rate + n + m)[:2 * rate]
            gd = cic_gain(rate, n, m, "decimate")
            expected = [tuple(q(v, gd, IW) for v in p)
                        for p in ref.decimate_reference(samples, rate, n, m)]
            got = dec_run(CICDecimator(rate, n, m, normalize=True), samples, rate)
            self.assertEqual([p for p, _ in got], expected)
            gi = cic_gain(rate, n, m, "interpolate")
            samples = wave("random", 4, rate + 2 * n + m)[:4]
            expected = [tuple(q(v, gi, IW) for v in p)
                        for p in ref.interpolate_reference(samples, rate, n, m)]
            got = int_run(CICInterpolator(rate, n, m, normalize=True), samples)
            self.assertEqual([p for p, _ in got], expected)

    def test_undersized_modular_wrap(self):
        samples = [(7, -8), (-8, 7), (7, 7), (-8, -8), (3, -4), (-5, 6), (7, 0), (0, -8)]
        for rate, n, m in [(1, 1, 1), (2, 2, 1), (4, 3, 2)]:
            with self.subTest(rate=rate, stages=n, delay=m):
                width = 4
                expected = wrapped(ref.decimate_reference(samples[:2 * rate], rate, n, m), width)
                got = dec_run(CICDecimator(rate, n, m, input_width=4, acc_width=width),
                              samples[:2 * rate], rate)
                self.assertEqual([p for p, _ in got], expected)
                expected = wrapped(ref.interpolate_reference(samples[:2], rate, n, m), width)
                got = int_run(CICInterpolator(rate, n, m, input_width=4, acc_width=width),
                              samples[:2])
                self.assertEqual([p for p, _ in got], expected)

    def test_convenience_and_float_reference(self):
        samples = wave("random", 12, 77)
        self.assertEqual(decimate(samples, 4, stages=3, delay=2),
                         [p for p, _ in dec_run(CICDecimator(4, 3, 2), samples, 4)])
        self.assertEqual(interpolate(samples[:3], 4, stages=2, delay=2),
                         [p for p, _ in int_run(CICInterpolator(4, 2, 2), samples[:3])])
        self.assertEqual(decimate([], 4), [])
        self.assertEqual(interpolate([], 4), [])
        with self.assertRaises(BAD):
            decimate(samples[:5], 4)
        f = ref.float_reference(samples[:4], 2, 2, 1, "decimate")
        self.assertEqual(len(f), 2)


class TestStateAndValidation(unittest.TestCase):
    def test_chunked_frames_are_continuous(self):
        rate, n, m = 3, 2, 2
        samples = wave("random", 4 * rate, 9)
        expected = wrapped(ref.decimate_reference(samples, rate, n, m),
                           register_width(IW, 32, n, m, "decimate"))
        d = CICDecimator(rate, n, m)
        got = dec_run(d, samples, rate, [rate, 2 * rate, rate])
        self.assertEqual([p for p, _ in got], expected)

    def test_reset_and_configure(self):
        rate, n, m = 4, 3, 1
        a, b = wave("random", 2 * rate, 1), wave("dc", 2 * rate, 2)
        d = CICDecimator(rate, n, m)
        d.push(a[0])
        d.reset()                         # discards partial frame
        got = dec_run(d, b, rate)
        expected = wrapped(ref.decimate_reference(b, rate, n, m),
                           register_width(IW, 32, n, m, "decimate"))
        self.assertEqual([p for p, _ in got], expected)
        d.configure(rate)                 # even same rate resets arithmetic
        got = dec_run(d, b, rate)
        self.assertEqual([p for p, _ in got], expected)

        i = CICInterpolator(rate, n, m)
        i.push(a[0])
        i.reset()
        got = int_run(i, b[:2])
        expected = wrapped(ref.interpolate_reference(b[:2], rate, n, m),
                           register_width(IW, 32, n, m, "interpolate"))
        self.assertEqual([p for p, _ in got], expected)

    def test_atomic_failures(self):
        rate, n, m = 4, 2, 2
        samples = wave("random", 2 * rate, 33)
        d = CICDecimator(rate, n, m)
        d.push(samples[0])
        d.push(samples[1])
        for bad in [((1,), False), ((0.5, 1), False), ((True, 1), False),
                    ((HI + 1, 0), False), ((1, 2, 3), False), ((1, 2), 1),
                    ((1, 2), "yes")]:
            with self.assertRaises(BAD):
                d.push(*bad)
        with self.assertRaises(BAD):
            d.configure(rate)             # mid-frame
        for bad_rate in (0, 33, True, 1.5):
            with self.assertRaises(BAD):
                d.configure(bad_rate)
        got = dec_run(d, samples[2:], rate, [rate - 2, rate])
        expected = wrapped(ref.decimate_reference(samples, rate, n, m),
                           register_width(IW, 32, n, m, "decimate"))
        self.assertEqual([p for p, _ in got], expected)

        i = CICInterpolator(rate, n, m)
        prefix = i.push(samples[0])
        with self.assertRaises(BAD):
            i.push((1, 2), last="bad")
        with self.assertRaises(BAD):
            i.configure(True)
        # Keep the prefix outputs produced by the first, valid push.
        got = prefix + int_run(i, samples[1:2])
        expected = wrapped(ref.interpolate_reference(samples[:2], rate, n, m),
                           register_width(IW, 32, n, m, "interpolate"))
        self.assertEqual([p for p, _ in got], expected)

    def test_multi_frame_flags(self):
        rate, n, m = 3, 2, 1
        samples = wave("random", 10, 55)
        got = int_run(CICInterpolator(rate, n, m), samples, [2, 3, 5])
        self.assertEqual(len(got), len(samples) * rate)
        flags = [bool(f) for _, f in got]
        self.assertEqual(sum(flags), 3)
        for frame_end, count in ((2, 1), (5, 2), (10, 3)):
            self.assertTrue(flags[frame_end * rate - 1])
            if count > 1:
                self.assertFalse(flags[(frame_end - 1) * rate - 1])
        self.assertEqual([p for p, _ in got],
                         wrapped(ref.interpolate_reference(samples, rate, n, m),
                                 register_width(IW, 32, n, m, "interpolate")))

    def test_premature_tlast_preserves_nonzero_state(self):
        rate, n, m = 4, 3, 1
        samples = wave("random", 2 * rate, 21)
        d = CICDecimator(rate, n, m)
        d.push((11, -13))
        d.push((17, 19))
        with self.assertRaises(BAD):
            d.push((5, -7), last=True)    # phase 2 of R=4: premature
        got = dec_run(d, samples[2:], rate, [rate - 2, rate])
        expected = wrapped(ref.decimate_reference(
            [(11, -13), (17, 19)] + samples[2:], rate, n, m),
            register_width(IW, 32, n, m, "decimate"))
        self.assertEqual([p for p, _ in got], expected)

        # Interpolator: rejected invalid input must not disturb nonzero state.
        i = CICInterpolator(rate, n, m)
        prefix = i.push(samples[0])
        with self.assertRaises(BAD):
            i.push((0.5, 1))
        rest = []
        for j, s in enumerate(samples[1:], start=1):
            rest.extend(i.push(s, last=(j == len(samples) - 1)))
        expected_i = wrapped(ref.interpolate_reference(samples, rate, n, m),
                             register_width(IW, 32, n, m, "interpolate"))
        self.assertEqual([p for p, _ in prefix + rest], expected_i)

    def test_rate_changes_both_directions(self):
        n, m = 3, 2
        a_rate, b_rate = 3, 5
        samples = wave("random", 4 * b_rate, 71)
        d = CICDecimator(a_rate, n, m)
        first = dec_run(d, samples[:2 * a_rate], a_rate)
        self.assertEqual([p for p, _ in first],
                         wrapped(ref.decimate_reference(samples[:2 * a_rate], a_rate, n, m),
                                 register_width(IW, 32, n, m, "decimate")))
        d.configure(b_rate)
        got = dec_run(d, samples, b_rate)
        self.assertEqual([p for p, _ in got],
                         wrapped(ref.decimate_reference(samples, b_rate, n, m),
                                 register_width(IW, 32, n, m, "decimate")))

        i = CICInterpolator(a_rate, n, m)
        i.push(samples[0], last=True)
        i.configure(b_rate)
        got = int_run(i, samples)
        self.assertEqual([p for p, _ in got],
                         wrapped(ref.interpolate_reference(samples, b_rate, n, m),
                                 register_width(IW, 32, n, m, "interpolate")))

    def test_numpy_integers_and_custom_max_rate(self):
        try:
            import numpy as np
        except ImportError:
            self.skipTest("numpy unavailable")
        rate, n, m = np.int64(4), np.int32(2), np.int64(1)
        samples = wave("random", 2 * int(rate), 44)
        d = CICDecimator(rate, n, m, max_rate=np.int64(8))
        got = dec_run(d, samples, int(rate))
        self.assertEqual([p for p, _ in got],
                         wrapped(ref.decimate_reference(samples, int(rate), int(n), int(m)),
                                 register_width(IW, int(rate), int(n), int(m), "decimate")))
        d.configure(np.int32(8))
        self.assertEqual(d.rate, 8)
        with self.assertRaises(BAD):
            CICDecimator(9, max_rate=np.int64(8))
        i = CICInterpolator(np.int64(4), np.int32(2), np.int64(1), max_rate=np.int64(6))
        self.assertEqual(len(int_run(i, samples[:2])), 2 * 4)

    def test_bad_parameters_and_premature_tlast(self):
        for cls in (CICDecimator, CICInterpolator):
            for kw in ({"rate": 0}, {"rate": 33}, {"rate": True},
                       {"rate": 2, "max_rate": 0}, {"rate": 2, "max_rate": 33},
                       {"rate": 2, "stages": 0}, {"rate": 2, "stages": 6},
                       {"rate": 2, "stages": True}, {"rate": 2, "delay": 0},
                       {"rate": 2, "delay": 3}, {"rate": 2, "delay": True},
                       {"rate": 2, "input_width": 1}, {"rate": 2, "input_width": 33},
                       {"rate": 2, "input_width": True}, {"rate": 2, "acc_width": 1},
                       {"rate": 2, "acc_width": 129}, {"rate": 2, "acc_width": True}):
                with self.subTest(cls=cls.__name__, kw=kw), self.assertRaises(BAD):
                    cls(**kw)
        d = CICDecimator(4)
        with self.assertRaises(BAD):
            d.push((0, 0), last=True)
        self.assertEqual(d.push((0, 0)), [])


if __name__ == "__main__":
    unittest.main()
