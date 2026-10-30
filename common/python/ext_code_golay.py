"""Source extended Golay24(24,12,8), low12 systematic data/high12 parity.

The source cB_TAB realizes g=0xC75 with its matrix bit permutation. Hard decoder
corrects <=3 errors. Chase-II16 enumerates flips of4 least reliable positions,
then bounded hard decoding, correlation metric, smallest codeword ties. It is
not universal ML; failures preserve hard input; beyond3 may miscorrect.
"""
from fractions import Fraction
from dataclasses import dataclass,field
from functools import lru_cache
from itertools import combinations
from math import isfinite
B=(0x7ff,0xee2,0xdc5,0xb8b,0xf16,0xe2d,0xc5b,0x8b7,0x96e,0xadc,0xdb8,0xb71)

@dataclass
class GolayResult:
    data:int
    codeword:int
    status:str
    corrected_positions:list
    candidates:list=field(default_factory=list)
    metric:float=0

def _integer(value,bits):
    if not isinstance(value,int) or isinstance(value,bool) or not 0<=value<1<<bits:raise ValueError('invalid integer word')

def golay_encode(data):
    _integer(data,12)
    parity=sum(((data&row).bit_count()&1)<<(11-i) for i,row in enumerate(B))
    return (parity<<12)|data

def golay_syndrome(word):
    _integer(word,24)
    return sum((((word>>12&row).bit_count()^(word>>(11-i)))&1)<<(11-i) for i,row in enumerate(B))

@lru_cache(maxsize=1)
def _syndromes():
    result={0:0}
    for weight in range(1,4):
        for positions in combinations(range(24),weight):
            mask=sum(1<<p for p in positions);syndrome=golay_syndrome(mask)
            if syndrome in result:raise AssertionError('nonunique Golay syndrome')
            result[syndrome]=mask
    return result

def golay_decode(word):
    _integer(word,24);mask=_syndromes().get(golay_syndrome(word))
    if mask is None:return GolayResult(word&4095,word,'failed',[])
    codeword=word^mask
    return GolayResult(codeword&4095,codeword,'corrected' if mask else 'clean',[i for i in range(24) if mask>>i&1])

def golay_chase(llrs,quant_bits=None,scale=8):
    values=list(llrs)
    if len(values)!=24 or any(not isinstance(v,(int,float)) or not isfinite(v) for v in values):raise ValueError('need24 finite LLRs')
    if quant_bits is not None:
        if not isinstance(quant_bits,int) or isinstance(quant_bits,bool) or not 2<=quant_bits<=24 or not isfinite(scale) or scale<=0:raise ValueError('invalid quantizer')
        values=[max(-(1<<(quant_bits-1)),min((1<<(quant_bits-1))-1,round(Fraction(v)*Fraction(scale)))) for v in values]
    hard=sum(int(v<0)<<i for i,v in enumerate(values))
    least=sorted(range(24),key=lambda i:(abs(values[i]),i))[:4];candidates=set()
    for pattern in range(16):
        trial=hard^sum(((pattern>>j)&1)<<p for j,p in enumerate(least))
        result=golay_decode(trial)
        if result.status!='failed':candidates.add(result.codeword)
    if not candidates:return GolayResult(hard&4095,hard,'failed',[])
    metric=lambda word:sum((1-2*(word>>i&1))*v for i,v in enumerate(values))
    chosen=min(candidates,key=lambda word:(-metric(word),word))
    return GolayResult(chosen&4095,chosen,'clean' if chosen==hard else 'corrected',[i for i in range(24) if (chosen^hard)>>i&1],sorted(candidates),metric(chosen))
