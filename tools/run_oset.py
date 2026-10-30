#!/usr/bin/env python3
"""Notch + Kalman reference, strict lint and Questa numeric scoreboard
(rtl/common/notch_iir.sv and kalman_scalar.sv driven by rtl/tb/oset_tb.sv)."""
import argparse
from pathlib import Path
import subprocess
import json
import re
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths
from run_oset_gardner_protocol import healthy_report_artifacts
from run_rtl import execute,SOURCES
from oset_cases import vectors,STRESS_NOTCH_RAW

DUTS=[ROOT/'rtl/common/notch_iir.sv',ROOT/'rtl/common/kalman_scalar.sv']
TOPS=['notch_iir','kalman_scalar']
# (notch=(f0,r), kalman=(q,r,p0))
CASES=[((.23,.94),(.0005,.25,1)),((0,.5),(0,.25,0)),((.5,.9),(.01,.1,2)),((.1,.99),(.0001,.05,.5))]
STRESS=dict(index=len(CASES),notch=(.23,.94),kalman=(.0005,.25,1),raw=STRESS_NOTCH_RAW,label='stress')
NEGATIVE=CASES[0]
PASS=r'PASS OSET: (\d+) notch, (\d+) kalman, (\d+) cycles'
SATPASS=r'PASS SATURATION (\w+): (\d+) evaluations, (\d+) events'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def folder_for(base,index,notch,kalman,raw=None):
    if raw is not None:
        return base/f'case{index}_stress_n{raw[0]}_{raw[1]}_{raw[2]}_k{kalman[0]}_{kalman[1]}_{kalman[2]}'
    return base/f'case{index}_n{notch[0]}_{notch[1]}_k{kalman[0]}_{kalman[1]}_{kalman[2]}'


def check_sat_markers(text,markers,work,scenario):
    found={name:(int(ev),int(evs)) for name,ev,evs in re.findall(SATPASS,text)}
    for name,(ev,evs) in markers.items():
        if found.get(name)!=(int(ev),int(evs)):
            raise RuntimeError(f'{work}/{scenario}: saturation marker {name}: got {found.get(name)}, want {(int(ev),int(evs))}')


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl'):
        for dut in DUTS:
            if not dut.is_file():raise RuntimeError(f'Missing DUT {dut}: the oset RTL is not written yet')
    output=ROOT/'build/rtl/oset';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_oset_fixed.log';execute([sys.executable,ROOT/'tests/test_oset_fixed.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for top in TOPS:
            log=output/f'lint_{top}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module',top,f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        runs=[dict(index=index,notch=notch,kalman=kalman,raw=None,label='designed')
              for index,(notch,kalman) in enumerate(CASES)]+[STRESS]
        for run in runs:
            folder=folder_for(base,run['index'],run['notch'],run['kalman'],run['raw'])
            reports[run['index']]=vectors(folder,notch=run['notch'],kalman=run['kalman'],
                                          transactions=4,seed=31+run['index'],
                                          notch_raw=run['raw'],label=run['label'])
        artifacts.extend(base.rglob('*.txt'))
        for run in runs:
            index,notch,kalman=run['index'],run['notch'],run['kalman']
            folder=folder_for(base,index,notch,kalman,run['raw']);report=reports[index]
            for active in (1,0):
                work=output/f'case{index}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/oset_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.oset_tb',f'-gRESET_ACTIVE={active}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if (not match or int(match.group(1))!=report['notch_outputs']
                            or int(match.group(2))!=report['kalman_outputs']
                            or re.search(r'\*\* (?:Error|Fatal)',text)):
                        raise RuntimeError(text[-6000:])
                    check_sat_markers(text,report['saturation_markers'],work,f'{scenario} reset={active}')
                    if not re.search(r'PASS BOUNDS oset: [1-9]\d* checks',text):
                        raise RuntimeError('Missing OSET bounds verification')
                    artifacts.append(work/f'{scenario}.log')
                if (notch,kalman)==NEGATIVE and run['raw'] is None:
                    negative_script=work/'negative.do'
                    negative_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.append(negative_script)
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do',negative_script.name]],cwd=work,capture_output=True,text=True,timeout=90)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if not bad.returncode or not re.search(r'\*\* Fatal:.*\[NUMERIC\]',negative) or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    for plus in ('+INJECT_SAT_MISMATCH','+INJECT_SAT_EVAL_MISMATCH'):
                        bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',plus,'-do',negative_script.name]],cwd=work,capture_output=True,text=True,timeout=90)
                        negative=bad.stdout+bad.stderr;(work/f'{plus[1:].lower()}.log').write_text(negative)
                        if not bad.returncode or not re.search(r'\*\* Fatal:.*\[SATURATION\]',negative) or 'PASS SATURATION notch_state' in negative or re.search(PASS,negative):
                            raise RuntimeError(f'saturation negative control {plus} not detected')
                        artifacts.append(work/f'{plus[1:].lower()}.log')
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_BOUND_MISMATCH','-do',negative_script.name]],cwd=work,capture_output=True,text=True,timeout=90)
                    negative=bad.stdout+bad.stderr;(work/'negative_bounds.log').write_text(negative)
                    if not bad.returncode or not re.search(r'\*\* Fatal:.*\[BOUNDS\]',negative) or re.search(PASS,negative):
                        raise RuntimeError('OSET bounds negative control not detected')
                    artifacts.append(work/'negative_bounds.log')
                report['bounds_verified']=True
                records[f'case{index}_reset_{active}']=report
                print(f'PASS OSET case{index} reset={active}',flush=True)
        # every normal scenario matched: store the actual RTL_verified counts separately
        # (saturation.json itself keeps the expected model counts from sat_diag.save_json).
        for run in runs:
            folder=folder_for(base,run['index'],run['notch'],run['kalman'],run['raw'])
            payload=json.loads((folder/'saturation.json').read_text())
            markers=reports[run['index']]['saturation_markers']
            payload['RTL_verified']={'evaluations':{k:int(v[0]) for k,v in markers.items()},
                                     'events':{k:int(v[1]) for k,v in markers.items()},
                                     'note':'actual RTL counters equalled the model in every normal scenario (both reset polarities, stalled, mid/out/cfg reset)'}
            (folder/'saturation.json').write_text(json.dumps(payload,indent=1,sort_keys=True)+'\n')
        protocol_folder=ROOT/'build/rtl/oset_protocol';protocol_log=output/'protocol.log'
        execute([sys.executable,ROOT/'tools/run_oset_gardner_protocol.py','--block','oset','--output',protocol_folder],ROOT,protocol_log)
        protocol_result=protocol_folder/'results.json';protocol=json.loads(protocol_result.read_text())
        artifacts.extend([protocol_log,protocol_result,*healthy_report_artifacts(protocol,'oset')]);records['protocol']=dict(status='PASS',runs=len(protocol['records']),results=str(protocol_result.relative_to(ROOT)))
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS OSET {args.suite}')

if __name__=='__main__':main()
