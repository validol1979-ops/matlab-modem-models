"""Integer OM-LSA speech enhancement (reference of rtl/common/omlsa.sv; research_core omlsa).

research_core: x is reflect-padded by n on both sides, STFT (n, hop, sqrt-Hann), the noise power
per bin is the mean |S|^2 of the first nnoise frames, then per frame and bin
  gamma = |S|^2/noise, xi = max(alpha prev + (1-alpha) max(gamma-1, 0), 1e-5),
  v = gamma xi/(1+xi), G = clip(xi/(1+xi) exp(E1(v)/2), .05, 1),
  p = 1/(1 + .25 (1+xi) exp(-v)), G = G^p .05^(1-p), prev = |S G|^2/noise,
and the ISTFT of S*G is cut to [n, n + len(x)).
Here (stft_fixed for the transforms; Q16 for every ratio, R(.) the 12-bit-mantissa reciprocal):
  S = stft_fixed.analyze(pad(x)) (X/n in Q19), P = re^2 + im^2;
  noise = max(divide(sum of the first nnoise P, nnoise), 1) (nearest-even);
  gamma = min(rnd(P*Rn, Zn - 16), GMAX) with Rn, Zn = beam_fixed.reciprocal(noise);
  xi = clip(rnd(A prev + (65536 - A) max(gamma - 65536, 0), 16), 1, GMAX), A = round(alpha 2^16);
  w = 65536 - R(65536 + xi); v = min(rnd(gamma w, 16), GMAX);
  G1 = clip(rnd(w F(v), 12), GMIN, 65536) with F = exp(E1/2) in Q12 from the log table TF;
  t = min(rnd((65536 + xi) E(v), 18), GMAX) with E = exp(-v) in Q16 from the log table TE;
  p = R(65536 + t); L = LN[G1 >> 4]; a = LN05 + rnd(p (L - LN05), 16);
  G = EXPN[min(max(-a, 0) >> 6, 4095)]; out = (rnd(re G, 16), rnd(im G, 16)); prev = min(rnd(rnd(G G, 16) gamma, 16), GMAX);
  y = stft_fixed.synthesize(out)[n : n + len(x)].
The log tables index v (Q16 integer) by its bit length s (1..32) and the 8 bits after the leading
one (v = 0 uses the s = 1 row): TF[s][m], TE[s][m] at v = (256 + m + .5)/256 2^(s-1) / 65536.
R(u) for a Q16 value u >= 65536 (a number >= 1): s = bit length, m = the top 12 bits (2048..4095),
R(u) = rnd(RECIP[m - 2048], s - 17) with RECIP[m] = round(2^27/m) (so R(u) ~ 2^32/u, 1/u in Q16).
round is half up, (v + 2^(s-1)) >> s."""
import math
import fft_fixed as f
import stft_fixed as st
from bpsk_fixed import divide
from beam_fixed import reciprocal
from research_core import expint1

GMAX=(1<<31)-1
GMIN=round(.05*65536)
LN05=round(math.log(.05)*65536)
RECIP=tuple(round((1<<27)/m) for m in range(2048,4096))


def _centre(s,m):return (256+m+.5)/256*2**(s-1)/65536


TF=tuple(min((1<<20)-1,round(math.exp(.5*expint1(_centre(s,m)))*4096)) for s in range(1,33) for m in range(256))
TE=tuple(min(65535,round(math.exp(-_centre(s,m))*65536)) for s in range(1,33) for m in range(256))
# Indices below GMIN >> 4 are never used (G1 >= GMIN); they hold the GMIN value to fit 19 bits.
LN=tuple(round(math.log((max(i,GMIN>>4)+.5)*16/65536)*65536) for i in range(4097))
EXPN=tuple(round(math.exp(-(i+.5)*64/65536)*65536) for i in range(4096))


def log_index(v):
    s=max(1,int(v).bit_length());m=((v<<8)>>(s-1))&255
    return (s-1)*256+m


def recip(u):
    s=u.bit_length();m=u>>(s-12)
    return RECIP[m-2048] if s==17 else f.rnd(RECIP[m-2048],s-17)


def pad(x,n):
    if len(x)<n+1:raise ValueError('OM-LSA needs at least n + 1 samples')
    return x[n:0:-1]+list(x)+x[-2:-n-2:-1]


def enhance(x,n,hop,nnoise,alpha,stats=None):
    x=list(x);L=len(x);xp=pad(x,n)
    frames=st.analyze(xp,n,hop);count=len(frames)//n
    if nnoise<1 or nnoise>count:raise ValueError('nnoise must be 1..frame count')
    power=[re*re+im*im for re,im in frames]
    A=int(round(alpha*65536))
    def clamp(stage,value,low,high=None):
        return max(low,value if high is None else min(high,value)) if stats is None else stats.record_range('omlsa.'+stage,value,low,high)
    noise=[clamp('noise',divide(sum(power[fr*n+k] for fr in range(nnoise)),nnoise),1) for k in range(n)]
    inv=[reciprocal(v) for v in noise]
    prev=[65536]*n;out=[]
    for fr in range(count):
        for k in range(n):
            re,im=frames[fr*n+k];P=power[fr*n+k];rn,zn=inv[k]
            gamma=clamp('gamma',f.rnd(P*rn,zn-16),0,GMAX)
            excess=clamp('excess',gamma-65536,0)
            xi=clamp('xi',f.rnd(A*prev[k]+(65536-A)*excess,16),1,GMAX)
            w=65536-recip(65536+xi)
            v=clamp('v',f.rnd(gamma*w,16),0,GMAX)
            g1=clamp('g1',f.rnd(w*TF[log_index(v)],12),GMIN,65536)
            t=clamp('t',f.rnd((65536+xi)*TE[log_index(v)],18),0,GMAX)
            p=recip(65536+t)
            a=LN05+f.rnd(p*(LN[g1>>4]-LN05),16)
            g=EXPN[clamp('exp_index',(-a)>>6,0,4095)]
            out.append((f.rnd(re*g,16),f.rnd(im*g,16)))
            prev[k]=clamp('prev',f.rnd(f.rnd(g*g,16)*gamma,16),0,GMAX)
    return st.synthesize(out,n,hop,stats=stats,prefix='omlsa_istft')[n:n+L]
