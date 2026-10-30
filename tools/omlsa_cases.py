"""Integer OM-LSA RTL vectors: the bit-exact outputs of common/python/omlsa_fixed.py for
rtl/common/omlsa.sv (cfg.txt + in.txt -> out.txt).

One configuration transfer carries `nnoise alpha_q` (alpha_q = round(alpha 2^16), 17 bit);
one transaction is one signal of L >= n + 1 samples (s_last on its last sample) that holds at
least `nnoise` frames, 1 + (L + n) // hop >= nnoise (the DUT reflect-pads by n on both sides),
and answers with exactly L outputs (m_last on the very last one). The first transaction is the
model case of tests/test_omlsa_fixed.py (rng default_rng(1), a .125 cycles/sample tone from
sample 160 of 640 plus .32 Gaussian noise); the others are noisy tones of random length
L in [n + 1 + hop*nnoise, 700]. Waves are real (im = 0) or complex, quantized to Q15 integers
in the signed 18 bit range. cfg.txt holds one `nnoise alpha_q` line, in.txt 're im last' per
input sample, out.txt 're im last' per sample of omlsa_fixed.enhance (last on the last output
of the transaction).

One deterministic full-scale transaction is appended after all random draws.
Its alternating prefix establishes the initial noise spectrum; a square wave
with eight samples per half-period then changes the spectrum. Per-bin gains
stay below one, but changing the spectrum can cause time-domain overshoot in
the ISTFT. Both actual 18-bit output rails are asserted on this transaction.
"""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import omlsa_fixed as o
from sat_diag import RangeTrace,write_expected,save_json

LIMIT=(1<<17)-1
MODEL_LENGTH=640
MODEL_CLEAN_START=160
MODEL_NOISE=.32
MAX_LENGTH=700
TONE_NOISE=.3
TONE_LEVEL=.8


def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n');return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range."""
    rows=[]
    for v in values:
        re=int(round(float(np.real(v))*32768));im=int(round(float(np.imag(v))*32768))
        rows.append((max(-LIMIT-1,min(LIMIT,re)),max(-LIMIT-1,min(LIMIT,im))))
    return rows


def model_wave():
    """The model case: sin(2 pi .125 t) from sample 160 of 640 plus .32 Gaussian noise."""
    rng=np.random.default_rng(1)
    t=np.arange(MODEL_LENGTH);clean=np.zeros(MODEL_LENGTH)
    clean[MODEL_CLEAN_START:]=np.sin(2*np.pi*.125*t[MODEL_CLEAN_START:])
    return clean+MODEL_NOISE*rng.normal(size=MODEL_LENGTH)


def tone_wave(length,complex_input,rng):
    """Noisy tone: .8 exp(2 pi f t) (or cos when real) plus .3 Gaussian noise, f random."""
    t=np.arange(length);f=float(rng.uniform(.03,.3))
    if complex_input:
        signal=TONE_LEVEL*np.exp(2j*np.pi*f*t)
        noise=TONE_NOISE*(rng.normal(size=length)+1j*rng.normal(size=length))
    else:
        signal=TONE_LEVEL*np.cos(2*np.pi*f*t)
        noise=TONE_NOISE*rng.normal(size=length)
    return signal+noise


def frames(length,n,hop):
    """Frame count of omlsa_fixed.enhance for a signal of `length` samples."""
    return 1+(length+n)//hop


def overload_wave(n,hop,nnoise,complex_input):
    """Legal input that changes spectral content after the noise-estimation prefix."""
    prefix=max(n+1,(nnoise-1)*hop+1)
    length=max(320,n+1+hop*nnoise)
    assert prefix<length<=MAX_LENGTH
    wave=[]
    for k in range(prefix):
        re=LIMIT if k%2==0 else -LIMIT-1
        im=(LIMIT if (k//2)%2==0 else -LIMIT-1) if complex_input else 0
        wave.append((re,im))
    for k in range(length-prefix):
        re=LIMIT if (k//8)%2==0 else -LIMIT-1
        im=(-LIMIT-1 if (k//8)%2==0 else LIMIT) if complex_input else 0
        wave.append((re,im))
    return wave


def lengths(n,hop,nnoise,transactions,rng):
    """`transactions` lengths in [n + 1 + hop*nnoise, 700] (so that the frame count reaches
    nnoise); the first one is the fixed model length."""
    low=min(n+1+hop*nnoise,MAX_LENGTH)
    values=[MODEL_LENGTH]
    values.extend(int(rng.integers(low,MAX_LENGTH+1)) for _ in range(transactions-1))
    for length in values:
        assert length>=n+1 and frames(length,n,hop)>=nnoise
    return values


def vectors(folder,n,hop,nnoise,alpha,transactions=2,complex_input=False,seed=31,stress=False):
    """cfg.txt: one `nnoise alpha_q` line. in.txt: 're im last' per input sample (last on the
    last sample of a transaction). out.txt: 're im last' per sample of omlsa_fixed.enhance
    (last on the very last output of the transaction)."""
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    alpha_q=int(round(alpha*65536))
    assert 1<=nnoise<=16 and 1<=alpha_q<=(1<<17)
    in_rows=[];out_rows=[]
    stats=RangeTrace();gain_bins=0;istft_samples=0
    for index,length in enumerate(lengths(n,hop,nnoise,transactions,rng)):
        wave=model_wave() if index==0 else tone_wave(length,complex_input,rng)
        samples=quantize(wave)
        assert len(samples)==length>=n+1
        y=o.enhance(samples,n,hop,nnoise,alpha,stats=stats)
        gain_bins+=frames(length,n,hop)*n;istft_samples+=(frames(length,n,hop)-1)*hop+n
        assert len(y)==length and all(abs(re)<=LIMIT+1 and abs(im)<=LIMIT+1 for re,im in y)
        in_rows.extend((re,im,int(k==length-1)) for k,(re,im) in enumerate(samples))
        out_rows.extend((re,im,int(k==length-1)) for k,(re,im) in enumerate(y))
    samples=overload_wave(n,hop,nnoise,complex_input)
    y=o.enhance(samples,n,hop,nnoise,alpha,stats=stats)
    gain_bins+=frames(len(samples),n,hop)*n;istft_samples+=(frames(len(samples),n,hop)-1)*hop+n
    assert len(y)==len(samples) and frames(len(samples),n,hop)>=nnoise
    flat=[v for pair in y for v in pair]
    assert max(flat)==LIMIT and min(flat)==-LIMIT-1, \
        f'OM-LSA overload misses the output rails: {min(flat)}, {max(flat)}'
    in_rows.extend((re,im,int(k==len(samples)-1)) for k,(re,im) in enumerate(samples))
    out_rows.extend((re,im,int(k==len(y)-1)) for k,(re,im) in enumerate(y))
    if stress:
        if nnoise!=1:raise ValueError('Quiet-prefix OM-LSA stress requires one noise frame')
        samples=[(0,0)]*(3*n)+[(LIMIT,-LIMIT-1)]*(4*n)+[(-LIMIT-1,LIMIT)]*(4*n)
        y=o.enhance(samples,n,hop,nnoise,alpha,stats=stats)
        gain_bins+=frames(len(samples),n,hop)*n;istft_samples+=(frames(len(samples),n,hop)-1)*hop+n
        in_rows.extend((*value,int(k==len(samples)-1)) for k,value in enumerate(samples))
        out_rows.extend((*value,int(k==len(y)-1)) for k,value in enumerate(y))
        assert stats.counts.get('omlsa.gamma',{}).get('pos',0)>0
    (folder/'cfg.txt').write_text(f'{nnoise} {alpha_q}\n')
    inputs=save(folder/'in.txt',in_rows)
    outputs=save(folder/'out.txt',out_rows)
    count=transactions+1+int(stress);formula={}
    for node in ('noise','gamma','excess','xi','v','g1','t','exp_index','prev'):
        stage='omlsa.'+node;expected=n*count if node=='noise' else gain_bins
        assert stats.evaluations[stage]==expected
        write_expected(folder/f'omlsa_{node}_expected.txt',stats,[stage]);formula[stage]=expected
    for node,expected in [('spectrum',gain_bins),('output',istft_samples)]:
        stages=[f'omlsa_istft.{node}.re',f'omlsa_istft.{node}.im']
        assert all(stats.evaluations[stage]==expected for stage in stages)
        write_expected(folder/f'omlsa_istft_{node}_expected.txt',stats,stages)
        formula.update({stage:expected for stage in stages})
    metadata=save_json(folder/'saturation.json',stats,evaluation_formula=formula)
    return dict(transactions=count,n=n,hop=hop,nnoise=nnoise,alpha=alpha,
                overload=True,rails=[max(flat),min(flat)],
                alpha_q=alpha_q,complex_input=complex_input,inputs=inputs,outputs=outputs,stress=stress,saturation=metadata)


if __name__=='__main__':
    print(vectors(ROOT/'build/rtl/omlsa/vectors',32,8,12,.92))
    print(vectors(ROOT/'build/rtl/omlsa/vectors/n64',64,16,6,.9,transactions=2,seed=32))
    print(vectors(ROOT/'build/rtl/omlsa/vectors/c32',32,8,4,.98,transactions=2,complex_input=True,seed=33))
    print(vectors(ROOT/'build/rtl/omlsa/vectors/n16',16,4,10,.8,transactions=2,seed=34))
