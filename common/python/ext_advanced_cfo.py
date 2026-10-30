"""Hoseyni/Ilow CFO characteristic-function model, eq12/17/19.

paper_sinc reproduces NONPERIODIC real sinc(m-k+x). fft_dirichlet is an
explicit finite-N FFT adaptation: samples multiplied exp(-j2pi*x*n/N).
The two operators are intentionally distinct; neither is Schmidl--Cox.
Cramer's determinant real roots are candidates, checked by complex pilot
residual and condition number. Singular matrices/ambiguous roots reject.
"""
import math
import numpy as np
from scipy.optimize import brentq
Q=1<<17;W=1<<24

def mixing(n,x,model='paper_sinc'):
 if isinstance(n,bool) or not isinstance(n,int) or not 4<=n<=64 or not np.isfinite(x):raise ValueError('N4..64/finite CFO')
 j=np.arange(n);d=j[:,None]-j[None,:]+x
 if model=='paper_sinc':return np.sinc(d).astype(complex)
 if model=='fft_dirichlet':return np.exp(-2j*np.pi*d[:,:,None]*j[None,None,:]/n).mean(2)
 raise ValueError('unknown spectral model')
def _data(b,pilot):
 b=np.asarray(b,complex)
 if b.ndim!=1 or not 4<=len(b)<=64 or not np.isfinite(b).all() or not np.isscalar(pilot) or not np.isfinite(pilot) or abs(pilot)==0:raise ValueError('finite B/nonzero pilot atindex0')
 return b,complex(pilot)
def characteristic(x,b,pilot,model='paper_sinc'):
 b,pilot=_data(b,pilot);s=mixing(len(b),x,model);s1=s.copy();s1[:,0]=b
 return pilot*np.linalg.det(s)-np.linalg.det(s1)
def pilot_residual(x,b,pilot,model='paper_sinc'):
 b,pilot=_data(b,pilot);s=mixing(len(b),x,model)
 if np.linalg.cond(s)>1e10:raise ArithmeticError('ill-conditioned mixing')
 return np.linalg.solve(s,b)[0]-pilot

def estimate_cfo(b,pilot,model='paper_sinc',bounds=(-.8,.8),grid=129,tolerance=1e-7,maxiter=80):
 b,pilot=_data(b,pilot)
 lo,hi=bounds
 if not np.isfinite([lo,hi,tolerance]).all() or not -.95<=lo<hi<=.95 or tolerance<=0 or isinstance(grid,bool) or not isinstance(grid,int) or not 17<=grid<=2049 or isinstance(maxiter,bool) or not isinstance(maxiter,int) or maxiter<8:raise ValueError('bounded search parameters')
 axis=np.linspace(lo,hi,grid);vals=[characteristic(x,b,pilot,model).real for x in axis];roots=[]
 if max(abs(v) for v in vals)<1e-12*(np.linalg.norm(b)+abs(pilot)):raise ArithmeticError('degenerate real characteristic')
 f=lambda x:characteristic(x,b,pilot,model).real
 for i,v in enumerate(vals):
  if abs(v)<1e-14:roots.append(float(axis[i]))
  if i and v*vals[i-1]<0:
   roots.append(float(brentq(f,axis[i-1],axis[i],xtol=1e-13,maxiter=maxiter)))
 unique=[]
 for r in sorted(roots):
  if not unique or abs(r-unique[-1])>1e-7:unique.append(r)
 accepted=[]
 for r in unique:
  try:e=abs(pilot_residual(r,b,pilot,model))
  except (ArithmeticError,np.linalg.LinAlgError):continue
  if e<=tolerance:accepted.append((e,r))
 if len(accepted)!=1:raise ArithmeticError('no unique complex-consistent CFO root')
 return accepted[0][1]

def correct_spectrum(b,x,model='paper_sinc'):
 b=np.asarray(b,complex);s=mixing(len(b),x,model)
 if b.ndim!=1 or not np.isfinite(b).all() or np.linalg.cond(s)>1e10:raise ValueError('B/condition')
 return np.linalg.solve(s,b)
def correct_time(x,cfo,nfft=None,start_index=0):
 a=np.asarray(x,complex);n=len(a) if nfft is None else nfft
 if a.ndim!=1 or not np.isfinite(a).all() or not np.isfinite(cfo) or n<=0 or not isinstance(start_index,int):raise ValueError('time input/config')
 return a*np.exp(2j*np.pi*cfo*(np.arange(len(a))+start_index)/n)

class FixedCFO:
 """Offline grid of inverse pilot rows; runtime integer characteristic search.

 For paper_sinc the determinant is real, so real Cramer and real pilot
 residual zeros agree away from singularity. For fft_dirichlet this is an
 explicitly PROJECT-DERIVED fixed grid pilot-residual adaptation; complex
 determinant phase means its real roots differ from real Cramer roots. Q24 inverse-pilot rows
 are precomputed offline; runtime Q17 samples ->integerpilotresidual and
 complex residual rejection. Bounded discrete root profile, no float solver
 in runtime. N4..16, grid257..4097; correction uses phase32 LUT16/mult Q17.
 """
 def __init__(self,n,pilot,model='paper_sinc',bounds=(-.8,.8),grid=1025):
  if isinstance(n,bool) or not isinstance(n,int) or not 4<=n<=16 or isinstance(grid,bool) or not isinstance(grid,int) or not 257<=grid<=4097:raise ValueError('fixed profile N4..16/grid257..4097')
  _data(np.zeros(n),pilot)
  lo,hi=bounds
  if not np.isfinite([lo,hi]).all() or not -.9<=lo<hi<=.9:raise ValueError('bounds')
  self.n=n;self.axis=np.linspace(lo,hi,grid);self.pilot=(int(np.floor(complex(pilot).real*Q+.5)),int(np.floor(complex(pilot).imag*Q+.5)))
  self.rows=[]
  for x in self.axis:
   s=mixing(n,x,model)
   if np.linalg.cond(s)>1e8:raise ValueError('profile illconditioned')
   row=np.linalg.solve(s.T,np.eye(n)[:,0])
   self.rows.append([(int(np.floor(v.real*W+.5)),int(np.floor(v.imag*W+.5))) for v in row])
 def estimate(self,iq,tolerance_q=256):
  a=np.asarray(iq,dtype=object)
  if a.shape!=(self.n,2) or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or abs(v)>=(1<<22) for v in a.flat):raise ValueError('signed23 spectral IQ Q17')
  if isinstance(tolerance_q,bool) or not isinstance(tolerance_q,int) or tolerance_q<=0:raise ValueError('tolerance Q17')
  errors=[]
  for row in self.rows:
   re=sum(int(x)*c-int(y)*d for (x,y),(c,d) in zip(a,row));im=sum(int(x)*d+int(y)*c for (x,y),(c,d) in zip(a,row))
   rr=(re+W//2)//W-self.pilot[0];ii=(im+W//2)//W-self.pilot[1]
   errors.append((rr,ii))
  candidates=set()
  for j,(re,im) in enumerate(errors):
   if re==0:candidates.add(j)
   if j and re*errors[j-1][0]<0:candidates.update((j-1,j))
  ranked=sorted((errors[j][0]**2+errors[j][1]**2,j) for j in candidates)
  if not ranked or ranked[0][0]>tolerance_q**2:raise ArithmeticError('no complex consistent fixed grid root')
  best=ranked[0][1]
  if any(e<=tolerance_q**2 and abs(j-best)>2 for e,j in ranked[1:]):raise ArithmeticError('ambiguous fixed roots')
  return float(self.axis[best])

def correct_time_fixed(iq,cfo,nfft=None,start_index=0):
 a=np.asarray(iq,dtype=object);n=len(a) if nfft is None else nfft
 if a.ndim!=2 or a.shape[1]!=2 or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or not -Q<=v<Q for v in a.flat) or n<=0 or not np.isfinite(cfo) or not isinstance(start_index,int):raise ValueError('Q17 time input/config')
 step=int(np.floor(cfo/n*2**32+.5));phase=(step*start_index)&0xffffffff
 # Offline trigonometric LUT. Runtime indexes/rotates only integer values.
 idx=np.arange(65536);cs=np.floor(np.cos(2*np.pi*idx/65536)*Q+.5).astype(int);sn=np.floor(np.sin(2*np.pi*idx/65536)*Q+.5).astype(int)
 out=[]
 for x,y in a:
  c,d=int(cs[phase>>16]),int(sn[phase>>16]);re=(int(x)*c-int(y)*d+Q//2)//Q;im=(int(x)*d+int(y)*c+Q//2)//Q
  out.append((max(-Q,min(Q-1,re)),max(-Q,min(Q-1,im))));phase=(phase+step)&0xffffffff
 return np.asarray(out,np.int64)
