"""Source-inspired SPC/eHamming product code soft model, no shortening.

SPC8x8/eHAM8x8/eHAM16x16. Explicit positional Hamming layout differs from
source systematic permutation; no WiMAX conformance. Row then column encoding,
row-major payload in component data positions. Positive0 adapts sourcepositive1.
Source FastChase8/16 candidates, min0/min1/max/4 extrinsic schedule; this soft
approximation is not exact per-bit ML. Fixed Q3 signed8 clips every exchange;
integer weighted metrics and quarter fallback, alpha=[1/2,3/4,1,1], nearest/away
scaling, 4iterations default. Complete-frame calls are stateless/atomic.
"""
from fractions import Fraction
from dataclasses import dataclass
from functools import lru_cache
from itertools import product
from math import isfinite
from ext_code_basics import hamming_encode,hamming_decode

@dataclass
class ComponentResult:
    bits:list
    posterior:list
    extrinsic:list
    candidates:list

@dataclass
class BTCResult:
    bits:list
    codeword:list
    iterations:int
    trace:list
    valid:bool

def data_positions(n,kind):
    if not isinstance(n,int) or isinstance(n,bool):raise ValueError('integer block length required')
    if kind=='spc' and n==8:return list(range(n-1))
    if kind=='eham' and n in (8,16):return [p-1 for p in range(1,n) if p&(p-1)]
    raise ValueError('supported: SPC8, eHAM8/16')

def _encode(bits,kind):
    if kind=='eham':return hamming_encode(bits)
    if any(not isinstance(v,int) or isinstance(v,bool) or v not in (0,1) for v in bits):raise ValueError('invalid bits')
    return list(bits)+[sum(bits)%2]

def _valid(word,kind):return word==_encode([word[p] for p in data_positions(len(word),kind)],kind)

def btc_encode(bits,n=8,kind='eham'):
    positions=data_positions(n,kind);k=len(positions);bits=list(bits)
    if len(bits)!=k*k or any(not isinstance(v,int) or isinstance(v,bool) or v not in (0,1) for v in bits):raise ValueError('invalid payload')
    rows=[_encode(bits[i*k:(i+1)*k],kind) for i in range(k)];word=[[0]*n for _ in range(n)]
    for j in range(n):
        column=_encode([rows[i][j] for i in range(k)],kind)
        for i in range(n):word[i][j]=column[i]
    return word

def _values(llrs):
    a=list(llrs)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) for v in a):raise ValueError('nonfinite/nonreal LLR')
    return a

def component_decode(llrs,kind='eham',fixed=False):
    a=_values(llrs);n=len(a);data_positions(n,kind);hard=[int(v<0) for v in a]
    if fixed and any(not isinstance(v,int) for v in a):raise ValueError('integer component metrics required')
    if kind=='spc':
        ext=[]
        for i in range(n):
            others=[v for j,v in enumerate(a) if j!=i];sign=-1 if sum(v<0 for v in others)%2 else 1
            ext.append(sign*min(abs(v) for v in others))
        corrected=hard.copy()
        if sum(hard)%2:corrected[min(range(n),key=lambda i:(abs(a[i]),i))]^=1
        return ComponentResult(corrected,[x+y for x,y in zip(a,ext)],ext,[])
    least=sorted(range(n),key=lambda i:(abs(a[i]),i))[:3 if n==8 else 4];candidates=set()
    for binary in range(1<<len(least)):
        pattern=binary^(binary>>1);trial=hard.copy()
        for j,p in enumerate(least):trial[p]^=pattern>>j&1
        _,status,word=hamming_decode(trial)
        if status=='detected_double':continue
        correction=[i for i,(x,y) in enumerate(zip(trial,word)) if x!=y]
        if correction and correction[0] in least:continue
        candidates.add(tuple(word))
    ordered=sorted((sum(abs(v) for v,x,y in zip(a,hard,word) if x!=y),sum(b<<i for i,b in enumerate(word)),word) for word in candidates)
    if not ordered:return ComponentResult(hard,a.copy(),[0]*n,[])
    cost,_,best=ordered[0];second=ordered[1] if len(ordered)>1 else ordered[0];worst=ordered[-1];ext=[]
    for i,b in enumerate(best):
        sign=1-2*b
        value=sign*(second[0]-cost)-a[i] if b!=second[2][i] else sign*((worst[0]-cost)//4 if fixed else (worst[0]-cost)/4)
        ext.append(value)
    return ComponentResult(list(best),[x+y for x,y in zip(a,ext)],ext,[(v,list(w)) for v,_,w in ordered])

@lru_cache(maxsize=8)
def _codebook(n,kind):
    k=len(data_positions(n,kind));return tuple(tuple(_encode(list(bits),kind)) for bits in product((0,1),repeat=k))

def component_exact(llrs,kind='eham'):
    """Independent exhaustive max-log reference for small components only."""
    a=_values(llrs);book=_codebook(len(a),kind);scores=[sum((1-2*b)*v for b,v in zip(word,a)) for word in book]
    return [(max(s for s,w in zip(scores,book) if w[i]==0)-max(s for s,w in zip(scores,book) if w[i]==1))/2 for i in range(len(a))]

def btc_decode(llrs,kind='eham',iterations=4,quant_bits=None,frac_bits=3,early_stop=False):
    rows=[_values(row) for row in llrs];n=len(rows);positions=data_positions(n,kind)
    if any(len(row)!=n for row in rows) or not isinstance(iterations,int) or isinstance(iterations,bool) or not 1<=iterations<=16:raise ValueError('invalid frame/iterations')
    fixed=quant_bits is not None
    if fixed and (not isinstance(quant_bits,int) or isinstance(quant_bits,bool) or not 2<=quant_bits<=24 or not isinstance(frac_bits,int) or isinstance(frac_bits,bool) or not 0<=frac_bits<quant_bits):raise ValueError('invalid quantizer')
    clips=0
    def clip(v):
        nonlocal clips
        if not fixed:return v
        q=max(-(1<<(quant_bits-1)),min((1<<(quant_bits-1))-1,v));clips+=int(q!=v);return q
    channel=[[clip(round(Fraction(v)*(1<<frac_bits))) if fixed else v for v in row] for row in rows]
    row_ext=[[0]*n for _ in range(n)];col_ext=[[0]*n for _ in range(n)];trace=[];posterior=channel
    for iteration in range(iterations):
        numerator,denominator=((1,2),(3,4),(1,1),(1,1))[min(iteration,3)]
        def scaled(v):
            if not fixed:return v*numerator/denominator
            q=(abs(v)*numerator+denominator//2)//denominator
            return q if v>=0 else -q
        for direction in ('row','column'):
            posterior=[[0]*n for _ in range(n)]
            for i in range(n):
                values=[clip(channel[i][j]+scaled(col_ext[i][j])) if direction=='row' else clip(channel[j][i]+scaled(row_ext[j][i])) for j in range(n)]
                result=component_decode(values,kind,fixed)
                for j in range(n):
                    r,c=(i,j) if direction=='row' else (j,i)
                    (row_ext if direction=='row' else col_ext)[r][c]=clip(result.extrinsic[j]);posterior[r][c]=clip(result.posterior[j])
            hard=[[int(v<0) for v in row] for row in posterior]
            invalid=sum(not _valid(row,kind) for row in hard)+sum(not _valid([hard[i][j] for i in range(n)],kind) for j in range(n))
            trace.append({'iteration':iteration+1,'direction':direction,'posterior_first8':posterior[0][:8],'extrinsic_first8':(row_ext if direction=='row' else col_ext)[0][:8],'min':min(map(min,posterior)),'max':max(map(max,posterior)),'invalid_components':invalid,'clips':clips})
        if early_stop and invalid==0:break
    return BTCResult([hard[i][j] for i in positions for j in positions],hard,iteration+1,trace,invalid==0)
