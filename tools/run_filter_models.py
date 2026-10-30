#!/usr/bin/env python3
"""Numerical acceptance of CIC compensation and rational Python models only."""
import argparse
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import sys
import unittest

import numpy as np
from scipy import signal

from regression_evidence import ROOT, begin, digest, finish, write_json

sys.path.insert(0, str(ROOT / 'common/python'))
import cic_compensation as comp
import cic_reference
import rational_model as rat

RATIOS = [(5, 3), (3, 5), (12, 5), (1, 2), (2, 1), (1, 1), (2, 7), (1, 32), (32, 1)]


def equal(actual, expected):
    if list(actual) != list(expected):
        raise RuntimeError('[NUMERIC] output disagreement')


def qround(value, divisor=131072, width=18):
    return max(-(1 << (width - 1)), min((1 << (width - 1)) - 1,
               math.floor(Fraction(int(value), divisor) + Fraction(1, 2))))


def independent_metrics(taps, rate, stages):
    frequency = np.linspace(0, .5, 8193)
    kernel = np.asarray(cic_reference.boxcar_kernel(rate, stages), dtype=float)
    kernel /= rate ** stages
    cic = abs(signal.freqz(kernel, worN=2 * np.pi * frequency / rate)[1])
    fir = abs(signal.freqz(taps, worN=2 * np.pi * frequency)[1])
    pb, sb = frequency <= .16, frequency >= .32
    db = lambda v: 20 * np.log10(np.maximum(v, 1e-300))
    cascade = db(cic * fir)
    return dict(dc_gain=float(sum(taps)), passband_ripple_db=float(np.ptp(cascade[pb])),
        passband_max_error_db=float(max(abs(cascade[pb]))),
        uncompensated_droop_db=float(max(abs(db(cic[pb])))),
        fir_stopband_db=float(max(db(fir[sb]))),
        cascade_stopband_db=float(max(db(cic[sb] * fir[sb]))))


def quality(metrics):
    if (abs(metrics['dc_gain'] - 1) > 1e-12 or metrics['passband_ripple_db'] > .05
            or metrics['passband_max_error_db'] > .05 or metrics['fir_stopband_db'] > -50):
        raise RuntimeError('[QUALITY] frozen compensation budget failed')


def cascade_reference(samples, rate, stages, taps, clipping=None):
    raw = cic_reference.decimate_reference(samples, rate, stages)
    normalized = [(qround(a, rate ** stages), qround(b, rate ** stages)) for a, b in raw]
    out = []
    for n in range(len(normalized) + len(taps) - 1):
        sums = [sum(taps[j][0] * normalized[n - j][ch] for j in range(len(taps))
                    if 0 <= n - j < len(normalized)) for ch in (0, 1)]
        if clipping is not None:
            clipping[0] += sum(not -131072 <= math.floor(Fraction(v, 131072) + Fraction(1, 2)) <= 131071
                               for v in sums)
        out.append(tuple(qround(v) for v in sums))
    return out


def compensation_sweep():
    rows, words = [], 0
    rng = np.random.default_rng(243490)
    for rate in (4, 10, 32):
        for stages in (3, 5):
            for length in (31, 63):
                h = comp.design(rate, stages, numtaps=length)
                qtaps = comp.quantize(h)
                if sum(a for a, _ in qtaps) != 131072 or any(b for _, b in qtaps):
                    raise RuntimeError('[NUMERIC] invalid Q17 export')
                measured = {}
                for name, taps in [('floating', h), ('q17', np.array([a for a, _ in qtaps]) / 131072)]:
                    m = independent_metrics(taps, rate, stages)
                    quality(m)
                    claimed = comp.metrics(taps, rate, stages)
                    if any(abs(m[key] - claimed[key]) > 1e-4 for key in m):
                        raise RuntimeError('[NUMERIC] reported response metrics disagree with SciPy')
                    measured[name] = m
                diagnostics = []
                for name, values in [('random', rng.integers(-8000, 8001, (rate * 48, 2)).tolist()),
                                     ('full_scale_dc', [(131071, -131072)] * (rate * 16))]:
                    actual = comp.cascade_fixed(values, rate, stages, qtaps)
                    clipping = [0]
                    expected = cascade_reference(values, rate, stages, qtaps, clipping)
                    equal(actual, expected)
                    words += len(actual)
                    diagnostics.append(dict(signal=name, output_words=len(actual),
                        clipped_components=clipping[0], exact=True))
                # A post-decimation FIR multiplies both already-folded tones
                # by the same response. It cannot change their alias/base ratio.
                kernel = np.asarray(cic_reference.boxcar_kernel(rate, stages), dtype=float) / rate ** stages
                gains = abs(signal.freqz(kernel, worN=2 * np.pi * np.array([.1, 1.1]) / rate)[1])
                fir_gain = abs(signal.freqz(h, worN=[2 * np.pi * .1])[1][0])
                before = float(gains[1] / gains[0])
                after = float((gains[1] * fir_gain) / (gains[0] * fir_gain))
                if abs(before - after) > 1e-14:
                    raise RuntimeError('Folded-alias invariant failed')
                rows.append(dict(rate=rate, stages=stages, delay=1, numtaps=length,
                    metrics=measured, folded_alias_amplitude_ratio=before,
                    fixed_cascade=diagnostics,
                    note='Output FIR does not undo already-folded aliases'))
    return rows, words


def explicit_resample(values, up, down, taps, tail):
    """SciPy's minimal-support output padded for the documented N*P convention."""
    if not len(values):
        return np.array([], dtype=complex)
    count = (len(values) * up + (len(taps) - 1 if tail else 0) + down - 1) // down
    y = signal.upfirdn(taps, np.asarray(values, dtype=complex), up=up, down=down)
    return np.pad(y, (0, max(0, count - len(y))))[:count]


def rational_sweep():
    rows, float_words, fixed_words = [], 0, 0
    rng = np.random.default_rng(532127)
    for up, down in RATIOS:
        for length in sorted({1, max(1, up - 1), up + 1, 17, 63}):
            taps = rng.integers(-30000, 30001, length).tolist()
            # Every partial integer sum is below 2^53, so the independent
            # SciPy double convolution is exact for this raw-integer matrix.
            if sum(abs(v) for v in taps) * 131072 >= 2 ** 53:
                raise RuntimeError('Reference integer exactness bound exceeded')
            signals = dict(empty=[], singleton=[(131071, -131072)],
                short=[(7, -11), (-13, 17)],
                random=rng.integers(-131072, 131072, (19, 2)).tolist(),
                dc=[(8192, -4096)] * 32,
                alternating=[(131071, -131072) if k % 2 else (-131072, 131071) for k in range(37)])
            for name, values in signals.items():
                complex_values = [complex(*v) for v in values]
                for tail in (False, True):
                    expected = explicit_resample(complex_values, up, down, np.asarray(taps) / 131072, tail)
                    actual = np.asarray(rat.resample_float(complex_values, up, down,
                                           np.asarray(taps) / 131072, tail=tail), dtype=complex)
                    if actual.shape != expected.shape or not np.allclose(actual, expected, atol=1e-9, rtol=2e-13):
                        raise RuntimeError('[NUMERIC] rational float disagreement with SciPy')
                    raw = explicit_resample(complex_values, up, down, taps, tail)
                    if any(z.real != round(z.real) or z.imag != round(z.imag) for z in raw):
                        raise RuntimeError('Integer reference lost exactness')
                    fixed_expected = [(qround(round(z.real)), qround(round(z.imag))) for z in raw]
                    fixed_actual = rat.resample_fixed(values, up, down, taps, tail=tail)
                    equal(fixed_actual, fixed_expected)
                    float_words += len(actual)
                    fixed_words += len(fixed_actual)
                    rows.append(dict(up=up, down=down, taps=length, signal=name, tail=tail,
                        output_words=len(actual), float_max_error=float(np.max(abs(actual - expected), initial=0)),
                        exact_fixed=True, accumulator_width=rat.accumulator_width(taps, up)))
    return rows, float_words, fixed_words


def lowpass_profiles():
    """Caller-supplied anti-image/alias prototypes, not a new filter-design API."""
    rows = []
    for up, down in RATIOS:
        length = 24 * max(up, down) + 1
        taps = up * signal.firwin(length, .45 / max(up, down), fs=1, window='hamming')
        qtaps = np.floor(taps * 131072 + .5).astype(int)
        qtaps[length // 2] += up * 131072 - int(sum(qtaps))
        if np.any(qtaps < -131072) or np.any(qtaps > 131071):
            raise RuntimeError('Low-pass profile coefficient out of range')
        frequency = .025 * min(1, up / down)
        n = np.arange(2048)
        waveform = np.exp(2j * np.pi * frequency * n)
        actual = np.asarray(rat.resample_float(waveform, up, down, taps, tail=False))
        expected = explicit_resample(waveform, up, down, taps, False)
        if not np.allclose(actual, expected, atol=1e-10, rtol=1e-12):
            raise RuntimeError('[NUMERIC] anti-alias prototype float mismatch')
        k = np.arange(len(actual))
        phase = np.exp(2j * np.pi * frequency * (k * down - length // 2) / up)
        steady = k * down >= length - 1
        gain_db = float(20 * np.log10(abs(np.mean(actual[steady] / phase[steady]))))
        if abs(gain_db) > .1:
            raise RuntimeError('[QUALITY] low-pass tone gain error')
        grid = np.linspace(0, .5, 8193)
        mask = grid >= .55 / max(up, down)
        stop = None
        if np.any(mask):
            response = abs(signal.freqz(qtaps / 131072, worN=2 * np.pi * grid)[1]) / up
            stop = float(max(20 * np.log10(np.maximum(response[mask], 1e-300))))
            if stop > -50:
                raise RuntimeError('[QUALITY] quantized low-pass stopband failed')
        iq = [(int(round(z.real * 16384)), int(round(z.imag * 16384))) for z in waveform]
        raw = explicit_resample([complex(*z) for z in iq], up, down, qtaps, False)
        expected_fixed = [(qround(round(z.real)), qround(round(z.imag))) for z in raw]
        equal(rat.resample_fixed(iq, up, down, qtaps, tail=False), expected_fixed)
        rows.append(dict(up=up, down=down, taps=length, gain_db=gain_db,
            q17_stopband_db=stop, output_words=len(actual), exact_fixed=True,
            input_tone_cycles_per_sample=frequency))
    return rows


def negatives():
    controls = []
    try:
        quality(independent_metrics([0] * 15 + [1] + [0] * 15, 10, 5))
    except RuntimeError as exc:
        if '[QUALITY]' not in str(exc):raise
        controls.append(dict(tag='QUALITY', fault='bypass compensation', rejected=True))
    else:
        raise RuntimeError('Bad filter escaped the quality gate')
    gold = rat.resample_fixed([(131071, -131072)], 3, 5, [65536])
    bad = list(gold)
    bad[0] = (bad[0][0] + 1, bad[0][1])
    try:
        equal(bad, gold)
    except RuntimeError as exc:
        if '[NUMERIC]' not in str(exc):raise
        controls.append(dict(tag='NUMERIC', fault='corrupted rational output', rejected=True))
    else:
        raise RuntimeError('Corrupted output escaped numeric comparison')
    return controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/filter_models/results.json')
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError('Run verification without -O')
    target = args.output.resolve()
    if target.exists():
        raise RuntimeError('Use a fresh output path')
    evidence = begin()
    write_json(target, dict(status='RUNNING', **evidence))
    rtl_before = {str(p.relative_to(ROOT)):digest(p) for p in (ROOT / 'rtl').rglob('*') if p.is_file()}
    log = target.with_suffix('.unittest.log')
    try:
        spec = importlib.util.spec_from_file_location('filter_model_tests', ROOT / 'tests/test_filter_models.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with log.open('w') as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(module))
        if not result.wasSuccessful() or not result.testsRun:
            raise RuntimeError('Independent tests failed: ' + str(log))
        compensation, cascade_words = compensation_sweep()
        rational, float_words, fixed_words = rational_sweep()
        lowpass = lowpass_profiles()
        controls = negatives()
        if any(digest(ROOT / name) != value for name, value in rtl_before.items()):
            raise RuntimeError('RTL changed during the models-only run')
        optional = ROOT / 'build/filter_model_agents_20261030'
        artifacts = [log]
        artifacts.extend(p for p in optional.glob('*/report.txt') if p.is_file())
        artifacts.extend(p for p in optional.glob('*/contract.txt') if p.is_file())
        artifacts.extend(p for p in optional.glob('logs/*.log') if p.is_file())
        write_json(target, dict(status='PASS', scope='CIC compensation and rational Python models only',
            python_tests=result.testsRun, compensation_profiles=len(compensation),
            cascade_output_words=cascade_words, rational_cases=len(rational),
            rational_numeric_cases=2 * len(rational), rational_float_words=float_words,
            rational_fixed_words=fixed_words, compensation=compensation, rational=rational,
            lowpass_profiles=lowpass,
            negative_controls=controls, rtl_files_unchanged=len(rtl_before),
            **finish(evidence, artifacts)))
        print(f'PASS filter models: {result.testsRun} tests; {len(compensation)} CIC-comp profiles; '
              f'{len(rational)} rational cases; {fixed_words} exact fixed words')
    except Exception as exc:
        write_json(target, dict(status='FAIL', error=f'{type(exc).__name__}: {exc}', **evidence))
        raise


if __name__ == '__main__':
    main()
