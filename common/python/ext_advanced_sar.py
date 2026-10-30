"""Small stripmap Omega-K arithmetic research model (Chen eq1.25--1.32).

Units are SI-compatible scalars, not a hardware radar claim. FFT convention is
exp(-j2pi f t); input fast-time is centered on 2Rref/c. RFM cancels reference
propagation/chirp phase, including that time-origin shift. Inverse Stolt lookup
f_old=sqrt((fc+f_new)^2+c² f_eta²/(4v²))-fc, zero outside support.
Interpolation is linear complex Cartesian. Amplitude convention: unit Jacobian
(reference-normalized focusing), not calibrated radiometry.
"""
from dataclasses import dataclass
import numpy as np
try:from . import fft_fixed, sat_diag
except ImportError:
 import fft_fixed
 import sat_diag

@dataclass(frozen=True)
class Geometry:
 nfast:int=256
 nslow:int=128
 fs:float=64.
 prf:float=20.
 fc:float=50.
 chirp_rate:float=16.
 pulse:float=.8
 velocity:float=20.
 range_ref:float=100.
 c:float=100.
 def __post_init__(self):
  for n in (self.nfast,self.nslow):
   if isinstance(n,bool) or not isinstance(n,int) or n<16 or n>512 or n&(n-1):raise ValueError('FFT dimensions power2 16..512')
  vals=[self.fs,self.prf,self.fc,self.chirp_rate,self.pulse,self.velocity,self.range_ref,self.c]
  if not np.isfinite(vals).all() or min(vals)<=0 or self.chirp_rate*self.pulse>=self.fs or self.fs>=2*self.fc:raise ValueError('positive geometry/chirpband/fs<2fc')
 @property
 def fast(self):return (np.arange(self.nfast)-self.nfast//2)/self.fs+2*self.range_ref/self.c
 @property
 def slow(self):return (np.arange(self.nslow)-self.nslow//2)/self.prf
 @property
 def ranges(self):return self.range_ref+(np.arange(self.nfast)-self.nfast//2)*self.c/(2*self.fs)
 @property
 def azimuths(self):return self.velocity*self.slow

def point_echo(g,targets):
 """Targets (azimuth_m, slant_broadside_range_m, complex_amplitude)."""
 out=np.zeros((g.nslow,g.nfast),complex)
 for x,r,a in targets:
  if not np.isfinite([x,r,complex(a).real,complex(a).imag]).all() or r<=0:raise ValueError('pointtarget')
  distance=np.sqrt(r*r+(g.velocity*g.slow-x)**2);delay=g.fast[None,:]-2*distance[:,None]/g.c
  out+=complex(a)*(abs(delay)<=g.pulse/2)*np.exp(1j*np.pi*g.chirp_rate*delay**2-4j*np.pi*g.fc*distance[:,None]/g.c)
 return out

def _fft2(x):return np.fft.fftshift(np.fft.fft2(np.fft.ifftshift(x)))
def _ifft2(x):return np.fft.fftshift(np.fft.ifft2(np.fft.ifftshift(x)))
def plan(g):
 fr=np.fft.fftshift(np.fft.fftfreq(g.nfast,1/g.fs));fa=np.fft.fftshift(np.fft.fftfreq(g.nslow,1/g.prf))
 rad=(g.fc+fr[None,:])**2-g.c*g.c*fa[:,None]**2/(4*g.velocity*g.velocity)
 valid=rad>0;root=np.sqrt(np.maximum(rad,0))
 phase=4*np.pi*g.range_ref/g.c*root+np.pi*fr[None,:]**2/g.chirp_rate-2*np.pi*fr[None,:]*(2*g.range_ref/g.c)
 rfm=np.exp(1j*phase)*valid
 old=np.sqrt((g.fc+fr[None,:])**2+g.c*g.c*fa[:,None]**2/(4*g.velocity*g.velocity))-g.fc
 support=(old>=fr[0])&(old<=fr[-1])
 position=(old-fr[0])/(fr[1]-fr[0]);left=np.clip(np.floor(position).astype(int),0,g.nfast-2);frac=position-left
 return rfm,left,frac,support

def omega_k(data,g,stolt=True):
 a=np.asarray(data,complex)
 if a.shape!=(g.nslow,g.nfast) or not np.isfinite(a).all():raise ValueError('echo shape/finite')
 rfm,left,frac,support=plan(g);s=_fft2(a)*rfm
 if stolt:
  rows=np.arange(g.nslow)[:,None];s=((1-frac)*s[rows,left]+frac*s[rows,left+1])*support
 return _ifft2(s)

def backprojection(data,g,azimuths,ranges):
 """Independent direct matched sum over original fast/slow samples.

 No FFT, RFM or Stolt. Returns coherent matched response on requested grid.
 """
 a=np.asarray(data,complex)
 if a.shape!=(g.nslow,g.nfast) or not np.isfinite(a).all():raise ValueError('echo shape/finite')
 out=np.zeros((len(azimuths),len(ranges)),complex)
 for i,x in enumerate(azimuths):
  for j,r in enumerate(ranges):
   distance=np.sqrt(float(r)**2+(g.velocity*g.slow-float(x))**2);dt=g.fast[None,:]-2*distance[:,None]/g.c
   reference=(abs(dt)<=g.pulse/2)*np.exp(1j*np.pi*g.chirp_rate*dt**2-4j*np.pi*g.fc*distance[:,None]/g.c)
   out[i,j]=np.vdot(reference,a)
 return out

class OmegaKFixed:
 """Offline geometry coefficients; integer fixed FFT/RFM/Stolt/IFFT runtime.

 Input signed18 Q17 IQ, shifted4 to Q21; FFT2 stage-scaled by 1/(Nslow*Nfast), headroom24.
 RFM Q20 multiply/round, Stolt fractionQ20 linear interpolation, inverseFFT2
 unnormalized, returning Q17 IQ signed24 (reject overflow before inverse FFT).
 This is an arithmetic profile, not bitexact to a vendor IP or radiometricgain.
 """
 def __init__(self,g):
  self.g=g;rfm,self.left,frac,self.support=plan(g);self.frac=np.floor(frac*(1<<20)+.5).astype(int)
  self.rfm=np.floor(np.stack([rfm.real,rfm.imag],2)*(1<<20)+.5).astype(int)
 def process(self,iq,stolt=True):
  a=np.asarray(iq,dtype=object);g=self.g
  if a.shape!=(g.nslow,g.nfast,2) or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or not -(1<<17)<=v<(1<<17) for v in a.flat):raise ValueError('signed18 Q17 echo')
  a=np.fft.ifftshift(a,axes=(0,1));a=np.asarray(a,dtype=np.int64)*16
  stats=sat_diag.SatStats();self.last_clip_count=0
  for i in range(g.nslow):a[i]=fft_fixed.forward(a[i].tolist(),in_width=22,width=24,stats=stats)
  for j in range(g.nfast):a[:,j]=fft_fixed.forward(a[:,j].tolist(),in_width=23,width=24,stats=stats)
  a=np.fft.fftshift(a,axes=(0,1));out=np.zeros_like(a);scale=1<<20
  for i in range(g.nslow):
   for j in range(g.nfast):
    x,y=map(int,a[i,j]);c,d=map(int,self.rfm[i,j]);out[i,j]=((x*c-y*d+scale//2)//scale,(x*d+y*c+scale//2)//scale)
  if stolt:
   a=out.copy();out[:]=0
   for i in range(g.nslow):
    for j in range(g.nfast):
     if self.support[i,j]:
      l=int(self.left[i,j]);f=int(self.frac[i,j])
      out[i,j]=[((scale-f)*int(a[i,l,c])+f*int(a[i,l+1,c])+scale//2)//scale for c in (0,1)]
  out=np.fft.ifftshift(out,axes=(0,1))
  for j in range(g.nfast):
   if np.max(abs(out[:,j]))>=(1<<22):raise OverflowError('inverseFFT headroom')
   out[:,j]=fft_fixed.inverse(out[:,j].tolist(),in_width=23,width=24,stats=stats)
  for i in range(g.nslow):
   if np.max(abs(out[i]))>=(1<<22):raise OverflowError('inverseFFT headroom')
   out[i]=fft_fixed.inverse(out[i].tolist(),in_width=23,width=24,stats=stats)
  self.last_clip_count=stats.total()
  if self.last_clip_count:raise OverflowError('FFT internal saturation detected')
  return (np.fft.fftshift(out,axes=(0,1))+8)//16
