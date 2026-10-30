#!/usr/bin/env python3
"""QPSK Costas acquisition evidence on sync_fixed.costas (rtl/common/costas_loop.sv model).

Deterministic 2400-sample QPSK stream with a perfectly known carrier reference
phase[n] = phase0 + cfo * n. A finite grid of initial phases [0, 20, 70, 160]
degrees and carrier offsets [0, 0.006, 0.3] rad/sample runs with loop gains
(0.08, 0.001); the same inputs also run with disabled gains (0, 0) as the
control. This samples a finite grid, not the complete acquisition region.

Two non-overlapping final windows [1600, 2000) and [2000, 2400) report, per
window: true angular error RMS (loop phase against the analytic reference,
full circle, never folded by payload decisions and never compensated toward
the payload truth), modulo-90 residual RMS, the dominant quadrant offset and
its stability. Classification: true_quadrant_lock at offset 0,
other_quadrant_lock at 90/180/270 (each offset is reported with its explicit
magnitude), unlocked otherwise or when the two
windows disagree. PASS (exit 0) requires every grid point to classify as
expected, all three classes present, window-stable classifications and the
disabled control not tracking; anything else is FAIL (exit 1).
"""
from pathlib import Path
import json
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
sys.path.insert(0, str(ROOT / 'tools'))
import sync_fixed
from regression_evidence import begin, finish, require_unoptimized, write_json

N = 2400
SEED = 20261013
GAINS = (0.08, 0.001)
DISABLED_GAINS = (0, 0)
PHASES_DEG = (0, 20, 70, 160)
CFOS = (0.0, 0.006, 0.3)
WINDOWS = ((1600, 2000), (2000, 2400))
LOCK_RESIDUAL_MAX_DEG = 1.0
LOCK_STABILITY_MIN = 1.0
CONTROL_RESIDUAL_MIN_DEG = 15.0
TARGET = ROOT / 'build/rtl/costas_acquisition/results.json'

TRUE_LOCK = 'true_quadrant_lock'
ADJACENT_LOCK = 'other_quadrant_lock'
UNLOCKED = 'unlocked'

# Deterministic fixed-point outcome locked in as the grid's regression expectation.
EXPECTED = {}
for _cfo in CFOS:
    for _phase in PHASES_DEG:
        if _cfo == 0.3:
            EXPECTED[(_phase, _cfo)] = (UNLOCKED, None)
        elif _phase in (0, 20):
            EXPECTED[(_phase, _cfo)] = (TRUE_LOCK, 0)
        elif _phase == 70:
            EXPECTED[(_phase, _cfo)] = (ADJACENT_LOCK, 270)
        else:
            EXPECTED[(_phase, _cfo)] = (ADJACENT_LOCK, 180)


def symbols():
    """Deterministic unit-magnitude QPSK symbols (+-1 +- j)/sqrt(2)."""
    rng = np.random.default_rng(SEED)
    return ((rng.integers(0, 2, N) * 2 - 1) + 1j * (rng.integers(0, 2, N) * 2 - 1)) / np.sqrt(2.0)


def reference(phase_deg, cfo):
    """Known carrier reference: phase + cfo * n rad, no payload-truth compensation."""
    return np.deg2rad(phase_deg) + cfo * np.arange(N)


def quantize(wave):
    """Q15 pairs as fed to sync_fixed.costas, clamped like rtl/common/costas_loop.sv."""
    return [(max(-131072, min(131071, round(float(z.real) * 32768))),
             max(-131072, min(131071, round(float(z.imag) * 32768)))) for z in wave]


def error_degrees(phases, reference_phase):
    """Signed true loop-vs-reference phase error per sample, (-180, 180] degrees."""
    loop = np.array(phases) * (2.0 * np.pi / 2**32)
    return np.degrees(np.angle(np.exp(1j * (loop - reference_phase))))


def window_metrics(error, start, stop):
    """True error RMS, modulo-90 residual RMS, dominant quadrant offset and stability."""
    error = np.asarray(error, dtype=float)
    if (error.ndim != 1 or not 0 <= start < stop <= len(error)
            or not np.all(np.isfinite(error))):
        raise ValueError('Invalid phase evidence window')
    deg = error[start:stop]
    folded = (deg + 45.0) % 90.0 - 45.0
    nearest = np.rint(deg / 90.0).astype(int) % 4
    counts = np.bincount(nearest, minlength=4)
    quadrant = int(np.argmax(counts))
    signed = quadrant * 90
    if quadrant == 3:
        signed = -90
    return {'window': [int(start), int(stop)],
            'true_angular_error_rms_deg': float(np.sqrt(np.mean(deg**2))),
            'modulo90_residual_rms_deg': float(np.sqrt(np.mean(folded**2))),
            'quadrant_offset_deg': int(quadrant * 90),
            'signed_offset_deg': int(signed),
            'quadrant_stability': float(counts[quadrant] / len(deg))}


def classify(metrics):
    if (metrics['modulo90_residual_rms_deg'] <= LOCK_RESIDUAL_MAX_DEG
            and metrics['quadrant_stability'] >= LOCK_STABILITY_MIN):
        return TRUE_LOCK if metrics['quadrant_offset_deg'] == 0 else ADJACENT_LOCK
    return UNLOCKED


def run_case(phase_deg, cfo, gains):
    ref = reference(phase_deg, cfo)
    _, phases = sync_fixed.costas(quantize(symbols() * np.exp(1j * ref)),
                                  sync_fixed.costas_gains(*gains))
    error = error_degrees(phases, ref)
    windows = [window_metrics(error, start, stop) for start, stop in WINDOWS]
    classes = [classify(m) for m in windows]
    offsets = [m['quadrant_offset_deg'] for m in windows]
    # A classification counts only when both non-overlapping windows agree on
    # class and quadrant offset; anything else is instability, hence unlocked.
    final = classes[0] if classes[0] == classes[1] and (classes[0] == UNLOCKED
                                                        or offsets[0] == offsets[1]) else UNLOCKED
    return {'phase_deg': phase_deg, 'cfo_rad_per_sample': cfo,
            'gains': list(gains), 'enabled': gains != DISABLED_GAINS,
            'windows': windows, 'classification': final,
            'quadrant_offset_deg': offsets[1] if final != UNLOCKED else None,
            'signed_offset_deg': windows[1]['signed_offset_deg'] if final != UNLOCKED else None}


def run_grid():
    cases = []
    for phase_deg in PHASES_DEG:
        for cfo in CFOS:
            enabled = run_case(phase_deg, cfo, GAINS)
            disabled = run_case(phase_deg, cfo, DISABLED_GAINS)
            cases.append({'phase_deg': phase_deg, 'cfo_rad_per_sample': cfo,
                          'enabled': enabled, 'disabled': disabled})
    return cases


def evaluate(cases):
    failures = []
    all_three = {TRUE_LOCK, ADJACENT_LOCK, UNLOCKED}
    keys = [(case['phase_deg'], case['cfo_rad_per_sample']) for case in cases]
    if len(keys) != len(EXPECTED) or set(keys) != set(EXPECTED):
        failures.append('the complete grid is required exactly once per point')
    for case in cases:
        key = case['phase_deg'], case['cfo_rad_per_sample']
        if key not in EXPECTED:
            failures.append(f'{key}: unexpected grid point')
            continue
        for state in ('enabled', 'disabled'):
            result = case[state]
            classes = [classify(m) for m in result['windows']]
            offsets = [m['quadrant_offset_deg'] for m in result['windows']]
            if len(set(classes)) > 1 or (classes[0] != UNLOCKED and offsets[0] != offsets[1]):
                failures.append(f"{key} {state}: windows disagree, classed {result['classification']}")
            recomputed = classes[0] if len(set(classes)) == 1 and (classes[0] == UNLOCKED
                                        or offsets[0] == offsets[1]) else UNLOCKED
            if result['classification'] != recomputed:
                failures.append(f'{key} {state}: classification disagrees with window metrics')
            if recomputed != UNLOCKED and result['quadrant_offset_deg'] != offsets[0]:
                failures.append(f'{key} {state}: quadrant offset disagrees with window metrics')
        expected_class, expected_offset = EXPECTED[key]
        enabled, disabled = case['enabled'], case['disabled']
        if enabled['classification'] != expected_class:
            failures.append(f"{key} enabled: classification {enabled['classification']}, expected {expected_class}")
        if expected_offset is not None and enabled['quadrant_offset_deg'] != expected_offset:
            failures.append(f"{key} enabled: quadrant offset {enabled['quadrant_offset_deg']}, expected {expected_offset}")
        if expected_class == UNLOCKED and disabled['classification'] != UNLOCKED:
            failures.append(f"{key} disabled: expected unlocked control")
        if expected_class != UNLOCKED and key != (0, 0.0):
            # Control on identical inputs must not track: no locked disabled case
            # and a clearly non-zero residual while the loop is off. The single
            # degenerate grid point (0 degrees, 0 rad/sample) has a constant zero
            # reference, so the loop being off there is not counter-evidence.
            if disabled['classification'] != UNLOCKED or \
                    min(m['modulo90_residual_rms_deg'] for m in disabled['windows']) < CONTROL_RESIDUAL_MIN_DEG:
                failures.append(f"{key} disabled: control tracks the carrier it should not")
            if max(m['modulo90_residual_rms_deg'] for m in enabled['windows']) > 1.0:
                failures.append(f"{key} enabled: residual above the 1 degree lock floor")
    if not all(cls in {case['enabled']['classification'] for case in cases} for cls in all_three):
        failures.append('the grid did not exercise all three classifications')
    locked = [case for case in cases if case['enabled']['classification'] != UNLOCKED]
    if not any(case['enabled']['quadrant_offset_deg'] == 180 for case in locked):
        failures.append('no adjacent lock with an explicit 180 degree offset was observed')
    if len(set(WINDOWS)) != 2 or WINDOWS[0][1] != WINDOWS[1][0] or WINDOWS[1][1] > N:
        failures.append('final windows must be two non-overlapping windows inside the stream')
    return failures


def parameters():
    return {'stream': {'samples': N, 'modulation': 'QPSK', 'seed': SEED,
                       'reference': 'phase_deg*pi/180 + cfo*n rad'},
            'grid': {'phase_deg': list(PHASES_DEG), 'cfo_rad_per_sample': list(CFOS),
                     'note': 'finite discrete grid, not the complete acquisition region'},
            'gains': {'enabled': list(GAINS), 'disabled': list(DISABLED_GAINS)},
            'windows': [list(w) for w in WINDOWS],
            'thresholds': {'lock_residual_max_deg': LOCK_RESIDUAL_MAX_DEG,
                           'lock_stability_min': LOCK_STABILITY_MIN,
                           'control_residual_min_deg': CONTROL_RESIDUAL_MIN_DEG},
            'classifications': [TRUE_LOCK, ADJACENT_LOCK, UNLOCKED],
            'expected': [{'phase_deg': p, 'cfo_rad_per_sample': c,
                          'classification': cls, 'quadrant_offset_deg': off}
                         for (p, c), (cls, off) in EXPECTED.items()]}


def main():
    require_unoptimized()
    evidence = begin()
    try:
        cases = run_grid()
        failures = evaluate(cases)
        payload = {'parameters': parameters(), 'rtl_verified': False,
                   'classes_observed': sorted({case['enabled']['classification'] for case in cases}),
                   'cases': cases, 'failures': failures,
                   'status': 'PASS' if not failures else 'FAIL'}
        result = dict(finish(evidence), **payload)
    except Exception as exc:
        result = dict(evidence, status='FAIL', failures=[f'unexpected error: {exc}'])
    write_json(TARGET, result)
    print(json.dumps(result, indent=2))
    if result['status'] == 'PASS':
        print(f"PASS COSTAS ACQUISITION: {len(result['cases'])} grid points, "
              f"classes {result['classes_observed']}", file=sys.stderr)
        return 0
    print(f"FAIL COSTAS ACQUISITION: {result['failures']}", file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
