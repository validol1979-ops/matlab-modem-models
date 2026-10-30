"""Independent numerical acceptance for signal transforms and streaming convolution."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"common"/"python"))
import unittest
import numpy as np
from scipy import signal, fft
from ext_signal_farrow import Farrow
from ext_signal_psd import Periodogram
from ext_signal_spectral import DCTCodec, FFTConvolver, FFTConvolverFixed

class SpectralOracles(unittest.TestCase):
    def test_farrow_rate_schedule_polynomial(self):
        # Time-tag independently from exact fixed Q16 schedule, no DUT coefficient access.
        for degree in [3,4]:
            m=Farrow(degree=degree,step=.75)
            qstep=round(.75*65536); t=0; outputs=[]; times=[]
            for n in range(80):
                got=m.push(float(n*n)/10000)
                expected=[]
                while (t+65535)//65536<=n:
                    if t/65536>degree+1: expected.append((t/65536)**2/10000)
                    else: expected.append(None)
                    times.append(t/65536);t+=qstep
                self.assertEqual(len(got),len(expected))
                for y,want in zip(got,expected):
                    if want is not None:self.assertAlmostEqual(y.real,want,places=10)
            self.assertEqual(m.next_time,t)

    def test_psd_parseval_and_scipy(self):
        rng=np.random.default_rng(93)
        for n in [32,128]:
            x=rng.normal(size=n)
            for window in ['boxcar','hann']:
                w=signal.get_window(window,n,fftbins=False) if window=='hann' else np.ones(n)
                # Explicit taps avoid ambiguity periodic versus symmetric Hann.
                dut=Periodogram(nfft=n,fs=8000,window=w,onesided=True)
                p=np.asarray(dut.add(x))
                _,gold=signal.periodogram(x,fs=8000,window=w,detrend=False,return_onesided=True)
                np.testing.assert_allclose(p,gold,atol=1e-15,rtol=1e-12)
                self.assertAlmostEqual(float(sum(p))*8000/n,float(np.dot(x*w,x*w)/np.dot(w,w)),places=12)

    def test_dct_scipy_and_projection(self):
        rng=np.random.default_rng(94)
        for n in [32,128]:
            x=rng.normal(size=n)*1000
            for keep in [n,n//2,n//4,n//8]:
                d=DCTCodec(n,keep)
                y=np.asarray(d.encode(x)); gold=fft.dct(x,norm='ortho');gold[keep:]=0
                np.testing.assert_allclose(y,gold,atol=1e-9)
                np.testing.assert_allclose(d.decode(y),fft.idct(gold,norm='ortho'),atol=1e-9)
                yf=np.asarray(DCTCodec(n,keep,fixed=True).process(np.rint(x).astype(int)))
                self.assertLess(max(abs(yf-fft.idct(fft.dct(np.rint(x),norm='ortho')*np.r_[np.ones(keep),np.zeros(n-keep)],norm='ortho'))),50)

    def test_convolution_chunk_boundary_and_tail(self):
        rng=np.random.default_rng(95)
        for n in [32,128]:
            for length in [1,7,n]:
                h=rng.normal(size=length)+1j*rng.normal(size=length);h/=max(np.sum(abs(h)),1)
                x=rng.normal(size=173)+1j*rng.normal(size=173)
                for mode in ['save','add']:
                    m=FFTConvolver(h,n,mode)
                    out=[];k=0
                    while k<len(x):
                        count=int(rng.integers(1,18));out.extend(m.push(x[k:k+count]));k+=count
                    out.extend(m.flush());np.testing.assert_allclose(out,np.convolve(x,h),atol=1e-11)
                    self.assertEqual(len(out),len(x)+len(h)-1)
                    self.assertEqual(len(m.flush()),0)
                    with self.assertRaises(RuntimeError):m.push([0])

if __name__=='__main__': unittest.main()
