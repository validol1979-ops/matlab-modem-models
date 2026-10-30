"""Coordinator's independent analytic/SciPy acceptance gates (models only)."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"common"/"python"))
import copy
import math
import unittest
import numpy as np
from scipy import signal
from ext_signal_core import DDS, AnalyticSignal, AnalyticSignalFixed
from ext_signal_sos import SOSFilter, SOSFilterFixed

class CoreOracles(unittest.TestCase):
    def test_dds_ideal_and_stall(self):
        d = DDS(0x12345679)
        phases=[]; values=[]
        for n in range(4096):
            p=d.phase; phases.append(p); values.append(complex(*d.next()))
            held=d.phase; d.next(False); self.assertEqual(d.phase,held)
        ideal=np.exp(2j*np.pi*np.array(phases,dtype=float)/2**32)*131071
        self.assertLess(np.max(np.abs(np.array(values)-ideal)),202)
        d.configure(step=0,phase=0x40000000)
        self.assertEqual(d.next(),(0,131071))
        old=(d.phase,d.step)
        with self.assertRaises((ValueError,TypeError)): d.configure(step=1,phase=-1)
        self.assertEqual((d.phase,d.step),old)

    def test_hilbert_positive_frequency_convention(self):
        for taps in [31,63]:
            n=np.arange(4096); x=.2*np.cos(2*np.pi*.125*n)
            y=np.array(AnalyticSignal(taps).process(x))
            delay=(taps-1)//2
            target=.2*np.exp(2j*np.pi*.125*(n-delay))
            self.assertLess(np.max(np.abs(y[2*taps:]-target[2*taps:])),.0015)
            # Explicit positive/negative tone projections, independent FFT analytic oracle.
            yp=y[2*taps:]; tt=n[2*taps:]-delay
            a=abs(np.sum(yp*np.exp(-2j*np.pi*.125*tt)))
            b=abs(np.sum(yp*np.exp(2j*np.pi*.125*tt)))
            self.assertGreater(20*np.log10(a/max(b,1e-15)),40)
            q=np.rint(x*100000).astype(int)
            z=np.array(AnalyticSignalFixed(taps).process(q))
            self.assertLess(np.max(np.abs(z[:,0]+1j*z[:,1]-y*100000)),5)

    def test_sos_float_independent_complex(self):
        rng=np.random.default_rng(912)
        x=rng.normal(size=1024)+1j*rng.normal(size=1024)
        for sections in [1,2,4]:
            for kind in ['lowpass','highpass']:
                sos=signal.butter(2*sections,.23,btype=kind,output='sos')
                m=SOSFilter(sos)
                actual=np.array(m.process(x))
                self.assertLess(np.max(abs(actual-signal.sosfilt(sos,x))),1e-11)
                m.reset(); self.assertEqual(m.push(0),0)

    def test_sos_fixed_quantized_transfer(self):
        # Low-amplitude wideband verifies the quantized *runtime* against an independent LTI oracle.
        rng=np.random.default_rng(91)
        x=rng.integers(-3000,3001,size=1024)
        for sections in [1,2,4]:
            sos=signal.butter(2*sections,.3,output='sos')
            m=SOSFilterFixed(sos)
            pairs=m.process([int(v) for v in x])
            actual=np.array([p[0] for p in pairs])
            self.assertLess(np.sqrt(np.mean((actual-signal.sosfilt(sos,x))**2)),12)
            self.assertTrue(all(p[1]==0 for p in pairs))
            m.reset(); self.assertEqual(m.push(0),(0,0))

if __name__=='__main__': unittest.main()
