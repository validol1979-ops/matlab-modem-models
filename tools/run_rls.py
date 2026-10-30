#!/usr/bin/env python3
"""RLS reference, strict lint and Questa numeric scoreboard
(rtl/common/rls_filter.sv driven by rtl/tb/rls_tb.sv).

Every scenario of every configuration also replays the nine clamp groups of the reference model
(rls_pred_err, rls_u, rls_q, rls_gain, rls_update, rls_pt, rls_p_real, rls_p_imag, rls_dump): the
observer in rtl/tb/rls_saturation_check.svh counts the actual pre-clamp values of the DUT and each
sat_group_check compares its own totals with <group>_group_expected.txt, so nine
'PASS SATURATION <group>' lines have to agree with the expected files the vectors were written from.
The two last configurations are deterministic clamp stress (weight34: the 34 bit WEIGHT clamp on both
rails, p44: the 44 bit P clamp) instead of random traffic. The negative controls inject a wrong event
count and a wrong evaluation count into the expected rows (+INJECT_SAT_MISMATCH,
+INJECT_SAT_EVAL_MISMATCH) and must end in a [SATURATION] fatal with a nonzero exit code."""
import argparse
from pathlib import Path
import subprocess
import re
import sys
import importlib
from concurrent.futures import ThreadPoolExecutor
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_pass
from run_rtl import execute,SOURCES
from rls_cases import GROUPS,read_saturation_expected,vectors
from run_adaptive_protocol import run_core as protocol_checks

DUT=ROOT/'rtl/common/rls_filter.sv'
# (lam, eps, taps, noise, LOG2N)
CASES=[(.995,.01,3,0,2),(.98,.01,4,.01,2),(.99,.01,1,0,0),
       (.95,.001,8,.05,3),(1.,.1,2,0,1),
       (1.,1/16384,1,0,1),(0.5,1/16384,2,0,2)]
# deterministic clamp stress of the two last configurations: the 34 bit weight clamp and the 44 bit P
# clamp, neither reachable with the Gaussian traffic of the random cases
STRESS={5:'weight34',6:'p44'}
NEGATIVE=CASES[0]
LINT_CASES=sorted({n for *_,n in CASES})
PASS=r'PASS RLS: (\d+) outputs, (\d+) weights, (\d+) cycles'
SATURATION=r'PASS SATURATION {}: (\d+) evaluations, (\d+) events'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def folder_for(base,index,lam,taps,log2n):
    return base/f'case{index}_lam{str(lam).replace(".","p")}_n{log2n}_t{taps}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl') and not DUT.is_file():
        raise RuntimeError(f'Missing DUT {DUT}: the rls RTL is not written yet')
    output=ROOT/'build/rtl/rls';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_rls_fixed.log';execute([sys.executable,ROOT/'tests/test_rls_fixed.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
        log=output/'test_rls_width_sweep.log';execute([sys.executable,ROOT/'tests/test_rls_width_sweep.py'],ROOT,log);artifacts.append(log)
        log=output/'test_rls_update_sweep.log';execute([sys.executable,ROOT/'tests/test_rls_update_sweep.py'],ROOT,log);artifacts.append(log)
    if args.suite in ('all','lint'):
        for log2n in LINT_CASES:
            parameters=[f'-GLOG2N={log2n}']
            log=output/f'lint_rls_filter_{log2n}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','rls_filter',*parameters,f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: rls_filter log2n={log2n}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,(lam,eps,taps,noise,log2n) in enumerate(CASES):
            folder=folder_for(base,index,lam,taps,log2n)
            reports[index]=vectors(folder,lam,eps,taps,transactions=3,noise=noise,seed=37+index,
                                   stress=STRESS.get(index))
        artifacts.extend([*base.rglob('*.txt'),*base.rglob('saturation.json')])
        for index,(lam,eps,taps,noise,log2n) in enumerate(CASES):
            folder=folder_for(base,index,lam,taps,log2n);report=reports[index]
            expected=read_saturation_expected(folder)
            assert set(expected)=={name for name,_,_,_ in GROUPS}
            for active in (1,0):
                work=output/f'rls_n{log2n}_t{taps}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/rls_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.rls_tb',f'-gLOG2N={log2n}',f'-gRESET_ACTIVE={active}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['outputs'] or int(match.group(2))!=report['weights'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    for name,_,_,_ in GROUPS:
                        counts=re.search(SATURATION.format(name),text)
                        if not counts or tuple(map(int,counts.groups()))!=expected[name][1:]:
                            raise RuntimeError(f'RLS saturation {name} not verified for {scenario}: '
                                               f'{counts.groups() if counts else None} != {expected[name][1:]}')
                    if not re.search(r'PASS BOUNDS rls: [1-9]\d* checks',text):raise RuntimeError('Missing bounds evidence')
                    artifacts.append(work/f'{scenario}.log')
                if (lam,eps,taps,noise,log2n)==NEGATIVE:
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if '[NUMERIC]' not in negative or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    # the expected rows are the contract: breaking them, in the events or in the number
                    # of evaluations, must stop the run instead of passing silently
                    script=work/'saturation.do'
                    script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.append(script)
                    for control,flag in [('negative_saturation','+INJECT_SAT_MISMATCH'),
                                         ('negative_evaluations','+INJECT_SAT_EVAL_MISMATCH'),
                                         ('negative_bounds','+INJECT_BOUND_MISMATCH')]:
                        bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',flag,'-do',script.name]],cwd=work,capture_output=True,text=True,timeout=60)
                        negative=bad.stdout+bad.stderr;(work/f'{control}.log').write_text(negative)
                        if bad.returncode==0 or not re.search(r'\*\* Fatal:.*\['+('BOUNDS' if control=='negative_bounds' else 'SATURATION')+r'\]',negative) \
                                or re.search(PASS,negative):
                            raise RuntimeError(f'{control} control not detected '
                                               f'(exit {bad.returncode}): {negative[-2000:]}')
                        artifacts.append(work/f'{control}.log')
                records[f'rls_n{log2n}_t{taps}_reset_{active}']=dict(report,saturation_rtl_verified=True,bounds_rtl_verified=True)
                print(f'PASS RLS log2n={log2n} taps={taps} reset={active} '
                      f"m_rails={report['m_rails']} w_rails={report['w_rails']} "
                      f"saturation_events={report['saturation']['total']}",flush=True)
    if args.suite in ('all','hdl'):
        records['protocol']=protocol_checks('rls',output/'protocol',artifacts)
        import json
        def study(module):
            path=ROOT/f'build/rtl/{module}/rtl_results.json';log=output/(module+'.log')
            execute([sys.executable,ROOT/f'tools/{module}.py','--verify-rtl','--output',path],ROOT,log)
            report=json.loads(path.read_text());require_pass(report);importlib.import_module(module).check_acceptance(report)
            if not report['rtl_verified']:raise RuntimeError('Missing RTL verification: '+module)
            return module,path,log,report
        with ThreadPoolExecutor(max_workers=2) as pool:
            for module,path,log,report in pool.map(study,('rls_width_sweep','rls_update_sweep')):
                records[module]=dict(rtl_verified=True,result=str(path.relative_to(ROOT)),normal=len(report['rtl_equivalence']),
                    parameters=len(report['rtl_parameters']),directed=len(report['rtl_directed']),negative=len(report['rtl_negative']))
                artifacts.extend([path,log,*(ROOT/name for name in report['artifact_hashes'])])
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS RLS {args.suite}')

if __name__=='__main__':main()
