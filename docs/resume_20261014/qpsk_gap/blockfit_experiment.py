"""Diagnosis 2026-10-14: fixed acquisition at -8 dB (UVM frame3). Run from repo root after
`python3 tools/run_bpsk_uvm.py --suite hdl --pilot rx --profile <name>` created the vectors.
Compares the current per-symbol unwrapped phase fit with the existing block fit (fit_blocks)."""
import sys,dataclasses
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'));sys.path.insert(0,str(ROOT/'common/python'))
import psk_fixed as p
import uvm_floating_reference as ref

def run(name,block):
    prof=next(q for q in p.PROFILES if q.name==name)
    if block:prof=dataclasses.replace(prof,block_fit=True)
    F=ROOT/'build/rtl/bpsk_uvm'/f'{name}_vectors'
    raw=ref.rows(F/'rx_wave.txt',3);starts=[0]+(np.flatnonzero(raw[:,2])+1).tolist()
    tr=ref.rows(F/'rx_trace.txt',10).reshape(4,768,10);pre=ref.rows(F/'preamble.txt',1)[:,0].tolist()
    out=[]
    for f,(a,b) in enumerate(zip(starts,starts[1:])):
        r=p.receive(prof,[tuple(map(int,x)) for x in raw[a:b,:2]],pre,768);acq=r['acquisition']
        out.append((int(np.count_nonzero(np.asarray(r['data'][192:])!=tr[f,192:,9])),acq['frequency'],acq['gain']))
    return out

if __name__=='__main__':
    for name in sys.argv[1:] or ('qpsk','qpsk_axis','qpsk_half_diff'):
        print(name,'current',run(name,False));print(name,'blockfit',run(name,True))
