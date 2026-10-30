"""Integer OQPSK modem: offset-quadrature transmitter and matched-filter Costas receiver.

Transmitter: per-axis Q15 amplitude T (0.7071), I impulses at samples 8k and Q impulses
at 8k+4 (a half-symbol offset), added into one complex wave and filtered by the same RRC
as BPSK (fir, shift 17), so the group delay is 2*16 and symbol 0 lands at index 32.

Receiver (modem_core.receive_oqpsk): pass 1 of acquisition uses adds only - the I instant
takes sI*y[32+8k+L] and the Q instant sQ*(-j)*y[32+8k+4+L] (the -j cancels the quadrature
offset), block sums per integer lag L in -1..16, energy peak, parabolic interpolation.
Pass 2: at that delay the block sums give the unwrapped phases and the per-symbol slope
(least squares); the loop tracks the residual with a classic split OQPSK Costas error,
I-branch at the I instant, Q-branch at the Q instant, applied LOOP_DELAY symbols late
(RTL latency budget)."""
import numpy as np
from fixed_point import round_shift
from bpsk_fixed import SPS, TRAIN, atan2, divide, interp, rotate, wrap, fir, quantize

T=23170                          # 0.7071 in Q15, per-axis symbol amplitude
LABELS=((1,1),(-1,1),(-1,-1),(1,-1))   # label -> (sign I, sign Q)
LAGS=18                          # integer lags -1..16
FIRST=32                         # MF output index of symbol 0 I-instant at zero delay
BLOCKS=8                         # acquisition window: symbols 0..127 in 8 blocks of 16
BLOCK=16
HALF=1<<15
PHASE_K=1311                     # 0.04 per radian-equivalent, Q15
FREQ_K=7                         # 0.0002, Q15
ERROR_LIMIT=341782637            # 0.5 rad in 2^-32 turns
LOOP_DELAY=8                     # loop updates applied 8 symbols late (RTL ready gate)


def _at(wave,index):return wave[index] if 0<=index<len(wave) else (0,0)


def transmit(labels):
    """Q15 wave: I at 8k, Q at 8k+4 (half-symbol offset), RRC filtered (fir, shift 17)."""
    if any(int(k)!=k or k not in (0,1,2,3) for k in labels):raise ValueError('Quaternary labels required')
    wave=[(0,0)]*(SPS*len(labels)+4)
    for k,label in enumerate(labels):
        sI,sQ=LABELS[int(label)]
        re,im=wave[SPS*k];wave[SPS*k]=(sI*T,im)
        re,im=wave[SPS*k+4];wave[SPS*k+4]=(re,sQ*T)
    return fir(wave)


def acquire(y,preamble):
    """Pass 1: sI*y(I) + sQ*(-j)*y(Q) block sums at integer lags, parabolic peak.
    Pass 2: block phases at that delay, unwrapped least squares -> slope and phase at the
    symbol 0 I-instant (block centre 16b+7.5)."""
    signs=[LABELS[int(p)] for p in preamble]
    energy=[0]*LAGS
    for j in range(LAGS):
        lag=j-1
        for b in range(BLOCKS):
            re=im=0
            for k in range(BLOCK*b,BLOCK*(b+1)):
                sI,sQ=signs[k]
                yi=_at(y,FIRST+SPS*k+lag);yq=_at(y,FIRST+SPS*k+4+lag)
                re+=sI*yi[0]+sQ*yq[1];im+=sI*yi[1]-sQ*yq[0]
            energy[j]+=(re>>9)**2+(im>>9)**2
    j=max(range(LAGS),key=lambda k:(energy[k],-k));lag=j-1
    e=[x>>8 for x in energy];fraction=0
    if 0<j<LAGS-1:
        den=2*(2*e[j]-e[j-1]-e[j+1])
        if den>0:fraction=max(-HALF,min(HALF,divide((e[j+1]-e[j-1])<<16,den)))
    delay=max(0,(lag<<16)+fraction)
    phases=[];previous=None;unwrapped=0
    for b in range(BLOCKS):
        re=im=0
        for k in range(BLOCK*b,BLOCK*(b+1)):
            sI,sQ=signs[k]
            zI=interp(y,((FIRST+SPS*k)<<16)+delay);zQ=interp(y,((FIRST+SPS*k+4)<<16)+delay)
            re+=sI*zI[0]+sQ*zQ[1];im+=sI*zI[1]-sQ*zQ[0]
        phase=atan2(im,re)
        unwrapped=phase if previous is None else unwrapped+wrap(phase-previous)
        previous=phase;phases.append(unwrapped)
    weighted=sum((2*b-BLOCKS+1)*p for b,p in enumerate(phases))
    slope_per_symbol=divide(6*weighted,BLOCKS*(BLOCKS**2-1)*BLOCK)
    frequency=wrap(divide(slope_per_symbol,SPS))
    phase=wrap(divide(sum(phases),BLOCKS)-round_shift(slope_per_symbol*(BLOCKS*BLOCK-1),1))
    return dict(delay=delay,frequency=frequency,slope=wrap(slope_per_symbol),phase=phase,lag=lag,energy=energy)


def receive(wave,preamble,count,*,observe=False,feedback=True,loop_delay=None):
    """Matched filter, acquisition, then a split Costas loop: the decision takes re of the
    I instant and im of the Q instant; eI=angle(rI*tI), eQ=angle(-j rQ*tQ), clipped 0.5 rad.
    feedback=False retains acquisition and disables the tracking correction for a
    same-input negative control. loop_delay overrides the feedback age in symbols
    for paired experiments without changing the module default."""
    if loop_delay is None:loop_delay=LOOP_DELAY
    if isinstance(loop_delay,bool) or not isinstance(loop_delay,(int,np.integer)) or loop_delay<1:
        raise ValueError('Loop delay must be a positive integer')
    if len(preamble)!=TRAIN or count<TRAIN or count>2048 or len(wave)<count*SPS:raise ValueError('Invalid frame')
    if any(int(p)!=p or p not in (0,1,2,3) for p in preamble):raise ValueError('Quaternary labels required')
    y=fir(wave);acq=acquire(y,preamble);delay=acq['delay']
    known=[LABELS[int(p)] for p in preamble][:TRAIN-4]
    loop_phase=loop_freq=0;pending=[0]*loop_delay
    data=[];values=[];nodes=[]
    for k in range(count):
        error=pending.pop(0)
        if feedback:
            loop_freq=wrap(loop_freq+round_shift(error*FREQ_K,15))
            loop_phase=wrap(loop_phase+loop_freq+round_shift(error*PHASE_K,15))
        thetaI=wrap(acq['phase']+acq['slope']*k+loop_phase)
        thetaQ=wrap(thetaI+4*acq['frequency'])
        zI=interp(y,((FIRST+SPS*k)<<16)+delay);zQ=interp(y,((FIRST+SPS*k+4)<<16)+delay)
        rI=rotate(zI,thetaI);rQ=rotate(zQ,thetaQ)
        re,im=rI[0],rQ[1]
        decided=0 if (re>=0 and im>=0) else 1 if (re<0 and im>=0) else 2 if (re<0 and im<0) else 3
        tI,tQ=known[k] if k<TRAIN-4 else LABELS[decided]
        eI=max(-ERROR_LIMIT,min(ERROR_LIMIT,atan2(rI[1]*tI,rI[0]*tI)))
        eQ=max(-ERROR_LIMIT,min(ERROR_LIMIT,atan2(-rQ[0]*tQ,rQ[1]*tQ)))
        error=(eI+eQ)>>1;pending.append(error)
        data.append(decided);values.append((re,im))
        if observe:nodes.append(dict(zI=zI,zQ=zQ,thetaI=thetaI,rI=rI,rQ=rQ,error=error))
    return dict(data=np.array(data),values=values,acquisition=acq,nodes=nodes)
