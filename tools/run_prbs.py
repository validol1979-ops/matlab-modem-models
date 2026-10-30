#!/usr/bin/env python3
"""PRBS/scrambler acceptance: Python, strict lint, Questa or Verilator simulation."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

from regression_evidence import ROOT, begin, finish, write_json, questa_paths, require_unoptimized

sys.path.insert(0, str(ROOT / 'common/python'))
from prbs_rtl_cases import HDL_CASES, ORDERS, vectors

DUT = ROOT / 'rtl/common/prbs_scrambler.sv'
TB = ROOT / 'rtl/tb/prbs_scrambler_tb.sv'
CHECK = ROOT / 'rtl/tb/axis_check.sv'
SUMMARY = r'PASS PRBS: configs=(\d+) outputs=(\d+) max_run=(\d+) holds=(\d+) gaps=(\d+)'
DIRECTED = 'PASS PRBS DIRECTED: priority pending_cfg sticky_error midreset outreset'
# Verilator's default fatal handler aborts. Its documented VL_USER_FATAL hook
# preserves the original diagnostic and gives the same exact exit 13 as Questa.
FATAL_CPP = r'''
#include <cstdio>
#include <cstdlib>
void vl_fatal(const char* filename, int linenum, const char* hier, const char* msg) {
    std::fprintf(stderr, "%%Error: %s:%d: %s %s\n", filename, linenum, hier, msg);
    std::fflush(nullptr);
    std::exit(13);
}
'''


def execute(command, work, log, timeout=180):
    result = subprocess.run(list(map(str, command)), cwd=work, capture_output=True,
                            text=True, timeout=timeout)
    output = result.stdout + result.stderr
    Path(log).write_text(output)
    if result.returncode:
        raise RuntimeError(f'Command failed ({result.returncode}): {command}\n{output[-5000:]}')
    return output


def check_negative(code, output, tag):
    if (type(code) is not int or code != 13 or tag not in ('NUMERIC', 'PROTOCOL') or
            not re.search(r'(?:\*\* Fatal:|%(?:Error|Fatal):)[^\n]*\[' + tag + r'\]', output) or
            re.search(SUMMARY, output)):
        raise RuntimeError(f'Negative control {tag} was not detected with exit 13: {code}\n{output[-2000:]}')
    return dict(returncode=code, detected_tag=tag)


def check_positive(code, output, report, stalled):
    matches = re.findall(SUMMARY, output)
    if (code != 0 or len(matches) != 1 or output.count(DIRECTED) != 1 or
            re.search(r'\*\* (?:Error|Fatal)|%(?:Error|Fatal)|\[(?:NUMERIC|PROTOCOL|TIMEOUT|CONFIG|RESET|RATE|COVERAGE|VECTOR)\]', output)):
        raise RuntimeError(f'Failed PRBS simulation: {code}\n{output[-4000:]}')
    configs, outputs, run, holds, gaps = map(int, matches[0])
    if configs != report['configurations'] or outputs != report['outputs']:
        raise RuntimeError('Incomplete PRBS scoreboard coverage')
    if (stalled and min(holds, gaps) < 1) or (not stalled and run < 16):
        raise RuntimeError('Missing stall/rate coverage')
    return dict(configurations=configs, outputs=outputs, max_run=run, holds=holds, gaps=gaps)


def main():
    require_unoptimized()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('python', 'lint', 'hdl', 'all'), default='all')
    parser.add_argument('--simulator', choices=('questa', 'verilator'), default='questa')
    parser.add_argument('--output-dir', type=Path, default=ROOT/'build/rtl/prbs')
    args = parser.parse_args()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = begin()
    target = output/'results.json'
    records, artifacts = {}, []
    write_json(target, dict(evidence, status='RUNNING'))
    try:
        if args.suite in ('python', 'all'):
            log = output/'python.log'
            execute([sys.executable, '-m', 'pytest', '-q', ROOT/'tests/test_prbs_rtl.py'], ROOT, log)
            artifacts.append(log)
            records['python'] = 'PASS'
        if args.suite in ('lint', 'all'):
            count = 0
            for order in ORDERS:
                for width in (1, 3, 8, 31, 32, 64):
                    for active in (0, 1):
                        log = output/f'lint_n{order}_w{width}_r{active}.log'
                        text = execute(['verilator', '--lint-only', '-Wall', '--top-module', 'prbs_scrambler',
                                        f'-GORDER={order}', f'-GWORD_WIDTH={width}', f'-GRESET_ACTIVE={active}', DUT], ROOT, log)
                        if '%Warning' in text:
                            raise RuntimeError(f'Strict lint warning: {log}')
                        artifacts.append(log)
                        count += 1
            records['lint'] = dict(configurations=count, warnings=0)
        if args.suite in ('hdl', 'all'):
            bindir = questa_paths()[0] if args.simulator == 'questa' else None
            hdl_records = []
            records['hdl'] = hdl_records
            for order, width in HDL_CASES:
                vector_file = output/f'vectors_n{order}_w{width}.txt'
                report = vectors(vector_file, order, width)
                artifacts.append(vector_file)
                for active in (1, 0):
                    work = output/f'n{order}_w{width}_r{active}'
                    work.mkdir()
                    params = dict(ORDER=order, WORD_WIDTH=width, RESET_ACTIVE=active)
                    if args.simulator == 'verilator':
                        fatal = work/'fatal.cpp'
                        fatal.write_text(FATAL_CPP)
                        artifacts.append(fatal)
                        execute(['verilator', '--binary', '--timing', '--timescale', '1ns/1ps', '-j', '4',
                                 '--top-module', 'prbs_scrambler_tb', '--Mdir', work/'obj',
                                 '-CFLAGS', '-DVL_USER_FATAL',
                                 *[f'-G{k}={v}' for k, v in params.items()], DUT, CHECK, TB, fatal],
                                ROOT, work/'compile.log')
                        command = [work/'obj/Vprbs_scrambler_tb', f'+VECTORS={vector_file}']
                    else:
                        execute([bindir/'vlib', 'work'], work, work/'vlib.log')
                        artifacts.append(work/'vlib.log')
                        execute([bindir/'vlog', '-64', '-sv', DUT, CHECK, TB], work, work/'compile.log')
                        # Как в run_stream_cfg_priority: обычный $finish положительного прогона даёт 0,
                        # остановка отрицательного контроля ($fatal/break) — код 13.
                        script = work/'run.do'
                        script.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
                        negative_script = work/'run_negative.do'
                        negative_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                        artifacts.extend((script, negative_script))
                        # Questa падает (Bad pointer access) на абсолютных путях с кириллицей в аргументах:
                        # векторы и скрипт передаются относительно рабочего каталога, как в других раннерах.
                        command = [bindir/'vsim', '-64', '-c', '-quiet', 'work.prbs_scrambler_tb',
                                   *[f'-g{k}={v}' for k, v in params.items()],
                                   f'+VECTORS={os.path.relpath(vector_file, work)}', '-do', script.name]
                    artifacts.append(work/'compile.log')
                    row = dict(order=order, word_width=width, reset_active=active, scenarios={}, negatives={})
                    hdl_records.append(row)
                    scenarios = [('stream', [], None), ('stalled', ['+STALLS'], None),
                                 ('negative_numeric', ['+INJECT_NUMERIC'], 'NUMERIC'),
                                 ('negative_protocol', ['+INJECT_PROTOCOL'], 'PROTOCOL')]
                    for name, flags, tag in scenarios:
                        log = work/f'{name}.log'
                        run = command
                        if args.simulator == 'questa' and tag:
                            run = [*command[:-1], negative_script.name]
                        result = subprocess.run(list(map(str, [*run, *flags])), cwd=work,
                                                capture_output=True, text=True, timeout=120)
                        text = result.stdout + result.stderr
                        log.write_text(text)
                        artifacts.append(log)
                        if tag:
                            row['negatives'][tag] = check_negative(result.returncode, text, tag)
                        else:
                            row['scenarios'][name] = check_positive(result.returncode, text, report, name == 'stalled')
                    print(f'PASS PRBS n={order} w={width} reset={active} ({args.simulator})', flush=True)
        write_json(target, dict(status='PASS', suite=args.suite, simulator=args.simulator,
                                records=records, **finish(evidence, artifacts)))
    except Exception as exc:
        write_json(target, dict(evidence, status='FAIL', suite=args.suite, simulator=args.simulator,
                                error=str(exc), records=records))
        raise
    print(f'PASS PRBS {args.suite}: {target}')


if __name__ == '__main__':
    main()
