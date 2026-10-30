#!/usr/bin/env python3
"""Explore the existing FFT WIDTH parameter; input Q15 and Q16 twiddles stay fixed.

WIDTH changes integer guard bits and the per-stage symmetric clamp, not the LSB
or twiddle precision. Compare the full fixed transform with NumPy on identical
legal signed18 input words. A simulation-qualified width is not an accepted
default change. Optional --verify-rtl checks the candidate and current control
on the same vectors, with unchanged RTL and parameter overrides only.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import subprocess
import sys

import numpy as np
from regression_evidence import ROOT, begin, finish, require_unoptimized, write_json, questa_paths
sys.path.insert(0,str(ROOT/'common/python'))
import fft_fixed as f
from sat_diag import SatTrace

INPUT_WIDTH=18
CURRENT_WIDTH=20
WIDTHS=(19,20,21,22,24)
SIZES=(64,256,1024)
SEED=31419
SQNR_BUDGET_DB=50.
EVM_BUDGET=.003
SCOPE=('Existing FFT integer guard-bit WIDTH sweep, fixed signed18/Q15 input and Q16 twiddles; '
       'NumPy FFT/N or N*IFFT on identical input words; finite seeded nominal envelope plus '
       'coherent inverse stress. No ADC, fractional-bit or twiddle-bit sweep, general capture '
       'region, resource estimate or new default width is claimed.')


class StageTrace(SatTrace):
    """Observe actual rounded pre-clamp values; equality to a rail is not a clamp."""
    def __init__(self):
        super().__init__();self.ranges={}

    def record(self,stage,value,limit,clamp='sym'):
        value=int(value)
        previous=self.ranges.get(stage,dict(minimum=value,maximum=value))
        self.ranges[stage]=dict(minimum=min(previous['minimum'],value),maximum=max(previous['maximum'],value),
                               low=-limit if clamp=='sym' else -limit-1,high=limit)
        return super().record(stage,value,limit,clamp)

    def stages(self):
        return {name:dict(self.ranges[name],evaluations=count,
                          positive_clamps=self.counts.get(name,{}).get('pos',0),
                          negative_clamps=self.counts.get(name,{}).get('neg',0))
                for name,count in sorted(self.evaluations.items())}


def row_hash(rows):
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()


def cases(n,seed=SEED):
    if n<4 or n>1024 or n&(n-1):raise ValueError('FFT experiment sizes must be powers of two in 4..1024')
    rng=np.random.default_rng(seed+n)
    pair=lambda array:[tuple(map(int,row)) for row in array]
    t=np.arange(n)
    tone=100000*np.exp(2j*np.pi*7*t/n)
    return [dict(case='forward_random',inverse=False,nominal=True,
                 rows=pair(rng.integers(-131072,131072,(n,2)))),
            dict(case='forward_tone',inverse=False,nominal=True,
                 rows=pair(np.rint(np.column_stack((tone.real,tone.imag))))),
            dict(case='forward_corner',inverse=False,nominal=True,rows=[(131071,-131072)]*n),
            dict(case='inverse_nominal',inverse=True,nominal=True,
                 rows=pair(rng.integers(-2048,2049,(n,2)))),
            dict(case='inverse_coherent_stress',inverse=True,nominal=False,rows=[(131071,-131072)]*n)]


def compare(actual,reference):
    actual=np.asarray(actual,complex);reference=np.asarray(reference,complex)
    if (actual.shape!=reference.shape or not len(actual) or not np.all(np.isfinite(actual))
            or not np.all(np.isfinite(reference))):raise ValueError('Invalid precision outputs')
    error_power=float(np.mean(abs(actual-reference)**2));reference_power=float(np.mean(abs(reference)**2))
    if reference_power<=0:raise ValueError('Precision workload must have positive reference energy')
    evm=math.sqrt(error_power/reference_power)
    return dict(reference_power=reference_power,error_power=error_power,evm_rms=evm,
                sqnr_db=10*math.log10(reference_power/error_power) if error_power else None,
                output_exact=error_power==0,max_complex_error=float(np.max(abs(actual-reference))))


def budget_met(record):
    sqnr=record['sqnr_db']
    precision_ok=(record['output_exact'] or (sqnr is not None and math.isfinite(sqnr) and sqnr>=SQNR_BUDGET_DB))
    return bool(precision_ok and math.isfinite(record['evm_rms']) and record['evm_rms']<=EVM_BUDGET
                and record['clamp_events']==0)


def report(widths=WIDTHS,sizes=SIZES,seed=SEED):
    widths=tuple(widths);sizes=tuple(sizes)
    if not widths or CURRENT_WIDTH not in widths or len(set(widths))!=len(widths) or not sizes:
        raise ValueError('Include unique widths, current20 control and nonempty sizes')
    records=[]
    for n in sizes:
        for case in cases(n,seed):
            rows=case['rows'];z=np.array([re+1j*im for re,im in rows])
            reference=np.fft.ifft(z)*n if case['inverse'] else np.fft.fft(z)/n
            default=f.transform(rows,case['inverse'])
            for width in widths:
                stats=StageTrace()
                values=f.transform(rows,case['inverse'],INPUT_WIDTH,width,stats=stats)
                plain=f.transform(rows,case['inverse'],INPUT_WIDTH,width)
                if values!=plain:raise RuntimeError('Instrumentation changed FFT outputs')
                metric=compare([re+1j*im for re,im in values],reference)
                metric.update(case=case['case'],n=n,inverse=case['inverse'],nominal=case['nominal'],
                              width=width,in_width=INPUT_WIDTH,input_hash=row_hash(rows),output_hash=row_hash(values),
                              clamp_events=stats.total(),clamp_evaluations=sum(stats.evaluations.values()),
                              stages=stats.stages(),control_bit_exact=(values==default) if width==CURRENT_WIDTH else None)
                metric['budget_met']=budget_met(metric);records.append(metric)
    summaries=[]
    for width in widths:
        nominal=[r for r in records if r['width']==width and r['nominal']]
        stress=[r for r in records if r['width']==width and not r['nominal']]
        finite=[r['sqnr_db'] for r in nominal if r['sqnr_db'] is not None]
        summaries.append(dict(width=width,nominal_budget_met=all(r['budget_met'] for r in nominal),
                              nominal_min_sqnr_db=min(finite) if finite else None,
                              nominal_max_evm=max(r['evm_rms'] for r in nominal),
                              nominal_clamp_events=sum(r['clamp_events'] for r in nominal),
                              stress_clamp_events=sum(r['clamp_events'] for r in stress),
                              stress_budget_met=all(r['budget_met'] for r in stress),
                              rtl_derived_widths=dict(data=width,butterfly=width+1,product=width+19,
                                                      complex_sum=width+20,shifted=width+4,twiddle=18)))
    passing=[s['width'] for s in summaries if s['nominal_budget_met']]
    all_passing=[s['width'] for s in summaries if s['nominal_budget_met'] and s['stress_budget_met']]
    return dict(scope=SCOPE,seed=seed,sizes=list(sizes),widths=list(widths),in_width=INPUT_WIDTH,
                data_fraction_bits=15,twiddle_fraction_bits=16,current_width=CURRENT_WIDTH,
                budget=dict(nominal_sqnr_min_db=SQNR_BUDGET_DB,nominal_evm_max=EVM_BUDGET,nominal_clamps_max=0),
                records=records,summaries=summaries,
                selected_simulation_width=min(passing) if passing else None,
                full_envelope_simulation_width=min(all_passing) if all_passing else None,
                accepted_new_default_width=None,rtl_candidate_equivalence_verified=False,rtl_equivalence=[])


def check_acceptance(result):
    records=result['records']
    expected={(width,n,case['case']) for width in result['widths'] for n in result['sizes'] for case in cases(n,result['seed'])}
    if not records or len(records)!=len(expected) or {(r['width'],r['n'],r['case']) for r in records}!=expected:
        raise RuntimeError('Incomplete internal-width sweep coverage')
    if CURRENT_WIDTH not in result['widths'] or result['accepted_new_default_width'] is not None:
        raise RuntimeError('Current width control or exploratory selection status is invalid')
    hashes={}
    for record in records:
        key=(record['n'],record['case'])
        if key in hashes and hashes[key]!=record['input_hash']:raise RuntimeError('Width candidates received different inputs')
        hashes[key]=record['input_hash']
        if record['width']==CURRENT_WIDTH and record['control_bit_exact'] is not True:
            raise RuntimeError('Current width control differs from production FFT')
        if record['budget_met']!=budget_met(record):raise RuntimeError('Inconsistent precision budget decision')
        if (not math.isfinite(record['evm_rms']) or record['clamp_evaluations']<=0
                or record['clamp_events']!=sum(s['positive_clamps']+s['negative_clamps'] for s in record['stages'].values())):
            raise RuntimeError('Invalid measured precision or clamp evidence')
    selected=result['selected_simulation_width']
    if selected is None or not all(budget_met(r) for r in records if r['width']==selected and r['nominal']):
        raise RuntimeError('No qualified candidate for the declared nominal budget')
    passing=[width for width in result['widths'] if all(budget_met(r) for r in records if r['width']==width and r['nominal'])]
    if selected!=min(passing):raise RuntimeError('Selected width is not the smallest qualified simulation')
    if not any(r['clamp_events']>0 for r in records if not r['nominal'] and r['width']==CURRENT_WIDTH):
        raise RuntimeError('Coherent inverse clipping control was not exercised')
    if result['rtl_candidate_equivalence_verified']:
        proof=result['rtl_equivalence']
        grid={(width,n,active,scenario) for width in {CURRENT_WIDTH,selected} for n in result['sizes']
              for active in (1,0) for scenario in ('stream','stalled','midreset','outreset')}
        observed={(item.get('width'),item.get('n'),item.get('reset_active'),item.get('scenario')) for item in proof}
        if len(proof)!=len(grid) or observed!=grid:
            raise RuntimeError('Missing, duplicate or unexpected actual RTL width equivalence coverage')
        if any(item.get('numeric_verified') is not True or item.get('saturation_verified') is not True
               or item.get('bounds_verified') is not True or item.get('outputs')!=5*item['n']
               or item.get('frames')!=5 for item in proof):
            raise RuntimeError('Incomplete actual RTL width equivalence checks')
    elif result['rtl_equivalence']:
        raise RuntimeError('Unverified RTL records must not be presented as accepted equivalence')


def verify_rtl(result,folder):
    """The unchanged RTL receives exactly the sweep words at candidate/current parameters."""
    from fft_cases import save,write_saturation_expected
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();artifacts=[];proof=[]
    for width in sorted({CURRENT_WIDTH,result['selected_simulation_width']}):
        for n in result['sizes']:
            bits=n.bit_length()-1;vector=folder/f'n{n}_w{width}'/'vectors';vector.mkdir(parents=True,exist_ok=True)
            inputs=[];outputs=[];flags=[];stats=SatTrace()
            for case in cases(n,result['seed']):
                record=next(r for r in result['records'] if r['width']==width and r['n']==n and r['case']==case['case'])
                rows=case['rows'];values=f.transform(rows,case['inverse'],INPUT_WIDTH,width,stats=stats)
                if row_hash(rows)!=record['input_hash'] or row_hash(values)!=record['output_hash']:
                    raise RuntimeError('RTL vectors do not correspond to measured sweep inputs/outputs')
                flags.append(int(case['inverse']))
                inputs.extend((re,im,int(case['inverse']),int(k==n-1),0) for k,(re,im) in enumerate(rows))
                outputs.extend((re,im,int(case['inverse']),int(k==n-1)) for k,(re,im) in enumerate(values))
            save(vector/'in.txt',inputs);save(vector/'out.txt',outputs)
            totals=write_saturation_expected(vector,bits,stats,flags)
            artifacts.extend(vector.glob('*.txt'))
            for active in (1,0):
                work=vector.parent/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
                if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{ROOT/"rtl/modems/bpsk_costas_2008_08_25"}',
                         f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',
                         ROOT/'rtl/tb/fft_tb.sv'],work,work/'compile.log')
                artifacts.append(work/'compile.log')
                common=[bindir/'vsim','-64','-c','-quiet','work.fft_tb',f'-gLOG2N={bits}',f'-gIN_WIDTH={INPUT_WIDTH}',
                        f'-gWIDTH={width}',f'-gRESET_ACTIVE={active}',f'-gTWIDDLE_FILE={ROOT/f"rtl/common/mem/fft_twiddle_{n}.mem"}',
                        f'+VECTORS={vector}']
                for name,options in [('stream',[]),('stalled',['+STALL_INPUT','+STALL_OUTPUT']),
                                     ('midreset',['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT']),
                                     ('outreset',['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'])]:
                    log=work/f'{name}.log'
                    # execute() has no timeout in older snapshots; bound these independent gates here.
                    process=subprocess.run(list(map(str,[*common,*options,'-do','onerror {quit -code 1}; run -all; quit -code 0'])),
                                           cwd=work,capture_output=True,text=True,timeout=90)
                    text=process.stdout+process.stderr;log.write_text(text)
                    numeric=re.search(r'PASS FFT: (\d+) outputs, (\d+) frames',text)
                    saturation=re.search(r'PASS FFT SATURATION: (\d+) evaluations, (\d+) events',text)
                    if (process.returncode or not numeric or tuple(map(int,numeric.groups()))!=(len(outputs),len(flags))
                            or not saturation or tuple(map(int,saturation.groups()))!=(totals['total_evaluations'],totals['total_events'])
                            or 'PASS BOUNDS fft counts:' not in text or re.search(r'\*\* (?:Error|Fatal)',text)):
                        raise RuntimeError(f'Actual RTL width equivalence failed: n{n}/w{width}/{active}/{name}\n{text[-4000:]}')
                    artifacts.append(log);proof.append(dict(n=n,width=width,reset_active=active,scenario=name,
                                                           outputs=len(outputs),frames=len(flags),numeric_verified=True,
                                                           saturation_verified=True,bounds_verified=True))
    result['rtl_equivalence']=proof;result['rtl_candidate_equivalence_verified']=True
    return artifacts


def main(argv=None):
    require_unoptimized()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/internal_widths/fft_results.json')
    parser.add_argument('--verify-rtl',action='store_true')
    args=parser.parse_args(argv)
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING',scope=SCOPE));result={};artifacts=[]
    try:
        result=report();check_acceptance(result)
        if args.verify_rtl:artifacts=verify_rtl(result,ROOT/'build/rtl/internal_widths/fft_equivalence')
        check_acceptance(result);completed=finish(evidence,artifacts)
    except Exception as exc:
        try:completed=finish(evidence)
        except RuntimeError as snapshot_error:completed=dict(evidence,source_snapshot_error=str(snapshot_error))
        write_json(args.output,dict(completed,status='FAIL',error=str(exc),result=result));raise
    write_json(args.output,dict(completed,status='PASS',**result))
    for summary in result['summaries']:
        print(f"WIDTH{summary['width']}: nominal SQNRmin={summary['nominal_min_sqnr_db']:.2f}dB "
              f"EVMmax={summary['nominal_max_evm']:.6g}, clamps={summary['nominal_clamp_events']}; "
              f"stress clamps={summary['stress_clamp_events']}")
    print(f"Simulation candidate WIDTH{result['selected_simulation_width']}; "
          f"actual RTL equivalence={result['rtl_candidate_equivalence_verified']}; new default accepted=None")
    return 0


if __name__=='__main__':raise SystemExit(main())
