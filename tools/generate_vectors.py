#!/usr/bin/env python3
"""Создание воспроизводимых общих стимулов и эталонных результатов."""
from pathlib import Path
import argparse
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common' / 'python'))
from modem_core import load_config, frame_data, transmit, channel, receive, maximal_ratio_combine


def complex_lines(values):
    return ''.join(f'{z.real:.17g} {z.imag:.17g}\n' for z in values)


def config_text(cfg):
    enums = [dict(psk=0,qam=1,pi4=2,msk=3,gmsk=4,oqpsk=5)[cfg['family']], cfg['order'],
             dict(none=0,psk=1,quadrant=2,pi4=3)[cfg['differential']], cfg['sps'], cfg['rrc_order'],
             dict(feedforward=0,feedback=1,costas=2)[cfg['carrier']],
             dict(feedforward=0,gardner=1)[cfg['timing']], dict(none=0,linear=1,dfe=2)[cfg['equalizer']]]
    return (' '.join(map(str,enums)) + f' {cfg["rolloff"]} {cfg["gaussian_bt"]} {len(cfg["constellation"])}\n' +
                                   ''.join(f'{a:.17g} {b:.17g}\n' for a,b in cfg['constellation']))


def generate(config_path):
    cfg = load_config(config_path)
    dest = ROOT / 'build' / 'vectors' / cfg['name']
    dest.mkdir(parents=True, exist_ok=True)
    (dest / 'config.txt').write_text(config_text(cfg))
    cases = [{}, dict(snr_db=28,gain=.65,phase=.38,frequency=.00015,delay=2.25),
             dict(snr_db=32,gain=1.3,phase=-.9,frequency=-.0003,delay=7.25,
                  echo=.4 if cfg['equalizer']!='none' else 0,
                  drift=.0001 if cfg['variable_delay'] else 0,
                  phase_noise=.0002 if cfg['phase_noise'] else 0)]
    manifest=[]
    for index,case in enumerate(cases):
        data=frame_data(cfg,512,19+index)
        tx=transmit(cfg,data)
        wave=channel(cfg,tx['waveform'],seed=29+index,**case)
        branches=cfg['diversity_branches']
        gain_a,gain_b=.2+.3j,1-.4j
        if branches==2:
            rng=np.random.default_rng(871+index)
            noise=.004*(rng.normal(size=(2,len(wave)))+1j*rng.normal(size=(2,len(wave))))
            branch_a=gain_a*wave+noise[0]
            branch_b=gain_b*wave+noise[1]
            combined=maximal_ratio_combine([branch_a,branch_b],[gain_a,gain_b])
        else:
            branch_a=wave; branch_b=None; combined=wave
        rx=receive(cfg,combined,data[:192],len(data))
        errors=int(np.count_nonzero(rx['data'][192:]!=data[192:]))
        if errors: raise AssertionError(f'{cfg["name"]} case {index}: {errors} payload errors')
        content=f'{len(data)} {len(wave)} {len(tx["waveform"])} 192 {branches}\n'
        content+=''.join(f'{v}\n' for v in data)
        content+=complex_lines(branch_a)
        if branches==2:
            content+=complex_lines(branch_b)+complex_lines([gain_a,gain_b])
        content+=complex_lines(tx['waveform'])
        content+=''.join(f'{v}\n' for v in rx['data'])
        content+=complex_lines(rx['symbols'])+f'{rx["delay"]:.17g} {rx["frequency"]:.17g}\n'
        (dest/f'case_{index}.txt').write_text(content)
        manifest.append(dict(case=index,channel=case,payload_errors=errors,tx_samples=len(tx['waveform'])))
    (dest/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    return dest


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--modem')
    args=parser.parse_args()
    paths=[ROOT/'modems'/args.modem/'config.json'] if args.modem else sorted((ROOT/'modems').glob('*/config.json'))
    for path in paths:
        print(f'Generated {generate(path).relative_to(ROOT)}')
