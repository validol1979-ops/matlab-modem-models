"""RS(240,210) source profile: GF256/0x11d, roots alpha^0..29.

Highest-degree symbol first, systematic payload then parity; leading-zero
shortening. Exact GF integer model. Errors/erasures satisfy 2e+v<=nsym.
Failure preserves received symbols. Beyond radius miscorrection is possible.
"""
from ext_code_gf import GF,DecodeResult,symbols
F=GF()

def _check(nsym,n):
    if not isinstance(nsym,int) or isinstance(nsym,bool) or not 1<=nsym<255 or not nsym<n<=255:raise ValueError('invalid RS dimensions')

def rs_generator(nsym=30):
    g=[1]
    for i in range(nsym):g=F.poly_mul(g,[F.alpha(i),1])
    return g

def rs_syndromes(word,nsym=30):
    return [F.eval(list(reversed(word)),F.alpha(i)) for i in range(nsym)]

def rs_encode(data,nsym=30):
    data=symbols(data,255);_check(nsym,len(data)+nsym)
    gen=list(reversed(rs_generator(nsym)));out=data+[0]*nsym
    for i in range(len(data)):
        factor=out[i]
        for j,g in enumerate(gen):out[i+j]^=F.mul(factor,g)
    return data+out[-nsym:]

def rs_decode(received,nsym=30,erasures=()):
    word=symbols(received,255);_check(nsym,len(word));n=len(word)
    erasures=list(erasures)
    if len(set(erasures))!=len(erasures) or any(not isinstance(i,int) or not 0<=i<n for i in erasures):raise ValueError('invalid erasures')
    fail=lambda:DecodeResult(word[:-nsym],word.copy(),'failed',[])
    if len(erasures)>nsym:return fail()
    synd=rs_syndromes(word,nsym)
    if not any(synd):return DecodeResult(word[:-nsym],word.copy(),'clean',[])
    sequence=synd.copy();gamma=[1]
    for p in erasures:
        x=F.alpha(n-1-p);gamma=F.poly_mul(gamma,[1,x])
        sequence=[sequence[i+1]^F.mul(x,sequence[i]) for i in range(len(sequence)-1)]
    unknown=F.bm(sequence)
    if 2*(len(unknown)-1)+len(erasures)>nsym:return fail()
    locator=F.poly_mul(gamma,unknown)
    positions=[p for p in range(n) if F.eval(locator,F.alpha(-(n-1-p)))==0]
    if len(positions)!=len(locator)-1 or not set(erasures)<=set(positions):return fail()
    m=len(positions)
    try:
        matrix=[[F.alpha((n-1-p)*j) for p in positions] for j in range(m)]
        magnitudes=F.solve(matrix,synd[:m])
    except ValueError:return fail()
    corrected=word.copy()
    for p,v in zip(positions,magnitudes):corrected[p]^=v
    if any(rs_syndromes(corrected,nsym)):return fail()
    changed=[p for p in positions if corrected[p]!=word[p]]
    return DecodeResult(corrected[:-nsym],corrected,'corrected',changed)
