#!/usr/bin/env python3
"""Integer FFT reference, strict lint, Questa numeric scoreboard (fft_r2sdf)."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths
from run_rtl import execute,SOURCES
from fft_cases import vectors,read_saturation_expected,boundary_vectors

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
# (LOG2N, frames, IN_WIDTH, WIDTH): the default 18/20 core and the wide 22/24 core of the STFT.
BOUNDARY=(2,5,18,20)
CASES=[(2,24,18,20),(5,24,18,20),(6,24,18,20),(10,6,18,20),(6,24,22,24),(8,8,22,24),BOUNDARY]
PASS=r'PASS FFT: (\d+) outputs, (\d+) frames, (\d+) cycles'
SATPASS=r'PASS FFT SATURATION: (\d+) evaluations, (\d+) events'
BOUNDS=r'PASS BOUNDS fft counts: '+' '.join([r'(\d+)']*10)
BOUND_FIELDS=('stage','twiddle','delay_ram','reorder','fifo','valid_sum','valid_diff','masked','flush','simultaneous')
NORMAL=['stream','gaps','backpressure','midreset','outreset']


def saturation_totals(folder):
    log2n,rows=read_saturation_expected(folder/'saturation_expected.txt')
    return sum(row[0] for row in rows),sum(row[1]+row[2] for row in rows)


def twiddle(log2n):return ROOT/f'rtl/common/mem/fft_twiddle_{1<<log2n}.mem'


def case_name(log2n,frames,in_width,width):
    if (log2n,frames,in_width,width)==BOUNDARY:return 'n4_boundaries'
    return f'n{1<<log2n}' if width==20 else f'n{1<<log2n}_w{width}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    output=ROOT/'build/rtl/fft';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_fft_fixed.log';execute([sys.executable,ROOT/'tests/test_fft_fixed.py'],ROOT,log);artifacts.append(log)
        log=output/'fft_tables.log';execute([sys.executable,ROOT/'tools/fft_tables.py','--check'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
    if args.suite in ('all','lint'):
        for log2n,in_width,width in [(n,18,20) for n in (2,3,5,6,10)]+[(6,22,24),(8,22,24)]:
            log=output/f'lint_fft_r2sdf_{1<<log2n}_w{width}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','fft_r2sdf',f'-GLOG2N={log2n}',f'-GIN_WIDTH={in_width}',f'-GWIDTH={width}',
                          f'-GTWIDDLE_FILE="{twiddle(log2n).relative_to(ROOT)}"',f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: fft_r2sdf LOG2N={log2n} WIDTH={width}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for log2n,frames,in_width,width in CASES:
            size=1<<log2n;name=case_name(log2n,frames,in_width,width);folder=base/name
            if (log2n,frames,in_width,width)==BOUNDARY:
                reports[name]={'stream':boundary_vectors(folder),'gaps':boundary_vectors(folder/'gaps',gaps=True)}
            else:
                reports[name]={'stream':vectors(folder,log2n,frames=frames,seed=31+log2n+width,in_width=in_width,width=width),
                               'gaps':vectors(folder/'gaps',log2n,frames=frames,seed=97+log2n+width,gaps=True,in_width=in_width,width=width)}
        artifacts.extend(list(base.rglob('*.txt'))+list(base.rglob('saturation.json')))
        seen=set()
        for log2n,frames,in_width,width in CASES:
            size=1<<log2n;name=case_name(log2n,frames,in_width,width);folder=base/name
            for active in (1,0):
                work=output/f'{name}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/fft_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.fft_tb',f'-gLOG2N={log2n}',f'-gIN_WIDTH={in_width}',f'-gWIDTH={width}',f'-gRESET_ACTIVE={active}',
                        f'-gTWIDDLE_FILE={twiddle(log2n)}']
                bounds_counts={}
                for scenario,report,folder_,options in [
                        ('stream',reports[name]['stream'],folder,[]),
                        ('gaps',reports[name]['gaps'],folder/'gaps',[]),
                        ('backpressure',reports[name]['gaps'],folder/'gaps',['+STALL_INPUT','+STALL_OUTPUT']),
                        ('midreset',reports[name]['gaps'],folder/'gaps',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                        ('outreset',reports[name]['gaps'],folder/'gaps',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder_}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['frames']*size or int(match.group(2))!=report['frames'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    marker=re.search(SATPASS,text)
                    if not marker:
                        raise RuntimeError(f'Missing FFT saturation verification: {name} reset={active} {scenario}')
                    totals=saturation_totals(folder_)
                    if (int(marker.group(1)),int(marker.group(2)))!=totals:
                        raise RuntimeError(f'saturation marker mismatch in {name} reset={active} {scenario}: '
                                           f'{marker.group(1)} evaluations, {marker.group(2)} events, expected {totals[0]}, {totals[1]}')
                    bounds=re.search(BOUNDS,text)
                    if not bounds:
                        raise RuntimeError(f'Missing FFT bounds evidence: {name} reset={active} {scenario}')
                    counts=dict(zip(BOUND_FIELDS,map(int,bounds.groups())))
                    if any(counts[field]<1 for field in BOUND_FIELDS if field not in ('delay_ram','simultaneous')) or (log2n>5 and counts['delay_ram']<1):
                        raise RuntimeError(f'Unexercised FFT bounds monitor: {name} reset={active} {scenario}: {counts}')
                    if log2n<=5 and counts['delay_ram']!=0:
                        raise RuntimeError(f'Unexpected RAM delay evidence for register-only FFT: {name}')
                    bounds_counts[scenario]=counts
                    seen.add((name,active,scenario))
                    artifacts.append(work/f'{scenario}.log')
                any_marker=any((name,active,scenario) in seen for scenario in NORMAL)
                monitored=all((name,active,scenario) in seen for scenario in NORMAL)
                if any_marker and not monitored:
                    missing=[scenario for scenario in NORMAL if (name,active,scenario) not in seen]
                    raise RuntimeError(f'saturation monitor incomplete for {name} reset={active}: no marker in {missing}')
                script=work/'negative_bounds.do'
                script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                artifacts.append(script)
                bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}','+INJECT_BOUND_MISMATCH','-do',script.name]],cwd=work,capture_output=True,text=True,timeout=60)
                negative=bad.stdout+bad.stderr;(work/'negative_bounds.log').write_text(negative)
                if bad.returncode==0 or not re.search(r'\*\* Fatal:.*\[BOUNDS\]',negative) or re.search(r'PASS FFT|PASS BOUNDS',negative):
                    raise RuntimeError(f'FFT bounds negative control not detected: {name} reset={active}, rc={bad.returncode}')
                artifacts.append(work/'negative_bounds.log')
                negative_bounds=dict(returncode=bad.returncode,detected_tag='[BOUNDS]')
                if name=='n64':
                    for control,flag in (('negative','+INJECT_MISMATCH'),('bad_last','+BAD_LAST')):
                        command=script.name if control=='negative' else 'onerror {quit -code 1}; run -all; quit -code 0'
                        bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={base/f"n{size}"}',flag,'-do',command]],cwd=work,capture_output=True,text=True,timeout=90)
                        negative=bad.stdout+bad.stderr;(work/f'{control}.log').write_text(negative)
                        if control=='negative':
                            if not bad.returncode or not re.search(r'\*\* Fatal:.*\[NUMERIC\]',negative) or re.search(PASS,negative):raise RuntimeError(f'{control} control not detected')
                        elif bad.returncode or 'PASS FFT BAD_LAST' not in negative or re.search(r'\*\* (?:Error|Fatal)',negative):
                            raise RuntimeError(f'{control} control not detected')
                        artifacts.append(work/f'{control}.log')
                    for control,flag in [('negative_saturation','+INJECT_SAT_MISMATCH'),
                                         ('negative_validity','+INJECT_SAT_EVAL_MISMATCH')]:
                        bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={base/f"n{size}"}',flag,'-do',script.name]],cwd=work,capture_output=True,text=True,timeout=90)
                        negative=bad.stdout+bad.stderr;(work/f'{control}.log').write_text(negative)
                        if not bad.returncode or not re.search(r'\*\* Fatal:.*\[SATURATION\]',negative) or re.search(r'PASS FFT',negative):
                            raise RuntimeError(f'{control} control not detected')
                        artifacts.append(work/f'{control}.log')
                records[f'{name}_reset_{active}']=dict(reports[name],saturation_rtl_verified=monitored,
                                                       bounds_rtl_verified=True,bounds_checks=bounds_counts,negative_bounds=negative_bounds)
                print(f'PASS FFT {name} reset={active} saturation_rtl_verified={monitored} bounds_rtl_verified=True',flush=True)
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS FFT {args.suite}')

if __name__=='__main__':main()
