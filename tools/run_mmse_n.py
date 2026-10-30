#!/usr/bin/env python3
"""MMSE_N (N = 2,3,4,5,8) integer reference, strict lint and streaming/reset/error verification in Questa."""
import argparse
import re
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_unoptimized
from run_rtl import execute,SOURCES
from mmse_n_cases import vectors,CASES,SIZES
from spectral_evidence import check_observers,negative_controls

PASS=r'PASS MMSE_N: (\d+) outputs, (\d+) cycles, (\d+) config cycles'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
SCENARIOS=[('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
           ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
           ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
           ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]
CLEAN=r'\*\* (?:Error|Fatal)'


def run_case(bindir,output,n,case_index,kind):
    folder=output/'vectors'/f'n{n}'/kind
    report=vectors(folder,kind,n,seed=53+17*n+case_index)
    artifacts=[*folder.glob('*.txt'),folder/'saturation.json'];records={};simultaneous=0
    for active in (1,0):
        work=output/f'n{n}'/f'{kind}_reset{active}';work.mkdir(parents=True,exist_ok=True)
        # Pre-optimised per (N, reset polarity) in main(): parallel jobs only read the library.
        common=[bindir/'vsim','-64','-c','-quiet','-lib',output/f'n{n}'/'work',f'mmse_n_tb_r{active}']
        observed={}
        for scenario,flags in SCENARIOS:
            log=work/f'{scenario}.log'
            text=execute([*common,f'+VECTORS={folder}',*flags,'-do',
                          'onerror {quit -code 1}; run -all; quit -code 0'],work,log)
            match=re.search(PASS,text)
            if not match or int(match[1])!=report['outputs'] or re.search(CLEAN,text):
                raise RuntimeError(f'MMSE_N N={n} {kind} {scenario}: incomplete numeric stream')
            check_observers(text,folder,'mmse_n')
            bounds=re.search(r'PASS BOUNDS mmse_n: (\d+) checks, (\d+) simultaneous',text)
            simultaneous+=int(bounds[2])
            observed[scenario]=dict(outputs=int(match[1]),cycles=int(match[2]),config_cycles=int(match[3]),
                                    bounds=int(bounds[1]),simultaneous=int(bounds[2]))
            artifacts.append(log)
        controls={}
        if kind in ('identity','tiny_identity'):
            negative_controls(common,folder,work,artifacts,PASS)
            script=work/'negative_numeric.do'
            script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
            artifacts.append(script)
            for name,flag,tag in [('numeric','+INJECT_MISMATCH','NUMERIC'),
                                  ('weights','+INJECT_WEIGHT_MISMATCH','WEIGHTS')]:
                bad=subprocess.run([str(v) for v in [*common,f'+VECTORS={folder}',flag,'-do',script.name]],
                                   cwd=work,capture_output=True,text=True,timeout=300)
                text=bad.stdout+bad.stderr;log=work/f'negative_{name}.log';log.write_text(text);artifacts.append(log)
                if not bad.returncode or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or re.search(PASS,text):
                    raise RuntimeError(f'MMSE_N N={n} {name} negative control passed')
                controls[f'{name}_exitcode']=bad.returncode
        if kind=='identity':
            for name,flag,marker in [('singular',f'+REJECT={folder}/reject_singular.txt','PASS MMSE_N CONFIG REJECT'),
                                     ('range',f'+REJECT={folder}/reject_range.txt','PASS MMSE_N CONFIG REJECT'),
                                     ('bad_cfg','+BAD_CFG_LAST','PASS MMSE_N CONFIG REJECT'),
                                     ('bad_cfg_count','+BAD_CFG_COUNT','PASS MMSE_N CONFIG REJECT'),
                                     ('bad_data','+BAD_DATA_LAST','PASS MMSE_N DATA REJECT'),
                                     *([('bad_data_second','+BAD_DATA_LAST_SECOND','PASS MMSE_N DATA REJECT')]
                                       if n>=3 else [])]:
                log=work/f'{name}.log'
                text=execute([*common,f'+VECTORS={folder}',flag,'-do',
                              'onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                if marker not in text or re.search(CLEAN,text):
                    raise RuntimeError(f'MMSE_N N={n} {name} was not rejected')
                controls[name]='PASS';artifacts.append(log)
        records[f'n{n}_{kind}_reset{active}']=dict(report,rtl_verified=True,scenarios=observed,controls=controls)
    print(f'PASS MMSE_N N={n} {kind}',flush=True)
    return records,artifacts,simultaneous


def main():
    require_unoptimized()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=('python','lint','hdl','all'),default='all')
    parser.add_argument('--jobs',type=int,default=8)
    args=parser.parse_args()
    output=ROOT/'build/rtl/mmse_n';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json'
    write_json(target,dict(evidence,status='RUNNING'))
    records={};artifacts=[]
    if args.suite in ('all','python'):
        log=output/'test_mmse_n_fixed.log'
        execute([sys.executable,ROOT/'tests/test_mmse_n_fixed.py'],ROOT,log)
        artifacts.append(log);records['python']='PASS'
    if args.suite in ('all','lint'):
        for n in range(2,9):
            log=output/f'lint_n{n}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','mmse_n',f'-GN={n}',f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'MMSE_N N={n} strict lint warnings')
            artifacts.append(log)
        records['lint']=dict(status='PASS',sizes=list(range(2,9)))
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths()
        for n in SIZES:
            base=output/f'n{n}';base.mkdir(parents=True,exist_ok=True)
            if not (base/'work').is_dir():execute([bindir/'vlib','work'],base,base/'vlib.log')
            log=base/'compile.log'
            text=execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',
                          *SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',
                          ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/mmse_n_tb.sv'],base,log)
            if re.search(r'Errors:\s*[1-9]',text):raise RuntimeError('MMSE_N compile errors')
            artifacts.append(log)
            for active in (1,0):
                log=base/f'vopt_r{active}.log'
                text=execute([bindir/'vopt','-64','work.mmse_n_tb',f'-gN={n}',f'-gRESET_ACTIVE={active}',
                              '-o',f'mmse_n_tb_r{active}'],base,log)
                if re.search(r'Errors:\s*[1-9]',text):raise RuntimeError('MMSE_N optimisation errors')
                artifacts.append(log)
        jobs=[(n,index,kind) for n in SIZES for index,kind in enumerate(CASES)]
        total_simultaneous=0
        with ThreadPoolExecutor(max_workers=args.jobs) as pool:
            for case_records,case_artifacts,simultaneous in pool.map(lambda job:run_case(bindir,output,*job),jobs):
                records.update(case_records);artifacts.extend(case_artifacts);total_simultaneous+=simultaneous
        if total_simultaneous<1:raise RuntimeError('MMSE_N simultaneous push/pop not exercised')
        records['hdl_summary']=dict(sizes=list(SIZES),cases=list(CASES),
                                    normal_runs=len(jobs)*2*len(SCENARIOS),simultaneous=total_simultaneous)
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)))
    print(f'PASS MMSE_N {args.suite}')


if __name__=='__main__':main()
