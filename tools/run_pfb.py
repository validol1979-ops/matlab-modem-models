#!/usr/bin/env python3
"""Integer polyphase bank reference, strict lint and Questa numeric scoreboard
(rtl/common/pfb_analysis.sv driven by rtl/tb/pfb_tb.sv)."""
import argparse
from pathlib import Path
import subprocess
import re
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_pass
from run_rtl import execute,SOURCES
from pfb_cases import vectors
from spectral_evidence import check_observers,negative_controls,check_embedded_fft,negative_fft_controls

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
DUT=ROOT/'rtl/common/pfb_analysis.sv'
# (LOG2M, LOG2LANES, LOG2TMAX, D, T)
CASES=[(2,2,6,4,33),(2,2,6,3,33),(2,0,6,3,33),(3,1,6,5,40),(4,4,7,16,64),(6,3,8,32,129),(2,1,2,1,3),(2,1,4,4,16)]
LINT_CASES=sorted({(m,l,t) for m,l,t,_,_ in CASES})
PASS=r'PASS PFB: (\d+) bins, (\d+) cycles'


def files(m):
    """Table files of one case as paths relative to the project root."""
    return dict(TWIDDLE_FILE=f'rtl/common/mem/fft_twiddle_{m}.mem')


def folder_for(base,index,m,d,t,log2lanes):
    return base/f'case{index}_m{m}_d{d}_t{t}_l{log2lanes}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl') and not DUT.is_file():
        raise RuntimeError(f'Missing DUT {DUT}: the pfb RTL is not written yet')
    output=ROOT/'build/rtl/pfb';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        for name in ('test_fft_fixed','test_pfb_fixed','test_pfb_width_sweep'):
            log=output/f'{name}.log';execute([sys.executable,ROOT/f'tests/{name}.py'],ROOT,log);artifacts.append(log)
        log=output/'fft_tables.log';execute([sys.executable,ROOT/'tools/fft_tables.py','--check'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for log2m,log2lanes,log2tmax in LINT_CASES:
            tables=files(1<<log2m)
            parameters=[f'-GLOG2M={log2m}',f'-GLOG2LANES={log2lanes}',f'-GLOG2TMAX={log2tmax}',
                        f'-GTWIDDLE_FILE="{tables["TWIDDLE_FILE"]}"']
            log=output/f'lint_pfb_analysis_{1<<log2m}_{log2lanes}_{log2tmax}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','pfb_analysis',*parameters,
                          f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: pfb_analysis M={1<<log2m} lanes={log2lanes} tmax={log2tmax}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        from run_stream_cfg_priority import run_group
        records['cfg_priority']=run_group('pfb',output/'cfg_priority',artifacts)
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,(log2m,log2lanes,log2tmax,d,taps) in enumerate(CASES):
            m=1<<log2m;folder=folder_for(base,index,m,d,taps,log2lanes)
            reports[index]=vectors(folder,log2m,d,taps,transactions=3,seed=31+index,stress=index==7)
        artifacts.extend(base.rglob('*.txt'))
        artifacts.extend(base.rglob('saturation.json'))
        artifacts.extend(base.rglob('fft_saturation.json'))
        for index,(log2m,log2lanes,log2tmax,d,taps) in enumerate(CASES):
            m=1<<log2m;folder=folder_for(base,index,m,d,taps,log2lanes);report=reports[index];tables=files(m)
            for active in (1,0):
                work=output/f'm{m}_d{d}_t{taps}_l{log2lanes}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/pfb_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.pfb_tb',f'-gLOG2M={log2m}',f'-gLOG2LANES={log2lanes}',
                        f'-gLOG2TMAX={log2tmax}',f'-gRESET_ACTIVE={active}',f'-gTWIDDLE_FILE={ROOT/tables["TWIDDLE_FILE"]}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['bins'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    artifacts.append(work/f'{scenario}.log')
                    check_observers(text,folder,'pfb')
                    check_embedded_fft(text,folder,('pfb',))
                if index==0:
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if '[NUMERIC]' not in negative or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    negative_controls(common,folder,work,artifacts,PASS)
                    negative_fft_controls(common,folder,work,artifacts,PASS)
                report['saturation_rtl_verified']=True;report['bounds_rtl_verified']=True
                report['embedded_fft_rtl_verified']=True
                records[f'm{m}_d{d}_t{taps}_l{log2lanes}_reset_{active}']=report
                print(f'PASS PFB M={m} D={d} T={taps} lanes={log2lanes} reset={active}',flush=True)
    if args.suite in ('all','hdl'):
        import json
        from pfb_width_sweep import check_acceptance
        path=ROOT/'build/rtl/pfb_width_sweep/rtl_results.json';log=output/'width_selection.log'
        execute([sys.executable,ROOT/'tools/pfb_width_sweep.py','--verify-rtl','--output',path],ROOT,log)
        report=json.loads(path.read_text());require_pass(report);check_acceptance(report)
        if not report['rtl_verified']:raise RuntimeError('Missing PFB accumulator RTL verification')
        records['width_selection']=dict(rtl_verified=True,result=str(path.relative_to(ROOT)),
            normal=len(report['rtl_equivalence']),parameters=len(report['rtl_parameters']),negative=len(report['rtl_negative']))
        artifacts.extend([path,log,*(ROOT/name for name in report['artifact_hashes'])])
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS PFB {args.suite}')

if __name__=='__main__':main()
