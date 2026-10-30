"""Polyphase analysis bank RTL vectors, scored against pfb_fixed.analyze.

Configuration: real Q17 taps followed by decimation D (1..M). A transaction
of L complex Q15 samples yields ceil(L/D)*M complex Q19 bins. The model
cases use firwin(33,.20) and a two-tone wave; others use seeded random taps
and Gaussian waves. Files have count headers and per-transaction TLAST.

Output full scale is unreachable. Before FFT/M, each polyphase component
is saturated to 22 bits, so its complex magnitude is at most sqrt(2)*2^21.
A halved butterfly can increase the complex magnitude by a factor at most
1+1/65536 (Q16 twiddle rounding) plus one (rounding the two components).
The integer recurrence in output_bound includes both effects; at LOG2M<=8
its global ceiling is 2966197, below the 24-bit rail 8388607. Per-case bounds
also use the actual sums of absolute taps in each phase. No transaction is
appended; all pre-existing vectors and RNG draws are preserved.

CLAMP STATISTICS (optional, sat_diag.SatTrace): every real clamp of pfb_fixed.analyze is counted
with its pre-clamp ROUNDED value, at the same place where rtl/common/pfb_analysis.sv clamps
(sat22 of the accumulator, before the rotation), and the total is replayed against the RTL by
rtl/tb/pfb_saturation_check.svh. The one observed field group is
  pfb_phase (2 fields, OUT22) phase.re and phase.im, the sat22 inputs of every phase.
The trace spans exactly the scored transactions (no hypothetical probes; the embedded FFT has its
own model-only counter below, never mixed into these files), so the model and the observer see the
same events. The group writes
pfb_phase_expected.txt with sat_diag.write_expected (header = field count, one 'evaluations
positive negative' row per field) and the vector folder writes saturation.json with
sat_diag.save_json. Independently per field the evaluation count is the bin total: every output
time rotates M clamped phases into the FFT, so each field is evaluated M times per output time,
i.e. once per output bin, bins = sum over transactions of M * ceil(L / D); vectors() checks this
formula against the counters and reports it.

WEIGHT-FIELD CLAMP STRESS (stress=True, only the LOG2M=2 (M=4), D=4, 16-tap configuration). The
random plan is replaced, deterministically and without touching the RNG, by two 64-sample
transactions of full 18 bit complex samples: all (+131071,-131072), then all (-131072,+131071),
over taps that are all 131071 (the largest positive Q17 word). Each phase sums up to four tap
products of magnitude ~2^34, so round(acc,13) is far past the 22 bit rails and both components of
the phase clamp see both polarities (checked before the vectors are written). Default and
pre-existing configurations, RNG draws and data are unchanged.

EMBEDDED FFT CLAMP STATISTICS (optional, second counter): vectors() creates ONE sat_diag.SatStats
and passes it to every pfb_fixed.analyze call as fft_stats, so it spans exactly the scored
transactions and counts only the embedded forward FFT's symmetric clamps (fft_fixed.forward at the
existing widths 22/24, stages 'forward.s<g>.<sum|diff>.<re|im>'). This model-only evidence never
reaches pfb_phase_expected.txt or saturation.json (the RTL observer keeps watching the phase clamp
only) and never touches the RNG, so all vectors stay byte-identical. The row file
pfb_fft_expected.txt uses the tools/fft_cases.py saturation_expected.txt layout: header LOG2M, then
8*LOG2M rows ordered direction (0 forward, 1 inverse), stage, branch (0 sum, 1 diff), component
(0 re, 1 im), built with fft_cases.saturation_expected_rows from all-forward flags. Every
transaction feeds ceil(L/D) FFT frames, so each active forward field has evaluations =
frames*M/2 (butterflies per stage over all frames, frames = sum ceil(L/D)); the inverse rows are
evaluations 0 with zero events. fft_saturation.json (sat_diag.save_json: model_only_evidence plus
the per-field formula) records the counts; the vector report returns fft_saturation.
"""
from pathlib import Path
import sys
import math
import numpy as np
from scipy import signal as scipy_signal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import pfb_fixed as p
import sat_diag
import fft_cases

LIMIT=(1<<17)-1
BIN=(1<<23)-1
CLIP=3.9
MODEL_TAPS=33
SAT_STAGES=('phase.re','phase.im')
SAT_EXPECTED='pfb_phase_expected.txt'
FFT_EXPECTED='pfb_fft_expected.txt'
FFT_JSON='fft_saturation.json'
# the only clamp-stress configuration: M = 4, D = 4, TMAX = 16, 16 taps (parent CASE 2,1,4,4,16)
STRESS_CONFIG=(2,4,16)
STRESS_TAP=131071          # every tap word: the largest positive Q17 tap (2^17 - 1)
STRESS_FULL=(131071,-131072)   # full-scaled 18 bit complex sample (rails +full / -full)
STRESS_LENGTH=64           # samples per stress transaction


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
    """Unit-power complex Gaussian clipped to +-3.9."""
    v=(rng.normal(size=length)+1j*rng.normal(size=length))/np.sqrt(2)
    return np.clip(v.real,-CLIP,CLIP)+1j*np.clip(v.imag,-CLIP,CLIP)


def model_signal():
    """The model.json case: exp(2j pi t/4) + .4 exp(-2j pi t/4), t = 0..255."""
    t=np.arange(256)
    return np.exp(2j*np.pi*t/4)+.4*np.exp(-2j*np.pi*t/4)


def output_bound(log2m,taps):
    """Ceiling on every output component, including quantized twiddles and rounding."""
    m=1<<log2m
    peak=131072*max(sum(abs(taps[j]) for j in range(len(taps)) if j%m==r) for r in range(m))
    component=min((peak+(1<<12))>>13, 1<<21)
    square=2*component*component
    bound=math.isqrt(square)
    bound+=int(bound*bound<square)
    for _ in range(log2m):
        bound+=(bound+65535)//65536+1
    return bound


def lengths(m,d,transactions,rng):
    """`transactions` random L in [1, 6*M] plus one long one; the model.json signal
    (length 256) leads the (log2m=2, d=4/3, T=33) cases."""
    short=[int(rng.integers(1,6*m+1)) for _ in range(transactions)]
    long_=6*m+int(rng.integers(1,6*m))+1
    return short+[long_]


def stress_transactions():
    """The two deterministic clamp-stress transactions as Q15 words: 64 samples of
    (+131071,-131072), then 64 samples of the opposite signs (-131072,+131071). Both 18 bit
    rails appear on both components, so with all taps positive every phase rounds past both
    rails of the 22 bit clamp on both polarities."""
    return [[STRESS_FULL]*STRESS_LENGTH,
            [(STRESS_FULL[1],STRESS_FULL[0])]*STRESS_LENGTH]


def saturation_formula(m,d,lengths_):
    """Independent per-field evaluation counts: M clamped phases per output time, one output
    time per D samples, so each field is evaluated exactly `bins` = M * ceil(L/D) per
    transaction (once per output bin)."""
    bins=sum(m*((l+d-1)//d) for l in lengths_)
    return {stage:bins for stage in SAT_STAGES}


def fft_saturation_formula(log2m,m,frames):
    """Embedded forward FFT evaluation counts: M/2 butterflies per stage per frame, so each of
    the 4*LOG2M active 'forward.s<g>.<sum|diff>.<re|im>' fields is evaluated exactly
    frames*M/2 times (frames = sum ceil(L/D)); inverse fields are never evaluated."""
    return {f'forward.s{g}.{b}.{c}':frames*(m//2) for g in range(log2m)
            for b in fft_cases.BRANCHES for c in fft_cases.COMPONENTS}


def vectors(folder,log2m,d,taps_count,transactions=3,seed=29,stress=False,full_scale=False):
    """cfg.txt: `count` (the tap count) then one `tap` row, then a final `d` row.
    in.txt: 're im last' per input sample (last on the last sample of a transaction).
    out.txt: 're im last' per bin of pfb_fixed.analyze (last on the very last bin of the
    transaction). pfb_phase_expected.txt and saturation.json: the phase.clamp counts of the
    scored vectors. stress=True replaces the random plan by the deterministic two-transaction
    clamp stress (only STRESS_CONFIG, LOG2M=2, D=4, 16 taps). pfb_fft_expected.txt and
    fft_saturation.json additionally record the embedded FFT clamps of the same transactions
    (model-only evidence, one SatStats passed to every analyze call as fft_stats)."""
    m=1<<log2m
    if not 2<=log2m<=8 or not 1<=d<=m:raise ValueError('PFB needs M = 2^b (4..256), 1 <= D <= M')
    if stress and (log2m,d,taps_count)!=STRESS_CONFIG:
        raise ValueError(f'PFB stress is only defined for LOG2M={STRESS_CONFIG[0]} (M=4), '
                         f'D={STRESS_CONFIG[1]}, {STRESS_CONFIG[2]} taps')
    model=(log2m==2 and d in (3,4) and taps_count==MODEL_TAPS)
    folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    stats=sat_diag.SatTrace()
    fft_stats=sat_diag.SatStats()   # one counter for exactly the scored FFT frames (model only)
    if full_scale:
        if stress:raise ValueError('Choose one stress plan')
        taps=[-131072]*taps_count
        waves=[[(-131072,-131072)]*(taps_count+m),
               [(131071,131071)]*(taps_count+m),[(-131072,131071)]]
        values=list(map(len,waves))
    elif stress:
        taps=[STRESS_TAP]*taps_count
        values=[STRESS_LENGTH]*2
        waves=stress_transactions()
    else:
        h=scipy_signal.firwin(MODEL_TAPS,.20) if model else rng.uniform(-.6,.6,taps_count)/np.sqrt(taps_count)
        taps=p.quantize_taps(h)
        values=lengths(m,d,transactions,rng)
        if model:values=[256]+values[1:]
    in_rows=[];out_rows=[]
    for index,length in enumerate(values):
        if stress or full_scale:
            samples=waves[index];assert len(samples)==length>=1
        else:
            wave=model_signal() if (model and index==0) else signal(length,rng)
            assert len(wave)==length>=1
            samples=quantize(wave)
        in_rows.extend((re,im,int(k==length-1)) for k,(re,im) in enumerate(samples))
        bins=p.analyze(samples,taps,m,d,stats=stats,fft_stats=fft_stats)
        assert len(bins)==m*((length+d-1)//d)
        assert all(abs(re)<=BIN and abs(im)<=BIN for re,im in bins)
        out_rows.extend((re,im,int(k==len(bins)-1)) for k,(re,im) in enumerate(bins))
    cfg=folder/'cfg.txt'
    cfg.write_text(str(len(taps))+'\n'+'\n'.join(str(t) for t in taps)+'\n'+str(d)+'\n')
    inputs=save(folder/'in.txt',in_rows)
    bins=save(folder/'out.txt',out_rows)
    # The legal complex input box cannot reach the 24-bit output rails.
    bound=output_bound(log2m,taps)
    assert bound<=BIN, f'PFB output bound {bound} exceeds the 24 bit rail {BIN} (model/RTL changed?)'
    assert all(abs(v)<=bound for re,im,_ in out_rows for v in (re,im)), \
        f'PFB bin exceeds the per-case output bound {bound}'
    # clamp statistics: one trace over the scored transactions, replayed by the RTL observer
    prediction=saturation_formula(m,d,values)
    assert set(stats.evaluations)==set(SAT_STAGES),stats.evaluations   # no embedded FFT counts
    assert {s:stats.evaluations[s] for s in SAT_STAGES}==prediction,(stats.evaluations,prediction)
    assert prediction['phase.re']==bins==prediction['phase.im'],(prediction,bins)
    rows=sat_diag.write_expected(folder/SAT_EXPECTED,stats,SAT_STAGES)
    assert [row[0] for row in rows]==[prediction[s] for s in SAT_STAGES],rows
    assert all(0<=row[1]+row[2]<=row[0] for row in rows),rows
    sat_diag.save_json(folder/'saturation.json',stats,model='pfb',log2m=log2m,m=m,d=d,
                       taps=len(taps),transactions=len(values),inputs=inputs,bins=bins,
                       stress=bool(stress),formula=prediction)
    if stress:
        assert all(stats.counts.get(s,{}).get(t,0) for s in SAT_STAGES for t in ('pos','neg')), \
            ('PFB stress did not clip both phases on both polarities',stats.counts)
    # embedded FFT clamp statistics: model-only evidence over exactly the scored frames.
    frames=sum((l+d-1)//d for l in values)
    assert frames*m==bins,(frames,m,bins)
    fft_formula=fft_saturation_formula(log2m,m,frames)
    assert set(fft_stats.counts)<=set(fft_formula),sorted(set(fft_stats.counts)-set(fft_formula))
    fft_rows=fft_cases.saturation_expected_rows(log2m,fft_stats,[0]*frames)  # every frame forward
    active=4*log2m
    assert all(row[0]==frames*(m//2) for row in fft_rows[:active]),fft_rows
    assert all(row==(0,0,0) for row in fft_rows[active:]),fft_rows
    (folder/FFT_EXPECTED).write_text(str(log2m)+'\n'+'\n'.join(' '.join(map(str,row)) for row in fft_rows)+'\n')
    sat_diag.save_json(folder/FFT_JSON,fft_stats,model='pfb-fft',log2m=log2m,m=m,d=d,
                       taps=len(taps),transactions=len(values),frames=frames,bins=bins,
                       stress=bool(stress),formula=fft_formula)
    return dict(transactions=len(values),log2m=log2m,m=m,d=d,taps=len(taps),
                inputs=inputs,bins=bins,output_bound=bound,overload=False,stress=bool(stress),
                saturation=stats.to_dict(),saturation_formula=prediction,
                saturation_expected={SAT_EXPECTED.removesuffix('_expected.txt'):[list(r) for r in rows]},
                fft_saturation=fft_stats.to_dict(),fft_saturation_formula=fft_formula,
                fft_saturation_expected={'log2m':log2m,'rows':[list(r) for r in fft_rows]})


if __name__=='__main__':print(vectors(ROOT/'build/rtl/pfb/vectors',2,4,MODEL_TAPS))
