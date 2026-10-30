"""Floating coherent GMSK receiver (Laurent C0 / Mengali), reference for the coherent RTL.

The portable model (modem_core.receive_cpm) keeps the frequency discriminator; the
original Simulink receiver is coherent. With h = 1/2 the GMSK signal is
    s(t) ~ sum_k alpha_k C0(t - kT),  alpha_k = exp(j*pi/2*sum_{i<=k} a_i) = j*a_k*alpha_{k-1},
with the Laurent main pulse C0 (computed here from the transmitter's own phase pulse on
the sample grid; the remaining C1 part carries about 0.4 % of the energy). The receiver
correlates with C0 at symbol starts, rotates z_k by (-j)^(k+1) onto the real axis, decides
beta_k = sign, and recovers a_k = beta_k*beta_{k-1}. A decision-directed phase loop (known
symbols on the preamble) tracks the carrier; acquisition is the preamble fit of
modem_core is replaced by the streaming acquisition of cpm_fixed (the grid fit loses frames
below about 4 dB per sample). After the axis rotation the first-neighbour C0 terms
(RHO[1] = 0.51) are purely imaginary, only RHO[2] = 0.056 reaches the decision; a Viterbi
search over beta was tried and gives the same error counts, so the receiver is linear.
The loop error is the angle of r*target (amplitude-free), clipped to +-0.5 rad.
"""
import numpy as np
import modem_core as m

SPS=8


def laurent_c0(bt=0.3,sps=SPS):
    """C0 on the sample grid from the phase pulse q (0..1/2) of one symbol."""
    f=np.convolve(np.ones(sps),m.gaussian_taps(sps,bt))
    q=np.cumsum(f)/sps*0.5;lt=len(q);symbols=lt//sps
    def s(n):
        if 0<=n<lt:return np.sin(np.pi*q[n])
        if lt<=n<2*lt:return np.sin(np.pi/2-np.pi*q[n-lt])
        return 0.0
    return np.array([np.prod([s(n+i*sps) for i in range(symbols)]) for n in range((symbols+1)*sps)])


C0=laurent_c0()
ENERGY=float(np.dot(C0,C0))
# Matched-filter output of one pseudo-symbol at symbol offsets 0, +-1, +-2 (real, symmetric).
RHO=np.array([np.dot(C0[:len(C0)-SPS*k],C0[SPS*k:])/ENERGY for k in range(3)])


def acquire(cfg,wave,preamble):
    """Delay, slope (rad/sample) and complex gain. The floating grid fit of modem_core loses
    whole frames below about 4 dB, so the streaming acquisition of cpm_fixed (discriminator
    correlation over 18 lags, block phases of the reference correlation) gives delay,
    frequency and phase; the amplitude is the coherent preamble correlation."""
    import cpm_fixed,psk_fixed
    bits=[int(b) for b in preamble]
    acq=cpm_fixed.acquire(psk_fixed.quantize(wave),cpm_fixed.transmit(bits,True),cpm_fixed.frequencies(bits,True),True)
    # The discriminator-based delay lies half a sample late for the C0 windows.
    delay=acq['delay']/65536-0.5;slope=2*np.pi*acq['frequency']/2**32;phase=2*np.pi*acq['phase']/2**32
    reference=m.transmit(cfg,preamble)['waveform'];used=(len(preamble)-4)*SPS;n=np.arange(used)
    y=m.cubic(wave,n+delay)*np.exp(-1j*(slope*n+phase))
    amplitude=abs(np.vdot(reference[:used],y))/np.vdot(reference[:used],reference[:used]).real
    return delay,slope,amplitude*np.exp(1j*phase)


def matched(cfg,wave,count,delay,slope,gain):
    positions=np.arange(count*SPS+len(C0))+delay
    aligned=m.cubic(wave,positions)*np.exp(-1j*slope*np.arange(len(positions)))/gain
    return np.array([np.dot(aligned[k*SPS:k*SPS+len(C0)],C0) for k in range(count)])/ENERGY


def axis(k):
    """(-j)^(k+1): rotates alpha_k onto the real axis."""
    return (-1j)**((k+1)%4)


def receive(cfg,wave,preamble,count,*,track=True):
    preamble=np.asarray(preamble,int);wave=np.asarray(wave,complex)
    delay,slope,gain=acquire(cfg,wave,preamble)
    z=matched(cfg,wave,count,delay,slope,gain)
    known=np.cumprod(2*preamble-1)          # beta_k on the preamble (beta_{-1} = 1)
    phase=freq=0.0;beta=np.empty(count);soft=np.empty(count)
    for k in range(count):
        r=z[k]*axis(k)*np.exp(-1j*phase)
        soft[k]=r.real
        decided=1.0 if r.real>=0 else -1.0
        target=known[k] if k<len(preamble)-4 else decided
        beta[k]=decided
        if track:
            pe=float(np.clip(np.angle(r*target),-0.5,0.5))
            freq+=0.0002*pe;phase+=freq+0.04*pe
    a=beta*np.r_[1.0,beta[:-1]]
    data=((a+1)//2).astype(int)
    return dict(data=data,beta=beta,soft=soft,delay=delay,frequency=slope/(2*np.pi),gain=abs(gain))
