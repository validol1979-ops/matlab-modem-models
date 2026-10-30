#!/usr/bin/env python3
"""Full LMS/NLMS/RLS model quality on common once-quantized input/desired data.

Both loops evolve their own states. The independent research_core reference gets
the Q15-dequantized words and common configured parameters, never fixed history,
weights or covariance. This is adaptive-filter precision/convergence, not SER.
Final coefficient comparisons use the exported signed18 Q15 weight dump; they
include dump rounding/clipping and do not expose internal Q30 weights.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys

import numpy as np
from regression_evidence import ROOT,begin,finish,require_unoptimized,write_json
sys.path.insert(0,str(ROOT/'common/python'))
import lms_fixed as lms
import rls_fixed as rls
from research_core import run as floating_run
from sat_diag import SatTrace

MODES=('lms','nlms','rls')
SAMPLES=1200
SETTLE=400
EARLY=64
SEED=6301
PLANT3=np.array([.6+.1j,-.2+.1j,.15])
PLANT8=np.array([.25+.08j,-.12+.06j,.1-.04j,.04+.1j,-.05-.03j,.03+.02j,.02-.015j,-.015+.01j])
SCENARIOS=(('quiet_complex3',3,PLANT3,0.),('noisy_complex3',3,PLANT3,.01),('noisy_complex8',8,PLANT8,.03))
BUDGET=dict(prediction_sqnr_min_db=40.,discrepancy_rms_max_signal_units=.001,
            exported_weight_rms_max_coefficient_units=.003,nominal_clamps_max=0,
            settled_to_early_mse_max=.35,fixed_to_float_settled_mse_factor_max=2.,
            settled_mse_floor_signal_units_squared=(2/32768)**2)
DIFFERENCES=[
    'Common input and desired words are rounded once to signed18 Q15; floating recursion retains real arithmetic thereafter.',
    'LMS uses configured MU Q17 and EPS Q30. NLMS uses a top-10-bit mantissa reciprocal ROM instead of floating exact division.',
    'RLS reference starts at the configured P0 (Q28) via epsilon=1/P0, and uses configured LAM Q28. Fixed INVL is separately rounded Q30.',
    'Fixed RLS updates only upper-triangle P, mirrors its conjugate and forces a real diagonal. Floating RLS evolves its full complex covariance independently.',
    'Fixed prediction/error use signed18 Q15 clamps; weights update in signed34 Q30 then export through signed18 Q15 rounding/clamping.',
    'Weight comparison uses the native vdot(w, history) convention directly; no truth fit, permutation, gain or phase compensation is applied.'
]
SCOPE=('Python production fixed recursions versus independent research_core floating recursions; '
       'three seeded nominal FIR/noise scenarios and separate clipping stresses. Known plant '
       'coefficients only generate desired data. No SER, general stability region or new RTL quality signoff.')


def complex_words(rows):
    return np.array([re+1j*im for re,im in rows])/32768


def hash_words(rows):
    return hashlib.sha256(json.dumps(rows,separators=(',',':')).encode()).hexdigest()


def quantize_once(wave):
    wave=np.asarray(wave,complex)
    if wave.ndim!=1 or not len(wave) or not np.all(np.isfinite(wave)):
        raise ValueError('Finite nonempty complex input is required')
    raw=np.rint(np.column_stack((wave.real,wave.imag))*32768)
    clipped=np.clip(raw,-131072,131071)
    clamps=int(np.count_nonzero(raw!=clipped))
    return [tuple(map(int,row)) for row in clipped],clamps


def nominal_data():
    datasets=[]
    for index,(name,taps,plant,noise_rms) in enumerate(SCENARIOS):
        rng=np.random.default_rng(SEED+index)
        x=.7*(rng.standard_normal(SAMPLES)+1j*rng.standard_normal(SAMPLES))/np.sqrt(2)
        clean=np.convolve(x,plant)[:SAMPLES]
        noise=noise_rms*(rng.standard_normal(SAMPLES)+1j*rng.standard_normal(SAMPLES))/np.sqrt(2)
        xq,xclamp=quantize_once(x);dq,dclamp=quantize_once(clean+noise)
        datasets.append(dict(case=name,taps=taps,nominal=True,x=xq,d=dq,
                             requested_noise_rms_signal_units=noise_rms,
                             measured_noise_power_signal_units_squared=float(np.mean(abs(noise)**2)),
                             clean_desired_power_signal_units_squared=float(np.mean(abs(clean)**2)),
                             input_clamps=xclamp,desired_clamps=dclamp,data_seed=SEED+index))
    return datasets


def configured(mode,stress=False):
    if mode=='rls':
        raw=rls.parameters(1. if stress else .995,1/16384 if stress else .01)
        return raw,[raw[1]/2**28,2**28/raw[0]],dict(P0_Q28=raw[0],LAM_Q28=raw[1],INVL_Q30=raw[2])
    raw=lms.parameters(1. if stress else (.05 if mode=='lms' else .6),
                       2**-21 if stress and mode=='nlms' else .01)
    return raw,[raw[0]/2**17,raw[1]/2**30],dict(MU_Q17=raw[0],EPS_Q30=raw[1])


def deviation(actual,reference):
    actual=np.asarray(actual,complex);reference=np.asarray(reference,complex)
    if actual.shape!=reference.shape or not len(actual) or not np.all(np.isfinite(actual)) or not np.all(np.isfinite(reference)):
        raise ValueError('Invalid precision streams')
    error=float(np.mean(abs(actual-reference)**2));power=float(np.mean(abs(reference)**2))
    actual_power=float(np.mean(abs(actual)**2))
    return dict(samples=len(actual),rms_signal_units=math.sqrt(error),max_signal_units=float(np.max(abs(actual-reference))),
                actual_rms_signal_units=math.sqrt(actual_power),reference_rms_signal_units=math.sqrt(power),
                actual_power_signal_units_squared=actual_power,
                reference_power_signal_units_squared=power,discrepancy_power_signal_units_squared=error,
                sqnr_db=10*math.log10(power/error) if power and error else None,
                sqnr_defined=bool(power and error),comparison_exact=error==0)


def evaluation_counts(mode,n,taps):
    expected={name:n for name in ('pred.re','pred.im','error.re','error.im')}
    expected.update({name:n*taps for name in ('update.re','update.im')})
    expected.update({'dump.re':taps,'dump.im':taps})
    if mode=='rls':
        expected.update({name:n*taps for name in ('u.re','u.im','gain.re','gain.im')})
        expected.update(q=n,**{name:n*taps*(taps+1)//2 for name in ('pt.re','pt.im','P.re')})
        expected['P.im']=n*taps*(taps-1)//2
    return expected


def measure(mode,dataset):
    x,d=dataset['x'],dataset['d'];n=len(x);taps=dataset['taps'];stress=not dataset['nominal']
    raw,parameters,raw_info=configured(mode,stress)
    trace=SatTrace()
    common=dict(case=dataset['case'],algorithm=mode,nominal=dataset['nominal'],samples=n,taps=taps,
                input_hash=hash_words(x),desired_hash=hash_words(d),input_clamps=dataset['input_clamps'],
                desired_clamps=dataset['desired_clamps'],configured_raw=raw_info,
                floating_parameters=[taps,*parameters],quality_accepted=False,
                signal_unit='Q15-normalized amplitude: integer word / 32768',
                weight_format='exported signed18 Q15 coefficients; internal signed34 Q30 states are not returned')
    def fixed(stats=None):
        return rls.adapt(x,d,taps,raw,stats=stats) if mode=='rls' else lms.adapt(x,d,taps,mode,raw,stats=stats)
    try:
        out,weights=fixed(trace)
    except ValueError as exc:
        if stress and mode=='rls' and 'denominator' in str(exc):
            return dict(common,status='diagnostic_rejection',reason=str(exc),
                        saturation=trace.to_dict(),instrumented_equal=None)
        raise
    plain=fixed()
    if (out,weights)!=plain:raise RuntimeError('Instrumentation changed adaptive recursion outputs')
    prediction=complex_words([p for p,e in out]);error=complex_words([e for p,e in out])
    reference=floating_run(mode,[taps,*parameters],complex_words(x),complex_words(d))
    if reference.shape!=(2*n+taps,) or not np.all(np.isfinite(reference)):
        raise RuntimeError('Independent floating recursion returned invalid outputs')
    fp,fe,fw=reference[:n],reference[n:2*n],reference[2*n:]
    start=SETTLE if dataset['nominal'] else 0
    window=slice(start,n);early=slice(0,min(EARLY,n))
    weight_delta=complex_words(weights)-fw
    fixed_early=float(np.mean(abs(error[early])**2));float_early=float(np.mean(abs(fe[early])**2))
    fixed_settled=float(np.mean(abs(error[window])**2));float_settled=float(np.mean(abs(fe[window])**2))
    measured=dict(common,status='measured',instrumented_equal=True,saturation=trace.to_dict(),
                  expected_evaluations=evaluation_counts(mode,n,taps),scored_sample_start=start,scored_sample_stop=n,
                  prediction_full=deviation(prediction,fp),error_full=deviation(error,fe),
                  prediction_settled=deviation(prediction[window],fp[window]),
                  error_settled=deviation(error[window],fe[window]),
                  exported_weight_rms_coefficient_units=float(np.sqrt(np.mean(abs(weight_delta)**2))),
                  exported_weight_max_coefficient_units=float(np.max(abs(weight_delta))),
                  convergence=dict(fixed_early_mse_signal_units_squared=fixed_early,
                                   floating_early_mse_signal_units_squared=float_early,
                                   fixed_settled_mse_signal_units_squared=fixed_settled,
                                   floating_settled_mse_signal_units_squared=float_settled,
                                   fixed_settled_to_early_ratio=fixed_settled/fixed_early if fixed_early else None,
                                   floating_settled_to_early_ratio=float_settled/float_early if float_early else None))
    if dataset['nominal']:
        for key in ('requested_noise_rms_signal_units','measured_noise_power_signal_units_squared',
                    'clean_desired_power_signal_units_squared','data_seed'):
            measured[key]=dataset[key]
        measured['quality_accepted']=nominal_quality(measured)
    return measured


def nominal_quality(record):
    if record['status']!='measured' or not record['nominal']:return False
    prediction=record['prediction_settled'];error=record['error_settled'];convergence=record['convergence']
    sqnr=prediction['sqnr_db'];late=convergence['fixed_settled_mse_signal_units_squared']
    early=convergence['fixed_early_mse_signal_units_squared'];float_late=convergence['floating_settled_mse_signal_units_squared']
    return bool((prediction['comparison_exact'] or (sqnr is not None and math.isfinite(sqnr) and sqnr>=BUDGET['prediction_sqnr_min_db']))
                and prediction['rms_signal_units']<=BUDGET['discrepancy_rms_max_signal_units']
                and error['rms_signal_units']<=BUDGET['discrepancy_rms_max_signal_units']
                and record['exported_weight_rms_coefficient_units']<=BUDGET['exported_weight_rms_max_coefficient_units']
                and record['saturation']['total']==0 and early>0 and late<BUDGET['settled_to_early_mse_max']*early
                and late<=BUDGET['fixed_to_float_settled_mse_factor_max']*float_late+BUDGET['settled_mse_floor_signal_units_squared'])


def report():
    records=[measure(mode,dataset) for dataset in nominal_data() for mode in MODES]
    stress=[dict(case='stress_lms',taps=2,x=[(131071,0),(0,0)],d=[(131071,0),(0,0)],mode='lms'),
            dict(case='stress_nlms',taps=1,x=[(1,0),(0,0)],d=[(131071,0),(0,0)],mode='nlms'),
            dict(case='stress_rls',taps=1,x=[(1,0)]*8,d=[(131071,131071)]*8,mode='rls')]
    for dataset in stress:
        dataset.update(nominal=False,input_clamps=0,desired_clamps=0)
        records.append(measure(dataset['mode'],dataset))
    return dict(scope=SCOPE,methodological_differences=list(DIFFERENCES),budget=dict(BUDGET),seed=SEED,
                samples=SAMPLES,settle=SETTLE,early=EARLY,records=records,rtl_quality_observed=False)


def check_acceptance(result):
    records=result['records'];nominal={(name,mode) for name,_,_,_ in SCENARIOS for mode in MODES}
    stress={(f'stress_{mode}',mode) for mode in MODES};all_expected=nominal|stress
    if not records or len(records)!=len(all_expected) or {(r['case'],r['algorithm']) for r in records}!=all_expected:
        raise RuntimeError('Incomplete adaptive precision coverage')
    if result['budget']!=BUDGET:raise RuntimeError('Adaptive precision budget metadata changed')
    nominal_taps={name:taps for name,taps,_,_ in SCENARIOS}
    stress_shapes={'stress_lms':(2,2),'stress_nlms':(2,1),'stress_rls':(8,1)}
    common_hashes={}
    for record in records:
        expected_nominal=(record['case'],record['algorithm']) in nominal
        if record['nominal'] is not expected_nominal:
            raise RuntimeError('Adaptive case quality/stress classification is inconsistent')
        expected_shape=(SAMPLES,nominal_taps[record['case']]) if expected_nominal else stress_shapes[record['case']]
        if (record['samples'],record['taps'])!=expected_shape:
            raise RuntimeError('Adaptive sample/tap metadata differs from the declared experiment')
        counts=record['saturation']['evaluations']
        expected=evaluation_counts(record['algorithm'],record['samples'],record['taps'])
        if any(value and key not in expected for key,value in counts.items()):
            raise RuntimeError('Unexpected active adaptive clamp stage')
        if record['nominal']:
            identity=(record['input_hash'],record['desired_hash'])
            old=common_hashes.setdefault(record['case'],identity)
            if identity!=old:raise RuntimeError('Algorithms did not receive common quantized data')
            if (record['instrumented_equal'] is not True or record['input_clamps'] or record['desired_clamps']
                    or record['quality_accepted'] is not True or not nominal_quality(record)):
                raise RuntimeError(f"Nominal adaptive quality failed: {record['case']}/{record['algorithm']}")
        elif record['quality_accepted'] is not False:
            raise RuntimeError('Clipping stress must not be accepted as nominal quality')
        if record['status']=='diagnostic_rejection':
            if record['algorithm']!='rls' or record['nominal'] or 'denominator' not in record.get('reason',''):
                raise RuntimeError('Invalid adaptive diagnostic rejection')
            continue
        if record['status']!='measured' or record['instrumented_equal'] is not True:
            raise RuntimeError('Missing complete measured adaptive outputs')
        start=SETTLE if record['nominal'] else 0
        if record['scored_sample_start']!=start or record['scored_sample_stop']!=record['samples']:
            raise RuntimeError('Adaptive scored sample range differs from the declared experiment')
        if (any(record[name]['samples']!=record['samples'] for name in ('prediction_full','error_full'))
                or any(record[name]['samples']!=record['samples']-start for name in ('prediction_settled','error_settled'))):
            raise RuntimeError('Adaptive precision metric spans are incomplete')
        if record['expected_evaluations']!=expected or {key:counts.get(key,0) for key in expected}!=expected:
            raise RuntimeError('Adaptive clamp observer was not fully exercised')
        actual=sum(c['pos']+c['neg'] for c in record['saturation']['stages'].values())
        if record['saturation']['total']!=actual or (not record['nominal'] and actual==0):
            raise RuntimeError('Missing or inconsistent adaptive clamp stress evidence')


def main(argv=None):
    require_unoptimized()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/adaptive_precision/results.json')
    args=parser.parse_args(argv)
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING',scope=SCOPE));result={}
    try:
        result=report();check_acceptance(result);completed=finish(evidence)
    except Exception as exc:
        try:completed=finish(evidence)
        except RuntimeError as snapshot_error:completed=dict(evidence,source_snapshot_error=str(snapshot_error))
        write_json(args.output,dict(completed,status='FAIL',error=str(exc),result=result));raise
    write_json(args.output,dict(completed,status='PASS',**result))
    for record in result['records']:
        if record['nominal']:
            metric=record['prediction_settled']
            print(f"PASS {record['algorithm'].upper()} {record['case']}: prediction SQNR {metric['sqnr_db']:.2f} dB, "
                  f"RMS deviation {metric['rms_signal_units']:.6g} signal units, "
                  f"exported-weight RMS {record['exported_weight_rms_coefficient_units']:.6g} coefficient units")
        else:
            print(f"DIAGNOSTIC {record['algorithm'].upper()}: {record['status']}, "
                  f"{record['saturation']['total']} clamp events; nominal quality accepted=False")
    return 0


if __name__=='__main__':raise SystemExit(main())
