"""Integer OQPSK RTL vectors: TX samples, RX frames, acquisitions and receiver values.

Non-loopback plans append one deterministic raw receiver stress frame: full-scale
complex samples change sign halfway through. It obeys the 18-bit input and frame
length contracts, exercises both RX output rails, and makes no payload-error claim.
The TX labels for this frame keep the shared preamble and cycle through labels 0..3.
All earlier RNG draws and vectors are preserved.

TX full scale is unreachable: impulse amplitude 23170 times the maximum RRC
absolute-tap sum over one residue modulo 8 gives a rounded component bound 12154.
In loopback, the matched FIR, cubic interpolation and rotation increase this bound
to at most 68229, still below 131071. output_bounds includes table quantization and
integer rounding, independent of the acquired delay and loop phase. Loopback plans
retain their actual TX-to-RX waveform and receive no overload frame.
"""
from pathlib import Path
import sys
import json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import oqpsk_fixed as o
import modem_core as real
import bpsk_fixed as b
from oqpsk_tracking import scenario as tracking_scenario

LIMIT=(1<<17)-1


def output_bounds():
    """Conservative absolute component bounds for TX and TX-to-RX loopback."""
    ceil=lambda value,shift:(value+(1<<shift)-1)>>shift
    phase_sum=max(sum(abs(h) for k,h in enumerate(b.RRC) if k%b.SPS==phase)
                  for phase in range(b.SPS))
    tx=ceil(o.T*phase_sum,17)
    matched=ceil(tx*sum(abs(h) for h in b.RRC),17)
    interpolated=ceil(matched*max(sum(abs(w) for w in row) for row in b.CUBIC),16)
    rotation=max(abs(c)+abs(b.COS[(k-1024)&4095]) for k,c in enumerate(b.COS))
    return tx,ceil(interpolated*rotation,17)

CONFIG='modems/oqpsk_2_sps_timing_recovery_2019_12_05/config.json'
DELAY_CHANNELS={'threshold':dict(snr_db=0,frequency=1e-4,delay=2.25),
                'phase_noise':dict(snr_db=40,frequency=3e-4,delay=1.25,phase_noise=.018)}
CASES=[{},dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
       dict(snr_db=30,gain=.2,phase=-1.1,frequency=-.0005,delay=7.25),
       dict(snr_db=-8),dict(snr_db=6,delay=3.4),dict(snr_db=35,gain=.8,phase=2.1,frequency=.0003,delay=.5)]


def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+''.join(' '.join(map(str,row))+'\n' for row in rows));return len(rows)


def delay_vectors(folder,loop_delay,frames=6):
    """Paired delay experiment using the loop study's channels and seeds. Preamble
    is shared within one RTL configuration; each channel has frames*576 payload symbols.
    Both delays receive byte-identical inputs and labels, with separate expected outputs."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    cfg=real.load_config(ROOT/CONFIG);count=768
    preamble=np.random.default_rng(1000).integers(0,4,192)
    data={name:[] for name in ('tx_symbols','tx_out','rx_wave','rx_out','rx_acquire')}
    errors={name:[] for name in DELAY_CHANNELS}
    for name,params in DELAY_CHANNELS.items():
        for frame in range(frames):
            seed=1000+17*frame;rng=np.random.default_rng(seed)
            rng.integers(0,4,192) # retain the study's payload draws
            labels=np.r_[preamble,rng.integers(0,4,count-192)]
            tx=o.transmit(labels)
            wave=o.quantize(real.channel(cfg,real.transmit(cfg,labels)['waveform'],seed=seed,**params))
            result=o.receive(wave,preamble,count,loop_delay=loop_delay);acq=result['acquisition']
            data['tx_symbols'].extend((int(label),int(k==count-1)) for k,label in enumerate(labels))
            for field,values in (('tx_out',tx),('rx_wave',wave)):
                data[field].extend((re,im,int(k==len(values)-1)) for k,(re,im) in enumerate(values))
            data['rx_out'].extend((re,im,int(result['data'][k]),int(k==count-1))
                                  for k,(re,im) in enumerate(result['values']))
            data['rx_acquire'].append((acq['delay'],acq['frequency'],acq['phase']))
            errors[name].append(int(np.count_nonzero(result['data'][192:]!=labels[192:])))
    save(folder/'preamble.txt',[(int(label),) for label in preamble])
    sizes={name:save(folder/(name+'.txt'),rows) for name,rows in data.items()}
    return dict(loop_delay=loop_delay,frames=frames*len(DELAY_CHANNELS),symbols=sizes['tx_symbols'],
                tx_samples=sizes['tx_out'],samples=sizes['rx_wave'],payload_errors=errors,
                payload_symbols_per_scenario=frames*(count-192),channels=DELAY_CHANNELS)


def vectors(folder,frames=12,count=768,seed=19,loopback=False,tracking=True,tailcut=False):
    """Frame k: the shared 192-label preamble plus count-192 random labels. The receiver
    input is the RRC-filtered OQPSK wave through the real channel (quantized to Q15);
    loopback=True feeds the integer transmitter output directly. Expected values come
    from oqpsk_fixed.receive on exactly the streamed samples. tailcut=True is a
    separate legal minimum-length RX stress plan: delay 7.25 samples, then cut
    the channel waveform to count*8 samples before the receiver's 32-zero FIR tail.
    It omits the overload/tracking frames and makes no zero-payload-SER claim."""
    if tailcut and loopback:raise ValueError('Tailcut is a channel stress plan, not TX-to-RX loopback')
    cfg=real.load_config(ROOT/CONFIG);folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    preamble=rng.integers(0,4,192)
    save(folder/'preamble.txt',[(int(p),) for p in preamble])
    symbol_rows=[];tx_rows=[];wave_rows=[];out_rows=[];acq_rows=[];errors=[]
    tx_bound,loopback_bound=output_bounds()
    assert tx_bound<LIMIT and loopback_bound<LIMIT
    for frame in range(frames):
        labels=np.r_[preamble,rng.integers(0,4,count-192)]
        tx=o.transmit(labels)
        assert all(abs(v)<=tx_bound for pair in tx for v in pair)
        symbol_rows.extend((int(l),int(k==count-1)) for k,l in enumerate(labels))
        tx_rows.extend((r,i,int(k==len(tx)-1)) for k,(r,i) in enumerate(tx))
        if loopback:wave=tx
        else:
            params=dict(delay=7.25) if tailcut else CASES[frame%len(CASES)]
            wave=o.quantize(real.channel(cfg,real.transmit(cfg,labels)['waveform'],seed=7+frame,**params))
            if tailcut:wave=wave[:count*8]
        wave_rows.extend((int(r),int(i),int(k==len(wave)-1)) for k,(r,i) in enumerate(wave))
        result=o.receive(wave,preamble,count);acq=result['acquisition']
        if loopback:assert all(abs(v)<=loopback_bound for pair in result['values'] for v in pair)
        acq_rows.append((acq['delay'],acq['frequency'],acq['phase']))
        out_rows.extend((int(v[0]),int(v[1]),int(result['data'][k]),int(k==count-1)) for k,v in enumerate(result['values']))
        errors.append(int(np.count_nonzero(result['data'][192:]!=labels[192:])))
    if not loopback and not tailcut:
        labels=np.r_[preamble,np.arange(count-192)%4]
        tx=o.transmit(labels)
        assert all(abs(v)<=tx_bound for pair in tx for v in pair)
        symbol_rows.extend((int(label),int(k==count-1)) for k,label in enumerate(labels))
        tx_rows.extend((re,im,int(k==len(tx)-1)) for k,(re,im) in enumerate(tx))
        wave=[(LIMIT,LIMIT)]*(len(tx)//2)+[(-LIMIT-1,-LIMIT-1)]*(len(tx)-len(tx)//2)
        result=o.receive(wave,preamble,count);acq=result['acquisition']
        flat=[v for pair in result['values'] for v in pair]
        assert max(flat)==LIMIT and min(flat)==-LIMIT-1, \
            f'OQPSK RX stress frame misses rails: {min(flat)}, {max(flat)}'
        wave_rows.extend((re,im,int(k==len(wave)-1)) for k,(re,im) in enumerate(wave))
        acq_rows.append((acq['delay'],acq['frequency'],acq['phase']))
        out_rows.extend((int(v[0]),int(v[1]),int(result['data'][k]),int(k==count-1))
                        for k,v in enumerate(result['values']))
        errors.append(int(np.count_nonzero(result['data'][192:]!=labels[192:])))
    tracking_report = None
    if tracking and not loopback and not tailcut and count >= 768:
        labels, tx, wave, result, _, tracking_report = tracking_scenario(preamble, count)
        assert all(tracking_report[k] for k in ('acquired','lost','recovered')), tracking_report
        symbol_rows.extend((int(label),int(k==count-1)) for k,label in enumerate(labels))
        tx_rows.extend((re,im,int(k==len(tx)-1)) for k,(re,im) in enumerate(tx))
        wave_rows.extend((re,im,int(k==len(wave)-1)) for k,(re,im) in enumerate(wave))
        acq=result['acquisition'];acq_rows.append((acq['delay'],acq['frequency'],acq['phase']))
        out_rows.extend((re,im,int(result['data'][k]),int(k==count-1))
                        for k,(re,im) in enumerate(result['values']))
        errors.append(int(np.count_nonzero(result['data'][192:]!=labels[192:])))
    (folder/'tracking.json').write_text(json.dumps(tracking_report,indent=2)+'\n')
    symbols=save(folder/'tx_symbols.txt',symbol_rows)
    tx_samples=save(folder/'tx_out.txt',tx_rows)
    samples=save(folder/'rx_wave.txt',wave_rows)
    save(folder/'rx_out.txt',out_rows)
    save(folder/'rx_acquire.txt',acq_rows)
    report=dict(frames=frames+int(not loopback and not tailcut)+int(tracking_report is not None),
                tracking=tracking_report,symbols=symbols,samples=samples,tx_samples=tx_samples,
                payload_errors=errors,overload=not loopback and not tailcut,tx_output_bound=tx_bound,
                loopback_output_bound=loopback_bound)
    if tailcut:report.update(tailcut=True,delay_samples=7.25,rx_samples_per_frame=count*8,
                             matched_samples_per_frame=count*8+32,
                             payload_ser=[errors_count/(count-192) if count>192 else None for errors_count in errors])
    return report


if __name__=='__main__':print(vectors(ROOT/'build/rtl/oqpsk/vectors',frames=2))
