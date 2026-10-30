#!/usr/bin/env python3
"""Capture input hashes before MATLAB and publish evidence only after validation."""
import argparse
import json
import subprocess
from regression_evidence import ROOT, begin, finish, write_json, mquote


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--suite', choices=['audit', 'compatible', 'references', 'research'], required=True)
    parser.add_argument('--modem')
    args = parser.parse_args()
    if args.modem and args.suite not in ('audit', 'compatible', 'research'):
        parser.error('--modem requires audit, compatible or research')
    if args.modem and ('/' in args.modem or not (ROOT/'modems'/args.modem/'config.json').is_file()):
        parser.error('Unknown modem name')
    if args.suite in ('audit', 'compatible'):
        output = ROOT/'build/matlab_originals'/args.suite
        command = f"matlab_check_originals('{args.suite}','{mquote(args.modem or '')}');"
        raw = 'results.json'
    elif args.suite == 'research':
        output = ROOT/'build/research_review'
        command = f"matlab_check_research(16384,'{mquote(args.modem or '')}');"
        raw = 'matlab_results.json'
    else:
        output = ROOT/'build/typed/originals'
        command = 'matlab_research_references;'
        raw = 'checks.json'
    if args.modem:
        output = output/'single'/args.modem
    output.mkdir(parents=True, exist_ok=True)
    target = output/('matlab_results.json' if args.suite == 'references' else 'evidence.json')
    evidence = begin()
    write_json(target, dict(evidence, status='RUNNING'))
    log = output/'runner.log'
    script = f"addpath('{mquote(ROOT/'tools')}'); {command}"
    result = subprocess.run([str(ROOT/'tools/matlab.sh'), '-nodisplay', '-batch', script, '-logfile',str(log)],cwd=ROOT)
    if result.returncode:
        raise RuntimeError(f'MATLAB failed ({result.returncode}); inspect {log}')
    checks = json.loads((output/raw).read_text())
    if not isinstance(checks, list):
        checks = [checks]
    expected_count = 1 if args.modem else {'audit':20, 'compatible':20, 'references':14, 'research':2}[args.suite]
    if len(checks) != expected_count:
        raise RuntimeError('Incomplete MATLAB checks')
    if args.suite == 'audit':
        expectations = json.loads((ROOT/'docs/matlab_audit_expectations.json').read_text())
        for row in checks:
            expected = expectations[row['name']]
            if row['load_status'] != 'PASS' or any(row.get(k, '') != v for k,v in expected.items()):
                raise RuntimeError(f"Unexpected audit result: {row['name']}")
    elif any(row['status'] != 'PASS' for row in checks):
        raise RuntimeError('Failed MATLAB checks')
    artifacts = [log, output/raw, *output.glob('*.mat')]
    for row in checks:
        name=row.get('name',row.get('model'))
        if name and (output/name).is_dir():
            artifacts.extend(p for p in (output/name).iterdir() if p.is_file() and p.suffix in ('.mat','.log','.json'))
    write_json(target, dict(finish(evidence, artifacts), status='PASS', checks=checks))
    print(f'PASS MATLAB {args.suite}: {len(checks)} checks')


if __name__ == '__main__':
    main()
