"""Source CCSDS convolutional Turbo rate1/6, blocks1784/3568/7136/8920.

Source16state recursive trellis; exactsource interleaver; independent4bit
zero-state termination. Serial [firsta0,a1,a2,a3,seconda1,a3], includingtails.
Positive0 LLR. True full-frame MaxLogMAP (not hard Viterbi), initial/final0,
extrinsic exchange, optional sign-change selfcorrection, explicit iterations.
Fixed Qfrac_bits inputs, integer doubled branchmetrics, normalized/clipped
state metrics and clipped extrinsic; posterior half-difference is integer-exact.
No streaming latency/Fmax, punctured rates or full CCSDS standards claim.
"""
from fractions import Fraction
from dataclasses import dataclass
from functools import lru_cache
from math import isfinite
BLOCKS=(1784,3568,7136,8920)

def constituent_transition(state,bit):
    if not isinstance(state,int) or isinstance(state,bool) or not 0<=state<16 or not isinstance(bit,int) or isinstance(bit,bool) or bit not in (0,1):raise ValueError('invalid trellis edge')
    f=bit^(state>>1&1)^(state&1);s3=state>>3&1;s2=state>>2&1;s1=state>>1&1;s0=state&1
    return (f<<3)|(state>>1),(bit,f^s3^s1^s0,f^s2^s0,f^s3^s2^s1^s0)
TRELLIS=tuple(tuple(constituent_transition(s,b) for b in (0,1)) for s in range(16))

@lru_cache(maxsize=4)
def turbo_interleaver(n):
    if not isinstance(n,int) or isinstance(n,bool) or n not in BLOCKS:raise ValueError('unsupported CCSDS block')
    k=n//8;out=[]
    for s in range(n):
        g=s//(2*k);j=(s//2)%k;t=(1-g)%4;p=(31,37,43,47)[t]
        out.append((t<<1)+(((p*j+(21 if s%2 else 0))%k)<<3)+(0 if s%2 else 1))
    return tuple(out)

def _bits(bits):
    a=list(bits)
    if any(not isinstance(v,int) or isinstance(v,bool) or v not in (0,1) for v in a):raise ValueError('invalid bits')
    return a

def constituent_encode(bits):
    a=_bits(bits);state=0;out=[]
    for b in a:
        state,row=TRELLIS[state][b];out.append(row)
    for _ in range(4):
        b=(state>>1&1)^(state&1);state,row=TRELLIS[state][b];out.append(row)
    assert state==0
    return out

def turbo_encode(bits):
    a=_bits(bits);permutation=turbo_interleaver(len(a));first=constituent_encode(a);second=constituent_encode([a[p] for p in permutation])
    return [v for x,y in zip(first,second) for v in (x[0],x[1],x[2],x[3],y[1],y[3])]

@dataclass
class BCJRResult:
    posterior:list
    extrinsic:list
    trace:dict

@dataclass
class TurboResult:
    bits:list
    iterations:int
    trace:list
    valid:bool

def _soft(values):
    a=list(values)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) for v in a):raise ValueError('invalid LLR')
    return a

def maxlog_map(systematic,parity,apriori=None,quantized=False,metric_bits=24,extrinsic_bits=12):
    """Constituent SISO; private-size toy frames useful for independent ML oracle.
    quantized=True expects integers already in common Q units.
    """
    systematic=_soft(systematic);parity=[_soft(row) for row in parity];length=len(systematic)
    apriori=[0]*length if apriori is None else _soft(apriori)
    if not length or len(parity)!=length or any(len(row)!=3 for row in parity) or len(apriori)!=length:raise ValueError('SISO dimensions')
    if quantized and any(not isinstance(v,int) for v in systematic+apriori+[v for row in parity for v in row]):raise ValueError('integer metrics required')
    if not isinstance(metric_bits,int) or not 4<=metric_bits<=48 or not isinstance(extrinsic_bits,int) or not 3<=extrinsic_bits<=32:raise ValueError('invalid metric widths')
    clips=0;bound=(1<<(extrinsic_bits-1))-1 if quantized else 1e6;metric_low=-(1<<(metric_bits-1))
    def normalize(row):
        nonlocal clips
        offset=max(v for v in row if v is not None);result=[]
        for v in row:
            if v is None:result.append(None);continue
            v-=offset
            if quantized and v<metric_low:v=metric_low;clips+=1
            result.append(v)
        return result
    gamma=[]
    for sy,pa,ap in zip(systematic,parity,apriori):
        gamma.append(tuple(tuple((1-2*b)*(sy+ap)+sum((1-2*c)*l for c,l in zip(TRELLIS[s][b][1][1:],pa)) for b in (0,1)) for s in range(16)))
    alpha=[[None]*16];alpha[0][0]=0
    for t in range(length):
        row=[None]*16
        for s,prior in enumerate(alpha[-1]):
            if prior is None:continue
            for b in (0,1):
                nxt=TRELLIS[s][b][0];v=prior+gamma[t][s][b]
                if row[nxt] is None or v>row[nxt]:row[nxt]=v
        alpha.append(normalize(row))
    beta=[None]*16;beta[0]=0;posterior=[0]*length;beta_trace={};ranges=[]
    for t in range(length-1,-1,-1):
        best=[None,None];previous=[None]*16
        for s in range(16):
            for b in (0,1):
                nxt=TRELLIS[s][b][0]
                if beta[nxt] is None:continue
                tail=gamma[t][s][b]+beta[nxt]
                if previous[s] is None or tail>previous[s]:previous[s]=tail
                if alpha[t][s] is not None:
                    value=alpha[t][s]+tail
                    if best[b] is None or value>best[b]:best[b]=value
        if best[0] is None:posterior[t]=-bound
        elif best[1] is None:posterior[t]=bound
        else:posterior[t]=(best[0]-best[1])//2 if quantized else (best[0]-best[1])/2
        beta=normalize(previous)
        if t<8:beta_trace[t]=beta.copy()
        ranges.extend(v for v in beta if v is not None)
    extrinsic=[]
    for post,sy,ap in zip(posterior,systematic,apriori):
        raw=post-sy-ap;clipped=max(-bound,min(bound,raw));clips+=int(raw!=clipped);extrinsic.append(clipped)
    return BCJRResult(posterior,extrinsic,{'alpha_first8':alpha[:8],'beta_first8':[beta_trace[i] for i in sorted(beta_trace)],'metric_min':min(ranges),'metric_max':max(ranges),'clips':clips})

def turbo_decode(llrs,iterations=4,quant_bits=None,frac_bits=3,self_correct=False,early_stop=False,metric_bits=24,extrinsic_bits=12):
    a=_soft(llrs)
    if len(a)%6:raise ValueError('rate1/6 frame length')
    n=len(a)//6-4;permutation=turbo_interleaver(n)
    if not isinstance(iterations,int) or isinstance(iterations,bool) or not 1<=iterations<=32:raise ValueError('invalid iterations')
    fixed=quant_bits is not None
    if fixed:
        if not isinstance(quant_bits,int) or isinstance(quant_bits,bool) or not 2<=quant_bits<=24 or not isinstance(frac_bits,int) or isinstance(frac_bits,bool) or not 0<=frac_bits<quant_bits:raise ValueError('invalid quantizer')
        a=[max(-(1<<(quant_bits-1)),min((1<<(quant_bits-1))-1,round(Fraction(v)*(1<<frac_bits)))) for v in a]
    rows=[a[i:i+6] for i in range(0,len(a),6)];sys0=[row[0] for row in rows];sys1=[sys0[p] for p in permutation]+[0]*4
    parity0=[row[1:4] for row in rows];parity1=[(row[4],0,row[5]) for row in rows]
    prior0=[0]*(n+4);previous0=[0]*n;previous1=[0]*n;trace=[];last=None;valid=False
    for iteration in range(iterations):
        first=maxlog_map(sys0,parity0,prior0,fixed,metric_bits,extrinsic_bits);ext0=first.extrinsic[:n]
        if self_correct:ext0=[0 if x*y<0 else x for x,y in zip(ext0,previous0)]
        previous0=ext0.copy();prior1=[ext0[p] for p in permutation]+[0]*4
        second=maxlog_map(sys1,parity1,prior1,fixed,metric_bits,extrinsic_bits);ext1=second.extrinsic[:n]
        if self_correct:ext1=[0 if x*y<0 else x for x,y in zip(ext1,previous1)]
        previous1=ext1.copy();prior0=[0]*(n+4);bits=[0]*n
        for i,p in enumerate(permutation):prior0[p]=ext1[i];bits[p]=int(second.posterior[i]<0)
        for name,result,ext in (('first',first,ext0),('second',second,ext1)):
            trace.append({'iteration':iteration+1,'constituent':name,'extrinsic_first8':ext[:8],**result.trace})
        # A posterior hard word may be stable without being transmitted correctly.
        # valid only denotes re-encoded hard channel agreement; not a CRC.
        valid=all((v<0)==bool(b) for v,b in zip(a,turbo_encode(bits)))
        if early_stop and last==bits and valid:break
        last=bits.copy()
    return TurboResult(bits,iteration+1,trace,valid)
