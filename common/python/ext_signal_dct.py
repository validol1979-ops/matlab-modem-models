"""Orthonormal DCT-II frame codec; coefficient selection is a lossy projection.

Alasooly DCT-compression example motivates retain N,N/2,N/4,N/8 (project N32/128).
Integer path uses an offline signed18 Q17 transform matrix, exact signed64 dots,
round-half-up per transform, signed24 encoded coefficients and signed18 decoded
samples. This is a numerical model; no timing or entropy coding claim.
"""
import numbers
import numpy as np


def _integer(v,lo,hi):
    if isinstance(v,(bool,np.bool_)) or not isinstance(v,numbers.Integral) or not lo<=v<=hi:raise ValueError('integer out of range')
    return int(v)


class DCTCodec:
    def __init__(self,n=32,keep=None,fixed=False):
        if type(fixed) is not bool:raise ValueError('fixed must be bool')
        self.fixed=fixed;self.configure(n,keep)
    def configure(self,n,keep=None):
        n=_integer(n,32,128)
        if n not in (32,128):raise ValueError('supported N32/128')
        k=n if keep is None else _integer(keep,1,n)
        if k not in (n,n//2,n//4,n//8):raise ValueError('retain N,N/2,N/4,N/8')
        c=np.cos(np.pi*np.outer(np.arange(n),np.arange(n)+.5)/n)*np.sqrt(2/n);c[0]/=np.sqrt(2)
        self.n,self.keep,self.matrix=n,k,c
        self.qmatrix=np.rint(c*2**17).astype(np.int64)
        self.clippings=0
    def _frame(self,x,width):
        if np.asarray(x).ndim!=1:raise ValueError("one-dimensional frame required")
        try:a=list(x)
        except TypeError:raise ValueError('frame sequence required') from None
        if len(a)!=self.n:raise ValueError('frame length')
        if self.fixed:return [_integer(v,-(1<<(width-1)),(1<<(width-1))-1) for v in a]
        try:z=np.asarray(a)
        except (TypeError,ValueError):raise ValueError('real finite frame') from None
        if np.iscomplexobj(z) or z.dtype.kind=='b':raise ValueError('real frame required')
        try:z=z.astype(float)
        except (TypeError,ValueError):raise ValueError('real frame required') from None
        if not np.isfinite(z).all():raise ValueError('finite frame required')
        return z
    def _dot(self,m,x,width):
        out=[];limit=(1<<(width-1))-1
        for row in m:
            raw=sum(int(a)*int(b) for a,b in zip(row,x))
            if not -(1<<63)<=raw<(1<<63):raise OverflowError('signed64 dot')
            y=(raw+2**16)>>17
            if y < -limit-1 or y>limit:self.clippings+=1
            out.append(min(limit,max(-limit-1,y)))
        return out
    def encode(self,frame):
        x=self._frame(frame,18)
        if self.fixed:y=self._dot(self.qmatrix,x,24);return y[:self.keep]+[0]*(self.n-self.keep)
        y=self.matrix@x;y[self.keep:]=0;return y
    def decode(self,coefficients):
        x=self._frame(coefficients,24)
        return self._dot(self.qmatrix.T,x,18) if self.fixed else self.matrix.T@x
    def process(self,frame):return self.decode(self.encode(frame))
    def process_stream(self,samples,tail='drop'):
        if tail not in ('drop','pad','error'):raise ValueError('tail policy')
        x=list(samples);rem=len(x)%self.n
        if rem and tail=='error':raise ValueError('incomplete frame')
        if rem and tail=='pad':x.extend([0]*(self.n-rem))
        return [v for i in range(0,len(x)-self.n+1,self.n) for v in self.process(x[i:i+self.n])]
