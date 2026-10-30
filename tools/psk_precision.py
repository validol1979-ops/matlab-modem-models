#!/usr/bin/env python3
"""PSK/QAM Python precision on one representative for each integer profile.

The full fixed TX drives one linear channel, which is quantized once. Complete
fixed and independent floating receivers see that identical waveform and only
192 training labels. TX is also compared with modem_core.transmit. Node SQNR
uses fixed upstream samples and fixed loop states to isolate local arithmetic;
it does not measure independent acquisition/tracking disagreement. Payload SER
uses original labels without fitting or rotating either receiver's output.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
import psk_fixed as fixed
import modem_core as real
from regression_evidence import begin, finish, require_unoptimized, write_json

COUNT, PREAMBLE, LABEL_SEED, CHANNEL_SEED = 512, 192, 19, 7
CHANNELS = dict(clean={}, nominal=dict(snr_db=30, gain=.65, phase=.38, frequency=.00015, delay=2.25),
                low_snr=dict(snr_db=-8))
NODE_LIMITS = dict(tx_rrc=80, rx_rrc=80, cubic_mid=65, rotation=55, gain=85,
                   pre_eq_gain=85, eq_arithmetic=85)


def vector(value, name):
    a = np.asarray(value)
    if a.ndim != 1 or not a.size:
        raise ValueError(name+' must be a nonempty 1D array')
    try:
        finite = np.all(np.isfinite(a))
    except TypeError as exc:
        raise ValueError(name+' must be numeric') from exc
    if not finite:
        raise ValueError(name+' must be finite')
    return a


def complex_samples(rows):
    a = np.asarray(rows)
    if a.ndim != 2 or a.shape[1] != 2 or not len(a) or not np.all(np.isfinite(a)):
        raise ValueError('Integer samples must have nonempty Nx2 shape')
    return (a[:, 0]+1j*a[:, 1])/32768


def metric(actual, expected):
    actual = vector(actual, 'actual'); expected = vector(expected, 'expected')
    if actual.shape != expected.shape:
        raise ValueError('Precision samples must have equal shape')
    power = float(np.mean(abs(expected)**2)); mse = float(np.mean(abs(actual-expected)**2))
    if not np.isfinite(power) or not np.isfinite(mse) or power <= 0:
        raise ValueError('SQNR power must be finite and reference power positive')
    rails = sum(int(np.count_nonzero(np.isin(np.rint(component*32768), [-131072, 131071])))
                for component in (actual.real, actual.imag))
    return dict(samples=len(actual), signal_power=power, error_power=mse,
                sqnr_db=None if mse == 0 else float(10*np.log10(power/mse)), exact_match=mse == 0,
                max_complex_error=float(np.max(abs(actual-expected))), rail_values=rails)


def payload_score(decoded, labels, preamble=PREAMBLE, alphabet=None):
    decoded = vector(decoded, 'decoded'); labels = vector(labels, 'labels')
    if decoded.shape != labels.shape or not np.issubdtype(decoded.dtype, np.integer) or not np.issubdtype(labels.dtype, np.integer):
        raise ValueError('Decoded and true labels must be equal-length integer arrays')
    if not isinstance(preamble, int) or not 0 <= preamble < len(labels):
        raise ValueError('Payload must contain symbols after the preamble')
    if np.any(labels < 0) or np.any(decoded < 0):
        raise ValueError('Labels must be nonnegative')
    if alphabet is not None and (np.any(labels >= alphabet) or np.any(decoded >= alphabet)):
        raise ValueError('Labels must be inside the configured alphabet')
    errors = int(np.count_nonzero(decoded[preamble:] != labels[preamble:]))
    count = len(labels)-preamble
    return dict(payload_symbols=count, errors=errors, ser=errors/count)


def representatives(profiles=fixed.PROFILES):
    grouped = {p.name: [] for p in fixed.PROFILES}
    for path in sorted((ROOT/'modems').glob('*/config.json')):
        cfg = real.load_config(path)
        try:
            profile = fixed.profile_for(cfg)
        except ValueError:
            continue
        grouped[profile.name].append(cfg)
    output = []
    for profile in profiles:
        candidates = grouped[profile.name]
        names = [cfg['name'] for cfg in candidates]
        derived = None
        if candidates:
            cfg = candidates[0]
        elif profile is fixed.QPSK_DIFF:
            base = real.load_config(ROOT/'modems/simo_maximal_ratio_combining_2010_08_27/config.json')
            derived = dict(source_config=base['name'], override=dict(diversity_branches=1),
                           scope='Single branch QPSK differential core; excludes SIMO combiner.')
            cfg = dict(base, name='derived_single_branch_qpsk_diff', diversity_branches=1)
        else:
            raise RuntimeError('No representative for profile '+profile.name)
        if fixed.profile_for(cfg) is not profile:
            raise RuntimeError('Representative profile mismatch')
        if (cfg['sps'], cfg['rrc_order'], cfg['rolloff']) != (8, 32, 1.):
            raise RuntimeError('Integer profiles require SPS8/order32/rolloff1')
        coverage = dict(profile=profile.name, representative=cfg['name'], matched_config_names=names,
                        derived=derived, tested_config_count=1, tx_shift=profile.tx_shift,
                        rx_shift=profile.rx_shift, tx_amplitude=profile.tx_amplitude or profile.amplitude,
                        rx_fir_scale=2.**(17-profile.rx_shift), equalizer=profile.equalizer)
        output.append((profile, cfg, coverage))
    return output


def gain_samples(nodes):
    return [tuple(fixed.sat(fixed.round_shift(v*node['gain'], 20)) for v in node['rotated']) for node in nodes]


def equalizer_node(profile, pre_gain, nodes, preamble):
    """Replay integer states, then compare only the unrounded floating dot sum.

    Includes forward and DFE feedback terms. Coefficient adaptation is conditioned
    on integer states, not an independent floating NLMS convergence measurement.
    """
    eq = fixed.Equalizer(profile.equalizer)
    train_ids = fixed.encode(profile, preamble)
    expected = []
    for k, (value, node) in enumerate(zip(pre_gain, nodes)):
        got = eq.output(value)
        if tuple(got) != tuple(node['value']):
            raise RuntimeError('Equalizer replay does not match observed receiver')
        terms = list(zip(eq.forward, eq.history))
        if profile.equalizer == 'dfe':
            terms += list(zip(eq.feedback, eq.past))
        expected.append(sum(complex(wr, wi)/2**22*complex(xr, xi)/32768
                            for (wr, wi), (xr, xi) in terms))
        idx = profile.slice(got)
        target_id = train_ids[k] if k < fixed.USABLE else idx
        eq.update(got, profile.target(target_id), k < fixed.USABLE)
    result = metric(complex_samples([node['value'] for node in nodes]), np.asarray(expected))
    result['scope'] = 'EQ output multiply/accumulate/round/saturate at integer taps/history; excludes coefficient adaptation discrepancy.'
    return result


def node_metrics(profile, cfg, rows, result, tx_fixed, tx_float, preamble):
    nodes = result['nodes']
    filtered = complex_samples(result['filtered'])
    incoming = complex_samples(rows)
    positions = np.asarray([node['position'] for node in nodes])/65536
    phases = np.asarray([node['phase'] for node in nodes])*2*np.pi/2**32
    gains = np.asarray([node['gain'] for node in nodes])/2**20
    mids = complex_samples([node['mid'] for node in nodes])
    rotated = complex_samples([node['rotated'] for node in nodes])
    reference_filtered = np.convolve(incoming, real.rrc_taps(8, 32, 1))*2.**(17-profile.rx_shift)
    metrics = dict(tx_rrc=metric(tx_fixed, tx_float), rx_rrc=metric(filtered, reference_filtered),
                   cubic_mid=metric(mids, real.cubic(filtered, positions)),
                   rotation=metric(rotated, mids*np.exp(-1j*phases)))
    pre_gain = gain_samples(nodes)
    name = 'gain' if profile.equalizer == 'none' else 'pre_eq_gain'
    metrics[name] = metric(complex_samples(pre_gain), rotated*gains)
    if profile.equalizer == 'none':
        if pre_gain != [tuple(node['value']) for node in nodes]:
            raise RuntimeError('Gain reconstruction does not match observed receiver')
    else:
        metrics['eq_arithmetic'] = equalizer_node(profile, pre_gain, nodes, preamble)
    return metrics


def measure_case(profile, cfg, labels, case, parameters, tx_rows, tx_float):
    # The full fixed transmitter is the shared channel source. The floating
    # transmitter remains an independent TX node reference only.
    tx_fixed = complex_samples(tx_rows)
    channel = real.channel(cfg, tx_fixed, seed=CHANNEL_SEED, **parameters)
    unbounded = np.rint(np.c_[channel.real, channel.imag]*32768)
    clips = int(np.count_nonzero((unbounded < -131072) | (unbounded > 131071)))
    rows = fixed.quantize(channel); wave = complex_samples(rows)
    record = dict(profile=profile.name, config=cfg['name'], case=case, channel_parameters=parameters,
                  label_seed=LABEL_SEED, channel_seed=CHANNEL_SEED, input_rail_excursions=clips,
                  input_sha256=hashlib.sha256(np.asarray(rows, dtype='<i8').tobytes()).hexdigest(),
                  labels_sha256=hashlib.sha256(labels.astype('<i8').tobytes()).hexdigest(), nodes={},
                  fixed=dict(status='not_run'), floating=dict(status='not_run'))
    preamble = labels[:PREAMBLE].copy()
    try:
        result = fixed.receive(profile, rows, preamble, len(labels), observe=True)
        record['fixed'] = dict(status='decoded', **payload_score(result['data'], labels, alphabet=profile.alphabet),
                               acquisition_confident=bool(result['acquisition']['confidence']))
        record['nodes'] = node_metrics(profile, cfg, rows, result, tx_fixed, tx_float, preamble)
    except (ValueError, RuntimeError) as exc:
        record['fixed'] = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
    try:
        reference = real.receive(cfg, wave, preamble, len(labels))
        record['floating'] = dict(status='decoded', **payload_score(reference['data'], labels, alphabet=profile.alphabet))
    except (ValueError, RuntimeError) as exc:
        record['floating'] = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
    return record


def check_records(records, profile_names):
    required = {(name, case) for name in profile_names for case in CHANNELS}
    actual = {(r['profile'], r['case']) for r in records}
    checks = dict(complete_cases=actual == required and len(records) == len(required) and bool(records))
    noise_counts = {'fixed': 0, 'floating': 0}
    for record in records:
        prefix = record['profile']+'/'+record['case']
        for receiver in ('fixed', 'floating'):
            decoded = record[receiver]['status'] == 'decoded'
            checks[prefix+'/'+receiver+'_decoded'] = decoded
            if record['case'] != 'low_snr':
                checks[prefix+'/'+receiver+'_zero_ser'] = decoded and record[receiver]['errors'] == 0
            elif decoded:
                noise_counts[receiver] += record[receiver]['errors']
        if record['case'] != 'low_snr':
            checks[prefix+'/input_no_clips'] = record['input_rail_excursions'] == 0
            profile = next(p for p in fixed.PROFILES if p.name == record['profile'])
            expected_nodes = {'tx_rrc', 'rx_rrc', 'cubic_mid', 'rotation'}
            expected_nodes |= {'gain'} if profile.equalizer == 'none' else {'pre_eq_gain', 'eq_arithmetic'}
            checks[prefix+'/nodes_present'] = expected_nodes == set(record['nodes'])
            for name, value in record['nodes'].items():
                checks[prefix+'/'+name+'_sqnr'] = value['exact_match'] or value['sqnr_db'] > NODE_LIMITS[name]
                checks[prefix+'/'+name+'_no_rails'] = value['rail_values'] == 0
    for receiver, errors in noise_counts.items():
        checks['low_snr/'+receiver+'_errors'] = errors > 20*len(profile_names)
    return checks


def report(profiles=fixed.PROFILES):
    selected = representatives(profiles)
    records = []
    for profile, cfg, _ in selected:
        labels = np.random.default_rng(LABEL_SEED).integers(0, profile.alphabet, COUNT)
        tx_rows = fixed.transmit(profile, labels)
        tx_float = real.transmit(cfg, labels)['waveform']
        for case, parameters in CHANNELS.items():
            records.append(measure_case(profile, cfg, labels, case, parameters, tx_rows, tx_float))
    names = [profile.name for profile in profiles]
    return dict(coverage=[coverage for _, _, coverage in selected], records=records,
                checks=check_records(records, names))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/rtl/psk_precision/results.json')
    args = parser.parse_args(argv)
    evidence = begin()
    write_json(args.output, dict(evidence, status='RUNNING'))
    try:
        require_unoptimized()
        data = report()
        status = 'PASS' if all(data['checks'].values()) else 'FAIL'
        completed = dict(finish(evidence), status=status, **data,
                         parameters=dict(count=COUNT, preamble_symbols=PREAMBLE, label_seed=LABEL_SEED,
                                         channel_seed=CHANNEL_SEED, channels=CHANNELS, node_limits_db=NODE_LIMITS),
                         scope='Python full fixed PSK/QAM TX/channel/RX, one representative per 14 profiles; matched configs enumerate compatible families, not separately exercised. No RTL equivalence claim.',
                         channel_scope='Shared fixed TX waveform -> modem_core linear channel -> Q15 quantization once -> both full receivers. SNR is modem_core channel sample-average signal/noise power before quantization; low-SNR results include reported rail clipping.',
                         node_scope='TX ideal floating constellation/filter. RX FIR same quantized input with 2**(17-rx_shift) scale. Cubic, rotation, gain at integer upstream values and loop states. EQ dot arithmetic at integer coefficients/history; independent final receiver includes full EQ adaptation.',
                         ser_scope='Raw labels after index192; each receiver receives only the preamble. No payload fitting, phase alignment, or truth rotation.')
        write_json(args.output, completed)
    except Exception as exc:
        write_json(args.output, dict(evidence, status='FAIL', error=f'{type(exc).__name__}: {exc}'))
        raise
    for record in data['records']:
        counts = [str(record[key].get('errors', record[key]['status'])) for key in ('fixed', 'floating')]
        print(f"{record['profile']}/{record['case']}: fixed/float errors {'/'.join(counts)}/{COUNT-PREAMBLE}")
    if status != 'PASS':
        raise RuntimeError('PSK precision failed: '+', '.join(k for k, ok in data['checks'].items() if not ok))
    print('PASS PSK precision')
    return completed


if __name__ == '__main__':
    main()
