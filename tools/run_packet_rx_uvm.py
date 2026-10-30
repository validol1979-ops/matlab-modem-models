#!/usr/bin/env python3
"""Full OQPSK/MSK/GMSK RX UVM on production waves and immutable payload truth."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

import numpy as np

from regression_evidence import ROOT, begin, finish, write_json, questa_paths, require_unoptimized
from run_rtl import SOURCES
from run_bpsk_uvm import (PILOT, SUMMARY, PROFILE_MARKER, parse_report, prepare_float,
                          poison_truth, poison_profile_warm_truth, float_negative_folders)
from oqpsk_cases import save, vectors as oqpsk_vectors
from cpm_cases import vectors as cpm_vectors
from uvm_floating_reference import rows

PROFILES = {'oqpsk': (1, 4), 'msk': (2, 2), 'gmsk': (3, 2)}
SCENARIOS = ('stream', 'stalled', 'gaps', 'midreset', 'outreset', 'cfgreset')
PACKET_SUMMARY = SUMMARY.replace('BPSK', 'PACKET')
CONTROLS = {
    'numeric': ('NUMERIC', 'INJECT_MISMATCH', 'stream'),
    'acquisition': ('NUMERIC', 'INJECT_ACQUISITION', 'stream'),
    'label_high_bit': ('NUMERIC', 'INJECT_LABEL_HIGH_BIT', 'stream'),
    's_valid_x': ('PROTOCOL', 'INJECT_S_VALID_X', 'stream'),
    's_ready_x': ('PROTOCOL', 'INJECT_S_READY_X', 'stream'),
    'cfg_valid_x': ('PROTOCOL', 'INJECT_CFG_VALID_X', 'stream'),
    'cfg_ready_x': ('PROTOCOL', 'INJECT_CFG_READY_X', 'stream'),
    'm_valid_x': ('PROTOCOL', 'INJECT_M_VALID_X', 'stream'),
    'm_ready_x': ('PROTOCOL', 'INJECT_M_READY_X', 'stream'),
    'data_x': ('NUMERIC', 'INJECT_M_DATA_X', 'stream'),
    'acquisition_x': ('NUMERIC', 'INJECT_ACQUISITION_X', 'stream'),
    'held_data': ('STALL', 'INJECT_HELD_DATA', 'stalled'),
    'input_data': ('NUMERIC', 'INJECT_INPUT_DATA', 'stream'),
}
VECTOR_CONTROLS = {'ser': 'SER', 'warm_ser': 'SER', **{f'float_{k}': 'FLOAT_SER' for k in ('decision', 'errorcount', 'denominator')}}
CPM_CONTROLS = {'acq_epoch': ('ACQ_EPOCH', 'INJECT_ACQ_EPOCH', 'stream')}


def prepare_vectors(folder, profile):
    """Retain the first four existing ordinary channel cases, without tuning waves."""
    folder = Path(folder)
    kind, alphabet = PROFILES[profile]
    if profile == 'oqpsk':
        native = oqpsk_vectors(folder, frames=4, count=768, tracking=False)
        truth_file, output_width = 'tx_symbols.txt', 4
    else:
        native = cpm_vectors(folder, profile == 'gmsk', frames=4, count=768)
        truth_file, output_width = 'tx_bits.txt', 3
    count, frames = 768, 4
    # OQPSK's existing generator appends a separate overload case. Keep only the
    # four ordinary cases in this SER experiment; production defaults stay intact.
    wave = rows(folder/'rx_wave.txt', 3)
    ends = np.flatnonzero(wave[:, 2])+1
    wave = wave[:ends[frames-1]]
    save(folder/'rx_wave.txt', wave)
    output = rows(folder/'rx_out.txt', output_width)[:frames*count]
    save(folder/'rx_out.txt', output)
    truth = rows(folder/truth_file, 2)[:frames*count, 0]
    save(folder/truth_file, [(int(label), int(k % count == count-1)) for k, label in enumerate(truth)])
    tx = rows(folder/'tx_out.txt', 3)
    tx_ends = np.flatnonzero(tx[:, 2])+1
    save(folder/'tx_out.txt', tx[:tx_ends[frames-1]])
    acquisition = rows(folder/'rx_acquire.txt', 3)[:frames]
    save(folder/'rx_acquire_native.txt', acquisition)
    save(folder/'rx_acquire.txt', [(*row, 0, 0, 0) for row in acquisition])
    trace = []
    for k, row in enumerate(output):
        re_value, im_value, label, last = map(int, row) if profile == 'oqpsk' else (int(row[0]), 0, int(row[1]), int(row[2]))
        trace.append((re_value, im_value, 0, 0, 0, 0, label, label, last, int(truth[k])))
    save(folder/'rx_trace.txt', trace)
    errors = [sum(row[7] != row[9] for row in trace[f*count+192:(f+1)*count]) for f in range(frames)]
    if errors != native['payload_errors'][:frames]:
        raise RuntimeError('Native payload truth/error counts changed')
    save(folder/'payload_expected.txt', [(error,) for error in errors])
    prefix = [0]
    for k, row in enumerate(trace[3*count:4*count]):
        prefix.append(prefix[-1]+int(k >= 192 and row[7] != row[9]))
    save(folder/'warm_reset_expected.txt', [(k, max(0, k-192), error) for k, error in enumerate(prefix)])
    model = dict(profile=profile, kind=kind, frames=frames, symbols=frames*count,
                 samples=len(wave), payload_errors=errors, warm_frame=3, warm_samples=5600,
                 warm_wave_samples=int(ends[3]-ends[2]), immutable_warm_error_prefix=prefix,
                 label_bits=(alphabet-1).bit_length(),
                 cfg_label_max=int(rows(folder/'preamble.txt', 1).max()),
                 decoded_label_max=max(row[7] for row in trace), index_max=max(row[6] for row in trace),
                 soft_bits=18 if profile == 'oqpsk' else 36,
                 source='First four production oqpsk_cases/cpm_cases channel frames, original truth and fixed outputs')
    return prepare_float(folder, profile, model)


def parse_packet_report(text, model, scenario, active, returncode=0):
    if scenario not in SCENARIOS:
        raise RuntimeError('Unsupported packet RX scenario')
    partial, terminal = scenario == 'midreset', scenario == 'outreset'
    warm = model['warm_samples'] if partial else model['warm_wave_samples'] if terminal else 0
    result = parse_report(text, model, 'midreset' if terminal else scenario, active, returncode,
                          require_partial_errors=False, warm_samples=warm, summary_pattern=PACKET_SUMMARY)
    widths = re.findall(PROFILE_MARKER, text)
    expected_widths = (model['label_bits'], model['label_bits'], 0, model['cfg_label_max'],
                       model['decoded_label_max'], model['index_max'])
    if len(widths) != 1 or tuple(map(int, widths[0])) != expected_widths:
        raise RuntimeError('Packet full-width label/config coverage mismatch')
    kinds = re.findall(r'UVM RX KIND packet=(\d+) gaps=(\d+)', text)
    if len(kinds) != 1 or int(kinds[0][0]) != model['kind'] or scenario == 'gaps' and int(kinds[0][1]) < 20:
        raise RuntimeError('Packet physical DUT/source gap coverage mismatch')
    inputs = re.findall(r'UVM RX INPUTS checked=(\d+) expected=(\d+) discarded=(\d+)', text)
    expected = model['samples']+(model['warm_wave_samples'] if partial or terminal else 0)
    discarded = model['warm_wave_samples']-warm if partial else 0
    if len(inputs) != 1 or tuple(map(int, inputs[0])) != (result['input_handshakes'], expected, discarded):
        raise RuntimeError('Packet actual waveform input queue conservation mismatch')
    epochs = re.findall(r'UVM RX EPOCHS frames=(\d+) checks=(\d+)',text)
    expected_epochs = (0,0) if model['kind']==1 else (model['frames'],1042*model['frames'])
    if len(epochs)!=1 or tuple(map(int,epochs[0]))!=expected_epochs:
        raise RuntimeError('Packet acquisition token epoch coverage mismatch')
    if result['resets'] != 1+int(partial or terminal or scenario == 'cfgreset') or result['pending_resets'] != int(partial or terminal):
        raise RuntimeError('Packet exact reset/pending coverage mismatch')
    if partial or terminal:
        prefix = result['checked']-model['symbols']
        if not 192 < prefix < 768 or terminal and prefix != 767:
            raise RuntimeError('Packet actual partial/terminal output interval mismatch')
        if (result['discarded_partial_payload'] != prefix-192 or
                result['discarded_partial_errors'] != model['immutable_warm_error_prefix'][prefix]):
            raise RuntimeError('Packet partial SER differs from immutable original prefix')
    elif result['discarded_partial_payload'] or result['discarded_partial_errors'] or result['discarded_expected_symbols']:
        raise RuntimeError('Unexpected packet partial discard')
    result.update(profile=model['profile'], scenario=scenario, label_bits=model['label_bits'],
                  soft_bits=model['soft_bits'], input_gaps=int(kinds[0][1]), expected_inputs=expected,
                  discarded_inputs=discarded, terminal_last_discarded=int(terminal))
    result.update(acquisition_epochs=expected_epochs[0],increment_checks=expected_epochs[1])
    return result


def verify_negative(text, returncode, category):
    if (not returncode or re.search(PACKET_SUMMARY, text) or
            not re.search(r'UVM_FATAL[^\n]*\['+category+r'\]', text) or not re.search(r'UVM_FATAL\s*:\s*[1-9]', text)):
        raise RuntimeError('Packet RX negative control not rejected: '+category)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=('python', 'hdl', 'all'), default='all')
    parser.add_argument('--profile', choices=('all', *PROFILES), default='all')
    args = parser.parse_args()
    require_unoptimized()
    output = ROOT/'build/rtl/packet_rx_uvm'
    output.mkdir(parents=True, exist_ok=True)
    target = output/(('' if args.profile == 'all' else args.profile+'_')+args.suite+'_results.json')
    evidence = begin()
    artifacts, records = [], {}
    write_json(target, dict(evidence, status='RUNNING'))
    try:
        def run(command, work, name):
            result = subprocess.run([str(x) for x in command], cwd=work, capture_output=True, text=True, timeout=120)
            text = result.stdout+result.stderr
            log = work/name
            log.write_text(text)
            artifacts.append(log)
            return result.returncode, text
        if args.suite in ('python', 'all'):
            rc, text = run([sys.executable, ROOT/'tests/test_packet_rx_uvm.py'], output, 'python.log')
            if rc:
                raise RuntimeError('Packet RX Python tests failed: '+text[-6000:])
            records['python'] = 'PASS'
        if args.suite in ('hdl', 'all'):
            bindir, uvm = questa_paths()
            for name, (kind, alphabet) in PROFILES.items():
                if args.profile not in ('all', name):
                    continue
                folder = output/(name+'_vectors')
                model = prepare_vectors(folder, name)
                bad = output/(name+'_negative_ser')
                poison_truth(folder, bad, alphabet=alphabet)
                warm_bad = output/(name+'_negative_warm_ser')
                poison_profile_warm_truth(folder, warm_bad, alphabet=alphabet)
                for source in (folder, bad, warm_bad):
                    artifacts.extend(p for p in source.iterdir() if p.is_file())
                float_bad = float_negative_folders(folder, output, name+'_', name, alphabet, records, artifacts)
                for source in float_bad.values():
                    artifacts.extend(p for p in source.iterdir() if p.is_file())
                for active in (1, 0):
                    work = output/f'{name}_reset_{active}'
                    work.mkdir(parents=True, exist_ok=True)
                    if not (work/'work').is_dir():
                        rc, text = run([bindir/'vlib', 'work'], work, 'vlib.log')
                        if rc:
                            raise RuntimeError('Packet vlib failed: '+text[-2000:])
                    defines = ['+define+UVM_NO_DPI', f'+define+PILOT_PACKET={kind}', f'+define+PILOT_ORDER={alphabet}']
                    if not active:
                        defines.append('+define+RTL_RESET_LOW')
                    rc, text = run([bindir/'vlog', '-64', '-sv', *defines, f'+incdir+{uvm/"src"}',
                                    f'+incdir+{PILOT}', uvm/'src/uvm_pkg.sv', *SOURCES,
                                    ROOT/'rtl/tb/cpm_acquisition_check.sv', ROOT/'rtl/tb/bpsk_rx_uvm_tb.sv'], work, 'compile.log')
                    if rc or re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):', text):
                        raise RuntimeError('Packet RX compile failed/warned: '+text[-6000:])
                    positive, negative = work/'run.do', work/'negative.do'
                    positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
                    negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.extend([positive, negative])
                    base = [bindir/'vsim', '-64', '-c', '-quiet', '-dpicpppath', os.environ.get('DPI_CC', '/usr/bin/gcc'),
                            'work.bpsk_rx_uvm_top', f'-gTABLE_DIR={PILOT/"tables"}', '+SYMBOLS=768',
                            '+CHECK_RESET_PREFIX', '+FLOAT_SER', '+WARM_SAMPLES=5600']
                    for scenario in SCENARIOS:
                        rc, text = run([*base, f'+VECTORS={folder}', f'+SCENARIO={scenario}', '-do', positive.name], work, scenario+'.log')
                        records[f'{name}_{scenario}_reset_{active}'] = parse_packet_report(text, model, scenario, active, rc)
                        print(f'PASS UVM RX {name} {scenario} reset={active}', flush=True)
                    controls = [(key, tag, flag, scenario, folder) for key, (tag, flag, scenario) in CONTROLS.items()]
                    if kind>=2:
                        controls += [(key,tag,flag,scenario,folder) for key,(tag,flag,scenario) in CPM_CONTROLS.items()]
                    controls += [('ser', 'SER', None, 'stream', bad), ('warm_ser', 'SER', None, 'midreset', warm_bad)]
                    controls += [(f'float_{key}', 'FLOAT_SER', None, 'stream', path) for key, path in float_bad.items()]
                    for key, tag, flag, scenario, source in controls:
                        rc, text = run([*base, f'+VECTORS={source}', f'+SCENARIO={scenario}',
                                        *(['+'+flag] if flag else []), '-do', negative.name], work, 'negative_'+key+'.log')
                        verify_negative(text, rc, tag)
                        records[f'{name}_negative_{key}_reset_{active}'] = dict(returncode=rc, detected_tag=tag)
                    records[f'{name}_model_reset_{active}'] = model
        write_json(target, dict(finish(evidence, artifacts), status='PASS', profiles=args.profile, records=records,
                               scope='Full OQPSK/MSK/GMSK RX UVM, physical port widths, independent floating SER on identical Q15 pin waves, exact input/config/acquisition/output handshakes and partial/terminal reset accounting.'))
    except Exception as exc:
        write_json(target, dict(evidence, status='FAIL', error=f'{type(exc).__name__}: {exc}'))
        raise
    print('PASS packet RX UVM '+args.suite)


if __name__ == '__main__':
    main()
