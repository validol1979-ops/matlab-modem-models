#!/usr/bin/env python3
"""DSP-SOS: Python vectors, strict lint, Questa/Verilator simulation; no synthesis."""
import argparse
import os
from datetime import datetime, timezone
from pathlib import Path
import re
import subprocess
import sys

from regression_evidence import (ROOT, begin, finish, write_json, questa_paths,
                                 require_unoptimized, digest)

sys.path.insert(0, str(ROOT/'common/python'))
from sos_rtl_cases import write_vectors

DUT = ROOT/'rtl/common/sos_iir.sv'
TB = ROOT/'rtl/tb/sos_iir_tb.sv'
CHECKER = ROOT/'rtl/tb/axis_check.sv'
EXIT_ADAPTER = ROOT/'rtl/tb/sos_verilator_exit.cpp'
PARAMETERS = ((28, 64), (28, 40), (16, 40), (16, 64), (22, 52), (28, 51))
MARKER = re.compile(r'PASS SOS: samples=(\d+) raw_checks=(\d+) input_stalls=(\d+) output_stalls=(\d+) cfg_blocked=(\d+) collisions=(\d+)')


def execute(command, cwd, log, timeout=240):
    result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True,
                            text=True, timeout=timeout)
    output = result.stdout+result.stderr
    Path(log).write_text(output)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {command[0]}\n{output[-8000:]}')
    return output


def check_run(returncode, output, samples, raw_checks, negative_tag=None, stalled=False):
    """A negative must have code 13, its exact diagnostic, and no PASS marker."""
    if negative_tag is not None:
        if returncode != 13 or negative_tag not in output or MARKER.search(output):
            raise RuntimeError(f'Negative control failed: rc={returncode}, tag={negative_tag}\n{output[-4000:]}')
        # Mere messages with matching tags cannot masquerade as simulator failures.
        if not re.search(r'\*\* Fatal:|%Error|Assertion failed', output):
            raise RuntimeError('Negative control has no simulator fatal diagnostic')
        return dict(returncode=returncode, detected_tag=negative_tag)
    match = MARKER.search(output)
    if returncode or not match or re.search(r'\*\* (?:Error|Fatal)|%Error|\[(?:TIMEOUT|NUMERIC|RAW_STAGE|RAW_STATE|CONFIG|RATE|LATENCY|COVERAGE)\]', output):
        raise RuntimeError(f'Simulation failed rc={returncode}\n{output[-5000:]}')
    values = list(map(int, match.groups()))
    if values[:2] != [samples, raw_checks] or min(values[2:]) < 1:
        raise RuntimeError(f'Incomplete vector/protocol coverage: {values}')
    result = dict(zip(('samples', 'raw_checks', 'input_stalls', 'output_stalls', 'cfg_blocked', 'collisions'), values))
    if not stalled:
        rate = re.search(r'PASS RATE: latency=(\d+),(\d+),(\d+) interval=(\d+),(\d+),(\d+)', output)
        if not rate or list(map(int, rate.groups())) != [12, 23, 45, 13, 24, 46]:
            raise RuntimeError('Missing or wrong actual pin timing measurements')
        result['latency_cycles'] = [12, 23, 45]
        result['initiation_interval_cycles'] = [13, 24, 46]
    return result


def simulate(work, vectors, report, frac, bits, active, simulator, artifacts):
    work.mkdir()
    params = dict(COEF_FRAC=frac, STATE_BITS=bits, RESET_ACTIVE=active)
    log = work/'compile.log'
    if simulator == 'verilator':
        execute(['verilator', '--binary', '--timing', '--timescale', '1ns/1ps',
                 '-j', '2', '-CFLAGS', '-DVL_USER_FATAL', '--top-module', 'sos_iir_tb', '--Mdir', work/'obj',
                 *[f'-G{k}={v}' for k, v in params.items()], DUT, CHECKER, TB, EXIT_ADAPTER],
                ROOT, log)
        command = [work/'obj/Vsos_iir_tb', f'+VECTORS={vectors}']
    else:
        bindir, _ = questa_paths()
        execute([bindir/'vlib', 'work'], work, work/'vlib.log')
        artifacts.append(work/'vlib.log')
        execute([bindir/'vlog', '-64', '-sv', '-timescale', '1ns/1ps', DUT, CHECKER, TB], work, log)
        # Обычный $finish положительного прогона даёт 0, остановка отрицательного — код 13;
        # пути относительно work: Questa падает на абсолютных путях с кириллицей.
        script = work/'run.do'
        script.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative_script = work/'run_negative.do'
        negative_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
        artifacts.extend((script, negative_script))
        command = [bindir/'vsim', '-64', '-c', '-quiet', 'work.sos_iir_tb',
                   *[f'-g{k}={v}' for k, v in params.items()], f'+VECTORS={os.path.relpath(vectors, work)}',
                   '-do', script.name]
    artifacts.append(log)
    raw_checks = sum(entry['samples']*entry['sections']*6 for entry in report['cases'])
    records = {}
    for name, flags, tag in (('stream', [], None), ('stalled', ['+STALL'], None),
                             ('negative_numeric', ['+INJECT_MISMATCH'], '[NUMERIC]'),
                             ('negative_protocol', ['+INJECT_PROTOCOL'], '[PROTOCOL]')):
        run = [*command[:-1], negative_script.name] if simulator == 'questa' and tag else command
        result = subprocess.run(list(map(str, [*run, *flags])), cwd=work,
                                capture_output=True, text=True, timeout=180)
        output = result.stdout+result.stderr
        log = work/f'{name}.log'
        log.write_text(output)
        artifacts.append(log)
        records[name] = check_run(result.returncode, output, report['samples'], raw_checks,
                                  negative_tag=tag, stalled=name == 'stalled')
    print(f'PASS SOS F={frac} state={bits} reset={active}: {report["samples"]} samples/scenario, negatives rc=13', flush=True)
    return records


def main(argv=None):
    require_unoptimized()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('python', 'lint', 'hdl', 'all'), default='all')
    parser.add_argument('--simulator', choices=('questa', 'verilator'), default='questa')
    parser.add_argument('--output-dir', type=Path, help='new directory, existing paths are rejected')
    args = parser.parse_args(argv)
    output = (args.output_dir or ROOT/'build/rtl'/('sos_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))).resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = begin()
    extra_hashes = {str(EXIT_ADAPTER.relative_to(ROOT)): digest(EXIT_ADAPTER)}
    target = output/'results.json'
    records, artifacts = {}, [EXIT_ADAPTER]
    write_json(target, dict(evidence, status='RUNNING', suite=args.suite, simulator=args.simulator))
    try:
        if args.suite in ('python', 'all'):
            log = output/'python.log'
            execute([sys.executable, '-m', 'pytest', '-q', 'tests/test_ext_signal_sos.py',
                     'tests/test_sos_rtl.py'], ROOT, log)
            artifacts.append(log)
            records['python'] = 'PASS'
        if args.suite in ('lint', 'all'):
            records['lint'] = []
            for frac, bits in PARAMETERS:
                for active in (1, 0):
                    log = output/f'lint_f{frac}_s{bits}_r{active}.log'
                    text = execute(['verilator', '--lint-only', '-Wall', '--top-module', 'sos_iir',
                                    f'-GCOEF_FRAC={frac}', f'-GSTATE_BITS={bits}', f'-GRESET_ACTIVE={active}', DUT], ROOT, log)
                    if '%Warning' in text:
                        raise RuntimeError('Strict lint produced warnings')
                    artifacts.append(log)
                    records['lint'].append(dict(coef_frac=frac, state_bits=bits, reset_active=active, status='PASS'))
        if args.suite in ('hdl', 'all'):
            records['hdl'] = []
            for frac, bits in PARAMETERS:
                vectors = output/f'vectors_f{frac}_s{bits}.txt'
                report = write_vectors(vectors, frac, bits)
                artifacts.extend((vectors, vectors.with_suffix('.json')))
                for active in (1, 0):
                    observations = simulate(output/f'f{frac}_s{bits}_r{active}', vectors, report,
                                            frac, bits, active, args.simulator, artifacts)
                    records['hdl'].append(dict(coef_frac=frac, state_bits=bits, reset_active=active,
                                               vectors=report, scenarios=observations))
        if any(digest(ROOT/name) != expected for name, expected in extra_hashes.items()):
            raise RuntimeError('Simulator exit adapter changed during regression')
        write_json(target, dict(status='PASS', suite=args.suite, simulator=args.simulator, records=records,
                                extra_source_hashes=extra_hashes, **finish(evidence, artifacts)))
    except Exception as exc:
        write_json(target, dict(evidence, status='FAIL', suite=args.suite, simulator=args.simulator,
                                records=records, error=str(exc)))
        raise
    print(f'PASS SOS {args.suite}: {target}', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
