import math
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"common"/"python"))
import unittest

import numpy as np

from ext_signal_core import AMP, PHASE_MOD, DDS

Q = PHASE_MOD // 4


class TestDDS(unittest.TestCase):
    def test_quadrants_and_wrap(self):
        d = DDS(step=Q)
        self.assertEqual([d.next() for _ in range(5)],
                         [(AMP, 0), (0, AMP), (-AMP, 0), (0, -AMP), (AMP, 0)])
        d = DDS(step=Q, phase=PHASE_MOD - Q)
        self.assertEqual((d.next(), d.next(), d.phase), ((0, -AMP), (AMP, 0), Q))

    def test_negative_frequency_conjugate(self):
        pos, neg = DDS(step=37 << 20), DDS(step=(-(37 << 20)) % PHASE_MOD)
        for _ in range(100):
            (i1, q1), (i2, q2) = pos.next(), neg.next()
            self.assertEqual((i1, q1), (i2, -q2))

    def test_stall(self):
        d = DDS(step=Q, phase=5)
        self.assertEqual((d.next(accept=False), d.phase), ((AMP, 0), 5))
        d.next(accept=True)
        self.assertEqual(d.phase, 5 + Q)

    def test_invalid_inputs(self):
        for bad in (-1, PHASE_MOD, 1.0, True, "3", None):
            with self.assertRaises((TypeError, ValueError)):
                DDS(step=bad)
        with self.assertRaises(ValueError):
            DDS(step=1, lut_bits=1)
        with self.assertRaises(TypeError):
            DDS(step=1, lut_bits=12.0)
        for bad in (1, 0, "yes", None):
            with self.assertRaises(TypeError):
                DDS(step=1).next(accept=bad)

    def test_configure_atomic(self):
        d = DDS(step=7, phase=9)
        with self.assertRaises(ValueError):
            d.configure(step=5, phase=-1)
        with self.assertRaises(TypeError):
            d.configure(step=5.0)
        self.assertEqual((d.step, d.phase), (7, 9))
        d.configure(step=5)
        d.configure(phase=PHASE_MOD - 1)
        self.assertEqual((d.step, d.phase), (5, PHASE_MOD - 1))

    def test_reset(self):
        d = DDS(step=Q)
        d.next()
        d.reset()
        self.assertEqual(d.phase, 0)
        d.reset(phase=Q)
        self.assertEqual(d.next(), (0, AMP))
        with self.assertRaises(ValueError):
            d.reset(phase=PHASE_MOD)

    def test_value_float_and_rom_budget(self):
        # Budget: ROM sample within 1.5 LSB of ideal phasor * AMP at all LUT entries.
        d, err = DDS(step=0), 0.0
        for k in range(4096):
            d.reset(phase=k << 20)
            i, q = d.next()
            err = max(err, abs(complex(i, q) - AMP * d.value_float()))
        self.assertLessEqual(err, 1.5)
        d = DDS(step=12345, phase=987654321)
        for _ in range(50):
            a = 2 * math.pi * d.phase / PHASE_MOD
            self.assertAlmostEqual(d.value_float(), complex(math.cos(a), math.sin(a)), places=12)
            d.next()

    def test_sfdr_coherent(self):
        # N=4096, coherent bin k=37; budget SFDR >= 90 dB.
        n, k = 4096, 37
        d = DDS(step=k * (PHASE_MOD // n))
        spec = np.abs(np.fft.fft([complex(*d.next()) for _ in range(n)])) / n
        self.assertGreaterEqual(20 * math.log10(spec[k] / np.max(np.delete(spec, k))), 90.0)
        self.assertEqual(int(np.argmax(spec)), k)


class TestDDSPhaseTruncation(unittest.TestCase):
    def test_off_grid_coherent_tone(self):
        n,k=65536,37
        for sign in [1,-1]:
            d=DDS((sign*k*(PHASE_MOD//n))%PHASE_MOD,phase=123456789)
            phases=[];x=[]
            for _ in range(n):
                phases.append(d.phase);x.append(complex(*d.next()))
            x=np.array(x);ideal=AMP*np.exp(2j*np.pi*np.array(phases,dtype=float)/PHASE_MOD)
            self.assertLessEqual(max(abs(x-ideal)),2*np.pi*AMP/4096+1)
            s=abs(np.fft.fft(x));i=(sign*k)%n
            self.assertGreater(20*np.log10(s[i]/max(np.delete(s,i))),71.0)

if __name__ == "__main__":
    unittest.main()
