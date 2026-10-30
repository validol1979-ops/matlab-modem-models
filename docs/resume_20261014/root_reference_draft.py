"""Independent float receiver on the exact quantized UVM pin waveform."""
from pathlib import Path
import sys
import numpy as np
ROOT=Path('~/PROJECT_THEORY/Модемы')
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'common/python'))
from bpsk_cases import CONFIGS
import modem_core as real
import psk_fixed as profiles

def rows(path,width):
    lines=Path(path).read_text().splitlines()
    if not lines or len(lines)-1!=int(lines[0]):raise ValueError('Reference header/count')
    values=np.array([list(map(int,line.split())) for line in lines[1:]],dtype=np.int64)
    if values.ndim!=2 or values.shape[1]!=width:raise ValueError('Reference column geometry')
    return values

def floating_payload_scores(folder,profile_name):
    folder=Path(folder);cfg=real.load_config(ROOT/CONFIGS[profile_name])
    profile=next(p for p in profiles.PROFILES if p.name==profile_name)
    training=rows(folder/'preamble.txt',1)[:,0]
    if len(training)!=192 or not np.all((training>=0)&(training<profile.alphabet)):raise ValueError('Training labels')
    simo=cfg['diversity_branches']==2
    raw=rows(folder/'rx_wave.txt',5 if simo else 3)
    if not np.all((raw[:,:-1]>=-131072)&(raw[:,:-1]<=131071)) or not np.isin(raw[:,-1],[0,1]).all():raise ValueError('Waveform ports')
    starts=[0]+(np.flatnonzero(raw[:,-1])+1).tolist()
    trace=rows(folder/'rx_trace.txt',10)
    if starts[-1]!=len(raw) or len(trace)%(len(starts)-1):raise ValueError('Frame geometry')
    count=len(trace)//(len(starts)-1)
    truth=trace[:,9].reshape(-1,count)
    if not 192<=count<=4095 or not np.all((truth>=0)&(truth<profile.alphabet)) or not np.all(truth[:,:192]==training):raise ValueError('Scoring labels')
    result=[]
    for frame,(a,b) in enumerate(zip(starts,starts[1:])):
        wave=(raw[a:b,0]+1j*raw[a:b,1])/32768
        if simo:
            gains=rows(folder/'gains.txt',6)
            if len(gains)!=1 or not np.all((gains[0,4:]>=1)&(gains[0,4:]<=65535)):raise ValueError('MRC gain configuration')
            if not np.all((gains[0,:4]>=-131072)&(gains[0,:4]<=131071)):raise ValueError('Q15 gains')
            gain=[complex(*gains[0,i:i+2])/32768 for i in (0,2)]
            other=(raw[a:b,2]+1j*raw[a:b,3])/32768
            wave=real.maximal_ratio_combine([wave,other],gain,gains[0,4:])
        # Decoder receives waveform and training only; truth is used below for scoring.
        decoded=np.asarray(real.receive(cfg,wave,training,count)['data'])
        if decoded.shape!=(count,) or decoded.dtype.kind not in 'iu' or not np.all((decoded>=0)&(decoded<profile.alphabet)):raise ValueError('Floating decision geometry')
        errors=(decoded[192:]!=truth[frame,192:])
        result.append(dict(frame=frame,symbols=count-192,errors=int(np.count_nonzero(errors)),ser=float(np.mean(errors)) if len(errors) else None,defined=bool(len(errors)),decisions=decoded.tolist()))
    return result
