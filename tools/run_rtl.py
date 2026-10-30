#!/usr/bin/env python3
"""Fixed-point tests, strict lint, actual streaming UVM and negative controls."""
import argparse
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_numeric_failure
from rtl_cases import BLOCKS,generate,support_vectors

# Library blocks and every modem core; modems may instantiate the pilot core.
SOURCES=sorted((ROOT/'rtl/common').rglob('*.sv'))+sorted((ROOT/'rtl/modems').glob('*/*.sv'))


def execute(command,cwd,log):
    result=subprocess.run([str(x) for x in command],cwd=cwd,capture_output=True,text=True)
    text=result.stdout+result.stderr;Path(log).write_text(text)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {command[0]}\n{text[-10000:]}')
    return text


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all')
    parser.add_argument('--block',choices=list(BLOCKS))
    parser.add_argument('--questa-bin',type=Path)
    parser.add_argument('--output',type=Path,help='new isolated output directory')
    args=parser.parse_args()
    if not __debug__:raise RuntimeError('Run verification without Python optimization (-O)')
    output=ROOT/'build/rtl';output=output/'single'/args.block if args.block else output
    if args.questa_bin:output=output/'questa_fse'
    if args.output:output=args.output.resolve()
    output.mkdir(parents=True,exist_ok=args.output is None)
    evidence=begin();target=output/f'{args.suite}_results.json'
    write_json(target,dict(evidence,status='RUNNING'));result=dict(suite=args.suite)
    artifacts=[]
    if args.suite in ('python','all'):
        result['python_tests']=0
        for name in ('fixed_point','rtl_tools'):
            log=output/f'python_{name}.log'
            text=execute([sys.executable,ROOT/f'tests/test_{name}.py'],ROOT,log)
            match=re.search(r'Ran (\d+) tests',text)
            if not match:raise RuntimeError('Missing Python test count')
            result['python_tests']+=int(match[1]);artifacts.append(log)
    if args.suite in ('lint','all'):
        tool=shutil.which('verilator')
        if not tool:raise RuntimeError('Verilator is required')
        tops=[config['top'] for config in BLOCKS.values()]+['axis_fifo','sync_ram','sync_rom','bit_sync','reset_sync','fxp_divide_seq','fxp_mrc2','costas_stream','rtl_synth_top']
        for top in tops:
            log=output/f'lint_{top}.log'
            text=execute([tool,'--lint-only','-Wall','--top-module',top,f'-I{ROOT/"rtl/modems/bpsk_costas_2008_08_25"}',*SOURCES,*([ROOT/'rtl/rtl_synth_top.sv'] if top=='rtl_synth_top' else [])],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: {top}')
            artifacts.append(log)
        result['lint_tops']=tops
    if args.suite in ('hdl','all'):
        default_bin,uvm=questa_paths();bindir=args.questa_bin.resolve() if args.questa_bin else default_bin
        if not (bindir/'vsim').is_file():raise RuntimeError('Missing Questa executable')
        records=[]
        for block,config in BLOCKS.items():
            if args.block and block!=args.block:continue
            vectors=output/block/'vectors.txt';count=generate(block,vectors);artifacts.append(vectors)
            for active in (1,0):
                work=output/block/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                defines=[f'+define+{config["define"]}']+(['+define+RTL_RESET_LOW'] if active==0 else [])
                execute([bindir/'vlog','-64','-sv','+define+UVM_NO_DPI',*defines,f'+incdir+{uvm/"src"}',
                         f'+incdir+{ROOT/"rtl/modems/bpsk_costas_2008_08_25"}',uvm/'src/uvm_pkg.sv',*SOURCES,ROOT/'rtl/tb/stream_tb.sv'],work,work/'compile.log')
                base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.rtl_stream_top',f'+VECTORS={vectors}',f'+LATENCY={config["latency"]}']
                text=execute([*base,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/'simulation.log')
                match=re.search(r'Checked (\d+) RTL samples, discarded (\d+) on reset; (\d+) saturations',text)
                if not match or not re.search(r'UVM_ERROR\s*:\s*0',text) or not re.search(r'UVM_FATAL\s*:\s*0',text) or re.search(r'\*\* (Error|Fatal)',text):
                    raise RuntimeError(f'RTL UVM failed: {block}\n{text[-10000:]}')
                checked,discarded,saturations=map(int,match.groups())
                if checked+discarded!=2*count:raise RuntimeError('Incomplete RTL vector coverage')
                bad=subprocess.run([str(x) for x in [*base,'+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
                negative=bad.stdout+bad.stderr;(work/'negative.log').write_text(negative);require_numeric_failure(negative)
                artifacts += [work/'compile.log',work/'simulation.log',work/'negative.log']
                records.append(dict(block=block,reset_active=active,samples=checked,discarded_on_reset=discarded,saturations=saturations,negative_control='PASS'))
                print(f'PASS {block}, reset={active}: {checked} bit-exact samples, {discarded} discarded on reset',flush=True)
        if not args.block:
            work=output/'support';work.mkdir(exist_ok=True)
            vectors=work/'vectors.txt';support_vectors(vectors)
            if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
            execute([bindir/'vlog','-64','-sv',f'+incdir+{ROOT/"rtl/modems/bpsk_costas_2008_08_25"}',*SOURCES,ROOT/'rtl/tb/support_tb.sv'],work,work/'compile.log')
            base=[bindir/'vsim','-64','-c','-quiet','work.rtl_support_top',f'-gROM_FILE={ROOT/"rtl/common/mem/test_rom.mem"}',f'+VECTORS={vectors}']
            text=execute([*base,'-do','run -all; quit -code 0'],work,work/'simulation.log')
            if 'PASS RTL support:' not in text or '** Fatal' in text or '** Error' in text:raise RuntimeError(text[-10000:])
            bad=subprocess.run([str(x) for x in [*base,'+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
            text=bad.stdout+bad.stderr;(work/'negative.log').write_text(text)
            if '** Fatal' not in text or '[NUMERIC]' not in text or 'PASS RTL support:' in text:raise RuntimeError('Support negative control was not detected')
            artifacts += [vectors,work/'compile.log',work/'simulation.log',work/'negative.log']
            result['support']='PASS'
        result['hdl']=records
    result.update(status='PASS',**finish(evidence,artifacts));write_json(target,result)
    print(f'PASS RTL {args.suite}')


if __name__=='__main__':main()
