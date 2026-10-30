"""Beamformer + Alamouti RTL vectors: the bit-exact outputs of common/python/beam_fixed.py for
rtl/common/beamform.sv and rtl/common/alamouti_rx.sv (one folder holds both streams).

A configuration is a stream of Q15 complex values accepted while cfg_ready with cfg_last on the
last one: beamform_cfg.txt holds the M weights a_m (one per transfer, M <= 2^LOG2M), alamouti_cfg.txt
holds h0 then h1. The bench waits for `configured` (a reciprocal of the weight energy is computed).
Files: <x>_cfg.txt is a count line then `re im` rows.

A beamform transaction is whole snapshots of M samples (channel 0..M-1, s_last on the last sample)
and answers with one output per snapshot (m_last on the last). Beamform weights: 'steering' is the
model case exp(2j pi m .125) with its signal (desired exp(.12j t) + 3 exp(.47j t) * ones, t < 128)
as the first transaction; 'random' is scale*(normal+j normal)/2 with scale in (1, .2, .5, 2) picked
by seed. The other transactions are random complex Gaussian /3 with 1..40 snapshots.

An Alamouti transaction is sample pairs (r0, r1) (s_last on the last r1) and answers with two outputs
per pair (y0, y1; m_last on the very last). The model configuration h = [.4+.3j, 1-.2j] (the 'steering'
case) uses the model received wave from tests/test_beam_fixed.py as the first transaction; random
configurations use random h and random pairs. All in/out streams are Q15 ints `re im last` (last on
the last sample/output of a transaction), Q15 clipped to the signed 18 bit range.

OUTPUT OVERLOAD TRANSACTION (sat18, the `m` covergroup bins). The weights are a CONFIGURATION (one
cfg file per stream, loaded once per run), so an overload transaction has to work with the weights
the case already uses, and the normalisation 1/(a^H a) decides whether full scale is reachable at
all: every output component is a linear function of the input components over the box
|re|, |im| <= 2^17 - 1, so its exact peak is L * sum of the weight magnitudes times the reciprocal
(bf: L * sum_m (|a_re| + |a_im|) * R >> (Z - 15), al: L * (|h0_re| + |h0_im| + |h1_re| + |h1_im|)
* R >> (Z - 15)), attained at a box corner. The last transaction is that corner snapshot (pair) and
its negation, which gives the +full and -full outputs. It reaches the bound in every case; where the
bound itself sits below 2^17 - 1 that case cannot saturate with its own weights and reports
overload=False (measured peaks: beamform case2 m=3 scale 2 -> 122166, alamouti case1 112511,
case2 81931, case3 114815, all < 131071), while the other cases saturate both ways. The check below
asserts saturation or bound < LIMIT, so a case that loses saturation is caught. The overload
transaction consumes no random numbers.
"""
from pathlib import Path
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import beam_fixed as r
from fft_fixed import rnd as fx_rnd
from sat_diag import SatTrace, save_json, write_expected

LIMIT = (1 << 17) - 1
BF_STAGES = ['beam.output.re', 'beam.output.im']
AL_STAGES = ['alamouti.y0.re', 'alamouti.y0.im', 'alamouti.y1.re', 'alamouti.y1.im']
SCALES = [1.0, 0.2, 0.5, 2.0]
MODEL_T = 128
MODEL_SYMBOLS = 128
MAX_SNAPSHOTS = 40
MAX_PAIRS = 20
MODEL_H = (0.4 + 0.3j, 1.0 - 0.2j)


def save(path, rows):
    rows = list(rows)
    path.write_text(str(len(rows)) + '\n' + '\n'.join(' '.join(map(str, row)) for row in rows) + '\n')
    return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range (q15 of test_beam_fixed.py)."""
    rows = []
    for v in values:
        re = int(round(float(np.real(v)) * 32768))
        im = int(round(float(np.imag(v)) * 32768))
        rows.append((max(-LIMIT - 1, min(LIMIT, re)), max(-LIMIT - 1, min(LIMIT, im))))
    return rows


def steering(m):
    return np.exp(2j * np.pi * np.arange(m) * .125)


def beam_model(m):
    """(desired[:,None]*steering + interference[:,None]*ones).ravel(), t = 0..MODEL_T-1."""
    t = np.arange(MODEL_T)
    desired = np.exp(.12j * t)
    interference = 3 * np.exp(.47j * t)
    matrix = desired[:, None] * steering(m) + interference[:, None] * np.ones(m)
    return matrix.ravel()


def gauss_complex(length, rng):
    """Complex Gaussian /3 (beamformer signals)."""
    return (rng.normal(size=length) + 1j * rng.normal(size=length)) / 3


def gauss_pairs(pairs, rng):
    """2*pairs complex Gaussian /2 samples (Alamouti received pairs)."""
    return (rng.normal(size=2 * pairs) + 1j * rng.normal(size=2 * pairs)) / 2


def alamouti_model(rng):
    """The model received wave of tests/test_beam_fixed.py for MODEL_H (MODEL_SYMBOLS symbols)."""
    symbols = (rng.normal(size=MODEL_SYMBOLS) + 1j * rng.normal(size=MODEL_SYMBOLS)) / np.sqrt(2)
    h = np.array(MODEL_H)
    s = symbols.reshape(-1, 2)
    return np.c_[h[0] * s[:, 0] + h[1] * s[:, 1],
                 -h[0] * s[:, 1].conj() + h[1] * s[:, 0].conj()].ravel()


def clip(value):
    return max(-LIMIT - 1, min(LIMIT, value))


def negate(sample):
    """Negated sample, clipped to the legal range: with the wave and its negation the transaction
    hits +full and -full."""
    return tuple(clip(-value) for value in sample)


def beam_overload(weights):
    """(wave, bound): two snapshots - the input corner that maximises one output component (the
    corner of a linear functional: every component takes +-L with the sign of its coefficient, real
    from the weight real parts, imaginary from the weight imaginary parts, or the same for the
    imaginary output), then its negation - and the exact peak of any output component."""
    energy, R, Z = sum(re * re + im * im for re, im in weights), 0, 0
    R, Z = r.reciprocal(energy)
    bound = fx_rnd((LIMIT+1) * sum(abs(re) + abs(im) for re, im in weights) * R, Z - 15)
    corners = [[(LIMIT if re >= 0 else -LIMIT, LIMIT if im >= 0 else -LIMIT) for re, im in weights],
               [(-LIMIT if im >= 0 else LIMIT, LIMIT if re >= 0 else -LIMIT) for re, im in weights]]
    wave = max(corners, key=lambda c: max(abs(v) for o in r.beamform(c, weights) for v in o))
    return wave + [negate(sample) for sample in wave], bound


def alamouti_overload(taps):
    """(wave, bound): two sample pairs - the corner of (r0, r1) that maximises one of the four output
    components (a linear function of the four input components, so the peak is at a box corner: the
    16 sign combinations are enumerated) - and its negation, plus the exact peak of any component."""
    energy = sum(value * value for tap in taps for value in tap)
    R, Z = r.reciprocal(energy)
    bound = fx_rnd((LIMIT+1) * sum(abs(value) for tap in taps for value in tap) * R, Z - 15)
    corners = [(re0, im0, re1, im1) for re0 in (LIMIT, -LIMIT) for im0 in (LIMIT, -LIMIT)
               for re1 in (LIMIT, -LIMIT) for im1 in (LIMIT, -LIMIT)]
    best = max(corners, key=lambda c: max(abs(v) for pair in r.alamouti([c[:2], c[2:]], taps) for v in pair))
    return [best[:2], best[2:], negate(best[:2]), negate(best[2:])], bound


def check_overload(name, outs, bound):
    """True when the overload outputs reach full scale; otherwise the exact bound must sit below it
    (no input of this configuration can), which is asserted here."""
    flat = [value for pair in outs for value in pair]
    if max(flat) == LIMIT and min(flat) == -LIMIT-1:
        return True
    assert abs(bound) < LIMIT, f'{name}: {max(flat)} below full scale although the bound is {bound}'
    return False


def build_beamform(folder, m, weights_kind, transactions, rng):
    if weights_kind == 'steering':
        weights = steering(m)
    else:
        scale = SCALES[seed_scale(rng)]
        weights = scale * (rng.normal(size=m) + 1j * rng.normal(size=m)) / 2
    qweights = quantize(weights)
    (folder / 'bf_cfg.txt').write_text(
        str(m) + '\n' + '\n'.join(f'{re} {im}' for re, im in qweights) + '\n')
    in_rows, out_rows = [], []
    trace = SatTrace()
    for index in range(transactions):
        if index == 0 and weights_kind == 'steering':
            snapshots = MODEL_T
            wave = beam_model(m)
        else:
            snapshots = int(rng.integers(1, MAX_SNAPSHOTS + 1))
            wave = gauss_complex(snapshots * m, rng)
        samples = quantize(wave)
        assert len(samples) == snapshots * m >= m
        in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
        outs = r.beamform(samples, qweights, stats=trace)
        assert len(outs) == snapshots
        assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in outs)
        out_rows.extend((re, im, int(k == snapshots - 1)) for k, (re, im) in enumerate(outs))
    # the overload transaction: two snapshots, the saturating corner and its negation.
    # beam_overload's corner probes are hypothetical (never streamed): they run without stats.
    # Only the outputs that are actually appended are counted, so trace the streamed call on a
    # local trace and merge it once the append has happened.
    samples, bound = beam_overload(qweights)
    probe = SatTrace()
    outs = r.beamform(samples, qweights, stats=probe)
    bf_over = check_overload('beamform', outs, bound)
    in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
    out_rows.extend((re, im, int(k == len(outs) - 1)) for k, (re, im) in enumerate(outs))
    trace.merge(probe)
    inputs = save(folder / 'bf_in.txt', in_rows)
    outputs = save(folder / 'bf_out.txt', out_rows)
    bf_rows = write_expected(folder / 'beam_expected.txt', trace, BF_STAGES)
    return inputs, outputs, bf_over, bound, trace, bf_rows


def seed_scale(rng):
    """Scale index in (1, .2, .5, 2) picked from the seeded stream."""
    return int(rng.integers(0, len(SCALES)))


def build_alamouti(folder, weights_kind, transactions, rng):
    if weights_kind == 'steering':
        h = np.array(MODEL_H)
    else:
        h = rng.normal(size=2) + 1j * rng.normal(size=2)
    qh = quantize(h)
    (folder / 'al_cfg.txt').write_text(
        '2\n' + '\n'.join(f'{re} {im}' for re, im in qh) + '\n')
    in_rows, out_rows = [], []
    trace = SatTrace()
    for index in range(transactions):
        if index == 0 and weights_kind == 'steering':
            wave = alamouti_model(rng)
            pairs = MODEL_SYMBOLS // 2
        else:
            pairs = int(rng.integers(1, MAX_PAIRS + 1))
            wave = gauss_pairs(pairs, rng)
        samples = quantize(wave)
        assert len(samples) == 2 * pairs
        in_rows.extend((re, im, int(k == 2 * pairs - 1)) for k, (re, im) in enumerate(samples))
        outs = r.alamouti(samples, qh, stats=trace)
        assert len(outs) == 2 * pairs
        assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in outs)
        out_rows.extend((re, im, int(k == 2 * pairs - 1)) for k, (re, im) in enumerate(outs))
    # the overload transaction: two pairs, the saturating corner and its negation. The 16-corner
    # probe in alamouti_overload is hypothetical (never streamed) and runs without stats; only the
    # appended transaction is traced, on a local trace merged after the append.
    samples, bound = alamouti_overload(qh)
    probe = SatTrace()
    outs = r.alamouti(samples, qh, stats=probe)
    al_over = check_overload('alamouti', outs, bound)
    in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
    out_rows.extend((re, im, int(k == len(outs) - 1)) for k, (re, im) in enumerate(outs))
    trace.merge(probe)
    inputs = save(folder / 'al_in.txt', in_rows)
    outputs = save(folder / 'al_out.txt', out_rows)
    al_rows = write_expected(folder / 'alamouti_expected.txt', trace, AL_STAGES)
    return inputs, outputs, al_over, bound, trace, al_rows


def vectors(folder, m, weights_kind, transactions=3, seed=29):
    """Files in `folder`: bf_cfg.txt / al_cfg.txt (count then `re im`), bf_in.txt / bf_out.txt /
    al_in.txt / al_out.txt (`re im last`), beam_expected.txt / alamouti_expected.txt (saturation
    monitor expectations: FIELDS then evaluations/positive/negative per field) and saturation.json
    (model counts of the streamed transactions; the runner adds rtl_verified once the RTL agrees)."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    bi, bo, bf_over, bf_bound, bf_trace, bf_rows = build_beamform(folder, m, weights_kind, transactions, rng)
    ai, ao, al_over, al_bound, al_trace, al_rows = build_alamouti(folder, weights_kind, transactions, rng)
    combined = SatTrace()
    combined.merge(bf_trace).merge(al_trace)
    save_json(folder / 'saturation.json', combined,
              m=m, weights_kind=weights_kind, transactions=transactions + 1,
              bf_stages=BF_STAGES, al_stages=AL_STAGES,
              bf_expected=[list(row) for row in bf_rows],
              al_expected=[list(row) for row in al_rows],
              counted='streamed transactions only (overload probes of *_overload are hypothetical)')
    return dict(m=m, weights_kind=weights_kind, transactions=transactions+1,
                bf_inputs=bi, bf_outputs=bo, al_inputs=ai, al_outputs=ao,
                bf_overload=bf_over, bf_bound=bf_bound, al_overload=al_over, al_bound=al_bound,
                bf_events=bf_trace.total(), al_events=al_trace.total(),
                bf_evaluations=2 * bo, al_evaluations=2 * ao,
                bf_expected=bf_rows, al_expected=al_rows)


if __name__ == '__main__':
    print(vectors(ROOT / 'build/rtl/beam/vectors', 8, 'steering'))
