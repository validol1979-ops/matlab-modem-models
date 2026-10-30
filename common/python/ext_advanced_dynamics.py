"""Feedforward compressor/finite-ratio soft limiter and hysteretic noise gate.

Douglas Self ch24 supplies behavior, not digital recurrences. These recurrences
are project-derived: one-pole detector with exp(-1/(Fs*tau)), peak or RMS;
max stereo linked sidechain. A finite ratio is not a brickwall/truepeak guarantee.
Fixed runtime: Q17 samples/envelope, Q34 RMS power, Q31 pole coefficients,
Q24 gain table/multiply. Tables/configuration generated offline in float.
"""
import math
import numpy as np
Q=1<<17;C=1<<31;G=1<<24

def _finite(x,name,lo,hi):
 if isinstance(x,bool) or not np.isscalar(x) or not np.isreal(x) or not np.isfinite(x) or not lo<=x<=hi:raise ValueError(name)
 return float(x)
def _pole(fs,t):return 0. if t==0 else math.exp(-1/(fs*t))
def _rnd(v,d):return (2*int(v)+int(d))//(2*int(d))
def _sat(v):return max(-Q,min(Q-1,int(v)))
def _sample(x,fixed):
 a=np.asarray(x,dtype=object if fixed else None)
 if a.ndim!=1 or len(a) not in (1,2) or np.iscomplexobj(a):raise ValueError('mono/stereo real vector')
 if fixed:
  if any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or not -Q<=v<Q for v in a):raise ValueError('signed18 samples')
  return [int(v) for v in a]
 a=np.asarray(a,float)
 if not np.isfinite(a).all() or np.max(abs(a))>1:raise ValueError('samples within +-1')
 return a.tolist()

def compressor_curve(level_db,threshold=-18.,ratio=3.,knee=6.):
 """Static output dBFS before makeup; quadratic C1 continuous knee."""
 x=np.asarray(level_db,float);t=threshold;r=ratio;w=knee;delta=x-t
 if w==0:return np.where(delta<=0,x,t+delta/r)
 return np.where(delta<=-w/2,x,np.where(delta>=w/2,t+delta/r,x+(1/r-1)*(delta+w/2)**2/(2*w)))

class Compressor:
 def __init__(self,fs=48000,threshold=-18.,ratio=3.,knee=6.,attack=.005,release=.08,makeup=0.,detector='peak',fixed=False,lookahead=0,bypass=False):
  self.fixed=bool(fixed);self.configure(fs=fs,threshold=threshold,ratio=ratio,knee=knee,attack=attack,release=release,makeup=makeup,detector=detector,lookahead=lookahead,bypass=bypass);self.reset()
 def configure(self,**kwargs):
  cfg=getattr(self,'cfg',{}).copy();cfg.update(kwargs)
  allowed={'fs','threshold','ratio','knee','attack','release','makeup','detector','lookahead','bypass'}
  if set(cfg)!=allowed:raise ValueError('configuration keys')
  for name,lo,hi in [('fs',8000,192000),('threshold',-96,0),('ratio',1,100),('knee',0,24),('attack',0,2),('release',0,10),('makeup',-24,24)]:cfg[name]=_finite(cfg[name],name,lo,hi)
  if cfg['detector'] not in ('peak','rms') or not isinstance(cfg['bypass'],bool):raise ValueError('detector/bypass')
  la=cfg['lookahead']
  if isinstance(la,bool) or not isinstance(la,int) or not 0<=la<=4096:raise ValueError('lookahead sample count')
  if hasattr(self,'cfg') and (cfg['lookahead']!=self.cfg['lookahead'] or cfg['detector']!=self.cfg['detector']):raise ValueError('lookahead/detector change requires new instance')
  aa=_pole(cfg['fs'],cfg['attack']);ar=_pole(cfg['fs'],cfg['release'])
  levels=np.arange(Q+1)/Q;db=20*np.log10(np.maximum(levels,1e-12));out=compressor_curve(db,cfg['threshold'],cfg['ratio'],cfg['knee'])
  table=np.floor(10**((out-db+cfg['makeup'])/20)*G+.5).astype(np.int64)
  self.cfg=cfg;self.aa=aa;self.ar=ar;self.aq=int(math.floor(aa*C+.5));self.rq=int(math.floor(ar*C+.5));self.table=table
 def reset(self):self.envelope=0;self.gain=G if self.fixed else 1.;self.delay=[];self.channels=None;self.saturations=0
 def next(self,sample,accept=True):
  if not isinstance(accept,bool):raise ValueError('accept bool')
  x=_sample(sample,self.fixed)
  if self.channels is not None and self.channels!=len(x):raise ValueError('channel count cannot change')
  peak=max(abs(v) for v in x);rms=self.cfg['detector']=='rms';target=peak*peak if rms else peak
  if self.fixed:
   coeff=self.aq if target>self.envelope else self.rq
   env=_rnd(coeff*self.envelope+(C-coeff)*target,C)
   level=min(Q,math.isqrt(env) if rms else env);gain=int(self.table[level])
  else:
   coeff=self.aa if target>self.envelope else self.ar;env=coeff*self.envelope+(1-coeff)*target;level=math.sqrt(env) if rms else env
   db=20*math.log10(max(level,1e-12));gain=10**((float(compressor_curve(db,self.cfg['threshold'],self.cfg['ratio'],self.cfg['knee']))-db+self.cfg['makeup'])/20)
  hist=self.delay+[x];la=self.cfg['lookahead'];delayed=hist[-la-1] if len(hist)>la else [0]*len(x)
  if self.cfg['bypass']:y=delayed
  elif self.fixed:y=[_sat(_rnd(v*gain,G)) for v in delayed]
  else:y=[v*gain for v in delayed]
  if accept:
   self.envelope=env;self.gain=gain;self.channels=len(x);self.delay=hist[-la:] if la else []
   if self.fixed and not self.cfg['bypass']:self.saturations+=sum(_rnd(v*gain,G)!=o for v,o in zip(delayed,y))
  return np.asarray(y,dtype=np.int64 if self.fixed else float)

class NoiseGate:
 """Open at >=threshold; retain open until <threshold-hysteresis for hold.

 Hold decrements only below closing threshold; at zero latch closes. Gain uses
 one-pole attack/release toward1/range, so tau means63.2% of step completion.
 Sidechain high/low-pass first order; zero Hz bypasses the respective filter.
 """
 def __init__(self,fs=48000,threshold=-40.,hysteresis=3.,attack=.001,hold=.02,release=.03,range_db=-60.,hp=0.,lp=0.,fixed=False,bypass=False):
  self.fixed=bool(fixed);self.configure(fs=fs,threshold=threshold,hysteresis=hysteresis,attack=attack,hold=hold,release=release,range_db=range_db,hp=hp,lp=lp,bypass=bypass);self.reset()
 def configure(self,**kwargs):
  cfg=getattr(self,'cfg',{}).copy();cfg.update(kwargs)
  if set(cfg)!={'fs','threshold','hysteresis','attack','hold','release','range_db','hp','lp','bypass'}:raise ValueError('configuration keys')
  for name,lo,hi in [('fs',8000,192000),('threshold',-96,0),('hysteresis',0,24),('attack',0,2),('hold',0,10),('release',0,10),('range_db',-96,0),('hp',0,20000),('lp',0,20000)]:cfg[name]=_finite(cfg[name],name,lo,hi)
  if not isinstance(cfg['bypass'],bool) or max(cfg['hp'],cfg['lp'])>=cfg['fs']/2 or (cfg['hp'] and cfg['lp'] and cfg['hp']>=cfg['lp']):raise ValueError('sidechain/bypass')
  coeff=[_pole(cfg['fs'],cfg['attack']),_pole(cfg['fs'],cfg['release'])]
  lowpole=math.exp(-2*np.pi*cfg['lp']/cfg['fs']) if cfg['lp'] else 0.
  highpole=math.exp(-2*np.pi*cfg['hp']/cfg['fs']) if cfg['hp'] else 0.
  self.cfg=cfg;self.coeff=coeff;self.cq=[int(math.floor(v*C+.5)) for v in coeff]
  self.lp=lowpole;self.hp=highpole;self.lq=int(math.floor(lowpole*C+.5));self.hq=int(math.floor(highpole*C+.5))
  self.on=10**(cfg['threshold']/20);self.off=10**((cfg['threshold']-cfg['hysteresis'])/20);self.floor=10**(cfg['range_db']/20)
  self.onq=int(math.floor(self.on*Q+.5));self.offq=int(math.floor(self.off*Q+.5));self.floorq=int(math.floor(self.floor*G+.5));self.hold_samples=int(math.floor(cfg['hold']*cfg['fs']+.5))
 def reset(self):self.open=False;self.count=0;self.gain=self.floorq if self.fixed else self.floor;self.previous=None;self.highstate=None;self.lowstate=None
 def next(self,sample,accept=True):
  if not isinstance(accept,bool):raise ValueError('accept bool')
  x=_sample(sample,self.fixed);n=len(x)
  if self.previous is not None and n!=len(self.previous):raise ValueError('channel count cannot change')
  old=self.previous if self.previous is not None else [0]*n;hs=self.highstate if self.highstate is not None else [0]*n;ls=self.lowstate if self.lowstate is not None else [0]*n
  if self.fixed:
   h=[_rnd(self.hq*(s+v-u),C) for s,v,u in zip(hs,x,old)] if self.cfg['hp'] else x[:]
   l=[_rnd(self.lq*s+(C-self.lq)*v,C) for s,v in zip(ls,h)] if self.cfg['lp'] else h[:]
  else:
   h=[self.hp*(s+v-u) for s,v,u in zip(hs,x,old)] if self.cfg['hp'] else x[:]
   l=[self.lp*s+(1-self.lp)*v for s,v in zip(ls,h)] if self.cfg['lp'] else h[:]
  level=max(abs(v) for v in l);on=self.onq if self.fixed else self.on;off=self.offq if self.fixed else self.off
  opened=self.open;count=self.count
  if level>=on:opened=True;count=self.hold_samples
  elif opened:
   if level>=off:count=self.hold_samples
   elif count>0:count-=1
   else:opened=False
  target=(G if opened else self.floorq) if self.fixed else (1. if opened else self.floor)
  idx=0 if target>self.gain else 1
  gain=_rnd(self.cq[idx]*self.gain+(C-self.cq[idx])*target,C) if self.fixed else self.coeff[idx]*self.gain+(1-self.coeff[idx])*target
  y=x if self.cfg['bypass'] else ([_sat(_rnd(v*gain,G)) for v in x] if self.fixed else [v*gain for v in x])
  if accept:self.open=opened;self.count=count;self.gain=gain;self.previous=x;self.highstate=h;self.lowstate=l
  return np.asarray(y,dtype=np.int64 if self.fixed else float)
