"""Integer BPSK pilot reference. Tables alone are generated with real arithmetic.

18/15 samples, 18/17 RRC/trigonometry, 18/16 cubic coefficients,
32-bit phase in turns, 32/20 gain, 32/16 sample positions.
"""
from fractions import Fraction
import math
import numpy as np
from fixed_point import SAMPLE, round_shift
from modem_core import rrc_taps

SPS=8
TRAIN=192
FIT_START=32
FIT_COUNT=128
LOOP_DELAY=4
GAIN_DELAY=8
ATAN=tuple(round(math.atan(2.0**-i)/(2*math.pi)*2**32) for i in range(20))
RRC=tuple(round(float(x)*2**17) for x in rrc_taps(8,32,1))
COS=tuple(round(math.cos(2*math.pi*i/4096)*2**17) for i in range(4096))
# +1 is representable for sample/coefficient formats with two integer bits.
COS=tuple(min(131071,max(-131072,x)) for x in COS)
CUBIC=[]
for i in range(256):
 m=Fraction(i,256)
 CUBIC.append(tuple(round(x*2**16) for x in (-m*(m-1)*(m-2)/6,(m+1)*(m-1)*(m-2)/2,-(m+1)*m*(m-2)/2,(m+1)*m*(m-1)/6)))
CUBIC=tuple(CUBIC)


def divide(n,d):
 if d<=0:raise ValueError('Positive denominator required')
 q,r=divmod(int(n),int(d))
 return q+int(2*r>d or (2*r==d and q&1))


def wrap(p):return ((int(p)+2**31)%2**32)-2**31


def atan2(y,x):
 x,y=int(x),int(y)
 if x==0 and y==0:return 0
 angle=0
 if x<0:
  angle=2**31 if y>=0 else -2**31;x,y=-x,-y
 for i,a in enumerate(ATAN):
  direction=1 if y>=0 else -1
  x,y=x+direction*(y>>i),y-direction*(x>>i)
  angle+=direction*a
 return wrap(angle)


def sat(n):return SAMPLE.saturate(int(n))[0]


def rotate(z,phase):
 index=(int(phase)>>20)&4095
 c=COS[index];s=COS[(index-1024)&4095]
 # exp(-j phase)
 return (sat(round_shift(z[0]*c+z[1]*s,17)),sat(round_shift(z[1]*c-z[0]*s,17)))


def interp(wave,position):
 base=int(position)>>16;weights=CUBIC[(int(position)>>8)&255]
 accum=[0,0]
 for j,coef in enumerate(weights):
  idx=base+j-1
  if 0<=idx<len(wave):
   for axis in (0,1):accum[axis]+=int(wave[idx][axis])*coef
 return tuple(sat(round_shift(x,16)) for x in accum)


def fir(wave,shift=17):
 # shift 17 keeps the Q15 scale; QAM64 uses 16 (TX, half-scale points) and 19 (RX, /4).
 a=[(int(x[0]),int(x[1])) for x in wave];out=[]
 for n in range(len(a)+32):
  accum=[0,0]
  for k,coef in enumerate(RRC):
   if 0<=n-k<len(a):
    for axis in (0,1):accum[axis]+=a[n-k][axis]*coef
  out.append(tuple(sat(round_shift(x,shift)) for x in accum))
 return out


def encode(bits):
 prev=0;ids=[]
 for bit in bits:
  if bit not in (0,1):raise ValueError('Binary labels required')
  prev^=int(bit);ids.append(prev)
 return ids


def transmit(bits):
 wave=[(0,0)]*(len(bits)*8)
 for i,idx in enumerate(encode(bits)):wave[8*i]=(-16384,-16384) if idx else (16384,16384)
 return fir(wave)


def quantize(wave):return [(SAMPLE.quantize(float(x.real)),SAMPLE.quantize(float(x.imag))) for x in wave]


def acquire(wave,preamble):
 ids=encode(preamble);energies=[0]*8
 for n in range(64,320):
  re,im=wave[n];energies[n&7]+=re*re+im*im
 # Average first 32 symbols, retain 18-bit Q16 power for the DFT.
 energies=[min(131071,round_shift(e,19)) for e in energies]
 re=sum(energies[i]*COS[i*512] for i in range(8))
 im=sum(energies[i]*COS[(i*512-1024)&4095] for i in range(8))
 delay=round_shift(atan2(im,re),13) # signed sample time Q16, modulo 8
 candidates=[]
 for off in (0,8,16):
  # Как psk_fixed.acquire и RTL: кандидат ограничивается диапазоном, а не отбрасывается.
  candidate=min(max(delay+(off<<16),-(1<<15)),(16<<16)+(1<<15))
  phases=[];previous=None;unwrapped=0
  for k in range(FIT_START,FIT_START+FIT_COUNT):
   r,i=interp(wave,(32<<16)+candidate+(8*k<<16));sign=1-2*ids[k]
   phase=atan2(sign*(i-r),sign*(r+i))
   if previous is None:unwrapped=phase
   else:unwrapped+=wrap(phase-previous)
   previous=phase;phases.append(unwrapped)
  weighted=sum((2*k-FIT_COUNT+1)*p for k,p in enumerate(phases))
  slope=divide(6*weighted,FIT_COUNT*(FIT_COUNT**2-1))
  intercept=divide(sum(phases),FIT_COUNT)-round_shift(slope*(2*FIT_START+FIT_COUNT-1),1)
  score=sum(round_shift(p-intercept-slope*(FIT_START+k),16)**2 for k,p in enumerate(phases))
  candidates.append((score,candidate,wrap(slope),wrap(intercept)))
 if not candidates:raise ValueError('No acquisition candidate')
 score,delay,slope,phase=min(candidates)
 amplitude=0
 for k in range(FIT_START,FIT_START+FIT_COUNT):
  z=rotate(interp(wave,(32<<16)+delay+(8*k<<16)),phase+slope*k)
  amplitude+=(1-2*ids[k])*(z[0]+z[1])
 amplitude=divide(amplitude,FIT_COUNT)
 if amplitude<0:
  phase=wrap(phase+2**31);amplitude=-amplitude
 confidence=amplitude>=32
 amplitude=max(32,amplitude)
 gain=min(16<<20,divide(1<<35,amplitude))
 return dict(delay=delay,frequency=slope,phase=phase,gain=gain,score=score,confidence=confidence)


def receive(wave,preamble,count,*,tracking=True,observe=False):
 if len(preamble)!=TRAIN or count<TRAIN or count>2048 or len(wave)<count*8:raise ValueError('Invalid frame')
 filtered=fir(wave);acq=acquire(filtered,preamble);ids_train=encode(preamble)
 phase=acq['phase'];frequency=acq['frequency'];gain=acq['gain'];correction=0
 inv_square=round_shift(gain*gain,28) # Q12
 pending=[(0,0)]*LOOP_DELAY;gain_pending=[0]*GAIN_DELAY;ids=[];labels=[];trace=[];nodes=[];prev=0
 for k in range(count):
  pe,te=pending.pop(0);gd=gain_pending.pop(0)
  if tracking:
   frequency=wrap(frequency+pe*4)
   phase=wrap(phase+pe*834)
   gain=max(1,min(16<<20,gain+gd))
   correction+=round_shift(te*3932,17)
  pos=(32<<16)+acq['delay']+(8*k<<16)+correction
  early=interp(filtered,pos-(4<<16));mid=interp(filtered,pos);late=interp(filtered,pos+(4<<16))
  ted=2*((late[0]-early[0])*mid[0]+(late[1]-early[1])*mid[1])
  te=max(-32768,min(32768,round_shift(ted*inv_square,27)))
  phase_used=wrap(phase+acq['frequency']*k)
  rotated=rotate(mid,phase_used);value=rotated
  value=tuple(sat(round_shift(x*gain,20)) for x in value)
  zi,zq=value[0]+value[1],value[1]-value[0]
  idx=int(zi<0);sign=1-2*idx
  pe=max(-16384,min(16384,sign*zq))
  target=1-2*(ids_train[k] if k<188 else idx)
  ge=max(-16384,min(16384,round_shift(2*((target*16384-value[0])*value[0]+(target*16384-value[1])*value[1]),15)))
  if observe:nodes.append(dict(position=pos,phase=phase_used,early=early,mid=mid,late=late,rotated=rotated,gain=gain,value=value,pe=pe,ge=ge,te=te))
  pending.append((pe,te));gain_pending.append(round_shift(gain*ge*262,32));phase=wrap(phase+frequency-acq['frequency'])
  ids.append(idx);labels.append(idx^prev);prev=idx
  trace.append((value[0],value[1],phase,frequency,gain,correction,idx,labels[-1]))
 return dict(data=np.array(labels),trace=trace,filtered=filtered,acquisition=acq,nodes=nodes)
