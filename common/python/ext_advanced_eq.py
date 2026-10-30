"""M16/D8 oversampled complex PFB equalizer, source RRC512 prototype.

MDL uses two IFFTs, 32tap/phase, decimation8 and sqrt8 prototype. Here the
polyphase algebra is explicit: analysis=sum_l h[l]x[rD-l]exp(+j2pi kl/16),
synthesis=sum_r,k h[n-rD]exp(+j2pi k(n-rD)/16)*gain[k]*analysis[k,r].
Both transforms have SAME sign as source IFFTs; their 1/16 scale is compensated
at the API boundary. Unity has latency512 and slight windowed RRC PR error,
measured in tests, not falsely advertised as exact PR. Complex16band output.
"""
import numpy as np
try:from . import fft_fixed, research_core
except ImportError:
 import fft_fixed
 import research_core
M=16;D=8;Q=1<<17;W=1<<24

def prototype():
 beta=.92;t=.0625*(np.arange(511)-255)
 pulse=np.empty(511);nz=t!=0
 pulse[nz]=(np.sin(np.pi*(1-beta)*t[nz])+4*beta*t[nz]*np.cos(np.pi*(1+beta)*t[nz]))/(np.pi*t[nz]*(1-(4*beta*t[nz])**2))
 pulse[~nz]=1+beta*(4/np.pi-1)
 return np.sqrt(8)*np.r_[0.,.0625*pulse*np.kaiser(511,4.4)]

def _gains(gains):
 a=np.asarray(gains)
 if a.shape!=(16,) or np.iscomplexobj(a) or not np.isfinite(a).all() or np.any(a<0) or np.any(a>4):raise ValueError('16 real gains0..4')
 return np.array(a,float)
def _input(x):
 a=np.asarray(x,complex)
 if a.ndim!=1 or not np.isfinite(a).all():raise ValueError('finite complex1D')
 return a

def analysis(x):
 """Frames at input times0,8,... through tail511. Shape framesx16."""
 x=_input(x)
 if not len(x):return np.empty((0,16),complex)
 # Reuse existing validated analysis PFB, correcting its transform sign and
 # absolute end-time rotation to the source's two-IFFT convention.
 z=research_core.run('pfb',[M,D],np.pad(x,(0,511)),prototype()).reshape(-1,M)
 indices=(-np.arange(M))%M
 rotation=np.exp(2j*np.pi*np.arange(len(z))[:,None]*D*np.arange(M)[None,:]/M)
 return z[:,indices]*rotation

def synthesis(bands,gains=None):
 a=np.asarray(bands,complex)
 if a.ndim!=2 or a.shape[1]!=16 or not np.isfinite(a).all():raise ValueError('framesx16')
 g=np.ones(16) if gains is None else _gains(gains)
 if not len(a):return np.empty(0,complex)
 out=np.zeros((len(a)-1)*8+512,complex);h=prototype()
 for r,row in enumerate(a):
  poly=np.fft.ifft(row*g)*M
  out[r*8:r*8+512]+=h*np.tile(poly,32)
 return out

def equalize(x,gains=None):return synthesis(analysis(x),gains)

class EqualizerFixed:
 """Integer PFB FIR Q24 prototype/Q17 signal, existing fixed inverse FFTs.

 FFT internal widths24, output24 fractional17 headroom. Coefficient gainsQ24.
 Existing pfb_fixed uses Q15 input/Q17 taps and different intermediate
 scaling; Q24 prototype retains this source filter precision. Its FFT core
 is reused while the FIR accumulator profile is explicit here.
 Each IFFT unnormalized (existing fft_fixed.inverse convention) matches float
 API. Final reconstruction saturates signed18 only after full overlap-add.
 """
 def __init__(self,gains=None):
  self.h=np.floor(prototype()*W+.5).astype(np.int64);self.configure(np.ones(16) if gains is None else gains)
 def configure(self,gains):
  g=_gains(gains);self.g=np.floor(g*W+.5).astype(np.int64)
 def process(self,iq):
  a=np.asarray(iq,dtype=object)
  if a.size==0:return np.empty((0,2),np.int64)
  if a.ndim!=2 or a.shape[1]!=2 or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or not -Q<=v<Q for v in a.flat):raise ValueError('signed18 IQ')
  frames=(len(a)+511+7)//8;acc=[[0,0] for _ in range((frames-1)*8+512)]
  for r in range(frames):
   poly=[]
   for p in range(16):
    rr=ii=0
    for l in range(p,512,16):
     ix=r*8-l
     if 0<=ix<len(a):rr+=int(a[ix,0])*int(self.h[l]);ii+=int(a[ix,1])*int(self.h[l])
    poly.append(((rr+W//2)//W,(ii+W//2)//W))
   bands=fft_fixed.inverse(poly,in_width=22,width=24)
   weighted=[((int(v[0])*int(g)+W//2)//W,(int(v[1])*int(g)+W//2)//W) for v,g in zip(bands,self.g)]
   if any(abs(v)>=(1<<22) for row in weighted for v in row):raise OverflowError('spectral headroom')
   back=fft_fixed.inverse(weighted,in_width=23,width=24)
   for l in range(512):
    for c in (0,1):acc[r*8+l][c]+=(int(back[l%16][c])*int(self.h[l])+W//2)//W
  return np.asarray([[max(-Q,min(Q-1,v)) for v in row] for row in acc],np.int64)
