#!/usr/bin/env python3
"""Feedback-loop delay study of the bit-accurate receivers (RTL loop latency).

The RTL applies a loop error LOOP_DELAY symbols after the symbol that produced it
(PSK/QAM carrier and timing 4, or 8 with an equalizer; AGC 8; OQPSK split Costas 10;
coherent GMSK 10). The Python models reproduce exactly that (bit-exact with the RTL).
This tool answers whether those delays are safe:

1. Linear analysis. Detector gains Kd are MEASURED on the integer models: a known
   phase / timing / amplitude step is inserted into the noiseless channel after the
   preamble and the loop is opened (tracking=False or an unreachable delay), so the mean
   error per unit step is the detector slope. Loop gains come from the model constants.
   With an equalizer the measured slope also contains the equalizer's own adaptation to
   the step (two coupled loops), so there the linear numbers are indicative and the
   simulation is the deciding check. A feedforward carrier (no frequency term) is a
   first-order loop.
   The characteristic polynomials of the exact update order are
     PSK/QAM carrier   z^D (z-1)^2 + a z (z-1) + b z   = 0
     OQPSK/GMSK        z^D (z-1)^2 + a z (z-1) + b z^2 = 0
     timing and AGC    z^(D-1) (z-1) + k              = 0
   with D the delay in symbols (D=1: the next symbol uses the error). Reported per loop:
   spectral radius at the chosen delay, gain margin (largest loop-gain factor that stays
   stable), and the largest stable delay.
2. Simulation. The integer receivers run on modem_core.channel frames (phase noise with
   frequency offset, clock drift, and noise near threshold) for a sweep of delays; payload
   symbol errors are counted per delay. Only the delay changes between runs.

RTL timing is recorded for comparison, not re-measured by this script. OQPSK's
native RTL feedback monitor measures 45 enabled clocks from sample request to error
write, including the sample reader. Its readiness gate stretches the nominal
4-clock issue interval at short feedback ages. Other latency entries come from RTL
headers and have not been re-measured here.
"""
import argparse
import dataclasses
import json
import math
import sys
from concurrent.futures import ProcessPoolExecutor
import numpy as np
from regression_evidence import ROOT, begin, finish, write_json
sys.path.insert(0, str(ROOT/'common/python'))
import modem_core as real
import psk_fixed as p
import oqpsk_fixed as o
import cpm_fixed as c
from bpsk_cases import CONFIGS
from oqpsk_cases import CONFIG as OQPSK_CONFIG
from cpm_cases import CONFIGS as CPM_CONFIGS

TURN = 2**32
COUNT = 768
STEP_SYMBOL = 240                 # the step is inserted this many symbols into the frame
PSK_PROFILES = ('bpsk', 'qpsk', 'psk8_fb', 'psk8_ff', 'qam16', 'qam16_eq', 'qam64')
RECEIVERS = PSK_PROFILES+('oqpsk', 'gmsk')
DELAYS = (1, 2, 4, 6, 8, 10, 12, 16, 20, 24, 32, 40, 48, 64)
# OQPSK includes the reader (native feedback observer); other latency entries are
# header budgets. clocks_per_symbol is the nominal issue interval, before gating.
RTL_LATENCY = {'psk': dict(clocks=None, clocks_per_symbol=8, chosen=4,
                           note='catch-up II=4; the delay of 4 symbols is the documented budget'),
               'psk_eq': dict(clocks=32, clocks_per_symbol=8, chosen=8),
               'oqpsk': dict(clocks=45, clocks_per_symbol=4, chosen=o.LOOP_DELAY,
                             note='Measured request-to-error latency in enabled clocks; readiness gate inserts bubbles'),
               'gmsk': dict(clocks=38, clocks_per_symbol=4, chosen=10)}
# Calibrated per receiver at its chosen delay (4 frames of 576 payload symbols each) so
# that the operating point already shows occasional errors: per-sample SNR (modem_core.channel)
# and random-walk phase noise (rad per sample at 40 dB). BPSK keeps no error up to 0.032.
THRESHOLD_SNR = {'bpsk': -3, 'qpsk': 0, 'psk8_fb': 6, 'psk8_ff': 6, 'qam16': 6, 'qam16_eq': 6,
                 'qam64': 12, 'oqpsk': 0, 'gmsk': -3}
PHASE_NOISE = {'bpsk': .032, 'qpsk': .018, 'psk8_fb': .012, 'psk8_ff': .010, 'qam16': .009,
               'qam16_eq': .008, 'qam64': .004, 'oqpsk': .018, 'gmsk': .014}
SCENARIOS = {
    # Carrier tracking: random-walk phase noise (PHASE_NOISE) on top of a frequency offset.
    'phase_noise': dict(snr_db=40, frequency=3e-4, delay=1.25),
    # Timing tracking: sample-clock drift (the specification's +-6e-4) and a frequency offset;
    # only receivers with a timing loop (OQPSK, GMSK and feedforward 8-PSK have none).
    'clock_drift': dict(snr_db=30, frequency=-2e-4, drift=6e-4, delay=1.25),
    # Noise near the operating threshold (THRESHOLD_SNR).
    'threshold': dict(frequency=1e-4, delay=2.25),
}


def has_timing_loop(name):
    return name in PSK_PROFILES and bool(profile(name).timing_gain)


def profile(name):
    return getattr(p, name.upper())


def cfg_for(name):
    if name == 'oqpsk':return real.load_config(ROOT/OQPSK_CONFIG)
    if name == 'gmsk':return real.load_config(ROOT/CPM_CONFIGS[True])
    return real.load_config(ROOT/CONFIGS[name])


def alphabet(name):
    return 4 if name == 'oqpsk' else 2 if name == 'gmsk' else profile(name).alphabet


def frame(name, seed, params):
    cfg = cfg_for(name); rng = np.random.default_rng(seed)
    preamble = rng.integers(0, alphabet(name), 192)
    symbols = np.r_[preamble, rng.integers(0, alphabet(name), COUNT-192)]
    wave = real.channel(cfg, real.transmit(cfg, symbols)['waveform'], seed=seed, **params)
    return preamble, symbols, wave


def run_receiver(name, wave, preamble, *, delay=None, gain_delay=None, observe=False, open_loop=False):
    """Integer receiver with the loop delay replaced (None: the model default)."""
    quantized = p.quantize(wave)
    if name == 'oqpsk':
        return o.receive(quantized, preamble, COUNT, observe=observe, feedback=not open_loop, loop_delay=delay)
    if name == 'gmsk':
        saved = c.COHERENT_DELAY
        try:
            c.COHERENT_DELAY = 10**6 if open_loop else saved if delay is None else delay
            return c.receive_coherent(quantized, preamble, COUNT, observe=observe)
        finally:c.COHERENT_DELAY = saved
    prof = profile(name)
    if delay is not None:prof = dataclasses.replace(prof, loop_delay=delay)
    saved = p.GAIN_DELAY
    try:
        p.GAIN_DELAY = saved if gain_delay is None else gain_delay
        return p.receive(prof, quantized, preamble, COUNT, tracking=not open_loop, observe=observe)
    finally:p.GAIN_DELAY = saved


def payload_errors(name, result, symbols):
    # Every receiver returns decoded labels/bits comparable with the transmitted symbols.
    return int(np.count_nonzero(np.asarray(result['data'])[192:] != np.asarray(symbols)[192:]))


# ---------------------------------------------------------------- detector gains

def _stepped(wave, start, kind, size):
    wave = np.array(wave, complex); n = np.arange(len(wave)); after = n >= start
    if kind == 'phase':wave[after] *= np.exp(1j*size)
    elif kind == 'amplitude':wave[after] *= 1+size
    elif kind == 'timing':
        # Fractional advance of the waveform after `start` by `size` samples (cubic).
        shifted = real.cubic(wave, n+size)
        wave[after] = shifted[after]
    return wave


def detector_gain(name, kind, size):
    """Mean open-loop error per unit step (+size and -size averaged to cancel bias)."""
    preamble, _, wave = frame(name, 101, {})
    start = 8*STEP_SYMBOL
    slopes = []
    for sign in (1, -1):
        result = run_receiver(name, _stepped(wave, start, kind, sign*size), preamble, observe=True, open_loop=True)
        nodes = result['nodes'][STEP_SYMBOL+16:COUNT-16]
        key = {'phase': 'pe', 'timing': 'te', 'amplitude': 'ge'}[kind]
        if name in ('oqpsk', 'gmsk'):key = 'error'
        slopes.append(sign*float(np.mean([node[key] for node in nodes]))/size)
    return float(np.mean(slopes))


# ---------------------------------------------------------------- linear analysis

def poly_carrier(D, a, b, form):
    z1 = np.poly1d([1, -1])
    lhs = np.poly1d([1]+[0]*D)*z1*z1
    if form == 'psk':return lhs+a*np.poly1d([1, -1, 0])+b*np.poly1d([1, 0])
    return lhs+a*np.poly1d([1, -1, 0])+b*np.poly1d([1, 0, 0])


def poly_first(D, k):
    return np.poly1d([1]+[0]*(D-1))*np.poly1d([1, -1])+k


def radius(poly):
    roots = np.roots(poly.coeffs)
    return float(np.max(np.abs(roots))) if len(roots) else 0.


def stable(poly):return radius(poly) < 1-1e-12


def margin(make, D):
    """Largest loop-gain factor g with make(D, g) stable (bisection on a stable g=1)."""
    if not stable(make(D, 1.)):return 0.
    low, high = 1., 2.
    while stable(make(D, high)) and high < 1e6:low, high = high, 2*high
    for _ in range(60):
        mid = (low+high)/2
        low, high = (mid, high) if stable(make(D, mid)) else (low, mid)
    return low


def crossover(open_loop):
    """Crossover of the delay-free open loop L0 (|L0| falls monotonically for these loops):
    a delay of D symbols keeps |L| and subtracts w*D from the phase, so the loop stays
    stable while D < PM0/wc. Returns wc (rad/symbol) and PM0 (rad)."""
    low, high = 1e-9, math.pi
    if abs(open_loop(high)) >= 1:return math.pi, 0.
    for _ in range(200):
        mid = math.sqrt(low*high)
        low, high = (mid, high) if abs(open_loop(mid)) > 1 else (low, mid)
    wc = (low+high)/2
    return wc, math.pi+float(np.angle(open_loop(wc)))


def max_delay(make, open_loop):
    """Largest stable D from the phase margin; verified with the roots at D and D+1 when
    the polynomial degree stays modest."""
    wc, pm0 = crossover(open_loop)
    D = max(0, math.floor(pm0/wc-1e-9))
    verified = None
    if D <= 400:
        while D >= 1 and not stable(make(D, 1.)):D -= 1
        while stable(make(D+1, 1.)):D += 1
        verified = True
    return D, wc, pm0, verified


def loop_record(make, open_loop, chosen, gains):
    D, wc, pm0, verified = max_delay(make, open_loop)
    return dict(gains=gains, chosen_delay=chosen, radius=radius(make(chosen, 1.)),
                gain_margin=margin(make, chosen), phase_margin_deg=math.degrees(pm0-wc*chosen),
                crossover_rad_per_symbol=wc, max_stable_delay=D, max_delay_root_verified=verified,
                radius_by_delay={D: radius(make(D, 1.)) for D in DELAYS})


def open_carrier(a, b, form):
    def L(w):
        q = np.exp(-1j*w)
        return ((a*(1-q)+b*q) if form == 'psk' else (b+a*(1-q)))/(1-q)**2
    return L


def open_first(k):
    return lambda w: k/(1-np.exp(-1j*w))


def linear_analysis():
    records = {}
    for name in PSK_PROFILES:
        prof = profile(name)
        kd_phase = detector_gain(name, 'phase', .02)                       # pe per rad
        # Detector slopes are reported signed; the loops are negative feedback by
        # construction (the simulation at the chosen delay confirms it), so |Kd| is used.
        a = abs(kd_phase)*prof.phase_gain*2*math.pi/TURN
        b = abs(kd_phase)*prof.freq_gain*2*math.pi/TURN
        if b:
            carrier = lambda D, g, a=a, b=b: poly_carrier(D, g*a, g*b, 'psk'); opened = open_carrier(a, b, 'psk')
        else:
            # Feedforward carrier: phase-only update, the frequency state is constant (a
            # z=1 root that is not a loop mode), so the loop is first order.
            carrier = lambda D, g, a=a: poly_first(D, g*a); opened = open_first(a)
        entry = dict(carrier=loop_record(carrier, opened, prof.loop_delay,
                                         dict(kd_pe_per_rad=kd_phase, a=a, b=b,
                                              phase_gain=prof.phase_gain, freq_gain=prof.freq_gain)))
        if prof.timing_gain:
            kd_timing = detector_gain(name, 'timing', .05)                  # te per sample
            k = abs(kd_timing)*prof.timing_gain/2**17/2**16
            entry['timing'] = loop_record(lambda D, g, k=k: poly_first(D, g*k), open_first(k), prof.loop_delay,
                                          dict(kd_te_per_sample=kd_timing, k=k, timing_gain=prof.timing_gain))
        kd_gain = detector_gain(name, 'amplitude', .02)                   # ge per relative amplitude
        k = abs(kd_gain)*262/TURN                                          # relative gain step per unit
        entry['agc'] = loop_record(lambda D, g, k=k: poly_first(D, g*k), open_first(k), p.GAIN_DELAY,
                                   dict(kd_ge_per_unit=kd_gain, k=k, gain_step=262))
        records[name] = entry
    for name, module, delay in (('oqpsk', o, o.LOOP_DELAY), ('gmsk', c, c.COHERENT_DELAY)):
        kd = abs(detector_gain(name, 'phase', .02))/(TURN/(2*math.pi))      # turns per turn
        a = kd*module.PHASE_K/2**15; b = kd*module.FREQ_K/2**15
        carrier = lambda D, g, a=a, b=b: poly_carrier(D, g*a, g*b, 'angle')
        records[name] = dict(carrier=loop_record(carrier, open_carrier(a, b, 'angle'), delay, dict(kd=kd, a=a, b=b,
                                                                      phase_k=module.PHASE_K, freq_k=module.FREQ_K)))
    return records


# ---------------------------------------------------------------- simulation sweep

def _job(args):
    name, scenario, delay, gain_delay, seed = args
    params = dict(SCENARIOS[scenario])
    if scenario == 'threshold':params['snr_db'] = THRESHOLD_SNR[name]
    if scenario == 'phase_noise':params['phase_noise'] = PHASE_NOISE[name]
    preamble, symbols, wave = frame(name, seed, params)
    result = run_receiver(name, wave, preamble, delay=delay, gain_delay=gain_delay)
    return name, scenario, delay, gain_delay, payload_errors(name, result, symbols)


def simulate(frames, jobs):
    tasks = []
    for name in RECEIVERS:
        for scenario in SCENARIOS:
            if scenario == 'clock_drift' and not has_timing_loop(name):continue
            for delay in DELAYS:
                tasks += [(name, scenario, delay, None, 1000+17*f) for f in range(frames)]
    for name in ('qam16', 'qam64'):
        for gain_delay in DELAYS:
            tasks += [(name, 'threshold', None, gain_delay, 1000+17*f) for f in range(frames)]
    table = {}
    with ProcessPoolExecutor(max_workers=jobs) as pool:
        for name, scenario, delay, gain_delay, errors in pool.map(_job, tasks, chunksize=4):
            key = (name, scenario, 'agc' if gain_delay is not None else 'loop')
            entry = table.setdefault(key, {})
            d = gain_delay if gain_delay is not None else delay
            entry[d] = entry.get(d, 0)+errors
    out = {}
    for (name, scenario, loop), entry in table.items():
        out.setdefault(name, {}).setdefault(loop, {})[scenario] = {str(d): entry[d] for d in sorted(entry)}
    return out, len(tasks)


def summarise(linear, sweep, frames):
    """Per receiver: errors at the chosen delay and the largest swept delay with no more
    errors than max(1.5x, +frames) of the chosen one in every scenario (and every smaller delay)."""
    payload = frames*(COUNT-192)
    summary = {}
    for name in RECEIVERS:
        chosen = linear[name]['carrier']['chosen_delay']
        loop = sweep[name]['loop']
        def ok(d):
            # Same seeds at every delay: allow 1.5x the chosen-delay errors or one per frame.
            return all(row[str(d)] <= max(1.5*row[str(chosen)], row[str(chosen)]+frames) for row in loop.values())
        tolerated = max([d for d in DELAYS if all(ok(e) for e in DELAYS if e <= d)] or [0])
        summary[name] = dict(chosen_delay=chosen, payload_symbols_per_scenario=payload,
                             errors_at_chosen={s: row[str(chosen)] for s, row in loop.items()},
                             errors_at_delay_1={s: row['1'] for s, row in loop.items()},
                             largest_tolerated_delay=tolerated,
                             linear_max_stable_delay=linear[name]['carrier']['max_stable_delay'],
                             carrier_gain_margin=linear[name]['carrier']['gain_margin'])
    return summary


MIN_GAIN_MARGIN = 3.
MIN_PHASE_MARGIN_DEG = 45.


def gates(linear, summary, frames):
    """Failures: a loop at its chosen delay that is not linearly stable with gain margin
    >= 3 and phase margin >= 45 degrees, or a noise/drift scenario whose errors at the
    chosen delay exceed max(1.5x, +frames) of the errors at delay 1 (same seeds). The
    phase-noise penalty is reported, not gated: it is the finding of this study."""
    failures = []
    for name, loops in linear.items():
        for loop, record in loops.items():
            if (record['radius'] >= 1 or record['gain_margin'] < MIN_GAIN_MARGIN
                    or record['phase_margin_deg'] < MIN_PHASE_MARGIN_DEG):
                failures.append(f'{name} {loop}: linear margins at delay {record["chosen_delay"]}')
    for name, row in summary.items():
        for scenario in ('threshold', 'clock_drift'):
            if scenario in row['errors_at_chosen']:
                chosen, first = row['errors_at_chosen'][scenario], row['errors_at_delay_1'][scenario]
                if chosen > max(1.5*first, first+frames):
                    failures.append(f'{name} {scenario}: {chosen} errors at the chosen delay, {first} at delay 1')
    return failures


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n')[0])
    parser.add_argument('--frames', type=int, default=6)
    parser.add_argument('--jobs', type=int, default=16)
    parser.add_argument('--output', default=str(ROOT/'build/rtl/loop_delay_study/results.json'))
    args = parser.parse_args()
    evidence = begin()
    linear = linear_analysis()
    sweep, runs = simulate(args.frames, args.jobs)
    summary = summarise(linear, sweep, args.frames)
    for row in summary.values():
        pn = row['errors_at_chosen'].get('phase_noise'); first = row['errors_at_delay_1'].get('phase_noise')
        row['phase_noise_penalty'] = None if not first else pn/first
    failures = gates(linear, summary, args.frames)
    result = dict(status='FAIL' if failures else 'PASS', failures=failures,
                  gates=dict(min_gain_margin=MIN_GAIN_MARGIN, min_phase_margin_deg=MIN_PHASE_MARGIN_DEG), frames=args.frames, frame_symbols=COUNT, runs=runs, delays=list(DELAYS),
                  scenarios=SCENARIOS, threshold_snr_db=THRESHOLD_SNR, phase_noise=PHASE_NOISE, rtl_latency=RTL_LATENCY,
                  linear=linear, sweep=sweep, summary=summary)
    write_json(args.output, dict(result, **finish(evidence)))
    for name, row in summary.items():
        print(name, json.dumps(row))
    if failures:raise RuntimeError('Loop delay gates failed: '+'; '.join(failures))
    print('PASS loop delay study')


if __name__ == '__main__':
    main()
