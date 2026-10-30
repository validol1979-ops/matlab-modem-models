"""Source DVB PLS128-label/64-bit code, fixed scramble, FHT32 soft ML.

LSB label bits dat0..dat6; transmitted index0 is leftmost source constant bit.
This alphabet does not assert MODCOD legality/full DVB-S2 conformance. Positive
LLR0; ties smallest label. Quantization clips input; FHT/score has6guard bits
(mathematical wide integers here). Frame-local phase starts even at symbol0.
"""
from fractions import Fraction
from math import isfinite,sqrt
SCRAMBLE=tuple(int(b) for b in '0111000110011101100000111100100101010011010000100010110111111010')

def pls_encode(label):
    if not isinstance(label,int) or isinstance(label,bool) or not 0<=label<128:raise ValueError('invalid label')
    bits=[]
    for i in range(32):
        rm=(label&1)
        for j in range(1,6):rm^=(label>>j&1)*(i>>(5-j)&1)
        bits.extend((rm,rm^(label>>6)))
    return [b^s for b,s in zip(bits,SCRAMBLE)]

def hadamard32(values):
    a=list(values)
    if len(a)!=32:raise ValueError('FHT32 needs32 inputs')
    step=1
    while step<32:
        for i in range(0,32,2*step):
            for j in range(step):x,y=a[i+j],a[i+j+step];a[i+j],a[i+j+step]=x+y,x-y
        step*=2
    return a

def pls_decode(llrs,quant_bits=None,scale=8):
    a=list(llrs)
    if len(a)!=64 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) for v in a):raise ValueError('need64finiteLLRs')
    if quant_bits is not None:
        if not isinstance(quant_bits,int) or isinstance(quant_bits,bool) or not 2<=quant_bits<=32 or not isinstance(scale,(int,float)) or not isfinite(scale) or scale<=0:raise ValueError('invalid quantizer')
        a=[max(-(1<<(quant_bits-1)),min((1<<(quant_bits-1))-1,round(Fraction(v)*Fraction(scale)))) for v in a]
    a=[v*(1-2*s) for v,s in zip(a,SCRAMBLE)];options=[]
    for b6 in (0,1):
        w=hadamard32([a[2*i]+(1-2*b6)*a[2*i+1] for i in range(32)])
        for index,metric in enumerate(w):
            label=(b6<<6)|int(metric<0)|sum(((index>>(5-j))&1)<<j for j in range(1,6))
            options.append((-abs(metric),label))
    return min(options)[1]

def _bits(bits):
    a=list(bits)
    if any(not isinstance(v,int) or isinstance(v,bool) or v not in (0,1) for v in a):raise ValueError('invalid bits')
    return a

def pls_map(bits):
    return [(1-2*b)*complex(1 if i%2==0 else -1,1)/sqrt(2) for i,b in enumerate(_bits(bits))]

def pls_demod(symbols,noise_variance=1.0):
    if not isinstance(noise_variance,(int,float)) or not isfinite(noise_variance) or noise_variance<=0:raise ValueError('invalid complex noise variance')
    a=list(symbols)
    if any(not isfinite(complex(v).real) or not isfinite(complex(v).imag) for v in a):raise ValueError('invalid IQ')
    return [4*(complex(v).imag+(complex(v).real if i%2==0 else -complex(v).real))/(sqrt(2)*noise_variance) for i,v in enumerate(a)]

def pls_map_fixed(bits,amplitude=32767):
    if not isinstance(amplitude,int) or isinstance(amplitude,bool) or amplitude<=0:raise ValueError('invalid amplitude')
    return [((1-2*b)*amplitude*(1 if i%2==0 else -1),(1-2*b)*amplitude) for i,b in enumerate(_bits(bits))]

def pls_demod_fixed(iq):
    """Source projection sum/difference, integer rawLLR, no saturation or N0 scaling."""
    a=list(iq)
    if any(len(v)!=2 or any(not isinstance(x,int) or isinstance(x,bool) for x in v) for v in a):raise ValueError('invalid integer IQ')
    return [q+(i if n%2==0 else -i) for n,(i,q) in enumerate(a)]
