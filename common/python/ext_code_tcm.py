"""Source4D-TCM-8PSK icode0:8 payload bits ->4 natural8PSK phases.

Exact differential accumulator on positions8,5,1, source64-state rate3/4
convolution on positions3,2,1, map_2_0. Reset initialstates0, unconstrained final
state; no invented zero tail. Float Euclidean and Q12 integer-square Viterbi;
per-stage normalization, stable smallest predecessor/word ties. No othericode.
"""
from fractions import Fraction
from math import cos,sin,pi,isfinite
from dataclasses import dataclass
POINTS=tuple(complex(cos(i*pi/4),sin(i*pi/4)) for i in range(8))
@dataclass
class TCMResult:
    payloads:list
    differential_words:list
    metric_trace:list
    final_state:int

def tcm_transition(state,x):
    if not isinstance(state,int) or isinstance(state,bool) or not 0<=state<64 or not isinstance(x,int) or isinstance(x,bool) or not 0<=x<8:raise ValueError('invalid trellis edge')
    return (((state&1)<<5)|((state>>2)<<1)|(((state>>1)^state)&1)) ^ (0x14 if x&4 else 0) ^ (0x0a if x&2 else 0) ^ (3 if x&1 else 0)

def tcm_map_indices(x):
    if not isinstance(x,int) or isinstance(x,bool) or not 0<=x<512:raise ValueError('invalid coded word')
    v=((x>>8&1)<<2)|((x>>5&1)<<1)|(x>>1&1)
    a=((x>>7&1)<<2)|((x>>3&1)<<1);b=((x>>6&1)<<2)|((x>>2&1)<<1);c=((x>>4&1)<<2)|((x&1)<<1)
    return v,(v+a)%8,(v+b)%8,(v+a+b+c)%8

def _set_v(x,v):
    return (x&~((1<<8)|(1<<5)|(1<<1)))|((v>>2&1)<<8)|((v>>1&1)<<5)|((v&1)<<1)

def tcm_encode(payloads,fixed=False,frac_bits=12):
    payloads=list(payloads)
    if any(not isinstance(v,int) or isinstance(v,bool) or not 0<=v<256 for v in payloads):raise ValueError('payload must be8bit integer')
    if not isinstance(frac_bits,int) or isinstance(frac_bits,bool) or not 1<=frac_bits<=24:raise ValueError('invalid coordinateQ')
    state=diff=0;out=[]
    for value in payloads:
        x=value<<1;v=((x>>8&1)<<2)|((x>>5&1)<<1)|(x>>1&1);diff=(diff+v)%8;x=_set_v(x,diff)
        coded=x|(state&1);state=tcm_transition(state,(x>>1)&7)
        group=[POINTS[k] for k in tcm_map_indices(coded)]
        out.append([(round(p.real*(1<<frac_bits)),round(p.imag*(1<<frac_bits))) for p in group] if fixed else group)
    return out

def tcm_decode(groups,fixed=False,frac_bits=12):
    groups=[list(g) for g in groups]
    if not groups or any(len(g)!=4 for g in groups) or not isinstance(frac_bits,int) or isinstance(frac_bits,bool) or not 1<=frac_bits<=24:raise ValueError('invalid4symbol frame')
    scale=1<<frac_bits;points=[(round(v.real*scale),round(v.imag*scale)) for v in POINTS] if fixed else POINTS
    samples=[]
    for group in groups:
        row=[]
        for value in group:
            if fixed and isinstance(value,(tuple,list)):
                if len(value)!=2 or any(not isinstance(x,int) or isinstance(x,bool) for x in value):raise ValueError('invalid integerIQ')
                row.append(tuple(value));continue
            z=complex(value)
            if not isfinite(z.real) or not isfinite(z.imag):raise ValueError('invalid IQ')
            row.append((round(Fraction(z.real)*scale),round(Fraction(z.imag)*scale)) if fixed else z)
        samples.append(row)
    maps=[tcm_map_indices(x) for x in range(512)];metrics=[None]*64;metrics[0]=0;survivors=[];trace=[]
    for group in samples:
        distance=[]
        for sample in group:
            distance.append([((sample[0]-p[0])**2+(sample[1]-p[1])**2) if fixed else abs(sample-p)**2 for p in points])
        costs=[[sum(distance[i][maps[(word<<1)|parity][i]] for i in range(4)) for word in range(256)] for parity in (0,1)]
        best=[[min((costs[p][word],word) for word in range(x,256,8)) for x in range(8)] for p in (0,1)]
        new=[None]*64;paths=[None]*64
        for state,metric in enumerate(metrics):
            if metric is None:continue
            for x in range(8):
                branch,word=best[state&1][x];nxt=tcm_transition(state,x);candidate=(metric+branch,state,word)
                if paths[nxt] is None or candidate<paths[nxt]:paths[nxt]=candidate;new[nxt]=candidate[0]
        offset=min(v for v in new if v is not None);trace.append((offset,max(v for v in new if v is not None)))
        metrics=[None if v is None else v-offset for v in new];survivors.append(paths)
    final=min((v,s) for s,v in enumerate(metrics) if v is not None)[1];state=final;words=[]
    for paths in reversed(survivors):_,state,word=paths[state];words.append(word)
    words.reverse();payloads=[];previous=0
    for word in words:
        x=word<<1;v=((x>>8&1)<<2)|((x>>5&1)<<1)|(x>>1&1);payloads.append(_set_v(x,(v-previous)%8)>>1);previous=v
    return TCMResult(payloads,words,trace,final)
