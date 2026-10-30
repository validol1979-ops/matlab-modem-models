"""Integer Costas loop and Gardner timing loop (references of rtl/common/costas_loop.sv,
gardner_timing.sv; research_core costas and timing, algorithms/synchronization/symbol_timing).

costas: value = x*exp(-j phase) (bpsk_fixed.rotate: phase in 2^-32 turns, its top 12 bits index
the pilot's Q17 cos table), error = sign(re)*im - sign(im)*re in Q15 (np.sign: 0 for 0),
frequency += rnd(K2*error, 16), phase += frequency + rnd(K1*error, 16) (32-bit wrap), with
K = round(k/(2 pi) * 2^33) (the error is Q15 and the phase 2^-32 turns). Outputs: the values
(Q15) and the phase used for each sample (2^-32 turns).
timing: positions in Q32 samples. early/mid/late = bpsk_fixed.interp(x, P16 -+ sps*2^15) with
P16 = P >> 16 (Q16, cubic table of 256 fractions), error = clip((late - early)*conj(mid), +-1)
as re((late-early) conj(mid)) in Q30 clipped to +-2^30, rate += rnd(K4*error, 30), P += sps*2^32 +
rate + rnd(K3*error, 30) with K = round(k*2^32). Outputs: mid (Q15) and P16 of each output.
round is half up, (v + 2^(s-1)) >> s.

timing(x, sps, count, parameters, stats=None): the optional stats is a sat_diag.SatStats /
SatTrace; every actual preclamp gradient (late - early) conj(mid) real part is recorded as
stage 'gradient' through the symmetric +-ONE30 clamp, so an instrumented run is bit-identical
to the default one (record() applies exactly the model clamp and counts only strict rail
excursions; SatTrace also counts every evaluated gradient)."""
import math
import fft_fixed as f
from bpsk_fixed import rotate, interp

ONE30=1<<30


def wrap32(v):return ((int(v)+(1<<31))%(1<<32))-(1<<31)
def sign(v):return (v>0)-(v<0)


def costas_gains(k1,k2):
    if k1<0 or k2<0:raise ValueError('Costas gains must be non-negative')
    g=[int(round(k/(2*math.pi)*(1<<33))) for k in (k1,k2)]
    if any(v>=1<<31 for v in g):raise ValueError('Costas gain too large')
    return tuple(g)


def costas(x,gains):
    k1,k2=gains;phase=frequency=0;values=[];phases=[]
    for z in x:
        re,im=rotate(z,phase);error=sign(re)*im-sign(im)*re
        values.append((re,im));phases.append(wrap32(phase))
        frequency=wrap32(frequency+f.rnd(k2*error,16));phase=wrap32(phase+frequency+f.rnd(k1*error,16))
    return values,phases


def costas_pipelined(x,gains,delay,gaps=None):
    """Pipelined Costas (rtl/common/costas_stream.sv): the SAME per-sample arithmetic, but the error
    of a sample is applied to the phase register only when the sample `delay` pipeline advances later
    is rotated, so a new sample can be rotated on every advance (II=1). delay=1 reproduces costas()
    exactly (there the error of sample n is applied before sample n+1 is rotated); delay=10 is the
    loop delay of costas_stream.sv.

    The delay is counted in pipeline ADVANCES, not wall clocks: a backpressure stall (m_valid and no
    m_ready) freezes every stage of the RTL, so it removes advances and leaves the outputs unchanged.
    `gaps` gives the number of advances between the acceptance of the previous sample and this one
    (default 1 = a dense stream; an input bubble is a gap of 2 or more). An input bubble therefore
    shortens the delay in SAMPLES: the RTL latency is a fixed number of advances."""
    delay=int(delay)
    if delay<1:raise ValueError('Costas pipeline delay must be at least one sample')
    x=list(x)
    if gaps is None:gaps=[1]*len(x)
    if len(gaps)!=len(x):raise ValueError('costas_pipelined needs one gap per sample')
    if any(int(g)<1 for g in gaps):raise ValueError('Costas pipeline gaps must be at least one advance')
    k1,k2=gains;phase=frequency=0;values=[];phases=[];errors=[];steps=[];applied=0
    advance=0
    for n,z in enumerate(x):
        advance+=int(gaps[n])
        while applied<n and steps[applied]<=advance-delay:
            error=errors[applied]
            frequency=wrap32(frequency+f.rnd(k2*error,16))
            phase=wrap32(phase+frequency+f.rnd(k1*error,16))
            applied+=1
        re,im=rotate(z,phase);values.append((re,im));phases.append(wrap32(phase))
        errors.append(sign(re)*im-sign(im)*re);steps.append(advance)
    return values,phases


def timing_gains(position,k3,k4):
    if position<0 or k3<0 or k4<0:raise ValueError('timing parameters must be non-negative')
    return int(round(position*(1<<32))),int(round(k3*(1<<32))),int(round(k4*(1<<32)))


def timing(x,sps,count,parameters,stats=None):
    if sps<2 or count<1:raise ValueError('timing needs sps >= 2 and count >= 1')
    p,k3,k4=parameters;rate=0;values=[];positions=[]
    half=sps<<15
    for _ in range(count):
        p16=p>>16
        early,mid,late=interp(x,p16-half),interp(x,p16),interp(x,p16+half)
        dr,di=late[0]-early[0],late[1]-early[1]
        gradient=dr*mid[0]+di*mid[1]
        error=max(-ONE30,min(ONE30,gradient)) if stats is None \
            else stats.record('gradient',gradient,ONE30,clamp='sym')
        values.append(mid);positions.append(p16)
        rate+=f.rnd(k4*error,30);p+=(sps<<32)+rate+f.rnd(k3*error,30)
    return values,positions
