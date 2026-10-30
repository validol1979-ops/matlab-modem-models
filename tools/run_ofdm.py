#!/usr/bin/env python3
"""Integer OFDM reference, strict lint and Questa numeric scoreboard
(rtl/modems/ofdm_awgn/ofdm_tx.sv + ofdm_rx.sv driven by rtl/tb/ofdm_tb.sv)."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths
from run_rtl import execute,SOURCES
from ofdm_cases import vectors
from spectral_evidence import check_observers,negative_controls,check_embedded_fft,negative_fft_controls

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
LINT_CASES=[(2,1),(5,8),(5,0),(6,16),(10,64),(3,8)]
CASES=[(5,8,12),(5,0,6),(6,16,8),(2,1,16),(10,64,3),(3,8,4)]
PASS=r'PASS OFDM: (\d+) tx samples, (\d+) rx symbols, (\d+) cycles'


def twiddle(log2n):return ROOT/f'rtl/common/mem/fft_twiddle_{1<<log2n}.mem'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    output=ROOT/'build/rtl/ofdm';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        for name in ('test_fft_fixed','test_ofdm_fixed'):
            log=output/f'{name}.log';execute([sys.executable,ROOT/f'tests/{name}.py'],ROOT,log);artifacts.append(log)
        log=output/'fft_tables.log';execute([sys.executable,ROOT/'tools/fft_tables.py','--check'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for log2n,cp in LINT_CASES:
            for top in ('ofdm_tx','ofdm_rx'):
                log=output/f'lint_{top}_{1<<log2n}_{cp}.log'
                text=execute(['verilator','--lint-only','-Wall','--top-module',top,f'-GLOG2N={log2n}',f'-GCP={cp}',
                              f'-GTWIDDLE_FILE="{twiddle(log2n).relative_to(ROOT)}"',f'-I{PILOT}',*SOURCES],ROOT,log)
                if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top} LOG2N={log2n} CP={cp}')
                artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for log2n,cp,frames in CASES:
            size=1<<log2n;folder=base/f'n{size}_cp{cp}'
            reports[(size,cp)]=vectors(folder,log2n,cp,frames=frames,seed=31+log2n+cp)
        artifacts.extend(base.rglob('*.txt'))
        artifacts.extend(base.rglob('saturation.json'))
        artifacts.extend(base.rglob('fft_saturation.json'))
        for log2n,cp,frames in CASES:
            size=1<<log2n;folder=base/f'n{size}_cp{cp}';report=reports[(size,cp)]
            for active in (1,0):
                work=output/f'n{size}_cp{cp}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/ofdm_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.ofdm_tb',f'-gLOG2N={log2n}',f'-gCP={cp}',
                        f'-gRESET_ACTIVE={active}',f'-gTWIDDLE_FILE={twiddle(log2n)}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['outputs'] or int(match.group(2))!=report['rx_outputs'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    artifacts.append(work/f'{scenario}.log')
                    check_observers(text,folder,'ofdm')
                    check_embedded_fft(text,folder,('ofdm_tx','ofdm_rx'))
                if (size,cp)==(32,8):
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if '[NUMERIC]' not in negative or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    negative_controls(common,folder,work,artifacts,PASS)
                    negative_fft_controls(common,folder,work,artifacts,PASS)
                report['saturation_rtl_verified']=True;report['bounds_rtl_verified']=True
                report['embedded_fft_rtl_verified']=True
                records[f'n{size}_cp{cp}_reset_{active}']=report
                print(f'PASS OFDM N={size} CP={cp} reset={active}',flush=True)
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS OFDM {args.suite}')

if __name__=='__main__':main()
