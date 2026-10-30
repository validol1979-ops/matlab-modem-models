"""STFT/ISTFT RTL vectors: the bit-exact outputs of common/python/stft_fixed.py for
rtl/common/stft_analysis.sv (an_in.txt -> an_out.txt) and rtl/common/stft_synthesis.sv
(sy_in.txt -> sy_out.txt).

One transaction is one signal of L samples (L >= N); the analyser answers with F =
1 + (L - N) // HOP frames of N bins, the synthesiser turns those F spectra back into
(F - 1) * HOP + N samples. Signals are complex Gaussian (unit power, clipped to +-3.9)
or a full-scale tone, quantized to Q15 integers in the signed 18 bit range; an_out /
sy_in are the 24 bit Q19 spectra of stft_fixed.analyze, sy_out the 18 bit Q15 samples of
stft_fixed.synthesize of exactly those spectra.

ANALYSIS OVERLOAD IS UNREACHABLE BY CONSTRUCTION, so no analysis overload transaction is
added. Each windowed component is at most 2^21 in magnitude. The complex magnitude is
therefore at most sqrt(2)*2^21. Each halved butterfly multiplies this bound by at most
1+sqrt(2)/2^17 (the Q16 twiddle rounding error) and adds sqrt(2)/2 for component rounding.
After at most eight stages the bound stays below 2966100, whereas the 24 bit full scale
is 8388607. This includes complex inputs, the asymmetric negative input rail, and rounding.

SYNTHESIS overload transaction (appended after all random transactions, deterministic, no
rng): one extra sy_in/sy_out transaction whose spectra are stft_fixed.analyze of a full 18
bit alternating wave, multiplied by OVERLOAD_GAIN = 4 and clamped to the documented +-
(2^22 - 1) input clamp of stft_fixed.synthesize (inside the 24 bit input range, no input
limit violated). The overlap-add then runs past 18 bits and sat18 clamps both ways; the
module asserts that the overload output really holds one +LIMIT and one -LIMIT value."""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import stft_fixed as s
from sat_diag import SatTrace,write_expected,save_json

LIMIT=(1<<17)-1
SPECTRUM=(1<<23)-1
CLIP=3.9
OVERLOAD_GAIN=4


def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n');return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range."""
    rows=[]
    for v in values:
        re=int(round(float(np.real(v))*32768));im=int(round(float(np.imag(v))*32768))
        rows.append((max(-LIMIT-1,min(LIMIT,re)),max(-LIMIT-1,min(LIMIT,im))))
    return rows


def signal(length,n,rng,tone):
    """Unit-power complex Gaussian clipped to +-3.9, or a full-scale complex tone."""
    if tone:
        return CLIP*np.exp(2j*np.pi*3*np.arange(length)/n)
    v=(rng.normal(size=length)+1j*rng.normal(size=length))/np.sqrt(2)
    return np.clip(v.real,-CLIP,CLIP)+1j*np.clip(v.imag,-CLIP,CLIP)


def lengths(n,hop,transactions,rng):
    """Different L in [N, N + 7*HOP + HOP-1]: L == N first, one L with a tail that does
    not fill a frame (impossible when HOP == 1), the rest random."""
    high=n+8*hop-1
    values=[int(rng.integers(n,high+1)) for _ in range(transactions)]
    values[0]=n
    if hop>1 and not any((value-n)%hop for value in values):
        values[-1]=n+hop*int(rng.integers(0,8))+int(rng.integers(1,hop))
    if hop==1 and len(set(values))==1:
        values[-1]=high
    return values


def overload(n,hop,stats=None):
    """Deterministic synthesis overload transaction as (input rows, output rows): the spectra of
    a full scale alternating wave, times OVERLOAD_GAIN and clamped to the documented +-
    (2^22 - 1) clamp of stft_fixed.synthesize, so that its sat18 output saturates both ways.
    The last flag sits on the last bin / sample of the transaction (error stays 0)."""
    wave=[(LIMIT if k%2==0 else -LIMIT-1,LIMIT if (k//2)%2==0 else -LIMIT-1) for k in range(n+3*hop)]
    spectra=s.analyze(wave,n,hop)
    clamp=lambda v:max(-s.SPECTRUM_LIMIT,min(s.SPECTRUM_LIMIT,v))
    boosted=[(clamp(OVERLOAD_GAIN*re),clamp(OVERLOAD_GAIN*im)) for re,im in spectra]
    assert all(abs(v)<=SPECTRUM for re,im in boosted for v in (re,im))
    out=s.synthesize(boosted,n,hop,stats=stats)
    flat=[v for re,im in out for v in (re,im)]
    assert max(flat)==LIMIT and min(flat)==-LIMIT-1, \
        f'STFT synthesis overload: no output saturation (max {max(flat)}, min {min(flat)})'
    rows_in=[(re,im,int(k==len(boosted)-1)) for k,(re,im) in enumerate(boosted)]
    rows_out=[(re,im,int(k==len(out)-1)) for k,(re,im) in enumerate(out)]
    return rows_in,rows_out


def vectors(folder,log2n,log2hop,transactions=4,seed=29,stress=False):
    """an_in.txt: 're im last' per input sample (last on the last sample of a signal).
    an_out.txt: 're im last' per spectrum bin of stft_fixed.analyze (last on the very
    last bin of the transaction). sy_in.txt: the same spectra (re im last).
    sy_out.txt: 're im last' per sample of stft_fixed.synthesize of each transaction's
    spectra (last on the last sample). sy_in/sy_out carry one extra overload transaction that
    an_in/an_out do not have (the two streams are independent in rtl/tb/stft_tb.sv)."""
    n=1<<log2n;hop=1<<log2hop;s.check(n,hop)
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    stats=SatTrace()
    an_in=[];an_out=[];sy_out=[]
    for index,length in enumerate(lengths(n,hop,transactions,rng)):
        tone=index%3==1
        samples=quantize(signal(length,n,rng,tone))
        assert len(samples)==length>=n
        an_in.extend((re,im,int(k==length-1)) for k,(re,im) in enumerate(samples))
        spectra=s.analyze(samples,n,hop)
        frames=len(spectra)//n
        assert len(spectra)==frames*n and frames==1+(length-n)//hop
        assert all(abs(re)<=SPECTRUM and abs(im)<=SPECTRUM for re,im in spectra)
        an_out.extend((re,im,int(k==len(spectra)-1)) for k,(re,im) in enumerate(spectra))
        wave=s.synthesize(spectra,n,hop,stats=stats)
        assert len(wave)==(frames-1)*hop+n
        sy_out.extend((re,im,int(k==len(wave)-1)) for k,(re,im) in enumerate(wave))
    inputs=save(folder/'an_in.txt',an_in)
    spectra=save(folder/'an_out.txt',an_out)
    ov_in,ov_out=overload(n,hop,stats=stats)
    sy_rows=list(an_out)+ov_in
    sy_out.extend(ov_out)
    if stress:
        c=s.SPECTRUM_LIMIT
        for values in [[(c,-c),(c+1,-c-1),(-c,c),(-c-1,c+1)]*(n//4),[(SPECTRUM,-SPECTRUM-1)]*n]:
            wave=s.synthesize(values,n,hop,stats=stats)
            sy_rows.extend((*value,int(k==len(values)-1)) for k,value in enumerate(values))
            sy_out.extend((*value,int(k==len(wave)-1)) for k,value in enumerate(wave))
    save(folder/'sy_in.txt',sy_rows)
    samples=save(folder/'sy_out.txt',sy_out)
    expected={'stft_spectrum':len(sy_rows),'stft_output':samples}
    for name,node in [('stft_spectrum','spectrum'),('stft_output','output')]:
        stages=[f'stft.{node}.re',f'stft.{node}.im']
        assert all(stats.evaluations[stage]==expected[name] for stage in stages)
        write_expected(folder/f'{name}_expected.txt',stats,stages)
    metadata=save_json(folder/'saturation.json',stats,evaluation_formula=expected)
    return dict(transactions=transactions+1+2*int(stress),log2n=log2n,log2hop=log2hop,n=n,hop=hop,
                analysis_transactions=transactions, synthesis_transactions=transactions+1+2*int(stress),
                inputs=inputs,spectra=spectra,samples=samples,stress=stress,saturation=metadata)


if __name__=='__main__':print(vectors(ROOT/'build/rtl/stft/vectors',6,4))
