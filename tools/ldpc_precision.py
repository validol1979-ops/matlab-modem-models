#!/usr/bin/env python3
"""Full LDPC model versus independent floating flooding, plus exact GF(2).

Common inputs: signed16 Q8 LLRs, binary parity check H and actual Q8 alpha/beta.
Independent sum-product uses stable analytic phi arithmetic in the log domain,
not production PHI/INV tables or clipped tanh products. Floating variable/posterior states are not saturated.
Both start with zero messages and run at least one iteration, stopping on syndrome0.
Terminal posteriors can correspond to different early-stop iterations: this is measured.
A separate comparison uses a common preset one-iteration cap, without truth alignment.
Only metrics see original codewords. Evidence is Python model-only, no new RTL claim.
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
import ldpc_fixed as fixed
from sat_diag import SatTrace

FRAMES=64
ITERATIONS=20
SEED=8319
A=np.array([[1,1,0,1,0,0],[0,1,1,0,1,0],[1,0,1,0,0,1],
            [1,1,0,0,1,0],[0,1,1,1,0,0],[1,0,1,0,1,1]],dtype=int)
H=np.column_stack((np.eye(6,dtype=int),A))
BUDGET=dict(clean_bit_errors_max=0,nominal_input_clamps_max=0,nominal_internal_clamps_max=0,
            first_iteration_posterior_rms_max_llr_units=.08,
            noisy_ber_excess_max=.03,noisy_fer_excess_max=.10)
FORMATS=dict(llr='signed16 Q8; positive means bit0; raw/256 gives dimensionless log likelihood',
             alpha='uint9 Q8 <=256',beta='uint16 Q8',matrix='binary H; systematic H=[I A]',
             fixed_state='signed16 Q8 variable/posterior saturate; messages start at0',
             floating_state='Independent double precision, no state saturation or fixed-derived messages',
             mode0='Fixed PHI/INV quantized lookup versus stable analytic phi arithmetic',
             floating_sum_product='Log-domain phi sum/inversion; zero other input gives zero outgoing message; no artificial message cap',
             modes123='Min-sum, Q8 normalized alpha, Q8 offset beta',
             noise='Real BPSK amplitude1 AWGN, noise variance=10**(-SNR_dB/10), LLR=2*r/variance',
             stop='At least1 iteration; first zero syndrome or configured iteration cap',
             posterior_policy='Terminal comparison may have unequal stop times; preset cap1 comparison also scored')
SCOPE='Production LDPC decisions and Q8 posteriors versus independent float flooding; GF2 exact independent matrix product. Model-only.'


def fingerprint(value):return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def gf2_reference(messages,matrix):
    b=np.asarray(messages);a=np.asarray(matrix)
    if a.ndim!=2 or b.ndim!=2 or b.shape[1]!=a.shape[1] or not b.shape[0] or not a.shape[0]:raise ValueError('GF2 shape')
    if not np.isin(a,[0,1]).all() or not np.isin(b,[0,1]).all():raise ValueError('GF2 binary input')
    return np.column_stack(((b.astype(np.int64)@a.astype(np.int64).T)%2,b)).astype(int)


def quantize(llrs):
    x=np.asarray(llrs,float)
    if not np.all(np.isfinite(x)):raise ValueError('Finite LLR required')
    raw=np.rint(x*256);bounded=np.clip(raw,-32768,32767)
    return bounded.astype(int).tolist(),int(np.count_nonzero(raw!=bounded))


def plans():
    rng=np.random.default_rng(SEED);data=[]
    messages=rng.integers(0,2,(FRAMES,6));words=gf2_reference(messages,A)
    symbols=1-2*words
    for name,snr,category in [('clean',None,'nominal'),('noisy',4.,'nominal'),('near_threshold',-2.,'diagnostic')]:
        variance=0 if snr is None else 10**(-snr/10)
        noise=np.zeros(symbols.shape) if snr is None else rng.normal(size=symbols.shape)*math.sqrt(variance)
        llr=symbols*6. if snr is None else 2*(symbols+noise)/variance
        raw,clamps=quantize(llr)
        data.append(dict(name=name,category=category,llrs=raw,words=words.tolist(),input_clamps=clamps,snr_db=snr,
                         signal_power=1.,noise_variance=variance,realized_noise_energy=float(np.sum(noise**2)),
                         realized_noise_power=float(np.mean(noise**2)),channel_note='Clean uses deterministic +/-6 LLR, zero physical noise' if snr is None else 'BPSK AWGN before common LLR quantization'))
    word=gf2_reference([[1,0,1,1,0,1]],A)[0]
    rails=[32767 if b==0 else -32767 for b in word]
    for name,values in [('posterior_clamp',rails),('variable_clamp',[(-v if c==1 else v) for c,v in enumerate(rails)])]:
        data.append(dict(name=name,category='clamp_stress',llrs=[values],words=[word.tolist()],input_clamps=0,
                         snr_db=None,signal_power=None,noise_variance=None,realized_noise_energy=None,realized_noise_power=None,
                         channel_note='Deterministic legal Q8 rails; no physical AWGN/SNR claim'))
    result=[]
    for mode in range(4):
        for sample in data:
            p={k:v for k,v in sample.items() if k!='name'}
            p.update(case=f'mode{mode}_{sample["name"]}',family='ldpc',mode=mode,H=H.tolist(),frames=len(sample['llrs']),
                     columns=12,checks=6,iterations=ITERATIONS,alpha_raw=205,beta_raw=38)
            result.append(p)
    for m,k,count in [(1,1,8),(6,6,64),(12,17,32)]:
        matrix=rng.integers(0,2,(m,k));bits=rng.integers(0,2,(count,k));bits[:2]=[np.zeros(k,dtype=int),np.ones(k,dtype=int)]
        result.append(dict(case=f'gf2_{m}x{k}',family='gf2',category='exact',A=matrix.tolist(),messages=bits.tolist(),frames=count,parity=m,message_bits=k))
    return result


def validate_plan(p):
    def binary(a):
        arr=np.asarray(a)
        if arr.dtype.kind not in 'iu' or not np.isin(arr,[0,1]).all():raise ValueError('Integer binary matrix required')
        return arr
    if p['family']=='gf2':
        a=binary(p['A']);b=binary(p['messages'])
        if a.shape!=(p['parity'],p['message_bits']) or b.shape!=(p['frames'],p['message_bits']):raise ValueError('GF2 shape mismatch')
        return
    if p['family']!='ldpc':raise ValueError('Unknown track')
    h=binary(p['H']);words=binary(p['words']);llrs=np.asarray(p['llrs'])
    if h.shape!=(p['checks'],p['columns']) or words.shape!=(p['frames'],p['columns']) or llrs.shape!=words.shape:
        raise ValueError('LDPC shape mismatch')
    if llrs.dtype.kind not in 'iu' or np.any(llrs<-32768) or np.any(llrs>32767):raise ValueError('signed16 Q8 required')
    if np.any(h.sum(axis=1)<2) or np.any((words@h.T)%2):raise ValueError('Original words must satisfy actual H')
    for key,low,high in [('mode',0,3),('iterations',1,255),('alpha_raw',0,256),('beta_raw',0,65535)]:
        v=p[key]
        if not isinstance(v,Integral) or isinstance(v,bool) or not low<=v<=high:raise ValueError('Configuration word out of range')


def phi(value):
    """Analytic involution phi(x) for nonnegative x; zero maps to infinity."""
    x=float(value)
    if x<0 or math.isnan(x):raise ValueError('phi requires nonnegative magnitude')
    if x==0:return math.inf
    if math.isinf(x):return 0.
    if x>=1:return 2*math.atanh(math.exp(-x))
    return math.log1p(math.exp(-x))-math.log(-math.expm1(-x))


def log_phi(value):
    x=float(value)
    if x==0:return math.inf
    # phi(x)=2*exp(-x)*(1+O(exp(-2x))); error below double precision here.
    if x>=18:return math.log(2.)-x
    return math.log(phi(x))


def sum_product_message(rest):
    values=np.asarray(rest,float)
    if np.any(values==0):return 0.  # One zero tanh factor => zero outgoing message.
    logs=[log_phi(abs(x)) for x in values];top=max(logs)
    log_sum=top+math.log(sum(math.exp(v-top) for v in logs))
    # phi(S)=log(2)-log(S)+O(S**2); no underflow when S is extremely small.
    magnitude=math.log(2.)-log_sum if log_sum < -36 else phi(math.exp(log_sum))
    return float(np.prod(np.sign(values)))*magnitude


def floating(llr,H,iterations,mode,alpha,beta):
    """Independent complete stable-phi flooding. No truth/codeword or production LUT/state."""
    h=np.asarray(H,dtype=int);channel=np.asarray(llr,dtype=float)/256
    if channel.shape!=(h.shape[1],) or not np.all(np.isfinite(channel)):raise ValueError('Float decoder LLR shape')
    checks=[np.flatnonzero(row) for row in h];messages=np.zeros(h.shape);post=channel.copy()
    for used in range(1,iterations+1):
        variable=post[None,:]-messages;new=np.zeros(h.shape)
        for row,cols in enumerate(checks):
            for col in cols:
                rest=variable[row,cols[cols!=col]]
                if mode==0:
                    new[row,col]=sum_product_message(rest)
                else:
                    magnitude=np.min(abs(rest))
                    if mode==2:magnitude*=alpha
                    if mode==3:magnitude=max(0,magnitude-beta)
                    new[row,col]=np.prod(np.sign(rest))*magnitude
        messages=new;post=channel+messages.sum(axis=0);bits=(post<0).astype(int)
        syndrome=(h@bits)%2
        if not np.any(syndrome):break
    return bits,post,used


def metric(actual,reference):
    a=np.asarray(actual,float);b=np.asarray(reference,float)
    if a.shape!=b.shape or not a.size or not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)):raise ValueError('Posterior shape/finite')
    mse=float(np.mean((a-b)**2));power=float(np.mean(b*b))
    return dict(count=int(a.size),mse_llr_units_squared=mse,rms_llr_units=math.sqrt(mse),
                max_llr_units=float(np.max(abs(a-b))),reference_rms_llr_units=math.sqrt(power),
                sqnr_db=None if mse==0 or power==0 else 10*math.log10(power/mse),exact=mse==0)


def decision(bits,words,H):
    b=np.asarray(bits);w=np.asarray(words);syndrome=(b@np.asarray(H).T)%2
    return dict(bit_errors=int(np.count_nonzero(b!=w)),frame_errors=int(np.count_nonzero(np.any(b!=w,axis=1))),
                syndrome_bits=int(np.count_nonzero(syndrome)),syndrome_frames=int(np.count_nonzero(np.any(syndrome,axis=1))),
                undetected_frame_errors=int(np.count_nonzero(np.any(b!=w,axis=1)&~np.any(syndrome,axis=1))),
                ber=float(np.mean(b!=w)),fer=float(np.mean(np.any(b!=w,axis=1))),
                bits=b.tolist(),syndromes=syndrome.tolist())


def evaluate(p):
    validate_plan(p);r={k:v for k,v in p.items() if k not in ('llrs','words','messages','A','H')}
    r.update(plan_hash=fingerprint(p),model_only=True,quality_claim=p['category'] in ('nominal','exact'))
    if p['family']=='gf2':
        reference=gf2_reference(p['messages'],p['A']);actual=np.array([fixed.encode(bits,p['A']) for bits in p['messages']])
        r.update(output_shape=list(actual.shape),mismatched_bits=int(np.count_nonzero(actual!=reference)),
                 actual_words=actual.tolist(),reference_words=reference.tolist());return r
    alpha=p['alpha_raw']/256;beta=p['beta_raw']/256;trace=SatTrace()
    bs=[];bf=[];ps=[];pf=[];us=[];uf=[];firsts=[];firstf=[]
    for llr in p['llrs']:
        bits,posterior,used=fixed.decode(llr,p['H'],p['iterations'],p['mode'],alpha,beta,stats=trace)
        fbits,fpost,fused=floating(llr,p['H'],p['iterations'],p['mode'],alpha,beta)
        bs.append(bits);bf.append(fbits);ps.append(np.asarray(posterior)/256);pf.append(fpost);us.append(used);uf.append(fused)
        firsts.append(np.asarray(fixed.decode(llr,p['H'],1,p['mode'],alpha,beta)[1])/256)
        firstf.append(floating(llr,p['H'],1,p['mode'],alpha,beta)[1])
    edges=int(np.sum(p['H']));evals=dict(v=edges*sum(us),post=p['columns']*sum(us))
    r.update(alpha=alpha,beta=beta,edges=edges,output_shape=[p['frames'],p['columns']],
             fixed=decision(bs,p['words'],p['H']),floating=decision(bf,p['words'],p['H']),
             decision_mismatches=int(np.count_nonzero(np.asarray(bs)!=np.asarray(bf))),
             fixed_iterations=us,float_iterations=uf,iteration_mismatch_frames=sum(a!=b for a,b in zip(us,uf)),
             fixed_posteriors=np.asarray(ps).tolist(),float_posteriors=np.asarray(pf).tolist(),
             fixed_first_posteriors=np.asarray(firsts).tolist(),float_first_posteriors=np.asarray(firstf).tolist(),
             terminal_posterior_error=metric(ps,pf),first_iteration_posterior_error=metric(firsts,firstf),
             trace=trace.to_dict(),expected_evaluations=evals)
    return r


def check_acceptance(report):
    if report['budget']!=BUDGET or report['formats']!=FORMATS or report['scope']!=SCOPE or report['model_only'] is not True:raise ValueError('Policy mismatch')
    expected=plans();records=report['records']
    if len(records)!=len(expected) or len({r['case'] for r in records})!=len(expected):raise ValueError('Coverage mismatch')
    byname={r['case']:r for r in records}
    for p in expected:
        r=byname.get(p['case'])
        if not r or r['plan_hash']!=fingerprint(p):raise ValueError('Plan mismatch')
        for k,v in p.items():
            if k not in ('llrs','words','messages','A','H') and r.get(k)!=v:raise ValueError('Metadata mismatch')
        if r['model_only'] is not True or r['quality_claim']!=(p['category'] in ('nominal','exact')):raise ValueError('Quality scope')
        if p['family']=='gf2':
            ref=gf2_reference(p['messages'],p['A']);a=np.asarray(r['actual_words']);b=np.asarray(r['reference_words'])
            if r['output_shape']!=list(ref.shape) or a.shape!=ref.shape or not np.array_equal(b,ref) or not np.array_equal(a,ref) or r['mismatched_bits']!=0:raise ValueError('GF2 exact failed')
            continue
        shape=(p['frames'],p['columns']);h=np.asarray(p['H'])
        if r['output_shape']!=list(shape) or r['alpha']!=p['alpha_raw']/256 or r['beta']!=p['beta_raw']/256:raise ValueError('LDPC output/config shape')
        for family in ('fixed','floating'):
            d=r[family];bits=np.asarray(d['bits'])
            if bits.shape!=shape or not np.isin(bits,[0,1]).all():raise ValueError('Decision shape')
            if d!=decision(bits,p['words'],p['H']):raise ValueError('Decision evidence inconsistent with truth/syndrome')
            used=r['fixed_iterations' if family=='fixed' else 'float_iterations']
            if len(used)!=p['frames'] or any(not isinstance(v,int) or isinstance(v,bool) or not 1<=v<=p['iterations'] for v in used):raise ValueError('Iteration span')
            for count,bad in zip(used,np.any(np.asarray(d['syndromes']),axis=1)):
                if bad and count!=p['iterations']:raise ValueError('Unsatisfied syndrome stopped early')
        us=r['fixed_iterations'];uf=r['float_iterations'];edges=int(h.sum());evals=dict(v=edges*sum(us),post=p['columns']*sum(us));tr=r['trace']
        if r['edges']!=edges or r['expected_evaluations']!=evals or tr['evaluations']!=evals:raise ValueError('Evaluation counts')
        total=0
        for stage,c in tr['stages'].items():
            if stage not in evals or set(c)!={'pos','neg'} or any(not isinstance(v,int) or v<0 for v in c.values()) or sum(c.values())>evals[stage]:raise ValueError('Clamp counts')
            total+=sum(c.values())
        if total!=tr['total'] or r['iteration_mismatch_frames']!=sum(a!=b for a,b in zip(us,uf)):raise ValueError('Total/iteration mismatch')
        mismatch=int(np.count_nonzero(np.asarray(r['fixed']['bits'])!=np.asarray(r['floating']['bits'])))
        if r['decision_mismatches']!=mismatch:raise ValueError('Decision mismatch count')
        for field,actualkey,refkey in [('terminal_posterior_error','fixed_posteriors','float_posteriors'),('first_iteration_posterior_error','fixed_first_posteriors','float_first_posteriors')]:
            a=np.asarray(r[actualkey]);b=np.asarray(r[refkey])
            if a.shape!=shape or b.shape!=shape:raise ValueError('Posterior shape')
            expected_metric=metric(a,b)
            if r[field]!=expected_metric:raise ValueError('Posterior metric mismatch')
        for family,terminalkey,firstkey,usedkey in (
                ('fixed','fixed_posteriors','fixed_first_posteriors','fixed_iterations'),
                ('floating','float_posteriors','float_first_posteriors','float_iterations')):
            terminal=np.asarray(r[terminalkey]);first=np.asarray(r[firstkey]);used=r[usedkey]
            if not np.array_equal(np.asarray(r[family]['bits']),(terminal<0).astype(int)):
                raise ValueError('Decoded bits contradict terminal posterior signs')
            first_satisfied=~np.any(((first<0).astype(int)@h.T)%2,axis=1)
            for frame,count in enumerate(used):
                if first_satisfied[frame] and count!=1:raise ValueError('First syndrome satisfied but decoder did not stop at1')
                if count==1 and not np.array_equal(terminal[frame],first[frame]):
                    raise ValueError('One iteration terminal posterior contradicts first posterior')
        if p['category']=='nominal':
            if total or p['input_clamps'] or r['first_iteration_posterior_error']['rms_llr_units']>BUDGET['first_iteration_posterior_rms_max_llr_units']:raise ValueError('Nominal precision/clipping budget')
            if p['case'].endswith('_clean') and (r['fixed']['bit_errors'] or r['floating']['bit_errors']):raise ValueError('Clean decoder failed')
            if r['fixed']['ber']>r['floating']['ber']+BUDGET['noisy_ber_excess_max'] or r['fixed']['fer']>r['floating']['fer']+BUDGET['noisy_fer_excess_max']:raise ValueError('Nominal decoding degradation')
        if p['category']=='clamp_stress':
            stage='v' if p['case'].endswith('variable_clamp') else 'post'
            if sum(tr['stages'].get(stage,{}).values())<=0:raise ValueError('Required stress clamp unexercised')
    return True


def run_report(path):
    require_unoptimized();evidence=begin();r=dict(evidence,status='RUNNING',model_only=True,scope=SCOPE,formats=dict(FORMATS),budget=dict(BUDGET),records=[]);write_json(path,r)
    try:
        r['records']=[evaluate(p) for p in plans()];check_acceptance(r);r.update(finish(evidence));r['status']='PASS';write_json(path,r)
    except Exception as exc:r['status']='FAIL';r['failure']=str(exc);write_json(path,r);raise
    return r


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,default=ROOT/'build/rtl/ldpc_precision/results.json');a=p.parse_args()
    r=run_report(a.output);print(f"PASS LDPC/GF2 precision: {len(r['records'])} cases; {a.output}")

if __name__=='__main__':main()
