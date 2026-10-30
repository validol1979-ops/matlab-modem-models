"""Streaming FFT linear convolution, overlap-save/add, float and integer pipelines.

Abood DFT convolution motivates zero padding; streaming modes are project-derived.
Fixed X=FFT(x<<5)/N,H=FFT(Q17 taps <<5)/N; P=round(X*H*N/2**22),
then existing unnormalized inverse yields Q5 convolution, rounded once to input units. Internal FFT
butterflies/twiddles are actual fft_fixed integer arithmetic. No timing claims.
"""
import numbers
import numpy as np
import fft_fixed
from ext_signal_dct import DCTCodec


def _pair(x):
    if isinstance(x,numbers.Integral) and not isinstance(x,(bool,np.bool_)):x=(x,0)
    try:
        if len(x)!=2:raise ValueError('IQ pair')
        if any(isinstance(v,(bool,np.bool_)) or not isinstance(v,numbers.Integral) or not -131072<=v<=131071 for v in x):raise ValueError('signed18 IQ')
        return tuple(int(v) for v in x)
    except TypeError:raise ValueError('signed18 integer or IQ pair') from None


class FFTConvolver:
    fixed=False
    def __init__(self,taps,nfft,mode='save'):
        self.closed=True;self.configure(taps,nfft,mode)
    def _sample(self,x):
        if isinstance(x,(bool,np.bool_)) or not isinstance(x,numbers.Number) or not np.isfinite(x):raise ValueError('finite numeric sample')
        return complex(x)
    def configure(self,taps,nfft,mode='save'):
        if hasattr(self,'count') and self.count and not self.closed:raise RuntimeError('configure only fresh/closed frame')
        if isinstance(nfft,(bool,np.bool_)) or not isinstance(nfft,numbers.Integral) or nfft<2 or nfft&(nfft-1):raise ValueError('FFT length poweroftwo >=2')
        if mode not in ('save','add'):raise ValueError('save/add mode')
        try:h=[self._sample(v) for v in taps]
        except TypeError:raise ValueError('taps sequence') from None
        if not 1<=len(h)<=nfft:raise ValueError('1<=M<=N')
        self.nfft,self.taps,self.mode=int(nfft),h,mode
        self.m=len(h);self.hop=self.nfft-self.m+1
        zero=(0,0) if self.fixed else 0j
        if self.fixed:self.spectrum=fft_fixed.forward([tuple(v<<5 for v in pair) for pair in h]+[zero]*(self.nfft-self.m),in_width=23,width=24)
        else:self.spectrum=np.fft.fft(h,self.nfft)
        self.reset()
    def reset(self):
        zero=(0,0) if self.fixed else 0j
        self.history=[zero]*(self.m-1);self.overlap=[zero]*(self.m-1)
        self.pending=[];self.count=0;self.emitted=0;self.closed=False;self.clippings=0
    def _clip(self,v,width):
        lim=(1<<(width-1))-1
        if v < -lim-1 or v>lim:self.clippings+=1
        return min(lim,max(-lim-1,v))
    def _fft_block(self,x):
        return list(np.fft.ifft(np.fft.fft(x)*self.spectrum))
    def _block(self,block):
        zero=(0,0) if self.fixed else 0j
        if self.mode=='save':
            x=self.history+block;y=self._fft_block(x)
            self.history=x[-(self.m-1):] if self.m>1 else []
            out=y[self.m-1:]
        else:
            y=self._fft_block(block+[zero]*(self.m-1))
            for i,z in enumerate(self.overlap):
                y[i]=tuple(self._clip(a+b,24) for a,b in zip(y[i],z)) if self.fixed else y[i]+z
            out=y[:self.hop];self.overlap=y[self.hop:self.hop+self.m-1]
        if self.fixed:return [tuple(self._clip((v+16)>>5,18) for v in pair) for pair in out]
        return out
    def push(self,samples):
        if self.closed:raise RuntimeError('closed frame; reset required')
        try:x=[self._sample(v) for v in samples]
        except TypeError:raise ValueError('sample sequence') from None
        self.count+=len(x);self.pending.extend(x);out=[]
        while len(self.pending)>=self.hop:
            block=self.pending[:self.hop];del self.pending[:self.hop]
            out.extend(self._block(block));self.emitted+=self.hop
        return out
    def flush(self):
        if self.closed:return []
        self.closed=True
        if not self.count:return []
        remaining=self.count+self.m-1-self.emitted;out=[]
        zero=(0,0) if self.fixed else 0j
        while len(out)<remaining:
            block=self.pending[:self.hop];del self.pending[:self.hop]
            block.extend([zero]*(self.hop-len(block)));out.extend(self._block(block))
        self.pending=[];self.emitted+=remaining
        return out[:remaining]


class FFTConvolverFixed(FFTConvolver):
    """Signed18 IQ and Q17 taps; exact5guardbit lifts,24bit FFT,
    23bit Q5 product,24bit Q5 OLA, rounded18bit output.

    Python integer products are exact before half-up Q22 rounding (5 coefficient-FFT guard bits). FFT internal
    saturation uses fft_fixed symmetric24 rails; product/output/OLA clipping counted.
    No coefficient normalization; headroom is the caller's filter/signal design.
    """
    fixed=True
    def _sample(self,x):return _pair(x)
    def _fft_block(self,x):
        f=fft_fixed.forward([tuple(v<<5 for v in pair) for pair in x],in_width=23,width=24);p=[]
        for (a,b),(c,d) in zip(f,self.spectrum):
            p.append((self._clip(((a*c-b*d)*self.nfft+2**21)>>22,23),self._clip(((a*d+b*c)*self.nfft+2**21)>>22,23)))
        return fft_fixed.inverse(p,in_width=23,width=24)
