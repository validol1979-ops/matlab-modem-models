"""OFDM RTL vectors: the bit-exact outputs of common/python/ofdm_fixed.py for
rtl/modems/ofdm_awgn/ofdm_tx.sv (tx_in.txt -> tx_out.txt) and ofdm_rx.sv
(rx_in.txt -> rx_out.txt). tx_in/tx_out are pure integer frames; rx_in is the float
research_core.run('ofdm_tx') wave of the same symbols plus noise, quantized to Q15 and
clipped to 18 bits, rx_out is ofdm_fixed.receive of exactly those samples.

Overload frame (appended after every random frame, deterministic, no rng): one extra frame
whose symbols (tx_in) and samples (rx_in) are a full 18 bit amplitude alternating wave, re =
+LIMIT / -LIMIT-1 and im = -re-1. ofdm_fixed.transmit prescales by 1/sqrt(n) and takes the
unhalved inverse (peak n*LIMIT*K/2^SHIFT_TX ~ LIMIT*sqrt(n)), ofdm_fixed.receive scales
FFT/n by sqrt(n), so both saturate in ofdm_fixed.sat18 in both directions; the module asserts
that the overload frame output really holds one +LIMIT and one -LIMIT value per stream.

Saturation evidence: one SatTrace instruments every actual transaction (random frames and the
overload frame) through ofdm_fixed.transmit/receive, counting ONLY the outer 18 bit clamps
(stages tx.re/tx.im, rx.re/rx.im; the embedded FFT is not counted). ofdm_tx_expected.txt and
ofdm_rx_expected.txt hold write_expected rows (evaluations positive negative per field) for the
sat_group_check observers of rtl/tb/ofdm_saturation_check.svh, saturation.json the
save_json summary. Evaluations are asserted per field: tx = tx_in count, rx = rx_out count.

EMBEDDED FFT EVIDENCE (fft_stats): two further SatTrace objects instrument ONLY the embedded
fft_fixed calls of the same actual scored frames (random frames plus overload): transmit
forwards fft_stats to fft_fixed.inverse (stages 'inverse.s<g>.<sum|diff>.<re|im>' plus
'inverse.conj.im'), receive to fft_fixed.forward ('forward.s<g>.<sum|diff>.<re|im>'). The
traces stay separate, so no stage name is shared and none of the outer tx.*/rx.* counters
move. ofdm_tx_fft_expected.txt and ofdm_rx_fft_expected.txt use the saturation_expected.txt
row layout of fft_cases (header LOG2N, then 8*LOG2N rows ordered direction 0 forward /
1 inverse, stage, 0 sum / 1 diff, 0 re / 1 im; 'evaluations positive negative' per row),
built with fft_cases.saturation_expected_rows from per-frame direction flags all-inverse
(TX) / all-forward (RX): active per-field evaluations = scored*N/2, inactive rows exactly
zero. The forward stages halve every butterfly and can never clip an 18 bit wave, so the RX
file has zero events by construction and is asserted so; the overload frame must clip the
unhalved inverse, so the TX file total is asserted positive. fft_saturation.json holds
save_json(model_only_evidence) over both traces plus an independent per-stage formula
(scored*N/2 per stage field, scored*N for inverse.conj.im) checked against the traces;
vectors() returns it as fft_saturation."""
from pathlib import Path
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import fft_fixed
import ofdm_fixed as o
from research_core import run
from sat_diag import SatTrace, write_expected, save_json
from fft_cases import saturation_expected_rows,read_saturation_expected,COMPONENTS,BRANCHES

LIMIT=(1<<17)-1


def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n');return len(rows)


def constellation(order):
    """Unit-power constellation of the ofdm_awgn model (BPSK is real +-1)."""
    if order==2:return np.array([-1,1],complex)
    side=int(np.sqrt(order));levels=np.arange(-(side-1),side,2);c=(levels[:,None]+1j*levels).ravel()
    return c/np.sqrt(np.mean(abs(c)**2))


def q15(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range."""
    rows=[]
    for v in values:
        re=int(round(float(np.real(v))*32768));im=int(round(float(np.imag(v))*32768))
        rows.append((max(-LIMIT-1,min(LIMIT,re)),max(-LIMIT-1,min(LIMIT,im))))
    return rows


def overload(count):
    """Deterministic overload samples: an alternating full scale wave, re = +LIMIT / -LIMIT-1
    and im = -re-1 (same magnitude, opposite sign). Every component stays inside the signed
    18 bit input range, so no documented input limit is violated."""
    rows=[]
    for k in range(count):
        re=LIMIT if k%2==0 else -LIMIT-1
        rows.append((re,-LIMIT-1 if k%2==0 else LIMIT))
    return rows


def fft_saturation_formula(log2n,scored):
    """Independent per-stage evaluation counts for the embedded FFT traces: every scored frame
    runs one transform, each stage has N/2 butterflies and so N/2 evaluated inputs per stage
    field, hence scored*N/2 per 'direction.s<g>.<sum|diff>.<re|im>'; the final inverse
    conjugation evaluates one value per output sample, scored*N. Forward has no conjugation."""
    n=1<<log2n;per=scored*n//2
    tx={f'inverse.s{g}.{b}.{c}':per for g in range(log2n) for b in BRANCHES for c in COMPONENTS}
    tx['inverse.conj.im']=scored*n
    rx={f'forward.s{g}.{b}.{c}':per for g in range(log2n) for b in BRANCHES for c in COMPONENTS}
    return dict(scored_frames=scored,n=n,evaluations_per_field=per,ofdm_tx_fft=tx,ofdm_rx_fft=rx)


def write_fft_expected(folder,name,log2n,stats,flags):
    """Write one FFT-layout expected file (header LOG2N, 8*LOG2N rows) built by
    fft_cases.saturation_expected_rows; verify the shape contract by reading it back."""
    rows=saturation_expected_rows(log2n,stats,flags)
    (folder/name).write_text(str(log2n)+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n')
    assert read_saturation_expected(folder/name)==(log2n,rows)
    return rows


def vectors(folder,log2n,cp,frames=8,seed=11):
    """tx_in.txt: 're im last' per input symbol (last on the N-th of each frame).
    tx_out.txt: 're im last' per output sample of ofdm_fixed.transmit (last on the
    N+CP-th). rx_in.txt: 're im last' per sample of the noisy float wave of the same
    symbols, quantized to Q15 and clipped to 18 bits (last on the N+CP-th).
    rx_out.txt: 're im last' of ofdm_fixed.receive of exactly rx_in (last on the N-th).
    The demodulated rx_out symbols must match the transmitted labels exactly (checked for the
    random frames only: the trailing overload frame is saturated by design, so its labels are
    deliberately not checked)."""
    n=1<<log2n;folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    tx_in=[];tx_out=[];rx_in=[];rx_out=[];errors=0;stats=SatTrace()
    tx_fft=SatTrace();rx_fft=SatTrace()
    for index in range(frames):
        order=(2,4,16,64)[index%4];const=constellation(order)
        labels=rng.integers(0,order,n);symbols=const[labels]
        syms=q15(symbols)
        tx_in.extend((re,im,int(k==n-1)) for k,(re,im) in enumerate(syms))
        tx_out.extend((re,im,int(k==n+cp-1)) for k,(re,im) in enumerate(o.transmit(syms,n,cp,stats=stats,fft_stats=tx_fft)))
        wave=run('ofdm_tx',[n,cp],symbols)
        noise=.003*(rng.normal(size=len(wave))+1j*rng.normal(size=len(wave)))/np.sqrt(2)
        samples=q15(wave+noise)
        assert len(samples)==n+cp
        rx_in.extend((re,im,int(k==n+cp-1)) for k,(re,im) in enumerate(samples))
        got=o.receive(samples,n,cp,stats=stats,fft_stats=rx_fft)
        rx_out.extend((re,im,int(k==n-1)) for k,(re,im) in enumerate(got))
        for j,(re,im) in enumerate(got):
            if int(np.argmin(abs((re+1j*im)/32768-const)))!=int(labels[j]):errors+=1
    assert errors==0,f'OFDM vectors: {errors} symbol errors'
    # Overload frame: drawn after all rng work, deterministic, so the earlier vectors stay
    # byte-identical. It drives ofdm_fixed.sat18 to +LIMIT and to -LIMIT-1 on both streams.
    tx_ov=o.transmit(overload(n),n,cp,stats=stats,fft_stats=tx_fft)
    rx_ov=o.receive(overload(n+cp),n,cp,stats=stats,fft_stats=rx_fft)
    for name,group in (('tx',tx_ov),('rx',rx_ov)):
        flat=[v for re,im in group for v in (re,im)]
        assert max(flat)==LIMIT and min(flat)==-LIMIT-1, \
            f'OFDM overload {name}: no output saturation (max {max(flat)}, min {min(flat)})'
    tx_in.extend((re,im,int(k==n-1)) for k,(re,im) in enumerate(overload(n)))
    tx_out.extend((re,im,int(k==n+cp-1)) for k,(re,im) in enumerate(tx_ov))
    rx_in.extend((re,im,int(k==n+cp-1)) for k,(re,im) in enumerate(overload(n+cp)))
    rx_out.extend((re,im,int(k==n-1)) for k,(re,im) in enumerate(rx_ov))
    inputs=save(folder/'tx_in.txt',tx_in)
    save(folder/'tx_out.txt',tx_out)
    save(folder/'rx_in.txt',rx_in)
    rx_outputs=save(folder/'rx_out.txt',rx_out)
    # One SatTrace for every actual transaction: per-field evaluations are exactly the outer
    # clamps the model ran (each core sample once before the prefix duplication, each received
    # symbol once after the rounding scale).
    assert [stats.evaluations.get(stage,0) for stage in ('tx.re','tx.im')]==[inputs]*2, \
        f'OFDM saturation tx: evaluations {stats.evaluations}, tx_in {inputs}'
    assert [stats.evaluations.get(stage,0) for stage in ('rx.re','rx.im')]==[rx_outputs]*2, \
        f'OFDM saturation rx: evaluations {stats.evaluations}, rx_out {rx_outputs}'
    tx_rows=write_expected(folder/'ofdm_tx_expected.txt',stats,('tx.re','tx.im'))
    rx_rows=write_expected(folder/'ofdm_rx_expected.txt',stats,('rx.re','rx.im'))
    groups={'ofdm_tx':dict(stages=('tx.re','tx.im'),bits=18,evaluations=sum(r[0] for r in tx_rows),
                           events=sum(r[1]+r[2] for r in tx_rows)),
            'ofdm_rx':dict(stages=('rx.re','rx.im'),bits=18,evaluations=sum(r[0] for r in rx_rows),
                           events=sum(r[1]+r[2] for r in rx_rows))}
    metadata=save_json(folder/'saturation.json',stats,groups=groups,
                       evaluation_formula={'ofdm_tx':[inputs]*2,'ofdm_rx':[rx_outputs]*2},
                       log2n=log2n,cp=cp)
    # Embedded FFT evidence: the two traces saw exactly the actual scored frames (random plus
    # overload), TX the unhalved inverse only, RX the halved forward only.
    scored=frames+1
    formula=fft_saturation_formula(log2n,scored)
    assert tx_fft.evaluations==formula['ofdm_tx_fft'],(tx_fft.evaluations,formula['ofdm_tx_fft'])
    assert rx_fft.evaluations==formula['ofdm_rx_fft'],(rx_fft.evaluations,formula['ofdm_rx_fft'])
    assert not any(k.startswith('forward') for k in tx_fft.counts|tx_fft.evaluations),tx_fft.evaluations
    assert not any(k.startswith('inverse') for k in rx_fft.counts|rx_fft.evaluations),rx_fft.evaluations
    tx_fft_rows=write_fft_expected(folder,'ofdm_tx_fft_expected.txt',log2n,tx_fft,[1]*scored)
    rx_fft_rows=write_fft_expected(folder,'ofdm_rx_fft_expected.txt',log2n,rx_fft,[0]*scored)
    assert all(row[0]==(0 if index<4*log2n else formula['evaluations_per_field'])
               for index,row in enumerate(tx_fft_rows)),tx_fft_rows
    assert all(row[0]==(formula['evaluations_per_field'] if index<4*log2n else 0)
               for index,row in enumerate(rx_fft_rows)),rx_fft_rows
    assert all(0<=row[1]+row[2]<=row[0] for row in tx_fft_rows+rx_fft_rows)
    # The halved forward cannot clip an 18 bit wave (every stage halves). The rows cover every
    # stage event, so the row totals must equal the trace totals (inverse.conj.im never clips).
    assert sum(row[1]+row[2] for row in rx_fft_rows)==0,rx_fft_rows
    tx_fft_events=sum(row[1]+row[2] for row in tx_fft_rows)
    assert tx_fft_events==tx_fft.total(),(tx_fft_events,tx_fft.total())
    # For n >= 16 the overload IDFT peak n*round(LIMIT*K,SHIFT) >= 524288 > the 20 bit rail
    # (K/2^SHIFT = 1/2, ~1/2.83, 1/4, ...), so the embedded inverse must clip; n = 4/8 peak
    # below the rail (262144 / ~370728) and only the outer sat18 saturates, as before.
    if n>=16:
        assert tx_fft_events>0,f'OFDM FFT tx: overload did not clip the inverse {tx_fft_rows}'
    combined=SatTrace()
    for prefix_,trace in (('tx.',tx_fft),('rx.',rx_fft)):
        for stage,c in trace.counts.items():combined.counts[prefix_+stage]=dict(c)
        for stage,e in trace.evaluations.items():combined.evaluations[prefix_+stage]=e
    fft_metadata=save_json(folder/'fft_saturation.json',combined,model='ofdm',log2n=log2n,cp=cp,
                           scored_frames=scored,in_width=18,width=fft_fixed.DATA_WIDTH,formula=formula,
                           expected_files=dict(ofdm_tx_fft_expected=[list(r) for r in tx_fft_rows],
                                               ofdm_rx_fft_expected=[list(r) for r in rx_fft_rows]))
    print(f"OFDM saturation (n={n}, cp={cp}): tx {groups['ofdm_tx']['evaluations']} evaluations / "
          f"{groups['ofdm_tx']['events']} events, rx {groups['ofdm_rx']['evaluations']} evaluations / "
          f"{groups['ofdm_rx']['events']} events")
    print(f"OFDM FFT saturation (n={n}, cp={cp}, scored={scored}): inverse {tx_fft.total()} events "
          f"on {formula['evaluations_per_field']} evaluations/field, forward {rx_fft.total()} events")
    return dict(frames=frames+1,inputs=inputs,outputs=len(tx_out),rx_outputs=rx_outputs,
                log2n=log2n,cp=cp,symbol_errors=errors,saturation=metadata,
                fft_saturation=fft_metadata)


if __name__=='__main__':print(vectors(ROOT/'build/rtl/ofdm/vectors',5,8))
