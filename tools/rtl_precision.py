#!/usr/bin/env python3
"""Initial ADC/sample quantization study; not a fixed-point receiver simulation."""
import argparse
import sys
import numpy as np
from regression_evidence import ROOT,begin,finish,write_json
sys.path.insert(0,str(ROOT/'common/python'))
from modem_core import load_config,frame_data,transmit,receive,channel


def quantize(values,width,integer_bits):
    frac=width-integer_bits
    components=np.array([np.real(values),np.imag(values)])
    raw=np.rint(components*(1<<frac))
    minimum=-(1<<(width-1));maximum=(1<<(width-1))-1
    overflow=int(np.count_nonzero((raw<minimum)|(raw>maximum)))
    raw=np.clip(raw,minimum,maximum)/(1<<frac)
    actual=raw[0]+1j*raw[1]
    signal=float(np.sum(abs(values)**2));error=float(np.sum(abs(actual-values)**2))
    return actual,dict(width=width,integer_bits=integer_bits,frac=frac,overflows=overflow,
                       sqnr_db=None if error==0 else float(10*np.log10(signal/error)))


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--modem');args=parser.parse_args()
    configs=sorted((ROOT/'modems').glob('*/config.json'))
    if args.modem:
        configs=[path for path in configs if path.parent.name==args.modem]
        if not configs:parser.error('Unknown modem')
    evidence=begin();output=ROOT/'build/rtl/precision';output.mkdir(parents=True,exist_ok=True)
    target=output/(args.modem+'.json' if args.modem else 'results.json')
    write_json(target,dict(evidence,status='RUNNING'));records=[]
    for path in configs:
        cfg=load_config(path);labels=frame_data(cfg,512);tx=transmit(cfg,labels)['waveform']
        for case,parameters in [('clean',{}),('impaired',dict(snr_db=30,gain=1.3,phase=.38,frequency=.00015,delay=2.25))]:
            wave=channel(cfg,tx,seed=3101,**parameters);reference=receive(cfg,wave,labels[:192],len(labels))
            peak=max(float(np.max(abs(wave.real))),float(np.max(abs(wave.imag))))
            integer_bits=max(2,int(np.floor(np.log2(max(peak,1e-12))))+2)
            for width in (12,14,16,18):
                actual,metric=quantize(wave,width,integer_bits)
                receiver=receive(cfg,actual,labels[:192],len(labels))
                metric.update(modem=cfg['name'],case=case,payload_symbols=len(labels)-192,
                              reference_errors=int(np.count_nonzero(reference['data'][192:]!=labels[192:])),
                              sample_quantization_errors=int(np.count_nonzero(receiver['data'][192:]!=labels[192:])))
                records.append(metric)
        print(f'PASS quantization study: {cfg["name"]}',flush=True)
    write_json(target,dict(status='PASS',records=records,scope='Quantized receiver input only; filters, acquisition and tracking retain real arithmetic. No full fixed-point SER or final width selection is claimed.',**finish(evidence)))


if __name__=='__main__':main()
