"""Windowed periodogram with batch averages K1/2/16 and explicit FFT scaling.

Abood DFT/PSD source; project Fs*windowenergy normalization. Fixed runtime uses
unsigned Q17 window, signed18 rounded samples, existing integer Q16-twiddle FFT/N,
full-width Python-integer squared magnitudes and accumulated powers. Conversion to
physical PSD (raw count squared/Hz) occurs only after integer averaging numerator.
"""
import numbers
import numpy as np
import fft_fixed


class Periodogram:
    def __init__(self,nfft=32,fs=1,window='hann',averages=1,onesided=False,fixed=False):
        if isinstance(nfft,(bool,np.bool_)) or not isinstance(nfft,numbers.Integral) or nfft<2 or nfft&(nfft-1):raise ValueError('power-of-two nfft >=2')
        if isinstance(fs,(bool,np.bool_)) or not isinstance(fs,numbers.Real) or not np.isfinite(fs) or fs<=0:raise ValueError('positive finite Fs')
        if isinstance(averages,(bool,np.bool_)) or not isinstance(averages,numbers.Integral) or averages not in (1,2,16):raise ValueError('K1/2/16')
        if type(onesided) is not bool or type(fixed) is not bool:raise ValueError('bool flags')
        if isinstance(window,str):
            if window not in ('hann','boxcar'):raise ValueError('window')
            w=np.hanning(nfft) if window=='hann' else np.ones(nfft)
        else:
            if np.iscomplexobj(window):raise ValueError('real window')
            w=np.asarray(window,dtype=float)
        if w.ndim!=1 or len(w)!=nfft or not np.isfinite(w).all() or np.any(w<0) or np.any(w>1) or not np.any(w):raise ValueError('window in[0,1], nonzero energy')
        self.nfft,self.fs,self.averages,self.onesided,self.fixed=int(nfft),float(fs),int(averages),onesided,fixed
        self.window=w.copy();self.window_q=[round(float(v)*2**17) for v in w]
        if fixed and not any(self.window_q):raise ValueError('quantized window energy zero')
        self.energy=sum((v/2**17)**2 for v in self.window_q) if fixed else float(sum(w*w))
        self.reset()
    def reset(self):self._count=0;self._sum=None;self.last_power=None
    def add(self,frame):
        try:rows=list(frame)
        except TypeError:raise ValueError('frame required') from None
        if len(rows)!=self.nfft:raise ValueError('frame length')
        if self.fixed:
            vals=[];isreal=True
            for x in rows:
                if isinstance(x,numbers.Integral) and not isinstance(x,(bool,np.bool_)):pair=(x,0)
                else:
                    try:
                        if len(x)!=2:raise ValueError('IQ pair')
                        pair=tuple(x);isreal=False
                    except TypeError:raise ValueError('integer sample') from None
                if any(isinstance(v,(bool,np.bool_)) or not isinstance(v,numbers.Integral) or not -131072<=v<=131071 for v in pair):raise ValueError('signed18 sample')
                vals.append(tuple(int(v) for v in pair))
            if self.onesided and not isreal:raise ValueError('one-sided needs real samples')
            z=[]
            for pair,w in zip(vals,self.window_q):z.append(tuple(min(131071,max(-131072,(v*w+2**16)>>17)) for v in pair))
            f=fft_fixed.forward(z,in_width=18,width=24)
            power=[int(a)**2+int(b)**2 for a,b in f]
            scale=self.nfft**2/(self.averages*self.fs*self.energy)
        else:
            a=np.asarray(rows)
            if a.ndim!=1 or a.dtype.kind=='b':raise ValueError('one-dimensional numeric samples')
            try:a=a.astype(complex if np.iscomplexobj(a) else float)
            except (ValueError,TypeError):raise ValueError('numeric samples') from None
            if not np.isfinite(a).all():raise ValueError('finite samples')
            if self.onesided and np.iscomplexobj(a):raise ValueError('one-sided needs real samples')
            power=list(abs(np.fft.fft(a*self.window))**2);scale=1/(self.averages*self.fs*self.energy)
        # Mutation starts only after complete validation and transform.
        self.last_power=tuple(power)
        self._sum=power if self._sum is None else [a+b for a,b in zip(self._sum,power)]
        self._count+=1
        if self._count<self.averages:return None
        y=np.array([v*scale for v in self._sum]);self._sum=None;self._count=0
        if self.onesided:y=y[:self.nfft//2+1];y[1:-1]*=2
        return y
