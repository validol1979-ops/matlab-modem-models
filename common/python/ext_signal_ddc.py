"""Accepted-sample 40:1 DDC, Harris figure14.3 project-derived 5-stage CIC10.

Runtime: DDS32/Q17 mixer -> existing normalized CIC5/10 -> compensation FIR/2
-> halfband FIR/2. Both FIR stages reuse RationalFixed. Float batch reference
uses independent complex sinusoid and NumPy/SciPy convolution. No timing claims.
"""
import numbers
import numpy as np
from scipy.signal import firwin,lfilter
from ext_signal_core import DDS
from cic_model import CICDecimator
from cic_compensation import design,quantize
from rational_model import RationalFixed


def _step(v):
    if isinstance(v,(bool,np.bool_)) or not isinstance(v,numbers.Integral) or not 0<=v<2**32:raise ValueError('unsigned32 step')
    return int(v)


def _sample(v):
    if isinstance(v,(bool,np.bool_)) or not isinstance(v,numbers.Integral) or not -131072<=v<=131071:raise ValueError('signed18 real input')
    return int(v)


class DDC:
    total_decimation=40
    def __init__(self,step=0,comp_taps=63,halfband_taps=63):
        step=_step(step)
        for n in [comp_taps,halfband_taps]:
            if isinstance(n,(bool,np.bool_)) or not isinstance(n,numbers.Integral) or not 31<=n<=127 or n%2!=1:raise ValueError('odd 31..127 taps')
        self.compensation=design(10,5,numtaps=int(comp_taps),passband=.16,stopband=.32)
        self.compensation_q=quantize(self.compensation)
        h=firwin(int(halfband_taps),.5,window='hamming')
        h[abs(h)<1e-15]=0
        self.halfband=h
        q=np.rint(h*2**17).astype(int);q[len(q)//2]+=2**17-int(sum(q))
        if min(q)<-131072 or max(q)>131071:raise ValueError('halfband coefficient overflow')
        self.halfband_q=[(int(v),0) for v in q]
        self.configure(step)
    def configure(self,step):
        step=_step(step);self.step=step;self.reset()
    def reset(self):
        self.dds=DDS((-self.step)%2**32)
        self.cic=CICDecimator(10,stages=5,normalize=True)
        self.comp=RationalFixed(1,2,[v[0] for v in self.compensation_q])
        self.hb=RationalFixed(1,2,[v[0] for v in self.halfband_q])
        self.closed=False;self.accepted=0;self.clippings=0
    def push(self,x,accept=True):
        if type(accept) is not bool:raise ValueError('accept must be bool')
        x=_sample(x)
        if self.closed:raise RuntimeError('frame closed; reset required')
        if not accept:return []
        i,q=self.dds.next();pair=[]
        for v in [x*i,x*q]:
            y=(2*v+131071)//(2*131071)
            if y<-131072 or y>131071:self.clippings+=1
            pair.append(min(131071,max(-131072,y)))
        self.accepted+=1;out=[]
        for iq,last in self.cic.push(tuple(pair)):
            for z in self.comp.push(iq):out.extend(self.hb.push(z))
        return out
    def process(self,samples):return [z for x in samples for z in self.push(x)]
    def flush(self):self.closed=True;return []
    def reference(self,samples):
        """Float oracle, zero extension before start only, no trailing flush samples."""
        x=np.array([_sample(v) for v in samples],dtype=float)
        if not len(x):return np.array([],complex)
        phases=(np.arange(len(x),dtype=np.uint64)*np.uint64(self.step))%np.uint64(2**32)
        mixed=x*np.exp(-2j*np.pi*phases.astype(float)/2**32)
        h=np.ones(1)
        for _ in range(5):h=np.convolve(h,np.ones(10))
        y=lfilter(h/10**5,[1],mixed)[9::10]
        if not len(y):return y
        y=lfilter(self.compensation,[1],y)[::2]
        return lfilter(self.halfband,[1],y)[::2]
