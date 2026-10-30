"""Runtime RLS RTL vectors: the bit-exact outputs of common/python/rls_fixed.py for
rtl/common/rls_filter.sv (cfg.txt + in.txt -> out.txt + w.txt).

One configuration is the single cfg transfer (tap count N, P0 = round(2^28/eps),
LAM = round(lam*2^28), INVL = round(2^30/lam) of rls_fixed.parameters). One transaction is one
signal of L samples (x and the desired d of the same sample, s_last on its last sample); every
sample answers with one (pred, e) output (m_last on the last sample) and the transaction then
reports the N final weights on w_* (w_last on the last weight). Each transaction restarts
P = P0*I, w = 0 and the history at zero.

The first transaction is the model case (complex Gaussian /sqrt2, 512 samples, desired =
convolve(x, [.6+.1j,-.2+.1j,.15])[:512]) when taps == 3, the rest are random lengths in
[1, 300] with a random complex channel of `taps` taps (normal complex /(2 sqrt N)) as the 'true'
system and `noise` of extra complex Gaussian /sqrt2 added to the desired signal. x and d are
Q15 clipped to the signed 18 bit range. out.txt holds `pre pim ere eim last`, w.txt holds the N
weights of every transaction in order as `re im last` (both from rls_fixed.adapt).

OUTPUT OVERLOAD TRANSACTION (sat18 of pred, e and of the reported weights, the `m` and `w`
covergroup bins). Every transaction restarts P = P0 I, w = 0 and the history, so the last transaction
owns the whole recursion and draws no random numbers. It is a small real signal x = (a, 0) with a full
scale desired wave, +full for the first half and -full for the second: e starts at d - 0 = +-full (both
rails on `m`), and RLS solves the least squares problem in one sample - g = P h / (lam + h^H P h) with
P = P0 I gives g = h / |x|^2 and w = g conj(e), a natural gain of |e| / |x| - with a small a that is
far past the full scale of the reported sat18(rnd(w, 15)). d real-positive over x real-positive puts
the converged weight on (+gain, -gain), so one weight already carries +full and -full, and flipping d
swaps the signs. HALVES / SMALL_A are searched from the shortest transaction up and candidates whose
recursion would leave the RLS domain (rls_fixed raises 'denominator lost positivity') are skipped, so
every configuration (1 to 8 taps, lam .95 to 1, eps .001 to .1) gets a legal saturating vector; the
assert reports a configuration that cannot saturate.

CLAMP STATISTICS (optional, sat_diag.SatTrace): every real clamp of rls_fixed.adapt is counted
with its pre-clamp ROUNDED value, at the same place where rtl/common/rls_filter.sv clamps, and the
total is replayed against the RTL by rtl/tb/rls_saturation_check.svh. The nine observed field groups
are
  rls_pred_err (4 fields, OUT18) pred.re/im and error.re/im,
  rls_u (2, OUT48) u.re/im, rls_q (1, OUT50) q, rls_gain (2, OUT40) gain.re/im,
  rls_update (2, OUT34) update.re/im, rls_pt (2, OUT46) pt.re/im,
  rls_p_real (1, OUT44) P.re, rls_p_imag (1, OUT44) P.im, rls_dump (2, OUT18) dump.re/im.
Each group writes <group>_group_expected.txt with sat_diag.write_expected (header = field count,
one 'evaluations positive negative' row per field) and the whole vector set writes saturation.json
with sat_diag.save_json. The RTL mirror counts each mirror assignment of P once (upper triangle),
keeps P.im off the diagonal, counts pt on both components including the diagonal and ignores the
lanes the DUT computes and discards (taps above cfg_taps, pt columns below the row).
For a transaction of S samples and T taps the evaluation counts follow independently per field:
pred = errors = S, u = gain = update = S*T, q = S, pt = P.re = S*T*(T+1)/2, P.im = S*T*(T-1)/2 and
dump = T per transaction. vectors() checks these formulas against the counters and reports both.

WEIGHT AND P CLAMP STRESS. The two last configurations are not random: with eps = 1/16384 the start
value P0 = round(2^28/eps) = 2^42 is legal for the 44 bit field and the RLS recursion stays inside
its domain (the denominator keeps the LAM term, so it never loses positivity), while the fixed point
is driven into the two clamps the random Gaussian traffic never reaches.
'weight34' (lambda 1, 1 tap) drives eight separate transactions of eight real LSB samples x = (1, 0)
with a full scale desired signal, four transactions at +full and four at -full, so the gain |e|/|x|
of a one tap filter over an almost empty regressor multiplies the weight far past the 34 bit field
and both rails of the WEIGHT clamp appear (update.re on one polarity, update.im with the opposite
sign, because the weight update is a conjugate product). 'p44' (lambda 0.5, 2 taps) uses four step
impulse signals x = (1, 0), (0, 0), (0, 0), (0, 0) with a full scale desired signal in two separate
transactions; INVL = round(2^30/0.5) = 2^31 still fits the 32 bit unsigned cfg field, so every P
entry doubles per sample and the 44 bit P.re clamp fires on every step of both transactions. The P
imaginary part and the 48/50/40/46 bit clamps stay at zero events for these two configurations,
which is written down honestly instead of forcing data with an unphysical covariance.

The overload search of the random configurations never touches the counters: its probe calls run
without stats, only the scored transaction is instrumented, so the expected counts describe exactly
the vectors that are played on the DUT.
"""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import rls_fixed as r
import sat_diag

LIMIT=(1<<17)-1
MODEL_TAPS=np.array([.6+.1j,-.2+.1j,.15])
MODEL_LENGTH=512
OVERLOAD_HALVES=(1,2,4,8,32,128)
OVERLOAD_AMPLITUDES=(1024,4096,16384,65536)
# name, model stages (in field order), field count, clamp bit width of the RTL observer
GROUPS=(('rls_pred_err',('pred.re','pred.im','error.re','error.im'),4,18),
        ('rls_u',('u.re','u.im'),2,48),
        ('rls_q',('q',),1,50),
        ('rls_gain',('gain.re','gain.im'),2,40),
        ('rls_update',('update.re','update.im'),2,34),
        ('rls_pt',('pt.re','pt.im'),2,46),
        ('rls_p_real',('P.re',),1,44),
        ('rls_p_imag',('P.im',),1,44),
        ('rls_dump',('dump.re','dump.im'),2,18))
STRESS_WEIGHT_TRANSACTIONS=8
STRESS_WEIGHT_LENGTH=8
STRESS_P_TRANSACTIONS=2
STRESS_P_LENGTH=4
STRESS_TAPS={'weight34':1,'p44':2}


def expected_file(name):
    """The expected counts file of one group (read by sat_group_check as EXPECTED_FILE)."""
    return f'{name}_group_expected.txt'


def saturation_formula(taps,transactions,samples):
    """Independent evaluation counts per field: S samples, T taps, `transactions` transactions."""
    S,T=samples,taps
    upper=S*T*(T+1)//2;strict=S*T*(T-1)//2
    return {'rls_pred_err':[S,S,S,S],'rls_u':[S*T]*2,'rls_q':[S],'rls_gain':[S*T]*2,
            'rls_update':[S*T]*2,'rls_pt':[upper]*2,'rls_p_real':[upper],'rls_p_imag':[strict],
            'rls_dump':[T*transactions]*2}


def read_group_expected(folder,name,fields):
    """Parse and shape-check one group's expected counts; return (evaluations, events)."""
    lines=[line for line in Path(folder,expected_file(name)).read_text().splitlines() if line.strip()]
    assert len(lines)==fields+1 and int(lines[0])==fields,(name,lines)
    rows=[tuple(map(int,line.split())) for line in lines[1:]]
    assert all(len(row)==3 and row[0]>=0 and 0<=row[1]+row[2]<=row[0] for row in rows),(name,rows)
    return sum(row[0] for row in rows),sum(row[1]+row[2] for row in rows)


def read_saturation_expected(folder):
    """Read back every group file: name -> (fields, evaluations, events)."""
    return {name:(fields,)+read_group_expected(folder,name,fields) for name,_,fields,_ in GROUPS}


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
    return (rng.normal(size=count)+1j*rng.normal(size=count))/(2*np.sqrt(count))


def plan(taps,transactions,rng):
    """`transactions` (length, float taps) pairs. For taps == 3 the first transaction is the
    model case (512 samples, MODEL_TAPS); every other transaction uses a random length in
    [1, 300] and a random 'true' channel of `taps` taps (MODEL_TAPS for the model case)."""
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


def overload_transaction(taps,params):
    """(x, d, (peak, valley) of the sample outputs, (peak, valley) of the reported weights): the
    overload transaction of `taps`/`params`, searched from the shortest candidate. x is the small real
    sample (a, 0) and d full scale, +full then -full, so the weight gain |e| / |x| runs past both
    rails. Candidates whose recursion leaves the RLS domain are skipped."""
    for half in OVERLOAD_HALVES:
        for a in OVERLOAD_AMPLITUDES:
            x=[(a,0)]*(2*half)
            d=[(LIMIT,LIMIT)]*half+[(-LIMIT-1,-LIMIT-1)]*half
            try: out,weights=r.adapt(x,d,taps,params)
            except ValueError:continue
            sample,reported=rails(out,weights)
            if sample[0]==LIMIT and sample[1]==-LIMIT-1 and reported[0]==LIMIT and reported[1]==-LIMIT-1:
                return x,d,sample,reported
    raise AssertionError(f'RLS: no overload transaction saturates taps={taps} {params}')


def manual_transactions(stress,taps):
    """[([x], [d])] of the deterministic clamp stress, one entry per transaction. 'weight34' is
    eight separate transactions of eight real LSB samples with a full scale desired signal (four at
    +full, four at -full); 'p44' is a four step unit impulse with a full scale desired signal, one
    transaction per polarity."""
    if stress not in STRESS_TAPS or STRESS_TAPS[stress]!=taps:
        raise ValueError(f'RLS stress {stress} needs taps={STRESS_TAPS.get(stress)}, got {taps}')
    if stress=='weight34':
        return [([(1,0)]*STRESS_WEIGHT_LENGTH,
                 [(LIMIT,LIMIT) if k%2==0 else (-LIMIT-1,-LIMIT-1)]*STRESS_WEIGHT_LENGTH)
                for k in range(STRESS_WEIGHT_TRANSACTIONS)]
    assert STRESS_P_TRANSACTIONS==2
    impulse=[(1,0)]+[(0,0)]*(STRESS_P_LENGTH-1)
    return [(list(impulse),[(LIMIT,LIMIT) if k%2==0 else (-LIMIT-1,-LIMIT-1)]*STRESS_P_LENGTH)
            for k in range(STRESS_P_TRANSACTIONS)]


def stress_reached(stress,stats):
    """True when the stress really drove the clamp it is there for (checked before the vectors are
    written, so a stress that stopped saturating fails the vector generation)."""
    want={'weight34':(('update.re','update.im'),('pos','neg')),'p44':(('P.re',),('pos',))}[stress]
    return all(stats.counts.get(stage,{}).get(sign,0) for stage in want[0] for sign in want[1])


def vectors(folder,lam,eps,taps,transactions=2,noise=0,seed=29,stress=None):
    """cfg.txt: one `taps p0 lam invl` row.
    in.txt: 'xre xim dre dim last' per input sample (last on the last sample of a transaction).
    out.txt: 'pre pim ere eim last' per sample of rls_fixed.adapt (last on the last sample of
    the transaction). w.txt: 're im last' per final weight, every transaction in order.
    <group>_group_expected.txt and saturation.json: the clamp counts of the scored vectors."""
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    if taps<1 or not (0<lam<=1) or eps<=0 or noise<0:raise ValueError('Invalid RLS vector request')
    if stress not in (None,'weight34','p44'):raise ValueError(f'Unknown RLS stress {stress}')
    p0,lam_q,invl=r.parameters(lam,eps)
    stats=sat_diag.SatTrace()
    blocks=[];overload=True
    if stress is None:
        for length,channel in plan(taps,transactions,rng):
            x=signal(length,rng);desired=np.convolve(x,channel)[:length]
            if noise:desired=desired+noise*signal(length,rng)
            assert len(x)==len(desired)==length>=1
            blocks.append((quantize(x),quantize(desired)))
        # the overload transaction: a small real x, a full scale desired wave, the gain runs to both
        # rails. The search below runs uninstrumented: its probes are not part of the vectors.
        x,d,sample,reported=overload_transaction(taps,(p0,lam_q,invl))
        blocks.append((x,d))
    else:
        blocks=manual_transactions(stress,taps)
        overload=False
        assert invl<(1<<32),f'INVL {invl} does not fit the 32 bit unsigned cfg field'
    in_rows=[];out_rows=[];w_rows=[];all_out=[];all_weights=[]
    for index,(xs,ds) in enumerate(blocks):
        out,weights=r.adapt(xs,ds,taps,(p0,lam_q,invl),stats=stats)
        length=len(xs)
        in_rows.extend((xr,xi,dr,di,int(k==length-1)) for k,((xr,xi),(dr,di)) in enumerate(zip(xs,ds)))
        out_rows.extend((p[0],p[1],er[0],er[1],int(k==len(out)-1)) for k,(p,er) in enumerate(out))
        w_rows.extend((wr,wi,int(k==len(weights)-1)) for k,(wr,wi) in enumerate(weights))
        assert len(weights)==taps
        all_out.extend(out);all_weights.extend(weights)
        if overload and index==len(blocks)-1:sample,reported=rails(out,weights)
    if stress is not None:
        assert stress_reached(stress,stats),(stress,stats.counts)
        sample,reported=rails(all_out,all_weights)      # rails over the whole manual set
    (folder/'cfg.txt').write_text(f"{taps} {p0} {lam_q} {invl}\n")
    inputs=save(folder/'in.txt',in_rows)
    outputs=save(folder/'out.txt',out_rows)
    weights_total=save(folder/'w.txt',w_rows)
    # clamp statistics: the counters of the scored vectors, replayed by the RTL observer
    samples=len(in_rows)
    assert outputs==samples and weights_total==taps*len(blocks)
    prediction=saturation_formula(taps,len(blocks),samples)
    predicted={stage:count for name,stages,_,_ in GROUPS for stage,count in zip(stages,prediction[name])}
    assert set(stats.evaluations)<=set(predicted),set(stats.evaluations)-set(predicted)
    expected={};evidence={}
    for name,stages,fields,bits in GROUPS:
        assert fields==len(stages)
        rows=sat_diag.write_expected(folder/expected_file(name),stats,stages)
        assert [row[0] for row in rows]==prediction[name],(name,rows,prediction[name])
        expected[name]=[list(row) for row in rows]
        evidence[name]=dict(stages=list(stages),fields=fields,out_width=bits,
                            evaluations=sum(row[0] for row in rows),
                            positive=sum(row[1] for row in rows),negative=sum(row[2] for row in rows),
                            expected_file=expected_file(name))
        assert 0<=sum(row[1]+row[2] for row in rows)<=sum(row[0] for row in rows)
    sat_diag.save_json(folder/'saturation.json',stats,model='rls',taps=taps,transactions=len(blocks),
                       samples=samples,stress=stress,formula=prediction)
    return dict(transactions=len(blocks),taps=taps,inputs=inputs,outputs=outputs,samples=samples,
                weights=weights_total,overload=overload,stress=stress,
                m_rails=list(sample),w_rails=list(reported),
                saturation=stats.to_dict(),saturation_expected=expected,
                saturation_formula=prediction,saturation_evidence=evidence)


if __name__=='__main__':print(vectors(ROOT/'build/rtl/rls/vectors',.995,.01,3))
