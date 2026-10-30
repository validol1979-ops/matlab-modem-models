#!/usr/bin/env python3
"""2x2 MMSE / zero-forcing reference, strict lint and Questa numeric scoreboard
(rtl/common/mmse2.sv driven by rtl/tb/mmse_tb.sv)."""
import argparse
from pathlib import Path
import subprocess
import re
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths
from run_rtl import execute,SOURCES
from mmse_cases import vectors

DUT=ROOT/'rtl/common/mmse2.sv'
CASES=['zf','mmse','random','strong','tinyidentity']
NEGATIVE='zf'                                            # +INJECT_MISMATCH and +SINGULAR run on 'zf'
PASS=r'PASS MMSE: (\d+) outputs, (\d+) cycles'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def folder_for(base,index,case):
    return base/f'case{index}_{case}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl') and not DUT.is_file():
        raise RuntimeError(f'Missing DUT {DUT}: the mmse RTL is not written yet')
    output=ROOT/'build/rtl/mmse';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_mmse_fixed.log';execute([sys.executable,ROOT/'tests/test_mmse_fixed.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        log=output/'lint_mmse2.log'
        text=execute(['verilator','--lint-only','-Wall','--top-module','mmse2',f'-I{PILOT}',*SOURCES],ROOT,log)
        if '%Warning' in text:raise RuntimeError('Lint warnings: mmse2')
        artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,case in enumerate(CASES):
            folder=folder_for(base,index,case)
            reports[index]=vectors(folder,case,transactions=3,seed=37+index)
        artifacts.extend([*base.rglob('*.txt'),*base.rglob('saturation.json')])
        for index,case in enumerate(CASES):
            folder=folder_for(base,index,case);report=reports[index]
            for active in (1,0):
                work=output/f'{case}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/mmse_tb.sv',ROOT/'rtl/tb/mmse_protocol_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet',f'work.mmse_tb',f'-gRESET_ACTIVE={active}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['outputs'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    sat_match=re.search(r'PASS SATURATION mmse: (\d+) evaluations, (\d+) events',text)
                    if not sat_match or tuple(map(int,sat_match.groups()))!=(2*report['outputs'],report['saturation']['total']):
                        raise RuntimeError('Missing or mismatched MMSE saturation verification')
                    if not re.search(r'PASS BOUNDS mmse: [1-9]\d* checks',text):
                        raise RuntimeError('Missing MMSE bounds verification')
                    artifacts.append(work/f'{scenario}.log')
                if case in (NEGATIVE,'tinyidentity'):
                    numeric_do=work/'negative_numeric.do'
                    numeric_do.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do',numeric_do.name]],cwd=work,capture_output=True,text=True,timeout=90)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if bad.returncode==0 or not re.search(r'\*\* Fatal:.*\[NUMERIC\]',negative) or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.extend([work/'negative.log',numeric_do])
                    text=execute([*common,f'+VECTORS={folder}','+SINGULAR','-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/'singular.log')
                    if 'PASS MMSE SINGULAR' not in text or re.search(r'\*\* (?:Error|Fatal)',text):raise RuntimeError(text[-6000:])
                    artifacts.append(work/'singular.log')
                    if case==NEGATIVE:
                        text=execute([*common,f'+VECTORS={folder}','+COEFFICIENT_OVERFLOW','-do',
                                      'onerror {quit -code 1}; run -all; quit -code 0'],work,work/'coefficient_overflow.log')
                        if 'PASS MMSE COEFFICIENT_OVERFLOW' not in text or re.search(r'\*\* (?:Error|Fatal)',text):
                            raise RuntimeError('MMSE coefficient overflow rejection failed')
                        artifacts.append(work/'coefficient_overflow.log')
                        for protocol_case in (1,2,3,4):
                            log=work/f'protocol_{protocol_case}.log'
                            text=execute([bindir/'vsim','-64','-c','-quiet','work.mmse_protocol_tb',
                                          f'-gRESET_ACTIVE={active}',f'-gCASE_ID={protocol_case}','-do',
                                          'onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                            expected=f'PASS MMSE PROTOCOL case={protocol_case} reset={active}'
                            if expected not in text or re.search(r'\*\* (?:Error|Fatal)',text):
                                raise RuntimeError(f'MMSE protocol probe {protocol_case} failed')
                            artifacts.append(log)
                    for control,flag,tag in [('negative_saturation','+INJECT_SAT_MISMATCH','SATURATION'),
                                             ('negative_evaluations','+INJECT_SAT_EVAL_MISMATCH','SATURATION'),
                                             ('negative_bounds','+INJECT_BOUND_MISMATCH','BOUNDS')]:
                        bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',flag,'-do',numeric_do.name]],cwd=work,capture_output=True,text=True,timeout=90)
                        negative=bad.stdout+bad.stderr;(work/f'{control}.log').write_text(negative)
                        if not bad.returncode or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',negative) or re.search(PASS,negative):
                            raise RuntimeError(f'{control} control not detected')
                        artifacts.append(work/f'{control}.log')
                records[f'{case}_reset_{active}']=dict(report,saturation_rtl_verified=True,bounds_verified=True,
                                                      protocol_verified=(case==NEGATIVE))
                print(f'PASS MMSE {case} reset={active} rails={report["rails"]} '
                      f"bound={report['bound']} overload={report['overload']}",flush=True)
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS MMSE {args.suite}')

if __name__=='__main__':main()
