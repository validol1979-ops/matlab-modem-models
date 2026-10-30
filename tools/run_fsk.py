#!/usr/bin/env python3
"""Integer M-FSK reference, strict lint and Questa numeric scoreboard
(rtl/common/fsk_tx.sv and fsk_rx.sv driven by rtl/tb/fsk_tb.sv)."""
import argparse
import json
from pathlib import Path
import subprocess
import re
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths
from run_rtl import execute,SOURCES
from fsk_cases import vectors
from run_fsk_ldpc_protocol import healthy_report_artifacts

DUTS=[ROOT/'rtl/common/fsk_tx.sv',ROOT/'rtl/common/fsk_rx.sv']
TOPS=['fsk_tx','fsk_rx']
# (n,f0,df,order,LOG2M,LOG2NMAX)
CASES=[(32,2,3,4,2,5),(16,1,2,2,1,4),(40,.5,1.5,8,3,6),(7,0,1,3,2,3),(64,3,4,16,4,6),(1,0,0,1,0,1)]
NEGATIVE=CASES[0]
PASS=r'PASS FSK: (\d+) samples, (\d+) labels, (\d+) cycles'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
TABLE_DIR=PILOT/'tables'


def folder_for(base,index,case):
    return base/f'case{index}_n{case[0]}_f{case[1]}_{case[2]}_m{case[3]}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl'):
        for dut in DUTS:
            if not dut.is_file():raise RuntimeError(f'Missing DUT {dut}: the fsk RTL is not written yet')
    output=ROOT/'build/rtl/fsk';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_fsk_fixed.log';execute([sys.executable,ROOT/'tests/test_fsk_fixed.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for log2m,log2n in dict.fromkeys((case[4],case[5]) for case in CASES):
            for top in TOPS:
                log=output/f'lint_{top}_{log2m}_{log2n}.log'
                text=execute(['verilator','--lint-only','-Wall','--top-module',top,f'-GLOG2M={log2m}',f'-GLOG2NMAX={log2n}',f'-I{PILOT}',*SOURCES],ROOT,log)
                if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top} LOG2M={log2m} LOG2NMAX={log2n}')
                artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,case in enumerate(CASES):
            folder=folder_for(base,index,case)
            reports[index]=vectors(folder,n=case[0],f0=case[1],df=case[2],order=case[3],
                                   symbols=40,transactions=3,seed=71+index)
        artifacts.extend(base.rglob('*.txt'))
        for index,case in enumerate(CASES):
            folder=folder_for(base,index,case);report=reports[index]
            for active in (1,0):
                work=output/f'case{index}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/fsk_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.fsk_tb',f'-gRESET_ACTIVE={active}',
                        f'-gLOG2M={case[4]}',f'-gLOG2NMAX={case[5]}',f'-gTABLE_DIR={TABLE_DIR}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if (not match or int(match.group(1))!=report['tx_outputs']
                            or int(match.group(2))!=report['rx_outputs']
                            or re.search(r'\*\* (?:Error|Fatal)',text)):
                        raise RuntimeError(text[-6000:])
                    artifacts.append(work/f'{scenario}.log')
                    if not re.search(r'PASS BOUNDS fsk: [1-9]\d* checks',text):
                        raise RuntimeError('FSK bounds monitor missing or not exercised')
                if tuple(case)==NEGATIVE:
                    numeric_script=work/'numeric_negative.do'
                    numeric_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.append(numeric_script)
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do',numeric_script.name]],cwd=work,capture_output=True,text=True,timeout=90)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if not bad.returncode or not re.search(r'\*\* Fatal:.*\[NUMERIC\]',negative) or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    script=work/'bounds.do'
                    script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.append(script)
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',
                                        '+INJECT_BOUND_MISMATCH','-do',script.name]],
                                       cwd=work,capture_output=True,text=True,timeout=90)
                    negative=bad.stdout+bad.stderr
                    (work/'negative_bounds.log').write_text(negative)
                    if not bad.returncode or not re.search(r'\*\* Fatal:.*\[BOUNDS\]',negative) or re.search(PASS,negative):
                        raise RuntimeError(f'FSK bound injection not rejected: {negative[-1500:]}')
                    artifacts.append(work/'negative_bounds.log')
                report['bounds_rtl_verified']=True
                records[f'case{index}_reset_{active}']=report
                print(f'PASS FSK case{index} reset={active}',flush=True)
        protocol_folder=ROOT/'build/rtl/fsk_protocol';protocol_log=output/'protocol.log'
        execute([sys.executable,ROOT/'tools/run_fsk_ldpc_protocol.py','--block','fsk','--output',protocol_folder],ROOT,protocol_log)
        protocol_result=protocol_folder/'results.json';protocol=json.loads(protocol_result.read_text())
        artifacts.extend([protocol_log,protocol_result,*healthy_report_artifacts(protocol,'fsk')])
        records['protocol']=dict(status='PASS',runs=len(protocol['records']),results=str(protocol_result.relative_to(ROOT)))
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS FSK {args.suite}')

if __name__=='__main__':main()
