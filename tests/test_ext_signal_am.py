import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"common"/"python"))
import unittest

from ext_signal_am import AMModulator, AMDemodulator

FS = 400000
AMP = 131071
TWO32 = 1 << 32
def step_for(f):
    return int(round(f * TWO32 / FS))


def alpha(f, fs=FS):
    return 1.0 - math.exp(-2.0 * math.pi * f / fs)
class TestAMModulator(unittest.TestCase):
    def test_float_formula_and_phase(self):
        d, fs = 0.7, 9000
        tx = AMModulator(depth=d, step=step_for(fs))
        for m in (0.0, 0.25, -0.8, 1.0, -1.0):
            a = 2 * math.pi * tx._dds.phase / TWO32      # ideal phasor at current phase
            want = 0.5 * (1.0 + d * m) * complex(math.cos(a), math.sin(a))
            self.assertLess(abs(tx.push(m) - want), 1e-15)
        self.assertEqual(tx._dds.phase, (5 * step_for(fs)) % TWO32)  # one advance per accept

    def test_fixed_integer_amplitude_oracle(self):
        tx = AMModulator(depth=0.5, step=0, fixed=True)
        self.assertEqual(tx.push(0), (65535, 0))       # (AMP+0)//2 at phase 0
        self.assertEqual(tx.push(AMP), (98303, 0))     # (AMP+65535)//2
        self.assertEqual(tx.push(-AMP), (32768, 0))    # (AMP-65535)//2
        tx.reset()
        self.assertEqual(tx.push(-131072 + 1), (32768, 0))
        with self.assertRaises(ValueError):
            tx.push(-131072)                            # excluded by audio bound

    def test_accept_stall_and_reset(self):
        tx = AMModulator(0.4, step_for(12345), fixed=True)
        fresh = AMModulator(0.4, step_for(12345), fixed=True)
        a = tx.push(1000)
        fresh.push(1000)
        held, phase = tx.push(0, accept=False), tx._dds.phase
        self.assertEqual(held, a)                       # stalled output is held
        self.assertEqual(tx.push(1000), fresh.push(1000))  # and phase did not advance
        self.assertNotEqual(phase, 0)
        tx.reset()
        self.assertEqual(tx._dds.phase, 0)
        self.assertEqual(tx.push(1000), AMModulator(0.4, step_for(12345), fixed=True).push(1000))

    def test_invalid_is_atomic(self):
        tx = AMModulator(0.5, step_for(1000))
        held, phase = tx.push(0.2), tx._dds.phase
        for bad in (1.0001, -1.0001, float("nan"), float("inf")):
            with self.assertRaises((ValueError, TypeError)):
                tx.push(bad)
            self.assertEqual(tx._dds.phase, phase)
            self.assertEqual(tx.push(0.0, accept=False), held)
        with self.assertRaises(TypeError):
            tx.push(0.5, accept=1)
        for bad in (-0.01, 1.01, float("nan"), float("inf")):
            with self.assertRaises(ValueError):
                AMModulator(depth=bad)
        with self.assertRaises(ValueError):
            AMModulator(depth=0.5, step=TWO32)
        with self.assertRaises(TypeError):
            AMModulator(depth=0.5, fixed=0)

    def test_process_atomic_on_bad_element(self):
        tx = AMModulator(depth=0.5)
        phase = tx._dds.phase
        with self.assertRaises(ValueError):
            tx.process([0.1, 0.2, 1.5])
        self.assertEqual(tx._dds.phase, phase)

    def test_depth_extremes_and_steady_envelope(self):
        for d in (0.0, 0.5, 1.0):
            tx = AMModulator(d, step_for(20000), fixed=True)
            peak = 0
            for m in (AMP, -AMP) * 20000:
                i, q = tx.push(m)
                peak = max(peak, i * i + q * q)
            self.assertLessEqual(math.isqrt(peak), AMP)   # headroom prevents saturation
        tx = AMModulator(1.0, step_for(20000))
        for m in (1.0, -1.0) * 5000:
            self.assertLessEqual(abs(tx.push(m)), 1.0 + 1e-12)
class TestAMDemodulator(unittest.TestCase):
    def test_float_reference_onepole_and_dc(self):
        rx = AMDemodulator(cutoff=5000, dc_cutoff=20)
        dc = lp = 0.0
        for n in range(3000):
            z = complex(0.4 * math.cos(0.1 * n), 0.4 * math.sin(0.1 * n))
            env = abs(z)
            dc += alpha(20) * (env - dc)
            lp += alpha(5000) * ((env - dc) - lp)
            self.assertAlmostEqual(rx.push(z), lp, delta=2e-12)

    def test_float_and_fixed_stall_preserve_nonzero_output(self):
        for fixed in (False, True):
            with self.subTest(fixed=fixed):
                rx = AMDemodulator(fixed=fixed)
                control = AMDemodulator(fixed=fixed)
                first = (30000, 40000) if fixed else complex(0.3, 0.4)
                following = (1000, 0) if fixed else complex(0.1, 0)
                out = rx.push(first)
                self.assertNotEqual(out, 0)
                control.push(first)
                state = rx.__dict__.copy()
                for _ in range(3):
                    self.assertEqual(rx.push(following, accept=False), out)
                    self.assertEqual(rx.__dict__, state)
                self.assertEqual(rx.push(following), control.push(following))

    def test_fixed_first_states_hand_oracle(self):
        rx = AMDemodulator(fixed=True)
        bq, aq = int(math.floor(alpha(20) * (1 << 30) + 0.5)), int(math.floor(alpha(5000) * (1 << 30) + 0.5))
        dc = lpr = 0
        for z in ((3, 4), (0, 0), (AMP, 0), (-131072, -131072)):
            env = math.isqrt(z[0] * z[0] + z[1] * z[1])
            dc += (bq * ((env << 17) - dc) + (1 << 29)) >> 30
            lpr += (aq * (((env - (dc >> 17)) << 17) - lpr) + (1 << 29)) >> 30
            out = (lpr + (1 << 16)) >> 17
            out = max(-AMP, min(AMP, out))
            self.assertEqual(rx.push(z), out)

    def test_fixed_input_contract_and_atomicity(self):
        rx = AMDemodulator(fixed=True)
        rx.push((5, 6))
        held, phase_state = rx.push((0, 0), accept=False), (rx._dcr, rx._lpr)
        for bad in ((AMP + 1, 0), (0, -131073), [5, 6], (5, 6, 7), (5.0, 6)):
            with self.assertRaises((ValueError, TypeError)):
                rx.push(bad)
            self.assertEqual((rx._dcr, rx._lpr), phase_state)
            self.assertEqual(rx.push((0, 0), accept=False), held)
        with self.assertRaises(TypeError):
            rx.push(5 + 6j)                              # correct type in fixed mode
        rx.reset()
        y = rx.push((30000, 40000))                      # envelope 50000, nonzero state
        self.assertNotEqual((rx._dcr, rx._lpr), (0, 0))
        self.assertEqual(rx.push((0, 0), accept=False), y)
        rx.reset()
        self.assertEqual((rx._dcr, rx._lpr, rx.push((0, 0), accept=False)), (0, 0, 0))

    def test_invalid_config(self):
        with self.assertRaises(ValueError):AMDemodulator(fs=1e20,fixed=True)
        for args in ((FS, 5000, 20),):
            AMDemodulator(*args)
        for kw in (dict(cutoff=0), dict(cutoff=FS / 2), dict(cutoff=5000, dc_cutoff=5000),
                   dict(cutoff=5000, dc_cutoff=0), dict(cutoff=5000, dc_cutoff=-1),
                   dict(fs=0), dict(cutoff=float("nan")), dict(fs=float("inf"))):
            with self.assertRaises((ValueError, TypeError)):
                AMDemodulator(**kw)
        with self.assertRaises(TypeError):
            AMDemodulator(fixed=1)

    def test_loopback_amplitude_and_startup(self):
        d, depth = 1000, 0.5
        tx, rx = AMModulator(depth, step_for(37000)), AMDemodulator()
        ys = [rx.push(tx.push(0.2 * math.sin(2 * math.pi * d * n / FS))) for n in range(80000)]
        self.assertGreater(5 * FS / (2 * math.pi * 20), 15000)
        tail = ys[40000:]
        peak = (max(tail) - min(tail)) / 2
        gain = alpha(5000) / abs(1 - (1 - alpha(5000)) * complex(math.cos(2 * math.pi * d / FS),
                                                               -math.sin(2 * math.pi * d / FS)))
        self.assertAlmostEqual(peak / (0.5 * depth * 0.2 * gain), 1.0, delta=0.01)
        self.assertLess(abs(sum(tail) / len(tail)), 2e-4)  # DC startup discarded
        self.assertEqual(rx.clip_count, 0)

    def test_fixed_matches_float_error_budget(self):
        step, amp = step_for(1000), 0.2
        txf, rxf = AMModulator(0.5, step), AMDemodulator()
        txq, rxq = AMModulator(0.5, step, fixed=True), AMDemodulator(fixed=True)
        for n in range(60000):
            m = amp * math.sin(2 * math.pi * 1000 * n / FS)
            yf = rxf.push(txf.push(m))
            yq = rxq.push(txq.push(int(round(m * AMP))))
            if n >= 20000:
                self.assertLess(abs(yf * AMP - yq), 20.0)   # amplitude .2, after startup
        self.assertEqual((txq.clip_count, rxq.clip_count), (0, 0))

    def test_depth_zero_and_one(self):
        a = alpha(5000)
        gain = a / abs(1 - (1 - a) * complex(math.cos(2 * math.pi * 2000 / FS),
                                            -math.sin(2 * math.pi * 2000 / FS)))
        for depth in (0.0, 1.0):
            tx, rx = AMModulator(depth, step_for(2000), fixed=True), AMDemodulator(cutoff=5000, fixed=True)
            ys = [rx.push(tx.push(int(round(0.1 * AMP * math.sin(2 * math.pi * 2000 * n / FS)))))
                  for n in range(40000)]
            pk = (max(ys[30000:]) - min(ys[30000:])) / 2 / AMP
            expect = 0.5 * depth * 0.1 * abs(gain)   # recovery depth*m/2, known LPF gain
            if expect:
                self.assertAlmostEqual(pk / expect, 1.0, delta=0.02)
            else:
                self.assertLess(pk, 2e-5)                # depth 0: only carrier, no audio

    def test_cfo_envelope_invariance(self):
        rx1, rx2 = AMDemodulator(), AMDemodulator()
        tx1, tx2 = AMModulator(0.5, step_for(1000)), AMModulator(0.5, step_for(37000))
        y1 = [rx1.push(tx1.push(0.2 * math.sin(2 * math.pi * 1000 * n / FS))) for n in range(40000)]
        y2 = [rx2.push(tx2.push(0.2 * math.sin(2 * math.pi * 1000 * n / FS))) for n in range(40000)]
        self.assertLess(abs((max(y1[30000:]) - min(y1[30000:])) -
                            (max(y2[30000:]) - min(y2[30000:]))) / 2, 5e-5)

    def test_noise_and_reset_counters(self):
        tx, rx = AMModulator(1.0, step_for(17000), fixed=True), AMDemodulator(fixed=True)
        state = [12345]
        for n in range(3000):
            state[0] = (1103515245 * state[0] + 12345) & 0x7FFFFFFF
            m = ((state[0] >> 8) % (AMP + 1)) * (-1 if state[0] & 1 else 1)
            y = rx.push(tx.push(m))
            self.assertTrue(-AMP <= y <= AMP)
        tx.push(0, accept=False), rx.push((0, 0), accept=False)
        tx.reset(), rx.reset()
        self.assertEqual((tx.clip_count, rx.clip_count, rx.state_clip_count), (0, 0, 0))
        self.assertEqual((tx.push(0, False), rx.push((0, 0), accept=False)), ((0, 0), 0))

    def test_full_rails_clipping_counter(self):
        rx = AMDemodulator(fixed=True)
        for _ in range(200):
            rx.push((131071, 131071))                    # envelope ~185k > signed18 rail
        self.assertGreater(rx.clip_count, 0)
        rx.reset()
        self.assertEqual(rx.clip_count, 0)
        self.assertEqual(rx.push((131071, 131071)), rx.push((0, 0), accept=False))
if __name__ == "__main__":
    unittest.main(verbosity=2)
