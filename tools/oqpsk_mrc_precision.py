#!/usr/bin/env python3
"""Full fixed OQPSK and two-branch MRC experiments with independent floating RX.

Both algorithms see the same quantized input (MRC: the same two branches).
Only the 192-symbol preamble enters receivers. TX drives the channel from the
fixed transmitter. Local node SQNR is conditioned on integer upstream values,
positions and phases; final payload SER uses the independent complete floating
receiver. No output gain fitting, payload phase rotation or truth alignment.
OQPSK fixed RX has no AGC; floating RX uses its own preamble-based acquisition.
Python arithmetic/tracking measurements only, no RTL or acquisition-range claim.
"""
import argparse
import hashlib
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
import oqpsk_fixed as oq
import mrc_fixed as mrc
import psk_fixed as psk
import modem_core as real
from psk_precision import metric, complex_samples, payload_score, node_metrics, vector, NODE_LIMITS
from regression_evidence import begin, finish, require_unoptimized, write_json

COUNT, PREAMBLE, LABEL_SEED, CHANNEL_SEED, NOISE_SEED = 512, 192, 19, 7, 99
OQ_CONFIG = 'oqpsk_2_sps_timing_recovery_2019_12_05'
MRC_CONFIG = 'simo_maximal_ratio_combining_2010_08_27'
GAINS = (.2+.3j, 1-.4j)
VARIANCES = ((1, 1), (1, 4))
OQ_CASES = dict(clean={}, nominal=dict(snr_db=30, gain=.65, phase=.38, frequency=.00015, delay=2.25), low_snr=dict(snr_db=-8))
# MRC AWGN is added independently in each branch. Nominal changes the COMMON
# linear signal before branch gains; it adds no extra correlated channel noise.
MRC_CASES = dict(quiet=(0., {}), small_noise=(.05, {}),
                 nominal=(.05, dict(gain=.65, phase=.38, frequency=.00015, delay=2.25)), noisy=(.3, {}))
OQ_LIMITS = dict(tx_rrc=80, rx_rrc=80, cubic_i=60, cubic_q=60, rotation_i=55, rotation_q=55)
MRC_LIMITS = dict(NODE_LIMITS, weights=80, combiner=80)


def rows_hash(rows):
    return hashlib.sha256(np.asarray(rows, dtype='<i8').tobytes()).hexdigest()


def quantized(wave, quantizer=psk.quantize):
    wave = vector(wave, 'waveform')
    raw = np.rint(np.c_[wave.real, wave.imag]*32768)
    clips = int(np.count_nonzero((raw < -131072) | (raw > 131071)))
    rows = quantizer(wave)
    return rows, dict(rail_excursions=clips, sha256=rows_hash(rows))


def oq_phases(nodes, acquisition):
    theta_i = np.asarray([int(node['thetaI']) for node in nodes], dtype=np.int64)
    theta_q = np.asarray([oq.wrap(int(phase)+4*int(acquisition['frequency'])) for phase in theta_i])
    return theta_i*2*np.pi/2**32, theta_q*2*np.pi/2**32


def oq_node_metrics(rows, result, tx_fixed, tx_float):
    nodes = result['nodes']
    # observe exposes split branch nodes, not the whole FIR vector. Reconstruct
    # its identical upstream integer FIR from the same quantized input only.
    filtered = complex_samples(oq.fir(rows))
    pos_i = oq.FIRST+oq.SPS*np.arange(len(nodes))+result['acquisition']['delay']/65536
    pos_q = pos_i+4
    phase_i, phase_q = oq_phases(nodes, result['acquisition'])
    z_i = complex_samples([node['zI'] for node in nodes]); z_q = complex_samples([node['zQ'] for node in nodes])
    r_i = complex_samples([node['rI'] for node in nodes]); r_q = complex_samples([node['rQ'] for node in nodes])
    return dict(tx_rrc=metric(tx_fixed, tx_float),
                rx_rrc=metric(filtered, np.convolve(complex_samples(rows), real.rrc_taps(8, 32, 1))),
                cubic_i=metric(z_i, real.cubic(filtered, pos_i)), cubic_q=metric(z_q, real.cubic(filtered, pos_q)),
                rotation_i=metric(r_i, z_i*np.exp(-1j*phase_i)), rotation_q=metric(r_q, z_q*np.exp(-1j*phase_q)))


def measure_oq(case, parameters):
    cfg = real.load_config(ROOT/'modems'/OQ_CONFIG/'config.json')
    labels = np.random.default_rng(LABEL_SEED).integers(0, 4, COUNT)
    tx_fixed = complex_samples(oq.transmit(labels)); tx_float = real.transmit(cfg, labels)['waveform']
    rows, input_meta = quantized(real.channel(cfg, tx_fixed, seed=CHANNEL_SEED, **parameters), oq.quantize)
    wave = complex_samples(rows); preamble = labels[:PREAMBLE].copy()
    record = dict(kind='oqpsk', config=OQ_CONFIG, case=case, channel_parameters=parameters,
                  input=input_meta, label_sha256=rows_hash(labels), fixed_agc=False, nodes={},
                  fixed=dict(status='not_run'), floating=dict(status='not_run'))
    try:
        result = oq.receive(rows, preamble, COUNT, observe=True)
        record['fixed'] = dict(status='decoded', **payload_score(result['data'], labels, alphabet=4),
                               acquisition={key: int(result['acquisition'][key]) for key in ('delay', 'phase', 'frequency', 'slope')})
        record['nodes'] = oq_node_metrics(rows, result, tx_fixed, tx_float)
    except (ValueError, RuntimeError) as exc:
        record['fixed'] = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
    try:
        result = real.receive(cfg, wave, preamble, COUNT)
        record['floating'] = dict(status='decoded', **payload_score(result['data'], labels, alphabet=4))
    except (ValueError, RuntimeError) as exc:
        record['floating'] = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
    return record


def checked_variances(variances):
    values = np.asarray(variances)
    if values.shape != (2,) or np.iscomplexobj(values) or not np.all(np.isfinite(values)) or np.any(values != np.floor(values)) or np.any((values < 1) | (values > 65535)):
        raise ValueError('Two integer noise variances in 1..65535 required')
    return tuple(map(int, values))


def float_weights(known_gains, variances):
    gains = vector(known_gains, 'known_gains')
    if len(gains) != 2 or not np.any(abs(gains) > 0):
        raise ValueError('Two known gains with nonzero combined energy required')
    variances = np.asarray(checked_variances(variances))
    return gains.conj()/variances/np.sum(abs(gains)**2/variances)


def make_branches(wave, known_gains, variances, sigma, seed=NOISE_SEED):
    wave = vector(wave, 'waveform'); known_gains = vector(known_gains, 'known_gains')
    if len(known_gains) != 2:
        raise ValueError('Two branch gains required')
    variances = checked_variances(variances)
    if np.ndim(sigma) != 0 or np.iscomplexobj(sigma) or not np.isfinite(sigma) or sigma < 0:
        raise ValueError('sigma must be a finite nonnegative real scalar')
    rng = np.random.default_rng(seed)
    waves, metadata = [], []
    for gain, variance in zip(known_gains, variances):
        noise = sigma*np.sqrt(variance)*(rng.normal(size=len(wave))+1j*rng.normal(size=len(wave)))
        waves.append(gain*wave+noise)
        metadata.append(dict(variance=variance, component_noise_power=float(sigma**2*variance),
                             expected_complex_noise_power=float(2*sigma**2*variance),
                             measured_complex_noise_power=float(np.mean(abs(noise)**2))))
    return waves, metadata


def measure_mrc(case, variances, sigma, parameters):
    cfg = real.load_config(ROOT/'modems'/MRC_CONFIG/'config.json'); profile = mrc.branch_profile(cfg)
    labels = np.random.default_rng(LABEL_SEED).integers(0, 4, COUNT)
    tx_fixed = complex_samples(psk.transmit(profile, labels)); tx_float = real.transmit(cfg, labels)['waveform']
    common = real.channel(cfg, tx_fixed, seed=CHANNEL_SEED, **parameters)
    raw_gains = tuple(mrc.quantize_gain(gain) for gain in GAINS)
    gains = complex_samples(raw_gains)
    branch_waves, noise_meta = make_branches(common, gains, variances, sigma)
    rows, branch_meta = [], []
    for wave, metadata in zip(branch_waves, noise_meta):
        branch_rows, input_meta = quantized(wave, psk.quantize)
        rows.append(branch_rows); branch_meta.append(dict(metadata, **input_meta))
    integer_weights = mrc.weights(*raw_gains, *variances)
    actual_weights = np.asarray([complex(*w)/16384 for w in integer_weights])
    expected_weights = float_weights(gains, variances)
    combined_rows = mrc.combine(*rows, *integer_weights)
    floating_combined = real.maximal_ratio_combine([complex_samples(branch) for branch in rows], gains, variances)
    weight_metric = metric(actual_weights, expected_weights)
    weight_metric['rail_values'] = int(np.count_nonzero(np.isin(np.asarray(integer_weights), [-131072, 131071])))
    weight_metric['fractional_bits'] = 14
    nodes = dict(weights=weight_metric, combiner=metric(complex_samples(combined_rows), floating_combined))
    record = dict(kind='mrc', config=MRC_CONFIG, case=case, variances=list(variances), sigma=float(sigma),
                  noise_seed=NOISE_SEED, channel_parameters=parameters, gains_q15=raw_gains, weights_q14=integer_weights,
                  branch_inputs=branch_meta, combined_sha256=rows_hash(combined_rows), label_sha256=rows_hash(labels),
                  nodes=nodes, fixed=dict(status='not_run'), floating=dict(status='not_run'))
    preamble = labels[:PREAMBLE].copy()
    try:
        result = psk.receive(profile, combined_rows, preamble, COUNT, observe=True)
        record['fixed'] = dict(status='decoded', **payload_score(result['data'], labels, alphabet=4),
                               acquisition_confident=bool(result['acquisition']['confidence']))
        nodes.update(node_metrics(profile, cfg, combined_rows, result, tx_fixed, tx_float, preamble))
    except (ValueError, RuntimeError) as exc:
        record['fixed'] = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
    try:
        result = real.receive(cfg, floating_combined, preamble, COUNT)
        record['floating'] = dict(status='decoded', **payload_score(result['data'], labels, alphabet=4))
    except (ValueError, RuntimeError) as exc:
        record['floating'] = dict(status='failed', error=f'{type(exc).__name__}: {exc}')
    return record


def check_records(records):
    expected = {('oqpsk', name, ()) for name in OQ_CASES}
    expected |= {('mrc', name, variances) for name in MRC_CASES for variances in VARIANCES}
    actual = {(r['kind'], r['case'], tuple(r.get('variances', ()))) for r in records}
    checks = dict(complete_coverage=actual == expected and len(records) == len(expected))
    noisy_mrc = dict(fixed=0, floating=0)
    for record in records:
        kind = record['kind']; case = record['case']; prefix = kind+'/'+case+'/'+str(record.get('variances', []))
        control = case in ('low_snr', 'noisy')
        for receiver in ('fixed', 'floating'):
            decoded = record[receiver]['status'] == 'decoded'
            checks[prefix+'/'+receiver+'_decoded'] = decoded
            if not control:
                checks[prefix+'/'+receiver+'_zero_ser'] = decoded and record[receiver]['errors'] == 0
            elif kind == 'oqpsk':
                checks[prefix+'/'+receiver+'_noise_errors'] = decoded and record[receiver]['errors'] > 20
            elif decoded:
                noisy_mrc[receiver] += record[receiver]['errors']
        if not control:
            limits = OQ_LIMITS if kind == 'oqpsk' else MRC_LIMITS
            required = set(OQ_LIMITS) if kind == 'oqpsk' else {'weights', 'combiner', 'tx_rrc', 'rx_rrc', 'cubic_mid', 'rotation', 'gain'}
            checks[prefix+'/nodes_complete'] = set(record['nodes']) == required
            clips = [record['input']['rail_excursions']] if kind == 'oqpsk' else [meta['rail_excursions'] for meta in record['branch_inputs']]
            checks[prefix+'/input_no_clips'] = not any(clips)
            for name, value in record['nodes'].items():
                checks[prefix+'/'+name+'_sqnr'] = value['exact_match'] or value['sqnr_db'] > limits[name]
                checks[prefix+'/'+name+'_no_rails'] = value['rail_values'] == 0
    for receiver, errors in noisy_mrc.items():
        checks['mrc/'+receiver+'_noisy_errors'] = errors > 0
    return checks


def report():
    records = [measure_oq(name, params) for name, params in OQ_CASES.items()]
    for variances in VARIANCES:
        records += [measure_mrc(name, variances, sigma, params) for name, (sigma, params) in MRC_CASES.items()]
    return dict(records=records, checks=check_records(records))


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT/'build/rtl/oqpsk_mrc_precision/results.json')
    args = parser.parse_args(argv); evidence = begin()
    write_json(args.output, dict(evidence, status='RUNNING'))
    try:
        require_unoptimized(); data = report()
        status = 'PASS' if all(data['checks'].values()) else 'FAIL'
        result = dict(finish(evidence), status=status, **data,
                      parameters=dict(count=COUNT, preamble_symbols=PREAMBLE, label_seed=LABEL_SEED, channel_seed=CHANNEL_SEED,
                                      noise_seed=NOISE_SEED, oq_cases=OQ_CASES, mrc_cases=MRC_CASES,
                                      variances=VARIANCES, oq_node_limits_db=OQ_LIMITS, mrc_node_limits_db=MRC_LIMITS),
                      scope='Python fixed TX/channel/full RX; independent floating full RX, raw payload SER, no truth alignment. OQPSK fixed RX has no AGC; local split nodes use its integer phase/delay states.',
                      noise_scope='MRC sigma is per-real-component standard deviation before quantization; complex noise power=2*sigma^2*variance. Known Q15 gains and common clock/delay. No extra correlated channel AWGN in MRC cases.',
                      node_scope='Local conditioned arithmetic; MRC weights against independent normalized inverse-variance formula, combiner from identical quantized branches. Downstream node SQNR at integer combined input/loop states. Final SER includes independent acquisition/tracking differences.',
                      oq_cubic_scope='Cubic SQNR includes 8-bit fraction table quantization: floor(Q16 position/256). The nominal measured SQNR is about64.5dB; gate60dB.')
        write_json(args.output, result)
    except Exception as exc:
        write_json(args.output, dict(evidence, status='FAIL', error=f'{type(exc).__name__}: {exc}'))
        raise
    for record in data['records']:
        counts = [str(record[key].get('errors', record[key]['status'])) for key in ('fixed', 'floating')]
        print(f"{record['kind']}/{record['case']}/{record.get('variances', [])}: fixed/float errors {'/'.join(counts)}/{COUNT-PREAMBLE}")
    if status != 'PASS':
        raise RuntimeError('OQPSK/MRC precision failed: '+', '.join(k for k, ok in data['checks'].items() if not ok))
    print('PASS OQPSK MRC precision')
    return result


if __name__ == '__main__':
    main()
