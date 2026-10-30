#!/usr/bin/env python3
"""Measured Costas/Gardner/LMS/NLMS/RLS interface cycles, not a timing model."""
import argparse
import csv
from pathlib import Path
import re
import subprocess

import numpy as np

from regression_evidence import ROOT, begin, digest, finish, questa_paths, require_unoptimized, write_json
from run_rtl import SOURCES
from run_stream_rates import longest_burst

FRAMES = 32
MODES = [('ready', 0, False), ('pressure_5of8', 0, True), ('frame_gap4', 4, False)]
COLUMNS = ('cycle,cfg_valid,cfg_ready,configured,s_valid,s_ready,s_last,'
           'm_valid,m_ready,m_last,w_valid,w_ready,w_last,error').split(',')


def profiles():
    # Keep ordinary dictionaries so the report states every selected configuration.
    rows = [dict(name='costas', kind=0)]
    rows += [dict(name=f'gardner_sps{sps}', kind=1, sps=sps) for sps in (4, 8)]
    for mode, kind in (('lms', 2), ('nlms', 3), ('rls', 4)):
        for taps in ((1, 3, 8) if mode == 'rls' else (1, 3, 8, 16)):
            rows.append(dict(name=f'{mode}_t{taps}', kind=kind, taps=taps,
                             log2n=(taps-1).bit_length()))
    return rows


def first_frame(path):
    with path.open() as fd:
        total = int(next(fd)); rows = []
        for line in fd:
            row = tuple(map(int, line.split()))
            rows.append(row)
            if row[-1] == 1:
                return rows, total
    raise RuntimeError(f'No first transaction: {path}')


def prepare(folder, spec):
    """Only existing generators supply values. Their expected outputs are never read."""
    folder.mkdir(parents=True, exist_ok=True)
    kind = spec['kind']
    if kind == 0:
        from sync_cases import build_costas
        build_costas(folder, (.08, .001), 1, np.random.default_rng(19))
        source, config = folder/'cl_in.txt', folder/'cl_cfg.txt'
    elif kind == 1:
        from sync_cases import build_timing
        build_timing(folder, (spec['sps'], 64, 32, .05, .00005), 1, np.random.default_rng(41))
        source, config = folder/'gt_in.txt', folder/'gt_cfg.txt'
    elif kind in (2, 3):
        from lms_cases import vectors
        vectors(folder, 'lms' if kind == 2 else 'nlms', .05 if kind == 2 else .3,
                .01, spec['taps'], transactions=1, seed=19)
        source, config = folder/'in.txt', folder/'cfg.txt'
    else:
        from rls_cases import vectors
        vectors(folder, .995, .01, spec['taps'], transactions=1, seed=19)
        source, config = folder/'in.txt', folder/'cfg.txt'
    original, _ = first_frame(source)
    selected = original if kind == 1 else original[:128]
    if kind != 1 and len(selected) != 128:
        raise RuntimeError('Representative source prefix is too short')
    values = [row[:4] if kind >= 2 else (*row[:2], 0, 0) for row in selected]
    if any(len(row) != 4 or any(not -131072 <= v <= 131071 for v in row) for row in values):
        raise RuntimeError('Invalid raw integer input')
    rate_input, rate_config = folder/'rate_in.txt', folder/'rate_cfg.txt'
    rate_input.write_text(str(len(values))+'\n'+'\n'.join(' '.join(map(str, row)) for row in values)+'\n')
    rate_config.write_bytes(config.read_bytes())
    metadata = dict(spec, input_length=len(values), output_count=64 if kind == 1 else len(values),
                    weights_per_frame=spec.get('taps', 0), original_first_frame_length=len(original),
                    original_input_hash=digest(source), original_config_hash=digest(config),
                    input_hash=digest(rate_input), config_hash=digest(rate_config),
                    stimulus='Original first transaction; unchanged integer values. Non-Gardner prefix128 with new measurement TLAST; repeated32 times.')
    return metadata, [source, config, rate_input, rate_config]


def channel_stats(cycles, frames, expected_length, frame_count):
    if len(frames) != frame_count or any(len(f) != expected_length for f in frames):
        raise RuntimeError('Accepted per-frame count mismatch')
    records = []
    for frame in frames:
        middle = frame[len(frame)//4:3*len(frame)//4] or frame
        records.append(dict(first=frame[0], last=frame[-1], transfers=len(frame),
                            middle_span_rate=len(middle)/(middle[-1]-middle[0]+1),
                            middle_max_gap=max((b-a for a, b in zip(middle, middle[1:])), default=1)))
    start, stop = frame_count//4, 3*frame_count//4
    central_span = records[stop]['first']-records[start]['first']
    central_count = sum(f['transfers'] for f in records[start:stop])
    span = cycles[-1]-cycles[0]+1
    return dict(accepted=len(cycles), first=cycles[0], last=cycles[-1], span_cycles=span,
                accepted_span_rate=len(cycles)/span,
                interaccept_rate=(len(cycles)-1)/(span-1),
                longest_consecutive_burst=longest_burst(cycles), frames=records,
                interaccept_min_gap=min(b-a for a, b in zip(cycles, cycles[1:])),
                interaccept_max_gap=max(b-a for a, b in zip(cycles, cycles[1:])),
                frame_start_periods=[b['first']-a['first'] for a, b in zip(records, records[1:])],
                boundary_idle_cycles=[b['first']-a['last']-1 for a, b in zip(records, records[1:])],
                central_periods=dict(first_frame=start, stop_frame=stop, cycles=central_span,
                                     transfers=central_count, rate=central_count/central_span))


def budgets(spec, measured):
    """Explicit rate units and assumptions, with no FPGA clock feasibility assertion."""
    rin = measured['input']['central_periods']['rate']
    rout = measured['output']['central_periods']['rate']
    result = dict(hypothetical_clock_mhz=100,
                  input_at_100mhz_msamples_per_second=100*rin,
                  output_at_100mhz_mtransfers_per_second=100*rout,
                  required_clock_mhz_for_100msps_raw_input=100/rin)
    if spec['kind'] == 1:
        sps = spec['sps']; target = 100/sps
        result.update(output_unit='interpolated timing symbols', configured_samples_per_symbol=sps,
                      symbol_target_mbaud=target, required_clock_mhz_for_symbol_target=target/rout,
                      required_clock_mhz_for_both_targets=max(100/rin, target/rout),
                      finite_input_to_output_ratio=spec['input_length']/spec['output_count'])
    else:
        result.update(output_unit='rotated complex samples' if spec['kind'] == 0 else 'prediction/error tuples',
                      conditional_symbol_placement=[dict(assumed_input_samples_per_symbol=sps,
                          symbol_target_mbaud=100/sps, required_clock_mhz=(100/sps)/rin) for sps in (1, 4, 8)],
                      symbol_scope='One invocation per symbol is a system placement assumption; these interfaces have no intrinsic oversampling setting.')
    return result


def analyze(path, spec, gap, pressure, frame_count=FRAMES):
    """Stream every CSV row; retain only accepted timestamps, bounded by frame counts."""
    if frame_count < 4 or any(spec[k] < 4 for k in ('input_length', 'output_count')):
        raise ValueError('At least four frames and four transfers per data frame required')
    cycles = {p: [] for p in ('s', 'm', 'w')}
    frames = {p: [] for p in cycles}; current = {p: [] for p in cycles}
    expected = dict(s=spec['input_length'], m=spec['output_count'], w=spec['weights_per_frame'])
    stalls = dict(s=0, m=0, w=0); cfg_count = unoffered = row_count = 0
    previous_cycle = None
    row_budget = 2_000_000
    input_started = False; input_completed = False
    with Path(path).open() as fd:
        reader = csv.DictReader(fd)
        if reader.fieldnames != COLUMNS:
            raise RuntimeError('Invalid trace columns')
        for raw in reader:
            row_count += 1
            if row_count > row_budget:
                raise RuntimeError('Bounded trace row budget exceeded')
            try:
                row = {key: int(value) for key, value in raw.items()}
            except (TypeError, ValueError) as exc:
                raise RuntimeError('Noninteger or unknown trace state') from exc
            cycle = row['cycle']
            if cycle < 0 or (previous_cycle is not None and cycle != previous_cycle+1):
                raise RuntimeError('Incomplete per-cycle trace')
            previous_cycle = cycle
            if any(row[key] not in (0, 1) for key in COLUMNS[1:]) or row['error']:
                raise RuntimeError('Invalid control state or DUT error')
            if pressure and (row['m_ready'] != int((cycle-1)%8 < 5) or row['w_ready'] != row['m_ready']):
                raise RuntimeError('Output pressure policy mismatch')
            if not pressure and (not row['m_ready'] or not row['w_ready']):
                raise RuntimeError('Unexpected output pressure')
            cfg_count += row['cfg_valid'] and row['cfg_ready']
            if row['s_valid'] and row['s_ready']:
                if not row['configured'] or cfg_count != 1:
                    raise RuntimeError('Input accepted without exactly one configuration')
                input_started = True
            if input_started and not input_completed:
                unoffered += not row['s_valid']
                stalls['s'] += row['s_valid'] and not row['s_ready']
            for prefix in cycles:
                valid, ready, last = (row[prefix+'_'+suffix] for suffix in ('valid', 'ready', 'last'))
                if last and not valid:
                    raise RuntimeError('Inactive LAST must be masked in the captured trace')
                if prefix != 's':
                    stalls[prefix] += valid and not ready
                if valid and ready:
                    cycles[prefix].append(cycle); current[prefix].append(cycle)
                    if len(current[prefix]) > expected[prefix] or len(frames[prefix]) >= frame_count:
                        raise RuntimeError('Extra channel transfers')
                    if last:
                        frames[prefix].append(current[prefix]); current[prefix] = []
            input_completed = len(frames['s']) == frame_count
    if cfg_count != 1 or any(current.values()) or unoffered != gap*(frame_count-1):
        raise RuntimeError('Incomplete frames/configuration or source offer holes')
    if not expected['w'] and (cycles['w'] or frames['w']):
        raise RuntimeError('Unexpected weights')
    inp = channel_stats(cycles['s'], frames['s'], expected['s'], frame_count)
    out = channel_stats(cycles['m'], frames['m'], expected['m'], frame_count)
    if out['frames'][3*frame_count//4]['first'] > inp['last']:
        raise RuntimeError('Central output window lies in final flush')
    weights = channel_stats(cycles['w'], frames['w'], expected['w'], frame_count) if expected['w'] else None
    last = max(out['last'], weights['last'] if weights else out['last'])
    full_span = last-inp['first']+1
    measured = dict(input=inp, output=out, weights=weights, csv_rows=row_count,
                    input_offered_stall_cycles=stalls['s'], input_unoffered_cycles=unoffered,
                    output_stall_cycles=stalls['m'], weight_stall_cycles=stalls['w'],
                    frame_first_input_to_first_output_lag=[o['first']-i['first'] for i, o in zip(inp['frames'], out['frames'])],
                    frame_last_input_to_last_output_flush=[o['last']-i['last'] for i, o in zip(inp['frames'], out['frames'])],
                    full_first_input_to_last_channel=dict(cycles=full_span, input_rate=inp['accepted']/full_span,
                                                        output_rate=out['accepted']/full_span))
    if weights:
        measured['weight_tail'] = [dict(first=w['first'], last=w['last'], transfers=w['transfers'],
            span_cycles=w['last']-w['first']+1, first_weight_minus_last_data=w['first']-o['last'],
            last_weight_minus_last_input=w['last']-i['last'])
            for i, o, w in zip(inp['frames'], out['frames'], weights['frames'])]
    measured['budgets'] = budgets(spec, measured)
    return measured


def execute(command, cwd, log):
    try:
        result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True, text=True, timeout=90)
    except subprocess.TimeoutExpired as exc:
        Path(log).write_text((exc.stdout or b'').decode() if isinstance(exc.stdout, bytes) else (exc.stdout or ''))
        raise RuntimeError(f'90-second subprocess watchdog: {command[0]}') from exc
    text = result.stdout+result.stderr; Path(log).write_text(text)
    if result.returncode or re.search(r'\*\* (?:Error|Fatal)', text):
        raise RuntimeError(f'Command failed ({result.returncode}): {command[0]}\n{text[-5000:]}')
    return text


def main(argv=None):
    require_unoptimized()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile', choices=[p['name'] for p in profiles()])
    parser.add_argument('--output', type=Path, default=ROOT/'build/rtl/sync_adaptive_rates')
    args = parser.parse_args(argv); output = args.output.resolve(); output.mkdir(parents=True, exist_ok=True)
    target = output/'results.json'; evidence = begin(); records = []; artifacts = []
    write_json(target, dict(evidence, status='RUNNING'))
    try:
        selected = [p for p in profiles() if not args.profile or p['name'] == args.profile]
        bindir, _ = questa_paths(); work = output/'workdir'; work.mkdir(exist_ok=True)
        if not (work/'work').is_dir():
            execute([bindir/'vlib', 'work'], work, work/'vlib.log')
        execute([bindir/'vlog', '-64', '-sv', f'+incdir+{ROOT}/rtl/modems/bpsk_costas_2008_08_25',
                 *SOURCES, ROOT/'rtl/tb/axis_check.sv', ROOT/'rtl/tb/sync_adaptive_rate_tb.sv'], work, work/'compile.log')
        artifacts.append(work/'compile.log')
        script = work/'rate.do'
        script.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        artifacts.append(script)
        for spec in selected:
            folder = output/spec['name']; metadata, stimulus = prepare(folder, spec); artifacts += stimulus
            for mode, gap, pressure in MODES:
                for active in (1, 0):
                    identifier = f'{spec["name"]}_{mode}_reset{active}'
                    print(f'RUN {identifier}: {FRAMES} frames, {metadata["input_length"]} inputs/frame', flush=True)
                    trace, log = output/(identifier+'.csv'), output/(identifier+'.log')
                    params = [f'-gKIND={spec["kind"]}', f'-gLOG2N={spec.get("log2n", 0)}',
                              f'-gTAPS={spec.get("taps", 1)}', f'-gOUTPUT_COUNT={metadata["output_count"]}',
                              f'-gFRAMES={FRAMES}', f'-gRESET_ACTIVE={active}', f'-gGAP={gap}',
                              f'-gBACKPRESSURE={int(pressure)}',
                              f'-gTABLE_DIR={ROOT}/rtl/modems/bpsk_costas_2008_08_25/tables',
                              f'-gRECIP_FILE={ROOT}/rtl/common/mem/lms_reciprocal.mem']
                    text = execute([bindir/'vsim', '-64', '-c', '-quiet', 'work.sync_adaptive_rate_tb', *params,
                                    f'+VECTORS={folder}', f'+TRACE={trace}', '-do', script.name], work, log)
                    match = re.search(r'PASS SYNC ADAPTIVE RATES: (\d+) inputs, (\d+) outputs, (\d+) weights, (\d+) frames', text)
                    required = (FRAMES*metadata['input_length'], FRAMES*metadata['output_count'], FRAMES*metadata['weights_per_frame'], FRAMES)
                    if not match or tuple(map(int, match.groups())) != required:
                        raise RuntimeError(f'Missing or incorrect completion marker: {identifier}')
                    measured = analyze(trace, metadata, gap, pressure)
                    records.append(dict(specification=metadata, mode=mode, reset_active=active, metrics=measured))
                    artifacts += [trace, log]
                    print(f'PASS {identifier}: central input/output {measured["input"]["central_periods"]["rate"]:.6f}/{measured["output"]["central_periods"]["rate"]:.6f} transfers/cycle', flush=True)
        if len(records) != len(selected)*6:
            raise RuntimeError('Incomplete profile/mode/reset coverage')
        write_json(target, dict(finish(evidence, artifacts), status='PASS', records=records,
            scope='Actual pre-edge accepted DUT interfaces; 32 identical bounded representative frames. Functional output values are not used by this meter. All expected traces from vector generation are ignored. No arithmetic correctness claim.',
            steady_scope='Central frame-start periods8..24 include per-frame pauses and adaptive coefficient tails; separate accepted-span, inner middle-span and peak burst rates.',
            latency_scope='First input to first output is per-frame lag, not corresponding-sample latency; Gardner is not one-to-one and its finite padded waveform ratio is separately reported.',
            clocks='10ns is simulation stimulus only. Rates at100MHz and required clocks for100Msps are hypothetical cycle-budget conversions; no physical Fmax claim.',
            output_pressure_policy='Both data and weight ready asserted5 clocks of each8, at negedge, same fixed phase; one policy only.',
            coverage=dict(profiles=[p['name'] for p in selected], frames_per_case=FRAMES, modes=[m[0] for m in MODES], reset_polarities=[1,0])))
    except Exception as exc:
        write_json(target, dict(evidence, status='FAIL', error=f'{type(exc).__name__}: {exc}', records=records))
        raise
    print(f'PASS SYNC ADAPTIVE RATES {len(records)} runs', flush=True)
    return records


if __name__ == '__main__':
    main()
