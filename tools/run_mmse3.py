#!/usr/bin/env python3
"""MMSE3 integer reference, strict lint and streaming/reset/error verification in Questa."""
import argparse
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_unoptimized
from run_rtl import execute,SOURCES
from mmse3_cases import vectors,CASES
from spectral_evidence import check_observers,negative_controls

DUT=ROOT/'rtl/common/mmse3.sv'
PASS=r'PASS MMSE3: (\d+) outputs, (\d+) cycles'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def main():
    require_unoptimized()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=('python','lint','hdl','all'),default='all')
    args=parser.parse_args()
    output=ROOT/'build/rtl/mmse3';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json'
    write_json(target,dict(evidence,status='RUNNING'))
    records={};artifacts=[]
    if args.suite in ('all','python'):
        log=output/'test_mmse3_fixed.log'
        execute([sys.executable,ROOT/'tests/test_mmse3_fixed.py'],ROOT,log)
        artifacts.append(log);records['python']='PASS'
    if args.suite in ('all','lint'):
        log=output/'lint.log'
        text=execute(['verilator','--lint-only','-Wall','--top-module','mmse3',f'-I{PILOT}',*SOURCES],ROOT,log)
        if '%Warning' in text:raise RuntimeError('MMSE3 strict lint warnings')
        artifacts.append(log);records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths()
        total_simultaneous=0
        for case_index,kind in enumerate(CASES):
            folder=output/'vectors'/kind
            report=vectors(folder,kind,seed=53+case_index)
            artifacts.extend(folder.glob('*.txt'));artifacts.append(folder/'saturation.json')
            for active in (1,0):
                work=output/f'{kind}_reset{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                log=work/'compile.log'
                text=execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',
                              *SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',
                              ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/mmse3_tb.sv'],work,log)
                if re.search(r'Errors:\s*[1-9]',text):raise RuntimeError('MMSE3 compile errors')
                artifacts.append(log)
                common=[bindir/'vsim','-64','-c','-quiet','work.mmse3_tb',f'-gRESET_ACTIVE={active}']
                observed={}
                for scenario,flags in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                       ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                       ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                       ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    log=work/f'{scenario}.log'
                    text=execute([*common,f'+VECTORS={folder}',*flags,'-do',
                                  'onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                    match=re.search(PASS,text)
                    if (not match or int(match[1])!=report['outputs']
                            or re.search(r'\*\* (?:Error|Fatal)',text)):
                        raise RuntimeError('MMSE3 incomplete numeric stream')
                    check_observers(text,folder,'mmse3')
                    bounds=re.search(r'PASS BOUNDS mmse3: (\d+) checks, (\d+) simultaneous',text)
                    if not bounds or int(bounds[1])<1:raise RuntimeError('Unexercised MMSE3 bounds')
                    total_simultaneous+=int(bounds[2])
                    observed[scenario]=dict(outputs=int(match[1]),cycles=int(match[2]),
                                             bounds=int(bounds[1]),simultaneous=int(bounds[2]))
                    artifacts.append(log)
                rejections={}
                if kind in ('identity','tiny_identity'):
                    negative_controls(common,folder,work,artifacts,PASS)
                    script=work/'negative_numeric.do'
                    script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.append(script)
                    for name,flag,tag in [('numeric','+INJECT_MISMATCH','NUMERIC'),
                                          ('weights','+INJECT_WEIGHT_MISMATCH','WEIGHTS')]:
                        bad=subprocess.run([str(v) for v in [*common,f'+VECTORS={folder}',flag,
                                                             '-do',script.name]],cwd=work,capture_output=True,text=True,timeout=90)
                        text=bad.stdout+bad.stderr;log=work/f'negative_{name}.log';log.write_text(text);artifacts.append(log)
                        if not bad.returncode or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or re.search(PASS,text):
                            raise RuntimeError(f'MMSE3 {name} negative control passed')
                        rejections[f'{name}_exitcode']=bad.returncode
                if kind=='identity':
                    for name,flag,marker in [('singular','+SINGULAR','PASS MMSE3 SINGULAR'),
                                             ('bad_cfg','+BAD_CFG_LAST','PASS MMSE3 CONFIG REJECT'),
                                             ('bad_cfg_count','+BAD_CFG_COUNT','PASS MMSE3 CONFIG REJECT'),
                                             ('overflow','+COEFFICIENT_OVERFLOW','PASS MMSE3 CONFIG REJECT'),
                                             ('bad_data','+BAD_DATA_LAST','PASS MMSE3 DATA REJECT'),
                                             ('bad_data_second','+BAD_DATA_LAST_SECOND','PASS MMSE3 DATA REJECT')]:
                        log=work/f'{name}.log'
                        text=execute([*common,f'+VECTORS={folder}',flag,'-do',
                                      'onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                        if marker not in text or re.search(r'\*\* (?:Error|Fatal)',text):
                            raise RuntimeError(f'MMSE3 {name} was not rejected')
                        rejections[name]='PASS';artifacts.append(log)
                records[f'{kind}_reset{active}']=dict(report,rtl_verified=True,scenarios=observed,
                                                    controls=rejections)
                print(f'PASS MMSE3 {kind} reset={active}',flush=True)
        if total_simultaneous<1:raise RuntimeError('MMSE3 simultaneous push/pop not exercised')
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)))
    print(f'PASS MMSE3 {args.suite}')


if __name__=='__main__':main()
