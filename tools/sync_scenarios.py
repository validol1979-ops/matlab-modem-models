"""Measured tracking transients; symbol indices and carrier phase are known references.

Costas leaves a 20 degree phase tolerance after a 30 degree jump. Gardner leaves
a 0.1 RMS symbol-error tolerance during a two-sample delay excursion. These are
tracking tests. The 100 degree Costas excursion below measures a quadrant change: the median phase
error of the two lock windows differs by about -90 degrees while the loop stays locked modulo 90.
These tests do not map the complete acquisition range and do not count slips.
"""
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import sync_fixed as fixed
from modem_core import load_config, transmit, rrc_taps, cubic


def _source():
    cfg = load_config(ROOT / 'modems/qpsk_script_costas/config.json')
    labels = np.random.default_rng(0).integers(0, cfg['order'], 1000)
    symbols = (np.array(cfg['constellation']) @ [1, 1j])[labels]
    return cfg, labels, symbols


def _quantize(wave):
    return [(max(-131072, min(131071, round(v.real * 32768))),
             max(-131072, min(131071, round(v.imag * 32768)))) for v in wave]


def costas_metrics(phases, disabled_phases, reference):
    def rms(values, start, stop):
        phase = np.array(values[start:stop]) * (2 * np.pi / 2**32)
        error = np.degrees(np.angle(np.exp(1j * (phase - reference[start:stop]))))
        return float(np.sqrt(np.mean(error**2)))
    metrics = {f'{window}_{mode}_deg': rms(values, *bounds)
               for mode, values in [('enabled', phases), ('disabled', disabled_phases)]
               for window, bounds in [('early', (0, 30)), ('before', (220, 290)),
                                      ('excursion', (300, 304)), ('recovery', (600, 850))]}
    metrics.update(acquired=metrics['before_enabled_deg'] < 1
                   and metrics['early_enabled_deg'] > 10 * metrics['before_enabled_deg']
                   and metrics['before_disabled_deg'] > 20,
                   lost=metrics['excursion_enabled_deg'] > 20,
                   recovered=metrics['recovery_enabled_deg'] < 1
                   and metrics['recovery_disabled_deg'] > 20)
    return metrics


def costas_scenario():
    _, _, symbols = _source()
    phase = .3 + .006 * np.arange(900)
    phase[300:] += np.deg2rad(30)
    samples = _quantize(symbols[:900] * np.exp(1j * phase))
    values, phases = fixed.costas(samples, fixed.costas_gains(.08, .001))
    _, disabled = fixed.costas(samples, (0, 0))
    metrics = costas_metrics(phases, disabled, phase)
    return samples, values, phases, metrics, phase, disabled


# The two lock windows around the jump at sample 300 of the slip scenario.
SLIP_BEFORE = (220, 290)
SLIP_AFTER = (600, 850)


def _slip_phase_error(phases, reference):
    """Phase error in degrees of one phase stream against the reference: against the TRUE carrier
    phase, and the same error folded into the 90 degree QPSK quadrant (the symmetry the Costas
    discriminator cannot resolve)."""
    phase = np.asarray(phases, dtype=float) * (2 * np.pi / 2**32)
    error = np.degrees(np.angle(np.exp(1j * (phase - np.asarray(reference, dtype=float)))))
    return error, (error + 45) % 90 - 45


def _slip_side(phases, reference, prefix):
    """One side (enabled or disabled loop) of the quadrant-change evidence, keys prefixed."""
    error, mod90 = _slip_phase_error(phases, reference)
    before_true, after_true = error[SLIP_BEFORE[0]:SLIP_BEFORE[1]], error[SLIP_AFTER[0]:SLIP_AFTER[1]]
    before_mod, after_mod = mod90[SLIP_BEFORE[0]:SLIP_BEFORE[1]], mod90[SLIP_AFTER[0]:SLIP_AFTER[1]]
    def rms(values):
        return float(np.sqrt(np.mean(values**2)))
    before, after = float(np.median(before_true)), float(np.median(after_true))
    return {
        f'{prefix}before_median_deg': before,
        f'{prefix}after_median_deg': after,
        # The observation is the shift of the median error between the two lock windows. It says
        # nothing about how many slips happened or whether the trajectory between the windows was
        # a single continuous one; the samples in between are not examined here.
        f'{prefix}quadrant_change_deg': after - before,
        f'{prefix}before_true_rms_deg': rms(before_true),
        f'{prefix}recovery_true_rms_deg': rms(after_true),
        f'{prefix}before_mod90_rms_deg': rms(before_mod),
        f'{prefix}recovery_mod90_rms_deg': rms(after_mod),
    }


def costas_slip_metrics(phases, disabled_phases, reference):
    """Quadrant-slip evidence of a Costas run against the known carrier phase in radians.

    Both the enabled phases (2^-32 turns) and the phases of the same samples with gains (0, 0) are
    measured twice: against the true carrier phase and modulo 90 degrees, before and after the jump.

    `quadrant_change_deg` is the difference of the two median errors (an observation about two
    medians, not a claim of one continuous cycle slip). `slipped` is the compatible boolean of that
    observation: the loop acquired the transmitted quadrant before the jump and a quadrant change
    was observed while it stayed locked modulo 90 degrees. It does NOT prove a single continuous
    slip. `disabled_rejected` verifies that the frozen loop fails the quadrant-change criterion and
    fails lock modulo 90 in these measured windows."""
    streams = [np.asarray(values, dtype=float) for values in
               (phases, disabled_phases, reference)]
    if (any(values.ndim != 1 for values in streams)
            or len({len(values) for values in streams}) != 1
            or len(streams[0]) < SLIP_AFTER[1]
            or not all(np.all(np.isfinite(values)) for values in streams)):
        raise ValueError('Costas slip streams must be finite, equally sized 1-D arrays of at least 850 samples')
    phases, disabled_phases, reference = streams
    metrics = _slip_side(phases, reference, '')
    metrics.update(_slip_side(disabled_phases, reference, 'disabled_'))
    metrics['locked_mod90'] = bool(metrics['before_mod90_rms_deg'] < 1
                                   and metrics['recovery_mod90_rms_deg'] < 1)
    metrics['quadrant_change_observed'] = bool(abs(abs(metrics['quadrant_change_deg']) - 90) < 2
                                               and abs(metrics['recovery_true_rms_deg'] - 90) < 2)
    metrics['disabled_locked'] = bool(metrics['disabled_before_mod90_rms_deg'] < 1
                                      and metrics['disabled_recovery_mod90_rms_deg'] < 1)
    metrics['acquired'] = bool(metrics['before_true_rms_deg'] < 1)
    metrics['slipped'] = bool(metrics['acquired'] and metrics['locked_mod90']
                              and metrics['quadrant_change_observed'])
    disabled_slipped = bool(metrics['disabled_before_true_rms_deg'] < 1
                            and metrics['disabled_locked']
                            and abs(abs(metrics['disabled_quadrant_change_deg']) - 90) < 2
                            and abs(metrics['disabled_recovery_true_rms_deg'] - 90) < 2)
    metrics['disabled_rejected'] = bool(not disabled_slipped and not metrics['disabled_locked'])
    return metrics


def costas_slip_scenario(jump_degrees=100):
    """Measure the QPSK quadrant change of the model loop against the transmitted carrier phase.

    Same API as costas_scenario: the Q15 inputs, the bit-exact values and phases of
    sync_fixed.costas with the model gains, the metrics of costas_slip_metrics, the reference phase
    in radians (a +jump_degrees step at sample 300) and the phases of the same samples with gains
    (0, 0), a disabled loop that never rotates."""
    _, _, symbols = _source()
    reference = .3 + .006 * np.arange(900)
    reference[300:] += np.deg2rad(jump_degrees)
    samples = _quantize(symbols[:900] * np.exp(1j * reference))
    values, phases = fixed.costas(samples, fixed.costas_gains(.08, .001))
    _, disabled = fixed.costas(samples, (0, 0))
    metrics = costas_slip_metrics(phases, disabled, reference)
    return samples, values, phases, metrics, reference, disabled


def costas_disturbance_metrics(phases, disabled_phases, reference):
    """Named noise/outage fixtures: loss of modulo-quadrant lock and later relocking."""
    streams = [np.asarray(v, dtype=float) for v in (phases, disabled_phases, reference)]
    if (any(v.ndim != 1 for v in streams) or len({len(v) for v in streams}) != 1
            or len(streams[0]) < 950 or not all(np.all(np.isfinite(v)) for v in streams)):
        raise ValueError('Disturbance phase streams must be finite, equal and contain 950 samples')
    windows = {'before': (220, 290), 'excursion': (360, 490), 'recovery': (750, 950)}
    result = {}
    for mode, trajectory in [('enabled', streams[0]), ('disabled', streams[1])]:
        error, mod90 = _slip_phase_error(trajectory, streams[2])
        for name, (start, stop) in windows.items():
            result[f'{mode}_{name}_true_rms_deg'] = float(np.sqrt(np.mean(error[start:stop]**2)))
            result[f'{mode}_{name}_mod90_rms_deg'] = float(np.sqrt(np.mean(mod90[start:stop]**2)))
    result['acquired'] = result['enabled_before_true_rms_deg'] < 1
    result['lost_mod90_lock'] = result['enabled_excursion_mod90_rms_deg'] > 10
    result['relocked_mod90'] = result['enabled_recovery_mod90_rms_deg'] < 1
    result['adjacent_quadrant'] = abs(result['enabled_recovery_true_rms_deg']-90) < 2
    result['disabled_rejected'] = result['disabled_before_true_rms_deg'] > 20
    return result


def costas_disturbance_scenario(kind, disturbed=True):
    """Noise burst or -30.46 dB amplitude fade with a temporary carrier rate change.

    AWGN power is defined before Q15 quantization relative to the unit-energy
    symbols outside the fade. The frequency excursion is continuous in phase.
    This is a selected reproducible fixture, not a probability-of-slip estimate.
    """
    if kind not in ('noise_burst', 'fade_frequency_excursion'):
        raise ValueError('Unknown Costas disturbance')
    _, _, symbols = _source()
    index = np.arange(1000)
    reference = .3 + .006*index
    amplitude = np.ones(1000)
    sigma = np.full(1000, 10**(-30/20))
    if disturbed:
        if kind == 'noise_burst':
            sigma[300:500] = 1
        else:
            amplitude[300:500] = .03
            reference += .01*np.clip(index-350, 0, 150)
    rng = np.random.default_rng(17)
    noise = (rng.normal(size=1000)+1j*rng.normal(size=1000))/np.sqrt(2)*sigma
    wave = amplitude*symbols*np.exp(1j*reference)+noise
    raw = np.rint(np.c_[wave.real, wave.imag]*32768)
    input_clips = int(np.count_nonzero((raw < -131072) | (raw > 131071)))
    samples = _quantize(wave)
    values, phases = fixed.costas(samples, fixed.costas_gains(.08, .001))
    _, disabled = fixed.costas(samples, (0, 0))
    metrics = costas_disturbance_metrics(phases, disabled, reference)
    metrics.update(input_rail_excursions=input_clips, noise_seed=17,
                   outside_esn0_db=30, disturbed=bool(disturbed),
                   excursion_esn0_db=0 if kind == 'noise_burst' and disturbed else 30,
                   fade_amplitude=.03 if kind == 'fade_frequency_excursion' and disturbed else 1,
                   extra_cfo_rad_per_symbol=.01 if kind == 'fade_frequency_excursion' and disturbed else 0)
    return samples, values, phases, metrics, reference, disabled


def timing_metrics(values, disabled_values, symbols):
    def rms(rows, start, stop):
        output = np.array([re + 1j * im for re, im in rows[start:stop]]) / 32768
        return float(np.sqrt(np.mean(abs(output - symbols[start:stop])**2)))
    metrics = {f'{window}_{mode}_rms': rms(rows, *bounds)
               for mode, rows in [('enabled', values), ('disabled', disabled_values)]
               for window, bounds in [('early', (0, 30)), ('before', (220, 290)),
                                      ('excursion', (300, 330)), ('recovery', (550, 700))]}
    metrics.update(acquired=metrics['before_enabled_rms'] < .02
                   and metrics['early_enabled_rms'] > 5 * metrics['before_enabled_rms']
                   and metrics['before_enabled_rms'] < .2 * metrics['before_disabled_rms'],
                   lost=metrics['excursion_enabled_rms'] > .1,
                   recovered=metrics['recovery_enabled_rms'] < .02
                   and metrics['recovery_enabled_rms'] < .2 * metrics['recovery_disabled_rms'])
    return metrics


def timing_scenario():
    cfg, labels, symbols = _source()
    shaped = transmit(cfg, labels)['waveform']
    matched = np.convolve(shaped, rrc_taps(8, 32, 1))
    delay = np.full(len(matched), 1.25)
    delay[32 + 8 * 300:32 + 8 * 360] += 2
    samples = _quantize(cubic(matched, np.arange(len(matched)) - delay))
    values, positions = fixed.timing(samples, 8, 700, fixed.timing_gains(32, .1, .00005))
    disabled, _ = fixed.timing(samples, 8, 700, fixed.timing_gains(32, 0, 0))
    metrics = timing_metrics(values, disabled, symbols)
    return samples, values, positions, metrics, symbols, disabled
