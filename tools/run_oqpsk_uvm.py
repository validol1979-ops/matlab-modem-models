#!/usr/bin/env python3
"""OQPSK TX UVM with actual pin handshakes, reset fences and negative controls."""
import argparse
import os
import re
import subprocess
import sys

import numpy as np

from regression_evidence import ROOT, begin, finish, write_json, questa_paths, require_unoptimized
from run_rtl import SOURCES
from run_bpsk_uvm import PILOT, TX_SCENARIOS, parse_tx_report, verify_tx_negative
from oqpsk_cases import o, save

CONTROLS = {
    'numeric': ('NUMERIC', 'INJECT_MISMATCH', 'stream'),
    'imaginary': ('NUMERIC', 'INJECT_IM_MISMATCH', 'stream'),
    'input_high_bit': ('NUMERIC', 'INJECT_INPUT_HIGH_BIT', 'stream'),
    's_valid_x': ('PROTOCOL', 'INJECT_S_VALID_X', 'stream'),
    's_ready_x': ('PROTOCOL', 'INJECT_S_READY_X', 'stream'),
    'm_valid_x': ('PROTOCOL', 'INJECT_M_VALID_X', 'stream'),
    'm_ready_x': ('PROTOCOL', 'INJECT_M_READY_X', 'stream'),
    'data_x': ('NUMERIC', 'INJECT_M_DATA_X', 'stream'),
    'held_data': ('STALL', 'INJECT_HELD_DATA', 'stalled'),
}


def prepare_vectors(folder):
    folder.mkdir(parents=True, exist_ok=True)
    lengths = [1, 2, 33, 192, 768]
    rng = np.random.default_rng(19)
    symbols, samples = [], []
    for frame, count in enumerate(lengths):
        # Directed short frames include label0, then labels1/2; longer frames
        # exercise every two-bit label before the deterministic random payload.
        labels = np.array([0] if frame == 0 else [1, 2] if frame == 1 else
                          list(range(4)) + rng.integers(0, 4, count-4).tolist())
        wave = o.transmit(labels)
        if len(wave) != 8*count+36:
            raise RuntimeError('OQPSK TX model differs from independent half-symbol tail geometry')
        symbols.extend((int(label), int(k == count-1)) for k, label in enumerate(labels))
        samples.extend((re, im, int(k == len(wave)-1)) for k, (re, im) in enumerate(wave))
    save(folder/'tx_symbols.txt', symbols)
    save(folder/'tx_out.txt', samples)
    return dict(frames=len(lengths), frame_symbols=lengths,
                input_symbols=len(symbols), output_samples=len(samples),
                label_bits=2, samples_per_symbol=8, quadrature_offset=4, fir_tail=32,
                waveform='Production oqpsk_fixed.transmit, signed18 Q15; I at8*k, Q at8*k+4',
                configuration='NOT_APPLICABLE: OQPSK_TX has no configuration ports')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=('python', 'hdl', 'all'), default='all')
    args = parser.parse_args()
    require_unoptimized()
    output = ROOT/'build/rtl/oqpsk_uvm'
    output.mkdir(parents=True, exist_ok=True)
    evidence = begin()
    target = output/f'{args.suite}_results.json'
    artifacts, records = [], {}
    write_json(target, dict(evidence, status='RUNNING'))
    try:
        def run(command, work, name):
            result = subprocess.run([str(x) for x in command], cwd=work,
                                    capture_output=True, text=True, timeout=90)
            text = result.stdout+result.stderr
            log = work/name
            log.write_text(text)
            artifacts.append(log)
            return result.returncode, text

        if args.suite in ('python', 'all'):
            rc, text = run([sys.executable, ROOT/'tests/test_oqpsk_uvm_evidence.py'],
                           output, 'python.log')
            if rc:
                raise RuntimeError('OQPSK UVM evidence tests failed: '+text[-6000:])
            records['python'] = 'PASS'
        if args.suite in ('hdl', 'all'):
            folder = output/'vectors'
            model = prepare_vectors(folder)
            artifacts.extend(folder.glob('*.txt'))
            bindir, uvm = questa_paths()
            for active in (1, 0):
                work = output/f'reset_{active}'
                work.mkdir(parents=True, exist_ok=True)
                if not (work/'work').is_dir():
                    rc, text = run([bindir/'vlib', 'work'], work, 'vlib.log')
                    if rc:
                        raise RuntimeError('OQPSK vlib failed: '+text[-3000:])
                defines = ['+define+UVM_NO_DPI']+(['+define+RTL_RESET_LOW'] if active == 0 else [])
                rc, text = run([bindir/'vlog', '-64', '-sv', *defines,
                                f'+incdir+{uvm/"src"}', f'+incdir+{PILOT}',
                                f'+incdir+{ROOT/"rtl/tb"}', uvm/'src/uvm_pkg.sv',
                                *SOURCES, ROOT/'rtl/tb/oqpsk_tx_uvm_tb.sv'], work, 'compile.log')
                if rc or re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):', text):
                    raise RuntimeError('OQPSK UVM compile failed/warned: '+text[-6000:])
                positive, negative = work/'run.do', work/'negative.do'
                positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
                negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                artifacts.extend([positive, negative])
                base = [bindir/'vsim', '-64', '-c', '-quiet', '-dpicpppath',
                        os.environ.get('DPI_CC', '/usr/bin/gcc'), 'work.oqpsk_tx_uvm_top',
                        f'+VECTORS={folder}']
                for scenario in TX_SCENARIOS:
                    rc, text = run([*base, f'+SCENARIO={scenario}', '-do', positive.name],
                                   work, f'{scenario}.log')
                    records[f'tx_{scenario}_reset_{active}'] = parse_tx_report(
                        text, model, scenario, active, rc, modulation='OQPSK')
                    print(f'PASS UVM OQPSK TX {scenario} reset={active}', flush=True)
                for name, (tag, flag, scenario) in CONTROLS.items():
                    rc, text = run([*base, f'+SCENARIO={scenario}', f'+{flag}', '-do', negative.name],
                                   work, f'negative_{name}.log')
                    verify_tx_negative(text, rc, tag, modulation='OQPSK')
                    records[f'tx_negative_{name}_reset_{active}'] = dict(returncode=rc, detected_tag=tag)
                records[f'tx_model_reset_{active}'] = model
        write_json(target, dict(finish(evidence, artifacts), status='PASS', pilot='tx', records=records,
                               scope='Full UVM OQPSK TX: two-bit labels, I/Q fixed waveform, independent8*N+36 geometry, actual input/output handshakes, gaps/backpressure and pending/terminal-output resets. OQPSK RX, CPM and section5 UVM remain open.'))
    except Exception as exc:
        write_json(target, dict(evidence, status='FAIL', error=f'{type(exc).__name__}: {exc}'))
        raise
    print('PASS OQPSK UVM '+args.suite)


if __name__ == '__main__':
    main()
