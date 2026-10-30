"""FM phase accumulation/discrimination and matched-z 75us emphasis models.

Clark basic analog source, exact400kHz/75kHz defaults (no integer8 resampling).
Fixed pipeline: Q30 emphasis coefficients, Q17-fraction64bit states,32bit phase,
DDS18 IQ, signed64 cross product/CORDIC vector with16guardbits,80bit phase and
discriminator products,96bit IIR products; Python integers implement exact wide
arithmetic. FixedFs is bounded to2**30-1 so these product widths hold for all
accepted parameters. Even accept=False samples are validated before holding state.
ROM/table and coefficient generation are offline float only.
"""
import math
import numbers
import numpy as np
from ext_signal_core import DDS

AMP=131071
ATAN=tuple(round(math.atan(2**-i)*2**32/(2*math.pi)) for i in range(32))

def _rounddiv(a,b):
    """Nearest integer division, exact ties toward positive infinity."""
    return (2*a+b)//(2*b)
def _sat(v,bits=18):return min((1<<(bits-1))-1,max(-(1<<(bits-1)),v))
def _bool(x):
    if type(x) is not bool:raise ValueError('bool required')
def _audio(x,fixed):
    if isinstance(x,(bool,np.bool_)) or not isinstance(x,numbers.Real) or not math.isfinite(x):raise ValueError('real finite audio')
    if fixed:
        if not isinstance(x,numbers.Integral) or not -AMP<=x<=AMP:raise ValueError('Q17 audio range +/-131071')
        return int(x)
    if abs(x)>1:raise ValueError('audio range +/-1')
    return float(x)
def _parameters(fs,deviation,tau,fixed):
    for v in [fs,deviation,tau]:
        if isinstance(v,(bool,np.bool_)) or not isinstance(v,numbers.Real) or not math.isfinite(v) or v<=0:raise ValueError('positive finite parameters')
    if deviation>=fs/2:raise ValueError('deviation must be below Nyquist')
    if fixed and (not isinstance(fs,numbers.Integral) or not isinstance(deviation,numbers.Integral)):raise ValueError('integer Fs/deviation for fixed rational arithmetic')
    if fixed and fs>2**30-1:raise ValueError("fixed Fs exceeds declared80bit product envelope")
    a=math.exp(-1/(fs*tau));aq=round(a*2**30)
    if not 0<=aq<2**30:raise ValueError('unrepresentable emphasis pole')
    return a,aq

def atan2_word(x,y):
    """Integer vectoring CORDIC atan2(y,x), angle units2**32/turn,32iterations.

    Input cross products fit signed36,16bit exact lift leaves vector inside64bits.
    Returns [-2**31,+2**31]; atan2(0,negative)=positivepi.
    """
    if isinstance(x,bool) or isinstance(y,bool) or not isinstance(x,numbers.Integral) or not isinstance(y,numbers.Integral):raise ValueError('integer vector')
    x,y=int(x),int(y)
    if abs(x)>=2**36 or abs(y)>=2**36:raise ValueError('CORDIC input width')
    if x==0 and y==0:raise ValueError('undefined zero angle')
    z=0
    if x<0:z=2**31 if y>=0 else -2**31;x,y=-x,-y
    x<<=16;y<<=16
    for i,a in enumerate(ATAN):
        if not y:break
        d=1 if y>0 else -1
        x,y=x+d*(y>>i),y-d*(x>>i);z+=d*a
    return z


class FMModulator:
    def __init__(self,fs=400000,deviation=75000,tau=75e-6,preemphasis=True,fixed=False):
        _bool(fixed);_bool(preemphasis);self.a,self.aq=_parameters(fs,deviation,tau,fixed)
        self.fs,self.deviation,self.fixed,self.preemphasis=(int(fs) if fixed else float(fs)),(int(deviation) if fixed else float(deviation)),fixed,preemphasis
        self.dds=DDS(0);self.reset()
    def reset(self):self.old=0;self.phase=0;self.dds.reset();self.last=(0,0) if self.fixed else 0j;self.clippings=0
    def push(self,x,accept=True):
        _bool(accept);x=_audio(x,self.fixed)
        if not accept:return self.last
        v=x
        if self.preemphasis:
            v=_rounddiv((x<<30)-self.aq*self.old,2**30-self.aq) if self.fixed else (x-self.a*self.old)/(1-self.a)
        self.old=x;lim=AMP if self.fixed else 1
        if v<-lim or v>lim:self.clippings+=1
        v=min(lim,max(-lim,v))
        if self.fixed:
            inc=_rounddiv(v*self.deviation*2**32,self.fs*AMP)
            self.phase=(self.phase+inc)%2**32;self.dds.configure(phase=self.phase);self.last=self.dds.next()
        else:
            self.phase=(self.phase+2*math.pi*self.deviation/self.fs*v)%(2*math.pi)
            self.last=complex(math.cos(self.phase),math.sin(self.phase))
        return self.last
    def process(self,seq):return [self.push(v) for v in seq]


class FMDemodulator:
    def __init__(self,fs=400000,deviation=75000,tau=75e-6,deemphasis=True,fixed=False):
        _bool(fixed);_bool(deemphasis);self.a,self.aq=_parameters(fs,deviation,tau,fixed)
        self.fs,self.deviation,self.fixed,self.deemphasis=(int(fs) if fixed else float(fs)),(int(deviation) if fixed else float(deviation)),fixed,deemphasis;self.reset()
    def reset(self):self.previous=None;self.last=0;self.state=0;self.valid=False;self.confidence=0;self.clippings=0
    def push(self,x,accept=True):
        _bool(accept)
        if self.fixed:
            try:
                if len(x)!=2:raise ValueError('IQ pair')
                # IQ uses the full signed18 range, unlike normalized audio.
                if any(isinstance(v,(bool,np.bool_)) or not isinstance(v,numbers.Integral) or not -131072<=v<=131071 for v in x):raise ValueError('signed18 IQ')
                x=tuple(int(v) for v in x)
            except TypeError:raise ValueError('IQ pair') from None
            power=x[0]**2+x[1]**2
        else:
            if isinstance(x,(bool,np.bool_)) or not isinstance(x,numbers.Number) or not np.isfinite(x):raise ValueError('finite IQ')
            x=complex(x);power=abs(x)**2
        if not accept:return self.last
        if not power:self.previous=None;self.valid=False;self.confidence=0;self.state=0;self.last=0;return 0
        if self.previous is None:self.previous=x;self.valid=False;self.confidence=0;self.last=0;return 0
        p=self.previous;self.previous=x;self.valid=True
        if self.fixed:
            self.confidence=min(power,p[0]**2+p[1]**2)
            re=x[0]*p[0]+x[1]*p[1];im=x[1]*p[0]-x[0]*p[1]
            angle=atan2_word(re,im)
            v=_rounddiv(angle*self.fs*AMP,self.deviation*2**32)
            if v<-AMP or v>AMP:self.clippings+=1
            v=min(AMP,max(-AMP,v))
            if self.deemphasis:
                self.state=_sat(self.state+(((2**30-self.aq)*((v<<17)-self.state)+2**29)>>30),64)
                v=_sat((self.state+2**16)>>17)
        else:
            self.confidence=min(power,abs(p)**2);z=x*p.conjugate()
            v=math.atan2(z.imag,z.real)*self.fs/(2*math.pi*self.deviation)
            if abs(v)>1:self.clippings+=1
            v=min(1,max(-1,v))
            if self.deemphasis:self.state+=(1-self.a)*(v-self.state);v=self.state
        self.last=v;return v
    def process(self,seq):return [self.push(v) for v in seq]
