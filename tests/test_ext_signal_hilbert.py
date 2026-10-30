"""Independent tests for DSP-HILBERT (AnalyticSignal / AnalyticSignalFixed).

Oracles are written from scratch here: Hamming formula, naive convolution, scipy.signal.hilbert,
coherent-bin FFT and a hand integer dot. Measured numbers are printed for results_hilbert.txt.
Budgets are pre-declared below.
"""
import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"common"/"python"))
import unittest

import numpy as np
import scipy.signal

from ext_signal_core import AnalyticSignal, AnalyticSignalFixed, hilbert_taps

SAT = 2 ** 17 - 1              # symmetric signed18 rail (test-side constant)
RAIL_MIN, RAIL_MAX = -(2 ** 17), 2 ** 17 - 1
N, PAD = 1000, 160             # coherent: 0.125*N=125, 0.2*N=200, 0.125*(N+PAD)=145, 0.2*1160=232
F1, F2 = 0.125, 0.2


def ref_hamming(m):
    return [0.54 - 0.46 * math.cos(2 * math.pi * n / (m - 1)) for n in range(m)]


def ref_taps(m):
    d = (m - 1) // 2
    return tuple(0.0 if (n - d) % 2 == 0 else w * 2.0 / (math.pi * (n - d))
                 for n, w in enumerate(ref_hamming(m)))


def ref_fir(x, taps):
    """Naive causal convolution with zero pre-history: y[n] = sum_k taps[k]*x[n-k]."""
    return [sum(t * x[n - k] for k, t in enumerate(taps) if n - k >= 0) for n in range(len(x))]


def ref_halfup(v, bits):
    return (v + (1 << (bits - 1))) >> bits


def ref_fixed_seq(xs, m=63, bits=17):
    """Hand integer pipeline oracle: Q17 taps, exact dot, half-up /2**bits, sat signed18."""
    ti = tuple(int(round(t * (1 << bits))) for t in ref_taps(m))
    d, z, out = (m - 1) // 2, [0] * m, []
    for x in xs:
        z = [x] + z[:m - 1]
        acc = 0
        for t, v in zip(ti, z):
            acc += t * v
        q = max(-SAT, min(SAT, ref_halfup(acc, bits)))
        out.append((z[d], q))
    return out, ti


def lcg(n, seed=20261030, amp=20000):
    s, out = seed, []
    for _ in range(n):
        s = (1103515245 * s + 12345) % (1 << 31)
        out.append(s % (2 * amp + 1) - amp)
    return out


class TestHilbertTaps(unittest.TestCase):
    def test_formula_symmetry_and_gain(self):
        for m in (31, 63):
            h, ref, d = hilbert_taps(m), ref_taps(m), (m - 1) // 2
            self.assertEqual(len(h), m)
            self.assertTrue(all(type(v) is float for v in h))
            self.assertLess(max(abs(a - b) for a, b in zip(h, ref)), 1e-15)
            self.assertLess(max(abs(h[n] + h[m - 1 - n]) for n in range(m)), 1e-15)  # antisymmetric
            self.assertEqual(h[d], 0.0)
            self.assertTrue(all(h[n] == 0.0 for n in range(m) if (n - d) % 2 == 0))     # even k -> 0
            self.assertAlmostEqual(h[d + 1], 2.0 / math.pi * ref_hamming(m)[d + 1], places=15)
            g = abs(sum(h[k] * np.exp(-2j * np.pi * 0.25 * k) for k in range(m)))
            self.assertTrue(0.9 < g < 1.1, f"gain(0.25)={g}: no accidental factor 2")     # ~1, not 2
        for bad in (30, 32, 1, 64, -31, 0, 31.0, True, None, "31"):
            with self.assertRaises((TypeError, ValueError)):
                hilbert_taps(bad)


class TestAnalyticFloat(unittest.TestCase):
    def test_impulse_equals_fir_and_delay(self):
        for m in (31, 63):
            d, ref = (m - 1) // 2, ref_taps(m)
            x = [1.0] + [0.0] * (m + 5)
            out, want = AnalyticSignal(numtaps=m).process(x), ref_fir(x, ref)
            for n in range(m):
                self.assertAlmostEqual(out[n].imag, want[n], places=15)   # Q == specified FIR
                self.assertAlmostEqual(out[n].imag, ref[n], places=15)
            self.assertEqual([o.real for o in out[:d]], [0.0] * d)        # delayed impulse...
            self.assertEqual((out[d].real, out[d].imag, out[d + 1].real), (1.0, 0.0, 0.0))
            self.assertAlmostEqual(abs(out[d]), 1.0, places=15)           # ...unity, no factor 2

    def test_cosine_positive_sine_group_delay(self):
        for m in (31, 63):
            for f, budget in ((F1, 0.02), (F2, 0.02)) if m == 63 else ((F1, 0.05), (F2, 0.05)):
                d = (m - 1) // 2
                x = [math.cos(2 * math.pi * f * n) for n in range(N + PAD)]
                out = AnalyticSignal(numtaps=m).process(x)
                ana = scipy.signal.hilbert(x)                             # ideal, zero delay
                err = max(abs(out[i] - ana[i - d]) for i in range(PAD, N + PAD))
                err_ref = max(abs(out[i] - complex(math.cos(2 * math.pi * f * (i - d)),
                                                   math.sin(2 * math.pi * f * (i - d))))
                              for i in range(PAD, N + PAD))
                c = sum(o.imag * math.sin(2 * math.pi * f * (i - d)) for i, o in enumerate(out))
                self.assertGreater(c / (N + PAD), 0.4, "Q must be POSITIVE sine")
                self.assertLess(err, budget)
                self.assertLess(err_ref, budget)
                print(f"HILB float m={m} f={f}: vs_scipy={err:.3e} vs_exp={err_ref:.3e} "
                      f"(budget {budget})")

    def test_image_rejection_two_tones(self):
        for m in (31, 63):
            x = [math.cos(2 * math.pi * F1 * n) + math.cos(2 * math.pi * F2 * n)
                 for n in range(N + PAD)]
            seg = AnalyticSignal(numtaps=m).process(x)[PAD:]
            s = np.abs(np.fft.fft(seg)) / N
            rej = [20 * math.log10(s[int(f * N)] / s[N - int(f * N)]) for f in (F1, F2)]
            img = 20 * math.log10(np.max(s[N // 2 + 1:]) / np.max(s[1:N // 2]))
            for f, r in zip((F1, F2), rej):
                self.assertGreater(r, 40.0)                                # budget: >40 dB
                self.assertAlmostEqual(s[int(f * N)], 1.0, delta=0.05)     # passband ~1, not 2
            self.assertLess(img, -40.0)
            self.assertEqual(set(np.argsort(s[1:N//2])[-2:]+1), {int(F1*N),int(F2*N)})
            print(f"HILB img m={m}: rej(+{F1})={rej[0]:.1f}dB rej(+{F2})={rej[1]:.1f}dB "
                  f"neg_over_pos={img:.1f}dB")

    def test_stall_reset_and_atomic(self):
        a = AnalyticSignal(numtaps=31)
        for v in (0.25, -0.5):
            a.push(v)
        held = a.push(0.75)
        z, n = list(a._z), len(a._z)
        self.assertEqual(a.push(9.0, accept=False), held)                  # held output
        self.assertEqual(a._z, z)                                          # no state advance
        for bad in (True, False, "x", None, 1 + 2j, float("nan"), float("inf")):
            with self.assertRaises((TypeError, ValueError)):
                a.push(bad)
            self.assertEqual(a._z, z)                                      # atomic reject
        for bad_acc in (1, 0, None, "yes", 1.0):
            with self.assertRaises(TypeError):
                a.push(0.1, accept=bad_acc)
            self.assertEqual(a._z, z)
        with self.assertRaises(ValueError):
            a.process([0.1, float("nan"), 0.2])                            # process is atomic
        self.assertEqual(a._z, z)
        a.reset()
        self.assertEqual([a._z, a.push(0.0)], [[0.0] * 31, 0j])
        for i in range(30):
            a.push(float(i))
        self.assertEqual(len(a._z), 31)                                    # state bounded
        a.reset()
        self.assertEqual(a._z, [0.0] * 31)

    def test_matches_oracle_on_noise(self):
        m, d, ref = 63, 31, ref_taps(63)
        xs = [math.sin(2 * math.pi * 0.07 * n / 3) * 0.5 + 0.4 * math.cos(2 * math.pi * 0.3 * n)
              for n in range(500)]
        out = AnalyticSignal(numtaps=m).process(xs)
        q = ref_fir(xs, ref)
        for i in range(500):
            self.assertAlmostEqual(out[i].imag, q[i], places=12)
            self.assertAlmostEqual(out[i].real, xs[i - d] if i >= d else 0.0, places=15)


class TestAnalyticFixed(unittest.TestCase):
    def test_integer_taps_and_hand_dot_oracle(self):
        for m in (31, 63):
            f = AnalyticSignalFixed(numtaps=m, coef_bits=17)
            _, ti = ref_fixed_seq([0], m, 17)
            self.assertEqual(f.taps_fixed, ti)
            self.assertLess(max(abs(a / 2 ** 17 - b) for a, b in zip(f.taps_fixed, ref_taps(m))),
                            0.5 / 2 ** 17 + 1e-15)
        xs = lcg(400)
        got, want = AnalyticSignalFixed(63).process(xs), ref_fixed_seq(xs)[0]
        self.assertEqual(got, want)                                        # exact bit-for-bit
        self.assertTrue(all(type(v) is int for p in got for v in p))

    def test_fixed_impulse_and_negative_rail(self):
        m, d = 63, 31
        f = AnalyticSignalFixed(numtaps=m)
        _, ti = ref_fixed_seq([0], m, 17)
        out = f.process([RAIL_MAX] + [0] * (m + 3))
        for n in range(m):
            self.assertEqual(out[n][1], ref_halfup(ti[n] * RAIL_MAX, 17))  # integer FIR
        self.assertEqual([p[0] for p in out[:d]], [0] * d)
        self.assertEqual((out[d][0], out[d][1]), (RAIL_MAX, 0))
        g = AnalyticSignalFixed(numtaps=m)
        o2 = g.process([RAIL_MIN] + [0] * (m + 3))
        self.assertEqual(o2[d][0], RAIL_MIN)                               # I exact, not saturated
        self.assertEqual(g.clip_count, 0)

    def test_fixed_vs_float_budget_and_exact_I(self):
        for f0 in (F1, F2):
            xs = [int(round(20000 * math.cos(2 * math.pi * f0 * n))) for n in range(800)]
            fl = AnalyticSignal(63).process([float(v) for v in xs])
            fx = AnalyticSignalFixed(63).process(xs)
            lsb = max(abs(fl[i].imag - fx[i][1]) for i in range(70, 800))
            self.assertEqual([float(p[0]) for p in fx], [p.real for p in fl])  # I exact
            self.assertLess(lsb, 6.0)                                      # budget: <6 LSB
            peak = max(abs(p[1]) for p in fx[70:])
            self.assertLess(abs(peak - max(abs(v.imag) for v in fl[70:])),6)                        # gain ~1
            print(f"HILB fixed f={f0}: max_q_err={lsb:.3f} LSB (budget 6) peakQ={peak} "
                  f"clips={AnalyticSignalFixed(63).clip_count}")

    def test_fixed_clipping_rails(self):
        f = AnalyticSignalFixed(numtaps=63)
        pat = [RAIL_MAX * (1 if t > 0 else -1 if t < 0 else 0)
               for t in reversed(hilbert_taps(63))]                        # matched -> sum|t|
        want = RAIL_MAX * sum(abs(t) for t in ref_taps(63))
        seq = pat + [-v for v in pat]
        out = [f.push(v) for v in seq]
        self.assertGreater(want, SAT)                                      # oracle expects clip
        self.assertEqual(out[62], (pat[62-31], SAT))                           # positive rail
        self.assertEqual(out[125], (seq[125-31], -SAT))                        # negative rail
        self.assertGreater(f.clip_count, 0)
        self.assertEqual(f.acc_clip_count, 0)                               # no 64-bit clamp
        self.assertGreater(sum(1 for p in out[:63] if p[1] == SAT), 0)        # at the rail
        for j in range(63, len(seq)):                                       # I exact, never sat
            self.assertEqual(out[j][0], seq[j - 31])
        print(f"HILB fixed rails: clip_count={f.clip_count} idealQ={want:.0f} -> sat +/-{SAT}")

    def test_fixed_validation_stall_reset_atomic(self):
        f = AnalyticSignalFixed(numtaps=31, coef_bits=17)
        for bad in (True, False, 1.0, "3", None, 1 + 0j, 131072, -131073, 2 ** 40):
            with self.assertRaises((TypeError, ValueError)):
                f.push(bad)
        for bad_acc in (1, None, "T", 0.0):
            with self.assertRaises(TypeError):
                f.push(5, accept=bad_acc)
        f.push(1000)
        held, z = f.push(-2000), list(f._z)
        self.assertEqual(f.push(30000, accept=False), held)                # stall holds pair
        self.assertEqual(f._z, z)                                          # and does not advance
        f.reset()
        self.assertEqual([f._z, f.push(0), f.clip_count, f.acc_clip_count],
                         [[0] * 31, (0, 0), 0, 0])
        for kw in (dict(numtaps=32), dict(numtaps=63.0), dict(numtaps=True), dict(coef_bits=0),
                   dict(coef_bits=True), dict(coef_bits=17.0), dict(coef_bits=25)):
            with self.assertRaises((TypeError, ValueError)):
                AnalyticSignalFixed(**kw)
        f.push(7)
        z2 = list(f._z)
        with self.assertRaises(ValueError):
            f.process([1, 2, 131072])                                      # atomic reject
        self.assertEqual(f._z, z2)


if __name__ == "__main__":
    unittest.main()
