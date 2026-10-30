#!/usr/bin/env python3
"""Empirical FFT/FIR precision and actual rounded preclamp ranges, Python only.

References use numpy FFT/convolve on the EXACT loaded integer input / 2**15.
FIR arithmetic uses loaded Q17 taps; a second reference retains ideal taps to
separate coefficient quantization. No separately generated reference noise.
Native FFT forward is fft(x)/N, inverse is N*ifft(x). Scaled/unscaled report
forms rescale those same native outputs AFTER the model; they are not new RTL
normalization modes. Clipping stress is separate from clean precision gates.
Observed signed widths cover only these finite fixtures, not all legal inputs.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
import fft_fixed as fft
import fir_fixed as fir
from sat_diag import SatTrace
from regression_evidence import begin, finish, write_json, require_unoptimized

SIZES = (4, 32, 128, 1024)
IN_WIDTH, FFT_WIDTH, FIR_WIDTH, SEED = 18, 20, 18, 123


def minimum_signed_bits(low, high):
    if not isinstance(low, int) or not isinstance(high, int) or low > high:
        raise ValueError('Ordered integer endpoints required')
    positive = high.bit_length()+1 if high >= 0 else 1
    negative = (-low-1).bit_length()+1 if low < 0 else 1
    return max(positive, negative)


class ObservedTrace(SatTrace):
    """Sample actual model.record arguments before the model's own output clamp."""
    def __init__(self, width, clamp):
        super().__init__(); self.width = width; self.clamp = clamp; self.ranges = {}

    def record(self, stage, value, limit, clamp='asym'):
        if clamp != self.clamp or limit != (1 << (self.width-1))-1:
            raise RuntimeError('Unexpected clamp format')
        value = int(value)
        previous = self.ranges.setdefault(stage, dict(min=value, max=value))
        previous['min'] = min(previous['min'], value); previous['max'] = max(previous['max'], value)
        return super().record(stage, value, limit, clamp)

    def report(self):
        stages = {}
        for name, observed in sorted(self.ranges.items()):
            bits = minimum_signed_bits(observed['min'], observed['max'])
            stages[name] = dict(observed, evaluations=self.evaluations[name],
                                events=dict(self.counts.get(name, dict(pos=0, neg=0))),
                                minimum_signed_bits_for_observed_range=bits,
                                observed_headroom_bits=self.width-bits)
        low = min(v['min'] for v in stages.values()); high = max(v['max'] for v in stages.values())
        bits = minimum_signed_bits(low, high)
        limit = (1 << (self.width-1))-1
        return dict(stages=stages, evaluations=sum(self.evaluations.values()), events=self.total(),
                    min=low, max=high, minimum_signed_bits_for_observed_range=bits,
                    observed_headroom_bits=self.width-bits, configured_width=self.width,
                    lower_rail=-limit if self.clamp == 'sym' else -limit-1, upper_rail=limit,
                    scope='Actual rounded preclamp Q15 values; finite-fixture empirical ranges, not a width guarantee.')


def as_complex(rows, fractional_bits=15):
    a = np.asarray(rows)
    if a.ndim != 2 or a.shape[1] != 2 or not len(a) or not np.issubdtype(a.dtype, np.integer):
        raise ValueError('Nonempty integer Nx2 array required')
    return (a[:, 0]+1j*a[:, 1])/2**fractional_bits


def metrics(actual, expected):
    a = np.asarray(actual); e = np.asarray(expected)
    if a.ndim != 1 or not len(a) or a.shape != e.shape or not np.all(np.isfinite(a)) or not np.all(np.isfinite(e)):
        raise ValueError('Precision arrays must be equally shaped nonempty finite vectors')
    power = float(np.mean(abs(e)**2)); mse = float(np.mean(abs(a-e)**2))
    if not np.isfinite(power) or not np.isfinite(mse) or power <= 0:
        raise ValueError('Finite positive reference energy required')
    evm = float(np.sqrt(mse/power))
    return dict(samples=len(a), signal_power=power, error_power=mse, exact_match=mse == 0,
                sqnr_db=None if mse == 0 else float(10*np.log10(power/mse)),
                normalized_rms_evm=evm, rms_evm_percent=100*evm,
                rms_complex_error=float(np.sqrt(mse)), max_complex_error=float(np.max(abs(a-e))))


def digest_rows(rows):
    return hashlib.sha256(np.asarray(rows, dtype='<i8').tobytes()).hexdigest()


def fft_input(n, direction, fixture):
    inverse = direction == 'inverse'
    if direction not in ('forward', 'inverse') or n not in SIZES:
        raise ValueError('Unsupported FFT profile')
    if fixture == 'random':
        scale = 60000 if not inverse else max(1, int(60000/np.sqrt(n)))
        rows = np.random.default_rng(SEED+n).integers(-scale, scale+1, (n, 2))
    elif fixture == 'tone':
        amplitude = 60000 if not inverse else max(1, 60000//n)
        k = 1 if n == 4 else 3
        wave = amplitude*np.exp(2j*np.pi*k*np.arange(n)/n)
        rows = np.rint(np.c_[wave.real, wave.imag]).astype(np.int64)
    elif fixture == 'impulse':
        rows = np.zeros((n, 2), dtype=np.int64); rows[0] = [65536, -32768]
    elif fixture in ('extreme_positive', 'extreme_negative') and inverse:
        value = (131071, -131072) if fixture == 'extreme_positive' else (-131072, 131071)
        rows = np.tile(value, (n, 1))
    else:
        raise ValueError('Unknown FFT fixture')
    if np.any((rows < -(1 << (IN_WIDTH-1))) | (rows >= (1 << (IN_WIDTH-1)))):
        raise ValueError('Fixture input outside signed width')
    return [tuple(map(int, row)) for row in rows]


def fft_case(n, direction, fixture):
    rows = fft_input(n, direction, fixture); inverse = direction == 'inverse'
    trace = ObservedTrace(FFT_WIDTH, 'sym')
    output = fft.transform(rows, inverse, IN_WIDTH, FFT_WIDTH, stats=trace)
    if output != fft.transform(rows, inverse, IN_WIDTH, FFT_WIDTH):
        raise RuntimeError('FFT range instrumentation changed integer results')
    wave = as_complex(rows); actual = as_complex(output)
    unscaled = np.fft.ifft(wave)*n if inverse else np.fft.fft(wave)
    native = unscaled if inverse else unscaled/n
    factors = dict(scaled=1/n if inverse else 1., unscaled=1. if inverse else n)
    forms = {name: dict(post_native_factor=factor, metrics=metrics(actual*factor, unscaled/n if name == 'scaled' else unscaled))
             for name, factor in factors.items()}
    return dict(kind='fft', n=n, direction=direction, fixture=fixture,
                classification='clipping_stress' if fixture.startswith('extreme') else 'clean',
                input_sha256=digest_rows(rows), output_sha256=digest_rows(output), seed=SEED+n,
                native_convention='N*ifft' if inverse else 'fft/N', native_metrics=metrics(actual, native),
                representations=forms, preclamp=trace.report())


def fir_fixture(fixture):
    rng = np.random.default_rng(SEED)
    if fixture == 'impulse':
        rows = [(32768, -16384)]+[(0, 0)]*31
        desired = np.array([.25, .5, .25], complex)
    elif fixture == 'wsinc':
        rows = [tuple(map(int, row)) for row in rng.integers(-12000, 12001, (256, 2))]
        t = np.arange(41)-20
        desired = 2*.12*np.sinc(2*.12*t)*np.hamming(41)
        desired = desired/np.sum(desired)
    elif fixture == 'complex':
        rows = [tuple(map(int, row)) for row in rng.integers(-12000, 12001, (256, 2))]
        desired = (rng.normal(size=9)+1j*rng.normal(size=9))/8
    elif fixture == 'extreme':
        rows = [(131071, -131072)]*32+[(-131072, 131071)]*32
        desired = np.full(8, 131071/2**17, complex)
    else:
        raise ValueError('Unknown FIR fixture')
    taps = fir.quantize_taps(desired)
    return rows, taps, desired


def fir_case(fixture):
    rows, taps, desired = fir_fixture(fixture)
    trace = ObservedTrace(FIR_WIDTH, 'asym')
    output = fir.filter(rows, taps, stats=trace)
    if output != fir.filter(rows, taps):
        raise RuntimeError('FIR range instrumentation changed integer results')
    wave = as_complex(rows); loaded = as_complex(taps, 17); actual = as_complex(output)
    return dict(kind='fir', fixture=fixture, classification='clipping_stress' if fixture == 'extreme' else 'clean',
                input_sha256=digest_rows(rows), taps_sha256=digest_rows(taps), output_sha256=digest_rows(output),
                tap_count=len(taps), input_count=len(rows), seed=SEED,
                loaded_taps_metrics=metrics(actual, np.convolve(wave, loaded)),
                ideal_taps_metrics=metrics(actual, np.convolve(wave, desired)),
                coefficient_metrics=metrics(loaded, desired), preclamp=trace.report())


def check_records(records):
    expected = {('fft', n, direction, fixture) for n in SIZES for direction in ('forward', 'inverse')
                for fixture in ('random', 'tone', 'impulse')}
    expected |= {('fft', n, 'inverse', fixture) for n in SIZES for fixture in ('extreme_positive', 'extreme_negative')}
    expected |= {('fir', 0, '', fixture) for fixture in ('impulse', 'wsinc', 'complex', 'extreme')}
    actual = {(r['kind'], r.get('n', 0), r.get('direction', ''), r['fixture']) for r in records}
    checks = dict(complete_coverage=actual == expected and len(records) == len(expected))
    for row in records:
        key = f"{row['kind']}/{row.get('n', 0)}/{row.get('direction', '')}/{row['fixture']}"
        pre = row['preclamp']
        expected_evaluations = (2*row['n']*int(np.log2(row['n']))+(row['n'] if row['direction'] == 'inverse' else 0)) if row['kind'] == 'fft' else 2*(row['input_count']+row['tap_count']-1)
        checks[key+'/preclamp_evaluated'] = pre['evaluations'] == expected_evaluations
        if row['classification'] == 'clipping_stress':
            checks[key+'/actual_clipping'] = pre['events'] > 0
            continue
        checks[key+'/no_events'] = pre['events'] == 0
        if row['kind'] == 'fft':
            metric_ = row['native_metrics']
            minimum = 45 if row['direction'] == 'inverse' and row['fixture'] == 'tone' else 60
            checks[key+'/native_precision'] = metric_['exact_match'] or metric_['sqnr_db'] > minimum
            for name, form in row['representations'].items():
                checks[key+'/'+name+'_same_evm'] = bool(np.isclose(form['metrics']['normalized_rms_evm'], metric_['normalized_rms_evm'], rtol=1e-12, atol=1e-15))
            if row['fixture'] == 'impulse':
                checks[key+'/analytic_impulse_exact'] = metric_['exact_match']
        else:
            for mode in ('loaded_taps_metrics', 'ideal_taps_metrics'):
                metric_ = row[mode]
                checks[key+'/'+mode+'_precision'] = metric_['exact_match'] or metric_['sqnr_db'] > 70
    return checks


def report():
    records = [fft_case(n, direction, fixture) for n in SIZES for direction in ('forward', 'inverse') for fixture in ('random', 'tone', 'impulse')]
    records += [fft_case(n, 'inverse', fixture) for n in SIZES for fixture in ('extreme_positive', 'extreme_negative')]
    records += [fir_case(fixture) for fixture in ('impulse', 'wsinc', 'complex', 'extreme')]
    return dict(records=records, checks=check_records(records))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/rtl/fft_fir_precision/results.json')
    args = parser.parse_args(argv); evidence = begin()
    write_json(args.output, dict(evidence, status='RUNNING'))
    try:
        require_unoptimized(); data = report()
        status = 'PASS' if all(data['checks'].values()) else 'FAIL'
        result = dict(finish(evidence), status=status, **data,
                      parameters=dict(fft_sizes=SIZES, input_fractional_bits=15, fft_width=FFT_WIDTH,
                                      fir_width=FIR_WIDTH, fir_tap_fractional_bits=17, seed=SEED),
                      scope=__doc__, range_scope='Minimum signed bits represent only sampled rounded preclamp minima/maxima. Symmetric FFT clamp additionally excludes -2**(width-1); these observations are not a proof of width safety.',
                      metric_definition='SQNR=10log10(mean|reference|²/mean|error|²); normalized RMS EVM=sqrt(errorpower/referencepower). Stress references remain unclipped; stress distortion is not pure quantization noise.')
        write_json(args.output, result)
    except Exception as exc:
        write_json(args.output, dict(evidence, status='FAIL', error=f'{type(exc).__name__}: {exc}'))
        raise
    for row in data['records']:
        metric_ = row['native_metrics'] if row['kind'] == 'fft' else row['loaded_taps_metrics']
        print(f"{row['kind']}/{row.get('n', '')}/{row.get('direction', '')}/{row['fixture']}: SQNR={metric_['sqnr_db']} EVM={metric_['normalized_rms_evm']:.6g} events={row['preclamp']['events']} observed_bits={row['preclamp']['minimum_signed_bits_for_observed_range']}")
    if status != 'PASS':
        raise RuntimeError('FFT/FIR precision failed: '+', '.join(k for k, ok in data['checks'].items() if not ok))
    print('PASS FFT FIR precision')
    return result


if __name__ == '__main__':
    main()
