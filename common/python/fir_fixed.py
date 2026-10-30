"""Integer FIR with runtime complex taps (reference of rtl/common/fir_runtime.sv).

research_core fir: y = np.convolve(x, a), length L + T - 1 (full convolution, x[t] = 0
outside 0..L-1). Here x is Q15 (18 bit) and the taps A = round(a*2^17) are complex Q17
(18 bit each, |re|, |im| < 1). acc = sum_j A[j]*x[n-j] exactly (complex), y[n] =
sat18(round(acc, 17)) in Q15. wsinc (the windowed-sinc design) is a coefficient generator:
its taps are computed here (wsinc_taps) and loaded into the FIR, not built in hardware.
round is half up, (v + 2^(s-1)) >> s."""
import math
import fft_fixed as f

TAP_FRAC=17
LIMIT=(1<<17)-1


def sat18(value):return max(-LIMIT-1,min(LIMIT,value))


def quantize_taps(a):
    taps=[(int(round(complex(v).real*(1<<TAP_FRAC))),int(round(complex(v).imag*(1<<TAP_FRAC)))) for v in a]
    if not taps or any(not -(1<<17)<=c<(1<<17) for t in taps for c in t):raise ValueError('Taps must lie in (-1, 1)')
    return taps


def wsinc_taps(size,cutoff):
    """research_core wsinc: Hamming-windowed sinc normalised to unit DC gain (floats)."""
    if size<2 or not 0<cutoff<.5:raise ValueError('wsinc needs size >= 2 and 0 < cutoff < 0.5')
    t=[k-(size-1)/2 for k in range(size)]
    sinc=lambda v:1.0 if v==0 else math.sin(math.pi*v)/(math.pi*v)
    y=[2*cutoff*sinc(2*cutoff*v)*(.54-.46*math.cos(2*math.pi*k/(size-1))) for k,v in enumerate(t)]
    total=sum(y);return [v/total for v in y]


def filter(x,taps,stats=None):
    """stats: optional sat_diag.SatStats; counts pre-clamp events per component output
    (stages 'output.re', 'output.im'). Outputs are identical with or without stats."""
    if not x or not taps:raise ValueError('FIR needs samples and taps')
    # NumPy-целые переполняются до сужения; считаем в Python int.
    x=[(int(r),int(i)) for r,i in x];taps=[(int(r),int(i)) for r,i in taps]
    out=[]
    for n in range(len(x)+len(taps)-1):
        re=im=0
        for j,(hr,hi) in enumerate(taps):
            if 0<=n-j<len(x):
                xr,xi=x[n-j];re+=hr*xr-hi*xi;im+=hr*xi+hi*xr
        re=f.rnd(re,TAP_FRAC);im=f.rnd(im,TAP_FRAC)
        if stats is None:out.append((sat18(re),sat18(im)))
        else:out.append((stats.record('output.re',re,LIMIT),stats.record('output.im',im,LIMIT)))
    return out
