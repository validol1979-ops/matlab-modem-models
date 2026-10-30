#!/usr/bin/env python3
"""Integer OM-LSA reference, strict lint and Questa numeric scoreboard
(rtl/common/omlsa.sv driven by rtl/tb/omlsa_tb.sv)."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_pass
from run_rtl import execute,SOURCES
from omlsa_cases import vectors
from spectral_evidence import check_observers,negative_controls

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
DUT=ROOT/'rtl/common/omlsa.sv'
MEM_DIR=ROOT/'rtl/common/mem'
# (n, hop, nnoise, alpha, complex_input); the first one is the model case of the reference test.
CASES=[(32,8,12,.92,False),(64,16,6,.9,False),(32,8,4,.98,True),(16,4,10,.8,False),(16,4,1,.9,True)]
NEGATIVE=(32,8,12)  # (n, hop, nnoise) of the first case: the negative control runs there
LINT_CASES=sorted({(n.bit_length()-1,hop.bit_length()-1) for n,hop,_,_,_ in CASES})
PASS=r'PASS OMLSA: (\d+) outputs, (\d+) cycles'


def folder_for(base,n,hop,nnoise):
    return base/f'n{n}_hop{hop}_nn{nnoise}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl') and not DUT.is_file():
        raise RuntimeError(f'Missing DUT {DUT}: the omlsa RTL is not written yet')
    output=ROOT/'build/rtl/omlsa';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        for name in ('test_omlsa_fixed','test_stft_fixed','test_omlsa_width_sweep'):
            log=output/f'{name}.log';execute([sys.executable,ROOT/f'tests/{name}.py'],ROOT,log);artifacts.append(log)
        log=output/'fft_tables.log';execute([sys.executable,ROOT/'tools/fft_tables.py','--check'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for log2n,log2hop in LINT_CASES:
            parameters=[f'-GLOG2N={log2n}',f'-GLOG2HOP={log2hop}',f'-GMEM_DIR="{MEM_DIR}/"']
            log=output/f'lint_omlsa_{1<<log2n}_{1<<log2hop}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','omlsa',*parameters,f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: omlsa LOG2N={log2n} LOG2HOP={log2hop}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        from run_stream_cfg_priority import run_group
        records['cfg_priority']=run_group('omlsa',output/'cfg_priority',artifacts)
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,(n,hop,nnoise,alpha,complex_input) in enumerate(CASES):
            folder=folder_for(base,n,hop,nnoise)
            reports[(n,hop,nnoise)]=vectors(folder,n,hop,nnoise,alpha,transactions=2,
                                            complex_input=complex_input,seed=31+index,stress=index==4)
        artifacts.extend(base.rglob('*.txt'))
        artifacts.extend(base.rglob('saturation.json'))
        for index,(n,hop,nnoise,alpha,complex_input) in enumerate(CASES):
            folder=folder_for(base,n,hop,nnoise);report=reports[(n,hop,nnoise)]
            log2n=n.bit_length()-1;log2hop=hop.bit_length()-1
            for active in (1,0):
                work=output/f'n{n}_hop{hop}_nn{nnoise}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/omlsa_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.omlsa_tb',f'-gLOG2N={log2n}',f'-gLOG2HOP={log2hop}',
                        f'-gRESET_ACTIVE={active}',f'-gMEM_DIR={MEM_DIR}/']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['outputs'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    artifacts.append(work/f'{scenario}.log')
                    check_observers(text,folder,'omlsa')
                if (n,hop,nnoise)==NEGATIVE:
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if '[NUMERIC]' not in negative or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    negative_controls(common,folder,work,artifacts,PASS)
                report['saturation_rtl_verified']=True;report['bounds_rtl_verified']=True
                records[f'n{n}_hop{hop}_nn{nnoise}_reset_{active}']=report
                print(f'PASS OMLSA N={n} HOP={hop} nnoise={nnoise} reset={active}',flush=True)
    if args.suite in ('all','hdl'):
        # Narrowed gain intermediates: 128-bit operand reference, corners, guards and fault controls.
        import json
        from omlsa_width_sweep import check_acceptance
        path=ROOT/'build/rtl/omlsa_width_sweep/rtl_results.json';log=output/'omlsa_width_sweep.log'
        execute([sys.executable,ROOT/'tools/omlsa_width_sweep.py','--verify-rtl','--output',path],ROOT,log)
        report=json.loads(path.read_text());require_pass(report);check_acceptance(report)
        if not report['rtl_verified']:raise RuntimeError('Missing OM-LSA width RTL verification')
        records['omlsa_width_sweep']=dict(rtl_verified=True,result=str(path.relative_to(ROOT)),normal=len(report['rtl_equivalence']),
            parameters=len(report['rtl_parameters']),directed=len(report['rtl_directed']),unsafe=len(report['rtl_unsafe']),negative=len(report['rtl_negative']))
        artifacts.extend([path,log,*(ROOT/name for name in report['artifact_hashes'])])
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS OMLSA {args.suite}')


if __name__=='__main__':main()
