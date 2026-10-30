import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'/'python'))
import unittest
import numpy as np
from scipy import fft
from ext_signal_dct import DCTCodec

class TestDCT(unittest.TestCase):
    def test_scipy_energy_and_projection(self):
        rng=np.random.default_rng(438)
        for n in [32,128]:
            for x in [rng.normal(size=n)*1000,np.ones(n),np.eye(n)[0],np.cos(np.arange(n)*.8)]:
                gold=fft.dct(x,norm='ortho')
                self.assertAlmostEqual(float(np.sum(gold**2)),float(np.sum(x*x)),places=5)
                for keep in [n,n//2,n//4,n//8]:
                    m=DCTCodec(n,keep);c=np.array(m.encode(x));g=gold.copy();g[keep:]=0
                    np.testing.assert_allclose(c,g,atol=2e-9)
                    y=m.decode(c);np.testing.assert_allclose(y,fft.idct(g,norm='ortho'),atol=2e-9)
                    self.assertAlmostEqual(float(np.sum((y-x)**2)),float(sum(gold[keep:]**2)),places=5)
    def test_fixed_pipeline_and_integer_oracle(self):
        rng=np.random.default_rng(81)
        for n in [32,128]:
            x=rng.integers(-5000,5001,size=n)
            for keep in [n,n//2,n//4,n//8]:
                m=DCTCodec(n,keep,True);encoded=m.encode(x)
                # Independent mathematical matrix and Python integer accumulation.
                c=[[round((1/np.sqrt(n) if k==0 else np.sqrt(2/n))*np.cos(np.pi*(j+.5)*k/n)*2**17) for j in range(n)] for k in range(n)]
                g=[(sum(a*int(b) for a,b in zip(row,x))+2**16)>>17 for row in c];g[keep:]=[0]*(n-keep)
                self.assertEqual(encoded,g)
                ideal=fft.dct(x,norm='ortho');ideal[keep:]=0
                self.assertLess(max(abs(np.array(m.decode(encoded))-fft.idct(ideal,norm='ortho'))),50)
    def test_rails_clipping_and_tail(self):
        for n in [32,128]:
            m=DCTCodec(n,fixed=True);x=[131071]*n;c=m.encode(x)
            self.assertGreater(c[0],131071);self.assertLess(c[0],2**23)
            y=m.decode([(2**23-1)]*n);self.assertGreater(m.clippings,0)
            self.assertTrue(all(-131072<=v<=131071 for v in y))
            self.assertEqual(len(m.process_stream([0]*(n+1),'drop')),n)
            self.assertEqual(len(m.process_stream([0]*(n+1),'pad')),2*n)
            with self.assertRaises(ValueError):m.process_stream([0]*(n+1),'error')
    def test_validation_atomic(self):
        m=DCTCodec(32,8);old=m.n,m.keep,m.matrix.copy()
        for kw in [(33,8),(32,3),(True,8)]:
            with self.assertRaises(ValueError):m.configure(*kw)
            self.assertEqual((m.n,m.keep),old[:2]);np.testing.assert_array_equal(m.matrix,old[2])
        for x in [[0]*31,[float('nan')]*32,[1j]*32,np.zeros((32,1)),np.zeros((1,32))]:
            with self.assertRaises(ValueError):m.encode(x)
        with self.assertRaises(ValueError):m.decode(np.zeros((32,1)))
        f=DCTCodec(fixed=True)
        for x in [[True]*32,[1.0]*32,[2**17]*32]:
            with self.assertRaises(ValueError):f.encode(x)
if __name__=='__main__':unittest.main()
