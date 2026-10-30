#!/usr/bin/env python3
"""Select exact FIR accumulator widths from legal input-box bounds; optionally
verify configured widths, raw sums, saturation and configuration rejection in RTL.
Also compare compact per-level/per-axis trees with the former uniform tree.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
from regression_evidence import ROOT, begin, finish, write_json, require_unoptimized, questa_paths
sys.path.insert(0, str(ROOT/'common/python'))
import fir_fixed as fixed
import fir_widths as widths
from fir_cases import build_taps, save
from run_fir import CASES as NATIVE_CASES
from sat_diag import SatStats

CASES=tuple((f'{kind}_l{lanes}_t{tmax}',kind,lanes,tmax) for kind,lanes,tmax in NATIVE_CASES)+(
    ('rounding_edge','rounding_edge',0,1),('minimum_complex','minimum_complex',2,3),('zero','zero',2,2),
    ('tree_full_scale','tree_full_scale',6,6))
SCENARIOS={'stream':[], 'stalled':['+STALL_INPUT','+STALL_OUTPUT'],
           'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}
SCOPE=('Exact complex FIR accumulator range over all signed18 input components for each loaded tap set, '
       'including half-up bias and every frame edge/partial sum; unchanged Q17 taps and Q15 outputs. '
       'Runtime rejection protects reduced-width configurations; exact products and every node of compact/uniform trees are observed. '
       'FPGA resources and physical timing await synthesis.')


def row_hash(rows):
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()


def taps_for(index,kind):
    if kind=='rounding_edge':return [(65536,0)]
    if kind=='minimum_complex':return [(-131072,-131072)]*8
    if kind=='tree_full_scale':return [(-131072,-131072)]*64
    if kind=='zero':return [(0,0)]*3
    return fixed.quantize_taps(build_taps(kind,np.random.default_rng(31+index)))


def workloads(taps):
    rng=np.random.default_rng(8151)
    signals=[[tuple(map(int,row)) for row in rng.integers(-131072,131072,(73,2))],
             [(131071,-131072)],[(32768,0),(0,0),(0,0)]]
    for axis in range(2):
        for upper in (False,True):
            sequence=[]
            for hr,hi in taps:
                candidates=[((xr,xi),(hr*xr-hi*xi,hr*xi+hi*xr)[axis])
                            for xr in (-131072,131071) for xi in (-131072,131071)]
                sequence.append((max if upper else min)(candidates,key=lambda row:row[1])[0])
            signals.append(list(reversed(sequence)))
    return signals


def raw_convolution(samples,taps):
    # Each product and all sums in this experiment are exact integers below 2^53,
    # so complex128 convolution is an independent exact pre-rounding reference.
    z=np.convolve(np.array([re+1j*im for re,im in samples]),np.array([re+1j*im for re,im in taps]))
    if np.max(abs(z))>=2**52 or not np.all(z.real==np.rint(z.real)) or not np.all(z.imag==np.rint(z.imag)):
        raise RuntimeError('Exact integer range of independent convolution exceeded')
    return [(int(re),int(im)) for re,im in zip(z.real,z.imag)]


def fixture(index,spec,folder=None):
    name,kind,lanes,tmax=spec;taps=taps_for(index,kind)
    signals=workloads(taps);inputs=[];outputs=[];raw=[];stats=SatStats()
    for signal in signals:
        sums=raw_convolution(signal,taps)
        actual=fixed.filter(signal,taps,stats=stats)
        expected=[tuple(fixed.sat18((value+65536)>>17) for value in pair) for pair in sums]
        if actual!=expected:raise RuntimeError('Production FIR differs from independent convolution')
        inputs.extend((re,im,int(k==len(signal)-1)) for k,(re,im) in enumerate(signal))
        outputs.extend((re,im,int(k==len(actual)-1)) for k,(re,im) in enumerate(actual));raw.extend(sums)
    intervals=widths.bounds(taps)
    observed={axis:[min(pair[i] for pair in raw),max(pair[i] for pair in raw)] for i,axis in enumerate(('re','im'))}
    if observed!=intervals:raise RuntimeError('Box-corner fixtures did not attain all exact bounds')
    counts=[stats.counts.get(stage,{}).get(sign,0) for stage in ('output.re','output.im') for sign in ('pos','neg')]
    record=dict(case=name,log2lanes=lanes,log2tmax=tmax,taps=[list(tap) for tap in taps],input_hash=row_hash(inputs),
                coefficient_hash=row_hash(taps),raw_hash=row_hash(raw),output_hash=row_hash(outputs),
                bounds=intervals,observed_bounds=observed,selected_width=widths.select(taps),default_width=38+tmax,
                frames=len(signals),inputs=len(inputs),outputs=len(outputs),saturation=counts,
                clamp_events=sum(counts),fractional_bits=17,tree_layout=widths.tree_layout(lanes),
                issues=len(outputs)*((len(taps)+(1<<lanes)-1)//(1<<lanes)))
    if folder is not None:
        folder.mkdir(parents=True,exist_ok=True)
        for filename,rows in (('cfg',taps),('in',inputs),('out',outputs),('accumulator',raw)):
            save(folder/(filename+'.txt'),rows)
        (folder/'saturation_expected.txt').write_text(' '.join(map(str,counts))+'\n')
    return record


def report():
    return dict(scope=SCOPE,records=[fixture(index,spec) for index,spec in enumerate(CASES)],
                rtl_verified=False,rtl_equivalence=[],rtl_guards=[],rtl_negative=[])


def check_acceptance(result):
    records=result['records']
    if len(records)!=len(CASES) or {r['case'] for r in records}!={s[0] for s in CASES}:
        raise RuntimeError('Incomplete/duplicated FIR width coverage')
    for index,spec in enumerate(CASES):
        row=next(r for r in records if r['case']==spec[0])
        if row!=fixture(index,spec):raise RuntimeError('Inconsistent FIR width measurement: '+spec[0])
        if not widths.fits(row['bounds'],row['selected_width']):raise RuntimeError('Unsafe FIR width')
        if row['selected_width']>18 and widths.fits(row['bounds'],row['selected_width']-1):
            raise RuntimeError('Nonminimal FIR accumulator width')
    if not result['rtl_verified']:
        if result['rtl_equivalence'] or result['rtl_guards'] or result['rtl_negative']:
            raise RuntimeError('Unverified RTL records')
        return
    expected={(r['case'],w,c,a,s) for r in records for w in {r['selected_width'],r['default_width']}
              for c in (0,1) for a in (1,0) for s in SCENARIOS}
    proof=result['rtl_equivalence']
    if len(proof)!=len(expected) or {(r['case'],r['width'],r['compact_tree'],r['active'],r['scenario']) for r in proof}!=expected:
        raise RuntimeError('Incomplete/duplicated actual FIR width equivalence')
    for r in proof:
        row=next(row for row in records if row['case']==r['case'])
        if (r['outputs']!=row['outputs'] or r['raw_sums']!=row['outputs'] or r['saturation']!=row['saturation']
                or r['bounds_verified'] is not True or r['tree_nodes']!=row['issues']*(2*(1<<row['log2lanes'])-1)
                or r['product_words']!=4*(1<<row['log2lanes'])*row['issues'] or not isinstance(r['cycles'],int) or r['cycles']<=0):
            raise RuntimeError('Incomplete FIR arithmetic observers')
    for row in records:
        for active in (0,1):
            if len({r['cycles'] for r in proof if r['case']==row['case'] and r['active']==active and r['scenario']=='stream'})!=1:
                raise RuntimeError('FIR stream latency changed with arithmetic layout')
    expected={(r['case'],w,a,reject) for r in records for w,reject in
              [(r['selected_width'],False)]+([(r['selected_width']-1,True)] if r['selected_width']>18 else []) for a in (1,0)}
    guards=result['rtl_guards']
    if len(guards)!=len(expected) or {(r['case'],r['width'],r['active'],r['rejected']) for r in guards}!=expected:
        raise RuntimeError('Incomplete/duplicated actual FIR configuration guards')
    if any(r['sticky_reset_recovery_verified'] is not True for r in guards):raise RuntimeError('Missing guard lifecycle evidence')
    controls=result['rtl_negative']
    if (len(controls)!=6 or {(r['active'],r['tag']) for r in controls}!={(a,t) for a in (0,1) for t in ('ACCUMULATOR','TREE','PRODUCT')}
            or any(r['returncode']==0 for r in controls)):
        raise RuntimeError('Incomplete FIR arithmetic negative controls')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
    artifacts=[]
    for index,spec in enumerate(CASES):
        vector=base/'vectors'/spec[0]
        if fixture(index,spec,vector)!=result['records'][index]:raise RuntimeError('RTL fixture differs from selection')
        artifacts.extend(vector.glob('*.txt'))
    for active in (1,0):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
                 ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/fir_saturation_check.sv',
                 ROOT/'rtl/tb/fir_tb.sv',ROOT/'rtl/tb/fir_width_guard_tb.sv'],work,work/'compile.log')
        artifacts.append(work/'compile.log')
        positive=work/'run.do';negative=work/'negative.do'
        positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
        artifacts.extend((positive,negative))
        def run(top,options,label,bad=False):
            command=[bindir/'vsim','-64','-c','-quiet',top,f'-gRESET_ACTIVE={active}',*options,
                     '-do',negative.name if bad else positive.name]
            completed=subprocess.run(list(map(str,command)),cwd=work,capture_output=True,text=True,timeout=90)
            text=completed.stdout+completed.stderr;path=work/(label+'.log');path.write_text(text);artifacts.append(path)
            if not bad and (completed.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):
                raise RuntimeError('FIR width RTL failed: '+label+'\n'+text[-4000:])
            return text,completed.returncode
        for row in result['records']:
            name=row['case'];vector=base/'vectors'/name
            parameters=[f'-gLOG2LANES={row["log2lanes"]}',f'-gLOG2TMAX={row["log2tmax"]}',f'+VECTORS={vector}']
            for width in sorted({row['default_width'],row['selected_width']}):
                for compact in (0,1):
                    if active==1:
                        log=work/f'lint_{name}_w{width}_c{compact}.log'
                        execute(['verilator','--lint-only','-Wall','--top-module','fir_runtime',f'-GACC_WIDTH={width}',f'-GCOMPACT_TREE={compact}',
                                 f'-GLOG2LANES={row["log2lanes"]}',f'-GLOG2TMAX={row["log2tmax"]}',f'-I{pilot}',*SOURCES],ROOT,log)
                        artifacts.append(log)
                    for scenario,options in SCENARIOS.items():
                        text,_=run('work.fir_tb',[*parameters,f'-gACC_WIDTH={width}',f'-gCOMPACT_TREE={compact}','+CHECK_ACCUMULATOR','+CHECK_TREE',*options],f'{name}_w{width}_c{compact}_{scenario}')
                        numeric=re.search(r'PASS FIR: (\d+) outputs, (\d+) cycles',text)
                        sums=re.search(r'PASS FIR ACCUMULATOR: (\d+)',text)
                        sat=re.search(r'PASS FIR SATURATION: (\d+) (\d+) (\d+) (\d+)',text)
                        bounds=re.search(r'PASS BOUNDS fir counts: (\d+) (\d+) (\d+) (\d+)',text)
                        tree=re.search(r'PASS FIR TREE: (\d+) (\d+) (\d+)',text)
                        expected_tree=(compact,row['issues']*(2*(1<<row['log2lanes'])-1),4*(1<<row['log2lanes'])*row['issues'])
                        if (not numeric or int(numeric[1])!=row['outputs'] or not sums or int(sums[1])!=row['outputs']
                                or not sat or list(map(int,sat.groups()))!=row['saturation'] or not bounds or min(map(int,bounds.groups()[:3]))<1
                                or not tree or tuple(map(int,tree.groups()))!=expected_tree):
                            raise RuntimeError('Incomplete FIR width/product/tree/clamp/bounds evidence')
                        result['rtl_equivalence'].append(dict(case=name,width=width,compact_tree=compact,active=active,scenario=scenario,
                                                             outputs=int(numeric[1]),raw_sums=int(sums[1]),saturation=list(map(int,sat.groups())),
                                                             tree_nodes=int(tree[2]),product_words=int(tree[3]),bounds_verified=True,cycles=int(numeric[2])))
            for width,reject in [(row['selected_width'],False)]+([(row['selected_width']-1,True)] if row['selected_width']>18 else []):
                text,_=run('work.fir_width_guard_tb',[*parameters,f'-gACC_WIDTH={width}',f'-gEXPECT_REJECT={int(reject)}'],f'{name}_guard_w{width}')
                marker=re.search(r'PASS FIR WIDTH GUARD: (\d+) (\d+) (\d+)',text)
                if not marker or tuple(map(int,marker.groups()))!=(width,int(reject),len(row['taps'])):
                    raise RuntimeError('Missing FIR configuration lifecycle evidence')
                result['rtl_guards'].append(dict(case=name,width=width,active=active,rejected=reject,sticky_reset_recovery_verified=True))
            print(f'PASS FIR widths {name}: {row["default_width"]} -> {row["selected_width"]}, reset={active}',flush=True)
        row=result['records'][0]
        for flag,tag in (('ACCUMULATOR','ACCUMULATOR'),('TREE','TREE'),('PRODUCT','PRODUCT')):
            text,rc=run('work.fir_tb',[f'-gLOG2LANES={row["log2lanes"]}',f'-gLOG2TMAX={row["log2tmax"]}',
                                     f'-gACC_WIDTH={row["selected_width"]}',f'+VECTORS={base/"vectors"/row["case"]}',
                                     '+CHECK_ACCUMULATOR','+CHECK_TREE','+INJECT_'+flag],'negative_'+tag.lower(),bad=True)
            if rc==0 or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or 'PASS FIR:' in text:
                raise RuntimeError('FIR arithmetic fault was not detected: '+tag)
            result['rtl_negative'].append(dict(active=active,returncode=rc,tag=tag))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/fir_width_sweep/results.json')
    parser.add_argument('--verify-rtl',action='store_true');args=parser.parse_args()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=[]
        if args.verify_rtl:artifacts=verify_rtl(result,args.output.parent/'equivalence')
        check_acceptance(result)
        write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    for row in result['records']:print(row['case'],row['default_width'],'->',row['selected_width'])
    print('PASS FIR width selection; RTL verified='+str(result['rtl_verified']))


if __name__=='__main__':main()
