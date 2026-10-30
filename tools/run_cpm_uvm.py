#!/usr/bin/env python3
"""MSK/GMSK TX UVM with exact sample geometry and pending-output reset accounting."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

from regression_evidence import ROOT, begin, finish, write_json, questa_paths, require_unoptimized
from run_rtl import SOURCES
from run_bpsk_uvm import PILOT, TX_SCENARIOS, parse_tx_report, verify_tx_negative
from run_oqpsk_uvm import CONTROLS
from cpm_cases import c, save

PROFILES=('msk','gmsk')


def prepare_vectors(folder,profile):
    if profile not in PROFILES:
        raise ValueError('Unsupported CPM transmitter')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    lengths=[1,2,33,192,768];rng=np.random.default_rng(19)
    inputs,outputs=[],[];tail=32 if profile=='gmsk' else 0
    for frame,count in enumerate(lengths):
        bits=[0] if frame==0 else [1,0] if frame==1 else rng.integers(0,2,count).tolist()
        wave=c.transmit(bits,profile=='gmsk')
        if len(wave)!=8*count+tail:
            raise RuntimeError('CPM production TX differs from independent frame geometry')
        inputs.extend((int(bit),int(k==count-1)) for k,bit in enumerate(bits))
        outputs.extend((re,im,int(k==len(wave)-1)) for k,(re,im) in enumerate(wave))
    save(folder/'tx_symbols.txt',inputs);save(folder/'tx_out.txt',outputs)
    return dict(profile=profile,frames=5,frame_symbols=lengths,input_symbols=len(inputs),
                output_samples=len(outputs),samples_per_symbol=8,tail=tail,label_bits=1,
                waveform='Production cpm_fixed.transmit; frame restarts its phase at0',
                configuration='NOT_APPLICABLE: CPM_TX has no configuration ports')


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=('python','hdl','all'),default='all')
    parser.add_argument('--profile',choices=('all',*PROFILES),default='all')
    args=parser.parse_args();require_unoptimized()
    output=ROOT/'build/rtl/cpm_uvm';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/(('' if args.profile=='all' else args.profile+'_')+args.suite+'_results.json')
    artifacts,records=[],{}
    write_json(target,dict(evidence,status='RUNNING'))
    try:
        def run(command,work,name):
            result=subprocess.run([str(x) for x in command],cwd=work,capture_output=True,text=True,timeout=90)
            text=result.stdout+result.stderr;log=work/name;log.write_text(text);artifacts.append(log)
            return result.returncode,text
        if args.suite in ('python','all'):
            rc,text=run([sys.executable,ROOT/'tests/test_cpm_uvm.py'],output,'python.log')
            if rc:raise RuntimeError('CPM TX evidence tests failed: '+text[-6000:])
            records['python']='PASS'
        if args.suite in ('hdl','all'):
            bindir,uvm=questa_paths()
            for profile in PROFILES:
                if args.profile not in ('all',profile):continue
                folder=output/(profile+'_vectors');model=prepare_vectors(folder,profile)
                artifacts.extend(folder.glob('*.txt'))
                for active in (1,0):
                    work=output/f'{profile}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                    if not (work/'work').is_dir():
                        rc,text=run([bindir/'vlib','work'],work,'vlib.log')
                        if rc:raise RuntimeError('CPM TX vlib failed: '+text[-2000:])
                    defines=['+define+UVM_NO_DPI',f'+define+TX_GMSK={int(profile=="gmsk")}']
                    if not active:defines.append('+define+RTL_RESET_LOW')
                    rc,text=run([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',
                                 f'+incdir+{ROOT/"rtl/tb"}',uvm/'src/uvm_pkg.sv',*SOURCES,ROOT/'rtl/tb/cpm_tx_uvm_tb.sv'],work,'compile.log')
                    if rc or re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):
                        raise RuntimeError('CPM TX compile failed/warned: '+text[-6000:])
                    positive,negative=work/'run.do',work/'negative.do'
                    positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
                    negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.extend([positive,negative])
                    base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),
                          'work.cpm_tx_uvm_top',f'-gTABLE_DIR={PILOT/"tables"}',f'+VECTORS={folder}']
                    for scenario in TX_SCENARIOS:
                        rc,text=run([*base,f'+SCENARIO={scenario}','-do',positive.name],work,scenario+'.log')
                        records[f'{profile}_{scenario}_reset_{active}']=parse_tx_report(text,model,scenario,active,rc,modulation=profile.upper())
                        print(f'PASS UVM TX {profile} {scenario} reset={active}',flush=True)
                    for key,(tag,flag,scenario) in CONTROLS.items():
                        rc,text=run([*base,f'+SCENARIO={scenario}','+'+flag,'-do',negative.name],work,'negative_'+key+'.log')
                        verify_tx_negative(text,rc,tag,modulation=profile.upper())
                        records[f'{profile}_negative_{key}_reset_{active}']=dict(returncode=rc,detected_tag=tag)
                    records[f'{profile}_model_reset_{active}']=model
        write_json(target,dict(finish(evidence,artifacts),status='PASS',profiles=args.profile,records=records,
                               scope='Full MSK/GMSK TX UVM: I/Q production waveform, actual accepted bits/samples, independent8*N or8*N+32 geometry, gaps/backpressure and partial/terminal resets.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'))
        raise
    print('PASS CPM TX UVM '+args.suite)


if __name__=='__main__':main()
