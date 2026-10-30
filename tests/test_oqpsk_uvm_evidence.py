"""OQPSK TX UVM acceptance rejects incomplete counts, resets and false negatives."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'tools'))
from run_oqpsk_uvm import CONTROLS, prepare_vectors
from run_bpsk_uvm import TX_SCENARIOS, parse_tx_report, verify_tx_negative
from run_tests import verified_oqpsk_uvm_artifacts
from regression_evidence import begin, finish

MODEL = dict(frames=5, frame_symbols=[1, 2, 33, 192, 768],
             input_symbols=996, output_samples=8148)


def report_text(scenario='stream'):
    mid, out = scenario == 'midreset', scenario == 'outreset'
    reset = mid or out
    warm_inputs = 768 if mid else 33 if out else 0
    warm_outputs = 6180 if mid else 300 if out else 0
    before = 111 if mid else 299 if out else 0
    inputs = 996+(16 if mid else 33 if out else 0)
    outputs = 8148+before
    rows = '\n'.join(f'UVM TX FRAME frame={f} inputs={n} samples={count}'
                     for f, (n, count) in enumerate(zip([1, 2, 33, 192, 768], [44, 52, 300, 1572, 6180])))
    return (rows+'\n'+f'UVM OQPSK TX checked={outputs} frames=5 input={inputs} '
            f'discarded={warm_outputs-before} discarded_inputs={warm_inputs-(inputs-996)} '
            f'expected={8148+warm_outputs} expected_inputs={996+warm_inputs} '
            f'resets={1+int(reset)} before_reset={before} pending_resets={int(reset)} held_last_resets={int(out)}\n'
            f'UVM TX HANDSHAKES input={inputs} output={outputs} input_stalls=7000 '
            f'output_stalls={100 if scenario in ("stalled", "midreset", "outreset") else 0} '
            f'ready_gaps={232 if scenario=="gaps" else 0} pending_resets={int(reset)}\n'
            'UVM TX LABELS bits=2 mask=15\nUVM_ERROR : 0\nUVM_FATAL : 0\n')


class TestOqpskUvmEvidence(unittest.TestCase):
    def test_vectors_match_independent_float_transmitter_and_geometry(self):
        import modem_core as floating
        config = floating.load_config(ROOT/'modems/oqpsk_2_sps_timing_recovery_2019_12_05/config.json')
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            model = prepare_vectors(folder)
            self.assertEqual({k: model[k] for k in MODEL}, MODEL)
            symbols = np.loadtxt(folder/'tx_symbols.txt', skiprows=1, dtype=int)
            wave = np.loadtxt(folder/'tx_out.txt', skiprows=1, dtype=int)
            self.assertEqual(set(symbols[:, 0]), {0, 1, 2, 3})
            self.assertEqual(np.flatnonzero(wave[:, 2]).tolist(), [43, 95, 395, 1967, 8147])
            start_input = start_output = 0
            for count in MODEL['frame_symbols']:
                labels = symbols[start_input:start_input+count, 0]
                expected = floating.transmit(config, labels)['waveform']
                actual = wave[start_output:start_output+8*count+36, :2]/2**15
                self.assertEqual(len(expected), len(actual))
                self.assertLess(np.max(abs(actual[:, 0]+1j*actual[:, 1]-expected)), 2e-4)
                start_input += count
                start_output += 8*count+36
            # One label0: I and Q pulses have identical signs and a four-sample offset.
            self.assertGreater(np.max(abs(wave[:44, 0])), 1000)
            np.testing.assert_array_equal(wave[4:44, 1], wave[:40, 0])

    def test_every_scenario_and_reset_polarity(self):
        for active in (1, 0):
            for scenario in TX_SCENARIOS:
                row = parse_tx_report(report_text(scenario), MODEL, scenario, active, modulation='OQPSK')
                self.assertEqual(row['profile'], 'oqpsk_tx')
                self.assertEqual(row['checked']+row['discarded_expected_samples'], row['expected_samples'])
                self.assertEqual(row['labels_seen_mask'], 15)

    def test_rejects_false_success_missing_duplicate_or_wrong_geometry(self):
        text = report_text()
        for bad in (text+text, text.replace('UVM_FATAL : 0', 'UVM_FATAL : 1'),
                    text.replace('samples=44', 'samples=40'), text.replace('mask=15', 'mask=3'),
                    text.replace('bits=2', 'bits=1'), text.replace('UVM OQPSK TX', 'UVM BPSK TX'),
                    text.replace('frames=5', 'frames=4'), text.replace('input=996', 'input=995'),
                    text.replace('output=8148', 'output=8147'), text.replace('input_stalls=7000', 'input_stalls=0')):
            with self.subTest(bad=bad), self.assertRaises(RuntimeError):
                parse_tx_report(bad, MODEL, 'stream', 1, modulation='OQPSK')
        with self.assertRaises(RuntimeError):
            parse_tx_report(text, MODEL, 'stream', 1, 13, modulation='OQPSK')
        with self.assertRaises(RuntimeError):
            parse_tx_report(text, dict(MODEL, output_samples=8128), 'stream', 1, modulation='OQPSK')
        with self.assertRaises(RuntimeError):
            parse_tx_report(text, MODEL, 'cfgreset', 1, modulation='OQPSK')

    def test_rejects_reset_without_real_pending_or_terminal_discard(self):
        for scenario, edits in [
                ('midreset', [('before_reset=111', 'before_reset=0'), ('discarded_inputs=752', 'discarded_inputs=0'),
                              ('pending_resets=1', 'pending_resets=0'), ('resets=2', 'resets=1')]),
                ('outreset', [('before_reset=299', 'before_reset=298'), ('discarded=1', 'discarded=2'),
                              ('held_last_resets=1', 'held_last_resets=0')]),
                ('stalled', [('output_stalls=100', 'output_stalls=0')]),
                ('gaps', [('ready_gaps=232', 'ready_gaps=0')])]:
            for old, new in edits:
                with self.subTest(scenario=scenario, old=old), self.assertRaises(RuntimeError):
                    parse_tx_report(report_text(scenario).replace(old, new), MODEL, scenario, 0, modulation='OQPSK')

    def test_negative_requires_correct_fatal_and_no_success(self):
        for tag in ('NUMERIC', 'PROTOCOL', 'STALL'):
            text = f'UVM_FATAL @ 1: reporter [{tag}] fault\nUVM_FATAL : 1\n'
            verify_tx_negative(text, 13, tag, modulation='OQPSK')
            for bad, rc in ((text, 0), (text.replace(f'[{tag}]', '[OTHER]'), 13),
                            (text.replace('UVM_FATAL : 1', 'UVM_FATAL : 0'), 13),
                            (text+report_text(), 13)):
                with self.subTest(tag=tag, bad=bad), self.assertRaises(RuntimeError):
                    verify_tx_negative(bad, rc, tag, modulation='OQPSK')

    def test_parent_requires_all_scenarios_controls_and_unchanged_artifacts(self):
        records = {}
        for active in (1, 0):
            for scenario in TX_SCENARIOS:
                records[f'tx_{scenario}_reset_{active}'] = parse_tx_report(
                    report_text(scenario), MODEL, scenario, active, modulation='OQPSK')
            for name, (tag, _, _) in CONTROLS.items():
                records[f'tx_negative_{name}_reset_{active}'] = dict(returncode=13, detected_tag=tag)
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory)/'pilot.log'
            log.write_text('OQPSK coverage fixture')
            original = dict(finish(begin(), [log]), status='PASS', pilot='tx', records=records)
            self.assertEqual(verified_oqpsk_uvm_artifacts(original), [log])
            for fault in ('missing_scenario', 'wrong_profile', 'bool_reset', 'missing_control', 'wrong_tag', 'rc0',
                          'bool_rc', 'labels', 'no_artifacts', 'wrong_scope'):
                data = copy.deepcopy(original)
                if fault == 'missing_scenario': data['records'].pop('tx_outreset_reset_0')
                elif fault == 'wrong_profile': data['records']['tx_stream_reset_1']['profile'] = 'bpsk_tx'
                elif fault == 'bool_reset': data['records']['tx_stream_reset_1']['reset_active'] = True
                elif fault == 'missing_control': data['records'].pop('tx_negative_imaginary_reset_1')
                elif fault == 'wrong_tag': data['records']['tx_negative_input_high_bit_reset_0']['detected_tag'] = 'STALL'
                elif fault == 'rc0': data['records']['tx_negative_numeric_reset_1']['returncode'] = 0
                elif fault == 'bool_rc': data['records']['tx_negative_numeric_reset_1']['returncode'] = True
                elif fault == 'labels': data['records']['tx_stalled_reset_0']['labels_seen_mask'] = 3
                elif fault == 'no_artifacts': data['artifact_hashes'] = {}
                else: data['pilot'] = 'both'
                with self.subTest(fault=fault), self.assertRaises(RuntimeError):
                    verified_oqpsk_uvm_artifacts(data)
            log.write_text('changed')
            with self.assertRaisesRegex(RuntimeError, 'artifact'):
                verified_oqpsk_uvm_artifacts(original)


if __name__ == '__main__':
    unittest.main()
