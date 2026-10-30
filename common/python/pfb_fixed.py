"""Integer polyphase analysis bank (reference of rtl/common/pfb_analysis.sv).

research_core pfb/wola (the same transform): for end = 0, D, 2D, ... < L,
phases[j mod M] += h[j]*x[end-j] for j <= min(end, T-1), Y = fft(phases) *
exp(2j pi k end/M). The rotation is a circular shift of the phases (shift theorem):
Y = fft(q) with q[m] = phases[(m + end) mod M], so no twiddle multiply is needed.
Here x is Q15 (18 bit), taps H = round(h*2^17) (18 bit), M = 2^b (4..256), 1 <= D <= M.
- acc[n] = sum H[j]*x[end-j] exactly; p[n] = sat22(round(acc[n], 13)) is Q19 (4 guard bits);
- Y = fft_fixed.forward(q, 22, 24) = fft(q)/M in Q19, 24 bit.
round is half up, (v + 2^(s-1)) >> s.

OPTIONAL CLAMP STATISTICS: analyze(..., stats=SatTrace()) records every real sat22 input of the
rounded accumulator, at the same place rtl/common/pfb_analysis.sv clamps (state DONE, the phases
latched before the rotation), in the stages 'phase.re' and 'phase.im'. record() returns the model's
own clamped value, so instrumented and plain runs are bit-identical; stats=None never touches
sat_diag. The embedded FFT (fft_fixed.forward) has its own optional counter: analyze(...,
fft_stats=SatStats()) passes it straight to fft_fixed.forward(q, 22, 24), which counts its
symmetric clamps under the stage names 'forward.s<g>.<sum|diff>.<re|im>' (clamp='sym', rail
+-2^23-1). record() clamps exactly as the FFT's own sat does, so instrumented and plain runs
are bit-identical; fft_stats=None never touches sat_diag. The bank's own phase clamp remains
the only edge replayed by rtl/tb/pfb_saturation_check.svh.
"""
import fft_fixed as f

TAP_FRAC=17
LIMIT=(1<<21)-1


def sat22(value):return max(-LIMIT-1,min(LIMIT,value))


def quantize_taps(h):
    taps=[int(round(float(v)*(1<<TAP_FRAC))) for v in h]
    if not taps or any(not -(1<<17)<=v<(1<<17) for v in taps):raise ValueError('Taps must lie in (-1, 1)')
    return taps


def analyze(x,taps,m,d,stats=None,fft_stats=None):
    """One transaction of complex Q15 samples; stats=None keeps the plain path unchanged, a
    sat_diag.SatStats/SatTrace counts the sat22 inputs of the rounded phases (stages
    'phase.re'/'phase.im') and clamps exactly as sat22 does. fft_stats is passed unchanged to
    fft_fixed.forward(q, 22, 24) (existing widths) and counts the embedded FFT's symmetric
    clamps ('forward.s<g>.<sum|diff>.<re|im>'); fft_stats=None keeps that path plain too."""
    bits=m.bit_length()-1
    if m<4 or m!=1<<bits or bits>8 or not 1<=d<=m or not taps or not x:raise ValueError('PFB needs M = 2^b (4..256), 1 <= D <= M, taps and samples')
    out=[]
    for end in range(0,len(x),d):
        acc=[[0,0] for _ in range(m)]
        for j in range(min(end+1,len(taps))):
            re,im=x[end-j];acc[j%m][0]+=taps[j]*re;acc[j%m][1]+=taps[j]*im
        rounded=[(f.rnd(re,13),f.rnd(im,13)) for re,im in acc]
        if stats is None:p=[(sat22(re),sat22(im)) for re,im in rounded]
        # counted where pfb_analysis clamps: sat22 of the rounded acc, before the rotation
        # (the shift is a reordering, so the counts belong to the unrotated phases).
        else:p=[(stats.record('phase.re',re,LIMIT),stats.record('phase.im',im,LIMIT)) for re,im in rounded]
        s=end%m
        out.extend(f.forward([p[(k+s)%m] for k in range(m)],22,24,stats=fft_stats))
    return out
