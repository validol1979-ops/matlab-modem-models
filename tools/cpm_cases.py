"""Integer MSK/GMSK RTL vectors: transmitter samples, receiver outputs and acquisitions."""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import cpm_fixed as c
import psk_fixed as p
import modem_core as real

CONFIGS={False:'modems/msk_modulator_2008_06_22/config.json',True:'modems/gmsk_coherent_demodulation_2010_10_03/config.json'}
CASES=[{},dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
       dict(snr_db=30,gain=.2,phase=-1.1,frequency=-.0005,delay=7.25),
       dict(snr_db=-8),dict(snr_db=6,delay=3.4),dict(snr_db=35,gain=.8,phase=2.1,frequency=.0003,delay=.5)]


def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+''.join(' '.join(map(str,row))+'\n' for row in rows));return len(rows)


def vectors(folder,gmsk,frames=12,count=768,seed=19,loopback=False):
    """Receiver vectors; loopback feeds the integer transmitter output (no channel)."""
    cfg=real.load_config(ROOT/CONFIGS[gmsk]);folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    preamble=rng.integers(0,2,192);save(folder/'preamble.txt',[(int(b),) for b in preamble])
    wave_rows=[];out_rows=[];acq_rows=[];bit_rows=[];tx_rows=[];errors=[]
    for frame in range(frames):
        bits=np.r_[preamble,rng.integers(0,2,count-192)]
        tx=c.transmit(bits,gmsk)
        bit_rows.extend((int(b),int(k==count-1)) for k,b in enumerate(bits))
        tx_rows.extend((r,i,int(k==len(tx)-1)) for k,(r,i) in enumerate(tx))
        if loopback:wave=tx
        else:wave=p.quantize(real.channel(cfg,real.transmit(cfg,bits)['waveform'],seed=7+frame,**CASES[frame%len(CASES)]))
        wave_rows.extend((r,i,int(k==len(wave)-1)) for k,(r,i) in enumerate(wave))
        # GMSK is received coherently (Laurent C0), MSK with the discriminator.
        result=c.receive_coherent(wave,preamble,count) if gmsk else c.receive(wave,preamble,count,False);acq=result['acquisition']
        out_rows.extend((v,int(result['data'][k]),int(k==count-1)) for k,v in enumerate(result['values']))
        acq_rows.append((acq['delay'],acq['frequency'],acq['phase']))
        errors.append(int(np.count_nonzero(result['data'][192:]!=bits[192:])))
    save(folder/'rx_wave.txt',wave_rows);save(folder/'rx_out.txt',out_rows);save(folder/'rx_acquire.txt',acq_rows)
    save(folder/'tx_bits.txt',bit_rows);save(folder/'tx_out.txt',tx_rows)
    return dict(frames=frames,symbols=frames*count,samples=len(wave_rows),tx_samples=len(tx_rows),payload_errors=errors)


if __name__=='__main__':
    for gmsk in (False,True):print(vectors(ROOT/'build/rtl/cpm/vectors'/('gmsk' if gmsk else 'msk'),gmsk,frames=2))
