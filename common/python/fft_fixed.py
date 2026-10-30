"""Integer radix-2 FFT, the bit-exact reference of rtl/common/fft_r2sdf.sv.

Decimation in frequency, natural-order input and output, Q16 twiddles
W = (round(cos(2 pi k/N)*2^16), -round(sin(2 pi k/N)*2^16)), k = j*2^s for butterfly j of
stage s. round(v, s) is round half up, (v + 2^(s-1)) >> s; sat clamps to +-(2^(width-1) - 1).
Widths: input in_width bits (default 18), data width bits (default 20), the RTL parameters
IN_WIDTH and WIDTH (in_width + 1 <= width <= 24).
- forward(x) = FFT(x)/N: every stage halves, the sum branch is sat(round((a+b)*2^16, 17))
  and the difference branch sat(round((a-b)*W, 17)). |X/N| <= max |x|, so with inputs up
  to +-2^(in_width-1) nothing saturates.
- inverse(y) = sum_k y_k exp(+2j pi k t/N) (no 1/N: the exact inverse of forward), as
  conj of the unhalved transform of conj(y): stages use round(., 16) and saturate; it is
  exact while the result and its partial sums fit width bits.
"""
import math
from numbers import Integral

TWIDDLE_FRAC=16
DATA_WIDTH=20


def rnd(value,shift):return (int(value)+(1<<(shift-1)))>>shift


def twiddles(n):
    """Q16 (cos, sin) of 2 pi k/n for k < n/2; the forward twiddle is cos - j sin."""
    return [(round(math.cos(2*math.pi*k/n)*(1<<TWIDDLE_FRAC)),round(math.sin(2*math.pi*k/n)*(1<<TWIDDLE_FRAC))) for k in range(n//2)]


def bitrev(value,bits):return int(format(value,f'0{bits}b')[::-1],2) if bits else 0


LIMIT=(1<<(DATA_WIDTH-1))-1


def sat(value,width=DATA_WIDTH):
    limit=(1<<(width-1))-1;return max(-limit,min(limit,value))


def _input_pairs(x,in_width,width,conjugated=False):
    if (not isinstance(in_width,Integral) or isinstance(in_width,bool)
            or not isinstance(width,Integral) or isinstance(width,bool)
            or not 1<=in_width<width<=24):
        raise ValueError('FFT widths need integer 1 <= in_width < width <= 24')
    low,high=-(1<<(in_width-1)),(1<<(in_width-1))-1
    try:
        len(x)
        rows=[]
        for pair in x:
            if len(pair)!=2:raise ValueError('FFT input must contain complex integer pairs')
            row=[]
            for component,value in enumerate(pair):
                if not isinstance(value,Integral) or isinstance(value,bool):
                    raise ValueError('FFT input components must be integers')
                value=int(value)
                # Only the proven inverse conjugation needs -MAX..-MIN on its imaginary axis.
                lower,upper=(-high,-low) if conjugated and component==1 else (low,high)
                if not lower<=value<=upper:raise ValueError('FFT input exceeds its signed width')
                row.append(value)
            rows.append(tuple(row))
        return rows
    except TypeError as exc:
        raise ValueError('FFT input must be a sequence of complex integer pairs') from exc


def _transform(x,shift,in_width=18,width=DATA_WIDTH,stats=None,tag='forward',*,_conjugated=False):
    data=_input_pairs(x,in_width,width,_conjugated)
    n=len(data);bits=n.bit_length()-1
    if n<2 or n!=1<<bits:raise ValueError('FFT length must be a power of two >= 2')
    limit=(1<<(width-1))-1
    table=twiddles(n)
    for st in range(bits):
        span=n>>(st+1)
        for start in range(0,n,2*span):
            for j in range(span):
                (ar,ai),(br,bi)=data[start+j],data[start+j+span]
                c,si=table[j<<st]
                dr,di=ar-br,ai-bi
                # The sum is multiplied by W = 1 (2^16), the difference by (c - j si).
                raw=(rnd((ar+br)<<TWIDDLE_FRAC,shift),rnd((ai+bi)<<TWIDDLE_FRAC,shift),
                     rnd(dr*c+di*si,shift),rnd(di*c-dr*si,shift))
                if stats is None:sr,si_,dr_,di_=tuple(sat(v,width) for v in raw)
                else:
                    names=(f'{tag}.s{st}.sum.re',f'{tag}.s{st}.sum.im',f'{tag}.s{st}.diff.re',f'{tag}.s{st}.diff.im')
                    sr,si_,dr_,di_=(stats.record(nm,v,limit,clamp='sym') for nm,v in zip(names,raw))
                data[start+j]=(sr,si_);data[start+j+span]=(dr_,di_)
    return [data[bitrev(k,bits)] for k in range(n)]


def forward(x,in_width=18,width=DATA_WIDTH,stats=None):return _transform(x,TWIDDLE_FRAC+1,in_width,width,stats,'forward')


def inverse(y,in_width=18,width=DATA_WIDTH,stats=None):
    # The internal stage name in _transform is 'inverse' via tag; the final conjugation
    # cannot leave the range (stages clamp to +-limit) but is counted as stage
    # 'inverse.conj.im' whenever stats is given, so a future change cannot hide here.
    y=_input_pairs(y,in_width,width)
    limit=(1<<(width-1))-1
    res=[]
    for re,im in _transform([(re,-im) for re,im in y],TWIDDLE_FRAC,in_width,width,stats,'inverse',_conjugated=True):
        v=-im
        res.append((re,v if stats is None else stats.record('inverse.conj.im',v,limit,clamp='sym')))
    return res


def transform(x,inverse_flag=False,in_width=18,width=DATA_WIDTH,stats=None):
    return inverse(x,in_width,width,stats) if inverse_flag else forward(x,in_width,width,stats)
