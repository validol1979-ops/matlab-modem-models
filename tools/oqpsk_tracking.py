"""Known-carrier OQPSK phase excursion, with the same acquired front end as control."""
from pathlib import Path
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import oqpsk_fixed as fixed

FREQUENCY = .00015             # turns per input sample
INITIAL_PHASE = .25           # radians
JUMP_SYMBOL = 300
JUMP_DEGREES = 30
WINDOWS = {'before': (220, 290), 'excursion': (310, 350), 'recovery': (650, 768)}


def metrics(result, disabled, labels):
    """Normalized RMS symbol error, measured against the actual transmitted labels.

    Tolerances are 4% for tracking and 15% for the excursion. Initial acquisition
    has its own known delay/carrier bounds. This is not a cycle-slip detector.
    """
    truth = np.array([complex(*fixed.LABELS[int(label)]) for label in labels]) * fixed.T / 32768
    report = {}
    for name, record in [('enabled', result), ('disabled', disabled)]:
        output = np.array([complex(re, im) for re, im in record['values']]) / 32768
        for window, (start, stop) in WINDOWS.items():
            report[f'{window}_{name}_evm'] = float(np.sqrt(
                np.mean(abs(output[start:stop] - truth[start:stop])**2)
                / np.mean(abs(truth[start:stop])**2)))
    acq = result['acquisition']
    # The matched filter adds 16 samples; symbol 0's RX peak at 32 corresponds
    # to input sample 16, where this known carrier has its initial symbol phase.
    expected_phase = INITIAL_PHASE + 2 * np.pi * FREQUENCY * 16
    report['acquisition_delay_samples'] = acq['delay'] / 65536
    report['acquisition_frequency_error'] = abs(acq['frequency'] / 2**32 - FREQUENCY)
    report['acquisition_phase_error_rad'] = float(abs(np.angle(np.exp(1j * (
        acq['phase'] * (2 * np.pi / 2**32) - expected_phase)))))
    report['acquired'] = (report['acquisition_delay_samples'] < .5
                          and report['acquisition_frequency_error'] < 5e-6
                          and report['acquisition_phase_error_rad'] < .02
                          and report['before_enabled_evm'] < .04)
    report['lost'] = report['excursion_enabled_evm'] > .15
    report['recovered'] = (report['recovery_enabled_evm'] < .04
                           and report['recovery_enabled_evm'] < .2 * report['recovery_disabled_evm'])
    return report


def scenario(preamble, count=768):
    if count < 768 or count > 2048:
        raise ValueError('Tracking scenario needs 768..2048 symbols')
    labels = np.random.default_rng(91).integers(0, 4, count)
    labels[:fixed.TRAIN] = preamble
    tx = fixed.transmit(labels)
    carrier = INITIAL_PHASE + 2 * np.pi * FREQUENCY * np.arange(len(tx))
    carrier[16 + fixed.SPS * JUMP_SYMBOL:] += np.deg2rad(JUMP_DEGREES)
    wave = (np.array([complex(re, im) for re, im in tx]) / 32768) * np.exp(1j * carrier)
    samples = fixed.quantize(wave)
    result = fixed.receive(samples, preamble, count)
    disabled = fixed.receive(samples, preamble, count, feedback=False)
    report = metrics(result, disabled, labels)
    return labels, tx, samples, result, disabled, report
