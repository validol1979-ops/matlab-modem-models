"""Runtime FIR RTL vectors: the bit-exact outputs of common/python/fir_fixed.py for
rtl/common/fir_runtime.sv (cfg.txt + in.txt -> out.txt).

One configuration is the T complex taps (Q17), one per cfg transfer (cfg_last on the last);
one transaction is one signal of L samples (s_last on its last sample) that answers with
L + T - 1 outputs (m_last on the very last output). The taps follow the taps_kind
('harger' [.25,.5,.25], 'impulse' [.2,.5,.3], 'wsinc' wsinc_taps(41,.12), 'complex' 9 random
complex normal/6, 'single' [.7], 'long' 100 random real uniform(-.3,.3)/sqrt(100)); the
signals are complex Gaussian /3 (and the two-tone exp(.3j t)+.5 exp(2.4j t) for 'wsinc'),
quantized to Q15 integers in the signed 18 bit range. For 'harger'/'impulse' the first
transaction is the impulse [1,0,0] and the last has L = 1. out.txt holds the 18 bit Q15
outputs of fir_fixed.filter (sat18 of round(acc, 17)).

One deterministic transaction is appended after all random draws when full scale is
reachable. Each output component is a linear function of the input components. Selecting
their legal box corners (+131071 or -131072) attains the exact positive and negative
component bounds, including half-up rounding. Two reversed tap-length corner sequences
exercise both extremes in one transaction. Both actual rails are asserted.
The single .7 tap has bounds [-91750, 91750], so no extra transaction is added for it.
Unity-gain harger/impulse taps reach the rails exactly; their legal input box cannot
exceed them. They cover full-scale values, while output_clipping=False distinguishes
this from exercising a clipping branch. Complex taps use component bounds rather than
sum of complex magnitudes, since the input limits apply separately to real and imaginary.
"""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import fir_fixed as r
import sat_diag

LIMIT=(1<<17)-1
TAP_FRAC=17
TWOTONE_LENGTH=64


def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n');return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range."""
    rows=[]
    for v in values:
        re=int(round(float(np.real(v))*32768));im=int(round(float(np.imag(v))*32768))
        rows.append((max(-LIMIT-1,min(LIMIT,re)),max(-LIMIT-1,min(LIMIT,im))))
    return rows


def build_taps(taps_kind,rng):
    """Float taps of one configuration."""
    if taps_kind=='harger':return [.25,.5,.25]
    if taps_kind=='impulse':return [.2,.5,.3]
    if taps_kind=='wsinc':return r.wsinc_taps(41,.12)
    if taps_kind=='complex':return [(rng.normal()/6)+1j*(rng.normal()/6) for _ in range(9)]
    if taps_kind=='single':return [.7]
    if taps_kind=='long':return list(rng.uniform(-.3,.3,100)/np.sqrt(100))
    raise ValueError(f'unknown taps_kind {taps_kind}')


def signal(length,rng):
    """Complex Gaussian /3."""
    return (rng.normal(size=length)+1j*rng.normal(size=length))/3


def two_tone(length):
    """exp(.3j t) + .5 exp(2.4j t), t = 0..length-1."""
    t=np.arange(length)
    return np.exp(.3j*t)+.5*np.exp(2.4j*t)


def plan(taps_kind,transactions,count,rng):
    """`transactions` (length, mode) pairs; mode in {'impulse','twotone','gauss'}. For
    'harger'/'impulse' the first is the impulse [1,0,0] and the last has L = 1; the rest are
    random lengths in [1, 3*T+20]. 'wsinc' carries one two-tone transaction."""
    modes=[]
    if taps_kind in ('harger','impulse'):
        modes.append((3,'impulse'))
        modes.extend((int(rng.integers(1,3*count+21)),'gauss') for _ in range(transactions-2))
        modes.append((1,'gauss'))
    else:
        modes.extend((int(rng.integers(1,3*count+21)),'gauss') for _ in range(transactions))
        if taps_kind=='wsinc':modes[len(modes)//2]=(TWOTONE_LENGTH,'twotone')
    return modes


def overload_wave(taps):
    """Two box-corner sequences and exact unsaturated (low, high) component bounds."""
    coefficients=([(re,-im) for re,im in taps],[(im,re) for re,im in taps])
    def corner(fields,positive):
        samples=[tuple(0 if c==0 else LIMIT if (c>0)==positive else -LIMIT-1
                       for c in pair) for pair in fields]
        total=sum(c*v for pair,row in zip(fields,samples) for c,v in zip(pair,row))
        return ((total+(1<<(TAP_FRAC-1)))>>TAP_FRAC,list(reversed(samples)))
    high,head=max((corner(fields,True) for fields in coefficients),key=lambda item:item[0])
    low,tail=min((corner(fields,False) for fields in coefficients),key=lambda item:item[0])
    return head+tail,(low,high)


def vectors(folder,taps_kind,transactions=4,seed=29):
    """cfg.txt: `count` (the tap count) then one `re im` row per tap.
    in.txt: 're im last' per input sample (last on the last sample of a transaction).
    out.txt: 're im last' per output of fir_fixed.filter (last on the very last output of
    the transaction), plus the overload transaction when the tap gain can reach full scale."""
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    taps=r.quantize_taps(build_taps(taps_kind,rng));count=len(taps)
    modes=plan(taps_kind,transactions,count,rng)
    stats=sat_diag.SatStats()
    in_rows=[];out_rows=[]
    for length,mode in modes:
        wave=np.array([1,0,0],dtype=complex) if mode=='impulse' else two_tone(length) if mode=='twotone' else signal(length,rng)
        assert len(wave)==length>=1
        samples=quantize(wave)
        in_rows.extend((re,im,int(k==length-1)) for k,(re,im) in enumerate(samples))
        outs=r.filter(samples,taps,stats=stats)
        assert len(outs)==length+count-1
        assert all(abs(re)<=LIMIT+1 and abs(im)<=LIMIT+1 for re,im in outs)
        out_rows.extend((re,im,int(k==len(outs)-1)) for k,(re,im) in enumerate(outs))
    cfg=folder/'cfg.txt'
    cfg.write_text(str(len(taps))+'\n'+'\n'.join(f'{re} {im}' for re,im in taps)+'\n')
    wave,(low,high)=overload_wave(taps)
    outs=r.filter(wave,taps,stats=stats)
    assert len(outs)==len(wave)+count-1
    flat=[v for re,im in outs for v in (re,im)]
    gain=sum(abs(complex(re,im)) for re,im in taps)/(1<<TAP_FRAC)
    if not (max(flat)>=LIMIT and min(flat)<=-LIMIT-1):
        assert low>-LIMIT-1 and high<LIMIT, \
            f'FIR corner misses reachable rails: output {min(flat)}, {max(flat)}, bounds {low}, {high}'
        overloaded=False
    else:
        overloaded=True
        in_rows.extend((re,im,int(k==len(wave)-1)) for k,(re,im) in enumerate(wave))
        out_rows.extend((re,im,int(k==len(outs)-1)) for k,(re,im) in enumerate(outs))
    inputs=save(folder/'in.txt',in_rows)
    outputs=save(folder/'out.txt',out_rows)
    sat_diag.save_json(folder/'saturation.json',stats,model='fir',taps_kind=taps_kind,
                       output_bounds=[low,high])
    counts=[stats.counts.get(stage, {}).get(sign, 0)
            for stage in ('output.re','output.im') for sign in ('pos','neg')]
    (folder/'saturation_expected.txt').write_text(' '.join(map(str,counts))+'\n')
    return dict(transactions=len(modes)+(1 if overloaded else 0),taps=count,taps_kind=taps_kind,
                gain=round(gain,4),overload=overloaded,output_bounds=[low,high],
                output_clipping=low<-LIMIT-1 or high>LIMIT,saturation=stats.to_dict(),
                inputs=inputs,outputs=outputs)


if __name__=='__main__':print(vectors(ROOT/'build/rtl/fir/vectors','harger'))
