import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'/'python'))
import unittest
import numpy as np
from scipy import signal
from ext_signal_psd import Periodogram

class TestPSD(unittest.TestCase):
    def test_scipy_parseval_noise_complex_and_average(self):
        rng=np.random.default_rng(89)
        for n in [32,128]:
            for real in [True,False]:
                for k in [1,2,16]:
                    for win in ['boxcar','hann']:
                        w=np.ones(n) if win=='boxcar' else np.hanning(n)
                        m=Periodogram(n,8000,win,k,real);gold=[]
                        for i in range(k):
                            x=rng.normal(size=n)+(0 if real else 1j*rng.normal(size=n))
                            _,p=signal.periodogram(x,fs=8000,window=w,detrend=False,return_onesided=real)
                            gold.append(p);y=m.add(x)
                            if i<k-1:self.assertIsNone(y)
                        np.testing.assert_allclose(y,np.mean(gold,axis=0),rtol=1e-12,atol=1e-15)
    def test_fixed_power_and_scaling(self):
        for n in [32,128]:
            for k in [1,2,16]:
                for x in [np.ones(n,dtype=int)*20000,(-1)**np.arange(n)*20000,np.rint(20000*np.cos(2*np.pi*3*np.arange(n)/n)).astype(int)]:
                    m=Periodogram(n,8000,'boxcar',k,True,True)
                    for _ in range(k):y=m.add(x)
                    self.assertTrue(all(isinstance(v,int) for v in m.last_power))
                    self.assertLess(abs(sum(y)*8000/n-np.mean(x*x))/np.mean(x*x),.001)
                    _,gold=signal.periodogram(x,8000,window='boxcar',detrend=False)
                    self.assertLess(sum(abs(y-gold))/sum(gold),.001)
    def test_hann_fixed_noise_and_integer_window_oracle(self):
        rng=np.random.default_rng(29)
        for n in [32,128]:
            x=rng.integers(-40000,40001,size=n);m=Periodogram(n,1,'hann',fixed=True)
            y=m.add(x);q=np.rint(np.hanning(n)*2**17).astype(int)
            z=np.array([(int(a)*int(b)+2**16)>>17 for a,b in zip(x,q)])
            gold=abs(np.fft.fft(z))**2/sum((q/2**17)**2)
            self.assertLess(sum(abs(y-gold))/sum(gold),.002)
    def test_invalid_atomic_and_dc_nyquist_no_double(self):
        m=Periodogram(32,1,'boxcar',2,True,True);m.add([1000]*32);old=m._count,list(m._sum)
        for bad in [[0]*31,[True]*32,[1.0]*32,[(1,0)]*32]:
            with self.assertRaises(ValueError):m.add(bad)
            self.assertEqual((m._count,m._sum),old)
        y=m.add([1000]*32);self.assertEqual(y[0],32*1000**2)
        z=Periodogram(32,1,'boxcar',onesided=True,fixed=True).add([1000*(-1)**n for n in range(32)])
        self.assertEqual(z[-1],32*1000**2)
        m.reset();self.assertEqual(m._count,0)
        for kw in [dict(nfft=33),dict(fs=0),dict(averages=3),dict(window=[0]*32),dict(window=[1]*31)]:
            with self.assertRaises(ValueError):Periodogram(**kw)
if __name__=='__main__':unittest.main()
