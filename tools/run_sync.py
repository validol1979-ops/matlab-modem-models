#!/usr/bin/env python3
"""Costas loop + Gardner timing reference, strict lint and Questa numeric scoreboard
(rtl/common/costas_loop.sv and gardner_timing.sv driven by rtl/tb/sync_tb.sv)."""
import argparse
import json
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_pass
from run_rtl import execute,SOURCES
from sync_cases import vectors
from spectral_evidence import check_observers,negative_controls
from sync_slip_evidence import check_costas_slip,check_costas_disturbances,check_costas_acquisition
from run_oset_gardner_protocol import healthy_report_artifacts

DUTS=[ROOT/'rtl/common/costas_loop.sv',ROOT/'rtl/common/gardner_timing.sv']
# (costas (k1,k2), timing (sps,count,position,k3,k4), kind); the model case runs one transaction only
CASES=[((.08,.001),(8,700,32,.1,.00005),'model'),((.02,.0001),(4,40,10,.05,.0001),'random'),
       ((0,0),(2,30,3.5,0,0),'off'),((.3,.01),(16,25,40.25,.2,.001),'wide')]
NEGATIVE=CASES[0]
PASS=r'PASS SYNC: (\d+) costas, (\d+) timing, (\d+) cycles'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def folder_for(base,index,kind):
    return base/f'case{index}_{kind}'


def transactions_for(kind):
    return 1 if kind=='model' else 3


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl'):
        for dut in DUTS:
            if not dut.is_file():raise RuntimeError(f'Missing DUT {dut}: the sync RTL is not written yet')
    output=ROOT/'build/rtl/sync';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        for test in ('sync_fixed','sync_slip_evidence','sync_disturbance','sync_grid_evidence'):
            log=output/f'test_{test}.log'
            execute([sys.executable,ROOT/f'tests/test_{test}.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
        for name in ('sync_precision','timing_precision','costas_acquisition'):
            log=output/f'{name}.log'
            execute([sys.executable,ROOT/f'tools/{name}.py'],ROOT,log)
            result=ROOT/f'build/rtl/{name}/results.json'
            data=json.loads(result.read_text());require_pass(data)
            artifacts.extend([log,result])
            records[name]=dict(status='PASS',results=str(result.relative_to(ROOT)))
    if args.suite in ('all','lint'):
        for dut in DUTS:
            top=dut.stem;log=output/f'lint_{top}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module',top,f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,(costas,timing,kind) in enumerate(CASES):
            folder=folder_for(base,index,kind)
            reports[index]=vectors(folder,costas,timing,transactions=transactions_for(kind),seed=41+index)
        artifacts.extend([*base.rglob('*.txt'), *base.rglob('*_tracking.json'),
                          *base.rglob('cl_slip.json'),
                          *base.rglob('cl_disturbances.json'),
                          *base.rglob('cl_acquisition.json'),
                          *base.rglob('saturation.json')])
        for index,(costas,timing,kind) in enumerate(CASES):
            folder=folder_for(base,index,kind);report=reports[index]
            for active in (1,0):
                work=output/f'case{index}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sync_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.sync_tb',f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={PILOT/"tables"}']
                slip_results={}
                disturbance_results={}
                acquisition_results={}
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    observed=work/f'{scenario}_costas_observed.txt'
                    text=execute([*common,f'+VECTORS={folder}',f'+COSTAS_OBSERVED={observed}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if (not match or int(match.group(1))!=report['cl_outputs']
                            or int(match.group(2))!=report['gt_outputs']
                            or re.search(r'\*\* (?:Error|Fatal)',text)):
                        raise RuntimeError(text[-6000:])
                    artifacts.append(work/f'{scenario}.log')
                    check_observers(text,folder,'sync')
                    measured=check_costas_slip(folder,observed)
                    artifacts.append(observed)
                    if measured is not None:
                        slip_results[scenario]=measured
                    disturbed=check_costas_disturbances(folder,observed)
                    if disturbed:
                        disturbance_results[scenario]=disturbed
                    acquisition=check_costas_acquisition(folder,observed)
                    if acquisition:
                        acquisition_results[scenario]=acquisition
                if (costas,timing,kind)==NEGATIVE:
                    script=work/'numeric_negative.do'
                    script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do',script.name]],cwd=work,capture_output=True,text=True,timeout=90)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if not bad.returncode or not re.search(r'\*\* Fatal:.*\[NUMERIC\]',negative) or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.extend([script,work/'negative.log'])
                    negative_controls(common,folder,work,artifacts,PASS)
                    observed=work/'negative_slip_costas_observed.txt'
                    execute([*common,f'+VECTORS={folder}',f'+COSTAS_OBSERVED={observed}',
                             '+INJECT_SLIP_PHASE','-do','onerror {quit -code 1}; run -all; quit -code 0'],
                            work,work/'negative_slip.log')
                    try:
                        check_costas_slip(folder,observed)
                    except RuntimeError as exc:
                        if '[SLIP]' not in str(exc):raise
                        (work/'negative_slip_check.log').write_text(str(exc)+'\n')
                    else:
                        raise RuntimeError('Corrupted RTL phase capture passed the slip criterion')
                    try:
                        check_costas_disturbances(folder,observed)
                    except RuntimeError as exc:
                        if '[DISTURBANCE]' not in str(exc):raise
                        (work/'negative_disturbance_check.log').write_text(str(exc)+'\n')
                    else:
                        raise RuntimeError('Corrupted RTL phase capture passed disturbance criteria')
                    try:
                        check_costas_acquisition(folder,observed)
                    except RuntimeError as exc:
                        if '[ACQUISITION]' not in str(exc):raise
                        (work/'negative_acquisition_check.log').write_text(str(exc)+'\n')
                    else:
                        raise RuntimeError('Corrupted RTL phase capture passed acquisition criteria')
                    artifacts.extend([observed,work/'negative_slip.log',work/'negative_slip_check.log',
                                      work/'negative_disturbance_check.log',work/'negative_acquisition_check.log'])
                report['saturation_rtl_verified']=True
                report['bounds_rtl_verified']=True
                records[f'case{index}_reset_{active}']=dict(report,cl_slip_rtl=slip_results,
                                                        cl_disturbances_rtl=disturbance_results,
                                                        cl_acquisition_rtl=acquisition_results)
                print(f"PASS SYNC case{index} reset={active} cl_overload={report['cl_overload']} "
                      f"cl_rails={report['cl_rails']} gt_overload={report['gt_overload']} "
                      f"gt_rails={report['gt_rails']}",flush=True)
        protocol_log=output/'costas_protocol.log'
        execute([sys.executable,ROOT/'tools/run_costas_protocol.py'],ROOT,protocol_log)
        protocol_result=ROOT/'build/rtl/costas_protocol/results.json'
        protocol=json.loads(protocol_result.read_text());require_pass(protocol)
        if protocol.get('expected_rejection') or len(protocol['records'])!=12:
            raise RuntimeError('Incomplete healthy Costas protocol gate')
        artifacts.extend([protocol_log,protocol_result,*(ROOT/p for p in protocol.get('artifact_hashes',{}))])
        records['costas_protocol']=dict(status='PASS',runs=len(protocol['records']),results=str(protocol_result.relative_to(ROOT)))
        gardner_folder=ROOT/'build/rtl/gardner_protocol';gardner_log=output/'gardner_protocol.log'
        execute([sys.executable,ROOT/'tools/run_oset_gardner_protocol.py','--block','gardner','--output',gardner_folder],ROOT,gardner_log)
        gardner_result=gardner_folder/'results.json';gardner=json.loads(gardner_result.read_text())
        artifacts.extend([gardner_log,gardner_result,*healthy_report_artifacts(gardner,'gardner')]);records['gardner_protocol']=dict(status='PASS',runs=len(gardner['records']),results=str(gardner_result.relative_to(ROOT)))
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS SYNC {args.suite}')

if __name__=='__main__':main()
