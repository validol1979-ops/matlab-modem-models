"""BPSK/QPSK/QAM16/QAM64 soft demapper. Complex variance=E|noise|².
Physical QAM table follows project psk_fixed, normalized Es=1 by default.
Labels default Cartesian Gray (QPSK cyclic Gray); label_mode=index preserves
existing modem table-index labels. Output nested symbol x MSB-first bit LLR,
positive0. Maxlog and exact logsumexp; integer distance/division Q8 adapter
uses identical positive0 convention as ldpc_fixed, signed16 saturation.
"""
from fractions import Fraction
from math import sqrt,log,exp,isfinite
QAM16_LEVELS=((3, 3), (1, 3), (3, 1), (1, 1), (-3, 3), (-3, 1), (-1, 3), (-1, 1), (-3, -3), (-1, -3), (-3, -1), (-1, -1), (3, -3), (3, -1), (1, -3), (1, -1))
QAM64_LEVELS=((1, 1), (3, 1), (1, 3), (3, 3), (7, 1), (5, 1), (7, 3), (5, 3), (1, 7), (3, 7), (1, 5), (3, 5), (7, 7), (5, 7), (7, 5), (5, 5), (1, -1), (1, -3), (3, -1), (3, -3), (1, -7), (1, -5), (3, -7), (3, -5), (7, -1), (7, -3), (5, -1), (5, -3), (7, -7), (7, -5), (5, -7), (5, -5), (-1, 1), (-1, 3), (-3, 1), (-3, 3), (-1, 7), (-1, 5), (-3, 7), (-3, 5), (-7, 1), (-7, 3), (-5, 1), (-5, 3), (-7, 7), (-7, 5), (-5, 7), (-5, 5), (-1, -1), (-3, -1), (-1, -3), (-3, -3), (-7, -1), (-5, -1), (-7, -3), (-5, -3), (-1, -7), (-3, -7), (-1, -5), (-3, -5), (-7, -7), (-5, -7), (-7, -5), (-5, -5))

def constellation(order,normalize=True):
    if not isinstance(order,int) or isinstance(order,bool):raise ValueError('integer order required')
    if order==2:return (1+0j,-1+0j)
    if order==4:return tuple(complex(i,q)/(sqrt(2) if normalize else 1) for i,q in ((1,1),(-1,1),(-1,-1),(1,-1)))
    if order not in (16,64):raise ValueError('unsupported modulation')
    scale=sqrt(10 if order==16 else 42) if normalize else 1
    return tuple(complex(i,q)/scale for i,q in (QAM16_LEVELS if order==16 else QAM64_LEVELS))

def bit_labels(order,label_mode='gray'):
    if label_mode not in ('gray','index'):raise ValueError('unknown label mode')
    constellation(order)
    if label_mode=='index' or order==2:return tuple(range(order))
    if order==4:return (0,1,3,2)
    table=QAM16_LEVELS if order==16 else QAM64_LEVELS;side=4 if order==16 else 8;axisbits=side.bit_length()-1
    return tuple((((int(i)+side-1)//2)^(((int(i)+side-1)//2)>>1))<<axisbits|(((int(q)+side-1)//2)^(((int(q)+side-1)//2)>>1)) for i,q in table)

def _logsum(values):
    peak=max(values);return peak+log(sum(exp(v-peak) for v in values))

def llr(symbols,order,noise_variance,method='maxlog',label_mode='gray'):
    points=constellation(order);labels=bit_labels(order,label_mode);width=order.bit_length()-1
    if not isinstance(noise_variance,(int,float)) or isinstance(noise_variance,bool) or not isfinite(noise_variance) or noise_variance<=0 or method not in ('maxlog','exact'):raise ValueError('invalid demapper parameters')
    result=[]
    for sample in symbols:
        sample=complex(sample)
        if not isfinite(sample.real) or not isfinite(sample.imag):raise ValueError('invalid IQ')
        distances=[abs(sample-p)**2/noise_variance for p in points];row=[]
        for b in reversed(range(width)):
            zero=[d for d,label in zip(distances,labels) if not label>>b&1];one=[d for d,label in zip(distances,labels) if label>>b&1]
            row.append(min(one)-min(zero) if method=='maxlog' else _logsum([-d for d in zero])-_logsum([-d for d in one]))
        result.append(row)
    return result

def quantized_demapper(iq,points,labels,noise_variance,frac_bits=8,bits=16):
    """Integer-only maxlog; IQ/points use same integer coordinate scale,
    noise_variance uses its squared units. labels are binary integers0..M-1.
    Round nearest ties away from0, clip signedbits; metric distances stay wide.
    """
    points=list(points);labels=list(labels);order=len(points);width=order.bit_length()-1
    if order<2 or order&(order-1) or any(not isinstance(v,int) or isinstance(v,bool) for v in labels) or sorted(labels)!=list(range(order)):raise ValueError('invalid constellation/labels')
    if not isinstance(noise_variance,int) or isinstance(noise_variance,bool) or noise_variance<=0 or not isinstance(bits,int) or isinstance(bits,bool) or not 2<=bits<=32 or not isinstance(frac_bits,int) or isinstance(frac_bits,bool) or not 0<=frac_bits<bits:raise ValueError('invalid fixed parameters')
    def pair(v):
        if len(v)!=2 or any(not isinstance(x,int) or isinstance(x,bool) for x in v):raise ValueError('integer IQ required')
        return v
    points=[pair(v) for v in points];result=[]
    for sample in iq:
        i,q=pair(sample);d=[(i-x)**2+(q-y)**2 for x,y in points];row=[]
        for b in reversed(range(width)):
            delta=min(v for v,l in zip(d,labels) if l>>b&1)-min(v for v,l in zip(d,labels) if not l>>b&1)
            numerator=delta<<frac_bits;value=(abs(numerator)+noise_variance//2)//noise_variance
            if numerator<0:value=-value
            row.append(max(-(1<<(bits-1)),min((1<<(bits-1))-1,value)))
        result.append(row)
    return result

def q8_adapter(values):
    """Flat floating LLRs to ldpc_fixed signed16 Q8; positive0, nearest/even."""
    a=list(values)
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not isfinite(v) for v in a):raise ValueError('invalid LLR')
    return [max(-32768,min(32767,round(Fraction(v)*256))) for v in a]
