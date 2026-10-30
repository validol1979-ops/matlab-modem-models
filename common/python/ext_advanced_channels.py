"""Source Tausworthe/Box--Muller and complex Clarke sum-of-sinusoids models.

Tausworthe emits XOR of the OLD states, as the original nonblocking assignment.
Uniforms are midpoint (word+.5)/2**32: log(0) is excluded. Source gaus_rng
LUT/CORDIC timing is not reproduced: fixed profile uses offline radius/cos LUTs
and integer multiply/phase state, with per-component Q17 saturation.
"""
import math
import numpy as np
MASK=(1<<32)-1;Q=1<<17

def rnd(v,d):return (2*int(v)+int(d))//(2*int(d))
def sat(v):return max(-Q,min(Q-1,int(v)))
def iq(v):
 a=np.asarray(v,dtype=object)
 if a.shape!=(2,) or any(isinstance(x,(bool,np.bool_)) or not isinstance(x,(int,np.integer)) or not -Q<=x<Q for x in a):raise ValueError('signed18 IQ required')
 return int(a[0]),int(a[1])

def _uint(x):
 if isinstance(x,bool) or not isinstance(x,(int,np.integer)) or not 0<=x<=MASK:raise ValueError('unsigned32 seed')
 return int(x)

class Tausworthe:
 def __init__(self,seeds=(0,0,0)):
  if len(seeds)!=3:raise ValueError('three seeds')
  self.seeds=tuple(_uint(s) for s in seeds);self.reset()
 def reset(self):self.state=[s+minimum if s<minimum else s for s,minimum in zip(self.seeds,(2,8,16))]

# Explicit expressions avoid precedence ambiguities and mirror 32-bit source.
def _advance(s,mask,left,shift,right):
 return (((s&mask)<<left)^((((s<<shift)&MASK)^s)>>right))&MASK

def _accept(accept):
 if not isinstance(accept,bool):raise ValueError('accept must be bool')

def _next(self,accept=True):
 _accept(accept)
 out=self.state[0]^self.state[1]^self.state[2]
 if accept:self.state=[_advance(s,*p) for s,p in zip(self.state,((0xfffffffe,12,13,19),(0xfffffff8,4,2,25),(0xfffffff0,17,3,11)))]
 return out
Tausworthe.next=_next

_COS=np.floor(np.cos(2*np.pi*np.arange(65536)/65536)*Q+.5).astype(np.int64)
_SIN=np.floor(np.sin(2*np.pi*np.arange(65536)/65536)*Q+.5).astype(np.int64)
_RADIUS=np.floor(np.sqrt(-2*np.log((np.arange(65536)+.5)/65536))*(1<<20)+.5).astype(np.int64)

class AWGN:
 """Sigma is the standard deviation PER real component, complex power2sigma²."""
 def __init__(self,sigma=.1,seeds=(0,0,0),fixed=False):
  if not np.isfinite(sigma) or not 0<=sigma<=1:raise ValueError('sigma0..1')
  self.sigma=float(sigma);self.gain=int(math.floor(sigma*Q+.5));self.fixed=bool(fixed)
  self.x=Tausworthe(seeds);self.y=Tausworthe(tuple((~s)&MASK for s in seeds))
 def reset(self):self.x.reset();self.y.reset()
 def next(self,sample=None,accept=True):
  _accept(accept)
  if self.fixed:
   base=(0,0) if sample is None else iq(sample)
  elif sample is not None and (not np.isscalar(sample) or not np.isfinite(sample)):raise ValueError('finite scalar input')
  a=self.x.next(accept);b=self.y.next(accept)
  if self.fixed:
   r=int(_RADIUS[a>>16]);j=b>>16
   noise=(rnd(r*int(_COS[j])*self.gain,(1<<20)*Q),rnd(r*int(_SIN[j])*self.gain,(1<<20)*Q))
   base=(0,0) if sample is None else iq(sample)
   return tuple(sat(v+n) for v,n in zip(base,noise))
  if sample is not None and not np.isfinite(sample):raise ValueError('finite input')
  return (0 if sample is None else sample)+self.sigma*math.sqrt(-2*math.log((a+.5)/2**32))*np.exp(2j*np.pi*(b+.5)/2**32)

class Rayleigh:
 """Complex isotropic Clarke SoS: h=sum exp(j(phi+2pi fd cos(theta)n))/sqrt(M).

 Angles/phases generated offline with PCG64. Float normalized Doppler fd<.5.
 Fixed: phase32 accumulator, cos/sin16 LUT Q17, sum round then signed18.
 Unit mean complex power is an ENSEMBLE property. No envelope rectification.
 """
 def __init__(self,fd=.01,sines=64,seed=1,fixed=False):
  if not np.isfinite(fd) or not 0<=fd<.5:raise ValueError('fd')
  if isinstance(sines,bool) or not isinstance(sines,int) or not 8<=sines<=1024:raise ValueError('sines8..1024')
  self.fd=float(fd);self.sines=sines;self.fixed=bool(fixed)
  rng=np.random.default_rng(seed);self.theta=rng.uniform(0,2*np.pi,sines);self.initial=rng.uniform(0,2*np.pi,sines)
  self.steps=np.floor(fd*np.cos(self.theta)*2**32+.5).astype(np.int64)
  self.phase0=np.floor(self.initial/(2*np.pi)*2**32+.5).astype(np.int64)&MASK
  self.norm=int(np.floor(Q/math.sqrt(sines)+.5));self.reset()
 def reset(self):self.n=0;self.phase=self.phase0.copy()
 def next(self,accept=True):
  _accept(accept)
  if self.fixed:
   idx=self.phase>>16
   out=(rnd(sum(int(x) for x in _COS[idx])*self.norm,Q),rnd(sum(int(x) for x in _SIN[idx])*self.norm,Q))
   # Channel coefficient has Q17 fractional bits with signed24 HEADROOM.
   if accept:self.phase=(self.phase+self.steps)&MASK;self.n+=1
   return out
  out=np.exp(1j*(self.initial+2*np.pi*self.fd*np.cos(self.theta)*self.n)).sum()/math.sqrt(self.sines)
  if accept:self.n+=1
  return out
 def apply(self,sample,accept=True):
  _accept(accept)
  if self.fixed:iq(sample)
  elif not np.isscalar(sample) or not np.isfinite(sample):raise ValueError('finite scalar input')
  h=self.next(accept)
  if self.fixed:
   a,b=iq(sample);c,d=h
   return sat(rnd(a*c-b*d,Q)),sat(rnd(a*d+b*c,Q))
  if not np.isfinite(sample):raise ValueError('finite input')
  return h*sample

class Multipath:
 """Independent complex SoS taps and integer delays; normalized average power."""
 def __init__(self,delays,powers,fd=.01,seed=1,fixed=False):
  if len(delays)==0 or len(delays)!=len(powers) or any(isinstance(d,bool) or not isinstance(d,int) or d<0 or d>4096 for d in delays):raise ValueError('delays')
  if np.iscomplexobj(powers):raise ValueError('real powers')
  p=np.asarray(powers,float)
  if not np.isfinite(p).all() or np.any(p<0) or p.sum()<=0:raise ValueError('powers')
  self.delays=list(delays);self.gains=np.sqrt(p/p.sum());self.fixed=bool(fixed)
  self.gq=np.floor(self.gains*Q+.5).astype(np.int64)
  self.taps=[Rayleigh(fd,64,seed+i,fixed) for i in range(len(p))];self.reset()
 def reset(self):
  self.history=[(0,0) if self.fixed else 0j]*(max(self.delays)+1)
  for t in self.taps:t.reset()
 def next(self,sample,accept=True):
  _accept(accept)
  value=iq(sample) if self.fixed else complex(sample)
  if not self.fixed and not np.isfinite(value):raise ValueError('finite input')
  hist=[value]+self.history[:-1];out=[0,0] if self.fixed else 0j
  for d,g,gq,t in zip(self.delays,self.gains,self.gq,self.taps):
   h=t.next(accept)
   if self.fixed:
    a,b=hist[d];c,e=h
    out[0]+=rnd((a*c-b*e)*int(gq),Q*Q);out[1]+=rnd((a*e+b*c)*int(gq),Q*Q)
   else:out+=g*h*hist[d]
  if accept:self.history=hist
  return tuple(sat(v) for v in out) if self.fixed else out
