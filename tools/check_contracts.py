#!/usr/bin/env python3
"""Проверяем приём допустимых границ и отказ до вычислений на неверных входах."""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT, begin, finish, write_json, questa_paths, mquote
sys.path.insert(0,str(ROOT/'common/python'))
import numpy as np
from research_core import run,OPERATIONS


def fixtures():
    invalid=[('short_'+op,op,[2,.1,.01],[1,2,3],[1]) for op in ('lms','nlms','rls')]
    invalid += [
        ('ldpc_zero_iterations','ldpc',[1,2,0,0,.8,.15],[2,2],[1,1]),
        ('ldpc_degree_one','ldpc',[1,2,2,1],[2,2],[1,0]),
        ('ldpc_missing_parameters','ldpc',[1,2,2],[2,2],[1,1]),
        ('fractional_bank','pfb',[2.6,1],[1,2],[1]),
        ('zero_decimation','pfb',[2,0],[1,2],[1]),
        ('short_stft','stft',[8,2],[1,2],[]),
        ('zero_hop','stft',[2,0],[1,2],[]),
        ('short_omlsa','omlsa',[8,2,1,.92],[1]*4,[]),
        ('excess_noise_frames','omlsa',[8,2,100,.92],[1]*16,[]),
        ('beamform_dimensions','beamform',[2],[1,2],[1]),
        ('fractional_timing','timing',[2.6,2,0,.1,.01],[1]*16,[]),
        ('partial_fsk','fsk_rx',[8,1,2,4],[1]*9,[]),
        ('invalid_cp','ofdm_tx',[2,3],[1,2],[]),
        ('single_sinc','wsinc',[1,.1],[0],[]),
        ('unknown_operation',99,[],[1],[]),
        ('empty_fir','fir',[],[1],[]),
        ('empty_signal','dft',[0],[],[]),
        ('singular_mimo','mimo',[2,0],[1,2],[1,1,1,1]),
        ('tiny_beamform','beamform',[1],[1],[1e-160]),
        ('tiny_alamouti','alamouti',[],[1,1],[1e-160,0]),
        ('overflow_ofdm_rx','ofdm_rx',[2147483647,2147483647],[1],[]),
        ('nan_parameter','dft',[np.nan],[1],[]),
        ('infinite_signal','dft',[0],[np.inf],[]),
        ('nan_auxiliary','fir',[],[1],[complex(0,np.nan)]),
        ('nonbinary_encoder','gf2_encode',[1,2],[2,1],[1,1]),
    ]
    valid=[('ldpc_defaults_'+str(mode),'ldpc',[1,2,2,mode],[2,2],[1,1]) for mode in (0,1,2)]
    valid += [('ldpc_beta_default','ldpc',[1,2,2,3,.8],[2,2],[1,1]),
              ('minimum_omlsa','omlsa',[8,2,1,.92],[1]*9,[]),
              ('minimum_stft','stft',[2,2],[1,2],[]),
              ('regularized_mimo','mimo',[2,.1],[1,2],[1,1,1,1]),
              ('zero_prefix','ofdm_tx',[2,0],[1,2],[])]
    return [(False,c) for c in invalid]+[(True,c) for c in valid]


def vectors(path):
    rows=[str(len(fixtures()))]
    for accepted,(name,op,p,x,a) in fixtures():
        if accepted: y=run(op,p,x,a)
        else:
            try: run(op,p,x,a)
            except ValueError as error:
                if 'Invalid DSP' not in str(error): raise RuntimeError(f'Unexpected rejection: {name}') from error
            else: raise AssertionError(f'Invalid input accepted: {name}')
            y=[]
        opid=OPERATIONS.index(op) if isinstance(op,str) else op
        rows.append(f'{int(accepted)} {opid} {len(p)} {len(x)} {len(a)} {len(y)}')
        rows.extend(str(v) for v in p)
        for arr in (x,a,y):rows.extend(f'{complex(z).real:.17g} {complex(z).imag:.17g}' for z in arr)
    path.write_text('\n'.join(rows)+'\n')


def main():
    if not __debug__: raise RuntimeError('Run verification without Python optimization (-O)')
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','octave','matlab','hdl','all'],default='all');args=parser.parse_args()
    evidence=begin();output=ROOT/'build/contracts';output.mkdir(parents=True,exist_ok=True)
    write_json(output/f'{args.suite}_results.json',{'status':'RUNNING',**evidence})
    path=output/'vectors.txt';vectors(path)
    result={'status':'PASS','cases':len(fixtures()),'rejections':sum(not v for v,_ in fixtures()),'python':'PASS'}
    if args.suite in ('octave','matlab','all'):
        script=f"addpath('{mquote(ROOT/'common/octave')}'); research_contract_check('{mquote(path)}');"
        if args.suite=='matlab':
            subprocess.run([str(ROOT/'tools/matlab.sh'),'-nodisplay','-batch',script,'-logfile',str(output/'matlab.log')],check=True)
            result['matlab']='PASS'
        else:
            completed=subprocess.run(['octave-cli','--quiet','--eval',script],capture_output=True,text=True)
            (output/'octave.log').write_text(completed.stdout+completed.stderr)
            if completed.returncode: raise RuntimeError(completed.stdout+completed.stderr)
            result['octave']='PASS'
    if args.suite in ('hdl','all'):
        bindir,_=questa_paths();work=output/'questa';work.mkdir(exist_ok=True)
        def execute(cmd,name):
            r=subprocess.run([str(x) for x in cmd],cwd=work,capture_output=True,text=True)
            text=r.stdout+r.stderr;(work/name).write_text(text)
            return r,text
        if not (work/'work').exists():
            r,t=execute([bindir/'vlib','work'],'vlib.log');r.check_returncode()
        r,t=execute([bindir/'vlog','-64','-sv',f'+incdir+{ROOT/"common/sv"}',ROOT/'common/sv/modem_dsp_pkg.sv',ROOT/'common/sv/research_dsp_pkg.sv',ROOT/'common/sv/research_contract_tb.sv'],'compile.log')
        if r.returncode: raise RuntimeError(t)
        for index,(accepted,(name,*_)) in enumerate(fixtures()):
            r,t=execute([bindir/'vsim','-64','-c','-quiet','work.research_contract_tb',f'+VECTORS={path}',f'+CASE={index}','-do','onerror {quit -code 1}; run -all; quit -code 0'],name+'.log')
            if accepted:
                if r.returncode or 'CONTRACT_ACCEPTED' not in t or '** Error' in t or '** Fatal' in t: raise RuntimeError(t)
            elif 'Invalid DSP' not in t or 'INVALID_ACCEPTED' in t or '** Fatal' not in t:
                raise RuntimeError(f'Input rejection was not observed: {name}\n{t}')
        result['hdl']='PASS'
    artifacts=[path]
    if args.suite in ('octave','all'): artifacts.append(output/'octave.log')
    if args.suite=='matlab': artifacts.append(output/'matlab.log')
    if args.suite in ('hdl','all'): artifacts.extend(sorted(work.glob('*.log')))
    result.update(finish(evidence,artifacts));write_json(output/f'{args.suite}_results.json',result)
    print(f'PASS {args.suite}: {result["cases"]} boundary cases, {result["rejections"]} expected rejections')

if __name__=='__main__':main()
