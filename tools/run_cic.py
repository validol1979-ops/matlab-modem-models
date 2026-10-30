#!/usr/bin/env python3
"""DSP-CIC-DEC: independent Python vectors, strict lint, Questa/Verilator simulation."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

from regression_evidence import ROOT, begin, finish, write_json, require_unoptimized, questa_paths, digest

sys.path.insert(0, str(ROOT / 'common/python'))
from cic_rtl_cases import PROFILES, vectors

DUT = ROOT / 'rtl/common/cic_decimator.sv'
TB = ROOT / 'rtl/tb/cic_decimator_tb.sv'
CHECK = ROOT / 'rtl/tb/axis_check.sv'
FATAL = ROOT / 'rtl/tb/cic_verilator_fatal.cpp'


def execute(command, cwd, log, timeout=300):
    result = subprocess.run(list(map(str, command)), cwd=cwd, capture_output=True,
                            text=True, timeout=timeout)
    text = result.stdout + result.stderr
    Path(log).write_text(text)
    if result.returncode:
        raise RuntimeError(f'Command failed rc={result.returncode}: {command[0]}\n{text[-6000:]}')
    return text


def check_run(returncode, text, active, negative=None):
    """Accept exact success evidence or an exact tagged failure with code 13."""
    if negative:
        tag = {'numeric': '[NUMERIC]', 'protocol': '[PROTOCOL]'}[negative]
        if (returncode != 13 or tag not in text or 'PASS CIC ALL' in text or
                not re.search(r'(?:%Error:|%Fatal:|\*\* Fatal:).*' + re.escape(tag), text)):
            raise RuntimeError(f'Negative control {negative} failed rc={returncode}:\n{text[-4000:]}')
        return dict(negative=negative, returncode=returncode, detected_tag=tag)
    matches = re.findall(r'PASS CIC profile=(\S+) reset=(\d) cases=(\d+) outputs=(\d+) '
                         r'adjacent=(\d+) stalls_in=(\d+) stalls_out=(\d+)', text)
    if (returncode != 0 or f'PASS CIC ALL reset={active} profiles=18' not in text or
            re.search(r'%Error|\*\* (?:Error|Fatal)', text) or len(matches) != len(PROFILES) or
            {m[0] for m in matches} != {p.name for p in PROFILES}):
        raise RuntimeError(f'CIC simulation failed rc={returncode}:\n{text[-6000:]}')
    records = []
    for name, polarity, cases, outputs, adjacent, sin, sout in matches:
        if (int(polarity) != active or int(cases) != 161 or int(outputs) != 2564 or int(adjacent) < 1):
            raise RuntimeError(f'Incomplete coverage for {name}')
        records.append(dict(profile=name, cases=int(cases), outputs=int(outputs),
                            adjacent=int(adjacent), stalls_in=int(sin), stalls_out=int(sout)))
    return dict(returncode=returncode, profiles=records)


def lint(output, artifacts):
    configs = [dict(STAGES=p.stages, DELAY=p.delay, NORMALIZE=int(p.normalize),
                    ACC_WIDTH=p.width, RESET_ACTIVE=active)
               for p in PROFILES for active in (0, 1)]
    # Non-power-of-two maxima exercise the exact ceil(log2(gain)) default;
    # explicit AW=128 and AW=18 exercise both quantizer extension bounds.
    configs += [dict(STAGES=5, DELAY=2, MAX_RATE=r, NORMALIZE=norm)
                for r in (1, 3, 31) for norm in (0, 1)]
    configs += [dict(STAGES=5, DELAY=2, ACC_WIDTH=128, NORMALIZE=norm) for norm in (0, 1)]
    for index, params in enumerate(configs):
        log = output / f'lint_{index}.log'
        text = execute(['verilator', '--lint-only', '-Wall', '--top-module', 'cic_decimator',
                        *(f'-G{k}={v}' for k, v in params.items()), DUT], ROOT, log)
        if '%Warning' in text:
            raise RuntimeError(f'Verilator warning: {params}')
        artifacts.append(log)
    return dict(status='PASS', configurations=configs, waivers=[])


def hdl(output, artifacts, simulator):
    records = []
    for active in (1, 0):
        work = output / f'reset{active}'
        work.mkdir()
        log = work / 'compile.log'
        if simulator == 'verilator':
            execute(['verilator', '--binary', '--timing', '--timescale', '1ns/1ps', '-j', '4',
                     '--top-module', 'cic_decimator_tb', '--Mdir', work / 'obj',
                     f'-GRESET_ACTIVE={active}', '-CFLAGS', '-DVL_USER_FATAL',
                     DUT, CHECK, TB, FATAL], ROOT, log, timeout=600)
            command = [work / 'obj/Vcic_decimator_tb']
        else:
            bindir, _ = questa_paths()
            execute([bindir / 'vlib', 'work'], work, work / 'vlib.log')
            artifacts.append(work / 'vlib.log')
            execute([bindir / 'vlog', '-64', '-sv', DUT, CHECK, TB], work, log)
            # Обычный $finish положительного прогона даёт 0, остановка отрицательного — код 13.
            script = work / 'run.do'
            script.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
            negative_script = work / 'run_negative.do'
            negative_script.write_text('onfinish stop\nonerror {quit -code 13}\n'
                                       'onbreak {quit -code 13}\nrun -all\nquit -code 0\n')
            artifacts.extend((script, negative_script))
            command = [bindir / 'vsim', '-64', '-c', '-quiet', 'work.cic_decimator_tb',
                       f'-gRESET_ACTIVE={active}', '-do', script.name]
        artifacts.append(log)
        for name, options, negative in (
                ('stream', [], None), ('stalled', ['+STALL'], None),
                ('negative_numeric', ['+INJECT_MISMATCH'], 'numeric'),
                ('negative_protocol', ['+INJECT_PROTOCOL'], 'protocol')):
            log = work / f'{name}.log'
            run = [*command[:-1], negative_script.name] if simulator == 'questa' and negative else command
            # Questa падает на абсолютных путях с кириллицей: векторы — относительно work.
            vectors = os.path.relpath(output / 'vectors', work) if simulator == 'questa' else output / 'vectors'
            result = subprocess.run(list(map(str, [*run, f'+VECTORS={vectors}', *options])),
                                    cwd=work, capture_output=True, text=True, timeout=180)
            text = result.stdout + result.stderr
            log.write_text(text)
            artifacts.append(log)
            record = check_run(result.returncode, text, active, negative)
            if name == 'stalled' and any(p['stalls_in'] < 1 or p['stalls_out'] < 1 for p in record['profiles']):
                raise RuntimeError('Missing backpressure coverage')
            records.append(dict(reset_active=active, scenario=name, **record))
            print(f'PASS CIC {name} reset={active} ({simulator}, rc={result.returncode})', flush=True)
    return records


def main(argv=None):
    require_unoptimized()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('python', 'lint', 'hdl', 'all'), default='all')
    parser.add_argument('--simulator', choices=('questa', 'verilator'), default='questa')
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/rtl/cic')
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    # Never overwrite an earlier result, including for the default directory.
    output.mkdir(parents=True, exist_ok=False)
    evidence = begin()
    # regression_evidence's common source glob does not include C++ helpers.
    evidence['support_source_hashes'] = {str(FATAL.relative_to(ROOT)): digest(FATAL)}
    target = output / 'results.json'
    artifacts, records = [FATAL], {}
    write_json(target, dict(evidence, status='RUNNING', suite=args.suite, simulator=args.simulator))
    try:
        if args.suite in ('python', 'hdl', 'all'):
            reports = []
            for profile in PROFILES:
                path = output / 'vectors' / f'{profile.name}.txt'
                reports.append(vectors(path, profile))
                artifacts.append(path)
            records['vectors'] = reports
        if args.suite in ('python', 'all'):
            log = output / 'python.log'
            execute([sys.executable, '-m', 'pytest', '-q', ROOT / 'tests/test_cic_models.py',
                     ROOT / 'tests/test_cic_rtl.py'], ROOT, log)
            artifacts.append(log)
            records['python'] = 'PASS'
        if args.suite in ('lint', 'all'):
            records['lint'] = lint(output, artifacts)
        if args.suite in ('hdl', 'all'):
            records['hdl'] = hdl(output, artifacts, args.simulator)
        if digest(FATAL) != evidence['support_source_hashes'][str(FATAL.relative_to(ROOT))]:
            raise RuntimeError('CIC Verilator fatal helper changed during regression')
        write_json(target, dict(status='PASS', suite=args.suite, simulator=args.simulator,
                                records=records, **finish(evidence, artifacts)))
    except Exception as exc:
        write_json(target, dict(evidence, status='FAIL', suite=args.suite, simulator=args.simulator,
                                records=records, error=str(exc)))
        raise
    print(f'PASS CIC {args.suite}: {target}', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
