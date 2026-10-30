"""Integer two-branch maximal ratio combining in front of the QPSK_DIFF receiver.

Contract (docs/PORTING_CONTRACT.md): branch gains and noise variances are known
configuration; channel estimation is outside the combiner. Both branches share
one sample clock and delay.

Formats: branch samples and gains Q3.15 (18 bits), variances unsigned integers
1..65535 in any common scale (only their ratio matters), weights Q4.14 (18 bits).
For two branches the variance divisions cancel:
    w_a = conj(g_a)*v_b / D,  w_b = conj(g_b)*v_a / D,  D = |g_a|^2 v_b + |g_b|^2 v_a,
so the hardware needs four divisions by D, done once per configuration.
"""
import numpy as np
from fixed_point import SAMPLE, QFormat, round_shift
from bpsk_fixed import divide
import psk_fixed as p

GAIN=SAMPLE
WEIGHT=QFormat(18,14)
VARIANCE_MAX=65535
# n*2^29/D: Q15 gain over Q30 power gives Q14 weights.
WEIGHT_SHIFT=29


def branch_profile(cfg):
    """Integer receiver profile behind the combiner of a two-branch config."""
    if cfg.get('diversity_branches')!=2:raise ValueError('Two diversity branches required')
    return p.profile_for(dict(cfg,diversity_branches=1))


def quantize_gain(gain):
    return (GAIN.quantize(float(np.real(gain))),GAIN.quantize(float(np.imag(gain))))


def weights(gain_a,gain_b,variance_a=1,variance_b=1):
    """Q14 weights ((re, im), (re, im)); ValueError where the RTL raises error."""
    for value in (*gain_a,*gain_b):GAIN.check(value)
    for value in (variance_a,variance_b):
        if int(value)!=value or not 1<=value<=VARIANCE_MAX:raise ValueError('Variance outside 1..65535')
    # NumPy-целые переполняются до сужения; считаем в Python int.
    gain_a=tuple(int(v) for v in gain_a);gain_b=tuple(int(v) for v in gain_b)
    variance_a=int(variance_a);variance_b=int(variance_b)
    power_a=gain_a[0]**2+gain_a[1]**2;power_b=gain_b[0]**2+gain_b[1]**2
    denominator=power_a*variance_b+power_b*variance_a
    if denominator==0:raise ValueError('Zero diversity gain')
    result=[]
    for (re,im),other in ((gain_a,variance_b),(gain_b,variance_a)):
        w=tuple(divide((x*other)<<WEIGHT_SHIFT,denominator) for x in (re,-im))
        if any(not WEIGHT.minimum<=x<=WEIGHT.maximum for x in w):raise ValueError('Weight outside Q4.14')
        result.append(w)
    return tuple(result)


def combine(branch_a,branch_b,weight_a,weight_b):
    """Per-sample sum of x*w over both branches, rounded to Q3.15 with saturation."""
    if len(branch_a)!=len(branch_b):raise ValueError('Branch lengths differ')
    (ar,ai),(br,bi)=((int(r),int(i)) for r,i in (weight_a,weight_b));out=[]
    for (xr,xi),(yr,yi) in zip(branch_a,branch_b):
        xr,xi,yr,yi=int(xr),int(xi),int(yr),int(yi)
        re=xr*ar-xi*ai+yr*br-yi*bi;im=xr*ai+xi*ar+yr*bi+yi*br
        out.append((SAMPLE.saturate(round_shift(re,14))[0],SAMPLE.saturate(round_shift(im,14))[0]))
    return out


def receive(profile,branch_a,branch_b,gain_a,gain_b,preamble,count,variance_a=1,variance_b=1,**options):
    weight_a,weight_b=weights(gain_a,gain_b,variance_a,variance_b)
    return p.receive(profile,combine(branch_a,branch_b,weight_a,weight_b),preamble,count,**options)
