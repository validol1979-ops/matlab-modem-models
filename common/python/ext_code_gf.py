"""Exact polynomial-basis GF(2^m) helpers; coefficients explicitly ascending."""
from dataclasses import dataclass

class GF:
    def __init__(self,m=8,primitive=0x11d):
        if not isinstance(m,int) or isinstance(m,bool) or not 2<=m<=12 or not isinstance(primitive,int) or isinstance(primitive,bool) or primitive<=0 or not primitive&1 or primitive.bit_length()!=m+1:raise ValueError('invalid field')
        self.m=m;self.primitive=primitive;self.order=(1<<m)-1
        self.exp=[];self.log=[-1]*(1<<m);x=1
        for i in range(self.order):
            if self.log[x]!=-1:raise ValueError('polynomial is not primitive for alpha=2')
            self.exp.append(x);self.log[x]=i;x<<=1
            if x&(1<<m):x^=primitive
        if x!=1:raise ValueError('field cycle does not close')
    def _value(self,v):
        if not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=self.order:raise ValueError('invalid field element')
    def mul(self,a,b):
        self._value(a);self._value(b)
        return 0 if not a or not b else self.exp[(self.log[a]+self.log[b])%self.order]
    def div(self,a,b):
        self._value(a);self._value(b)
        if not b:raise ZeroDivisionError('GF division by zero')
        return 0 if not a else self.exp[(self.log[a]-self.log[b])%self.order]
    def alpha(self,n):
        if not isinstance(n,int) or isinstance(n,bool):raise ValueError('invalid exponent')
        return self.exp[n%self.order]
    def eval(self,p,x):
        p=symbols(p,self.order);self._value(x)
        value=0
        for c in reversed(p):value=self.mul(value,x)^c
        return value
    def poly_mul(self,a,b):
        a=symbols(a,self.order);b=symbols(b,self.order)
        if not a or not b:raise ValueError('empty polynomial')
        out=[0]*(len(a)+len(b)-1)
        for i,x in enumerate(a):
            for j,y in enumerate(b):out[i+j]^=self.mul(x,y)
        return out
    def bm(self,sequence):
        sequence=symbols(sequence,self.order)
        c=[1];bpoly=[1];length=0;shift=1;previous=1
        for n,s in enumerate(sequence):
            d=s
            for i in range(1,length+1):d^=self.mul(c[i] if i<len(c) else 0,sequence[n-i])
            if not d:shift+=1;continue
            old=c.copy();factor=self.div(d,previous)
            c += [0]*max(0,len(bpoly)+shift-len(c))
            for i,v in enumerate(bpoly):c[i+shift]^=self.mul(factor,v)
            if 2*length<=n:length=n+1-length;bpoly=old;previous=d;shift=1
            else:shift+=1
        while len(c)>1 and not c[-1]:c.pop()
        return c
    def solve(self,matrix,rhs):
        matrix=[symbols(row,self.order) for row in matrix];rhs=symbols(rhs,self.order)
        if len(matrix)!=len(rhs) or any(len(row)!=len(rhs) for row in matrix):raise ValueError('invalid square system')
        a=[list(row)+[v] for row,v in zip(matrix,rhs)];n=len(a)
        for i in range(n):
            pivot=next((j for j in range(i,n) if a[j][i]),None)
            if pivot is None:raise ValueError('singular GF system')
            a[i],a[pivot]=a[pivot],a[i];v=a[i][i]
            a[i]=[self.div(x,v) for x in a[i]]
            for j in range(n):
                if j!=i and a[j][i]:
                    v=a[j][i];a[j]=[x^self.mul(v,y) for x,y in zip(a[j],a[i])]
        return [row[-1] for row in a]

@dataclass
class DecodeResult:
    data:list
    codeword:list
    status:str
    corrected_positions:list

def symbols(values,maximum):
    out=list(values)
    if any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=maximum for v in out):raise ValueError('invalid symbol')
    return out
