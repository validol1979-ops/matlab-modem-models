#!/usr/bin/env python3
"""Run typed algorithm tests and actual cross-language/UVM comparisons."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from datetime import datetime,timezone
import numpy as np
from research_cases import cases,ROOT
from regression_evidence import begin, finish, write_json, questa_paths, require_numeric_failure, mquote


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def execute(command,directory,log):
    result=subprocess.run([str(x) for x in command],cwd=directory,capture_output=True,text=True)
    log.write_text(result.stdout+result.stderr)
    if result.returncode:
        print((result.stdout+result.stderr)[-14000:]);raise RuntimeError(f'Command failed ({result.returncode}): {command[0]}')
    return result.stdout+result.stderr


def generate(selected,output):
    content=[str(len(selected))]
    for c in selected:
        content.append(f"{c['operation_id']} {len(c['parameters'])} {len(c['x'])} {len(c['a'])} {len(c['y'])}")
        content.extend(f'{v:.17g}' for v in c['parameters'])
        for key in ('x','a','y'):content.extend(f'{v.real:.17g} {v.imag:.17g}' for v in c[key])
    (output/'vectors.txt').write_text('\n'.join(content)+'\n')
    for i,c in enumerate(selected):
        np.savez_compressed(output/f'case_{i:03}.npz',**{key:c[key] for key in ('parameters','x','a','y')},truth=c.get('truth',np.array([])))
    return output/'vectors.txt'


def main():
    if not __debug__: raise RuntimeError("Run verification without Python optimization (-O)")
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','octave','matlab','hdl','all'],default='all');parser.add_argument('--workspace')
    args=parser.parse_args();evidence=begin();selected=[c for c in cases() if not args.workspace or c['workspace']==args.workspace]
    if not selected:parser.error('No cases match the workspace')
    output=ROOT/'build/typed';output=output/args.workspace.replace('/','__') if args.workspace else output
    output.mkdir(parents=True,exist_ok=True)
    write_json(output/f'{args.suite}_results.json',{'status':'RUNNING',**evidence})
    if args.suite=='all':
        for lang in ('octave','hdl'): write_json(output/f'{lang}_results.json',{'status':'RUNNING',**evidence})
    vectors=generate(selected,output)
    manifest=[]
    for i,c in enumerate(selected):
        manifest.append({k:v for k,v in c.items() if k not in ('parameters','x','a','y','truth')} | {'case':i,'input_values':len(c['x']),'output_values':len(c['y']),'capture_sha256':sha(output/f'case_{i:03}.npz'),'python_status':'PASS'})
    (output/'cases.json').write_text(json.dumps(manifest,indent=2)+'\n')
    summary={'checked_at_utc':datetime.now(timezone.utc).isoformat(),'suite':args.suite,'cases':len(selected),'workspaces':len({c['workspace'] for c in selected}),'python':'PASS','vectors_sha256':sha(vectors)}
    mcommand=f"addpath('{mquote(ROOT/'common/octave')}'); research_check('{mquote(vectors)}','{mquote(output/('matlab_cases.json' if args.suite=='matlab' else 'octave_cases.json'))}');"
    if args.suite in ('octave','all'):
        text=execute(['octave-cli','--quiet','--eval',mcommand],ROOT,output/'octave.log');print(text.strip())
        summary['octave']=json.loads((output/'octave_cases.json').read_text())
    if args.suite=='matlab':
        # Процесс наследует терминал: R2020b на этом хосте возвращает 129 без него.
        subprocess.run([str(ROOT/'tools/matlab.sh'),'-nodisplay','-batch',mcommand,'-logfile',str(output/'matlab.log')],cwd=ROOT,check=True)
        summary['matlab']=json.loads((output/'matlab_cases.json').read_text())
    if args.suite in ('hdl','all'):
        bindir,uvm=questa_paths()
        work=output/'questa';work.mkdir(exist_ok=True)
        if not (work/'work').exists():execute([bindir/'vlib','work'],work,work/'vlib.log')
        variant=[]
        if args.workspace:
            directory=ROOT/args.workspace if args.workspace.startswith('modems/') else ROOT/'algorithms'/args.workspace
            variant=['+define+TYPED_VARIANT',directory/'sv/model.sv']
        execute([bindir/'vlog','-64','-sv','-work','work','+define+UVM_NO_DPI',f'+incdir+{uvm/"src"}',f'+incdir+{ROOT/"common/sv"}',uvm/'src/uvm_pkg.sv',ROOT/'common/sv/modem_dsp_pkg.sv',ROOT/'common/sv/research_dsp_pkg.sv',ROOT/'common/sv/research_tb.sv',*variant],work,work/'compile.log')
        base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.research_tb',f'+VECTORS={vectors}']
        text=execute(base+['-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/'simulation.log')
        match=re.search(r'Checked (\d+) DSP transactions, (\d+) complex values; maximum error ([\deE.+-]+)',text)
        if not match or not re.search(r'UVM_ERROR\s*:\s*0',text) or not re.search(r'UVM_FATAL\s*:\s*0',text) or re.search(r'\*\* (Error|Fatal)',text):
            print(text[-16000:]);raise RuntimeError('UVM scoreboard failed')
        summary['hdl']={'status':'PASS','transactions':int(match[1]),'values':int(match[2]),'maximum_error':float(match[3])}
        if int(match[1])!=2*len(selected): raise RuntimeError('Incomplete UVM transaction coverage')
        negative=subprocess.run([str(x) for x in base+['+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
        bad=negative.stdout+negative.stderr;(work/'negative_control.log').write_text(bad)
        require_numeric_failure(bad)
        summary['hdl']['negative_control']='PASS'
        print(f'PASS UVM {match[1]} transactions, {match[2]} values, maximum error {match[3]}; injected mismatch detected')
    artifacts=[vectors,output/'cases.json',*sorted(output.glob('case_*.npz'))]
    if args.suite in ('octave','all'): artifacts += [output/'octave.log',output/'octave_cases.json']
    if args.suite=='matlab': artifacts += [output/'matlab.log',output/'matlab_cases.json']
    if args.suite in ('hdl','all'): artifacts += [work/'compile.log',work/'simulation.log',work/'negative_control.log']
    summary.update(finish(evidence,artifacts))
    summary['status']='PASS';write_json(output/f'{args.suite}_results.json',summary)
    if args.suite=='all':
        for language in ('octave','hdl'):
            write_json(output/f'{language}_results.json',dict(summary,suite=language))
    print(f'PASS {args.suite}: {len(selected)} cases in {summary["workspaces"]} typed workspaces')


if __name__=='__main__':main()
