#!/usr/bin/env python3
"""Beamformer + Alamouti reference, strict lint and Questa numeric scoreboard
(rtl/common/beamform.sv and alamouti_rx.sv driven by rtl/tb/beam_tb.sv)."""
import argparse
from pathlib import Path
import json
import subprocess
import re
import sys
from concurrent.futures import ThreadPoolExecutor
import importlib
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_pass
from run_rtl import execute,SOURCES
from beam_cases import vectors

DUTS=[ROOT/'rtl/common/beamform.sv',ROOT/'rtl/common/alamouti_rx.sv']
# (M, weights_kind, LOG2M)
CASES=[(8,'steering',3),(1,'random',0),(3,'random',2),(16,'random',4),(4,'random',3)]
NEGATIVE=CASES[0]
PASS=r'PASS BEAM: (\d+) beams, (\d+) symbols, (\d+) cycles'
SATPASS={'beam':r'PASS SATURATION beam: (\d+) evaluations, (\d+) events',
         'alamouti':r'PASS SATURATION alamouti: (\d+) evaluations, (\d+) events'}
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def folder_for(base,index,m,kind):
    return base/f'case{index}_m{m}_{kind}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl'):
        for dut in DUTS:
            if not dut.is_file():raise RuntimeError(f'Missing DUT {dut}: the beam RTL is not written yet')
    output=ROOT/'build/rtl/beam';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_beam_fixed.log';execute([sys.executable,ROOT/'tests/test_beam_fixed.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
        log=output/'test_beam_energy_study.log';execute([sys.executable,ROOT/'tests/test_beam_energy_study.py'],ROOT,log);artifacts.append(log)
        log=output/'test_alamouti_width_sweep.log';execute([sys.executable,ROOT/'tests/test_alamouti_width_sweep.py'],ROOT,log);artifacts.append(log)
    if args.suite in ('all','lint'):
        for log2m in sorted({case[2] for case in CASES}):
            log=output/f'lint_beamform_L{log2m}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','beamform',f'-GLOG2M={log2m}',f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: beamform LOG2M={log2m}')
            artifacts.append(log)
        log=output/'lint_alamouti_rx.log'
        text=execute(['verilator','--lint-only','-Wall','--top-module','alamouti_rx',f'-I{PILOT}',*SOURCES],ROOT,log)
        if '%Warning' in text:raise RuntimeError(f'Lint warnings: alamouti_rx')
        artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        from run_stream_cfg_priority import run_group
        records['cfg_priority']=run_group('beam',output/'cfg_priority',artifacts)
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,(m,kind,log2m) in enumerate(CASES):
            folder=folder_for(base,index,m,kind)
            reports[index]=vectors(folder,m,kind,transactions=4,seed=31+index)
        artifacts.extend(base.rglob('*.txt'))
        for index,(m,kind,log2m) in enumerate(CASES):
            folder=folder_for(base,index,m,kind);report=reports[index]
            for active in (1,0):
                work=output/f'case{index}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/beam_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.beam_tb',f'-gLOG2M={log2m}',f'-gRESET_ACTIVE={active}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if (not match or int(match.group(1))!=report['bf_outputs']
                            or int(match.group(2))!=report['al_outputs']
                            or re.search(r'\*\* (?:Error|Fatal)',text)):
                        raise RuntimeError(text[-6000:])
                    for name,evaluations,events in (('beam',report['bf_evaluations'],report['bf_events']),
                                                    ('alamouti',report['al_evaluations'],report['al_events'])):
                        sat=re.search(SATPASS[name],text)
                        if (not sat or int(sat.group(1))!=evaluations or int(sat.group(2))!=events):
                            raise RuntimeError(f'saturation marker missing or wrong for {name} '
                                               f'(want {evaluations} evaluations, {events} events):\n{text[-6000:]}')
                    artifacts.append(work/f'{scenario}.log')
                    if not re.search(r'PASS BOUNDS beam: [1-9]\d* checks',text):
                        raise RuntimeError('Missing beam bounds verification')
                if (m,kind,log2m)==NEGATIVE:
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if '[NUMERIC]' not in negative or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    for flag,label in (('+INJECT_SAT_MISMATCH','negative_sat_events'),('+INJECT_SAT_EVAL_MISMATCH','negative_sat_evaluations')):
                        bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',flag,'-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                        negative=bad.stdout+bad.stderr;(work/f'{label}.log').write_text(negative)
                        if not re.search(r'\*\* Fatal:.*\[SATURATION\]',negative) or re.search(r'PASS SATURATION|PASS BEAM',negative):
                            raise RuntimeError(f'saturation negative control {flag} not detected')
                        artifacts.append(work/f'{label}.log')
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_BOUND_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                    negative=bad.stdout+bad.stderr;(work/'negative_bounds.log').write_text(negative)
                    if not re.search(r'\*\* Fatal:.*\[BOUNDS\]',negative) or re.search(PASS,negative):
                        raise RuntimeError('Beam bounds negative control not detected')
                    artifacts.append(work/'negative_bounds.log')
                report['bounds_verified']=True
                records[f'case{index}_reset_{active}']=report
                print(f"PASS BEAM case{index} reset={active} bf_overload={report['bf_overload']} "
                      f"bf_bound={report['bf_bound']} al_overload={report['al_overload']} "
                      f"al_bound={report['al_bound']} bf_events={report['bf_events']} "
                      f"al_events={report['al_events']}",flush=True)
            # every normal scenario of both reset polarities agreed with the model counts:
            # the model-only saturation.json gains the actual RTL_verified flag separately.
            payload=json.loads((folder/'saturation.json').read_text())
            payload['rtl_verified']=True
            write_json(folder/'saturation.json',payload)
            report['saturation_rtl_verified']=True
            artifacts.append(folder/'saturation.json')
    if args.suite in ('all','hdl'):
        def study(module):
            path=ROOT/f'build/rtl/{module}/rtl_results.json';log=output/(module+'.log')
            execute([sys.executable,ROOT/f'tools/{module}.py','--verify-rtl','--output',path],ROOT,log)
            report=json.loads(path.read_text());require_pass(report);importlib.import_module(module).check_acceptance(report)
            if not report['rtl_verified']:raise RuntimeError('Missing RTL verification: '+module)
            return module,path,log,report
        with ThreadPoolExecutor(max_workers=2) as pool:
            for module,path,log,report in pool.map(study,('beam_energy_study','alamouti_width_sweep')):
                records[module]=dict(rtl_verified=True,result=str(path.relative_to(ROOT)),normal=len(report['rtl_equivalence']),
                    parameters=len(report['rtl_parameters']),negative=len(report['rtl_negative']))
                artifacts.extend([path,log,*(ROOT/name for name in report['artifact_hashes'])])
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS BEAM {args.suite}')

if __name__=='__main__':main()
