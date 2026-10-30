#!/usr/bin/env python3
"""Run the 17 streaming FFT/DSP/OQPSK suites without vendor synthesis."""
import argparse
import json
import subprocess
import sys

from regression_evidence import ROOT, begin, finish, require_pass, write_json

BLOCKS = ('fft', 'ofdm', 'stft', 'pfb', 'fir', 'oset', 'fsk', 'beam', 'sync',
          'lms', 'ldpc', 'mmse', 'mmse3', 'mmse_n', 'rls', 'omlsa', 'oqpsk')


def main():
    if not __debug__:
        raise RuntimeError('Verification requires Python assertions enabled')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite', choices=('python', 'lint', 'hdl', 'all'), default='all')
    parser.add_argument('--blocks', nargs='+', choices=BLOCKS, default=BLOCKS)
    args = parser.parse_args()
    blocks = list(dict.fromkeys(args.blocks))
    output = ROOT / 'build/rtl/streaming'
    output.mkdir(parents=True, exist_ok=True)
    target = output / f'{args.suite}_results.json'
    evidence = begin()
    write_json(target, dict(status='RUNNING', blocks=blocks, **evidence))
    records, artifacts = {}, []
    for block in blocks:
        log = output / f'{block}_{args.suite}.log'
        result = subprocess.run([sys.executable, str(ROOT / f'tools/run_{block}.py'),
                                 '--suite', args.suite], cwd=ROOT, capture_output=True, text=True)
        log.write_text(result.stdout + result.stderr)
        artifacts.append(log)
        report = ROOT / f'build/rtl/{block}/{args.suite}_results.json'
        try:
            if result.returncode:
                raise RuntimeError(f'Runner exited with {result.returncode}')
            data = json.loads(report.read_text())
            require_pass(data)
            if data['started_at_utc'] < evidence['started_at_utc']:
                raise RuntimeError('Runner did not produce a new result for this invocation')
            artifacts.extend([report, *(ROOT / p for p in data.get('artifact_hashes', {}))])
            records[block] = dict(status='PASS', result=str(report.relative_to(ROOT)))
            print(f'PASS {block} {args.suite}', flush=True)
        except (RuntimeError, ValueError, OSError) as exc:
            records[block] = dict(status='FAIL', error=str(exc), log=str(log.relative_to(ROOT)))
            print(f'FAIL {block}: {exc}\n{log.read_text()[-6000:]}', flush=True)
    protocol = None
    saturation_checker = None
    grouped_saturation_checker = None
    if args.suite in ('all', 'hdl'):
        log = output / 'axis_contract.log'
        result = subprocess.run([sys.executable, str(ROOT / 'tools/run_axis_contract.py')],
                                cwd=ROOT, capture_output=True, text=True)
        log.write_text(result.stdout + result.stderr)
        artifacts.append(log)
        report = ROOT / 'build/rtl/axis_contract/all_results.json'
        try:
            if result.returncode:
                raise RuntimeError(f'Protocol runner exited with {result.returncode}')
            data = json.loads(report.read_text())
            require_pass(data)
            if data['started_at_utc'] < evidence['started_at_utc']:
                raise RuntimeError('Protocol runner did not produce a new result')
            artifacts.extend([report, *(ROOT / p for p in data.get('artifact_hashes', {}))])
            protocol = dict(status='PASS', result=str(report.relative_to(ROOT)))
            print('PASS axis protocol controls', flush=True)
        except (RuntimeError, ValueError, OSError) as exc:
            protocol = dict(status='FAIL', error=str(exc), log=str(log.relative_to(ROOT)))
            print(f'FAIL axis protocol controls: {exc}\n{log.read_text()[-6000:]}', flush=True)
        log = output / 'sat_event.log'
        result = subprocess.run([sys.executable, str(ROOT / 'tools/run_sat_event.py')],
                                cwd=ROOT, capture_output=True, text=True)
        log.write_text(result.stdout + result.stderr)
        artifacts.append(log)
        report = ROOT / 'build/rtl/sat_event/all_results.json'
        try:
            if result.returncode:
                raise RuntimeError(f'Saturation checker runner exited with {result.returncode}')
            data = json.loads(report.read_text())
            require_pass(data)
            if data['started_at_utc'] < evidence['started_at_utc']:
                raise RuntimeError('Saturation checker runner did not produce a new result')
            artifacts.extend([report, *(ROOT / p for p in data.get('artifact_hashes', {}))])
            saturation_checker = dict(status='PASS', result=str(report.relative_to(ROOT)))
            print('PASS saturation checker controls', flush=True)
        except (RuntimeError, ValueError, OSError) as exc:
            saturation_checker = dict(status='FAIL', error=str(exc), log=str(log.relative_to(ROOT)))
            print(f'FAIL saturation checker controls: {exc}\n{log.read_text()[-6000:]}', flush=True)
        log = output / 'sat_group.log'
        result = subprocess.run([sys.executable, str(ROOT / 'tools/run_sat_group.py')],
                                cwd=ROOT, capture_output=True, text=True)
        log.write_text(result.stdout + result.stderr)
        artifacts.append(log)
        report = ROOT / 'build/rtl/sat_group/all_results.json'
        try:
            if result.returncode:
                raise RuntimeError(f'Grouped saturation checker exited with {result.returncode}')
            data = json.loads(report.read_text())
            require_pass(data)
            if data['started_at_utc'] < evidence['started_at_utc']:
                raise RuntimeError('Grouped saturation checker did not produce a new result')
            artifacts.extend([report, *(ROOT / p for p in data.get('artifact_hashes', {}))])
            grouped_saturation_checker = dict(status='PASS', result=str(report.relative_to(ROOT)))
            print('PASS grouped saturation checker controls', flush=True)
        except (RuntimeError, ValueError, OSError) as exc:
            grouped_saturation_checker = dict(status='FAIL', error=str(exc), log=str(log.relative_to(ROOT)))
            print(f'FAIL grouped saturation checker controls: {exc}\n{log.read_text()[-6000:]}', flush=True)
    passed = (all(record['status'] == 'PASS' for record in records.values())
              and (protocol is None or protocol['status'] == 'PASS')
              and (saturation_checker is None or saturation_checker['status'] == 'PASS')
              and (grouped_saturation_checker is None or grouped_saturation_checker['status'] == 'PASS'))
    write_json(target, dict(status='PASS' if passed else 'FAIL', blocks=blocks, records=records,
                            protocol=protocol,
                            saturation_checker=saturation_checker,
                            grouped_saturation_checker=grouped_saturation_checker,
                            **finish(evidence, list(dict.fromkeys(artifacts)))))
    print(f"{'PASS' if passed else 'FAIL'} streaming RTL {args.suite}: "
          f"{sum(r['status'] == 'PASS' for r in records.values())}/{len(blocks)} suites", flush=True)
    return 0 if passed else 1


if __name__ == '__main__':
    sys.exit(main())
