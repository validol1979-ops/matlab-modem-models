"""Deterministic, integer-only RTL vectors plus independent noisy channels."""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import bpsk_fixed as b
import psk_fixed as p

CONFIGS={'bpsk':'modems/bpsk_costas_2008_08_25/config.json','qpsk':'modems/qpsk_script_costas/config.json',
         'qpsk_half_diff':'modems/qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15/config.json',
         'qpsk_axis_diff_ff':'modems/qpsk_phase_noise_phase_sync_2009_04_12/config.json',
         'qpsk_axis':'modems/qpsk_demod_with_phase_noise/config.json',
         'psk8_ff':'modems/psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15/config.json',
         'psk8_fb':'modems/psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19/config.json',
         'psk8_rotated_fb':'modems/dqpsk_19_09_2006/config.json',
         'qpsk_diff':'modems/simo_maximal_ratio_combining_2010_08_27/config.json',
         'pi4':'modems/pi4_qpsk_8_sps_ff_sync_2021_05_27/config.json',
         'qam16':'modems/qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18/config.json',
         'qam16_eq':'modems/qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21/config.json',
         'qam16_dfe':'modems/qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26/config.json',
         'qam64':'modems/QAM64_2008_11_21/config.json'}
# Two-branch vectors: known gains, unequal noise variances, extra branch noise.
SIMO_GAINS=(.2+.3j,1-.4j);SIMO_VARIANCES=(1,2);SIMO_SIGMA=.05


def rtl_parameters(profile):
    """Verilog parameters of bpsk_tx/bpsk_rx that implement an integer profile."""
    if profile.order==2:return dict(ORDER=2)
    return dict(ORDER=profile.order,AMPLITUDE=profile.amplitude,DIFFERENTIAL=int(profile.differential!='none'),TX_AXIS=int(profile.tx_axis),
                FEEDFORWARD=int(profile.freq_gain==0),TIMING_LOOP=int(profile.timing_gain!=0),PI4=int(profile.differential=='pi4'),
                EQUALIZER={'none':0,'linear':1,'dfe':2}[profile.equalizer])

def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+''.join(' '.join(map(str,row))+'\n' for row in rows));return len(rows)

def generate(folder):
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(71);counts={}
    bit_frames=[rng.integers(0,2,n).tolist() for n in (1,2,33,192,768)]
    counts['bits']=save(folder/'bits.txt',[(bit,int(i==len(bits)-1)) for bits in bit_frames for i,bit in enumerate(bits)])
    counts['tx']=save(folder/'tx.txt',[(r,i,int(k==len(wave)-1)) for bits in bit_frames for wave in [b.transmit(bits)] for k,(r,i) in enumerate(wave)])
    rows=[]
    for n in (1,17,72,513):
        wave=[tuple(map(int,row)) for row in rng.integers(-131072,131072,(n,2))]+[(0,0)]*32
        expected=b.fir(wave)[:len(wave)]
        rows.extend((r,i,int(k==0),int(k==len(wave)-1),*expected[k]) for k,(r,i) in enumerate(wave))
    counts['fir']=save(folder/'fir.txt',rows)
    xy=[(0,0),(1,0),(-1,0),(0,1),(0,-1),(-2**48,-2**48)]+[tuple(map(int,row)) for row in rng.integers(-2**48,2**48,(513,2))]
    counts['cordic']=save(folder/'cordic.txt',[(x,y,b.atan2(y,x)) for x,y in xy])
    rows=[]
    for n in range(600):
        z=tuple(map(int,rng.integers(-131072,131072,2)));phase=int(rng.integers(-2**31,2**31));gain=int(rng.integers(1,16<<20))
        value=b.rotate(z,phase);value=[b.sat(b.round_shift(v*gain,20)) for v in value]
        rows.append((*z,phase,gain,*value))
    counts['rotate']=save(folder/'rotate.txt',rows)
    # Exercise the two full RAMs across main/tail and the short RAM to its last row.
    waves=[[tuple(map(int,row)) for row in rng.integers(-131072,131072,(n,2))] for n in (16640,16640,2048)]
    counts['memory']=save(folder/'memory.txt',[(frame,k,*z) for frame,wave in enumerate(waves) for k,z in enumerate(wave)])
    rows=[]
    for k in range(1000):
        frame=k%3;length=len(waves[frame])
        # Include every bank, the main/tail seam, zero padding and fractional reads
        # at the short RAM boundary. Random requests also vary ce in the bench.
        edges=(-2,-1,0,1,2,3,16382,16383,16384,16385,length-2,length-1,length,length+1)
        sample=edges[(k//3)%len(edges)] if k<3*len(edges)*4 else int(rng.integers(-2,length+2))
        pos=sample*65536+int(rng.integers(0,65536))
        rows.append((frame,pos,length,*b.interp(waves[frame],pos)))
    counts['interp']=save(folder/'interp.txt',rows)
    pairs=[(0,1),(1,2),(3,2),(-1,2),(-3,2),(-2**63,1),(2**63-1,1)]
    # Denominator zero is invalid. Both unsigned32 endpoints are legal,
    # including signed64 extrema and remainders around the rounding boundary.
    pairs += [(n,d) for d in (1,2**32-1) for n in
              (-2**63,2**63-1,0,1,-1,d//2,-(d//2),d//2+1,-(d//2+1),d,-d)]
    pairs += [(sign*n,d) for sign in (-1,1) for d in (2,4,32,349504,2**32-2)
              for n in (d//2,3*d//2,5*d//2,d-1,d,d+1)]
    pairs += [(int(rng.integers(-2**63,2**63)),int(rng.integers(1,2**32))) for _ in range(3000)]
    counts['divide']=save(folder/'divide.txt',[(n,d,b.divide(n,d)) for n,d in pairs])
    return counts


def receiver_vectors(folder,frames=12,*,loopback=False,count=768,seed=19,profile=p.BPSK,frame_padding=None):
    if frame_padding is not None and (loopback or not 0 <= frame_padding <= 64):
        raise ValueError('frame_padding requires pin waveforms and d in 0..64')
    def pin_length(wave):
        if frame_padding is None:return wave
        length=8*count+frame_padding
        return (list(wave)+[(0,0)]*max(0,length-len(wave)))[:length]
    import modem_core as real
    cfg=real.load_config(ROOT/CONFIGS[profile.name])
    simo=cfg['diversity_branches']==2
    if simo:
        import mrc_fixed as m
        gains=[m.quantize_gain(g) for g in SIMO_GAINS];weights=m.weights(*gains,*SIMO_VARIANCES)
        if m.branch_profile(cfg) is not profile:raise ValueError('Profile and configuration disagree')
    elif p.profile_for(cfg) is not profile:raise ValueError('Profile and configuration disagree')
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    if simo:save(folder/'gains.txt',[(*gains[0],*gains[1],*SIMO_VARIANCES)])
    preamble=rng.integers(0,profile.alphabet,192);rows=[];traces=[];acquisitions=[];errors=[]
    save(folder/'preamble.txt',[(int(bit),) for bit in preamble])
    cases=[{},dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
           dict(snr_db=30,gain=.2,phase=-1.1,frequency=-.0005,delay=7.25),
           dict(snr_db=-8)]
    # QAM16 also covers the clock-drift requirement of the variable-delay model.
    if profile.qam:cases.append(dict(snr_db=35,drift=.0006,delay=1.25))
    # Equalizer profiles: the one-symbol echo they exist for, with a carrier offset.
    if profile.equalizer!='none':cases+=[dict(echo=.45,delay=3.25,snr_db=35),dict(echo=.45,delay=2.25,snr_db=30,gain=.65,phase=.38,frequency=.00015)]
    for frame in range(frames):
        bits=np.r_[preamble,rng.integers(0,profile.alphabet,count-192)]
        wave=real.channel(cfg,real.transmit(cfg,bits)['waveform'],seed=7+frame,**cases[frame%len(cases)])
        if simo:
            # Loopback feeds the transmitter output to both branches.
            noise=np.random.default_rng(500+frame).normal(size=(4,len(wave)))
            branches=[p.transmit(profile,bits)]*2 if loopback else [p.quantize(g*wave+SIMO_SIGMA*np.sqrt(v)*(noise[2*j]+1j*noise[2*j+1]))
                                                                   for j,(g,v) in enumerate(zip(SIMO_GAINS,SIMO_VARIANCES))]
            branches=[pin_length(branch) for branch in branches]
            result=p.receive(profile,m.combine(*branches,*weights),preamble,count)
            if not loopback:rows.extend((*branches[0][k],*branches[1][k],int(k==len(branches[0])-1)) for k in range(len(branches[0])))
        else:
            quantized=pin_length(p.transmit(profile,bits) if loopback else p.quantize(wave));result=p.receive(profile,quantized,preamble,count)
            if not loopback:rows.extend((r,i,int(k==len(quantized)-1)) for k,(r,i) in enumerate(quantized))
        if loopback:rows.extend((int(bit),0,int(k==len(bits)-1)) for k,bit in enumerate(bits))
        acq=result['acquisition']
        for k,trace in enumerate(result['trace']):
            r,i,phase,freq,gain,correction,idx,label=trace
            traces.append((r,i,b.wrap(phase+acq['frequency']*(k+1)),freq,gain,correction,idx,label,int(k==count-1),int(bits[k])))
        acquisitions.append(tuple(int(acq[key]) for key in ('delay','frequency','phase','gain','score','confidence')))
        errors.append(int(np.count_nonzero(result['data'][192:]!=bits[192:])))
    save(folder/'rx_wave.txt',rows);save(folder/'rx_trace.txt',traces);save(folder/'rx_acquire.txt',acquisitions)
    return dict(frames=frames,symbols=frames*count,samples=len(rows),payload_errors=errors)


def mrc_vectors(folder):
    """Divider and two-branch combiner: configurations with weights or error, then samples."""
    import mrc_fixed as m
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(97);counts={}
    pairs=[(0,1),(1,2),(3,2),(-1,2),(-3,2),(5,2),(-5,2),(2**62,1),(-2**62,3),(2**62,2**51-1)]
    pairs+=[(int(rng.integers(-2**62,2**62)),int(rng.integers(1,2**52))) for _ in range(200)]
    pairs+=[(int(rng.integers(-2**40,2**40)),int(rng.integers(1,2**20))) for _ in range(100)]
    counts['divide_wide']=save(folder/'divide.txt',[(n,d,b.divide(n,d)) for n,d in pairs])
    configs=[((6554,9830),(32768,-13107),1,1),((6554,9830),(32768,-13107),1,2),((32768,0),(0,0),1,1),((0,0),(0,-16384),7,3),
             ((-131072,-131072),(-131072,131071),65535,65535),((4097,0),(0,0),1,1),((-131072,-131072),(131071,131071),1,65535),
             ((0,0),(0,0),1,1),((4096,0),(0,0),1,1),((32768,0),(0,0),0,1),((32768,0),(0,0),5,0)]
    for _ in range(12):
        configs.append((tuple(map(int,rng.integers(-60000,60000,2))),tuple(map(int,rng.integers(-60000,60000,2))),*map(int,rng.integers(1,65536,2))))
    rows=[];samples=0
    for index,(ga,gb,va,vb) in enumerate(configs):
        try:weights=m.weights(ga,gb,va,vb)
        except ValueError:weights=None
        n=0 if weights is None else (40 if index%3 else 300)
        a=[tuple(map(int,z)) for z in rng.integers(-131072,131072,(n,2))];c=[tuple(map(int,z)) for z in rng.integers(-131072,131072,(n,2))]
        if index==4 and n:a[0]=c[0]=(131071,-131072)
        out=m.combine(a,c,*weights) if weights else []
        flat=[x for w in (weights or ((0,0),(0,0))) for x in w]
        saturated=0
        if weights:
            (wr,wi),(xr,xi)=weights
            for (pr,pi),(qr,qi) in zip(a,c):
                for v in (pr*wr-pi*wi+qr*xr-qi*xi,pr*wi+pi*wr+qr*xi+qi*xr):saturated|=b.round_shift(v,14)!=b.sat(b.round_shift(v,14))
        rows.append((*ga,*gb,va,vb,int(weights is not None),*flat,n,int(saturated)))
        rows.extend((*a[k],*c[k],int(k==n-1),*out[k]) for k in range(n));samples+=n
    path=folder/'mrc.txt';path.write_text(f'{len(configs)} {samples}\n'+''.join(' '.join(map(str,row))+'\n' for row in rows))
    counts['mrc_configs']=len(configs);counts['mrc_samples']=samples
    return counts
