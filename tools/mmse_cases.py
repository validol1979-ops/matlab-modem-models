"""Runtime 2x2 MMSE / zero-forcing RTL vectors: the bit-exact outputs of
common/python/mmse_fixed.py for rtl/common/mmse2.sv (cfg.txt + in.txt -> out.txt).

One configuration is the four Q15 entries of H in row-major order (h00, h01, h10, h11), one per cfg
transfer, cfg_last on h11 together with LAMBDA = round(lambda*2^30) (Q30). One transaction is a run
of observation pairs (o0, o1) with s_last on the last o1; the DUT answers with y0, y1 per pair and
m_last on the very last output of the transaction.

'zf'/'mmse' use the model channel H = [[1+.3j, .4-.2j], [-.2+.1j, .8+.2j]] and lambda 0 / .015: the
first transaction is 128 BPSK symbol pairs (2*randint-1) times H^T (plus .02 noise for 'mmse').
'random' is a random H = (normal + j normal)/2 with lambda .1, 'strong' a random H with entries up
to |h| = 3 and lambda 1. Every other transaction is a random length in [1, 40] of complex Gaussian/3
pairs; whatever mmse_fixed.solve returns (including saturation) is scored as-is.
'tinyidentity' uses H=I/32768 and lambda=0: det=1 and Z-39=-16 require an exact
left shift when computing the weights. Its first transaction carries BPSK symbols
through this tiny channel (Q15 observation components +/-1), followed by the same
random and overload transaction machinery used by the other configurations.
'gram_peak' and 'scale_peak' (docs/RTL_MMSE2_WIDTHS.md) are exact signed18 corner channels with
LAMBDA = 2^34 - 1: the first reaches det = 1.5625*2^72 and |M| = 1.25*2^53, the second
|M*R| = 1.176*2^76 (the reachable witnesses of the minimal det, M and scale widths).

cfg.txt: 4 `re im` rows (h00 h01 h10 h11) then one line with the integer LAMBDA.
in.txt: `re im last` per observation sample (last on the last o1 of a transaction).
out.txt: `re im last` per solved sample (last on the last output of a transaction).

OUTPUT OVERLOAD TRANSACTION (sat18 of the solved symbols, the `mmse m` covergroup bins). The solve is
linear in the observation pair of fixed coefficients - y_i = sat18(rnd(W_i0 o_0 + W_i1 o_1, 24)) with
W = mmse_fixed.weights(H, lambda) in Q24 - so the largest value any output component takes over the
observation box is attained at a CORNER, and its exact bound is
(sum_j |W_i0| + |W_i1| components) * 2^17 + 2^23 >> 24 (every component of o_0 and o_1 at the widest
value of the field, whose magnitude is 2^17, the
corner picking the sign of the matching coefficient). The last transaction is the best of the 16
corners of (o_0, o_1) together with the worst one, so both rails appear whenever the bound allows it;
the bound is reported and, if it stays under full scale, that is written down instead of faking data.

'zf' (bound 237074), 'mmse' (231470) and 'random' (227680) reach +131071 and -131072 with that corner
pair. 'strong' CANNOT: its channel is drawn with |h| up to 3 and lambda 1, so W = (H^H H + LAMBDA I)^-1
H^H is a weak inverse and the exact row bound above is 66219 - less than half of full scale, which no
observation whatsoever can exceed, and the best corner reaches it exactly. A strong channel is precisely the case where the solver must divide the observation down,
so no full scale output exists for that configuration.
"""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import mmse_fixed as r
import sat_diag

LIMIT=(1<<17)-1
MODEL_H=np.array([[1+.3j,.4-.2j],[-.2+.1j,.8+.2j]])
MODEL_LENGTH=128
LO,HI=-(1<<17),(1<<17)-1
PEAK_H={'gram_peak':((LO,LO),(LO,HI),(LO,HI),(LO,LO)),'scale_peak':((LO,LO),(LO,HI),(HI,HI),(HI,HI))}
PEAK_LAMBDA=((1<<34)-1)/(1<<30)
CASES=('zf','mmse','random','strong','tinyidentity','gram_peak','scale_peak')
SCALE=1<<30


def save(path,rows):
    rows=list(rows);path.write_text('\n'.join(' '.join(map(str,row)) for row in rows)+'\n');return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range."""
    rows=[]
    for v in np.ravel(values):
        re=int(round(float(np.real(v))*32768));im=int(round(float(np.imag(v))*32768))
        rows.append((max(-LIMIT-1,min(LIMIT,re)),max(-LIMIT-1,min(LIMIT,im))))
    return rows


def pairs(count,rng):
    """`count` complex Gaussian/3 observation pairs of shape (count, 2)."""
    return (rng.normal(size=(count,2))+1j*rng.normal(size=(count,2)))/3


def channel(case,rng):
    """Float H (2x2) and lambda of the vector case."""
    if case in ('zf','mmse'):return MODEL_H,(0. if case=='zf' else .015)
    if case=='random':return (rng.normal(size=(2,2))+1j*rng.normal(size=(2,2)))/2,.1
    if case=='strong':return 3*(rng.uniform(-1,1,(2,2))+1j*rng.uniform(-1,1,(2,2))),1.
    if case=='tinyidentity':return np.eye(2)/(1<<15),0.
    if case in PEAK_H:return np.array([complex(*v) for v in PEAK_H[case]]).reshape(2,2)/32768,PEAK_LAMBDA
    raise ValueError(f'unknown MMSE case {case}')


def observations(case,H,lam,rng,length):
    """Complex observations of `length` pairs; the first transaction of 'zf'/'mmse' is BPSK."""
    if case in ('zf','mmse','tinyidentity') and length==MODEL_LENGTH:
        symbols=(2*rng.integers(0,2,(length,2))-1).astype(complex);obs=symbols@H.T
        if lam:obs=obs+.02*(rng.normal(size=obs.shape)+1j*rng.normal(size=obs.shape))/np.sqrt(2)
        return obs
    return pairs(length,rng)


def overload_transaction(Hm,lam):
    """([o_0, o_1 of the best corner, o_0, o_1 of the worst corner], (peak, valley) reached, exact
    upper bound of |y| over the observation box). y is linear in the four components of the pair, so
    the extremes sit at the 16 corners of the box."""
    W=r.weights(Hm,lam)
    bound=max(((sum(abs(W[i][j][0])+abs(W[i][j][1]) for j in range(2))*(LIMIT+1)+(1<<23))>>24)
              for i in range(2))
    corners=[[(LIMIT if (bits>>index)&1 else -LIMIT-1,LIMIT if (bits>>(index+2))&1 else -LIMIT-1)
              for index in range(2)] for bits in range(16)]
    scored=[]
    for corner in corners:
        flat=[value for y in r.solve(corner,Hm,lam) for value in y]
        scored.append((max(flat),min(flat),corner))
    samples=[(re,im) for pair in (max(scored,key=lambda item:item[0])[2],
                                  min(scored,key=lambda item:item[1])[2]) for (re,im) in pair]
    flat=[value for y in r.solve(samples,Hm,lam) for value in y]
    return samples,(max(flat),min(flat)),bound


def vectors(folder,case,transactions=3,seed=41):
    """cfg.txt: 4 `re im` rows of H (row-major) then the integer LAMBDA.
    in.txt: 're im last' per observation sample (last on the last o1 of a transaction).
    out.txt: 're im last' per solved sample of mmse_fixed.solve (last on the last output)."""
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    if case not in CASES or transactions<1:raise ValueError('Invalid MMSE vector request')
    H,lam=channel(case,rng)
    Hq=quantize(H);Hm=[[Hq[0],Hq[1]],[Hq[2],Hq[3]]]
    lam_int=int(round(lam*SCALE));lam_q=lam_int/SCALE        # bit-exact with the sampled LAMBDA
    lengths=[MODEL_LENGTH]+[int(rng.integers(1,41)) for _ in range(transactions-1)]
    samples=[]
    for length in lengths:samples.extend(quantize(observations(case,H,lam,rng,length)))
    # the overload transaction: the best and the worst corner of the observation box
    overload,rails,bound=overload_transaction(Hm,lam_q)
    samples.extend(overload);lengths.append(2)
    assert len(samples)%2==0 and len(samples)>=2
    stats=sat_diag.SatTrace()
    solved=r.solve(samples,Hm,lam_q,stats=stats)
    assert len(solved)==len(samples)
    flat=[value for y in solved[-4:] for value in y]
    assert max(flat)<=bound and min(flat)>=-bound
    assert (max(flat)>=LIMIT and min(flat)<=-LIMIT) or bound<LIMIT
    bounds=[];start=0
    for length in lengths:bounds.append(start+2*length-1);start+=2*length   # last o1 of every transaction
    in_rows=[(re,im,int(k in bounds)) for k,(re,im) in enumerate(samples)]
    out_rows=[(y[0],y[1],int(k in bounds)) for k,y in enumerate(solved)]
    (folder/'cfg.txt').write_text('\n'.join(f'{re} {im}' for re,im in Hq)+f'\n{lam_int}\n')
    inputs=save(folder/'in.txt',in_rows)
    outputs=save(folder/'out.txt',out_rows)
    sat_diag.save_json(folder/'saturation.json',stats,model='mmse')
    expected=sat_diag.write_expected(folder/'mmse_expected.txt',stats,
              ('output.y0.re','output.y0.im','output.y1.re','output.y1.im'))
    return dict(case=case,transactions=len(lengths),pairs=sum(lengths),lambda_=lam,
                lambda_int=lam_int,inputs=inputs,outputs=outputs,
                overload=max(flat)>=LIMIT and min(flat)<=-LIMIT,rails=list(rails),bound=bound,
                saturation=stats.to_dict(),saturation_expected=expected)


if __name__=='__main__':
    for name in ('zf','mmse','random','strong','tinyidentity'):
        print(name,vectors(ROOT/'build/rtl/mmse/vectors'/name,name))
