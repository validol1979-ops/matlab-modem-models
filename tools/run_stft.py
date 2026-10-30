#!/usr/bin/env python3
"""Integer STFT reference, strict lint and Questa numeric scoreboard
(rtl/common/stft_analysis.sv + stft_synthesis.sv driven by rtl/tb/stft_tb.sv)."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_pass
from run_rtl import execute,SOURCES
from stft_cases import vectors
from spectral_evidence import check_observers,negative_controls

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
DUTS=(ROOT/'rtl/common/stft_analysis.sv',ROOT/'rtl/common/stft_synthesis.sv')
LINT_CASES=[(2,0),(5,3),(5,5),(6,4),(6,5),(8,6),(3,1)]
CASES=[(2,0,4),(5,3,4),(5,5,4),(6,4,4),(6,5,4),(8,6,2),(3,1,2)]
PASS=r'PASS STFT: (\d+) spectra, (\d+) samples, (\d+) cycles'


def files(log2n,log2hop):
    """Table files of one case as paths relative to the project root."""
    n=1<<log2n
    return dict(TWIDDLE_FILE=f'rtl/common/mem/fft_twiddle_{n}.mem',
                WINDOW_FILE=f'rtl/common/mem/stft_window_{n}.mem',
                RECIP_FILE=f'rtl/common/mem/stft_recip_{n}_{1<<log2hop}.mem')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl'):
        for log2n,log2hop,_ in CASES:
            for table in files(log2n,log2hop).values():
                if not (ROOT/table).is_file():raise RuntimeError(f'Missing STFT ROM: {table}')
    if args.suite in ('all','hdl'):
        for dut in DUTS:
            if not dut.is_file():raise RuntimeError(f'Missing DUT {dut}: the stft RTL is not written yet')
    output=ROOT/'build/rtl/stft';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        for name in ('test_fft_fixed','test_stft_fixed','test_istft_width_sweep'):
            log=output/f'{name}.log';execute([sys.executable,ROOT/f'tests/{name}.py'],ROOT,log);artifacts.append(log)
        log=output/'fft_tables.log';execute([sys.executable,ROOT/'tools/fft_tables.py','--check'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for log2n,log2hop in LINT_CASES:
            tables=files(log2n,log2hop)
            for top in ('stft_analysis','stft_synthesis'):
                parameters=[f'-GLOG2N={log2n}',f'-GLOG2HOP={log2hop}',f'-GTWIDDLE_FILE="{tables["TWIDDLE_FILE"]}"',
                            f'-GWINDOW_FILE="{tables["WINDOW_FILE"]}"']
                if top=='stft_synthesis':parameters.append(f'-GRECIP_FILE="{tables["RECIP_FILE"]}"')
                log=output/f'lint_{top}_{1<<log2n}_{1<<log2hop}.log'
                text=execute(['verilator','--lint-only','-Wall','--top-module',top,*parameters,
                              f'-I{PILOT}',*SOURCES],ROOT,log)
                if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top} LOG2N={log2n} LOG2HOP={log2hop}')
                artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for log2n,log2hop,transactions in CASES:
            n=1<<log2n;hop=1<<log2hop;folder=base/f'n{n}_hop{hop}'
            reports[(n,hop)]=vectors(folder,log2n,log2hop,transactions=transactions,seed=31+log2n+log2hop,stress=log2n==3)
        artifacts.extend(base.rglob('*.txt'))
        artifacts.extend(base.rglob('saturation.json'))
        for log2n,log2hop,transactions in CASES:
            n=1<<log2n;hop=1<<log2hop;folder=base/f'n{n}_hop{hop}';report=reports[(n,hop)];tables=files(log2n,log2hop)
            for active in (1,0):
                work=output/f'n{n}_hop{hop}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/stft_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.stft_tb',f'-gLOG2N={log2n}',f'-gLOG2HOP={log2hop}',
                        f'-gRESET_ACTIVE={active}',f'-gTWIDDLE_FILE={ROOT/tables["TWIDDLE_FILE"]}',
                        f'-gWINDOW_FILE={ROOT/tables["WINDOW_FILE"]}',f'-gRECIP_FILE={ROOT/tables["RECIP_FILE"]}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['spectra'] or int(match.group(2))!=report['samples'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    artifacts.append(work/f'{scenario}.log')
                    check_observers(text,folder,'stft')
                if (n,hop)==(64,16):
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if '[NUMERIC]' not in negative or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    negative_controls(common,folder,work,artifacts,PASS)
                report['saturation_rtl_verified']=True;report['bounds_rtl_verified']=True
                records[f'n{n}_hop{hop}_reset_{active}']=report
                print(f'PASS STFT N={n} HOP={hop} reset={active}',flush=True)
    if args.suite in ('all','hdl'):
        import json
        from istft_width_sweep import check_acceptance
        path=ROOT/'build/rtl/istft_width_sweep/rtl_results.json';log=output/'width_selection.log'
        execute([sys.executable,ROOT/'tools/istft_width_sweep.py','--verify-rtl','--output',path],ROOT,log)
        report=json.loads(path.read_text());require_pass(report);check_acceptance(report)
        if not report['rtl_verified']:raise RuntimeError('Missing ISTFT width RTL evidence')
        records['width_selection']=dict(rtl_verified=True,result=str(path.relative_to(ROOT)),
            normal=len(report['rtl_equivalence']),parameters=len(report['rtl_parameters']),negative=len(report['rtl_negative']))
        artifacts.extend([path,log,*(ROOT/name for name in report['artifact_hashes'])])
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS STFT {args.suite}')

if __name__=='__main__':main()
