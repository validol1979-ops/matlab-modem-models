#!/usr/bin/env python3
"""MSK/GMSK integer reference, strict lint, Questa numeric scoreboards (cpm_tx, cpm_rx)."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths
from run_rtl import execute,SOURCES
from cpm_cases import vectors

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
CPM=ROOT/'rtl/modems/msk_modulator_2008_06_22'
PASS=r'PASS CPM receiver: (\d+) symbols, (\d+) acquisitions, (\d+) tx samples'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');parser.add_argument('--output',type=Path,help='new isolated output directory');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    output=args.output.resolve() if args.output else ROOT/'build/rtl/cpm';output.mkdir(parents=True,exist_ok=args.output is None)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_cpm_fixed.log';execute([sys.executable,ROOT/'tests/test_cpm_fixed.py'],ROOT,log);artifacts.append(log)
        log=output/'tables.log';execute([sys.executable,ROOT/'tools/bpsk_tables.py','--check'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for source in sorted(CPM.glob('*.sv')):
            for gmsk in ((0,1) if source.stem not in ('cpm_samples','cpm_coherent') else (None,)):
                top=source.stem;log=output/f'lint_{top}{"" if gmsk is None else f"_{gmsk}"}.log'
                text=execute(['verilator','--lint-only','-Wall','--top-module',top,*([f'-GGMSK={gmsk}'] if gmsk is not None else []),f'-I{PILOT}',*SOURCES],ROOT,log)
                if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top}')
                artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        reports={}
        for gmsk in (0,1):
            name='gmsk' if gmsk else 'msk';base=output/'vectors'/name
            reports[name]={'stream':vectors(base,bool(gmsk)),'loopback':vectors(base/'loopback',bool(gmsk),frames=3,loopback=True),
                           'minimum':vectors(base/'minimum',bool(gmsk),frames=1,count=192,seed=23),
                           'maximum':vectors(base/'maximum',bool(gmsk),frames=3,count=2048,seed=23)}
        artifacts.extend((output/'vectors').rglob('*.txt'))
        bindir,_=questa_paths()
        for active in (1,0):
            work=output/f'reset_{active}';work.mkdir(exist_ok=True)
            if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
            execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',*SOURCES,ROOT/'rtl/tb/cpm_tb.sv'],work,work/'compile.log')
            artifacts.append(work/'compile.log')
            for gmsk in (0,1):
                name='gmsk' if gmsk else 'msk';base=output/'vectors'/name
                common=[bindir/'vsim','-64','-c','-quiet','work.cpm_tb',f'-gRESET_ACTIVE={active}',f'-gGMSK={gmsk}',f'-gTABLE_DIR={PILOT/"tables"}']
                for scenario,folder,options,count in [('stream',base,[],768),('stalled',base,['+STALL_OUTPUT'],768),('loopback',base/'loopback',['+STALL_OUTPUT'],768),
                                                      ('minimum',base/'minimum',['+STALL_OUTPUT'],192),('maximum',base/'maximum',[],2048)]:
                    report=reports[name]['stream' if scenario in ('stream','stalled') else scenario];log=work/f'{name}_{scenario}.log'
                    text=execute([*common,f'-gSYMBOLS={count}',f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                    match=re.search(PASS,text)
                    if not match or tuple(map(int,match.groups()))!=(report['symbols'],report['frames'],report['tx_samples']) or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    artifacts.append(log)
                bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={base}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                negative=bad.stdout+bad.stderr;(work/f'{name}_negative.log').write_text(negative)
                if '[NUMERIC]' not in negative or re.search(PASS,negative):raise RuntimeError(f'{name} negative control not detected')
                artifacts.append(work/f'{name}_negative.log')
            records[f'reset_{active}']=dict(reports=reports,negative_control='PASS')
            print(f'PASS CPM reset={active}',flush=True)
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS CPM {args.suite}')

if __name__=='__main__':main()
