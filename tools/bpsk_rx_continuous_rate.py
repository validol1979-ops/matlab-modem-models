#!/usr/bin/env python3
"""Finite uninterrupted-offer BPSK RX experiment using the existing integer scoreboard.

Writes only to a new output directory; does not replace any acceptance evidence.
The simulation measures logical cycles, not hardware clock frequency.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

from bpsk_cases import receiver_vectors
from regression_evidence import ROOT, questa_paths
from run_rtl import SOURCES
from bpsk_verilator import build as verilator_build, command as verilator_command

PILOT = ROOT / 'rtl/modems/bpsk_costas_2008_08_25'
GUARD = '    if(!LOOPBACK&&!stall_mode&&boundary_cycles>=32) `uvm_fatal("THROUGHPUT","Input stalled beyond the 32 matched-filter tail clocks")\n'
PATTERN = (r'RX RATE accepted=(\d+) offered=(\d+) blocked=(\d+) tail_blocked=(\d+) '
           r'other_blocked=(\d+) frames=(\d+) boundaries=(\d+) min_gap=(\d+) '
           r'max_gap=(\d+) tail_checks=(\d+)')
STATE_PATTERN = r'RX BLOCK STATES wait=(\d+) acquire=(\d+) track=(\d+) retire=(\d+)'
BLOCK_PATTERN = r'RX BUFFER BLOCK frame=(\d+) buffer=(\d+) first=(\d+) last=(\d+) cycles=(\d+) release=(\d+)'
EVENT_PATTERN = r'RX EVENT cycle=(\d+) kind=(acquisition_done|tracking_done|retire) process_buffer=(\d+)'
ACQUISITION_PATTERN = r'RX ACQUISITION start=(\d+) done=(\d+) A=(\d+)'
RESERVE_PATTERN = r'RX RESERVE cycle=(\d+) frame=(\d+) buffer=(\d+)'


def run(command, cwd, log, *, failure=False):
    p = subprocess.run([str(v) for v in command], cwd=cwd, capture_output=True,
                       text=True, timeout=300)
    text = p.stdout + p.stderr
    log.write_text(text)
    if failure:
        if (p.returncode != 13 or not re.search(r'UVM_FATAL[^\n]*\[NUMERIC\]', text)
                or 'PASS BPSK receiver:' in text):
            raise RuntimeError(f'Invalid negative control rc={p.returncode}: {log}')
    elif p.returncode != 0 or re.search(r'UVM_(?:ERROR|FATAL)|\*\* (?:Error|Fatal)', text):
        raise RuntimeError(f'Command failed rc={p.returncode}: {log}\n{text[-2000:]}')
    return text


def checked_rate(text, model, active, *, short_samples=2048):
    if re.search(r'UVM_(?:ERROR|FATAL)|\*\* (?:Error|Fatal)', text):
        raise RuntimeError('Receiver reported an error')
    if (model['frames'] < 2 or model['symbols'] % model['frames'] or
            not 192 <= model['symbols'] // model['frames'] <= 2048):
        raise RuntimeError('Invalid configured frame length')
    buffers = 3 if 8 * (model['symbols'] // model['frames']) + 96 <= short_samples else 2
    matches = re.findall(PATTERN, text)
    if len(matches) != 1 or 'PASS BPSK receiver:' not in text:
        raise RuntimeError('Missing scoreboard/rate summary')
    names = ('accepted', 'offered', 'blocked', 'tail_blocked', 'other_blocked',
             'frames', 'boundaries', 'min_gap', 'max_gap', 'tail_checks')
    row = dict(zip(names, map(int, matches[0])))
    pass_count = re.search(r'PASS BPSK receiver: (\d+) symbols, (\d+) acquisitions, (\d+) payload errors', text)
    if not pass_count or tuple(map(int, pass_count.groups())) != (
            model['symbols'], model['frames'], sum(model['payload_errors'])):
        raise RuntimeError('Fixed-model scoreboard incomplete')
    if (row['accepted'] != model['samples'] or row['frames'] != model['frames'] or row['boundaries'] != model['frames'] - 1 or
        row['offered'] != row['accepted'] + row['blocked'] or
        row['blocked'] != row['tail_blocked'] + row['other_blocked'] or
        row['tail_checks'] != 32 * model['frames'] or row['min_gap'] < 32 or
        row['max_gap'] < row['min_gap'] or row['max_gap'] > 32 + row['other_blocked'] or
        (row['other_blocked'] > 0 and row['max_gap'] == 32) or
        row['tail_blocked'] != 32 * (model['frames'] - 1)):
        raise RuntimeError('Missing boundary or FIR-flush coverage')
    if row['other_blocked'] != 0 or row['min_gap'] != 32 or row['max_gap'] != 32:
        raise RuntimeError('Additional blockage or non-32 boundary gap')
    acquisition = [dict(zip(('start','done','A'),map(int,match)))
                   for match in re.findall(ACQUISITION_PATTERN,text)]
    if (len(acquisition) != model['frames'] or
        any(r['start'] >= r['done'] or r['done']-r['start'] != r['A'] or r['A'] > 686 for r in acquisition) or
        any(a['done'] >= b['start'] for a,b in zip(acquisition,acquisition[1:]))):
        raise RuntimeError('Incomplete acquisition latency or A exceeds BPSK budget 686')
    row['acquisition_cycles'] = acquisition
    row['a_min'] = min(r['A'] for r in acquisition)
    row['a_max'] = max(r['A'] for r in acquisition)
    row['queued_processing_period'] = row['a_max'] + 882

    reservations = [dict(zip(('cycle', 'frame', 'buffer'), map(int, match)))
                    for match in re.findall(RESERVE_PATTERN, text)]
    if (len(reservations) != model['frames'] or
        any(r['frame'] != i or r['buffer'] != i % buffers for i, r in enumerate(reservations)) or
        any(a['cycle'] >= b['cycle'] for a, b in zip(reservations, reservations[1:]))):
        raise RuntimeError('Incomplete or out-of-order buffer assignments')
    states = re.findall(STATE_PATTERN, text)
    if len(states) != 1:
        raise RuntimeError('Missing state breakdown')
    state_counts = dict(zip(('wait', 'acquire', 'track', 'retire'), map(int, states[0])))
    if sum(state_counts.values()) != row['other_blocked']:
        raise RuntimeError('State breakdown differs from non-tail blockage')
    blocks = [dict(zip(('frame', 'buffer', 'first', 'last', 'cycles', 'release'), map(int, match)))
              for match in re.findall(BLOCK_PATTERN, text)]
    if (sum(block['cycles'] for block in blocks) != row['other_blocked'] or
        any(block['cycles'] <= 0 or block['last'] - block['first'] + 1 != block['cycles'] or
            block['release'] != block['last'] + 1 or block['frame'] < 1 or block['frame'] >= model['frames'] or
            block['buffer'] != block['frame'] % buffers or
            block['release'] != reservations[block['frame']]['cycle'] for block in blocks) or
        any(a['release'] > b['first'] for a, b in zip(blocks, blocks[1:]))):
        raise RuntimeError('Invalid buffer blockage intervals')
    events = [dict(cycle=int(cycle), kind=kind, buffer=int(buffer))
              for cycle, kind, buffer in re.findall(EVENT_PATTERN, text)]
    if (len(events) != 3 * model['frames'] or
        [event['kind'] for event in events] != ['acquisition_done', 'tracking_done', 'retire'] * model['frames'] or
        any(event['buffer'] != reservations[index // 3]['buffer'] for index, event in enumerate(events)) or
        any(a['cycle'] >= b['cycle'] for a, b in zip(events, events[1:]))):
        raise RuntimeError('Incomplete or out-of-order receiver lifecycle')
    if any(r['cycle'] >= events[3*i]['cycle'] or
           (i >= buffers and events[3*(i-buffers)+2]['cycle'] >= r['cycle'])
           for i, r in enumerate(reservations)):
        raise RuntimeError('Buffer reused before retirement or processed before reservation')
    if any(not any(event['kind'] == 'retire' and event['buffer'] == block['buffer'] and
                   event['cycle'] == block['last'] for event in events) for block in blocks):
        raise RuntimeError('Blocked buffer not retired on last blocked cycle')
    row['state_counts'] = state_counts
    row['buffer_count'] = buffers
    row['reservations'] = reservations
    row['buffer_blocks'] = blocks
    row['lifecycle_events'] = events
    row['reset_active'] = active
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--backend', choices=('questa','verilator'), default='questa')
    parser.add_argument('--output', type=Path, required=True, help='new isolated directory')
    args = parser.parse_args()
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    source = (ROOT / 'rtl/tb/bpsk_rx_tb.sv').read_text()
    if source.count(GUARD) != 1:
        raise RuntimeError('Historical stall ceiling not found exactly once')
    bench = out / 'bpsk_rx_tb_rate_copy.sv'
    bench.write_text(source.replace(GUARD, ''))
    vectors = out / 'vectors'
    cases = [('burst_192', 192, 4), ('burst_768', 768, 4), ('burst_2048', 2048, 4),
             ('series_192', 192, 16), ('series_192_d0', 192, 16)]
    models = {name: receiver_vectors(vectors / name, frames=frames, count=n, seed=19,
                                     frame_padding=0 if name.endswith('_d0') else None)
              for name, n, frames in cases}
    if args.backend == 'questa':
        bindir, uvm = questa_paths()
        run([bindir/'vlib', 'work'], out, out/'vlib.log')
        run([bindir/'vlog', '-64', '-sv', '+define+UVM_NO_DPI', f'+incdir+{uvm / "src"}',
             f'+incdir+{PILOT}', uvm/'src/uvm_pkg.sv', *SOURCES, bench,
             ROOT/'rtl/tb/bpsk_rx_rate_tb.sv', ROOT/'rtl/tb/bpsk_rx_buffers_tb.sv'], out, out/'compile.log')
        (out/'normal.do').write_text('onfinish stop\nonerror {quit -code 1}\nrun -all\nquit -code 0\n')
        (out/'negative.do').write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
    rows = []
    for name, symbols, frames in cases:
        model = models[name]
        for active in (1, 0):
            if args.backend == 'verilator':
                binary = verilator_build(out/f'{name}_reset{active}', 'bpsk_rx_rate_tb',
                    [bench, ROOT/'rtl/tb/bpsk_rx_rate_tb.sv'],
                    dict(RESET_ACTIVE=active,SYMBOLS=symbols,FRAMES=frames))
                base = [binary, f'+VECTORS={vectors/name}']
                text = verilator_command(base, ROOT, out/f'{name}_{active}.log')
            else:
                base = [bindir/'vsim', '-64', '-c', '-quiet', '-dpicpppath', os.environ.get('DPI_CC', '/usr/bin/gcc'),
                        'work.bpsk_rx_rate_tb', f'-gRESET_ACTIVE={active}', f'-gSYMBOLS={symbols}',
                        f'-gFRAMES={frames}', f'-gTABLE_DIR={PILOT / "tables"}', f'+VECTORS={vectors / name}']
                text = run([*base, '-do', 'normal.do'], out, out/f'{name}_{active}.log')
            row = checked_rate(text, model, active)
            row['symbols_per_frame'] = symbols
            row['scenario'] = name
            rows.append(row)
            if symbols == 768:
                if args.backend == 'verilator':
                    verilator_command([*base,'+INJECT_MISMATCH'],ROOT,out/f'negative_{active}.log',negative=True)
                else:
                    run([*base, '+INJECT_MISMATCH', '-do', 'negative.do'], out,
                        out/f'negative_{active}.log', failure=True)
    for active in (1, 0):
        if args.backend == 'verilator':
            binary = verilator_build(out/f'buffers_reset{active}', 'bpsk_rx_buffers_tb',
                [ROOT/'rtl/tb/bpsk_rx_buffers_tb.sv'],dict(RESET_ACTIVE=active))
            text = verilator_command([binary],ROOT,out/f'buffers_{active}.log')
        else:
            text = run([bindir/'vsim', '-64', '-c', '-quiet', '-dpicpppath', os.environ.get('DPI_CC', '/usr/bin/gcc'), 'work.bpsk_rx_buffers_tb',
                        f'-gRESET_ACTIVE={active}', f'-gTABLE_DIR={PILOT / "tables"}', '-do', 'normal.do'],
                       out, out/f'buffers_{active}.log')
        if 'PASS BPSK RX buffer guards' not in text:
            raise RuntimeError('Missing buffer protocol/reset coverage')
    (out/'results.json').write_text(json.dumps({'status': 'PASS', 'backend': args.backend, 'scope': 'finite unbroken offered input; fixed-model scoreboard; no physical timing claim',
                                                 'models': models, 'rows': rows}, indent=2) + '\n')
    print('PASS BPSK uninterrupted-offer rate:', out/'results.json')


if __name__ == '__main__':
    main()
