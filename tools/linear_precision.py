#!/usr/bin/env python3
"""MMSE2/MMSE3, beamformer and Alamouti model precision on common Q15 words.

Independent NumPy references use the quantized configuration and observations,
never integer model weights/reciprocals. Native MMSE Q24 weights are compared
directly. Beam/Alamouti effective coefficients are reconstructed on the fixed
side from the production R/Z encoding; there is no coefficient dump API there.
Clamping and configuration rejection are diagnostics, not nominal precision.
"""
import argparse
import hashlib
import itertools
import json
import math
from numbers import Integral
from pathlib import Path
import sys

import numpy as np
from regression_evidence import ROOT,begin,finish,require_unoptimized,write_json
sys.path.insert(0,str(ROOT/'common/python'))
import mmse_fixed as mmse2
import mmse3_fixed as mmse3
import beam_fixed as beam
from sat_diag import SatTrace

BLOCKS=64
SEED=9143
MODELS={'mmse2':mmse2,'mmse3':mmse3}
H2=np.array([[1+.3j,.4-.2j],[-.2+.1j,.8+.2j]])
H3=np.array([[1+.2j,.125-.1j,.02],[-.1j,.8+.1j,.1+.2j],[.2,-.1+.1j,1.1-.15j]])
BUDGET=dict(output_sqnr_min_db=55.,output_rms_max_signal_units=5e-5,output_max_signal_units=1e-4,
            coefficient_relative_rms_max=1e-5,nominal_output_clamps_max=0,clipped_stress_max_signal_units=1e-4)
SCOPE=('Python production fixed linear transforms versus independent NumPy on common once-quantized '
       'configuration/observations. Signal units are raw signed18 Q15 words / 32768; coefficients are '
       'dimensionless. No SER, parameter-width change or new actual RTL observation is claimed.')


def words(values):
    values=np.asarray(values,complex).reshape(-1)
    if not len(values) or not np.all(np.isfinite(values)):raise ValueError('Finite nonempty quantization input required')
    raw=np.rint(np.column_stack((values.real,values.imag))*32768);clipped=np.clip(raw,-131072,131071)
    return [tuple(map(int,row)) for row in clipped],int(np.count_nonzero(raw!=clipped))


def complex_words(rows,fraction=15):
    return np.array([complex(re,im) for re,im in rows])/2**fraction


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,separators=(',',':'),sort_keys=True).encode()).hexdigest()


def _plan(name,family,category,config,observations,blocks,dimension,clamps=0):
    return dict(case=name,family=family,category=category,config=config,observations=observations,
                blocks=blocks,dimension=dimension,input_clamps=clamps)


def plans():
    rng=np.random.default_rng(SEED);result=[]
    def observations(count,tiny=False):
        if tiny:return [tuple(map(int,row)) for row in rng.integers(-3,4,(count,2))],0
        return words(.3*(rng.standard_normal(count)+1j*rng.standard_normal(count))/np.sqrt(2))
    for n,family,H in ((2,'mmse2',H2),(3,'mmse3',H3)):
        for name,Hfloat,lam in (('complex_zf',H,0.),('complex_regularized',H,.05),
                               ('rank_regularized',np.ones((n,n)),.1),('tiny_identity',np.eye(n)/32768,0.)):
            Hflat,cclamp=words(Hfloat);raw=[Hflat[i*n:(i+1)*n] for i in range(n)]
            obs,clamp=observations(BLOCKS*n,name=='tiny_identity')
            result.append(_plan(f'{family}_{name}',family,'nominal',dict(H=raw,lambda_raw=round(lam*2**30)),
                                obs,BLOCKS,n,clamp+cclamp))
    for name,a in (('steering8',np.exp(2j*np.pi*np.arange(8)*.125)),
                   ('weak3',np.array([.2+.1j,-.3+.05j,.15-.12j])),('tiny1',np.array([1/32768]))):
        config,cclamp=words(a);obs,clamp=observations(BLOCKS*len(a),name=='tiny1')
        result.append(_plan(f'beamformer_{name}','beamformer','nominal',dict(a=config),obs,BLOCKS,len(a),clamp+cclamp))
    for name,h in (('complex2',np.array([.4+.3j,1-.2j])),('orthogonal2',np.array([.7,.7j])),
                   ('tiny2',np.array([1/32768,1j/32768]))):
        config,cclamp=words(h);obs,clamp=observations(2*BLOCKS,name=='tiny2')
        result.append(_plan(f'alamouti_{name}','alamouti','nominal',dict(h=config),obs,BLOCKS,2,clamp+cclamp))
    for n,family in ((2,'mmse2'),(3,'mmse3')):
        H=[[(16384,0) if i==j else (0,0) for j in range(n)] for i in range(n)]
        obs=[(131071,131071),(-131072,-131072),(131071,-131072)][:n]
        result.append(_plan(f'{family}_output_clamp',family,'clamp_stress',dict(H=H,lambda_raw=0),obs,1,n))
    result.append(_plan('beamformer_output_clamp','beamformer','clamp_stress',dict(a=[(1,0)]),
                        [(131071,131071),(-131072,-131072)],2,1))
    result.append(_plan('alamouti_output_clamp','alamouti','clamp_stress',dict(h=[(1,0),(0,1)]),
                        [(131071,131071),(-131072,-131072)],1,2))
    for n,family in ((2,'mmse2'),(3,'mmse3')):
        H=[[(32768,0)]*n for _ in range(n)]
        result.append(_plan(f'{family}_singular',family,'singular_rejection',dict(H=H,lambda_raw=0),[(1,0)]*n,1,n))
    result.append(_plan('mmse2_coefficient_overflow','mmse2','coefficient_rejection',
                        dict(H=[[(131071,0),(131070,0)],[(1,0),(1,0)]],lambda_raw=0),[(1,0)]*2,1,2))
    N=131071
    result.append(_plan('mmse3_coefficient_overflow','mmse3','coefficient_rejection',
                        dict(H=[[(N,0),(1,0),(0,0)],[(0,0),(N,0),(1,0)],[(1,0),(0,0),(0,0)]],lambda_raw=0),
                        [(1,0)]*3,1,3))
    result.append(_plan('beamformer_zero_energy','beamformer','zero_energy_rejection',dict(a=[(0,0)]*3),[(1,0)]*3,1,3))
    result.append(_plan('alamouti_zero_energy','alamouti','zero_energy_rejection',dict(h=[(0,0)]*2),[(1,0)]*2,1,2))
    return result


def validate_plan(plan):
    n=plan['dimension'];family=plan['family'];config=plan['config']
    if n<1 or plan['blocks']<1 or len(plan['observations'])!=n*plan['blocks']:
        raise ValueError('Linear experiment observation shape mismatch')
    if family in MODELS:
        if n!=(2 if family=='mmse2' else 3) or len(config['H'])!=n or any(len(row)!=n for row in config['H']):
            raise ValueError('MMSE channel shape mismatch')
        cfgwords=[pair for row in config['H'] for pair in row]
        L=config['lambda_raw']
        if not isinstance(L,Integral) or isinstance(L,bool) or not 0<=L<2**34:raise ValueError('Invalid Q30 lambda word')
    elif family=='beamformer':
        if len(config['a'])!=n:raise ValueError('Beamformer steering shape mismatch')
        cfgwords=config['a']
    elif family=='alamouti':
        if n!=2 or len(config['h'])!=2:raise ValueError('Alamouti needs two channel coefficients')
        cfgwords=config['h']
    else:raise ValueError('Unknown linear algorithm')
    for pair in [*cfgwords,*plan['observations']]:
        try:pair_length=len(pair)
        except TypeError as exc:raise ValueError('Linear experiment requires complex integer pairs') from exc
        if pair_length!=2 or any(not isinstance(v,Integral) or isinstance(v,bool) or not -131072<=v<=131071 for v in pair):
            raise ValueError('Linear experiment requires legal signed18 integer pairs')


def floating_reference(plan):
    """Only encoded configuration/data enter this independent floating operator."""
    validate_plan(plan);family=plan['family'];config=plan['config'];n=plan['dimension']
    X=complex_words(plan['observations']).reshape(-1,n)
    if family in MODELS:
        H=complex_words([v for row in config['H'] for v in row]).reshape(n,n)
        W=np.linalg.solve(H.conj().T@H+(config['lambda_raw']/2**30)*np.eye(n),H.conj().T)
        return (X@W.T).ravel(),W
    if family=='beamformer':
        a=complex_words(config['a']);W=a.conj()/np.vdot(a,a).real
        return X@W,W
    h=complex_words(config['h']);energy=np.vdot(h,h).real
    W=np.array([[h[0].conjugate(),h[1]],[h[1].conjugate(),-h[0]]])/energy
    augmented=np.column_stack((X[:,0],X[:,1].conjugate()))
    return (augmented@W.T).ravel(),W


def fixed_outputs(plan,stats=None):
    family=plan['family'];cfg=plan['config'];x=plan['observations']
    if family in MODELS:return MODELS[family].solve(x,cfg['H'],cfg['lambda_raw']/2**30,stats=stats)
    if family=='beamformer':return beam.beamform(x,cfg['a'],stats=stats)
    return beam.alamouti(x,cfg['h'],stats=stats)


def fixed_coefficients(plan):
    """Fixed side only: native MMSE W, or the actually encoded beam/Alamouti linear map."""
    family=plan['family'];cfg=plan['config'];n=plan['dimension']
    if family in MODELS:
        W=MODELS[family].weights(cfg['H'],cfg['lambda_raw']/2**30)
        return complex_words([v for row in W for v in row],24).reshape(n,n)
    rows=cfg['a'] if family=='beamformer' else cfg['h']
    E=sum(re*re+im*im for re,im in rows);r,z=beam.reciprocal(E)
    scale=math.ldexp(float(r),15-z)
    raw=np.array([complex(re,im) for re,im in rows])
    if family=='beamformer':return raw.conj()*scale
    return np.array([[raw[0].conjugate(),raw[1]],[raw[1].conjugate(),-raw[0]]])*scale


def metric(actual,reference):
    actual=np.asarray(actual,complex);reference=np.asarray(reference,complex)
    if actual.shape!=reference.shape or not actual.size or not np.all(np.isfinite(actual)) or not np.all(np.isfinite(reference)):
        raise ValueError('Linear precision metric shape/finite-value mismatch')
    mse=float(np.mean(abs(actual-reference)**2));power=float(np.mean(abs(reference)**2))
    if power<=0:raise ValueError('Positive reference energy required for precision scoring')
    return dict(items=int(actual.size),shape=list(actual.shape),rms_deviation=math.sqrt(mse),max_complex_deviation=float(np.max(abs(actual-reference))),
                mse=mse,reference_power=power,relative_mse=mse/power,relative_rms=math.sqrt(mse/power),
                sqnr_db=10*math.log10(power/mse) if mse else None,comparison_exact=mse==0)


def output_count(plan):
    return plan['blocks'] if plan['family']=='beamformer' else plan['blocks']*plan['dimension']


def evaluation_counts(plan):
    family=plan['family'];blocks=plan['blocks']
    if family in MODELS:return {f'output.y{i}.{axis}':blocks for i in range(plan['dimension']) for axis in ('re','im')}
    if family=='beamformer':return {'beam.output.re':blocks,'beam.output.im':blocks}
    return {f'alamouti.y{i}.{axis}':blocks for i in (0,1) for axis in ('re','im')}


def _determinant(matrix):
    n=len(matrix);result=0
    for permutation in itertools.permutations(range(n)):
        inversions=sum(permutation[i]>permutation[j] for i in range(n) for j in range(i+1,n))
        term=math.prod(matrix[i][permutation[i]] for i in range(n))
        result+=(-1 if inversions%2 else 1)*term
    return result


def rejection_proof(plan):
    cfg=plan['config'];category=plan['category']
    if category=='zero_energy_rejection':
        rows=cfg['a'] if plan['family']=='beamformer' else cfg['h']
        return dict(energy_raw_q30=sum(re*re+im*im for re,im in rows))
    H=[[int(re) for re,im in row] for row in cfg['H']]
    if any(im for row in cfg['H'] for re,im in row):raise ValueError('Real determinant certificate fixture required')
    determinant=_determinant(H)
    if category=='singular_rejection':return dict(determinant_raw=determinant,lambda_raw=cfg['lambda_raw'])
    if abs(determinant)!=1:raise ValueError('Unimodular coefficient overflow fixture required')
    cofactors=[]
    for i in range(len(H)):
        for j in range(len(H)):
            minor=[[H[a][b] for b in range(len(H)) if b!=j] for a in range(len(H)) if a!=i]
            cofactors.append(_determinant(minor))
    required=max(abs(value) for value in cofactors)<<39
    width=48 if plan['family']=='mmse2' else 64
    return dict(determinant_raw=determinant,gram_determinant_raw=determinant**2,
                required_max_abs_coefficient_q24=str(required),signed_coefficient_bits=width,
                positive_limit_q24=str((1<<(width-1))-1),mathematically_exceeds_range=required>(1<<(width-1)))


def nominal_quality(record):
    if record['category']!='nominal' or record['status']!='measured':return False
    output=record['unclipped_output'];coefficient=record['coefficients'];sqnr=output['sqnr_db']
    return bool((output['comparison_exact'] or (sqnr is not None and math.isfinite(sqnr) and sqnr>=BUDGET['output_sqnr_min_db']))
                and output['rms_deviation']<=BUDGET['output_rms_max_signal_units']
                and output['max_complex_deviation']<=BUDGET['output_max_signal_units']
                and coefficient['relative_rms']<=BUDGET['coefficient_relative_rms_max']
                and record['saturation']['total']==0 and record['input_clamps']==0)


def validate_metric(value):
    for name in ('rms_deviation','max_complex_deviation','mse','reference_power','relative_mse','relative_rms'):
        if not math.isfinite(value[name]) or value[name]<0:raise RuntimeError('Invalid finite linear precision metric')
    if value['reference_power']<=0 or value['comparison_exact'] is not (value['mse']==0):
        raise RuntimeError('Inconsistent exact linear precision result')
    if (not math.isclose(value['rms_deviation']**2,value['mse'],rel_tol=1e-12,abs_tol=1e-30)
            or not math.isclose(value['relative_mse'],value['mse']/value['reference_power'],rel_tol=1e-12,abs_tol=1e-30)
            or not math.isclose(value['relative_rms']**2,value['relative_mse'],rel_tol=1e-12,abs_tol=1e-30)):
        raise RuntimeError('Inconsistent linear RMS/relative MSE metrics')
    if value['mse']:
        expected=10*math.log10(value['reference_power']/value['mse'])
        if value['sqnr_db'] is None or not math.isfinite(value['sqnr_db']) or not math.isclose(value['sqnr_db'],expected,rel_tol=1e-12,abs_tol=1e-12):
            raise RuntimeError('Inconsistent linear SQNR metric')
    elif value['sqnr_db'] is not None:raise RuntimeError('Exact linear result must report undefined infinite SQNR as null')


def measure(plan):
    validate_plan(plan);family=plan['family'];category=plan['category'];trace=SatTrace()
    record={key:plan[key] for key in ('case','family','category','blocks','dimension','input_clamps')}
    record.update(config_hash=fingerprint(plan['config']),input_hash=fingerprint(plan['observations']),
                  inputs=len(plan['observations']),quality_accepted=False,
                  output_units='Q15-normalized signal amplitude; one unit = 32768 integer counts',
                  coefficient_units='dimensionless linear coefficients',
                  coefficient_format=('native signed48 Q24' if family=='mmse2' else 'native signed64 Q24')
                     if family in MODELS else 'effective pre-rounding coefficients from native Q15 configuration and encoded R/Z')
    if category.endswith('_rejection'):
        proof=rejection_proof(plan)
        try:fixed_outputs(plan,trace)
        except ValueError as exc:
            text=str(exc).lower()
            expected=('singular' in text if category=='singular_rejection' else
                      ('coefficient' in text and str(proof['signed_coefficient_bits']) in text) if category=='coefficient_rejection' else
                      'zero weight energy' in text)
            if not expected:raise RuntimeError('Wrong configuration rejection category') from exc
            return dict(record,status='rejected_configuration',outputs=0,rejection_verified=True,rejection_reason=str(exc),
                        independent_rejection_proof=proof,saturation=trace.to_dict())
        raise RuntimeError('Invalid configuration was accepted')
    actual_rows=fixed_outputs(plan,trace)
    if actual_rows!=fixed_outputs(plan):raise RuntimeError('Linear clamp instrumentation changed numeric outputs')
    actual=complex_words(actual_rows);reference,coefficient_reference=floating_reference(plan)
    fixed_W=fixed_coefficients(plan)
    clipped=np.clip(reference.real,-4,131071/32768)+1j*np.clip(reference.imag,-4,131071/32768)
    outside=int(np.count_nonzero((reference.real<-4)|(reference.real>131071/32768))
                +np.count_nonzero((reference.imag<-4)|(reference.imag>131071/32768)))
    record.update(status='measured',outputs=len(actual_rows),instrumented_equal=True,
                  saturation=trace.to_dict(),expected_evaluations=evaluation_counts(plan),
                  unclipped_output=metric(actual,reference),clipped_output=metric(actual,clipped),
                  coefficients=metric(fixed_W,coefficient_reference),float_components_outside_output_range=outside,
                  coefficient_reference_basis='r0, conjugate(r1)' if family=='alamouti' else 'direct observation columns')
    record['quality_accepted']=nominal_quality(record)
    return record


def report():
    return dict(scope=SCOPE,budget=dict(BUDGET),seed=SEED,nominal_blocks=BLOCKS,rtl_numeric_observed=False,
                methodological_notes=['MMSE weights are Q24, signed48 for 2x2 and signed64 for 3x3; output is signed18 Q15.',
                                      'Beam/Alamouti effective fixed coefficients describe the actual R/Z normalizer, not a coefficient dump port.',
                                      'NumPy reference never uses fixed coefficients or reciprocal encodings; Alamouti uses the documented conjugated second observation.',
                                      'Clamp diagnostics expose unclipped distortion and clipped-reference agreement separately.',
                                      'Coefficient rejection uses exact raw determinant/adjugate certificates, avoiding ill-conditioned floating Gram classification.'],
                records=[measure(plan) for plan in plans()])


def check_acceptance(result):
    expected={p['case']:p for p in plans()};records=result['records']
    if not records or len(records)!=len(expected) or {r['case'] for r in records}!=set(expected):
        raise RuntimeError('Incomplete linear precision coverage')
    if result['budget']!=BUDGET:raise RuntimeError('Linear precision budget metadata changed')
    for record in records:
        plan=expected[record['case']]
        if any(record[key]!=plan[key] for key in ('family','category','blocks','dimension','input_clamps')):
            raise RuntimeError('Linear case shape/classification metadata changed')
        if (record['inputs']!=len(plan['observations']) or record['config_hash']!=fingerprint(plan['config'])
                or record['input_hash']!=fingerprint(plan['observations'])):
            raise RuntimeError('Linear reference did not use declared common configuration/inputs')
        category=plan['category']
        if category.endswith('_rejection'):
            if (record['status']!='rejected_configuration' or record['rejection_verified'] is not True
                    or record['quality_accepted'] is not False or record['outputs']!=0
                    or record['independent_rejection_proof']!=rejection_proof(plan)
                    or record['saturation']!={'stages':{},'total':0,'evaluations':{}}):
                raise RuntimeError('Incomplete or mislabeled linear configuration rejection')
            continue
        counts=evaluation_counts(plan);actual=record['saturation']['evaluations']
        if (record['status']!='measured' or record['instrumented_equal'] is not True or record['outputs']!=output_count(plan)
                or record['expected_evaluations']!=counts or actual!=counts):
            raise RuntimeError('Incomplete measured linear output/clamp shape evidence')
        for key in ('unclipped_output','clipped_output'):
            validate_metric(record[key])
            if record[key]['shape']!=[output_count(plan)] or record[key]['items']!=output_count(plan):
                raise RuntimeError('Incomplete linear output metric span')
        cshape=[plan['dimension'],plan['dimension']] if plan['family'] in MODELS else ([plan['dimension']] if plan['family']=='beamformer' else [2,2])
        validate_metric(record['coefficients'])
        if record['coefficients']['shape']!=cshape or record['coefficients']['items']!=math.prod(cshape):
            raise RuntimeError('Invalid linear coefficient metric shape')
        total=sum(c['pos']+c['neg'] for c in record['saturation']['stages'].values())
        if record['saturation']['total']!=total:raise RuntimeError('Inconsistent linear clamp totals')
        if category=='nominal':
            if record['quality_accepted'] is not True or not nominal_quality(record):
                raise RuntimeError(f"Nominal linear quality failed: {record['case']}")
        elif (record['quality_accepted'] is not False or total<=0 or record['float_components_outside_output_range']<=0
              or record['clipped_output']['max_complex_deviation']>BUDGET['clipped_stress_max_signal_units']):
            raise RuntimeError('Missing real output-clamp diagnostic evidence')


def main(argv=None):
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/linear_precision/results.json');args=parser.parse_args(argv)
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING',scope=SCOPE));result={}
    try:result=report();check_acceptance(result);completed=finish(evidence)
    except Exception as exc:
        try:completed=finish(evidence)
        except RuntimeError as snapshot_error:completed=dict(evidence,source_snapshot_error=str(snapshot_error))
        write_json(args.output,dict(completed,status='FAIL',error=str(exc),result=result));raise
    write_json(args.output,dict(completed,status='PASS',**result))
    for record in result['records']:
        if record['category']=='nominal':
            metric_=record['unclipped_output'];sqnr='exact' if metric_['comparison_exact'] else f"{metric_['sqnr_db']:.2f} dB"
            print(f"PASS {record['case']}: SQNR {sqnr}, RMS deviation {metric_['rms_deviation']:.6g} signal units")
        else:print(f"DIAGNOSTIC {record['case']}: {record['status']}; quality accepted=False")
    return 0


if __name__=='__main__':raise SystemExit(main())
