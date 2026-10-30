"""Cascaded 1/2/4 SOS; DF2T float and quantized integer runtime.

Abood cascade realization, local source context in build/full_dsp_20261030/signal/core.
Fixed design: offline peak-gain balancing across sections preserves transfer,
signed32 Q28 coefficients, signed64 raw state, per-section symmetric
signed18 output saturation. Coefficient design/stability checks run offline in float.
Accepted-sample semantics only; no hardware timing claims.
"""
import numbers
import numpy as np


def _int(v,lo,hi,name):
    if isinstance(v,(bool,np.bool_)) or not isinstance(v,numbers.Integral) or not lo<=v<=hi:
        raise ValueError(name)
    return int(v)


def _sos(sos,frac=None):
    if any(isinstance(v,(bool,np.bool_)) for v in np.asarray(sos,dtype=object).flat):raise ValueError("SOS coefficients must be numeric, not bool")
    if np.iscomplexobj(sos):raise ValueError("SOS coefficients must be real")
    try:a=np.array(sos,dtype=float,copy=True)
    except (TypeError,ValueError):raise ValueError('SOS must be real six-column rows') from None
    if a.ndim!=2 or a.shape[0] not in (1,2,4) or a.shape[1]!=6 or not np.isfinite(a).all() or np.any(a[:,3]==0):
        raise ValueError('SOS needs 1, 2, or 4 finite six-column sections with nonzero a0')
    a/=a[:,3,None]
    if frac is not None:
        a=np.rint(a*(1<<frac))
        if np.any(a<-(1<<31)) or np.any(a>(1<<31)-1):raise ValueError('signed32 coefficient overflow')
        a=a.astype(np.int64)
    for row in a:
        if np.any(np.abs(np.roots(np.asarray(row[3:],dtype=float)))>=1):raise ValueError('unstable quantized poles')
    return a


class SOSFilter:
    """Float DF2T, zero-state configure/reset, complex samples accepted."""
    def __init__(self,sos):self.configure(sos)
    def configure(self,sos):
        a=_sos(sos);self.sos=a;self.reset()
    def reset(self):
        self.state=[[0j,0j] for _ in self.sos];self.last=0j
    def push(self,x,accept=True):
        if type(accept) is not bool:raise ValueError('accept must be bool')
        if isinstance(x,(bool,np.bool_)) or not isinstance(x,numbers.Number):raise ValueError('finite sample required')
        x=complex(x)
        if not np.isfinite(x):raise ValueError('finite sample required')
        if not accept:return self.last
        for i,(b0,b1,b2,_,a1,a2) in enumerate(self.sos):
            s1,s2=self.state[i];y=b0*x+s1
            self.state[i]=[b1*x-a1*y+s2,b2*x-a2*y];x=y
        self.last=x;return x
    def process(self,x):
        import copy
        state=copy.deepcopy(self.__dict__)
        try:return [self.push(v) for v in x]
        except Exception:
            self.__dict__.clear();self.__dict__.update(state);raise


class SOSFilterFixed:
    """Q-coefficient DF2T; integer IQ pairs, independent channel states.

    Rounding is floor((raw+2**(frac-1))/2**frac), including negative ties.
    Output and state saturation are symmetric; input accepts full two-complement18.
    Coefficient storage is always32bits, coef_bits specifies fractional bits only.
    Negative ties round toward positive infinity by contract. Clipping count includes both.
    Balancing approximates peak gains on1025points and does not guarantee headroom.
    """
    def __init__(self,sos,coef_bits=28,state_bits=64):
        self.coef_bits=_int(coef_bits,16,28,'coef_bits')
        self.state_bits=_int(state_bits,40,64,'state_bits');self.configure(sos)
    def configure(self,sos):
        a=_sos(sos)
        if len(a)>1:
            w=np.exp(-1j*np.linspace(0,np.pi,1025))
            gains=np.array([max(abs((r[0]+r[1]*w+r[2]*w*w)/(1+r[4]*w+r[5]*w*w))) for r in a])
            if np.all(gains>0):a[:,:3]*=(np.exp(np.mean(np.log(gains)))/gains)[:,None]
        a=_sos(a,self.coef_bits);self.sos=a.tolist();self.reset()
    def reset(self):
        self.state=[[[0,0] for _ in self.sos] for _ in range(2)]
        self.last=(0,0);self.clippings=0
    @property
    def clipping_count(self):return self.clippings
    def _clip(self,v,bits):
        lim=(1<<(bits-1))-1
        if abs(v)>lim:self.clippings+=1
        return min(lim,max(-lim,v))
    def push(self,x,accept=True):
        if type(accept) is not bool:raise ValueError('accept must be bool')
        if isinstance(x,numbers.Integral) and not isinstance(x,(bool,np.bool_)):x=(x,0)
        try:
            if len(x)!=2:raise ValueError('IQ pair required')
            pair=tuple(_int(v,-131072,131071,'signed18 sample') for v in x)
        except TypeError:raise ValueError('integer sample or IQ pair required') from None
        if not accept:return self.last
        out=[];f=self.coef_bits
        for c,x in enumerate(pair):
            for i,(b0,b1,b2,_,a1,a2) in enumerate(self.sos):
                s1,s2=self.state[c][i]
                y=self._clip((b0*x+s1+(1<<(f-1)))>>f,18)
                ns1=b1*x-a1*y+s2;ns2=b2*x-a2*y
                self.state[c][i]=[self._clip(ns1,self.state_bits),self._clip(ns2,self.state_bits)]
                x=y
            out.append(x)
        self.last=tuple(out);return self.last
    def process(self,x):
        import copy
        state=copy.deepcopy(self.__dict__)
        try:return [self.push(v) for v in x]
        except Exception:
            self.__dict__.clear();self.__dict__.update(state);raise
