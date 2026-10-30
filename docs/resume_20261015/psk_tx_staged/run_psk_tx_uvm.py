#!/usr/bin/env python3
"""Full label and waveform UVM for every production PSK/QAM transmitter profile."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path('')
sys.path.insert(0,str(ROOT/'tools'))
import numpy as np
from regression_evidence import begin,finish,write_json,questa_paths,require_unoptimized
from run_rtl import SOURCES
from run_bpsk_uvm import PILOT,TX_SCENARIOS,parse_tx_report,verify_tx_negative
from run_oqpsk_uvm import CONTROLS
from bpsk_cases import p as fixed,save,rtl_parameters,CONFIGS

PROFILES={profile.name:profile for profile in fixed.PROFILES if profile is not fixed.BPSK}
TX_PARAMETERS=('ORDER','AMPLITUDE','DIFFERENTIAL','TX_AXIS','PI4')


def parameters(name):return {key:rtl_parameters(PROFILES[name])[key] for key in TX_PARAMETERS}


def prepare_vectors(folder,name):
    profile=PROFILES[name];folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    lengths=[1,2,33,192,768];rng=np.random.default_rng(19);inputs=[];outputs=[]
    for f,n in enumerate(lengths):
        labels=([0] if f==0 else [profile.alphabet-1,0] if f==1 else
                list(range(min(n,profile.alphabet)))+rng.integers(0,profile.alphabet,max(0,n-profile.alphabet)).tolist())
        wave=fixed.transmit(profile,labels)
        if len(labels)!=n or len(wave)!=8*n+32:raise RuntimeError('Independent PSK TX geometry')
        inputs.extend((int(value),int(k==n-1)) for k,value in enumerate(labels))
        outputs.extend((re,im,int(k==len(wave)-1)) for k,(re,im) in enumerate(wave))
    save(folder/'tx_symbols.txt',inputs);save(folder/'tx_out.txt',outputs)
    return dict(profile=name,frames=5,frame_symbols=lengths,input_symbols=len(inputs),output_samples=len(outputs),
                label_bits=(profile.alphabet-1).bit_length(),alphabet=profile.alphabet,labels_seen_mask=(1<<profile.alphabet)-1,
                tx_parameters=parameters(name),configuration='NOT_APPLICABLE: no runtime configuration ports',
                waveform='Unchanged psk_fixed.transmit, signed18 I/Q, independent8*N+32')


def parse_report(text,model,scenario,active,returncode=0):
    if type(active) is not int or active not in (0,1):raise RuntimeError('PSK reset polarity')
    row=parse_tx_report(text.replace('UVM PSK TX checked=','UVM BPSK TX checked='),model,scenario,active,returncode)
    name=model['profile'];profile=PROFILES[name]
    bits=(profile.alphabet-1).bit_length();mask=(1<<profile.alphabet)-1
    if model['tx_parameters']!=parameters(name) or model['label_bits']!=bits or model['labels_seen_mask']!=mask or model['alphabet']!=profile.alphabet:
        raise RuntimeError('PSK TX immutable profile metadata')
    if re.findall(r'UVM TX LABELS bits=(\d+) mask=(\d+)',text)!=[(str(bits),str(mask))]:
        raise RuntimeError('Complete PSK/QAM label alphabet required, including bit63 of QAM64 mask')
    observed=re.findall(r'UVM PSK TX PARAMETERS order=(\d+) amplitude=(\d+) differential=(\d+) axis=(\d+) pi4=(\d+)',text)
    if observed!=[tuple(str(parameters(name)[key]) for key in TX_PARAMETERS)]:raise RuntimeError('Actual TX mapper parameters mismatch')
    row.update(profile=name+'_tx',label_bits=bits,labels_seen_mask=mask,tx_parameters=parameters(name))
    return row


def run_profile(output,name):
    folder=output/(name+'_vectors');model=prepare_vectors(folder,name);records={};artifacts=list(folder.glob('*.txt'))
    bindir,uvm=questa_paths()
    def run(cmd,work,file):
        result=subprocess.run([str(x) for x in cmd],cwd=work,capture_output=True,text=True,timeout=90)
        text=result.stdout+result.stderr;log=work/file;log.write_text(text);artifacts.append(log)
        return result.returncode,text
    for active in (1,0):
        work=output/f'{name}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():
            rc,text=run([bindir/'vlib','work'],work,'vlib.log')
            if rc:raise RuntimeError('PSK TX vlib: '+text[-2000:])
        defines=['+define+UVM_NO_DPI',f'+define+PSK_LABEL_BITS={model["label_bits"]}']
        defines.extend(f'+define+PSK_{key}={value}' for key,value in model['tx_parameters'].items())
        if not active:defines.append('+define+RTL_RESET_LOW')
        rc,text=run([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',
                     f'+incdir+{Path(__file__).resolve().parent}',uvm/'src/uvm_pkg.sv',*SOURCES,Path(__file__).with_name('psk_tx_uvm_tb.sv')],work,'compile.log')
        if rc or re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):raise RuntimeError('PSK TX compile failed/warned: '+text[-6000:])
        positive,negative=work/'run.do',work/'negative.do'
        positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.psk_tx_uvm_top',f'+VECTORS={folder}']
        for scenario in TX_SCENARIOS:
            rc,text=run([*base,f'+SCENARIO={scenario}','-do',positive.name],work,scenario+'.log')
            records[f'{name}_{scenario}_reset_{active}']=parse_report(text,model,scenario,active,rc)
        for key,(tag,flag,scenario) in CONTROLS.items():
            rc,text=run([*base,f'+SCENARIO={scenario}','+'+flag,'-do',negative.name],work,'negative_'+key+'.log')
            verify_tx_negative(text,rc,tag,modulation='PSK');records[f'{name}_negative_{key}_reset_{active}']=dict(returncode=rc,detected_tag=tag)
        records[f'{name}_model_reset_{active}']=model
    print('PASS PSK/QAM TX UVM '+name,flush=True)
    return records,artifacts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=('python','hdl','all'),default='all')
    parser.add_argument('--profile',choices=('all',*PROFILES),default='all');parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args();require_unoptimized()
    if not 1<=args.jobs<=4:parser.error('--jobs must be1..4')
    output=ROOT/'build/rtl/psk_tx_uvm';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/(('' if args.profile=='all' else args.profile+'_')+args.suite+'_results.json')
    records,artifacts={},[];write_json(target,dict(evidence,status='RUNNING'))
    try:
        if args.suite in ('python','all'):
            result=subprocess.run([sys.executable,ROOT/'tests/test_psk_tx_uvm.py'],cwd=ROOT,capture_output=True,text=True)
            log=output/'python.log';log.write_text(result.stdout+result.stderr);artifacts.append(log)
            if result.returncode:raise RuntimeError('PSK TX Python tests failed: '+log.read_text()[-6000:])
            records['python']='PASS'
        if args.suite in ('hdl','all'):
            selected=[name for name in PROFILES if args.profile in ('all',name)]
            pool=ThreadPoolExecutor(max_workers=min(args.jobs,len(selected)))
            futures=[pool.submit(run_profile,output,name) for name in selected]
            try:
                for future in as_completed(futures):
                    child,files=future.result();records.update(child);artifacts.extend(files)
            except Exception:
                for future in futures:future.cancel()
                raise
            finally:pool.shutdown(wait=True,cancel_futures=True)
        write_json(target,dict(finish(evidence,sorted(set(artifacts))),status='PASS',profiles=args.profile,records=records,
                               scope='All13 PSK/QAM bpsk_tx profiles, physical mapper parameters, complete label alphabets including QAM64 bit63, signed18 I/Q, accepted inputs/outputs, gaps/backpressure, partial and terminal reset.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise
    print('PASS PSK/QAM TX UVM '+args.suite)


if __name__=='__main__':main()
