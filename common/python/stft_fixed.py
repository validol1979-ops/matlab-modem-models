"""Integer STFT/ISTFT over fft_fixed (reference of the stft_rtl / istft_rtl RTL).

research_core: stft = frames of n samples every hop with the sqrt-Hann window
w[k] = sqrt(0.5 - 0.5 cos(2 pi (k + 0.5)/n)) (non-zero edges), spectra fft(x*w);
istft = overlap-add of ifft(s)*w divided by sum w^2 (normalised overlap-add).
Here n = 2^b (4..256), hop = n/R with R = n/hop in (1, 2, 4), samples Q15 integers (18 bit).
GUARD = 4 extra fraction bits keep the window edges accurate (the normalisation divides by
w^2, which is 6e-4 at the first sample of a 64-point window).
- STFT: z_k = round(x_k*W_k, 17 - GUARD) with W = round(w*2^17) (18 bit), so z is Q19 in
  22 bits; X = fft_fixed.forward(z, 22, 24) = FFT(x*w)/n in Q19 (24 bit, |X| < 2^21.5).
  The frame count is 1 + (len - n)//hop.
- ISTFT: Y is clamped to +-(2^22-1) (never active for STFT output), u =
  fft_fixed.inverse(Y, 23, 24) (= the windowed frame for Y = X/n), acc[t] += u_k*W_k
  exactly, y_t = sat18(round(acc_t*RECIP[p][mask], 17 + GUARD + F)) where p = t mod hop and
  bit m of mask says frame floor(t/hop) - m exists (0 <= frame < F); RECIP =
  round(2^F / sum of covered w^2) in 24 unsigned bits, F = recip_frac(n, hop).
  Output length (F-1)*hop + n.
round is half up, (v + 2^(s-1)) >> s."""
import math
import fft_fixed as f

WINDOW_FRAC=17
GUARD=4
LIMIT=(1<<17)-1
SPECTRUM_LIMIT=(1<<22)-1


def sat18(value):return max(-LIMIT-1,min(LIMIT,value))


def check(n,hop):
    bits=n.bit_length()-1
    # n = 1024 is refused: its window edge (0.0015) makes the edge samples meaningless.
    if n<4 or n!=1<<bits or bits>8 or hop<1 or n%hop or n//hop not in (1,2,4):raise ValueError('STFT needs n = 2^b (4..256) and n/hop in 1, 2, 4')
    return n//hop


def window(n):
    """Q17 sqrt-Hann (the largest value is below 1, so 18 signed bits hold it)."""
    return [round(math.sqrt(.5-.5*math.cos(2*math.pi*(k+.5)/n))*(1<<WINDOW_FRAC)) for k in range(n)]


def _norms(n,hop):
    ratio=check(n,hop);w=[math.sqrt(.5-.5*math.cos(2*math.pi*(k+.5)/n)) for k in range(n)]
    return ratio,[[sum(w[p+m*hop]**2 for m in range(ratio) if mask>>m&1) for mask in range(1<<ratio)] for p in range(hop)]


def recip_frac(n,hop):
    """Fraction bits of RECIP so that the largest reciprocal fits 24 unsigned bits."""
    _,norms=_norms(n,hop);largest=max(1/v for row in norms for v in row[1:])
    return 23-math.ceil(math.log2(largest+1))


def reciprocals(n,hop):
    """RECIP[p][mask] = round(2^F / sum_{m in mask} w(p + m*hop)^2), mask != 0 (row[0] unused)."""
    ratio,norms=_norms(n,hop);frac=recip_frac(n,hop)
    table=[[0]+[round((1<<frac)/norm) for norm in row[1:]] for row in norms]
    assert all(v<(1<<24) for row in table for v in row)
    return table


def analyze(x,n,hop):
    check(n,hop)
    if len(x)<n:raise ValueError('STFT input shorter than one frame')
    W=window(n);count=1+(len(x)-n)//hop;out=[]
    for frame in range(count):
        z=[(f.rnd(re*W[k],WINDOW_FRAC-GUARD),f.rnd(im*W[k],WINDOW_FRAC-GUARD)) for k,(re,im) in enumerate(x[frame*hop:frame*hop+n])]
        out.extend(f.forward(z,22,24))
    return out


def synthesize(spectra,n,hop,stats=None,prefix='stft'):
    ratio=check(n,hop)
    if len(spectra)%n or not spectra:raise ValueError('ISTFT input must be whole frames')
    W=window(n);R=reciprocals(n,hop);shift=WINDOW_FRAC+GUARD+recip_frac(n,hop)
    frames=len(spectra)//n;size=(frames-1)*hop+n
    def clamp(stage,value,limit,symmetric=False):
        if stats is not None:return stats.record(prefix+'.'+stage,value,limit,'sym' if symmetric else 'asym')
        return max(-limit if symmetric else -limit-1,min(limit,value))
    acc=[[0,0] for _ in range(size)]
    for frame in range(frames):
        u=f.inverse([(clamp('spectrum.re',re,SPECTRUM_LIMIT,True),clamp('spectrum.im',im,SPECTRUM_LIMIT,True)) for re,im in spectra[frame*n:(frame+1)*n]],23,24)
        for k,(re,im) in enumerate(u):
            acc[frame*hop+k][0]+=re*W[k];acc[frame*hop+k][1]+=im*W[k]
    out=[]
    for t,(re,im) in enumerate(acc):
        mask=sum(1<<m for m in range(ratio) if 0<=t//hop-m<frames)
        r=R[t%hop][mask]
        out.append((clamp('output.re',f.rnd(re*r,shift),LIMIT),clamp('output.im',f.rnd(im*r,shift),LIMIT)))
    return out
