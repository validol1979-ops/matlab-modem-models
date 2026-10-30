"""Notch + Kalman RTL vectors: the bit-exact outputs of common/python/oset_fixed.py for
rtl/common/notch_iir.sv and rtl/common/kalman_scalar.sv (one folder holds both streams).

One configuration is ONE transfer (all coefficients at once, accepted while cfg_ready):
notch_cfg.txt `b1 a1 a2` (Q16), kalman_cfg.txt `q r p0` (Q24). One transaction is one signal
of L samples (s_last on its last sample) and answers with L outputs (m_last on the very last);
every transaction restarts the filter state (and the Kalman covariance from P0).

Notch signals: the model case exp(2j pi .07 t) + 2 exp(2j pi .23 t), t = 0..511, as the first
transaction (f0 = .23, r = .94), then random complex Gaussian /4 clipped to +-1.9 of random
length 1..300 (a length-1 and a length-2 transaction are included). Kalman signals:
1 + .5*normal (real) of length 512 first, then random lengths 1..300 (real and complex).
Both in/out files hold Q15 ints `re im last` (last on the last sample/output of a transaction).

Overload transactions (appended after each plan, deterministic, no rng draw):
- notch: one transaction of NOTCH_OVERLOAD samples at +LIMIT (re = im = 2^17 - 1) followed by
  NOTCH_OVERLOAD samples at -LIMIT-1, i.e. a full scale square wave inside the signed 18 bit
  input range. DC gain is (2-2c)/(1-2rc+r^2), with quantized coefficients in the model.
  Square-wave edges excite the stable filter's transient response, including the f0=0
  DC-rejection case. All configured r are below one; f0=.5/r=.9 has poles at -.9.
  The model output holds both +LIMIT and -LIMIT-1 samples, asserted below.
- kalman: one transaction of KALMAN_OVERLOAD samples at +LIMIT and KALMAN_OVERLOAD at -LIMIT-1.
  The tracker converges to (x << 8) with the steady state gain K (K = 5732 .. 35410 in these
  cases), so 400 samples per half is enough to put out = sat18(rnd(V, 8)) on +LIMIT and on
  -LIMIT-1, asserted.
For the Kalman configuration (q, R, p0) = (0, .25, 0) OUTPUT OVERLOAD IS UNREACHABLE BY
CONSTRUCTION: P stays P0 + i*q = 0, so K = divide(0, R) = 0 for every step, V never moves from
0 and the output is 0 for any input; that configuration gets no overload transaction (the
module reports kalman_overload=False).
"""
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import oset_fixed as r
import sat_diag

LIMIT = (1 << 17) - 1
# Separately labelled STRESS notch configuration: a raw registered-coefficient tuple
# (b1, a1, a2) in Q16 with pole a1 = -1.5 (|pole| > 1, unstable by design, accepted through
# the raw configuration-port contract). It is NOT a designed research_core profile: the
# sign-alternating divergence drives the 25 bit state clamp on BOTH signs and saturates the
# output both ways; the model consumes the same raw tuple.
STRESS_NOTCH_RAW = (-131072, -98304, 0)
NOTCH_STATE_STAGES = ['notch.state.re', 'notch.state.im']
NOTCH_OUTPUT_STAGES = ['notch.output.re', 'notch.output.im']
KALMAN_STAGES = ['kalman.output.re', 'kalman.output.im']
MODEL_LENGTH = 512
MAX_RANDOM = 300
NOTCH_OVERLOAD = 200
KALMAN_OVERLOAD = 400


def overload_wave(half):
    """Full scale square wave: `half` samples at +LIMIT on both axes, `half` at -LIMIT-1."""
    return [(LIMIT, LIMIT)] * half + [(-LIMIT - 1, -LIMIT - 1)] * half


def save(path, rows):
    rows = list(rows)
    path.write_text(str(len(rows)) + '\n' + '\n'.join(' '.join(map(str, row)) for row in rows) + '\n')
    return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range."""
    rows = []
    for v in values:
        re = int(round(float(np.real(v)) * 32768))
        im = int(round(float(np.imag(v)) * 32768))
        rows.append((max(-LIMIT - 1, min(LIMIT, re)), max(-LIMIT - 1, min(LIMIT, im))))
    return rows


def notch_model(length):
    """exp(2j pi .07 t) + 2 exp(2j pi .23 t), t = 0..length-1."""
    t = np.arange(length)
    return np.exp(2j * np.pi * .07 * t) + 2 * np.exp(2j * np.pi * .23 * t)


def gauss_complex(length, rng):
    """Complex Gaussian /4 clipped to +-1.9."""
    v = np.clip((rng.normal(size=length) + 1j * rng.normal(size=length)) / 4, -1.9, 1.9)
    return v


def gauss_real(length, rng):
    """1 + .5*normal (real)."""
    return 1 + .5 * rng.normal(size=length)


def notch_plan(transactions, rng):
    """(length, mode) pairs: the model case first, then a length-1 and a length-2
    transaction and random complex Gaussian transactions of length 1..300."""
    modes = [(MODEL_LENGTH, 'model')]
    for i in range(transactions - 1):
        if i == 0:
            modes.append((1, 'gauss'))
        elif i == 1:
            modes.append((2, 'gauss'))
        else:
            modes.append((int(rng.integers(1, MAX_RANDOM + 1)), 'gauss'))
    return modes


def kalman_plan(transactions, rng):
    """(length, mode) pairs: the real model case first, then random lengths 1..300
    alternating real and complex."""
    modes = [(MODEL_LENGTH, 'model')]
    for i in range(transactions - 1):
        mode = 'real' if i % 2 == 0 else 'complex'
        modes.append((int(rng.integers(1, MAX_RANDOM + 1)), mode))
    return modes


def build_notch(folder, notch, transactions, rng, trace=None, raw=None):
    coefficients = tuple(raw) if raw is not None else r.notch_coefficients(*notch)
    assert all(-LIMIT - 1 <= c <= LIMIT for c in coefficients), 'notch coefficient outside 18 bit'
    (folder / 'notch_cfg.txt').write_text(' '.join(map(str, coefficients)) + '\n')
    in_rows = []
    out_rows = []
    for length, mode in notch_plan(transactions, rng):
        wave = notch_model(length) if mode == 'model' else gauss_complex(length, rng)
        assert len(wave) == length >= 1
        samples = quantize(wave)
        in_rows.extend((re, im, int(k == length - 1)) for k, (re, im) in enumerate(samples))
        outs = r.notch(samples, coefficients, stats=trace)
        assert len(outs) == length
        assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in outs)
        out_rows.extend((re, im, int(k == length - 1)) for k, (re, im) in enumerate(outs))
    wave = overload_wave(NOTCH_OVERLOAD)
    outs = r.notch(wave, coefficients, stats=trace)
    flat = [v for re, im in outs for v in (re, im)]
    assert max(flat) == LIMIT and min(flat) == -LIMIT-1, \
        f'notch overload wave does not saturate ({max(flat)}, {min(flat)}) with {notch} -> {coefficients}'
    in_rows.extend((re, im, int(k == len(wave) - 1)) for k, (re, im) in enumerate(wave))
    out_rows.extend((re, im, int(k == len(outs) - 1)) for k, (re, im) in enumerate(outs))
    inputs = save(folder / 'notch_in.txt', in_rows)
    outputs = save(folder / 'notch_out.txt', out_rows)
    return inputs, outputs


def build_kalman(folder, kalman, transactions, rng, trace=None):
    parameters = r.kalman_parameters(*kalman)
    (folder / 'kalman_cfg.txt').write_text(' '.join(map(str, parameters)) + '\n')
    in_rows = []
    out_rows = []
    for length, mode in kalman_plan(transactions, rng):
        if mode == 'model':
            wave = gauss_real(length, rng)
        elif mode == 'real':
            wave = gauss_real(length, rng)
        else:
            wave = gauss_complex(length, rng)
        assert len(wave) == length >= 1
        samples = quantize(wave)
        in_rows.extend((re, im, int(k == length - 1)) for k, (re, im) in enumerate(samples))
        outs = r.kalman(samples, parameters, stats=trace)
        assert len(outs) == length
        assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in outs)
        out_rows.extend((re, im, int(k == length - 1)) for k, (re, im) in enumerate(outs))
    if any(k for k in r.kalman_gains(parameters, 16)):
        wave = overload_wave(KALMAN_OVERLOAD)
        # recorded in `trace` only because this wave IS appended to the stream below
        outs = r.kalman(wave, parameters, stats=trace)
        flat = [v for re, im in outs for v in (re, im)]
        assert max(flat) == LIMIT and min(flat) == -LIMIT-1, \
            f'kalman overload wave does not saturate ({max(flat)}, {min(flat)}) with {kalman}'
        in_rows.extend((re, im, int(k == len(wave) - 1)) for k, (re, im) in enumerate(wave))
        out_rows.extend((re, im, int(k == len(outs) - 1)) for k, (re, im) in enumerate(outs))
        overloaded = True
    else:
        overloaded = False   # q = p0 = 0 makes every gain K = 0: V (and the output) stay 0
    inputs = save(folder / 'kalman_in.txt', in_rows)
    outputs = save(folder / 'kalman_out.txt', out_rows)
    return inputs, outputs, overloaded


def vectors(folder, notch=(.23, .94), kalman=(.0005, .25, 1), transactions=3, seed=29,
            notch_raw=None, label=None):
    """Files in `folder`: notch_cfg.txt (`b1 a1 a2`), notch_in.txt / notch_out.txt
    (`re im last`), kalman_cfg.txt (`q r p0`), kalman_in.txt / kalman_out.txt (`re im last`),
    plus the saturation expected files notch_state_expected.txt, notch_output_expected.txt,
    kalman_expected.txt (sat_diag.write_expected: FIELDS, then evaluations/positive/negative
    per field, stage order as NOTCH_STATE_STAGES / NOTCH_OUTPUT_STAGES / KALMAN_STAGES) and
    saturation.json (model-side expected counts; the runner stores the actual RTL_verified
    counts separately once every normal scenario matched).
    `notch_raw` bypasses notch_coefficients with a raw registered-coefficient tuple
    (labelled stress configuration; the model takes that same raw tuple)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    trace = sat_diag.SatTrace()
    ni, no = build_notch(folder, notch, transactions, rng, trace=trace, raw=notch_raw)
    ki, ko, kalman_overload = build_kalman(folder, kalman, transactions, rng, trace=trace)
    # every recorded sample above IS part of the streamed *_in.txt files; nothing else
    # was traced, so the expected counts equal exactly the streamed transactions.
    sat_diag.write_expected(folder / 'notch_state_expected.txt', trace, NOTCH_STATE_STAGES)
    sat_diag.write_expected(folder / 'notch_output_expected.txt', trace, NOTCH_OUTPUT_STAGES)
    sat_diag.write_expected(folder / 'kalman_expected.txt', trace, KALMAN_STAGES)
    payload = sat_diag.save_json(
        folder / 'saturation.json', trace,
        label=label or 'designed', notch=list(notch), kalman=list(kalman),
        notch_raw=list(notch_raw) if notch_raw is not None else None,
        notch_state_stages=NOTCH_STATE_STAGES, notch_output_stages=NOTCH_OUTPUT_STAGES,
        kalman_stages=KALMAN_STAGES,
        expected_files=dict(notch_state='notch_state_expected.txt',
                            notch_output='notch_output_expected.txt',
                            kalman='kalman_expected.txt'))
    def totals(stages):
        return (sum(trace.evaluations.get(s, 0) for s in stages),
                sum(trace.counts.get(s, {}).get('pos', 0) + trace.counts.get(s, {}).get('neg', 0)
                    for s in stages))
    return dict(notch=tuple(notch_raw) if notch_raw is not None else notch, kalman=kalman,
                notch_raw=notch_raw, transactions=transactions,
                notch_transactions=transactions+1,
                kalman_transactions=transactions+int(kalman_overload),
                notch_inputs=ni, notch_outputs=no, kalman_inputs=ki, kalman_outputs=ko,
                kalman_overload=kalman_overload,
                saturation=payload,
                saturation_markers={'notch_state': totals(NOTCH_STATE_STAGES),
                                    'notch_output': totals(NOTCH_OUTPUT_STAGES),
                                    'kalman': totals(KALMAN_STAGES)})


if __name__ == '__main__':
    print(vectors(ROOT / 'build/rtl/oset/vectors'))
