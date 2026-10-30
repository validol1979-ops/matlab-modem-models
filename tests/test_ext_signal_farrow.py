import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"common"/"python"))
import unittest

import numpy as np
from scipy.interpolate import lagrange as sp_lagrange

from ext_signal_farrow import Farrow

F = 16
ONE = 1 << F


def oracle_weights(D, mu):
    """Independent Lagrange weights via scipy on nodes 0..D (sample x[n-j] at node j)."""
    nodes = np.arange(D + 1, dtype=float)
    return np.array([sp_lagrange(nodes, np.eye(D + 1)[j])(mu) for j in range(D + 1)])


def oracle_q27(D):
    """Q27 integer coefficients from scipy polynomials (separate code path)."""
    nodes = np.arange(D + 1, dtype=float)
    q = []
    for j in range(D + 1):
        p = sp_lagrange(nodes, np.eye(D + 1)[j])
        c = list(p.coefficients)[::-1]  # ascending
        c += [0.0] * (D + 1 - len(c))
        q.append([int(math.floor(v * 2.0**27 + 0.5)) for v in c])
    return q


def oracle_fixed_stream(D, step_q, xs):
    """Independent integer recurrence over the full sequence (no streaming logic)."""
    Q = oracle_q27(D)
    out = []
    t, N = 0, len(xs)
    while True:
        n = -((-t) // ONE)  # ceil
        if n > N - 1:
            break
        mu = n * ONE - t
        taps = [xs[n - j] if n - j >= 0 else 0 for j in range(D + 1)]
        out.append((n, mu, taps))
        t += step_q
    results = []
    for n, mu, taps in out:
        vals = []
        for comp in range(2):
            xs_c = [(tp[comp] if isinstance(tp, tuple) else tp) for tp in taps]
            c = [sum(Q[j][k] * xs_c[j] for j in range(D + 1)) for k in range(D + 1)]
            acc = c[D]
            for k in range(D - 1, -1, -1):
                acc = (acc * mu + (1 << (F - 1))) // ONE + c[k]
            v = (acc + (1 << 26)) // (1 << 27)
            vals.append(min(max(v, -(1 << 17)), (1 << 17) - 1))
        results.append(tuple(vals))
    return results


def state(f):
    return (f.next_time, f.count, f._step, list(f._hist))


class TestCoefficients(unittest.TestCase):
    def test_match_scipy(self):
        for D in (3, 4):
            from ext_signal_farrow import lagrange_coeffs
            ex = lagrange_coeffs(D)
            q = oracle_q27(D)
            for j in range(D + 1):
                for k in range(D + 1):
                    self.assertLess(abs(float(ex[j][k]) * 2**27 - q[j][k]), 0.5 + 1e-6)

    def test_partition_of_unity(self):
        for D in (3, 4):
            for mu in np.linspace(0, 1, 11):
                self.assertAlmostEqual(oracle_weights(D, mu).sum(), 1.0, 12)


class TestFloatPath(unittest.TestCase):
    def test_polynomial_reproduction(self):
        rng = np.random.default_rng(1)
        for D in (3, 4):
            coef = rng.uniform(-1, 1, D + 1)
            p = np.poly1d(coef)
            f = Farrow(degree=D, step=0.37)
            outs = []
            N = 60
            for m in range(N):
                outs += [(m, o) for o in f.push(float(p(m)))]
            for k, (n, y) in enumerate(outs):
                t = k * 24248 / ONE  # Q16-quantized step (0.37 * 65536 rounded)
                if math.ceil(t - 1e-12) < D:  # zero-history region excluded
                    continue
                self.assertTrue(np.isclose(y, p(t), rtol=1e-12, atol=1e-9), f"D={D} k={k}")

    def test_matches_scipy_weights(self):
        rng = np.random.default_rng(2)
        D = 4
        xs = rng.standard_normal(40)
        f = Farrow(degree=D, step=1.0)
        ys = []
        for x in xs:
            ys += f.push(float(x))
        for n, y in enumerate(ys):
            if n < D:
                continue
            ref = sum(oracle_weights(D, 0.0)[j] * xs[n - j] for j in range(D + 1))
            self.assertAlmostEqual(y.real, ref, 12)
            self.assertEqual(y.imag, 0.0)

    def test_mu_zero_and_near_one(self):
        f = Farrow(degree=3, step=1.0)
        xs = [1.0, 2.0, 5.0, -3.0, 7.0]
        ys = []
        for x in xs:
            ys += f.push(x)
        self.assertEqual([y.real for y in ys], xs)  # delta0: exact samples
        g = Farrow(degree=3, step=1.0 - 1 / ONE)
        rng = np.random.default_rng(3)
        x = rng.standard_normal(30)
        ys = []
        for v in x:
            ys += g.push(float(v))
        self.assertGreater(len(ys), 20)
        n = 10
        k = n  # sample times (nearly-1 step) decode to t = k*(1-2^-16)
        t = k * (1 - 1 / ONE)
        ref = sum(oracle_weights(3, n - t)[j] * x[n - j] for j in range(4)) if n - t >= 0 else None
        self.assertLess(abs(ys[n].real - ref), 1e-9)

    def test_complex_input(self):
        f = Farrow(degree=3, step=0.5)
        g = Farrow(degree=3, step=0.5)
        rng = np.random.default_rng(4)
        z = rng.standard_normal(20) + 1j * rng.standard_normal(20)
        yz = []
        for v in z:
            yz += f.push(complex(v))
        yr = []
        for v in z.real:
            yr += g.push(float(v))
        ref = []
        h = Farrow(degree=3, step=0.5)
        for v in z.imag:
            ref += h.push(float(v))
        for a, b, c in zip(yz, yr, ref):
            self.assertAlmostEqual(a, b + 1j * c, 12)


class TestFixedPath(unittest.TestCase):
    def test_bit_exact_vs_oracle(self):
        rng = np.random.default_rng(5)
        for D in (3, 4):
            for step_q in (ONE, ONE // 2, 2 * ONE + 1, 3 * ONE // 10 + 7):
                xs = [(int(a), int(b)) for a, b in rng.integers(-2**15, 2**15, (80, 2))]
                f = Farrow(degree=D, step=step_q / ONE, fixed=True)
                got = []
                for s in xs:
                    got += f.push(s)
                ref = oracle_fixed_stream(D, step_q, xs)
                self.assertEqual(got, ref[:len(got)])
                self.assertEqual(len(got), len(ref))

    def test_fixed_vs_float_within_10lsb(self):
        rng = np.random.default_rng(6)
        for D in (3, 4):
            xs = rng.integers(-2**14, 2**14, 200)
            fx = Farrow(degree=D, step=0.123, fixed=True)
            fl = Farrow(degree=D, step=0.123)
            for x in xs:
                a = fx.push(int(x))
                b = fl.push(float(x))
                for (yi, _), yf in zip(a, b):
                    self.assertLessEqual(abs(yi - yf.real), 10)
        # mu endpoints
        for D in (3, 4):
            fx = Farrow(degree=D, step=1 / 16, fixed=True)
            fl = Farrow(degree=D, step=1 / 16)
            for x in [12345, -20000, 7, 0, 30000]:
                a = fx.push(x)
                b = fl.push(float(x))
                for (yi, _), yf in zip(a, b):
                    self.assertLessEqual(abs(yi - yf.real), 10)

    def test_halfup_and_saturation(self):
        f = Farrow(degree=3, step=1.0, fixed=True)
        self.assertEqual(f.push((5, -7)), [((5, -7))])
        g = Farrow(degree=4, step=0.5, fixed=True)
        out = []
        for _ in range(10):
            out += g.push(S_MAX)
        for i, q in out:
            self.assertTrue(-(1 << 17) <= i <= (1 << 17) - 1)


S_MAX = (1 << 17) - 1


class TestSchedule(unittest.TestCase):
    def test_rate_change_and_carries(self):
        rng = np.random.default_rng(7)
        xs = rng.standard_normal(300)
        f = Farrow(degree=3, step=0.1)
        steps = [0.1, 1.0, 0.3, 2.5, 0.0625, 16.0]
        t_ext, step_q = 0, math.floor(0.1 * ONE + 0.5)  # external schedule, independent of Farrow
        for i, x in enumerate(xs):
            if i % 50 == 0:
                st = steps[(i // 50) % len(steps)]
                before = f.next_time
                f.configure_rate(st)
                self.assertEqual(f.next_time, before)  # preserved across rate change
                step_q = math.floor(st * ONE + 0.5)
            exp = 0
            while -((-t_ext) // ONE) <= i:  # ceil(t) <= accepted index
                exp += 1
                t_ext += step_q
            got = f.push(float(x))
            self.assertEqual(len(got), exp, f"push {i}")
            self.assertEqual(f.next_time, t_ext)

    def test_stall_and_accept_flag(self):
        f = Farrow(degree=3, step=1.0)
        self.assertEqual(f.push(1.0, accept=False), [])
        self.assertEqual(f.count, 0)
        self.assertEqual(f.next_time, 0)
        out = f.push(1.0)
        self.assertEqual(len(out), 1)
        before = state(f)
        self.assertEqual(f.push(9.0, accept=False), [])
        self.assertEqual(state(f), before)

    def test_reset(self):
        f = Farrow(degree=4, step=0.7)
        for x in range(10):
            f.push(float(x))
        f.reset()
        self.assertEqual((f.next_time, f.count, len(f._hist)), (0, 0, 0))
        fresh = Farrow(degree=4, step=0.7)
        a = [f.push(float(x)) for x in range(8)]
        b = [fresh.push(float(x)) for x in range(8)]
        self.assertEqual(a, b)

    def test_invalid_atomic(self):
        f = Farrow(degree=3, step=0.5)
        f.push(1.0)
        before = state(f)
        bad_samples = [float("nan"), float("inf"), True, "x", None]
        for s in bad_samples:
            with self.assertRaises(ValueError):
                f.push(s)
            self.assertEqual(state(f), before)
        for st in (0, 0.0, 17, float("nan"), -1.0, True):
            with self.assertRaises(ValueError):
                f.configure_rate(st)
            self.assertEqual(state(f), before)
        with self.assertRaises(ValueError):
            Farrow(degree=2)
        with self.assertRaises(ValueError):
            Farrow(frac_bits=15)
        g = Farrow(degree=3, step=1.0, fixed=True)
        for s in [(1 << 17, 0), 1.5, (0, 1 << 17), (1, 2, 3)]:
            with self.assertRaises(ValueError):
                g.push(s)
        self.assertEqual(g.count, 0)


if __name__ == "__main__":
    unittest.main()
