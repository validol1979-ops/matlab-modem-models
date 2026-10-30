#!/usr/bin/env python3
"""Causal notch/Kalman model precision and FSK decisions on common Q15 words.

This is Python model evidence, not a new RTL equivalence claim. Float recurrences
start from zero, consume quantized coefficients/inputs and never fixed states.
Notch b1/a1/a2 are Q16; Kalman Q/R/P0 are unsigned Q24 (no lambda parameter).
Kalman fixed K is Q17, covariance Q24 and value Q23; notch state is Q20.
FSK float phasors use the same uint32 turn increment, without the fixed Q17 LUT.
"""
import argparse
import hashlib
import json
import math
from numbers import Integral
from pathlib import Path
import sys
import numpy as np
from regression_evidence import ROOT,begin,finish,require_unoptimized,write_json
sys.path.insert(0,str(ROOT/'common/python'))
import oset_fixed as o
import fsk_fixed as fsk
from sat_diag import SatTrace

N=1024
SETTLE=256
SEED=7283
BUDGET=dict(nominal_rms_max_signal_units=5e-5,nominal_max_signal_units=1e-4,
            nominal_sqnr_min_db=60.,low_reference_rms_signal_units=.01,
            nominal_clamps_max=0,fsk_correlator_rms_max_signal_units=.002,
            fsk_decision_mismatch_fraction_max=.02)
FORMATS=dict(signal='signed18 Q15, normalized amplitude units',notch_coefficients='signed18 Q16',
             notch_state='signed25 Q20 with actual saturation',kalman_parameters='unsigned Q24 Q/R/P0',
             kalman_covariance='unsigned32 Q24',kalman_gain='Q17',kalman_value='Q23',
             fsk_steps='uint32 turns per sample',fsk_basis='fixed Q17 LUT versus analytic float phasors',
             initial_state='Zero signal histories and value; Kalman covariance starts at common P0',
             lambda_parameter='Not applicable to these tracks',
             float_policy='No fixed-derived states/gains; no fitting to truth')
SCOPE=('Complete production notch/Kalman recurrences versus independent float arithmetic on common '
       'once-quantized configurations and inputs; FSK actual correlator decisions on common waveforms. '
       'Signal units are signed18 Q15 / 32768. No new RTL observation or default width change.')


def fingerprint(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def words(values):
    a=np.asarray(values,complex)
    if a.ndim!=1 or not len(a) or not np.all(np.isfinite(a)):raise ValueError('Finite nonempty vector required')
    raw=np.rint(np.column_stack((a.real,a.imag))*32768);clipped=np.clip(raw,-131072,131071)
    return [tuple(map(int,row)) for row in clipped],int(np.count_nonzero(raw!=clipped))


def signal(rows):return np.array([complex(re,im) for re,im in rows])/32768


def plans():
    rng=np.random.default_rng(SEED);t=np.arange(N);result=[]
    def add(name,family,category,config,x,start=SETTLE,**extra):
        raw,clamps=words(x)
        result.append(dict(case=name,family=family,category=category,config=list(config),inputs=raw,
                           samples=len(raw),score_start=start,input_clamps=clamps,**extra))
    for name,freq,radius in [('tone',.23,.94),('near_dc',0.,.9),('narrow',.07,.98),('wide',.4,.7)]:
        # A wanted tone away from the notch, plus an interfering notch tone and Gaussian noise.
        x=.2*np.exp(2j*np.pi*.13*t)+.3*np.exp(2j*np.pi*freq*t)
        x+=.02*(rng.standard_normal(N)+1j*rng.standard_normal(N))/np.sqrt(2)
        add('notch_'+name,'notch','nominal',o.notch_coefficients(freq,radius),x)
    for name,param in [('slow',(.0005,.25,1)),('fast',(.01,.1,.5)),('static',(0,.25,1)),('disabled',(0,.25,0))]:
        truth=.4+.15j+.1*np.sin(2*np.pi*.003*t)
        noise=.1*(rng.standard_normal(N)+1j*rng.standard_normal(N))/np.sqrt(2)
        x=truth+noise
        add('kalman_'+name,'kalman','nominal',o.kalman_parameters(*param),x,
            truth=[[float(z.real),float(z.imag)] for z in truth],measurement_noise_power=.01,
            realized_noise_energy_signal_units_squared=float(np.sum(abs(noise)**2)),
            realized_noise_power_signal_units_squared=float(np.mean(abs(noise)**2)))
    rail=(131071+131071j)/32768;negative=(-131072-131072j)/32768
    add('notch_output_clamp','notch','clamp_stress',o.notch_coefficients(.23,.94),[rail]*200+[negative]*200,0)
    add('notch_state_clamp','notch','clamp_stress',(-131072,-98304,0),[rail]*64,0,
        configuration_note='Raw port-valid unstable a1=-1.5; not a stable designed profile')
    add('kalman_legal_rails','kalman','rail_stress',o.kalman_parameters(.0005,.25,1),[rail]*400+[negative]*400,0)
    for name,n,order,f0,df,snr in [('quiet4',32,4,2,3,None),('noisy20',40,8,.5,1.5,20.),
                                 ('noisy0',32,4,2,3,0.),('noisy_low',32,4,2,3,-12.)]:
        table=fsk.steps(n,f0,df,order);labels=np.tile(np.arange(order),32)
        phase=np.array(table,dtype=np.float64)/2**32
        clean=np.exp(2j*np.pi*phase[labels,None]*np.arange(n)).reshape(-1)
        noise_power=0. if snr is None else 10**(-snr/10)
        noise=np.sqrt(noise_power/2)*(rng.standard_normal(len(clean))+1j*rng.standard_normal(len(clean)))
        add('fsk_'+name,'fsk','decision',table,clean+noise,0,block_samples=n,order=order,
            labels=list(map(int,labels)),signal_power_signal_units_squared=1.,
            noise_power_signal_units_squared=noise_power,snr_db=snr,
            realized_noise_energy_signal_units_squared=float(np.sum(abs(noise)**2)),
            realized_noise_power_signal_units_squared=float(np.mean(abs(noise)**2)),
            noise_location='Before common Q15 quantization; input clamps are measured')
    return result


def validate_plan(p):
    n=p['samples'];family=p['family'];config=p['config']
    if not isinstance(n,Integral) or isinstance(n,bool) or n<1 or len(p['inputs'])!=n:
        raise ValueError('Input shape mismatch')
    if not isinstance(p['score_start'],Integral) or not 0<=p['score_start']<n:raise ValueError('Empty scoring range')
    for pair in p['inputs']:
        if len(pair)!=2 or any(not isinstance(v,Integral) or isinstance(v,bool) or not -131072<=v<=131071 for v in pair):
            raise ValueError('Expected signed18 integer pair')
    if any(not isinstance(v,Integral) or isinstance(v,bool) for v in config):raise ValueError('Integer configuration required')
    if family=='notch':
        if len(config)!=3 or any(not -131072<=v<=131071 for v in config):raise ValueError('Notch Q16 configuration')
    elif family=='kalman':
        if len(config)!=3 or any(not 0<=v<2**31 for v in config) or config[1]==0:raise ValueError('Kalman Q24 configuration')
        if 'truth' in p and (np.asarray(p['truth']).shape!=(n,2) or not np.all(np.isfinite(p['truth']))):raise ValueError('Truth shape')
    elif family=='fsk':
        if len(config)!=p['order'] or any(not 0<=v<2**32 for v in config):raise ValueError('FSK step shape')
        m=p['block_samples']
        if m<1 or n%m or len(p['labels'])!=n//m or any(not 0<=v<p['order'] for v in p['labels']):raise ValueError('FSK whole symbols required')
    else:raise ValueError('Unknown family')


def floating(p):
    """No truth, integer states, quantized gains or fixed coefficients beyond common ports."""
    validate_plan(p);x=signal(p['inputs']);family=p['family']
    if family=='notch':
        b,a,c=np.array(p['config'],float)/65536;y=np.zeros(len(x),complex)
        for k,z in enumerate(x):
            y[k]=z
            if k:y[k]+=b*x[k-1]+a*y[k-1]
            if k>1:y[k]+=x[k-2]+c*y[k-2]
        return y
    if family=='kalman':
        q,r,covariance=np.array(p['config'],float)/2**24;value=0j;y=[]
        for z in x:
            covariance+=q;gain=covariance/(covariance+r)
            value+=gain*(z-value);covariance*=1-gain;y.append(value)
        return np.array(y)
    n=p['block_samples'];phase=np.array(p['config'],dtype=float)/2**32
    basis=np.exp(-2j*np.pi*phase[:,None]*np.arange(n))
    return x.reshape(-1,n)@basis.T/2**((n-1).bit_length())


def metrics(actual,reference):
    a=np.asarray(actual,complex);b=np.asarray(reference,complex)
    if a.shape!=b.shape or a.size==0 or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):
        raise ValueError('Finite equally shaped output required')
    mse=float(np.mean(abs(a-b)**2));power=float(np.mean(abs(b)**2))
    return dict(count=int(a.size),mse_signal_units_squared=mse,rms_signal_units=math.sqrt(mse),
                max_signal_units=float(np.max(abs(a-b))),reference_rms_signal_units=math.sqrt(power),
                sqnr_db=None if mse==0 or power==0 else 10*math.log10(power/mse),
                exact=mse==0)


def expected_evaluations(p):
    if p['family']=='fsk':return {}
    stages=['notch.state.re','notch.state.im','notch.output.re','notch.output.im'] if p['family']=='notch' else ['kalman.output.re','kalman.output.im']
    return dict.fromkeys(stages,p['samples'])


def fixed_correlations(p):
    """Observe actual production LUT/rounding formula; receive() verifies decisions."""
    n=p['block_samples'];shift=17+(n-1).bit_length();result=[]
    for start in range(0,p['samples'],n):
        row=[]
        for step in p['config']:
            re=im=0
            for t,(xr,xi) in enumerate(p['inputs'][start:start+n]):
                c,s=fsk._basis(step,t);re+=xr*c+xi*s;im+=xi*c-xr*s
            row.append(complex(fsk.f.rnd(re,shift),fsk.f.rnd(im,shift))/32768)
        result.append(row)
    return np.array(result)


def evaluate(p):
    validate_plan(p);reference=floating(p);trace=SatTrace();family=p['family']
    r={k:v for k,v in p.items() if k not in ('inputs','truth','labels')}
    r.update(plan_hash=fingerprint(p),quality_claim=p['category']=='nominal',model_only=True,
             scored_stop=p['samples'],expected_evaluations=expected_evaluations(p))
    if family=='fsk':
        actual=fixed_correlations(p);decisions=np.array(fsk.receive(p['inputs'],p['block_samples'],p['config']))
        observed=np.argmax(abs(actual)**2,axis=1)
        if not np.array_equal(decisions,observed):raise RuntimeError('Correlation observer differs from production receiver')
        floatdec=np.argmax(abs(reference)**2,axis=1);labels=np.array(p['labels'])
        r.update(correlator_error=metrics(actual,reference),correlator_shape=list(actual.shape),symbols=len(labels),
                 fixed_decisions=decisions.astype(int).tolist(),float_decisions=floatdec.astype(int).tolist(),
                 fixed_correlations=np.stack((actual.real,actual.imag),axis=-1).tolist(),
                 float_correlations=np.stack((reference.real,reference.imag),axis=-1).tolist(),
                 fixed_errors=int(np.count_nonzero(decisions!=labels)),float_errors=int(np.count_nonzero(floatdec!=labels)),
                 decision_mismatches=int(np.count_nonzero(decisions!=floatdec)),
                 fixed_ser=float(np.mean(decisions!=labels)),float_ser=float(np.mean(floatdec!=labels)),
                 decision_mismatch_fraction=float(np.mean(decisions!=floatdec)))
    else:
        raw=(o.notch if family=='notch' else o.kalman)(p['inputs'],p['config'],stats=trace)
        actual=signal(raw);start=p['score_start']
        r.update(output_error=metrics(actual,reference),steady_error=metrics(actual[start:],reference[start:]),output_samples=len(raw))
        if 'truth' in p:
            truth=np.array([complex(*z) for z in p['truth']]);r['fixed_tracking_error']=metrics(actual[start:],truth[start:]);r['float_tracking_error']=metrics(reference[start:],truth[start:])
    r['trace']=trace.to_dict();return r


def _validate_metric(m,count):
    if m['count']!=count:raise ValueError('Metric scoring count')
    for k in ('mse_signal_units_squared','rms_signal_units','max_signal_units','reference_rms_signal_units'):
        if not isinstance(m[k],(int,float)) or not math.isfinite(m[k]) or m[k]<0:raise ValueError('Invalid metric')
    mse=m['mse_signal_units_squared'];power=m['reference_rms_signal_units']**2
    if not math.isclose(m['rms_signal_units']**2,mse,rel_tol=1e-10,abs_tol=1e-30) or m['exact']!=(mse==0):raise ValueError('Incoherent MSE')
    expected=None if mse==0 or power==0 else 10*math.log10(power/mse)
    if expected is None:
        if m['sqnr_db'] is not None:raise ValueError('Undefined SQNR')
    elif m['sqnr_db'] is None or not math.isfinite(m['sqnr_db']) or not math.isclose(m['sqnr_db'],expected,abs_tol=1e-8):raise ValueError('Incoherent SQNR')
    if m['max_signal_units']<m['rms_signal_units']:raise ValueError('Incoherent maximum')


def check_acceptance(report):
    expected=plans();records=report['records']
    if report['budget']!=BUDGET or report['scope']!=SCOPE or report['formats']!=FORMATS or report['model_only'] is not True:raise ValueError('Report policy mismatch')
    if len(records)!=len(expected) or len({r['case'] for r in records})!=len(expected):raise ValueError('Coverage mismatch')
    byname={r['case']:r for r in records}
    for p in expected:
        r=byname.get(p['case'])
        if r is None or r['plan_hash']!=fingerprint(p):raise ValueError('Plan mismatch')
        for k,v in p.items():
            if k not in ('inputs','truth','labels') and r.get(k)!=v:raise ValueError('Plan metadata mismatch')
        if r['model_only'] is not True or r['quality_claim']!=(p['category']=='nominal') or r['scored_stop']!=p['samples']:raise ValueError('Scope mismatch')
        evals=expected_evaluations(p);tr=r['trace']
        if r['expected_evaluations']!=evals or tr['evaluations']!=evals:raise ValueError('Clamp evaluation coverage mismatch')
        total=0
        for stage,c in tr['stages'].items():
            if stage not in evals or set(c)!={'pos','neg'} or any(not isinstance(v,int) or isinstance(v,bool) or v<0 for v in c.values()) or sum(c.values())>evals[stage]:raise ValueError('Invalid clamp counts')
            total+=sum(c.values())
        if total!=tr['total']:raise ValueError('Clamp total mismatch')
        if p['family']=='fsk':
            symbols=len(p['labels']);_validate_metric(r['correlator_error'],symbols*p['order'])
            if r['symbols']!=symbols or r['correlator_shape']!=[symbols,p['order']]:raise ValueError('Symbol count')
            correlations=[];decisions=[]
            for corrkey,deckey in (('fixed_correlations','fixed_decisions'),('float_correlations','float_decisions')):
                raw=np.asarray(r[corrkey],float);d=np.asarray(r[deckey])
                if raw.shape!=(symbols,p['order'],2) or not np.all(np.isfinite(raw)):
                    raise ValueError('Finite FSK correlation shape required')
                if d.shape!=(symbols,) or d.dtype.kind not in 'iu' or np.any(d<0) or np.any(d>=p['order']):
                    raise ValueError('FSK decision shape/range')
                c=raw[:,:,0]+1j*raw[:,:,1]
                if not np.array_equal(d,np.argmax(abs(c)**2,axis=1)):
                    raise ValueError('FSK decisions contradict observed correlation argmax')
                correlations.append(c);decisions.append(d)
            if not np.array_equal(correlations[0],fixed_correlations(p)) or not np.array_equal(correlations[1],floating(p)):
                raise ValueError('FSK correlations contradict seeded common waveform/configuration')
            if not np.array_equal(decisions[0],fsk.receive(p['inputs'],p['block_samples'],p['config'])):
                raise ValueError('FSK observations contradict production receiver')
            if r['correlator_error']!=metrics(correlations[0],correlations[1]):raise ValueError('FSK correlation metric mismatch')
            labels=np.asarray(p['labels'])
            derived={'fixed_errors':int(np.count_nonzero(decisions[0]!=labels)),
                     'float_errors':int(np.count_nonzero(decisions[1]!=labels)),
                     'decision_mismatches':int(np.count_nonzero(decisions[0]!=decisions[1]))}
            if any(r[k]!=v for k,v in derived.items()):raise ValueError('FSK error counts contradict actual decisions and original labels')
            for countkey,fractionkey in [('fixed_errors','fixed_ser'),('float_errors','float_ser'),('decision_mismatches','decision_mismatch_fraction')]:
                v=r[countkey]
                if not isinstance(v,int) or isinstance(v,bool) or not 0<=v<=symbols or r[fractionkey]!=v/symbols:raise ValueError('Decision metric mismatch')
            if r['correlator_error']['rms_signal_units']>BUDGET['fsk_correlator_rms_max_signal_units'] or r['decision_mismatch_fraction']>BUDGET['fsk_decision_mismatch_fraction_max']:raise ValueError('FSK precision budget')
            if p['snr_db'] is None and (r['fixed_errors'] or r['float_errors'] or p['input_clamps']):raise ValueError('Quiet FSK failed')
        else:
            if r['output_samples']!=p['samples']:raise ValueError('Output shape')
            _validate_metric(r['output_error'],p['samples']);_validate_metric(r['steady_error'],p['samples']-p['score_start'])
            if 'truth' in p:
                for k in ('fixed_tracking_error','float_tracking_error'):_validate_metric(r[k],p['samples']-p['score_start'])
            if p['category']=='nominal':
                m=r['steady_error']
                if total or p['input_clamps'] or m['rms_signal_units']>BUDGET['nominal_rms_max_signal_units'] or m['max_signal_units']>BUDGET['nominal_max_signal_units']:raise ValueError('Nominal absolute precision/clipping budget')
                if m['reference_rms_signal_units']>=BUDGET['low_reference_rms_signal_units'] and not m['exact'] and (m['sqnr_db'] is None or m['sqnr_db']<BUDGET['nominal_sqnr_min_db']):raise ValueError('Nominal SQNR budget')
            elif p['category']=='clamp_stress':
                if total<=0:raise ValueError('Stress did not clip')
                prefix='notch.state.' if p['case']=='notch_state_clamp' else 'notch.output.'
                if not any(k.startswith(prefix) and sum(v.values())>0 for k,v in tr['stages'].items()):raise ValueError('Required clamp edge unexercised')
            elif p['category']=='rail_stress' and total:raise ValueError('Legal convex Kalman unexpectedly clips')
    return True


def run_report(path):
    require_unoptimized();evidence=begin();report=dict(evidence,status='RUNNING',model_only=True,scope=SCOPE,formats=dict(FORMATS),budget=dict(BUDGET),records=[])
    write_json(path,report)
    try:
        report['records']=[evaluate(p) for p in plans()];check_acceptance(report)
        report.update(finish(evidence));report['status']='PASS';write_json(path,report)
    except Exception as exc:
        report['status']='FAIL';report['failure']=str(exc);write_json(path,report);raise
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/state_precision/results.json');args=parser.parse_args()
    r=run_report(args.output)
    print(f"PASS state precision: {len(r['records'])} cases; {args.output}")

if __name__=='__main__':main()
