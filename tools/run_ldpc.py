#!/usr/bin/env python3
"""LDPC decoder + GF(2) encoder reference, strict lint and Questa numeric scoreboard
(rtl/common/ldpc_decoder.sv and gf2_encoder.sv driven by rtl/tb/ldpc_tb.sv)."""
import argparse
import json
from pathlib import Path
import subprocess
import re
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths
from run_rtl import execute,SOURCES
from ldpc_cases import vectors
from spectral_evidence import check_observers,negative_controls
from run_fsk_ldpc_protocol import healthy_report_artifacts

DUTS=[ROOT/'rtl/common/ldpc_decoder.sv',ROOT/'rtl/common/gf2_encoder.sv']
# (mode, code): the model code H = [I A] in every mode, the random 12 x 24 code in modes 0 and 1.
CASES=[(0,'model'),(1,'model'),(2,'model'),(3,'model'),(0,'big'),(1,'big'),(0,'model')]
PASS=r'PASS LDPC: (\d+) llrs, (\d+) bits, (\d+) cycles'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
PHI=ROOT/'rtl/common/mem/ldpc_phi.mem'
INV=ROOT/'rtl/common/mem/ldpc_inv.mem'


def folder_for(base,index,mode,code):
    return base/f'case{index}_{code}_mode{mode}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl'):
        for dut in DUTS:
            if not dut.is_file():raise RuntimeError(f'Missing DUT {dut}: the LDPC RTL is not written yet')
    output=ROOT/'build/rtl/ldpc';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_ldpc_fixed.log';execute([sys.executable,ROOT/'tests/test_ldpc_fixed.py'],ROOT,log);artifacts.append(log)
        log=output/'fft_tables.log';execute([sys.executable,ROOT/'tools/fft_tables.py','--check'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for top,extra in [('ldpc_decoder',[f'-GPHI_FILE="{PHI}"',f'-GINV_FILE="{INV}"']),('gf2_encoder',[])]:
            log=output/f'lint_{top}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module',top,f'-I{PILOT}',*extra,*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,(mode,code) in enumerate(CASES):
            folder=folder_for(base,index,mode,code)
            reports[index]=vectors(folder,mode,transactions=6,seed=31+index,code=code,stress=index==6)
        artifacts.extend(base.rglob('*.txt'))
        artifacts.extend(base.rglob('saturation.json'))
        for index,(mode,code) in enumerate(CASES):
            folder=folder_for(base,index,mode,code);report=reports[index]
            for active in (1,0):
                work=output/f'case{index}_{code}_mode{mode}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/ldpc_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.ldpc_tb',f'-gRESET_ACTIVE={active}',
                        f'-gPHI_FILE={PHI}',f'-gINV_FILE={INV}']
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if (not match or int(match.group(1))!=report['dec_outputs']
                            or int(match.group(2))!=report['enc_outputs']
                            or re.search(r'\*\* (?:Error|Fatal)',text)):
                        raise RuntimeError(text[-6000:])
                    artifacts.append(work/f'{scenario}.log')
                    check_observers(text,folder,'ldpc')
                if index==0:
                    numeric_script=work/'numeric_negative.do'
                    numeric_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.append(numeric_script)
                    bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_MISMATCH','-do',numeric_script.name]],cwd=work,capture_output=True,text=True,timeout=90)
                    negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative)
                    if not bad.returncode or not re.search(r'\*\* Fatal:.*\[NUMERIC\]',negative) or re.search(PASS,negative):raise RuntimeError('negative control not detected')
                    artifacts.append(work/'negative.log')
                    negative_controls(common,folder,work,artifacts,PASS)
                report['saturation_rtl_verified']=True
                report['bounds_rtl_verified']=True
                records[f'case{index}_{code}_mode{mode}_reset_{active}']=report
                print(f'PASS LDPC case{index} {code} mode={mode} reset={active} '
                      f"posterior_rails={report['posterior_rails']}",flush=True)
        protocol_folder=ROOT/'build/rtl/ldpc_protocol';protocol_log=output/'protocol.log'
        execute([sys.executable,ROOT/'tools/run_fsk_ldpc_protocol.py','--block','ldpc','--output',protocol_folder],ROOT,protocol_log)
        protocol_result=protocol_folder/'results.json';protocol=json.loads(protocol_result.read_text())
        artifacts.extend([protocol_log,protocol_result,*healthy_report_artifacts(protocol,'ldpc')])
        records['protocol']=dict(status='PASS',runs=len(protocol['records']),results=str(protocol_result.relative_to(ROOT)))
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS LDPC {args.suite}')

if __name__=='__main__':main()
