#!/usr/bin/env python3
"""Full fixed Gardner trajectories against an independently evolving floating loop.

AWGN is injected at the loop input, after QPSK RRC shaping, matched filtering and
cubic delay. These deterministic tracking cases do not establish an acquisition
region or model noise before the matched filter. Both algorithms receive the
same quantized samples; transmitted labels are used only to score outputs.
"""
import argparse
import math
from pathlib import Path
import sys

import numpy as np

from regression_evidence import ROOT, begin, finish, require_unoptimized, write_json

sys.path.insert(0, str(ROOT / 'common/python'))
import sync_fixed
from modem_core import cubic, load_config, rrc_taps, transmit
from research_core import run as floating_run

SPS = 8
COUNT = 900
SETTLE = 300
POSITION = 32
GAINS = (.1, .00005)
SEED = 41
CASES = (('quiet_delay_1.25', 1.25, None), ('quiet_delay_2.5', 2.5, None),
         ('awgn_30db', 1.25, 30), ('awgn_20db', 1.25, 20), ('awgn_10db', 1.25, 10))
SCOPE = ('Complete Gardner fixed and independent floating trajectories on identical Q15 inputs; '
         'loop-input AWGN after matched filtering/cubic delay; outputs scored from symbol 300 '
         'through 899 without truth alignment, rotation or gain compensation. Deterministic '
         'tracking evidence, not a general acquisition region or final width selection.')


def quantize(wave):
    wave = np.asarray(wave, complex)
    if wave.ndim != 1:
        raise ValueError('One dimensional complex input samples are required')
    components = np.column_stack((np.real(wave), np.imag(wave)))
    if components.ndim != 2 or not len(components) or not np.all(np.isfinite(components)):
        raise ValueError('Finite nonempty complex input samples are required')
    raw = np.rint(components * 32768)
    lower, upper = -131072, 131071
    stats = dict(component_evaluations=int(raw.size),
                 positive_clamps=int(np.count_nonzero(raw > upper)),
                 negative_clamps=int(np.count_nonzero(raw < lower)))
    stats['total_clamps'] = stats['positive_clamps'] + stats['negative_clamps']
    integer = np.clip(raw, lower, upper).astype(np.int64)
    rows = [tuple(map(int, row)) for row in integer]
    return rows, integer[:, 0] / 32768 + 1j * integer[:, 1] / 32768, stats


def nearest_labels(values, constellation):
    """Use the declared constellation directly; no transform fitted to transmitted truth."""
    values, constellation = np.asarray(values, complex), np.asarray(constellation, complex)
    if values.ndim != 1 or constellation.ndim != 1 or not len(constellation):
        raise ValueError('One dimensional outputs and constellation are required')
    return np.argmin(abs(values[:, None] - constellation[None, :]) ** 2, axis=1)


def score_outputs(values, labels, constellation):
    values, labels = np.asarray(values, complex), np.asarray(labels, int)
    if values.shape != labels.shape or not len(values) or not np.all(np.isfinite(values)):
        raise ValueError('Finite outputs matching the scored label count are required')
    symbols = np.asarray(constellation, complex)[labels]
    errors = int(np.count_nonzero(nearest_labels(values, constellation) != labels))
    return dict(symbols=len(labels), symbol_errors=errors, ser=errors / len(labels),
                symbol_rms_error=float(np.sqrt(np.mean(abs(values - symbols) ** 2))))


def run_loops(rows, quantized, gains):
    """Truth-free receiver path: each loop computes its own positions from the same input."""
    values, positions = sync_fixed.timing(
        rows, SPS, COUNT, sync_fixed.timing_gains(POSITION, *gains))
    fixed = np.asarray(values, float) @ [1, 1j] / 32768
    fixed_positions = np.asarray(positions, float) / 65536
    reference = floating_run('timing', [SPS, COUNT, POSITION, *gains], quantized)
    return fixed, fixed_positions, reference[:COUNT], reference[COUNT:].real


def compare_loops(outputs, labels, constellation):
    fixed, positions, reference, reference_positions = outputs
    streams = (fixed, positions, reference, reference_positions)
    if any(np.shape(a) != (COUNT,) or not np.all(np.isfinite(a)) for a in streams):
        raise RuntimeError('Invalid full timing-loop output or trajectory')
    window = slice(SETTLE, COUNT)
    actual, expected = fixed[window], reference[window]
    error_power = float(np.mean(abs(actual - expected) ** 2))
    reference_power = float(np.mean(abs(expected) ** 2))
    delta = positions[window] - reference_positions[window]
    return dict(fixed=score_outputs(actual, labels[window], constellation),
                floating=score_outputs(expected, labels[window], constellation),
                output_error_power=error_power, floating_output_power=reference_power,
                output_sqnr_db=(10 * math.log10(reference_power / error_power)
                                if error_power and reference_power else None),
                output_exact=error_power == 0,
                max_complex_output_error=float(np.max(abs(actual - expected))),
                position_rms_discrepancy_samples=float(np.sqrt(np.mean(delta ** 2))),
                position_max_discrepancy_samples=float(np.max(abs(delta))))


def report():
    cfg = load_config(ROOT / 'modems/qpsk_script_costas/config.json')
    labels = np.random.default_rng(SEED).integers(0, cfg['order'], COUNT + 150)
    constellation = np.asarray(cfg['constellation']) @ [1, 1j]
    matched = np.convolve(transmit(cfg, labels)['waveform'],
                          rrc_taps(cfg['sps'], cfg['rrc_order'], cfg['rolloff']))
    records = []
    # Same physically indexed loop-input interval for reference signal and noise energies.
    energy_window = slice(POSITION, POSITION + COUNT * SPS)
    for index, (name, delay, snr) in enumerate(CASES):
        clean = cubic(matched, np.arange(len(matched)) - delay)
        signal_energy = float(np.sum(abs(clean[energy_window]) ** 2))
        signal_power = signal_energy / (COUNT * SPS)
        noise = np.zeros(len(clean), complex)
        noise_seed = SEED + 1000 + index
        if snr is not None:
            rng = np.random.default_rng(noise_seed)
            # Complex total noise power = signal power / 10^(SNR/10); half in I and half in Q.
            sigma = math.sqrt(signal_power / 10 ** (snr / 10) / 2)
            noise = sigma * (rng.standard_normal(len(clean)) + 1j * rng.standard_normal(len(clean)))
        noise_energy = float(np.sum(abs(noise[energy_window]) ** 2))
        rows, quantized, clamps = quantize(clean + noise)
        enabled = compare_loops(run_loops(rows, quantized, GAINS), labels, constellation)
        disabled = compare_loops(run_loops(rows, quantized, (0, 0)), labels, constellation)
        records.append(dict(case=name, label_seed=SEED, noise_seed=noise_seed, delay_samples=delay,
                            requested_snr_db=snr, measured_snr_db=(10 * math.log10(signal_energy / noise_energy)
                                                                 if noise_energy else None),
                            noise_injection='after matched filter and cubic delay, before quantization',
                            noise_model='circular complex Gaussian, equal independent I/Q powers',
                            energy_sample_start=POSITION, energy_sample_stop=POSITION + COUNT * SPS,
                            signal_energy=signal_energy, complex_noise_energy=noise_energy,
                            signal_power=signal_power, complex_noise_power=noise_energy / (COUNT * SPS),
                            input_samples=len(rows), input_clamps=clamps,
                            scored_symbol_start=SETTLE, scored_symbol_stop=COUNT,
                            enabled_gains=list(GAINS), disabled_gains=[0, 0],
                            enabled=enabled, disabled=disabled))
    return records


def check_acceptance(records):
    if {record.get('case') for record in records} != {case[0] for case in CASES} or len(records) != len(CASES):
        raise RuntimeError('Incomplete timing precision scenario coverage')
    for record in records:
        name = record['case']
        if record['input_clamps']['total_clamps']:
            raise RuntimeError(f'{name}: nominal loop-input samples clipped')
        enabled = record['enabled']
        sqnr = enabled['output_sqnr_db']
        sqnr_ok = ((enabled['output_exact'] and enabled['output_error_power'] == 0)
                   or (sqnr is not None and math.isfinite(sqnr) and sqnr >= 35))
        if (not sqnr_ok
                or not math.isfinite(enabled['position_rms_discrepancy_samples'])
                or enabled['position_rms_discrepancy_samples'] >= .05):
            raise RuntimeError(f'{name}: fixed and floating trajectories diverged')
        for mode in ('enabled', 'disabled'):
            for implementation in ('fixed', 'floating'):
                metrics = record[mode][implementation]
                if (metrics['symbols'] != COUNT - SETTLE or not math.isfinite(metrics['symbol_rms_error'])
                        or not 0 <= metrics['ser'] <= 1):
                    raise RuntimeError(f'{name}: invalid symbol metrics')
        if record['requested_snr_db'] is None:
            for implementation in ('fixed', 'floating'):
                on, off = enabled[implementation], record['disabled'][implementation]
                if (on['symbol_errors'] != 0 or on['symbol_rms_error'] >= .025
                        or on['symbol_rms_error'] >= .5 * off['symbol_rms_error']):
                    raise RuntimeError(f'{name}: quiet tracking or disabled-loop control failed')
        elif (not math.isfinite(record['measured_snr_db'])
              or abs(record['measured_snr_db'] - record['requested_snr_db']) > .5
              or record['complex_noise_energy'] <= 0):
            raise RuntimeError(f'{name}: AWGN energy or SNR evidence is invalid')


def main(argv=None):
    require_unoptimized()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/rtl/timing_precision/results.json')
    args = parser.parse_args(argv)
    evidence = begin()
    write_json(args.output, dict(evidence, status='RUNNING', scope=SCOPE))
    records = []
    try:
        records = report()
        check_acceptance(records)
        completed = finish(evidence)
    except Exception as exc:
        try:
            completed = finish(evidence)
        except RuntimeError as snapshot_error:
            completed = dict(evidence, source_snapshot_error=str(snapshot_error))
        write_json(args.output, dict(completed, status='FAIL', scope=SCOPE,
                                    records=records, error=str(exc)))
        raise
    write_json(args.output, dict(completed, status='PASS', scope=SCOPE, records=records))
    for record in records:
        metrics = record['enabled']
        sqnr='exact' if metrics['output_exact'] else f"{metrics['output_sqnr_db']:.2f} dB"
        print(f"PASS timing {record['case']}: SQNR {sqnr}; "
              f"position RMS {metrics['position_rms_discrepancy_samples']:.6f} samples; "
              f"SER fixed/float {metrics['fixed']['ser']:.4g}/{metrics['floating']['ser']:.4g}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
