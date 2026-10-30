#!/usr/bin/env python3
"""Measured Costas arithmetic precision and raw symbol errors on known QPSK.

One sample per symbol, no pulse shaping/timing recovery. Es/N0 means complex
AWGN power relative to unit-energy symbols, before quantization. Both complete
loops receive the exact same Q15 waveform; the floating loop is research_core.
Phase histories are the phase used BEFORE the update for each sample. Raw SER
and true phase RMS never rotate, align or fit outputs using transmitted labels.
Modulo-90 phase RMS and quadrant histograms are diagnostics only. These cases
measure tracking for named inputs, not the complete acquisition range.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
import sync_fixed as fixed
import research_core
from regression_evidence import begin, finish, require_unoptimized, write_json

CONSTELLATION = np.array([1+1j, -1+1j, -1-1j, 1-1j])/np.sqrt(2)
DEFAULTS = dict(count=4096, steady_start=512, seed=17, noise_seed=33,
                phase_rad=.3, cfo_rad_per_symbol=.006, k1=.08, k2=.001)


def _vector(values, name, real=False):
    array = np.asarray(values)
    if array.ndim != 1 or array.size == 0:
        raise ValueError(name+' must be a nonempty one-dimensional array')
    if real and np.iscomplexobj(array):
        raise ValueError(name+' must be real')
    try:
        finite = np.all(np.isfinite(array))
    except TypeError as exc:
        raise ValueError(name+' must be numeric') from exc
    if not finite:
        raise ValueError(name+' must be finite')
    return array


def quantize(wave):
    """Signed 18-bit samples scaled by 2**15; count excursions before clipping."""
    wave = _vector(wave, 'waveform')
    unbounded = np.rint(np.c_[wave.real, wave.imag]*32768)
    clipped = int(np.count_nonzero((unbounded < -131072) | (unbounded > 131071)))
    rows = np.clip(unbounded, -131072, 131071).astype(np.int64)
    return [tuple(map(int, row)) for row in rows], clipped


def complex_of(rows):
    data = np.asarray(rows, dtype=np.int64)
    return (data[:, 0]+1j*data[:, 1])/32768


def waveform(esn0_db=None, **parameters):
    p = dict(DEFAULTS, **parameters)
    n = p['count']
    if (not isinstance(n, (int, np.integer)) or isinstance(n, (bool, np.bool_)) or n <= 0
            or not isinstance(p['steady_start'], (int, np.integer))
            or isinstance(p['steady_start'], (bool, np.bool_))):
        raise ValueError('count must be a positive integer and steady_start an integer')
    if not 0 <= p['steady_start'] < n:
        raise ValueError('The steady window must contain samples')
    for name, value in [(k, p[k]) for k in ('phase_rad', 'cfo_rad_per_symbol', 'k1', 'k2')] + [('esn0_db', esn0_db)]:
        if value is not None and (np.ndim(value) != 0 or np.iscomplexobj(value) or not np.isfinite(value)):
            raise ValueError(name+' must be a finite real scalar')
    labels = np.random.default_rng(p['seed']).integers(0, 4, n)
    phase = p['phase_rad']+p['cfo_rad_per_symbol']*np.arange(n)
    clean = CONSTELLATION[labels]*np.exp(1j*phase)
    rng = np.random.default_rng(p['noise_seed'])
    unit_noise = (rng.normal(size=n)+1j*rng.normal(size=n))/np.sqrt(2)
    noise = np.zeros(n, complex) if esn0_db is None else unit_noise*10**(-esn0_db/20)
    rows, clips = quantize(clean+noise)
    noise_power = float(np.mean(abs(noise)**2))
    signal = complex_of(rows)
    meta = dict(p, esn0_db=esn0_db, symbol_energy=1., noise_power=noise_power,
                measured_esn0_db=None if noise_power == 0 else float(-10*np.log10(noise_power)),
                input_rail_excursions=clips,
                input_sha256=hashlib.sha256(np.asarray(rows, dtype='<i8').tobytes()).hexdigest(),
                labels_sha256=hashlib.sha256(labels.astype('<i8').tobytes()).hexdigest())
    return rows, signal, labels, phase, meta


def run_loops(rows, k1=.08, k2=.001):
    signal = complex_of(rows)
    n = len(rows)
    result = {}
    for name, gains in [('enabled', (k1, k2)), ('disabled', (0., 0.))]:
        values, phases = fixed.costas(rows, fixed.costas_gains(*gains))
        reference = research_core.run('costas', gains, signal)
        if len(reference) != 2*n:
            raise RuntimeError('Unexpected floating Costas output/history length')
        result[name] = dict(fixed_output=complex_of(values),
                            fixed_phase=np.asarray(phases)*2*np.pi/2**32,
                            float_output=reference[:n], float_phase=reference[n:].real)
    return result


def sqnr_db(output, reference):
    output = _vector(output, 'output')
    reference = _vector(reference, 'reference')
    if output.shape != reference.shape:
        raise ValueError('SQNR arrays must have the same shape')
    power = float(np.mean(abs(reference)**2))
    error = float(np.mean(abs(np.asarray(output)-reference)**2))
    if power <= 0:
        raise ValueError('SQNR reference power must be positive')
    return dict(signal_power=power, error_power=error,
                sqnr_db=None if error == 0 else float(10*np.log10(power/error)),
                exact_match=error == 0)


def receiver_metrics(output, phases, labels, true_phase):
    output = _vector(output, 'output')
    phases = _vector(phases, 'phases', real=True)
    labels = _vector(labels, 'labels', real=True)
    true_phase = _vector(true_phase, 'true_phase', real=True)
    if not (output.shape == phases.shape == labels.shape == true_phase.shape):
        raise ValueError('Receiver arrays must have the same count')
    if not np.issubdtype(labels.dtype, np.integer) or np.any((labels < 0) | (labels > 3)):
        raise ValueError('Labels must be integers in 0..3')
    decisions = np.argmin(abs(output[:, None]-CONSTELLATION[None, :]), axis=1)
    count = len(labels)
    wrong = int(np.count_nonzero(decisions != labels))
    error = np.angle(np.exp(1j*(np.asarray(phases)-true_phase)))
    mod90 = (error+np.pi/4) % (np.pi/2)-np.pi/4
    quadrants = np.rint((error-mod90)/(np.pi/2)).astype(int) % 4
    histogram = [int(np.count_nonzero(quadrants == k)) for k in range(4)]
    return dict(symbol_count=count, symbol_errors=wrong, raw_ser=wrong/count,
                true_phase_rms_deg=float(np.degrees(np.sqrt(np.mean(error**2)))),
                modulo90_phase_rms_deg=float(np.degrees(np.sqrt(np.mean(mod90**2)))),
                quadrant_histogram=histogram, dominant_quadrant=int(np.argmax(histogram)),
                dominant_quadrant_fraction=max(histogram)/count)


def measure_case(name, esn0_db=None, **parameters):
    rows, signal, labels, phase, meta = waveform(esn0_db, **parameters)
    loops = run_loops(rows, meta['k1'], meta['k2'])
    window = slice(meta['steady_start'], meta['count'])
    records = {}
    for mode, loop in loops.items():
        records[mode] = dict(comparison=sqnr_db(loop['fixed_output'][window], loop['float_output'][window]))
        for kind in ('fixed', 'float'):
            records[mode][kind] = receiver_metrics(loop[kind+'_output'][window],
                                                  loop[kind+'_phase'][window], labels[window], phase[window])
    return dict(name=name, parameters=meta, steady_window=[meta['steady_start'], meta['count']], **records)


def check_cases(cases):
    """Explicit measured regression gates, restricted to the default fixtures."""
    expected = {'quiet', 'esn0_20db', 'esn0_12db', 'esn0_8db', 'quadrant_ambiguity'}
    checks = {'required_cases': len(cases) == len(expected) and {c['name'] for c in cases} == expected}
    for case in cases:
        name = case['name']; enabled = case['enabled']; disabled = case['disabled']
        checks[name+'_input_no_clips'] = case['parameters']['input_rail_excursions'] == 0
        checks[name+'_sqnr_gt55db'] = enabled['comparison']['sqnr_db'] is not None and enabled['comparison']['sqnr_db'] > 55
        checks[name+'_same_error_count'] = enabled['fixed']['symbol_errors'] == enabled['float']['symbol_errors']
        for kind in ('fixed', 'float'):
            m = enabled[kind]; off = disabled[kind]
            if name == 'quadrant_ambiguity':
                checks[name+'_'+kind] = (m['raw_ser'] > .99 and 89 < m['true_phase_rms_deg'] < 91
                                         and m['modulo90_phase_rms_deg'] < .1
                                         and m['dominant_quadrant'] == 3 and m['dominant_quadrant_fraction'] > .99)
            else:
                checks[name+'_'+kind+'_tracking'] = m['true_phase_rms_deg'] < 10 and m['raw_ser'] < .06
                checks[name+'_'+kind+'_control'] = off['raw_ser'] > .6 and off['true_phase_rms_deg'] > 80
                if name == 'quiet':
                    checks[name+'_'+kind+'_quiet'] = m['raw_ser'] == 0 and m['true_phase_rms_deg'] < .1
                if name == 'esn0_8db':
                    checks[name+'_'+kind+'_measurable_errors'] = .005 < m['raw_ser'] < .06
    return checks


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/rtl/sync_precision/results.json')
    args = parser.parse_args(argv)
    require_unoptimized()
    evidence = begin()
    write_json(args.output, dict(evidence, status='RUNNING'))
    try:
        cases = [measure_case('quiet')]
        cases += [measure_case(f'esn0_{snr}db', snr) for snr in (20, 12, 8)]
        cases += [measure_case('quadrant_ambiguity', phase_rad=np.deg2rad(100))]
        checks = check_cases(cases)
        status = 'PASS' if all(checks.values()) else 'FAIL'
        report = dict(finish(evidence), status=status, parameters=DEFAULTS, cases=cases, checks=checks,
                      scope='Symbol-rate QPSK Costas tracking; Python arithmetic measurement, no RTL claim or acquisition-range mapping.',
                      ambiguity='Raw SER and true phase error are never corrected using labels. Modulo90 and quadrant histograms are diagnostics only.',
                      snr_definition='Es/N0 = 10log10(1/E|complex AWGN|^2), before Q15 quantization.',
                      sqnr_definition='10log10(mean|floating output|^2/mean|fixed output-floating output|^2); no alignment.',
                      phase_definition='Wrapped estimated minus true carrier phase at the same pre-update sample index.')
        write_json(args.output, report)
    except Exception as exc:
        write_json(args.output, dict(evidence, status='FAIL', error=str(exc)))
        raise
    for case in cases:
        m = case['enabled']['fixed']; snr = case['enabled']['comparison']['sqnr_db']
        print(f"{case['name']}: SQNR={snr:.2f}dB SER={m['raw_ser']:.6f} phaseRMS={m['true_phase_rms_deg']:.3f}deg")
    if status != 'PASS':
        raise RuntimeError('Costas precision regression failed: '+', '.join(k for k, ok in checks.items() if not ok))
    print('PASS SYNC precision')
    return report


if __name__ == '__main__':
    main()
