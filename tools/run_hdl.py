#!/usr/bin/env python3
"""Запуск настоящего UVM testbench в Questa с общими тестовыми векторами."""
from pathlib import Path
import argparse
import os
import re
import shutil
import subprocess
import sys
import json
from generate_vectors import generate, ROOT
from regression_evidence import begin, finish, write_json, questa_paths, require_numeric_failure


def run(command, directory, logfile):
    result=subprocess.run([str(x) for x in command],cwd=directory,capture_output=True,text=True)
    logfile.write_text(result.stdout+result.stderr)
    if result.returncode:
        print(result.stdout+result.stderr)
        raise RuntimeError(f'Command failed with exit code {result.returncode}: {command[0]}')
    return result.stdout+result.stderr


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--modem')
    parser.add_argument('--all',action='store_true')
    parser.add_argument('--vectors', type=Path)
    parser.add_argument('--output-dir', type=Path)
    args=parser.parse_args()
    if not args.modem and not args.all: parser.error('Specify --modem NAME or --all')
    if args.vectors and (not args.modem or args.all): parser.error('--vectors requires a single --modem')
    if args.modem and (Path(args.modem).name!=args.modem or not (ROOT/'modems'/args.modem/'config.json').is_file()):
        parser.error('Unknown modem name')
    bindir,uvm=questa_paths()
    work=args.output_dir.resolve() if args.output_dir else (ROOT/'build/questa/single'/args.modem if args.modem else ROOT/'build/questa')
    evidence=begin()
    write_json(work/'results.json',[])
    work.mkdir(parents=True,exist_ok=True)
    if not (work/'work').exists(): run([bindir/'vlib','work'],work,work/'vlib.log')
    sources=['modem_dsp_pkg.sv','modem_if.sv','modem_model.sv','modem_uvm_pkg.sv']
    run([bindir/'vlog','-64','-sv','-work','work','+define+UVM_NO_DPI',f'+incdir+{uvm / "src"}',
         uvm/'src'/'uvm_pkg.sv',*[ROOT/'common'/'sv'/s for s in sources]],work,work/'compile.log')
    configs=[ROOT/'modems'/args.modem/'config.json'] if args.modem else sorted((ROOT/'modems').glob('*/config.json'))
    reports=[]
    for config in configs:
        name=config.parent.name
        # Явно заданные векторы позволяют проверять отсчёты исходной MATLAB-схемы.
        vectors=args.vectors.resolve() if args.vectors else generate(config)
        if args.vectors:
            for filename in ['config.txt', 'case_0.txt', 'case_1.txt', 'case_2.txt']:
                if not (vectors/filename).is_file(): raise FileNotFoundError(vectors/filename)
        run([bindir/'vlog','-64','-sv','-work','work',f'+incdir+{ROOT / "common" / "sv"}',
             config.parent/'sv'/'modem.sv',config.parent/'tb'/'testbench.sv'],work,work/f'{name}_compile.log')
        script='onerror {quit -code 1}; run -all; quit -code 0'
        output=run([bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.tb_top',
                    f'+CONFIG={vectors / "config.txt"}',f'+VECTORS={vectors}', '-do',script],work,work/f'{name}.log')
        if (not re.search(r'UVM_ERROR\s*:\s*0',output) or not re.search(r'UVM_FATAL\s*:\s*0',output)
                or 'Checked 4 frames' not in output or re.search(r'\*\* (?:Error|Fatal):?',output)):
            print(output); raise RuntimeError(f'UVM regression failed: {name}')
        match=re.search(r'Checked (\d+) frames, (\d+) complex samples; maximum error ([\deE.+-]+)',output)
        negative=subprocess.run([str(x) for x in [bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.tb_top',f'+CONFIG={vectors / "config.txt"}',f'+VECTORS={vectors}','+INJECT_MISMATCH','-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True)
        bad=negative.stdout+negative.stderr
        (work/f'{name}_negative.log').write_text(bad)
        require_numeric_failure(bad)
        artifacts=[work/f'{name}.log',work/f'{name}_negative.log',*sorted(vectors.glob('*.txt'))]
        reports.append(dict(modem=name,frames=int(match[1]),samples=int(match[2]),maximum_error=float(match[3]),status='PASS',negative_control='PASS',**finish(evidence,artifacts)))
        print(f'PASS {name} UVM: {match[1]} frames, {match[2]} samples, maximum error {match[3]}',flush=True)
    write_json(work/'results.json',reports)


if __name__=='__main__': main()
