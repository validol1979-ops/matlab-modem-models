import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'/'python'))
import unittest
import numpy as np
from ext_signal_ssb import SSBModulator,SSBDemodulator

class TestSSB(unittest.TestCase):
    def test_sidebands_and_translation(self):
        n=np.arange(4160);x=.2*np.cos(2*np.pi*.125*n)+.1*np.cos(2*np.pi*.2*n)
        for side,sign in [('usb',1),('lsb',-1)]:
            # Coherent carrier .1; skip160 to get4000-sample coherent spectral segment.
            step=round(.1*2**32);y=np.array(SSBModulator(side,step).process(x))[160:]
            spectrum=abs(np.fft.fft(y));N=len(y)
            q=np.rint(x*131071).astype(int); yi=np.array(SSBModulator(side,step,fixed=True).process(q))[160:]
            si=abs(np.fft.fft(yi[:,0]+1j*yi[:,1]))
            for f in [.125,.2]:
                wanted=round(((.1+sign*f)%1)*N);image=round(((.1-sign*f)%1)*N)
                self.assertGreater(20*np.log10(spectrum[wanted]/spectrum[image]),40)
                self.assertGreater(20*np.log10(si[wanted]/si[image]),40)
    def test_coherent_loopback_fixed_and_cfo(self):
        n=np.arange(4160);x=.08*np.cos(2*np.pi*.125*n)+.05*np.cos(2*np.pi*.2*n);q=np.rint(x*131071).astype(int)
        for side in ['usb','lsb']:
            step=round(.1*2**32);tx=SSBModulator(side,step);rx=SSBDemodulator(step)
            y=np.array(rx.process(tx.process(x)));np.testing.assert_allclose(y[31:],x[:-31],atol=1e-14)
            tx=SSBModulator(side,step,fixed=True);rx=SSBDemodulator(step,True)
            yf=np.array(rx.process(tx.process(q)));self.assertLess(max(abs(yf[31:]-q[:-31])),30)
        # A receiver CFO translates complex USB frequencies directly.
        y=np.array(SSBModulator('usb',0).process(.2*np.cos(2*np.pi*.125*n)))
        z=np.array(SSBDemodulator(round(.025*2**32)).process(y))[160:]
        self.assertEqual(np.argmax(abs(np.fft.rfft(z))),400) # (.125-.025)*4000
    def test_stall_reset_and_invalid_atomic(self):
        for fixed in [False,True]:
            tx=SSBModulator(step=17,fixed=fixed);rx=SSBDemodulator(17,fixed)
            a=tx.push(100 if fixed else .1);rx.push(a)
            p=tx.dds.phase;state=list(tx.analytic._z);old=tx.last
            self.assertEqual(tx.push(0,False),old);self.assertEqual(tx.dds.phase,p)
            for bad in [True,1j,float('nan'),131072 if fixed else 1.1]:
                with self.assertRaises((ValueError,TypeError)):tx.push(bad)
                self.assertEqual(tx.dds.phase,p);self.assertEqual(tx.analytic._z,state)
            tx.reset();rx.reset();self.assertEqual(tx.dds.phase,0);self.assertEqual(rx.push((0,0) if fixed else 0),0)
        for kw in [dict(sideband='other'),dict(step=-1),dict(numtaps=32),dict(fixed=1)]:
            with self.assertRaises((ValueError,TypeError)):SSBModulator(**kw)
if __name__=='__main__':unittest.main()
