import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'/'python'))
import unittest
import numpy as np
from ext_signal_ddc import DDC

class TestDDC(unittest.TestCase):
    def test_float_oracle_and_count(self):
        rng=np.random.default_rng(819)
        for length in [0,1,9,10,11,39,40,41,4001]:
            x=rng.integers(-20000,20001,size=length);m=DDC(step=round(.21*2**32))
            y=m.process(x);gold=m.reference(x)
            self.assertEqual(len(y),(length//10+3)//4)
            self.assertEqual(len(y),len(gold))
            if len(y):self.assertLess(max(abs(np.array(y)[:,0]+1j*np.array(y)[:,1]-gold)),80)
    def test_passband_and_alias_rejection(self):
        n=np.arange(24000);carrier=.2;step=round(carrier*2**32);gains=[]
        for offset in [.002,.005,.008,.035,.045]:
            x=np.rint(20000*np.cos(2*np.pi*(carrier+offset)*n)).astype(int);m=DDC(step)
            y=np.array(m.process(x));z=y[:,0]+1j*y[:,1]
            # Real input positive side is half amplitude after complex downconversion.
            amp=float(np.sqrt(np.mean(abs(z[200:])**2)));gains.append(20*np.log10(max(amp,1e-10)/10000))
            self.assertLess(max(abs(z-m.reference(x))),80)
        self.assertLess(max(abs(v) for v in gains[:3]),1)
        self.assertTrue(all(v<-35 for v in gains[3:]))
    def test_reset_stall_invalid_close(self):
        m=DDC();m.push(50);p=m.dds.phase;c=m.accepted
        self.assertEqual(m.push(100,False),[]);self.assertEqual((m.dds.phase,m.accepted),(p,c))
        for x in [True,1.0,131072,float('nan')]:
            with self.assertRaises(ValueError):m.push(x)
            self.assertEqual(m.accepted,c)
        with self.assertRaises(ValueError):m.configure(-1)
        self.assertEqual(m.accepted,c)
        self.assertEqual(m.flush(),[]);self.assertEqual(m.flush(),[])
        with self.assertRaises(RuntimeError):m.push(0)
        m.reset();self.assertEqual(m.accepted,0)
        self.assertEqual(sum(v[0] for v in m.compensation_q),131072)
        self.assertEqual(sum(v[0] for v in m.halfband_q),131072)
    def test_impulse_and_chunking(self):
        x=[10000]+[0]*3999;a=DDC();b=DDC();expected=a.process(x);got=[]
        for i in range(0,len(x),37):got.extend(b.process(x[i:i+37]))
        self.assertEqual(got,expected)
        z=np.array(got);self.assertLess(max(abs(z[:,0]+1j*z[:,1]-a.reference(x))),80)
if __name__=='__main__':unittest.main()
