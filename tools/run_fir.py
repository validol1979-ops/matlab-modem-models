#!/usr/bin/env python3
"""Runtime FIR reference, strict lint and Questa numeric scoreboard
(rtl/common/fir_runtime.sv driven by rtl/tb/fir_tb.sv)."""
import argparse
from pathlib import Path
import subprocess
import re
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_pass
from run_rtl import execute,SOURCES
from fir_cases import vectors

DUT=ROOT/'rtl/common/fir_runtime.sv'
# (taps_kind, LOG2LANES, LOG2TMAX)
CASES=[('harger',0,2),('harger',2,2),('impulse',1,3),('wsinc',3,6),('wsinc',6,6),
       ('complex',2,4),('single',0,1),('long',4,7)]
NEGATIVE=('wsinc',3,6)
LINT_CASES=sorted({(l,t) for _,l,t in CASES})
PASS=r'PASS FIR: (\d+) outputs, (\d+) cycles'
BOUNDS=r'PASS BOUNDS fir counts: (\d+) (\d+) (\d+) (\d+)'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def folder_for(base,index,kind,log2lanes,log2tmax):
    return base/f'case{index}_{kind}_l{log2lanes}_t{log2tmax}'


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['python','lint','hdl','all'],default='all');args=parser.parse_args()
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    if args.suite in ('all','lint','hdl') and not DUT.is_file():
        raise RuntimeError(f'Missing DUT {DUT}: the fir RTL is not written yet')
    output=ROOT/'build/rtl/fir';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/f'{args.suite}_results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records={}
    if args.suite in ('all','python'):
        log=output/'test_fir_fixed.log';execute([sys.executable,ROOT/'tests/test_fir_fixed.py'],ROOT,log);artifacts.append(log)
        records['python']='PASS'
        log=output/'test_fir_width_sweep.log';execute([sys.executable,ROOT/'tests/test_fir_width_sweep.py'],ROOT,log);artifacts.append(log)
        records['width_python']='PASS'
    if args.suite in ('all','lint'):
        for log2lanes,log2tmax in LINT_CASES:
            parameters=[f'-GLOG2LANES={log2lanes}',f'-GLOG2TMAX={log2tmax}']
            log=output/f'lint_fir_runtime_{log2lanes}_{log2tmax}.log'
            text=execute(['verilator','--lint-only','-Wall','--top-module','fir_runtime',*parameters,f'-I{PILOT}',*SOURCES],ROOT,log)
            if '%Warning' in text:raise RuntimeError(f'Lint warnings: fir_runtime lanes={log2lanes} tmax={log2tmax}')
            artifacts.append(log)
        records['lint']='PASS'
    if args.suite in ('all','hdl'):
        bindir,_=questa_paths();base=output/'vectors';reports={}
        for index,(kind,log2lanes,log2tmax) in enumerate(CASES):
            folder=folder_for(base,index,kind,log2lanes,log2tmax)
            reports[index]=vectors(folder,kind,transactions=4,seed=31+index)
        artifacts.extend(list(base.rglob('*.txt'))+list(base.rglob('saturation.json')))
        for index,(kind,log2lanes,log2tmax) in enumerate(CASES):
            folder=folder_for(base,index,kind,log2lanes,log2tmax);report=reports[index]
            for active in (1,0):
                work=output/f'{kind}_l{log2lanes}_t{log2tmax}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/fir_saturation_check.sv',ROOT/'rtl/tb/fir_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.fir_tb',f'-gLOG2LANES={log2lanes}',
                        f'-gLOG2TMAX={log2tmax}',f'-gRESET_ACTIVE={active}']
                bounds_counts={}
                for scenario,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                         ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                         ('cfgreset',['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    text=execute([*common,f'+VECTORS={folder}',*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/f'{scenario}.log')
                    match=re.search(PASS,text)
                    if not match or int(match.group(1))!=report['outputs'] or re.search(r'\*\* (?:Error|Fatal)',text):
                        raise RuntimeError(text[-6000:])
                    observed=re.search(r'PASS FIR SATURATION: (\d+) (\d+) (\d+) (\d+)',text)
                    expected=[report['saturation']['stages'].get(stage,{}).get(sign,0)
                              for stage in ('output.re','output.im') for sign in ('pos','neg')]
                    if not observed or list(map(int,observed.groups()))!=expected:
                        raise RuntimeError('Missing or mismatched RTL saturation observations')
                    bounds=re.search(BOUNDS,text)
                    if not bounds or min(int(value) for value in bounds.groups()[:3])<1:
                        raise RuntimeError(f'Missing or unexercised FIR bounds evidence for {scenario}')
                    bounds_counts[scenario]=dict(zip(('active','state','bank','simultaneous'),map(int,bounds.groups())))
                    artifacts.append(work/f'{scenario}.log')
                negative_controls={}
                if (kind,log2lanes,log2tmax)==NEGATIVE:
                    script=work/'negative_controls.do'
                    script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.append(script)
                    for flag,tag,name in [('+INJECT_MISMATCH','[NUMERIC]','negative'),
                                          ('+INJECT_SAT_MISMATCH','[SATURATION]','negative_saturation'),
                                          ('+INJECT_BOUND_MISMATCH','[BOUNDS]','negative_bounds')]:
                        bad=subprocess.run([str(x) for x in [*common,f'+VECTORS={folder}',flag,'-do',script.name]],cwd=work,capture_output=True,text=True,timeout=60)
                        negative=bad.stdout+bad.stderr;(work/f'{name}.log').write_text(negative)
                        if bad.returncode==0 or not re.search(r'\*\* Fatal:.*'+re.escape(tag),negative) or re.search(PASS,negative):
                            raise RuntimeError(f'{name} control not detected')
                        artifacts.append(work/f'{name}.log')
                        negative_controls[name]={'returncode':bad.returncode,'detected_tag':tag}
                records[f'{kind}_l{log2lanes}_t{log2tmax}_reset_{active}']=dict(report,saturation_rtl_verified=True,bounds_rtl_verified=True,bounds_checks=bounds_counts,negative_controls=negative_controls)
                print(f'PASS FIR {kind} lanes={log2lanes} tmax={log2tmax} reset={active}',flush=True)
    if args.suite in ('all','hdl'):
        protocols={}
        for active in (1,0):
            work=output/f'protocol_reset{active}';work.mkdir(parents=True,exist_ok=True)
            if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
            log=work/'compile.log'
            execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT}/rtl/tb',*SOURCES,
                     ROOT/'rtl/tb/fir_protocol_tb.sv'],work,log)
            artifacts.append(log)
            observations={}
            for scenario in range(4):
                log=work/f'scenario{scenario}.log'
                text=execute([bindir/'vsim','-64','-c','-quiet','work.fir_protocol_tb',
                              f'-gRESET_ACTIVE={active}',f'-gSCENARIO={scenario}',
                              '-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                match=re.search(r'PASS FIR PROTOCOL scenario(\d+): cfg(\d+) input(\d+) output(\d+)',text)
                if not match or int(match[1])!=scenario or re.search(r'\*\* (?:Error|Fatal)',text):
                    raise RuntimeError(f'FIR protocol scenario {scenario} failed: {text[-2000:]}')
                observations[f'scenario{scenario}']=dict(zip(('cfg','input','output'),map(int,match.groups()[1:])))
                artifacts.append(log)
            protocols[f'reset{active}']=observations
        records['protocols']=dict(rtl_verified=True,scenarios=protocols)
    if args.suite in ('all','hdl') and not any(counts['simultaneous']>0
            for record in records.values() if isinstance(record,dict)
            for counts in record.get('bounds_checks',{}).values()):
        raise RuntimeError('No simultaneous FIR FIFO push/pop was exercised')
    if args.suite in ('all','hdl'):
        from fir_width_sweep import check_acceptance
        import json
        report_path=ROOT/'build/rtl/fir_width_sweep/rtl_results.json'
        log=output/'width_selection.log'
        execute([sys.executable,ROOT/'tools/fir_width_sweep.py','--verify-rtl','--output',report_path],ROOT,log)
        report=json.loads(report_path.read_text());require_pass(report);check_acceptance(report)
        if not report['rtl_verified']:raise RuntimeError('Missing FIR width RTL evidence')
        artifacts.extend([report_path,log,*(ROOT/path for path in report['artifact_hashes'])])
        records['width_selection']=dict(rtl_verified=True,result=str(report_path.relative_to(ROOT)),
                                        normal=len(report['rtl_equivalence']),guards=len(report['rtl_guards']),negative=len(report['rtl_negative']))
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)));print(f'PASS FIR {args.suite}')

if __name__=='__main__':main()
