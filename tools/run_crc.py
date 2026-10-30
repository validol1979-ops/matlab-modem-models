#!/usr/bin/env python3
"""CRC/FCS: independent Python vectors, strict lint, Questa/Verilator simulation."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT, begin, finish, write_json, questa_paths, require_unoptimized

sys.path.insert(0, str(ROOT / 'common/python'))
from crc_rtl_cases import write_vectors

DUT = ROOT / 'rtl/common/crc_stream.sv'
TB = ROOT / 'rtl/tb/crc_stream_tb.sv'
CHECK = ROOT / 'rtl/tb/axis_check.sv'
MATRIX = [(width, bits) for width in (1, 16, 32) for bits in (1, 8, 32)]
SUMMARY = re.compile(r'PASS CRC frames=(\d+) inputs=(\d+) outputs=(\d+) collisions=(\d+) '
                     r'pending=(\d+) istall=(\d+) ostall=(\d+) rate=(\d+) latency=(\d+)')
# Verilator's documented VL_USER_FATAL hook makes the actual executable return 13
# on $fatal (including axis_check), instead of abort/SIGABRT. No log/rc rewriting.
FATAL_CPP = '''#include "verilated.h"
#include <cstdlib>
void vl_fatal(const char* filename, int line, const char* hier, const char* msg) {
    VL_PRINTF("%%Error: %s:%d: %s %s\\n", filename, line, hier, msg);
    std::fflush(stdout);
    std::exit(13);
}
'''


def execute(command, cwd, log, timeout=180):
    result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True,
                            text=True, timeout=timeout)
    output = result.stdout + result.stderr
    log.write_text(output)
    return result.returncode, output


def checked_command(command, cwd, log, timeout=180):
    rc, output = execute(command, cwd, log, timeout)
    if rc:
        raise RuntimeError(f'Command failed rc={rc}; {log}\n{output[-8000:]}')
    return output


def check_run(rc, output, report, negative=None):
    if negative:
        if rc != 13 or negative not in output or 'PASS CRC' in output or '[CONTROL_MISSING]' in output:
            raise RuntimeError(f'Negative control not detected: rc={rc}, tag={negative}\n{output[-3000:]}')
        return dict(returncode=rc, detected_tag=negative)
    match = SUMMARY.search(output)
    if rc or not match or re.search(r'\*\* (?:Error|Fatal)|%Error|\[(?:NUMERIC|PROTOCOL|TIMEOUT)\]', output):
        raise RuntimeError(f'CRC simulation failed rc={rc}\n{output[-6000:]}')
    counts = dict(zip(('frames', 'inputs', 'outputs', 'collisions', 'pending',
                       'input_stalls', 'output_stalls', 'rate_pairs', 'latency_checks'),
                      map(int, match.groups())))
    if any(counts[key] != report[key] for key in ('frames', 'inputs', 'outputs')):
        raise RuntimeError(f'Incomplete scoreboard: {counts} vs {report}')
    return dict(returncode=rc, **counts)


def run_hdl(output, artifacts, simulator, reports):
    records = []
    bindir = questa_paths()[0] if simulator == 'questa' else None
    fatal_cpp = output / 'fatal_exit.cpp'
    if simulator == 'verilator':
        fatal_cpp.write_text(FATAL_CPP)
        artifacts.append(fatal_cpp)
    for width, bits in MATRIX:
        vector = output / f'vectors_w{width}_b{bits}.txt'
        for active in (1, 0):
            work = output / f'w{width}_b{bits}_reset{active}'
            work.mkdir()
            params = dict(CRC_WIDTH=width, WORD_BITS=bits, RESET_ACTIVE=active)
            compile_log = work / 'compile.log'
            if simulator == 'verilator':
                # TIMESCALEMOD: DUT/checker deliberately carry no time units;
                # simulation timing belongs exclusively to the testbench.
                checked_command(['verilator', '--binary', '--timing', '-j', '4',
                                 '-Wall', '-Wno-TIMESCALEMOD', '--top-module', 'crc_stream_tb',
                                 '--Mdir', work / 'obj', '-CFLAGS', '-DVL_USER_FATAL',
                                 *[f'-G{k}={v}' for k, v in params.items()],
                                 DUT, CHECK, TB, fatal_cpp], ROOT, compile_log)
                command = [work / 'obj/Vcrc_stream_tb']
            else:
                vlib = work / 'vlib.log'
                checked_command([bindir / 'vlib', 'work'], work, vlib)
                artifacts.append(vlib)
                checked_command([bindir / 'vlog', '-64', '-sv', DUT, CHECK, TB], work, compile_log)
                script = work / 'run.do'
                script.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
                negative_script = work / 'negative.do'
                negative_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                artifacts.extend([script, negative_script])
                command = [bindir / 'vsim', '-64', '-c', '-quiet', 'work.crc_stream_tb',
                           *[f'-g{k}={v}' for k, v in params.items()], '-do', script.name]
            artifacts.append(compile_log)
            scenarios = [('stalled', [], None), ('continuous', ['+NO_STALL'], None),
                         ('negative_numeric', ['+INJECT_MISMATCH'], '[NUMERIC]'),
                         ('negative_protocol', ['+INJECT_PROTOCOL'], '[PROTOCOL]')]
            observations = {}
            for name, flags, negative in scenarios:
                log = work / f'{name}.log'
                run_command = list(command)
                if simulator == 'questa' and negative:
                    run_command[-1] = negative_script.name
                # Questa падает на абсолютных путях с кириллицей: векторы — относительно work.
                vector_arg = os.path.relpath(vector, work) if simulator == 'questa' else vector
                rc, text = execute([*run_command, f'+VECTORS={vector_arg}', *flags], work, log)
                artifacts.append(log)
                observations[name] = check_run(rc, text, reports[(width, bits)], negative)
            records.append(dict(width=width, word_bits=bits, reset_active=active,
                                scenarios=observations))
            print(f'PASS CRC W={width} word={bits} reset={active} ({simulator})', flush=True)
    return records


def main(argv=None):
    require_unoptimized()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('python', 'lint', 'hdl', 'all'), default='all')
    parser.add_argument('--simulator', choices=('questa', 'verilator'), default='questa')
    parser.add_argument('--output-dir', type=Path, help='new output directory; existing paths are rejected')
    args = parser.parse_args(argv)
    output = (args.output_dir or ROOT / 'build/rtl/crc').resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = begin()
    target = output / 'results.json'
    artifacts, records = [], {}
    write_json(target, dict(evidence, status='RUNNING', suite=args.suite, simulator=args.simulator))
    try:
        reports = {}
        if args.suite in ('python', 'hdl', 'all'):
            for width, bits in MATRIX:
                vector = output / f'vectors_w{width}_b{bits}.txt'
                reports[(width, bits)] = write_vectors(vector, width, bits)
                artifacts.append(vector)
            records['vectors'] = {f'w{w}_b{b}': r for (w, b), r in reports.items()}
        if args.suite in ('python', 'all'):
            log = output / 'pytest.log'
            checked_command([sys.executable, '-m', 'pytest', '-q', ROOT / 'tests/test_crc_rtl.py'], ROOT, log)
            artifacts.append(log)
            records['python'] = 'PASS'
        if args.suite in ('lint', 'all'):
            for width, bits in MATRIX:
                for active in (1, 0):
                    log = output / f'lint_w{width}_b{bits}_reset{active}.log'
                    text = checked_command(['verilator', '--lint-only', '-Wall', '--top-module', 'crc_stream',
                                            f'-GCRC_WIDTH={width}', f'-GWORD_BITS={bits}',
                                            f'-GRESET_ACTIVE={active}', DUT], ROOT, log)
                    if '%Warning' in text:
                        raise RuntimeError(f'Unexpected lint warning: {log}')
                    artifacts.append(log)
            records['lint'] = dict(status='PASS', configurations=2*len(MATRIX), waivers=[])
        if args.suite in ('hdl', 'all'):
            records['hdl'] = run_hdl(output, artifacts, args.simulator, reports)
        write_json(target, dict(status='PASS', suite=args.suite, simulator=args.simulator,
                                records=records, **finish(evidence, artifacts)))
    except Exception as exc:
        write_json(target, dict(evidence, status='FAIL', suite=args.suite, simulator=args.simulator,
                                error=str(exc), records=records))
        raise
    print(f'PASS CRC {args.suite}: {target}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
