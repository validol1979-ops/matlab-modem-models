"""Costas loop + Gardner timing RTL vectors: the bit-exact outputs of common/python/sync_fixed.py for
rtl/common/costas_loop.sv and rtl/common/gardner_timing.sv (one folder holds both streams).

Both DUTs are configured with ONE transfer (the bench drives the values, waits for cfg_ready and then
for `configured`): cl_cfg.txt holds `k1 k2` (the integer gains of sync_fixed.costas_gains), gt_cfg.txt
holds `sps count position k3 k4` (position as an integer Q32, gains as in sync_fixed.timing_gains).

A costas transaction is one signal (s_last on its last sample) and answers one output per sample
(value + the phase used for it, m_last on the last). A timing transaction is one signal (s_last on its
last sample, length <= 16384) and answers exactly `count` outputs (mid + position in Q16, m_last on the
very last); `count` is the same for every transaction of one configuration, so one vectors() call uses
one count.

A Costas signal is the model case first (qpsk_script_costas constellation symbols of random labels
times exp(1j(.3+.006 t)), 768 samples, see tests/test_sync_fixed.py) and then random QPSK with a random
phase and frequency of random length 1..300. A timing signal is the model case first (transmit + rrc
matched filter + cubic delay -1.25 as in tests/test_sync_fixed.py, count 700) and then shorter
random-label signals with count kept so that position + count*sps stays inside the signal (the signals
are zero padded so the loop always reads samples inside the transaction). Files: cl_cfg.txt, cl_in.txt
(`re im last`), cl_out.txt (`re im phase last`), gt_cfg.txt, gt_in.txt (`re im last`), gt_out.txt
(`re im position last`), cl_slip_reference.txt (one reference phase in radians per row, the slip
transaction of the model configuration only) and the cl_tracking.json / gt_tracking.json / cl_slip.json
sidecars. All values are Q15 ints clipped to the signed 18 bit range, phases (2^-32
turns) and positions (Q16) are 32 bit signed.

OUTPUT OVERLOAD TRANSACTION (the Q15 sat of the outputs, the `m` covergroup bins). Both loops restart
with every transaction (costas_loop.sv: "Each transaction starts from phase = frequency = 0"), so each
stream carries a deterministic wave that owns the whole loop trajectory and draws no random numbers
(after the streamed transactions, and before the model scenarios where the model cases are present).

COSTAS QUADRANT SLIP TRANSACTION (model configuration only, appended AFTER every other Costas
transaction so the existing vectors stay an exact prefix and the RNG stream is untouched; the slip
signal is deterministic and draws no random numbers). A +100 degree carrier step at sample 300 moves
the median phase error of the loop by about -90 degrees: the loop keeps tracking modulo 90 degrees
while the true carrier stays in the neighbouring quadrant. The 900 samples of that scenario are one
transaction, and cl_slip.json records where it sits in cl_in.txt/cl_out.txt (`row_start`, `row_stop`
as 0-based data-row indices, stop exclusive, counted from the first row after the row-count header),
the file holding the known reference phase of every sample (`reference_file`, one float radian per
row, written with save()) and the metrics of sync_scenarios.costas_slip_metrics; `rtl_verified` is
false - the quadrant change is Python model evidence and the RTL scoreboard does not claim it. For
every non-model configuration cl_slip.json holds the JSON value null and no reference file is written
(the transaction count of the stream only grows by the slip transaction in the model case).

Costas: an output component reaches 2^17 - 1 only when the desrotated vector lies close to an axis and
carries more than one axis of magnitude. A constellation corner (|re| = |im|) holds the discriminator
sign(re) im - sign(im) re at 0 and freezes the phase, and a locked loop parks the desrotated point on
the 45 degree corner, whose components are the corner magnitude scaled by the cos table (131070). The
overload signal starts with COSTAS_RAMP samples of (2^17 - 1, 2^16), whose discriminator is -2^16 and
lets the frequency accumulator grow, and then feeds the corner (2^17 - 1, 2^17 - 1): the discriminator
returns to 0, so the frequency stops growing while the phase keeps sweeping at it, and the sweep
crosses the rotation that puts the whole corner magnitude sqrt 2 (2^17 - 1) on one axis (+full); the
opposite corner at the end gives -full. Both rails are hit with every non-zero gain. With the
zero-gain configuration (k1, k2) = (0, 0) the phase stays 0 forever, rotate(z, 0) = z * 131071 / 2^17
is bounded by +131070 and only -full is reachable (the input -2^17 gives -131071); that case reports
overload=False and the assert below allows only that exception.

Gardner: the output is interp(x, P16), a cubic interpolation, which reproduces a constant wave exactly
and overshoots at a step, so the overload transaction is half +full and half -full samples across the
window the loop reads (plus the zero tail that keeps the four taps inside the transaction): both rails
are hit with all four configurations.

GRADIENT SATURATION EVIDENCE. Every scored timing transaction (every gt_out.txt row: the streamed
transactions, the overload transaction and the model scenario when present) is re-evaluated through
sync_fixed.timing(stats=SatTrace()), which records each actual preclamp Gardner gradient as stage
'gradient' under the symmetric +-ONE30 clamp; the run is bit-identical to the uninstrumented one, so
all existing txt vector bytes and the RNG stream are unchanged. sync_gradient_expected.txt holds the
sat_diag.write_expected row for the single field (evaluations positive negative); the evaluations are
the total scored timing output count. saturation.json holds the same model counts (the runner may add
rtl_verified separately).
"""
from pathlib import Path
import math
import json
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import sync_fixed as s
import sat_diag
from modem_core import load_config, transmit, rrc_taps, cubic
from sync_scenarios import costas_scenario, costas_slip_scenario, costas_disturbance_scenario, timing_scenario

LIMIT = (1 << 17) - 1
MODEL_MODEM = ROOT / 'modems/qpsk_script_costas/config.json'
MODEL_SAMPLES = 768
COSTAS_MODEL = (.08, .001)
TIMING_MODEL = (8, 700, 32, .1, .00005)
MAX_COSTAS_SAMPLES = 300
MAX_TIMING_SAMPLES = 16384
COSTAS_RAMP = 8
COSTAS_PLATEAU = 16
GRADIENT_STAGES = ('gradient',)


def save(path, rows):
    rows = list(rows)
    path.write_text(str(len(rows)) + '\n' + '\n'.join(' '.join(map(str, row)) for row in rows) + '\n')
    return len(rows)


def quantize(values):
    """Complex wave as Q15 ints, clipped to the signed 18 bit range (q15 of test_sync_fixed.py)."""
    rows = []
    for v in values:
        re = int(round(float(np.real(v)) * 32768))
        im = int(round(float(np.imag(v)) * 32768))
        rows.append((max(-LIMIT - 1, min(LIMIT, re)), max(-LIMIT - 1, min(LIMIT, im))))
    return rows


def pilot():
    return load_config(MODEL_MODEM)


def symbols_of(cfg, labels):
    return (np.array(cfg['constellation']) @ [1, 1j])[np.asarray(labels, dtype=int)]


def costas_signal(cfg, rng, model):
    """Model case: symbols*exp(1j(.3+.006 t)), 768 samples; otherwise random QPSK with a random
    carrier phase and frequency offset of random length 1..300."""
    if model:
        length, phase, frequency = MODEL_SAMPLES, .3, .006
    else:
        length = int(rng.integers(1, MAX_COSTAS_SAMPLES + 1))
        phase = float(rng.uniform(0, 2 * np.pi))
        frequency = float(rng.uniform(-.04, .04))
    return symbols_of(cfg, rng.integers(0, cfg['order'], length)) \
        * np.exp(1j * (phase + frequency * np.arange(length)))


def shaped_signal(cfg, rng, labels_count):
    """Random-label QPSK through the transmod rrc and the cubic matched filter/delay of the model
    case in tests/test_sync_fixed.py (delay -1.25 samples)."""
    shaped = transmit(cfg, rng.integers(0, cfg['order'], labels_count))['waveform']
    matched = np.convolve(shaped, rrc_taps(cfg['sps'], cfg['rrc_order'], cfg['rolloff']))
    return cubic(matched, np.arange(len(matched)) - 1.25)


def rails(rows):
    """(peak, valley) over every output field of the rows."""
    flat = [value for row in rows for value in row]
    return max(flat), min(flat)


def costas_overload():
    """Deterministic overload signal: COSTAS_RAMP samples of (2^17 - 1, 2^16) build frequency (their
    discriminator is -2^16), then COSTAS_PLATEAU samples of the corner (2^17 - 1, 2^17 - 1) - its
    discriminator is 0, which freezes the frequency but not the phase - so the sweep crosses the
    rotation that puts the corner magnitude on one axis (+full), and the opposite corner at the end
    gives -full."""
    return ([(LIMIT, LIMIT // 2)] * COSTAS_RAMP + [(LIMIT, LIMIT)] * COSTAS_PLATEAU
            + [(-LIMIT - 1, -LIMIT - 1)] * COSTAS_PLATEAU)


def timing_overload(sps, count, position, pad):
    """Deterministic overload signal: half +full and half -full samples across the window the loop
    reads (ceil(position) + count * sps taps deep) and the zero tail, so interp() reproduces both
    rails and overshoots them at the step."""
    needed = math.ceil(position) + count * sps + 8 + pad
    first = needed // 2
    return ([(LIMIT, LIMIT)] * first + [(-LIMIT - 1, -LIMIT - 1)] * (needed - first)
            + [(0, 0)] * (pad + 16))


def build_costas(folder, k, transactions, rng):
    gains = s.costas_gains(*k)
    (folder / 'cl_cfg.txt').write_text(f'{gains[0]} {gains[1]}\n')
    model = tuple(round(v, 12) for v in k) == COSTAS_MODEL
    cfg = pilot()
    in_rows, out_rows = [], []
    for index in range(transactions):
        samples = quantize(costas_signal(cfg, rng, model and index == 0))
        assert 1 <= len(samples) <= MAX_TIMING_SAMPLES
        in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
        values, phases = s.costas(samples, gains)
        assert len(values) == len(phases) == len(samples)
        assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in values)
        assert all(-(1 << 31) <= phase < 1 << 31 for phase in phases)
        out_rows.extend((re, im, phase, int(k == len(samples) - 1))
                        for k, ((re, im), phase) in enumerate(zip(values, phases)))
    # the overload transaction: a full scale corner, swept across the rotation by the loop inertia
    samples = costas_overload()
    values, phases = s.costas(samples, gains)
    assert len(values) == len(phases) == len(samples)
    assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in values)
    assert all(-(1 << 31) <= phase < (1 << 31) for phase in phases)
    peak, valley = rails(values)
    assert valley <= -LIMIT, f'costas: valley {valley} above the negative rail'
    # a frozen loop (k1 = k2 = 0) never rotates: its output is the input scaled by 131071 / 2^17,
    # bounded by +131070, so only -full is reachable there
    assert peak >= LIMIT or gains == (0, 0), f'costas: peak {peak} below the positive rail'
    in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
    out_rows.extend((re, im, phase, int(k == len(samples) - 1))
                    for k, ((re, im), phase) in enumerate(zip(values, phases)))
    tracking = None
    if model:
        samples, values, phases, tracking, _, _ = costas_scenario()
        assert all(tracking[name] for name in ('acquired', 'lost', 'recovered'))
        in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
        out_rows.extend((re, im, phase, int(k == len(samples) - 1))
                        for k, ((re, im), phase) in enumerate(zip(values, phases)))
    (folder/'cl_tracking.json').write_text(json.dumps(tracking, indent=2)+'\n')
    # The quadrant slip follows the original transactions: their rows stay byte identical and the
    # deterministic scenario draws no numbers from `rng`, so the whole stream keeps its prefix.
    slip = None
    if model:
        samples, values, phases, metrics, reference, disabled = costas_slip_scenario()
        # The scenario ran with the model gains, so its outputs are the outputs of this transaction.
        assert s.costas(samples, gains) == (values, phases)
        assert len(samples) == len(values) == len(phases) == len(reference) == len(disabled)
        assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in values)
        assert all(-(1 << 31) <= phase < 1 << 31 for phase in phases)
        # The disabled loop is the negative control: with (k1, k2) = (0, 0) the phase never leaves 0
        # and it never holds either view of the phase error.
        assert disabled == [0] * len(disabled)
        assert metrics['slipped'] and metrics['disabled_rejected']
        row_start = len(out_rows)
        in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
        out_rows.extend((re, im, phase, int(k == len(samples) - 1))
                        for k, ((re, im), phase) in enumerate(zip(values, phases)))
        row_stop = len(out_rows)
        assert row_stop - row_start == len(samples)
        assert save(folder / 'cl_slip_reference.txt', [(float(v),) for v in reference]) \
            == len(samples)
        assert save(folder / 'cl_slip_disabled.txt', [(int(v),) for v in disabled]) == len(samples)
        slip = dict(row_start=row_start, row_stop=row_stop, reference_file='cl_slip_reference.txt',
                    disabled_file='cl_slip_disabled.txt', metrics=metrics, rtl_verified=False)
    (folder/'cl_slip.json').write_text(json.dumps(slip, indent=2)+'\n')
    disturbances = []
    if model:
        for kind in ('noise_burst', 'fade_frequency_excursion'):
            samples, values, phases, metrics, reference, disabled = costas_disturbance_scenario(kind)
            assert all(metrics[name] for name in ('acquired','lost_mod90_lock','relocked_mod90',
                                                 'adjacent_quadrant','disabled_rejected'))
            row_start = len(out_rows)
            in_rows.extend((re, im, int(k == len(samples)-1)) for k, (re, im) in enumerate(samples))
            out_rows.extend((re, im, phase, int(k == len(samples)-1))
                            for k, ((re, im), phase) in enumerate(zip(values, phases)))
            reference_file=f'cl_{kind}_reference.txt'
            disabled_file=f'cl_{kind}_disabled.txt'
            save(folder/reference_file, [(float(v),) for v in reference])
            save(folder/disabled_file, [(int(v),) for v in disabled])
            disturbances.append(dict(kind=kind,row_start=row_start,row_stop=len(out_rows),
                                     reference_file=reference_file,disabled_file=disabled_file,
                                     metrics=metrics,rtl_verified=False))
    (folder/'cl_disturbances.json').write_text(json.dumps(disturbances,indent=2)+'\n')
    acquisition = []
    if model:
        import costas_acquisition as ac
        source = ac.symbols()
        for phase in ac.PHASES_DEG:
            for cfo in ac.CFOS:
                reference = ac.reference(phase,cfo)
                samples = ac.quantize(source*np.exp(1j*reference))
                values,phases = s.costas(samples,gains)
                row_start = len(out_rows)
                in_rows.extend((re,im,int(k==len(samples)-1)) for k,(re,im) in enumerate(samples))
                out_rows.extend((re,im,p,int(k==len(samples)-1))
                                for k,((re,im),p) in enumerate(zip(values,phases)))
                reference_file=f'cl_acquisition_{phase}_{cfo}_reference.txt'
                save(folder/reference_file,[(float(v),) for v in reference])
                acquisition.append(dict(phase_deg=phase,cfo_rad_per_sample=cfo,
                                        row_start=row_start,row_stop=len(out_rows),
                                        reference_file=reference_file))
    (folder/'cl_acquisition.json').write_text(json.dumps(acquisition,indent=2)+'\n')
    inputs = save(folder / 'cl_in.txt', in_rows)
    outputs = save(folder / 'cl_out.txt', out_rows)
    return inputs, outputs, peak >= LIMIT and valley <= -LIMIT, [peak, valley], tracking, slip, disturbances, acquisition


def build_timing(folder, parameters, transactions, rng):
    sps, count, position, k3, k4 = parameters
    gains = s.timing_gains(position, k3, k4)
    (folder / 'gt_cfg.txt').write_text(f'{sps} {count} {gains[0]} {gains[1]} {gains[2]}\n')
    model = tuple(parameters) == TIMING_MODEL
    cfg = pilot()
    # The loop can move the position by up to (k3+k4) samples per output; the zeros keep every tap
    # inside the transaction so that the DUT and the model read the same samples.
    pad = 8 + int(math.ceil(4 * (1 + count * (k3 + k4))))
    needed = math.ceil(position) + count * sps + 8 + pad
    in_rows, out_rows = [], []
    trace = sat_diag.SatTrace()
    for index in range(transactions):
        if model and index == 0:
            labels_count = MODEL_SAMPLES
        else:
            labels_count = max(8, int(math.ceil((needed - pad - cfg['rrc_order']) / cfg['sps'])))
        wave = shaped_signal(cfg, rng, labels_count)
        assert len(wave) + pad >= needed
        samples = quantize(np.concatenate([wave, np.zeros(pad, dtype=complex)]))
        assert len(samples) <= MAX_TIMING_SAMPLES
        in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
        values, positions = s.timing(samples, sps, count, gains, stats=trace)
        assert len(values) == len(positions) == count
        assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in values)
        # The four cubic taps of every output must stay inside the transaction.
        assert all(1 <= pos >> 16 and (pos >> 16) + 3 <= len(samples) and pos < 1 << 31
                   for pos in positions)
        out_rows.extend((re, im, pos, int(k == count - 1))
                        for k, ((re, im), pos) in enumerate(zip(values, positions)))
    # the overload transaction: half +full and half -full samples across the read window
    samples = timing_overload(sps, count, position, pad)
    assert len(samples) <= MAX_TIMING_SAMPLES
    values, positions = s.timing(samples, sps, count, gains, stats=trace)
    assert len(values) == len(positions) == count
    assert all(abs(re) <= LIMIT + 1 and abs(im) <= LIMIT + 1 for re, im in values)
    # The four cubic taps of every output must stay inside the transaction.
    assert all(1 <= pos >> 16 and (pos >> 16) + 3 <= len(samples) and pos < (1 << 31)
               for pos in positions)
    peak, valley = rails(values)
    assert peak >= LIMIT and valley <= -LIMIT, f'timing: {peak}, {valley} inside the rails'
    in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
    out_rows.extend((re, im, pos, int(k == count - 1))
                    for k, ((re, im), pos) in enumerate(zip(values, positions)))
    tracking = None
    if model:
        samples, values, positions, tracking, _, _ = timing_scenario()
        assert len(samples) <= MAX_TIMING_SAMPLES
        assert len(values) == count
        assert all(1 <= pos >> 16 and (pos >> 16) + 3 <= len(samples) for pos in positions)
        assert all(tracking[name] for name in ('acquired', 'lost', 'recovered'))
        # Trace the scenario transaction too: scenario() ran without stats, so re-evaluate the
        # same samples with the very same gains and require the identical (bit-exact) outputs.
        traced_values, traced_positions = s.timing(samples, sps, count, gains, stats=trace)
        assert traced_values == values and traced_positions == positions
        in_rows.extend((re, im, int(k == len(samples) - 1)) for k, (re, im) in enumerate(samples))
        out_rows.extend((re, im, pos, int(k == count - 1))
                        for k, ((re, im), pos) in enumerate(zip(values, positions)))
    (folder/'gt_tracking.json').write_text(json.dumps(tracking, indent=2)+'\n')
    inputs = save(folder / 'gt_in.txt', in_rows)
    outputs = save(folder / 'gt_out.txt', out_rows)
    # Every scored timing output evaluates the Gardner gradient exactly once.
    assert trace.evaluations.get('gradient', 0) == outputs
    expected = sat_diag.write_expected(folder / 'sync_gradient_expected.txt', trace, GRADIENT_STAGES)
    sat_diag.save_json(folder / 'saturation.json', trace, model='sync_timing',
                       stages=list(GRADIENT_STAGES), sps=sps, count=count,
                       position=gains[0], k3=gains[1], k4=gains[2],
                       scored_outputs=outputs,
                       counted='scored timing transactions only (gt_out.txt rows)')
    return inputs, outputs, True, [peak, valley], tracking, trace, expected[0]


def vectors(folder, costas=COSTAS_MODEL, timing=TIMING_MODEL, transactions=2, seed=37):
    """Files in `folder`: cl_cfg.txt (`k1 k2`), cl_in.txt / gt_in.txt (`re im last`), cl_out.txt
    (`re im phase last`), gt_cfg.txt (`sps count position k3 k4`), gt_out.txt (`re im position last`).
    The model cases of tests/test_sync_fixed.py are the first transaction when `costas`/`timing` are
    the model parameters; the timing `count` is shared by all transactions of the call. The model
    configuration also appends the quadrant slip transaction and writes cl_slip.json (the other
    configurations write a null cl_slip.json); see the module docstring."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(seed)
    ci, co, cl_over, cl_rails, cl_tracking, cl_slip, disturbances, acquisition = build_costas(
        folder, tuple(costas), transactions, rng)
    ti, to, gt_over, gt_rails, gt_tracking, gt_trace, gt_gradient = build_timing(
        folder, tuple(timing), transactions, rng)
    return dict(costas=tuple(costas), timing=tuple(timing), transactions=transactions,
                costas_transactions=transactions + 1 + int(cl_tracking is not None)
                                        + int(cl_slip is not None)+len(disturbances)+len(acquisition),
                cl_slip=cl_slip,
                cl_disturbances=disturbances,
                cl_acquisition=acquisition,
                cl_slip_rows=None if cl_slip is None else [cl_slip['row_start'], cl_slip['row_stop']],
                timing_transactions=transactions+1+int(gt_tracking is not None),
                cl_tracking=cl_tracking, gt_tracking=gt_tracking,
                cl_inputs=ci, cl_outputs=co, gt_inputs=ti, gt_outputs=to,
                cl_overload=cl_over, cl_rails=cl_rails, gt_overload=gt_over, gt_rails=gt_rails,
                gt_gradient_evaluations=gt_trace.evaluations.get('gradient', 0),
                gt_gradient_events=gt_trace.total(), gt_gradient_expected=list(gt_gradient))


if __name__ == '__main__':
    print(vectors(ROOT / 'build/rtl/sync/vectors/selftest_model', transactions=1))
    print(vectors(ROOT / 'build/rtl/sync/vectors/selftest_random',
                  (.02, .0001), (4, 40, 10, .05, .0001)))
