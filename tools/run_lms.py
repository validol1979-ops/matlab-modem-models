#!/usr/bin/env python3
"""LMS/NLMS reference, strict lint and Questa numeric scoreboard
(rtl/common/lms_filter.sv driven by rtl/tb/lms_tb.sv)."""
import argparse
from pathlib import Path
import subprocess
import re
import sys
import importlib
from concurrent.futures import ThreadPoolExecutor
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_pass
from run_rtl import execute,SOURCES
from lms_cases import vectors,read_saturation_expected
from run_adaptive_protocol import run_core as protocol_checks

DUT=ROOT/'rtl/common/lms_filter.sv'
# (mode, step, eps, taps, LOG2N)
CASES=[('lms',.05,.01,3,2),('nlms',.6,.01,3,2),('lms',.02,.01,1,0),
       ('nlms',.3,.05,8,3),('nlms',1,.001,16,4),('lms',.2,.01,4,2),('lms',1,.01,2,1)]
NEGATIVE=CASES[0]
LINT_CASES=sorted({n for *_,n in CASES})
PASS=r'PASS LMS: (\d+) outputs, (\d+) weights, (\d+) cycles'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def folder_for(base,index,mode,taps,log2n):
    return base/f'case{index}_{mode}_n{log2n}_t{taps}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl') and not DUT.is_file():
        raise RuntimeError(f'Missing DUT {DUT}: the lms RTL is not written yet')
    output=ROOT/'build/rtl/lms';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_lms_fixed.log';execute([sys.executable,ROOT/'tests/test_lms_fixed.py'],ROOT,log);artifacts.append(log)
        log=output/'test_lms_energy_study.log';execute([sys.executable,ROOT/'tests/test_lms_energy_study.py'],ROOT,log);artifacts.append(log)
        log=output/'test_lms_width_sweep.log';execute([sys.executable,ROOT/'tests/test_lms_width_sweep.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for log2n in LINT_CASES:
            parameters=[f'-GLOG2N={log2n}']
            log=output/f'lint_lms_filter_{log2n}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','lms_filter',*parameters,f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: lms_filter log2n={log2n}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,(mode,step,eps,taps,log2n) in enumerate(CASES):
            folder=folder_for(base,index,mode,taps,log2n)
            reports[index]=vectors(folder,mode,step,eps,taps,transactions=3,seed=37+index,stress=index==6)
        artifacts.extend(base.rglob('*.txt'))
        artifacts.extend(base.rglob('saturation.json'))
        for index,(mode,step,eps,taps,log2n) in enumerate(CASES):
            folder=folder_for(base,index,mode,taps,log2n);report=reports[index]
            for active in (1,0):
                work=output/f'{mode}_n{log2n}_t{taps}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/lms_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.lms_tb',f'-gLOG2N={log2n}',f'-gRESET_ACTIVE={active}',f"-gRECIP_FILE={ROOT/'rtl/common/mem/lms_reciprocal.mem'}"]
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['outputs'] or int(match.group(2))!=report['weights'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    for name,(evaluations,events) in read_saturation_expected(folder).items():
                        if f'PASS SATURATION {name}: {evaluations} evaluations, {events} events' not in text:
                            raise RuntimeError(f'Missing completed clamp comparison: {name}')
                    if not re.search(r'PASS BOUNDS lms: [1-9]\d* checks',text):raise RuntimeError('Missing bounds evidence')
                    artifacts.append(work/f'{scenario}.log')
                if (mode,step,eps,taps,log2n)==NEGATIVE:
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if '[NUMERIC]' not in negative or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    script=work/'negative.do'
                    script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.append(script)
                    for name,flag,tag in [('events','+INJECT_SAT_MISMATCH','SATURATION'),
                                          ('evaluations','+INJECT_SAT_EVAL_MISMATCH','SATURATION'),
                                          ('bounds','+INJECT_BOUND_MISMATCH','BOUNDS')]:
                        bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',flag,'-do','negative.do']],cwd=work,capture_output=True,text=True,timeout=60)
                        negative=bad.stdout+bad.stderr;log=work/f'negative_{name}.log';log.write_text(negative);artifacts.append(log)
                        if not bad.returncode or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',negative) or re.search(PASS,negative):
                            raise RuntimeError(f'Negative {name} not rejected')
                report['saturation_rtl_verified']=True;report['bounds_rtl_verified']=True
                records[f'{mode}_n{log2n}_t{taps}_reset_{active}']=report
                print(f'PASS LMS {mode} log2n={log2n} taps={taps} reset={active} '
                      f"m_rails={report['m_rails']} w_rails={report['w_rails']}",flush=True)
    if args.suite in ('all','hdl'):
        records['protocol']=protocol_checks('lms',output/'protocol',artifacts)
        import json
        def study(module):
            path=ROOT/f'build/rtl/{module}/rtl_results.json';log=output/(module+'.log')
            execute([sys.executable,ROOT/f'tools/{module}.py','--verify-rtl','--output',path],ROOT,log)
            report=json.loads(path.read_text());require_pass(report);importlib.import_module(module).check_acceptance(report)
            if not report['rtl_verified']:raise RuntimeError('Missing RTL verification: '+module)
            return module,path,log,report
        with ThreadPoolExecutor(max_workers=2) as pool:
            for module,path,log,report in pool.map(study,('lms_energy_study','lms_width_sweep')):
                key={'lms_energy_study':'energy_study'}.get(module,module)
                records[key]=dict(rtl_verified=True,result=str(path.relative_to(ROOT)),normal=len(report['rtl_equivalence']),
                    parameters=len(report['rtl_parameters']),negative=len(report['rtl_negative']),
                    **({'directed':len(report['rtl_directed'])} if 'rtl_directed' in report else {}))
                artifacts.extend([path,log,*(ROOT/name for name in report['artifact_hashes'])])
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS LMS {args.suite}')

if __name__=='__main__':main()
