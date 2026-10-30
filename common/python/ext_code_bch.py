"""Narrow-sense BCH255,223,t4 using SOURCE primitive0x171 (not RS0x11d).

Systematic high-degree-first bits; shortening removes leading zero payload bits.
BM/Chien integer decoder preserves received on detected failure. Above t errors
may decode another valid codeword; no universal detection guarantee.
"""
from functools import lru_cache
from ext_code_gf import GF,DecodeResult,symbols

@lru_cache(maxsize=16)
def bch_generator(m=8,t=4,primitive=0x171):
    if not isinstance(m,int) or isinstance(m,bool) or not 2<=m<=12:raise ValueError('invalid m')
    if not isinstance(t,int) or isinstance(t,bool) or not 1<=t<(1<<m)//2:raise ValueError('invalid t')
    f=GF(m,primitive);roots=set()
    for exponent in range(1,2*t+1):
        e=exponent
        while e not in roots:roots.add(e);e=e*2%f.order
    p=[1]
    for e in sorted(roots):p=f.poly_mul(p,[f.alpha(e),1])
    if any(v not in (0,1) for v in p):raise ValueError('nonbinary generator')
    return sum(v<<i for i,v in enumerate(p))

def _mod(value,g):
    while value.bit_length()>=g.bit_length():value^=g<<(value.bit_length()-g.bit_length())
    return value

def _params(n,m,t,primitive):
    g=bch_generator(m,t,primitive);r=g.bit_length()-1
    if not r<n<=(1<<m)-1:raise ValueError('invalid BCH length')
    return GF(m,primitive),g,r

def bch_encode(bits,m=8,t=4,primitive=0x171):
    bits=symbols(bits,1);g=bch_generator(m,t,primitive);r=g.bit_length()-1
    _params(len(bits)+r,m,t,primitive);value=0
    for b in bits:value=(value<<1)|b
    code=(value<<r)^_mod(value<<r,g)
    return [code>>(len(bits)+r-1-i)&1 for i in range(len(bits)+r)]

def bch_syndromes(word,m=8,t=4,primitive=0x171):
    f=GF(m,primitive)
    return [f.eval(list(reversed(word)),f.alpha(j)) for j in range(1,2*t+1)]

def bch_decode(received,m=8,t=4,primitive=0x171):
    word=symbols(received,1);f,g,r=_params(len(word),m,t,primitive);n=len(word)
    synd=bch_syndromes(word,m,t,primitive)
    if not any(synd):return DecodeResult(word[:-r],word.copy(),'clean',[])
    locator=f.bm(synd)
    positions=[p for p in range(n) if f.eval(locator,f.alpha(-(n-1-p)))==0]
    if len(positions)!=len(locator)-1 or len(positions)>t:return DecodeResult(word[:-r],word.copy(),'failed',[])
    corrected=word.copy()
    for p in positions:corrected[p]^=1
    if any(bch_syndromes(corrected,m,t,primitive)):return DecodeResult(word[:-r],word.copy(),'failed',[])
    return DecodeResult(corrected[:-r],corrected,'corrected',positions)
