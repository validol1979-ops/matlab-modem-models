"""Runtime LMS/NLMS RTL vectors: the bit-exact outputs of common/python/lms_fixed.py for
rtl/common/lms_filter.sv (cfg.txt + in.txt -> out.txt + w.txt).

One configuration is the single cfg transfer (nlms flag, tap count N, MU = round(step*2^17),
EPS = round(eps*2^30) of lms_fixed.parameters). One transaction is one signal of L samples
(s_last on its last sample, x and the desired d of the same sample); every sample answers with
one (pred, e) output (m_last on the last sample) and the transaction then reports the N final
weights on w_* (w_last on the last weight). Each transaction starts from zero weights/history.

The first transaction is the model case (complex Gaussian/sqrt2, 512 samples, desired =
convolve(x, [.6+.1j,-.2+.1j,.15])[:512]) when taps == 3, the rest are random lengths in
[1, 300] with a random complex channel of `taps` taps as the 'true' system. x and d are Q15
clipped to the signed 18 bit range. out.txt holds `pre pim ere eim last`, w.txt holds the N
weights of every transaction in order as `re im last` (both from lms_fixed.adapt).

OUTPUT OVERLOAD TRANSACTION (sat18 of pred, e and of the reported weights, the `m` and `w`
covergroup bins). Every transaction restarts the filter from zero weights and history, so the last
transaction owns the whole adaptation trajectory and draws no random numbers. It is a small real
signal x = (a, 0) with a full scale desired wave, +full for the first half and -full for the second:
the error starts at e = d - 0 = +-full (both rails on `m`), and the weights run to the Wiener
solution w = conj(d) / (T * conj(x)), a natural gain of 4 * 32768 / (T * a), which saturates the
reported sat18(rnd(w, 15)) as soon as that gain exceeds full scale - with a small a it goes far past
it. Because d is real-positive over x real-positive, the converged weight has equal real and
imaginary parts of opposite signs, so ONE weight already carries +full and -full (and flipping d to
-full keeps that property with the signs swapped). SMALL_A / HALVES are searched from the shortest
transaction up and the first (a, k) whose outputs reach both rails on both streams is used, so every
configuration (lms and nlms, 1 to 16 taps, step .02 to 1) gets its own length; the assert reports a
configuration that cannot saturate.
"""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import lms_fixed as r
from sat_diag import SatTrace, write_expected, save_json

LIMIT=(1<<17)-1
MODEL_TAPS=np.array([.6+.1j,-.2+.1j,.15])
MODEL_LENGTH=512
OVERLOAD_AMPLITUDES=(1024,4096,16384)
OVERLOAD_HALVES=(64,256,1024,2048)
GROUPS=(('lms_pred_err',('pred.re','pred.im','error.re','error.im'),18),
        ('lms_update',('update.re','update.im'),34),
        ('lms_dump',('dump.re','dump.im'),18))


def saturation_formula(taps,transactions,samples):
    return {'lms_pred_err':[samples]*4, 'lms_update':[samples*taps]*2,
            'lms_dump':[taps*transactions]*2}


def read_saturation_expected(folder):
    result={}
    for name,stages,_ in GROUPS:
        lines=(folder/f'{name}_expected.txt').read_text().splitlines()
        assert int(lines[0])==len(stages) and len(lines)==len(stages)+1
        rows=[list(map(int,line.split())) for line in lines[1:]]
        assert all(len(row)==3 and min(row)>=0 and sum(row[1:])<=row[0] for row in rows)
        result[name]=(sum(row[0] for row in rows),sum(sum(row[1:]) for row in rows))
    return result


def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n');return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range."""
    rows=[]
    for v in values:
        re=int(round(float(np.real(v))*32768));im=int(round(float(np.imag(v))*32768))
        rows.append((max(-LIMIT-1,min(LIMIT,re)),max(-LIMIT-1,min(LIMIT,im))))
    return rows


def signal(length,rng):
    """Complex Gaussian /sqrt2."""
    return (rng.normal(size=length)+1j*rng.normal(size=length))/np.sqrt(2)


def true_taps(count,rng):
    """Random complex channel of `count` taps (used as the desired signal generator)."""
    return (rng.normal(size=count)+1j*rng.normal(size=count))/count


def plan(mode,taps,transactions,rng):
    """`transactions` (length, float taps) pairs. For taps == 3 the first transaction is the
    model case (512 samples, MODEL_TAPS); every transaction uses a random length in [1, 300]
    and a random 'true' channel of `taps` taps (MODEL_TAPS for the model case)."""
    if mode not in ('lms','nlms'):raise ValueError(f'unknown mode {mode}')
    cases=[]
    if taps==3:cases.append((MODEL_LENGTH,MODEL_TAPS))
    for _ in range(transactions-(1 if taps==3 else 0)):
        cases.append((int(rng.integers(1,301)),true_taps(taps,rng)))
    return cases


def rails(out,weights):
    """((peak, valley) of the sample outputs (pred and error fields), (peak, valley) of the reported
    weights)."""
    sample=[value for pred,error in out for value in (*pred,*error)]
    reported=[value for weight in weights for value in weight]
    return (max(sample),min(sample)),(max(reported),min(reported))


def overload_transaction(mode,taps,params):
    """(x, d, (peak, valley) of the sample outputs, (peak, valley) of the reported weights): the
    overload transaction of `mode`/`taps`/`params`, searched from the shortest candidate. x is the
    small real sample (a, 0) and d full scale, +full then -full, so the weights run to a gain of
    4 * 32768 / (T * a) and both rails appear on both streams."""
    for half in OVERLOAD_HALVES:
        for a in OVERLOAD_AMPLITUDES:
            x=[(a,0)]*(2*half)
            d=[(LIMIT,LIMIT)]*half+[(-LIMIT-1,-LIMIT-1)]*half
            out,weights=r.adapt(x,d,taps,mode,params)
            sample,reported=rails(out,weights)
            if sample[0]==LIMIT and sample[1]==-LIMIT-1 and reported[0]==LIMIT and reported[1]==-LIMIT-1:
                return x,d,sample,reported
    raise AssertionError(f'LMS: no overload transaction saturates {mode} taps={taps} {params}')


def vectors(folder,mode,step,eps,taps,transactions=2,seed=29,stress=False):
    """cfg.txt: one `nlms taps mu eps` row.
    in.txt: 'xre xim dre dim last' per input sample (last on the last sample of a transaction).
    out.txt: 'pre pim ere eim last' per sample of lms_fixed.adapt (last on the last sample of
    the transaction). w.txt: 're im last' per final weight, every transaction in order."""
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    if mode not in ('lms','nlms') or taps<1:raise ValueError('Invalid LMS vector request')
    mu,e=r.parameters(step,eps)
    if stress and (mode!='lms' or step!=1 or taps!=2):raise ValueError('Invalid LMS weight stress configuration')
    stats=SatTrace()
    cases=plan(mode,taps,transactions,rng)
    in_rows=[];out_rows=[];w_rows=[]
    for length,channel in cases:
        x=signal(length,rng);desired=np.convolve(x,channel)[:length]
        assert len(x)==len(desired)==length>=1
        xs=quantize(x);ds=quantize(desired)
        out,weights=r.adapt(xs,ds,taps,mode,(mu,e),stats=stats)
        in_rows.extend((xr,xi,dr,di,int(k==length-1)) for k,((xr,xi),(dr,di)) in enumerate(zip(xs,ds)))
        out_rows.extend((p[0],p[1],er[0],er[1],int(k==len(out)-1)) for k,(p,er) in enumerate(out))
        w_rows.extend((wr,wi,int(k==len(weights)-1)) for k,(wr,wi) in enumerate(weights))
        assert len(weights)==taps
    # the overload transaction: a small real x, a full scale desired wave, the weights run to both rails
    x,d,sample,reported=overload_transaction(mode,taps,(mu,e))
    out,weights=r.adapt(x,d,taps,mode,(mu,e),stats=stats)
    length=len(x)
    in_rows.extend((xr,xi,dr,di,int(k==length-1)) for k,((xr,xi),(dr,di)) in enumerate(zip(x,d)))
    out_rows.extend((p[0],p[1],er[0],er[1],int(k==len(out)-1)) for k,(p,er) in enumerate(out))
    w_rows.extend((wr,wi,int(k==len(weights)-1)) for k,(wr,wi) in enumerate(weights))
    if stress:
        for desired in (LIMIT,-LIMIT-1):
            xs=[(LIMIT,0),(0,0)];ds=[(desired,0),(0,0)]
            out,weights=r.adapt(xs,ds,taps,mode,(mu,e),stats=stats)
            in_rows.extend((*z,*target,int(k==1)) for k,(z,target) in enumerate(zip(xs,ds)))
            out_rows.extend((*p,*er,int(k==1)) for k,(p,er) in enumerate(out))
            w_rows.extend((*w,int(k==taps-1)) for k,w in enumerate(weights))
    (folder/'cfg.txt').write_text(f"{1 if mode=='nlms' else 0} {taps} {mu} {e}\n")
    inputs=save(folder/'in.txt',in_rows)
    outputs=save(folder/'out.txt',out_rows)
    weights_total=save(folder/'w.txt',w_rows)
    count=len(cases)+1+2*int(stress)
    formula=saturation_formula(taps,count,inputs)
    groups={}
    for name,stages,bits in GROUPS:
        assert [stats.evaluations.get(stage,0) for stage in stages]==formula[name]
        rows=write_expected(folder/f'{name}_expected.txt',stats,stages)
        groups[name]=dict(stages=stages,bits=bits,evaluations=sum(row[0] for row in rows),
                          events=sum(row[1]+row[2] for row in rows))
    metadata=save_json(folder/'saturation.json',stats,groups=groups,evaluation_formula=formula)
    return dict(transactions=count,taps=taps,mode=mode,inputs=inputs,outputs=outputs,
                weights=weights_total,overload=True,m_rails=list(sample),w_rails=list(reported),
                stress=stress,saturation=metadata)


if __name__=='__main__':print(vectors(ROOT/'build/rtl/lms/vectors','lms',.05,.01,3))
