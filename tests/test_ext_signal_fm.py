import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'/'python'))
import math
import unittest
import numpy as np
from ext_signal_fm import FMModulator,FMDemodulator,atan2_word

class TestFM(unittest.TestCase):
    def test_cordic_independent_atan2(self):
        rng=np.random.default_rng(891);vectors=[(10**9,0),(-10**9,0),(0,10**9),(0,-10**9)]
        vectors+=list(map(tuple,rng.integers(-10**9,10**9,size=(2000,2))))
        errors=[]
        for x,y in vectors:
            gold=round(math.atan2(y,x)*2**32/(2*math.pi));errors.append(abs(atan2_word(x,y)-gold))
        self.assertLess(max(errors),20)
        with self.assertRaises(ValueError):atan2_word(0,0)
    def test_float_phase_and_discriminator(self):
        n=np.arange(4000);x=.1*np.sin(2*np.pi*1000*n/400000)
        tx=FMModulator(preemphasis=False);y=np.array(tx.process(x))
        gold=np.exp(2j*np.pi*75000/400000*np.cumsum(x));np.testing.assert_allclose(y,gold,atol=1e-12)
        rx=FMDemodulator(deemphasis=False);a=np.array(rx.process(y));np.testing.assert_allclose(a[1:],x[1:],atol=2e-14)
        self.assertAlmostEqual(float(max(abs(y))),1)
    def test_matched_emphasis_float_and_fixed(self):
        n=np.arange(12000);x=.02*np.sin(2*np.pi*1000*n/400000)+.01*np.cos(2*np.pi*2500*n/400000)
        y=np.array(FMDemodulator().process(FMModulator().process(x)));self.assertLess(max(abs(y[1000:]-x[1000:])),1e-12)
        q=np.rint(x*131071).astype(int);tx=FMModulator(fixed=True);rx=FMDemodulator(fixed=True)
        a=np.array(rx.process(tx.process(q)));self.assertLess(max(abs(a[1000:]-q[1000:])),25);self.assertEqual(tx.clippings,0)
    def test_signed_frequency_noise_and_cfo(self):
        tx_np=FMModulator(fs=np.int64(400000),deviation=np.int64(75000),preemphasis=False,fixed=True)
        tx_py=FMModulator(preemphasis=False,fixed=True)
        self.assertEqual(tx_np.process([30000]*50),tx_py.process([30000]*50))
        for audio in [-30000,30000]:
            y=FMModulator(preemphasis=False,fixed=True).process([audio]*4000)
            a=FMDemodulator(deemphasis=False,fixed=True).process(y)
            self.assertLess(abs(np.mean(a[100:])-audio),1)
        n=np.arange(4000);rng=np.random.default_rng(11)
        x=.03*np.sin(2*np.pi*.002*n);y=np.array(FMModulator(preemphasis=False).process(x))*np.exp(2j*np.pi*1000*n/400000)
        noisy=y+.0001*(rng.normal(size=len(n))+1j*rng.normal(size=len(n)))
        a=np.array(FMDemodulator(deemphasis=False).process(noisy));self.assertLess(np.std(a[1:]-x[1:]-1000/75000),.001)
    def test_zero_stall_reset_invalid_and_clipping(self):
        for fixed in [False,True]:
            tx=FMModulator(fixed=fixed);rx=FMDemodulator(fixed=fixed);v=100 if fixed else .1
            iq=tx.push(v);tx.push(v,False);p=tx.phase
            for bad in [True,1j,float('nan'),131072 if fixed else 1.1]:
                with self.assertRaises(ValueError):tx.push(bad)
                self.assertEqual(tx.phase,p)
            rx.push(iq);self.assertFalse(rx.valid);rx.push(iq);self.assertTrue(rx.valid)
            old=rx.previous;rx.push(iq,False);self.assertEqual(rx.previous,old)
            self.assertEqual(rx.push((0,0) if fixed else 0),0);self.assertFalse(rx.valid);self.assertIsNone(rx.previous)
            tx.push(-131071 if fixed else -1);self.assertGreater(tx.clippings,0)
            tx.reset();rx.reset();self.assertEqual(tx.phase,0);self.assertEqual(rx.last,0)
        for kw in [dict(fs=0),dict(deviation=200000),dict(tau=0),dict(fixed=1),dict(fs=400000.5,fixed=True),dict(fs=2**30,deviation=75000,fixed=True)]:
            with self.assertRaises(ValueError):FMModulator(**kw)
    def test_discriminator_phase_wrap_boundaries(self):
        angles=[0,np.pi-.1,-np.pi+.1,np.pi-.1,-.1,.1,np.pi,-np.pi+.001]
        iq=[(round(100000*np.cos(a)),round(100000*np.sin(a))) for a in angles]
        fixed=FMDemodulator(deemphasis=False,fixed=True).process(iq)
        reference=FMDemodulator(deemphasis=False).process([complex(*v)/131071 for v in iq])
        self.assertLess(max(abs(np.array(fixed)-np.array(reference)*131071)),2)
        self.assertGreater(fixed[2],0) # wrapped change near +.2rad, not -2pi
        self.assertLess(fixed[3],0)

if __name__=='__main__':unittest.main()
