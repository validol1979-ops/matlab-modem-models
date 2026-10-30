"""ULA MVDR/MUSIC/ESPRIT floating and partitioned fixed arithmetic models.

Broadside theta convention a[m]=exp(-j2pi d m sin(theta)), d in wavelengths.
Original Haupt Fig7_16 uses endfire cos(theta); theta here is 90deg-original.
Fixed covariance and beamforming/MUSIC projection are integer. Weight solve,
eigenspaces and ESPRIT rotation eigenproblem are explicitly OFFLINE floating;
this module does not claim a fixed eigensolver. No weight-energy normalization.
"""
import numpy as np
Q=1<<17;W=1<<24

def _m(m):
 if isinstance(m,bool) or m not in (4,8):raise ValueError('M4/8')
def steering(m,theta,spacing=.5):
 _m(m)
 if not np.isfinite(theta) or not -90<=theta<=90 or not np.isfinite(spacing) or not 0<spacing<=.5:raise ValueError('angle/spacing')
 return np.exp(-2j*np.pi*spacing*np.arange(m)*np.sin(np.deg2rad(theta)))
def _snap(x):
 x=np.asarray(x,complex)
 if x.ndim!=2 or x.shape[1]<1 or not np.isfinite(x).all():raise ValueError('snapshots MxN')
 _m(x.shape[0]);return x

def covariance(x):
 x=_snap(x);return x@x.conj().T/x.shape[1]
def mvdr(r,a,loading=1e-3):
 r=np.asarray(r,complex);a=np.asarray(a,complex)
 if r.ndim!=2 or r.shape[0]!=r.shape[1] or a.shape!=(r.shape[0],):raise ValueError('R/a shape')
 _m(len(a))
 if not np.isfinite(r).all() or not np.isfinite(a).all() or not np.isfinite(loading) or loading<0 or not np.allclose(r,r.conj().T,rtol=0,atol=1e-12):raise ValueError('Hermitian finite covariance/loading')
 if np.linalg.eigvalsh(r).min() < -1e-10:raise ValueError('covariance PSD')
 loaded=r+loading*np.eye(len(a));z=np.linalg.solve(loaded,a);den=np.vdot(a,z)
 if abs(den)<1e-15:raise ValueError('zero steering denominator')
 return z/den

def beamform(x,w):
 x=_snap(x);w=np.asarray(w,complex)
 if w.shape!=(x.shape[0],) or not np.isfinite(w).all():raise ValueError('weights')
 return w.conj()@x

def _subspaces(r,k):
 r=np.asarray(r,complex)
 if r.ndim!=2 or r.shape[0]!=r.shape[1] or not np.isfinite(r).all() or not np.allclose(r,r.conj().T,rtol=0,atol=1e-12):raise ValueError('Hermitian R')
 _m(len(r))
 if isinstance(k,bool) or k not in (1,2) or k>=len(r):raise ValueError('source count1/2')
 val,vec=np.linalg.eigh(r)
 if val.min()<-1e-10:raise ValueError('R PSD')
 return vec[:,:len(r)-k],vec[:,len(r)-k:]
def music(r,k,angles,spacing=.5):
 en,_=_subspaces(r,k);grid=np.asarray(angles,float)
 if grid.ndim!=1 or not np.isfinite(grid).all():raise ValueError('angles')
 return np.asarray([1/max(float(np.sum(abs(en.conj().T@steering(len(r),t,spacing))**2)),1e-30) for t in grid])
def esprit(r,k,spacing=.5):
 _,es=_subspaces(r,k)
 if not np.isfinite(spacing) or not 0<spacing<=.5:raise ValueError('spacing')
 phi=np.linalg.lstsq(es[:-1],es[1:],rcond=None)[0]
 u=-np.angle(np.linalg.eigvals(phi))/(2*np.pi*spacing)
 if np.any(abs(u)>1+1e-10):raise ArithmeticError('unphysical rotation')
 return np.sort(np.rad2deg(np.arcsin(np.clip(u,-1,1))))

def _iq(x):
 a=np.asarray(x,dtype=object)
 if a.ndim!=3 or a.shape[2]!=2 or a.shape[1]<1:raise ValueError('IQ MxNx2')
 _m(a.shape[0])
 if any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or not -Q<=v<Q for v in a.flat):raise ValueError('signed18 IQ')
 return a

def covariance_fixed(x,frac=24):
 """Qfrac covariance from exact signed18 Q17 IQ outer products/divide N."""
 a=_iq(x);m,n,_=a.shape
 if not isinstance(frac,int) or isinstance(frac,bool) or not 17<=frac<=30:raise ValueError('frac')
 out=np.zeros((m,m,2),np.int64);den=n*Q*Q;scale=1<<frac
 for i in range(m):
  for j in range(m):
   re=sum(int(a[i,t,0])*int(a[j,t,0])+int(a[i,t,1])*int(a[j,t,1]) for t in range(n))
   im=sum(int(a[i,t,1])*int(a[j,t,0])-int(a[i,t,0])*int(a[j,t,1]) for t in range(n))
   out[i,j]=((re*scale+den//2)//den,(im*scale+den//2)//den)
 # Exact Hermitian pair assignment: anti-symmetric imaginary rounding.
 for i in range(m):
  out[i,i,1]=0
  for j in range(i):out[i,j]=out[j,i,0],-out[j,i,1]
 return out

def covariance_float(q,frac=24):
 q=np.asarray(q)
 if q.ndim!=3 or q.shape[0]!=q.shape[1] or q.shape[2]!=2:raise ValueError('covariance IQ')
 return (q[:,:,0]+1j*q[:,:,1])/(1<<frac)

def weights_fixed(w):
 w=np.asarray(w,complex)
 if w.ndim!=1 or not np.isfinite(w).all() or np.max(abs(w))>=128:raise ValueError('Q24 weights magnitude<128')
 _m(len(w));return np.floor(np.c_[w.real,w.imag]*W+.5).astype(np.int64)
def beamform_fixed(x,weights):
 a=_iq(x);w=np.asarray(weights,dtype=object)
 if w.shape!=(a.shape[0],2) or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or abs(v)>=128*W for v in w.flat):raise ValueError('Q24 weights')
 out=[]
 for t in range(a.shape[1]):
  re=sum(int(a[m,t,0])*int(w[m,0])+int(a[m,t,1])*int(w[m,1]) for m in range(a.shape[0]))
  im=sum(int(a[m,t,1])*int(w[m,0])-int(a[m,t,0])*int(w[m,1]) for m in range(a.shape[0]))
  out.append(tuple(max(-Q,min(Q-1,(v+W//2)//W)) for v in (re,im)))
 return np.asarray(out,np.int64)

def music_fixed(rq,k,angles,spacing=.5,frac=24):
 """Offline eig from integer covariance; Q24 noise eigenvectors/steering.

 Dynamic projection multiply/accumulate and squared denominator are integer.
 Returns Q48 denominators (small means peak), avoiding floating reciprocal.
 """
 en,_=_subspaces(covariance_float(rq,frac),k)
 er=np.floor(en.real*W+.5).astype(np.int64);ei=np.floor(en.imag*W+.5).astype(np.int64)
 out=[]
 for t in angles:
  a=steering(len(rq),t,spacing);ar=np.floor(a.real*W+.5).astype(np.int64);ai=np.floor(a.imag*W+.5).astype(np.int64)
  den=0
  for j in range(en.shape[1]):
   re=(sum(int(er[m,j])*int(ar[m])+int(ei[m,j])*int(ai[m]) for m in range(len(a)))+W//2)//W
   im=(sum(int(er[m,j])*int(ai[m])-int(ei[m,j])*int(ar[m]) for m in range(len(a)))+W//2)//W
   den+=re*re+im*im
  out.append(den)
 return np.asarray(out,dtype=object)
