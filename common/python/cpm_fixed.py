"""Integer MSK/GMSK modem: phase-accumulator transmitter and frequency discriminator.

Transmitter: data d in {-1,+1} repeated per sample (sps 8), for GMSK filtered by the
Gaussian taps G (Q16, sum exactly 2^16, 4*sps+1 taps); the phase advances by f*2^11
turns*2^-32 per sample (a quarter turn per symbol), cos/sin from the pilot table (Q17)
rounded to Q15.

Receiver (modem_core.receive_cpm with a streaming acquisition): the reference is the
integer transmitter output for the preamble. Coarse delay: the integer lag L in 0..16
maximizing |sum x[n+L]*conj(r[n])|^2 over COARSE samples. Fine delay: the candidates
L-0.75..L+0.75 in quarter samples (cubic interpolation) over FINE samples, in four
blocks; the block sums of the winner give the frequency (unwrapped block phases, least
squares). The discriminator sums wrap(angle(x_n*conj(x_{n-1})) - slope) over each
symbol (after 2*sps samples of Gaussian delay for GMSK); the decision is the sign.
The first increment of a frame is zero (the floating model uses the absolute phase of
the first sample there, inside the preamble).
"""
import math
import numpy as np
from fixed_point import round_shift
from bpsk_fixed import COS, SPS, TRAIN, atan2, divide, interp, rotate, sat, wrap
from modem_core import gaussian_taps

USED=(TRAIN-4)*SPS
LAGS=18            # integer lags -1..16
# Sampling offset after acquisition: the increment of sample n spans n-1..n, so the
# symbol window is centred half a sample later (the floating grid fit lands there at low SNR).
OFFSET=1<<15


def gaussian_q16(bt=0.3):
    """Gaussian taps in Q16 with the centre tap absorbing the rounding: sum is 2^16."""
    g=[round(float(x)*65536) for x in gaussian_taps(SPS,bt)]
    g[len(g)//2]+=65536-sum(g)
    return tuple(g)


GAUSS=gaussian_q16()


def frequencies(bits,gmsk):
    """Per-sample frequency in Q16 (+-2^16 for MSK); GMSK is the full convolution."""
    f=[(1 if b else -1)*65536 for b in bits for _ in range(SPS)]
    if not gmsk:return f
    d=[1 if b else -1 for b in bits for _ in range(SPS)];out=[]
    for n in range(len(d)+len(GAUSS)-1):
        out.append(sum(GAUSS[k]*d[n-k] for k in range(len(GAUSS)) if 0<=n-k<len(d)))
    return out


def transmit(bits,gmsk):
    if any(int(b)!=b or b not in (0,1) for b in bits):raise ValueError('Binary symbols required')
    phase=0;out=[]
    for f in frequencies([int(b) for b in bits],gmsk):
        phase=wrap(phase+f*2048)
        index=(phase>>20)&4095
        out.append((round_shift(COS[index],2),round_shift(COS[(index-1024)&4095],2)))
    return out


CORR=1024          # correlation and frequency window (samples)
HALF=1<<15         # window centring offset (half a sample), see receive


def increments(wave,count,delay):
    """wrap(angle(x_n*conj(x_{n-1}))) at positions n+delay, n = 0..count-1; the first is 0."""
    out=[];previous=None
    for n in range(count):
        x=interp(wave,(n<<16)+delay)
        if previous is None:out.append(0)
        else:out.append(atan2(x[1]*previous[0]-x[0]*previous[1],x[0]*previous[0]+x[1]*previous[1]))
        previous=x
    return out


BLOCKS=8           # frequency fit: 8 blocks of CORR/8 samples


def acquire(wave,reference,reference_frequency,gmsk):
    """Pass 1: discriminator at integer positions over the preamble; corr[L] = sum
    inc[n+L]*sign(f_ref[n]) (17 lags at once), triangular peak interpolation. Pass 2: at
    that delay, block sums of x*conj(r) give the frequency (unwrapped block phases, least
    squares), robust to the discriminator noise at low SNR."""
    inc=increments(wave,CORR+LAGS,0)
    # MSK: frequency signs and a triangular peak; GMSK: the reference frequency in Q8 and a
    # parabolic peak. corr[j] is lag j-1 over reference samples 1..CORR.
    weight=[round_shift(f,8) if gmsk else (1 if f>=0 else -1) for f in reference_frequency[:CORR+1]]
    corr=[sum(round_shift(inc[n+j-1],16)*weight[n] for n in range(1,CORR+1)) for j in range(LAGS)]
    j=max(range(LAGS),key=lambda k:(corr[k],-k));lag=j-1
    # The fraction uses corr >> 5 for GMSK (|corr| < 2^33), so its denominator fits 32 bits.
    peak=[x>>5 for x in corr] if gmsk else corr
    fraction=0
    if 0<j<LAGS-1:
        if gmsk:
            # Smooth (Gaussian) peak: vertex of the parabola through the three lags.
            den=2*(2*peak[j]-peak[j-1]-peak[j+1])
        else:
            # MSK: the correlation of rectangular frequency pulses is a triangle.
            den=2*(peak[j]-min(peak[j-1],peak[j+1]))
        if den>0:fraction=max(-HALF,min(HALF,divide((peak[j+1]-peak[j-1])<<16,den)))
    delay=max(0,(lag<<16)+fraction)
    size=CORR//BLOCKS;phases=[];previous=None;unwrapped=0
    for j in range(BLOCKS):
        re=im=0
        for n in range(j*size,(j+1)*size):
            x=interp(wave,(n<<16)+delay);r=reference[n]
            re+=x[0]*r[0]+x[1]*r[1];im+=x[1]*r[0]-x[0]*r[1]
        phase=atan2(im,re)
        unwrapped=phase if previous is None else unwrapped+wrap(phase-previous);previous=phase;phases.append(unwrapped)
    weighted=sum((2*j-BLOCKS+1)*p for j,p in enumerate(phases))
    slope=divide(6*weighted,BLOCKS*(BLOCKS**2-1)*size)
    # Phase at sample 0: mean block phase minus the slope over the mean block centre (CORR-1)/2.
    intercept=divide(sum(phases),BLOCKS)-round_shift(slope*(CORR-1),1)
    return dict(delay=delay,frequency=wrap(slope),phase=wrap(intercept),lag=lag,corr=corr)


def receive(wave,preamble,count,gmsk,*,observe=False):
    if len(preamble)!=TRAIN or count<TRAIN or count>2048 or len(wave)<count*SPS:raise ValueError('Invalid frame')
    bits=[int(b) for b in preamble]
    acq=acquire(wave,transmit(bits,gmsk),frequencies(bits,gmsk),gmsk)
    gdelay=2*SPS if gmsk else 0
    previous=None;values=[];value=0;nodes=[]
    for n in range(count*SPS+gdelay):
        x=interp(wave,(n<<16)+acq['delay']+OFFSET)
        if previous is None:increment=0
        else:
            re=x[0]*previous[0]+x[1]*previous[1];im=x[1]*previous[0]-x[0]*previous[1]
            increment=wrap(atan2(im,re)-acq['frequency'])
        previous=x
        if n>=gdelay:
            value+=increment
            if (n-gdelay)%SPS==SPS-1:values.append(value);value=0
        if observe:nodes.append((x,increment))
    data=np.array([int(v>=0) for v in values])
    return dict(data=data,values=values,acquisition=acq,nodes=nodes)


# Coherent GMSK (Laurent C0 / Mengali; floating reference gmsk_coherent.py).
def _c0_taps():
    import gmsk_coherent
    return tuple(round(float(x)*32768) for x in gmsk_coherent.C0)


C0_TAPS=_c0_taps()          # 48 taps, Q15
C0_SHIFT=20                 # z_k = round(sum x*C0, 20), saturated to 18 bits
COHERENT_DELAY=10           # phase loop: updates applied 10 symbols late (RTL: ~31 clocks of rotation and CORDIC at 4 clocks per symbol)
# The discriminator-based delay estimate lies half a sample late for the C0 windows.
COHERENT_OFFSET=-(1<<15)
PHASE_K=1311                # 0.04 per unit angle error, Q15
FREQ_K=7                    # 0.0002, Q15
ERROR_LIMIT=341782637       # 0.5 rad in 2^-32 turns
AXIS=((0,0,1),(1,1,0),(0,1,1),(1,0,0))   # (-j)^m as (swap, negate re, negate im) for m = 0..3


def axis_rotate(z,k):
    """z*(-j)^((k+1) mod 4): onto the real axis for alpha_k."""
    re,im=z;m=(k+1)%4
    if m==1:return (im,-re)
    if m==2:return (-re,-im)
    if m==3:return (-im,re)
    return (re,im)


def receive_coherent(wave,preamble,count,*,observe=False):
    """C0 matched filter at the symbol starts n = 8k + delay - 1/2 (window of 48 samples),
    rotation by phase + frequency*(8k + 23.5) + loop phase (one rotation per symbol),
    axis rotation, decision beta = sign(re), loop error angle(r*target) clipped to 0.5 rad,
    data a_k = beta_k*beta_{k-1}."""
    if len(preamble)!=TRAIN or count<TRAIN or count>2048 or len(wave)<count*SPS:raise ValueError('Invalid frame')
    bits=[int(b) for b in preamble]
    acq=acquire(wave,transmit(bits,True),frequencies(bits,True),True)
    known=[];beta=1
    for b in bits:beta*=1 if b else -1;known.append(beta)
    samples=[interp(wave,(n<<16)+acq['delay']+COHERENT_OFFSET) for n in range(count*SPS+len(C0_TAPS))]
    loop_phase=loop_freq=0;pending=[0]*COHERENT_DELAY;previous=1;data=[];values=[];nodes=[]
    centre=round_shift(acq['frequency']*(len(C0_TAPS)-1),1)
    for k in range(count):
        error=pending.pop(0)
        loop_freq=wrap(loop_freq+round_shift(error*FREQ_K,15))
        loop_phase=wrap(loop_phase+loop_freq+round_shift(error*PHASE_K,15))
        acc=[0,0]
        for m,c in enumerate(C0_TAPS):
            x=samples[SPS*k+m];acc[0]+=x[0]*c;acc[1]+=x[1]*c
        z=(sat(round_shift(acc[0],C0_SHIFT)),sat(round_shift(acc[1],C0_SHIFT)))
        theta=wrap(acq['phase']+acq['frequency']*SPS*k+centre+loop_phase)
        r=axis_rotate(rotate(z,theta),k)
        decided=1 if r[0]>=0 else -1
        target=known[k] if k<TRAIN-4 else decided
        angle=atan2(r[1]*target,r[0]*target)
        pending.append(max(-ERROR_LIMIT,min(ERROR_LIMIT,angle)))
        data.append(int(decided*previous>0));values.append(r[0]);previous=decided
        if observe:nodes.append(dict(z=z,theta=theta,r=r,error=angle))
    return dict(data=np.array(data),values=values,acquisition=acq,nodes=nodes)
