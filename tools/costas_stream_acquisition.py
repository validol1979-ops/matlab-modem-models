"""Reproducible finite-grid QPSK acquisition study of the delayed integer Costas model.

This is a functional model experiment, not an RTL, physical timing, or capture-range proof.
Each sample is a new independent ideal QPSK symbol: no pulse shaping or timing recovery.
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import sync_fixed

DELAY = 10
WINDOW = 128
LENGTH = 3072
QUARTER = math.pi / 2


def measure(phases, carrier, window=WINDOW):
    """Score full windows against known carrier; branch changes are not exact slip counts.

    Good windows have mean absolute modulo-pi/2 error < .12 rad and 90th percentile < .30 rad.
    Two adjacent good windows define acquisition. Compare median unwrapped quadrant indices of
    successive good windows, including across failed windows, to flag an observed branch change.
    """
    if window < 2 or len(phases) != len(carrier) or len(phases) < 2 * window:
        raise ValueError('need equal-length phase sequences with at least two windows')
    phase = np.asarray(phases, dtype=float) * (2 * math.pi / 2**32)
    error = np.unwrap(np.asarray(carrier, dtype=float) - phase)
    folded = (error + QUARTER / 2) % QUARTER - QUARTER / 2
    good, branches, means = [], [], []
    for start in range(0, len(error) - window + 1, window):
        values = folded[start:start + window]
        mean = float(np.mean(np.abs(values)))
        good.append(mean < .12 and float(np.quantile(np.abs(values), .9)) < .30)
        means.append(mean)
        branches.append(int(np.rint(np.median(error[start:start + window]) / QUARTER)))
    acquired = next((i - 1 for i in range(1, len(good)) if good[i - 1] and good[i]), None)
    transitions = []
    if acquired is not None:
        previous = acquired
        for i in range(acquired + 1, len(good)):
            if good[i]:
                if branches[i] != branches[previous]:
                    transitions.append({'from_window': previous, 'to_window': i,
                                        'quadrant_delta': branches[i] - branches[previous],
                                        'intervening_bad_windows': i - previous - 1})
                previous = i
    return {'acquired_window': acquired, 'last_two_windows_good': all(good[-2:]),
            'bad_windows_after_acquisition': None if acquired is None else good[acquired:].count(False),
            'quadrant_changes': transitions, 'mean_abs_folded_last_window_rad': means[-1]}


def signal(initial_phase, rate, snr_db, seed, length=LENGTH):
    """Unit-power QPSK + complex AWGN; SNR is signal power / total complex noise power."""
    rng = np.random.default_rng(seed)
    labels = rng.integers(0, 4, length)
    constellation = np.array([1+1j, -1+1j, -1-1j, 1-1j]) / math.sqrt(2)
    carrier = initial_phase + rate * np.arange(length)
    wave = constellation[labels] * np.exp(1j * carrier)
    if snr_db is not None:
        sigma = math.sqrt(10**(-snr_db / 10) / 2)
        wave += sigma * (rng.standard_normal(length) + 1j * rng.standard_normal(length))
    scaled = np.rint(np.column_stack((wave.real, wave.imag)) * 32768)
    clipped = int(np.count_nonzero((scaled < -131072) | (scaled > 131071)))
    data = np.clip(scaled, -131072, 131071).astype(np.int64)
    return [tuple(map(int, pair)) for pair in data], carrier, clipped


def run_case(initial_phase, rate, snr_db, seed, gains=(.08, .001), length=LENGTH):
    data, carrier, clipped = signal(initial_phase, rate, snr_db, seed, length)
    _, phases = sync_fixed.costas_pipelined(data, sync_fixed.costas_gains(*gains), DELAY)
    return {'initial_phase_rad': initial_phase, 'rate_rad_per_sample': rate, 'snr_db': snr_db,
            'seed': seed, 'gains': list(gains), 'clipped_components': clipped,
            **measure(phases, carrier)}


def study():
    cases = [run_case(phase, rate, snr, seed)
             for phase in (-.6, 0., .6)
             for rate in (-.012, 0., .012)
             for snr in (None, 24., 12., 6.)
             for seed in (0, 1)]
    control = run_case(.6, .012, None, 0, gains=(0., 0.))
    return {'description': 'finite ideal-QPSK dense-input integer-model sweep; no RTL or timing claim',
            'samples': LENGTH, 'window': WINDOW, 'delay_advances': DELAY,
            'snr_definition': 'unit signal power / total complex AWGN power',
            'criteria': 'two adjacent windows: mean abs residual modulo pi/2 < .12 rad and p90 < .30 rad',
            'cases': cases, 'zero_gain_control': control}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True,
                        help='new JSON path; existing files are never overwritten')
    args = parser.parse_args()
    result = study()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
        handle.write('\n')
    print(f"wrote {len(result['cases'])} cases to {args.output}")


if __name__ == '__main__':
    main()
