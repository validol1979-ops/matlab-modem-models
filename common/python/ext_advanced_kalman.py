"""Linear KF: innovation solve and Joseph covariance update.

Chen 6.25--6.30 motivates the state model; its 6.29a omits the inverse.
Here K solves S K.T = H P, independently specified. Fixed runtime uses Q24
integer products with rounding at each matrix multiplication and rational solve.
This is an executable arithmetic model, not a bounded-latency RTL solver.
"""
from fractions import Fraction
import numpy as np


def _matrix(a, shape, name, positive=False, strict=False):
    if np.iscomplexobj(a): raise ValueError(name+' real values required')
    a=np.asarray(a,dtype=float)
    if a.shape!=shape or not np.isfinite(a).all(): raise ValueError(name+' shape/finite')
    if positive and (not np.allclose(a,a.T,rtol=0,atol=1e-12) or np.linalg.eigvalsh(a).min() < (1e-14 if strict else -1e-12)):
        raise ValueError(name+' must be symmetric '+('positive definite' if strict else 'PSD'))
    return a.copy()


class Kalman:
    def __init__(self,F,H,Q,R,x0,P0):
        if np.iscomplexobj(x0): raise ValueError('x0 real values required')
        x=np.asarray(x0,dtype=float)
        if x.ndim!=1 or len(x) not in (1,2,4) or not np.isfinite(x).all(): raise ValueError('x0')
        n=len(x); h=np.asarray(H)
        if h.ndim!=2 or h.shape[0] not in (1,2): raise ValueError('H')
        m=h.shape[0]
        self.F=_matrix(F,(n,n),'F');self.H=_matrix(H,(m,n),'H')
        self.Q=_matrix(Q,(n,n),'Q',True);self.R=_matrix(R,(m,m),'R',True,True)
        self.x0=x.copy();self.P0=_matrix(P0,(n,n),'P0',True);self.reset()
    def reset(self): self.x=self.x0.copy();self.P=self.P0.copy();self.K=None;self.innovation=None
    def step(self,z=None):
        xp=self.F@self.x;pp=self.F@self.P@self.F.T+self.Q
        if z is None:
            self.x=xp;self.P=(pp+pp.T)*.5;self.K=None;self.innovation=None
        else:
            z=_matrix(z,(self.H.shape[0],),'z');v=z-self.H@xp
            s=self.H@pp@self.H.T+self.R
            k=np.linalg.solve(s,self.H@pp).T
            a=np.eye(len(xp))-k@self.H
            p=a@pp@a.T+k@self.R@k.T
            self.x=xp+k@v;self.P=(p+p.T)*.5;self.K=k;self.innovation=v
        return self.x.copy(),self.P.copy()


def _rnd(n,d): return (2*n+d)//(2*d)
def _int(a): return [[int(x) for x in row] for row in np.asarray(a,dtype=object)]
def _t(a): return list(map(list,zip(*a)))
def _add(a,b,sign=1): return [[x+sign*y for x,y in zip(ar,br)] for ar,br in zip(a,b)]
def _mul(a,b,scale):
    bt=_t(b)
    return [[_rnd(sum(x*y for x,y in zip(ar,bc)),scale) for bc in bt] for ar in a]
def _bound(a):
    if any(abs(x)>=(1<<62) for row in a for x in row): raise OverflowError('Q arithmetic exceeds signed63 contract')
    return a

def _solve(s,b):
    """Exact rational Gauss--Jordan; no floating arithmetic in dynamic solve."""
    n=len(s);m=len(b[0]);a=[[Fraction(x) for x in sr+br] for sr,br in zip(s,b)]
    for j in range(n):
        pivot=next((i for i in range(j,n) if a[i][j]),None)
        if pivot is None: raise ArithmeticError('singular innovation')
        a[j],a[pivot]=a[pivot],a[j]
        v=a[j][j];a[j]=[x/v for x in a[j]]
        for i in range(n):
            if i!=j:
                v=a[i][j];a[i]=[x-v*y for x,y in zip(a[i],a[j])]
    return [row[n:] for row in a]

class KalmanFixed:
    """Q24 state/covariance/config; exact products and rational innovation solve.

    Python integers prevent accumulator overflow. Stored quantities outside
    signed63 are rejected rather than silently wrapped/saturated. PSD within
    quantization is measured by callers; Joseph rounding need not preserve
    exact PSD for singular covariance. Config validation occurs offline.
    """
    def __init__(self,F,H,Q,R,x0,P0,frac=24):
        if isinstance(frac,bool) or not isinstance(frac,int) or not 12<=frac<=32: raise ValueError('frac')
        self.frac=frac;self.scale=1<<frac;validated=Kalman(F,H,Q,R,x0,P0)
        q=lambda a:_bound(_int(np.floor(np.asarray(a)*self.scale+.5)))
        self.F=q(validated.F);self.H=q(validated.H);self.Q=q(validated.Q);self.R=q(validated.R)
        self.x0=q(validated.x0[:,None]);self.P0=q(validated.P0)
        for name,mat,strict in [('R',self.R,True),('Q',self.Q,False),('P0',self.P0,False)]:
            _matrix(np.asarray(mat,dtype=float)/self.scale,np.asarray(mat).shape,'quantized '+name,True,strict)
        # Quantization must not make positive measurement noise singular.
        _solve(self.R,[[int(i==j) for j in range(len(self.R))] for i in range(len(self.R))])
        self.reset()
    def reset(self): self.x=[r[:] for r in self.x0];self.P=[r[:] for r in self.P0];self.K=None;self.innovation=None
    def step(self,z=None):
        s=self.scale;mm=lambda a,b:_bound(_mul(a,b,s))
        xp=mm(self.F,self.x);pp=_bound(_add(mm(mm(self.F,self.P),_t(self.F)),self.Q))
        if z is None: self.x=xp;self.P=pp;self.K=None;self.innovation=None
        else:
            a=np.asarray(z,dtype=object)
            if a.shape!=(len(self.H),) or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) for v in a): raise ValueError('z must be Q integer vector')
            zz=_bound([[int(v)] for v in a]);v=_add(zz,mm(self.H,xp),-1)
            innovation=_bound(_add(mm(mm(self.H,pp),_t(self.H)),self.R))
            hpp=mm(self.H,pp);solution=_solve(innovation,hpp)
            kt=[[_rnd(v.numerator*s,v.denominator) for v in row] for row in solution];k=_bound(_t(kt))
            ident=[[s*int(i==j) for j in range(len(xp))] for i in range(len(xp))]
            aa=_add(ident,mm(k,self.H),-1)
            p=_bound(_add(mm(mm(aa,pp),_t(aa)),mm(mm(k,self.R),_t(k))))
            self.x=_bound(_add(xp,mm(k,v)));self.P=p;self.K=k;self.innovation=v
        self.P=[[_rnd(self.P[i][j]+self.P[j][i],2) for j in range(len(self.P))] for i in range(len(self.P))]
        return np.asarray(self.x,dtype=np.int64).ravel(),np.asarray(self.P,dtype=np.int64)
