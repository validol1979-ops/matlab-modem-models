"""Hilbert phasing SSB USB/LSB with coherent complex-IQ reception.

Laufer source describes SSB family; precise phasing algorithm is project-derived.
Runtime fixed path reuses integer Hilbert FIR and DDS32/LUT18 then integer complex
multiply/131071. USB=delayed real+jHilbert, LSB=conjugate. RX is coherent real
projection after downmix. No carrier recovery, AGC or hardware timing claim.
"""
import numbers
import numpy as np
from ext_signal_core import DDS,AnalyticSignal,AnalyticSignalFixed


def _audio(x,fixed):
    if isinstance(x,(bool,np.bool_)) or not isinstance(x,numbers.Real) or not np.isfinite(x):raise ValueError('finite real audio')
    if fixed:
        if not isinstance(x,numbers.Integral) or not -131072<=x<=131071:raise ValueError('signed18 audio')
        return int(x)
    if abs(x)>1:raise ValueError('audio in[-1,1]')
    return float(x)


def _iq(x,fixed):
    if fixed:
        try:
            if len(x)!=2:raise ValueError('IQpair')
            return tuple(_audio(v,True) for v in x)
        except TypeError:raise ValueError('IQpair') from None
    if isinstance(x,(bool,np.bool_)) or not isinstance(x,numbers.Number) or not np.isfinite(x):raise ValueError('finite IQ')
    return complex(x)


def _flag(x):
    if type(x) is not bool:raise ValueError('bool required')


class SSBModulator:
    def __init__(self,sideband='usb',step=0,numtaps=63,fixed=False):
        _flag(fixed)
        if sideband not in ('usb','lsb'):raise ValueError('usb/lsb')
        self.sideband,self.fixed=sideband,fixed
        self.dds=DDS(step);self.analytic=(AnalyticSignalFixed if fixed else AnalyticSignal)(numtaps)
        self.reset()
    def reset(self):
        self.dds.reset();self.analytic.reset();self.last=(0,0) if self.fixed else 0j;self.clippings=0
    def push(self,x,accept=True):
        _flag(accept);x=_audio(x,self.fixed)
        if not accept:return self.last
        z=self.analytic.push(x)
        if self.fixed:
            i,q=z;q=q if self.sideband=='usb' else -q;c,s=self.dds.next()
            out=[]
            for raw in [i*c-q*s,i*s+q*c]:
                v=(2*raw+131071)//(2*131071)
                if v<-131072 or v>131071:self.clippings+=1
                out.append(min(131071,max(-131072,v)))
            self.last=tuple(out)
        else:
            if self.sideband=='lsb':z=z.conjugate()
            self.last=z*self.dds.value_float();self.dds.next()
        return self.last
    def process(self,seq):return [self.push(v) for v in seq]


class SSBDemodulator:
    def __init__(self,step=0,fixed=False):
        _flag(fixed);self.fixed=fixed;self.dds=DDS(step);self.reset()
    def reset(self):self.dds.reset();self.last=0;self.clippings=0
    def push(self,x,accept=True):
        _flag(accept);x=_iq(x,self.fixed)
        if not accept:return self.last
        if self.fixed:
            i,q=x;c,s=self.dds.next();raw=i*c+q*s
            v=(2*raw+131071)//(2*131071)
            if v<-131072 or v>131071:self.clippings+=1
            self.last=min(131071,max(-131072,v))
        else:self.last=(x*self.dds.value_float().conjugate()).real;self.dds.next()
        return self.last
    def process(self,seq):return [self.push(v) for v in seq]
