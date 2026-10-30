#!/usr/bin/env python3
"""RTL-подтверждение конечного исследования захвата QPSK в Questa, без синтеза."""
import argparse
from contextlib import contextmanager
from dataclasses import dataclass
from itertools import product
import json
from pathlib import Path
import re
import subprocess
import sys

import costas_stream_acquisition as study
from costas_stream_cases import write_case
from regression_evidence import (ROOT, begin, digest, finish, questa_paths, require_pass,
                                 require_unoptimized, write_json)
from run_costas_stream import PASS, PILOT, RESETS, TABLES, check_negative, hold_coverage
from run_rtl import SOURCES

REFERENCE = ROOT / 'docs/rtl_costas_stream_acquisition_20261029_results.json'
PARAMETERS = ('initial_phase_rad', 'rate_rad_per_sample', 'snr_db', 'seed', 'gains')


def trajectory_parameters():
    """Именно исходная сетка 72 точек и отдельный контроль; порядок фиксирован."""
    cases = []
    for index, (phase, rate, snr, seed) in enumerate(product(
            (-.6, 0., .6), (-.012, 0., .012), (None, 24., 12., 6.), (0, 1))):
        cases.append((f'case_{index:03d}', dict(zip(PARAMETERS,
                     (phase, rate, snr, seed, [.08, .001])))))
    cases.append(('zero_gain_control', dict(zip(PARAMETERS, (.6, .012, None, 0, [0., 0.])))))
    return cases


def load_reference(path):
    reference = json.loads(path.read_text())
    for key, expected in (('samples', study.LENGTH), ('window', study.WINDOW),
                          ('delay_advances', study.DELAY)):
        if reference.get(key) != expected:
            raise RuntimeError(f'[REFERENCE] {key} must be {expected}')
    cases = reference.get('cases', [])
    if len(cases) != 72 or not isinstance(reference.get('zero_gain_control'), dict):
        raise RuntimeError('[REFERENCE] need 72 trajectories and a zero-gain control')
    records = [*cases, reference['zero_gain_control']]
    for (name, params), record in zip(trajectory_parameters(), records):
        if {key: record.get(key) for key in PARAMETERS} != params:
            raise RuntimeError(f'[REFERENCE] wrong grid parameters: {name}')
    return reference


@dataclass
class Trajectory:
    name: str
    folder: Path
    parameters: dict
    carrier: object
    expected: list
    reference: dict


def check_metrics(trajectory, phases):
    """Фазы передаются явно: в RTL-прогоне это только прочитанный файл OBSERVED."""
    record = dict(trajectory.parameters, **study.measure(phases, trajectory.carrier))
    if record != trajectory.reference:
        raise RuntimeError(f'[METRICS] {trajectory.name}: differs from saved model study')
    return record


def prepare_vectors(base, reference):
    records = [*reference['cases'], reference['zero_gain_control']]
    trajectories = []
    for (name, params), record in zip(trajectory_parameters(), records):
        data, carrier, clipped = study.signal(*(params[key] for key in PARAMETERS[:4]))
        last = [int(n == len(data) - 1) for n in range(len(data))]
        folder = base / name
        values, phases = write_case(folder, data, last, params['gains'])
        trajectory = Trajectory(name, folder, dict(params, clipped_components=clipped), carrier,
                                [(*value, phase, flag)
                                 for value, phase, flag in zip(values, phases, last)], record)
        # Проверка воспроизведения исторического JSON до первого HDL-прогона.
        check_metrics(trajectory, phases)
        trajectories.append(trajectory)
    return trajectories


def check_observed(trajectory, path):
    """Повторная независимая сверка каждого слова, включая длину и формат RTL-лога."""
    rows = []
    for index, line in enumerate(path.read_text().splitlines()):
        if not re.fullmatch(r'-?\d+ -?\d+ -?\d+ [01]', line):
            raise RuntimeError(f'[FORMAT] {trajectory.name}: output row {index}')
        rows.append(tuple(map(int, line.split())))
    if len(rows) != len(trajectory.expected):
        raise RuntimeError(f'[COUNT] {trajectory.name}: {len(rows)} of '
                           f'{len(trajectory.expected)} outputs')
    for index, (actual, expected) in enumerate(zip(rows, trajectory.expected)):
        if actual != expected:
            raise RuntimeError(f'[NUMERIC] {trajectory.name} output {index}: {actual} != {expected}')
    return [row[2] for row in rows]


def check_dense(text, samples):
    matches = list(PASS.finditer(text))
    if len(matches) != 1 or re.search(r'\*\* (?:Error|Fatal)', text):
        raise RuntimeError('[SIMULATION] need exactly one PASS and no Error/Fatal')
    numbers = dict(zip(('samples', 'outputs', 'run_max', 'gap_max', 'out_gap_max', 'span', 'cycles'),
                       map(int, matches[0].groups())))
    expected = dict(samples=samples, outputs=samples, run_max=samples, gap_max=0,
                    out_gap_max=0, span=samples - 1)
    if any(numbers[key] != value for key, value in expected.items()):
        raise RuntimeError(f'[DENSE] incomplete coverage or unexpected gaps: {numbers}')
    numbers['hold_checks'] = hold_coverage(text, False)
    return numbers


def summarize(records):
    summary = []
    for snr in (None, 24., 12., 6.):
        cases = [record for record in records if record['snr_db'] == snr]
        summary.append(dict(snr_db=snr, cases=len(cases),
                            acquired=sum(r['acquired_window'] is not None for r in cases),
                            tracking_at_end=sum(r['last_two_windows_good'] for r in cases),
                            cases_with_quadrant_changes=sum(bool(r['quadrant_changes']) for r in cases),
                            bad_windows_after_acquisition=sum(
                                r['bad_windows_after_acquisition'] or 0 for r in cases)))
    return summary


@contextmanager
def record_failure(output, evidence, artifacts, commands, progress, reference_hash):
    """Даже отказ запуска сохраняет проверяемые хеши и фактическое незавершённое покрытие."""
    try:
        yield
    except Exception as error:
        command_log = output / 'commands.json'
        write_json(command_log, commands)
        if command_log not in artifacts:
            artifacts.append(command_log)
        write_json(output / 'acquisition_results.json', dict(
            status='FAIL', error=str(error), progress=progress, reference_sha256=reference_hash,
            **finish(evidence, artifacts)))
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, default=ROOT / 'build/rtl/costas_stream_acquisition_rtl',
                        help='новый каталог; существующий никогда не перезаписывается')
    args = parser.parse_args()
    require_unoptimized()
    reference_hash = digest(REFERENCE)
    reference = load_reference(REFERENCE)
    bindir, _ = questa_paths()
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    evidence = begin()
    target = output / 'acquisition_results.json'
    write_json(target, dict(evidence, status='RUNNING', reference_sha256=reference_hash))
    artifacts, commands = [REFERENCE], []
    progress = dict(positive_runs=0, negative_runs=0, bit_exact_output_words=0)
    with record_failure(output, evidence, artifacts, commands, progress, reference_hash):
        run_suite(output, evidence, artifacts, commands, progress, reference, reference_hash, bindir)


def run_suite(output, evidence, artifacts, commands, progress, reference, reference_hash, bindir):
    target = output / 'acquisition_results.json'

    def run(command, cwd, log, negative=False):
        command = [str(value) for value in command]
        result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=300)
        text = result.stdout + result.stderr
        log.write_text(text)
        artifacts.append(log)
        commands.append(dict(argv=command, cwd=str(cwd), returncode=result.returncode))
        if negative:
            return check_negative(text, result.returncode, 'NUMERIC', 'costas_stream output')
        if result.returncode != 0:
            raise RuntimeError(f'Command failed ({result.returncode}): {command[0]}\n{text[-6000:]}')
        return text

    run(['verilator', '--version'], output, output / 'verilator_version.log')
    run([sys.executable, '--version'], output, output / 'python_version.log')
    write_json(output / 'python_environment.json', dict(
        python=sys.version, numpy=study.np.__version__))
    artifacts.append(output / 'python_environment.json')
    python_log = run([sys.executable, '-m', 'pytest', '-q',
                      *sorted((ROOT / 'tests').glob('test_costas_stream_*.py')),
                      ROOT / 'tests/test_sync_fixed.py'], ROOT, output / 'python_tests.log')
    python_match = re.search(r'(\d+) passed(?:, (\d+) subtests passed)?', python_log)
    if not python_match:
        raise RuntimeError('[PYTHON] missing passing test count')
    progress.update(python_tests=int(python_match[1]), python_subtests=int(python_match[2] or 0))
    lint = run(['verilator', '--lint-only', '-Wall', '--top-module', 'costas_stream',
                f'-I{PILOT}', *SOURCES], ROOT, output / 'lint.log')
    if '%Warning' in lint:
        raise RuntimeError('[LINT] warnings in costas_stream')
    progress['lint'] = 'PASS'
    trajectories = prepare_vectors(output / 'vectors', reference)
    artifacts.extend(sorted((output / 'vectors').rglob('*.txt')))
    progress.update(model_reference_matches=len(trajectories),
                    generated_input_samples=len(trajectories) * study.LENGTH)
    for name in ('vsim', 'vlog'):
        run([bindir / name, '-version'], output, output / f'{name}_version.log')
    work = output / 'work'
    work.mkdir()
    run([bindir / 'vlib', 'work'], work, work / 'vlib.log')
    run([bindir / 'vlog', '-64', '-sv', f'+incdir+{PILOT}', *SOURCES,
         ROOT / 'rtl/tb/costas_stream_tb.sv'], work, work / 'compile.log')
    script = work / 'numeric_negative.do'
    script.write_text('onfinish stop\nonerror {quit -code 13}\n'
                      'onbreak {quit -code 13}\nrun -all\nquit -code 0\n')
    artifacts.append(script)
    resets = {}
    for active in RESETS:
        folder = output / f'reset_{active}'
        folder.mkdir()
        common = [bindir / 'vsim', '-64', '-c', '-quiet', 'work.costas_stream_tb',
                  f'-gRESET_ACTIVE={active}', f'-gTABLE_DIR={TABLES}']
        records, coverage = [], []
        for trajectory in trajectories:
            observed = folder / f'{trajectory.name}_out.txt'
            text = run([*common, f'+VECTORS={trajectory.folder}', f'+OBSERVED={observed}',
                        '-do', 'onerror {quit -code 1}; run -all; quit -code 0'],
                       work, folder / f'{trajectory.name}.log')
            numbers = check_dense(text, study.LENGTH)
            phases = check_observed(trajectory, observed)
            records.append(check_metrics(trajectory, phases))
            coverage.append(dict(name=trajectory.name, bit_exact=True, **numbers))
            artifacts.append(observed)
            progress['positive_runs'] += 1
            progress['bit_exact_output_words'] += len(phases)
            print(f'PASS ACQUISITION {trajectory.name} reset={active}: '
                  f'{len(phases)} bit-exact RTL outputs, metrics match JSON', flush=True)
        negative = run([*common, f'+VECTORS={trajectories[0].folder}', '+INJECT_MISMATCH',
                        '-do', script.name], work, folder / 'numeric_negative.log', negative=True)
        progress['negative_runs'] += 1
        resets[str(active)] = dict(cases=records[:-1], zero_gain_control=records[-1],
                                   summary=summarize(records[:-1]), coverage=coverage,
                                   negative=dict(case=trajectories[0].name, **negative))
    if digest(REFERENCE) != reference_hash:
        raise RuntimeError('[REFERENCE] saved study changed during the run')
    write_json(output / 'commands.json', commands)
    artifacts.append(output / 'commands.json')
    write_json(target, dict(status='PASS', reference_sha256=reference_hash,
                           samples=study.LENGTH, window=study.WINDOW, delay_advances=study.DELAY,
                           lint='PASS', records=resets,
                           counts=dict(trajectories=72, controls=1, reset_polarities=len(RESETS),
                                       positive_runs=len(trajectories) * len(RESETS),
                                       bit_exact_output_words=study.LENGTH * len(trajectories) * len(RESETS),
                                       negative_runs=len(RESETS), python_tests=int(python_match[1]),
                                       python_subtests=int(python_match[2] or 0)),
                           claims=dict(metrics='measured from bit-exact RTL OBSERVED phase words',
                                       reference='all per-trajectory fields equal the saved model JSON',
                                       scope='finite ideal-QPSK dense-input grid only; no full capture range',
                                       physical_timing='not measured; synthesis remains on agreed pause'),
                           **finish(evidence, artifacts)))
    require_pass(json.loads(target.read_text()))
    print(f'PASS ACQUISITION: 146 positive runs, 448512 bit-exact output words, '
          f'2 negative controls (exit 13); evidence: {target}', flush=True)


if __name__ == '__main__':
    main()
