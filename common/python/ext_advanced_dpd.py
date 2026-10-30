"""All-power memory polynomial from MathWorks DPD Example (M5,K5).

Coefficients [power0..K-1, oldest..current] match original MATLAB column order.
Offline least-squares identifies forward PA or reversed I/O postdistorter.
Fixed streaming path uses integer sqrt magnitude, recurrent Q17 powers,
Q24 complex coefficients, full-precision sum then round/saturate signed18.
Synthetic experiments do not characterize measured hardware or online learning.
"""
import math
import numpy as np
Q=1<<17

def _params(memory,degree):
 for x in (memory,degree):
  if isinstance(x,bool) or not isinstance(x,int) or not 1<=x<=9:raise ValueError('memory/degree1..9')
def design(x,memory=5,degree=5):
 _params(memory,degree);x=np.asarray(x,complex)
 if x.ndim!=1 or len(x)<memory or not np.isfinite(x).all():raise ValueError('input length/finite')
 w=np.lib.stride_tricks.sliding_window_view(x,memory)
 return np.concatenate([w*abs(w)**k for k in range(degree)],axis=1)
def fit(x,y,memory=5,degree=5,rcond=None):
 a=design(x,memory,degree);y=np.asarray(y,complex)
 if y.shape!=(len(x),) or not np.isfinite(y).all():raise ValueError('target')
 c,res,rank,s=np.linalg.lstsq(a,y[memory-1:],rcond=rcond)
 if rank<memory*degree:raise ValueError('rank deficient identification')
 return c.reshape(degree,memory)

class MemoryPolynomial:
 def __init__(self,coefficients):
  c=np.asarray(coefficients,complex)
  if c.ndim!=2 or not np.isfinite(c).all():raise ValueError('coefficients')
  self.degree,self.memory=c.shape;_params(self.memory,self.degree);self.c=c.copy();self.reset()
 def configure(self,coefficients):
  c=MemoryPolynomial(coefficients)
  if c.c.shape!=self.c.shape:raise ValueError('atomic updates preserve dimensions/state')
  self.c=c.c
 def reset(self):self.history=[0j]*self.memory
 def next(self,x,accept=True):
  if not isinstance(accept,bool):raise ValueError('accept bool')
  if not np.isfinite(x):raise ValueError('input')
  h=self.history[1:]+[complex(x)]
  out=sum(self.c[k,m]*v*abs(v)**k for k in range(self.degree) for m,v in enumerate(h))
  if accept:self.history=h
  return out
 def process(self,x):return np.asarray([self.next(v) for v in x])

class MemoryPolynomialFixed:
 def __init__(self,coefficients):
  c=MemoryPolynomial(coefficients);self.memory=c.memory;self.degree=c.degree
  if np.max(abs(c.c))>=128:raise ValueError('Q24 coefficients require magnitude<128')
  self.c=[[(int(np.floor(v.real*(1<<24)+.5)),int(np.floor(v.imag*(1<<24)+.5))) for v in row] for row in c.c]
  self.reset();self.saturations=0
 def configure(self,coefficients):
  c=MemoryPolynomialFixed(coefficients)
  if (c.memory,c.degree)!=(self.memory,self.degree):raise ValueError('atomic updates preserve dimensions/state')
  self.c=c.c
 def reset(self):self.history=[(0,0)]*self.memory;self.saturations=0
 def next(self,x,accept=True):
  if not isinstance(accept,bool):raise ValueError('accept bool')
  if len(x)!=2 or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or not -Q<=v<Q for v in x):raise ValueError('signed18 IQ')
  h=self.history[1:]+[tuple(map(int,x))];ar=ai=0
  for m,(a,b) in enumerate(h):
   mag=math.isqrt(a*a+b*b);power=Q
   for k in range(self.degree):
    # Q17 basis round at each nonlinear stage, coefficients Q24.
    br=(a*power+Q//2)//Q;bi=(b*power+Q//2)//Q;c,d=self.c[k][m]
    ar+=br*c-bi*d;ai+=br*d+bi*c
    power=(power*mag+Q//2)//Q
  y=((ar+(1<<23))>>24,(ai+(1<<23))>>24)
  out=tuple(max(-Q,min(Q-1,v)) for v in y)
  if accept:self.history=h;self.saturations+=sum(v!=w for v,w in zip(y,out))
  return out
 def process(self,x):return np.asarray([self.next(v) for v in x],dtype=np.int64)

def nmse(actual,reference):
 a=np.asarray(actual);r=np.asarray(reference)
 if a.shape!=r.shape or np.sum(abs(r)**2)==0:raise ValueError('NMSE')
 return float(10*np.log10(max(np.sum(abs(a-r)**2),np.finfo(float).tiny)/np.sum(abs(r)**2)))
