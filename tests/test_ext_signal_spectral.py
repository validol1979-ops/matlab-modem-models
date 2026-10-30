import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'/'python'))
import copy
import unittest
import numpy as np
from ext_signal_spectral import FFTConvolver,FFTConvolverFixed

class TestFFTConvolution(unittest.TestCase):
    def test_direct_oracle_arbitrary_chunks_full_tail(self):
        rng=np.random.default_rng(888)
        for n in [32,128]:
            for m in [1,7,n]:
                h=rng.normal(size=m)+1j*rng.normal(size=m);h/=sum(abs(h));x=rng.normal(size=173)+1j*rng.normal(size=173)
                for mode in ['save','add']:
                    dut=FFTConvolver(h,n,mode);out=[];k=0
                    while k<len(x):
                        step=int(rng.integers(1,18));out.extend(dut.push(x[k:k+step]));k+=step
                    out.extend(dut.flush());np.testing.assert_allclose(out,np.convolve(x,h),atol=2e-14)
                    self.assertEqual(len(out),len(x)+m-1);self.assertEqual(dut.flush(),[])
    def test_fixed_direct_and_stage_quantization(self):
        rng=np.random.default_rng(89);errors=[];differs=False
        for n in [32,128]:
            for m in [1,7,n]:
                h=rng.normal(size=m)+1j*rng.normal(size=m);h/=sum(abs(h))*1.5
                hq=[(round(v.real*2**17),round(v.imag*2**17)) for v in h];hc=np.array([complex(*v)/2**17 for v in hq])
                x=rng.integers(-10000,10001,size=(173,2));xc=x[:,0]+1j*x[:,1]
                for mode in ['save','add']:
                    dut=FFTConvolverFixed(hq,n,mode);out=dut.push(x);out.extend(dut.flush());a=np.array(out);z=a[:,0]+1j*a[:,1];gold=np.convolve(xc,hc)
                    e=float(max(abs(z-gold)));errors.append(e);self.assertLess(e,120)
                    direct=np.floor(np.column_stack((gold.real,gold.imag))+.5).astype(int)
                    differs=differs or not np.array_equal(a,direct)
        self.assertTrue(differs)
    def test_singleton_partial_empty_closed_and_config(self):
        for cls,h,x in [(FFTConvolver,[1],[1,2,3]),(FFTConvolverFixed,[131071],[(100,0),(200,0),(300,0)])]:
            d=cls(h,32);self.assertEqual(d.flush(),[])
            with self.assertRaises(RuntimeError):d.push(x)
            d.reset();a=d.push(x);a.extend(d.flush());self.assertEqual(len(a),len(x))
            d.configure(h,32,'add');self.assertFalse(d.closed)
            d.push(x)
            with self.assertRaises(RuntimeError):d.configure(h,32)
            d.reset();before=repr(d.__dict__)
            with self.assertRaises(ValueError):d.push(x+[True])
            self.assertEqual(repr(d.__dict__),before)
        for h,n in [([],32),([1]*33,32),([1],33)]:
            with self.assertRaises(ValueError):FFTConvolver(h,n)
    def test_clipping_and_zero_padding_regression(self):
        d=FFTConvolverFixed([131071]*7,32,'add');x=[(100000,0)]*100
        y=d.push(x)+d.flush();self.assertGreater(d.clippings,0);self.assertTrue(all(-131072<=v<=131071 for p in y for v in p))
        d=FFTConvolver([1,2,3,4],4,'save');y=d.push([1,2,3])+d.flush()
        np.testing.assert_allclose(y,[1,4,10,16,17,12],atol=1e-12)
if __name__=='__main__':unittest.main()
