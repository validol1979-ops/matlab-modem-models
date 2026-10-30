#!/usr/bin/env python3
"""Per-node SQNR and payload SER, with independent floating references.

DSP-node comparisons use the same integer loop positions/phase/gain so the
report measures node quantization, not disagreement between acquisition modes.
Final SER is independently compared with the original floating receiver.
"""
import argparse
import math
import sys
from pathlib import Path
import numpy as np
from regression_evidence import ROOT,begin,finish,write_json
sys.path.insert(0,str(ROOT/'common/python'))
import bpsk_fixed as b
import modem_core as real


def complex_samples(values):
    a=np.asarray(values,dtype=float)/2**15
    return a[:,0]+1j*a[:,1]


def metric(actual,expected):
    actual=np.asarray(actual,complex);expected=np.asarray(expected,complex)
    if actual.shape!=expected.shape or not np.all(np.isfinite(actual)) or not np.all(np.isfinite(expected)):raise RuntimeError('Invalid precision samples')
    mse=float(np.mean(abs(actual-expected)**2));energy=float(np.mean(abs(expected)**2))
    rails=int(np.count_nonzero(np.isin(np.rint(actual.real*32768),[-131072,131071]))+np.count_nonzero(np.isin(np.rint(actual.imag*32768),[-131072,131071])))
    return dict(samples=len(actual),sqnr_db=10*math.log10(energy/mse) if energy and mse else None,max_complex_error=float(np.max(abs(actual-expected))),rail_values=rails)


def report():
    cfg=real.load_config(ROOT/'modems/bpsk_costas_2008_08_25/config.json');records=[]
    cases=[('clean',{}),('carrier_timing',dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25)),
           ('low_gain',dict(snr_db=30,gain=.2,phase=-1.1,frequency=-.0005,delay=7.25)),('noise',dict(snr_db=-8))]
    for seed in (19,82):
        bits=np.random.default_rng(seed).integers(0,2,768);float_tx=real.transmit(cfg,bits)['waveform'];int_tx=complex_samples(b.transmit(bits))
        for name,params in cases:
            wave=real.channel(cfg,float_tx,**params);quantized=b.quantize(wave);result=b.receive(quantized,bits[:192],len(bits),observe=True)
            filtered=complex_samples(result['filtered']);float_filtered=np.convolve(wave,real.rrc_taps(8,32,1))
            nodes=result['nodes'];positions=np.array([node['position']/65536 for node in nodes]);phases=np.array([node['phase']/2**32*2*math.pi for node in nodes]);gains=np.array([node['gain']/2**20 for node in nodes])
            mids=complex_samples([node['mid'] for node in nodes]);rotated=complex_samples([node['rotated'] for node in nodes]);values=complex_samples([node['value'] for node in nodes])
            metrics=dict(tx_rrc=metric(int_tx,float_tx),rx_rrc=metric(filtered,float_filtered),
                         cubic_mid=metric(mids,real.cubic(filtered,positions)),rotation=metric(rotated,mids*np.exp(-1j*phases)),gain=metric(values,rotated*gains))
            errors=int(np.count_nonzero(result['data'][192:]!=bits[192:]));acq=result['acquisition']
            # The original receiver may reject unusable training under extreme noise.
            try:reference_errors=int(np.count_nonzero(real.receive(cfg,wave,bits[:192],768)['data'][192:]!=bits[192:]));reference_status='decoded'
            except ValueError:reference_errors=None;reference_status='acquisition_rejected'
            if name!='noise' and (errors or reference_errors):raise RuntimeError(f'Payload SER regression: {seed}/{name}')
            if name=='noise' and errors<=20:raise RuntimeError('Noise negative control returned payload truth')
            if name!='noise' and any(node['rail_values'] for node in metrics.values()):raise RuntimeError('Nominal channel clipped a DSP node')
            records.append(dict(seed=seed,case=name,payload_symbols=576,fixed_errors=errors,fixed_ser=errors/576,float_errors=reference_errors,float_status=reference_status,
                                delay_error_samples=acq['delay']/65536-params.get('delay',0),frequency_error_cycles_per_sample=acq['frequency']/2**32/8-params.get('frequency',0),nodes=metrics))
    return records


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/bpsk/precision_results.json')
    args=parser.parse_args()
    evidence=begin();target=args.output;write_json(target,dict(evidence,status='RUNNING'))
    records=report();write_json(target,dict(status='PASS',records=records,scope='Node SQNR at fixed loop states; final payload SER against independent original floating receiver; rail_values count values on saturation rails, not overflow events.',**finish(evidence)))
    for record in records:print(f"PASS BPSK {record['seed']}/{record['case']}: {record['fixed_errors']}/576 errors")

if __name__=='__main__':main()
