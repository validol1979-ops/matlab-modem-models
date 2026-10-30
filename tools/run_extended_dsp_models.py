#!/usr/bin/env python3
"""Run the complete library DSP model backlog; never invokes HDL tools."""
import argparse
import importlib.util
import json
from pathlib import Path
import sys
import unittest

from regression_evidence import ROOT, begin, digest, finish, require_unoptimized, write_json

sys.path.insert(0, str(ROOT / 'common/python'))

PLAN = ROOT / 'research/full_dsp_20261030/model_plan.json'
BASELINE = ROOT / 'research/full_dsp_20261030/rtl_baseline.json'
LEGACY = ROOT / 'research/full_dsp_20261030/initial_legacy_hashes.json'


def local_file(name, prefix):
    if not isinstance(name, str):
        raise RuntimeError('Manifest file paths must be strings')
    path = (ROOT / name).resolve()
    if not path.is_relative_to((ROOT / prefix).resolve()) or not path.is_file():
        raise RuntimeError(f'Invalid or missing model acceptance input: {name}')
    return path


def read_plan(groups):
    plan = json.loads(PLAN.read_text())
    catalogs = [json.loads((ROOT / name).read_text()) for name in (
        'research/library_dsp_20261029/task_catalog.json',
        'research/library_dsp_20261030_round2/task_additions.json')]
    catalog_ids = [row['id'] for catalog in catalogs for row in catalog['tasks']]
    prior = {'DSP-CIC-DEC', 'DSP-CIC-INT', 'DSP-CIC-COMP', 'DSP-RATIONAL'}
    assigned = [task for tasks in plan['groups'].values() for task in tasks]
    if (len(catalog_ids) != 44 or len(set(catalog_ids)) != 44
            or len(assigned) != 40 or len(set(assigned)) != 40
            or set(plan['prior_completed']) != prior
            or set(assigned) | prior != set(catalog_ids)):
        raise RuntimeError('Plan must cover all 44 canonical library tasks exactly once')
    expected = {task for group in groups for task in plan['groups'][group]}
    records, manifests = {}, []
    for group in groups:
        path = ROOT / f'research/full_dsp_20261030/{group}/manifest.json'
        data = json.loads(path.read_text())
        manifests.append(path)
        for task, row in data['tasks'].items():
            if task not in plan['groups'][group] or task in records:
                raise RuntimeError(f'Unexpected or repeated task: {task}')
            if row.get('state') not in ('ready_for_root_review', 'root_review_passed'):
                raise RuntimeError(f'Task is not ready: {task}')
            for field in ('contract', 'sources', 'model_scope', 'fixed_scope', 'numerical_results'):
                if not row.get(field):
                    raise RuntimeError(f'Missing {field}: {task}')
            if isinstance(row['contract'], str) and row['contract'].startswith('build/'):
                raise RuntimeError(f'Contract must survive a clean checkout: {task}')
            if not row.get('modules') or not row.get('tests'):
                raise RuntimeError(f'Missing executable models or tests: {task}')
            for name in row['modules']:
                local_file(name, 'common/python')
            for name in row['tests']:
                local_file(name, 'tests')
            records[task] = row
    if set(records) != expected:
        raise RuntimeError(f'Incomplete backlog: {sorted(expected-set(records))}')
    return plan, records, manifests


def verify_rtl():
    baseline = json.loads(BASELINE.read_text())
    current = {str(path.relative_to(ROOT)): digest(path)
               for path in (ROOT / 'rtl').rglob('*') if path.is_file()}
    if baseline != current:
        changed = sorted(name for name in baseline.keys() | current.keys()
                         if baseline.get(name) != current.get(name))
        raise RuntimeError(f'RTL changed during model-only work: {changed}')
    return len(current)


def verify_legacy():
    baseline = json.loads(LEGACY.read_text())
    changed = [name for name, expected in baseline.items()
               if not (ROOT / name).is_file() or digest(ROOT / name) != expected]
    if set(changed) - {'tools/run_tests.py'}:
        raise RuntimeError(f'Existing Python files changed outside the test registry: {changed}')
    return len(baseline)


def artifact_paths(groups, records=()):
    paths = [PLAN, BASELINE, LEGACY,
        ROOT / 'research/library_dsp_20261029/task_catalog.json',
        ROOT / 'research/library_dsp_20261030_round2/task_additions.json']
    for group in groups:
        directory = ROOT / f'research/full_dsp_20261030/{group}'
        paths.extend((directory / 'manifest.json', directory / 'external_agents.json'))
        paths.extend(path for path in directory.rglob('*')
                     if path.is_file() and path.suffix in ('.json', '.txt'))
    for row in records:
        contract = row['contract']
        if isinstance(contract, str) and contract.startswith(('research/', 'docs/')):
            paths.append(local_file(contract, contract.split('/')[0]))
    if 'advanced' in groups:
        for algorithm in ('imcra', 'dpd'):
            paths.extend((ROOT / f'tests/data/{algorithm}_source_reference_20261030.npz',
                          ROOT / f'research/full_dsp_20261030/{algorithm}_reference.json'))
        paths.extend((ROOT / 'tests/data/eq16_source_prototype_20261030.json',
                      ROOT / 'research/full_dsp_20261030/eq16_reference.json'))
    return sorted(set(paths))


def run_tests(files):
    suite = unittest.TestSuite()
    counts = {}
    for index, name in enumerate(sorted(files)):
        path = local_file(name, 'tests')
        spec = importlib.util.spec_from_file_location(f'extended_dsp_test_{index}', path)
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        tests = unittest.defaultTestLoader.loadTestsFromModule(module)
        counts[name] = tests.countTestCases()
        if not counts[name]:
            raise RuntimeError(f'No tests found in {name}')
        suite.addTests(tests)
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    if not result.wasSuccessful() or result.skipped or result.expectedFailures:
        raise RuntimeError('DSP model acceptance requires passing tests without skips or expected failures')
    return result.testsRun, counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--group', choices=('signal', 'coding', 'advanced'))
    parser.add_argument('--output', type=Path)
    parser.add_argument('--frozen-baseline', action='store_true',
                        help='also require RTL and legacy Python hashes of the 2026-10-30 model-only campaign')
    args = parser.parse_args()
    require_unoptimized()
    groups = [args.group] if args.group else ['signal', 'coding', 'advanced']
    evidence = begin()
    # Bind metadata and fixtures BEFORE reading manifests or executing tests.
    evidence['artifact_hashes'] = {str(path.relative_to(ROOT)): digest(path)
                                   for path in artifact_paths(groups)}
    plan, tasks, _ = read_plan(groups)
    artifacts = artifact_paths(groups, tasks.values())
    for path in artifacts:
        name = str(path.relative_to(ROOT))
        if name not in evidence['artifact_hashes']:
            evidence['artifact_hashes'][name] = digest(path)
    # Замороженная база относится к кампании 2026-10-30; после неё RTL и код меняются штатно.
    rtl_tree = lambda: sorted(str(p.relative_to(ROOT)) for p in (ROOT/'rtl').rglob('*') if p.is_file())
    rtl_before = rtl_tree()
    rtl_files = verify_rtl() if args.frozen_baseline else len(rtl_before)
    legacy_files = verify_legacy() if args.frozen_baseline else 0
    tests = {name for row in tasks.values() for name in row['tests']}
    if not args.group:
        # Include the four model stages verified before this expansion.
        tests.update(('tests/test_cic_models.py', 'tests/test_filter_models.py'))
        tests.add('tests/test_ext_cross_models.py')
    count, counts = run_tests(tests)
    if rtl_tree() != rtl_before or (args.frozen_baseline and verify_rtl() != rtl_files):
        raise RuntimeError('RTL file set changed during acceptance')
    if args.frozen_baseline:
        verify_legacy()
    if artifacts != artifact_paths(groups, tasks.values()):
        raise RuntimeError('Acceptance input file set changed during tests')
    evidence.update(status='PASS', scope='Python floating/fixed models only',
        groups=groups, new_tasks_verified=len(tasks),
        total_model_stages_verified=len(tasks)+(len(plan['prior_completed']) if not args.group else 0),
        tests_run=count, tests_per_file=counts, tasks=tasks,
        rtl_tree_unchanged=True, rtl_files_checked=rtl_files, frozen_baseline_checked=args.frozen_baseline,
        legacy_python_files_checked=legacy_files,
        legacy_python_changes_allowed=['tools/run_tests.py: register extended model tests'],
        vendor_compilation_performed=False, hdl_simulation_performed=False)
    # Исторический docs-отчёт перезаписывается только при проверке замороженной базы.
    output = args.output or (ROOT / 'docs/extended_dsp_models_20261030_results.json'
                             if args.frozen_baseline and not args.group else
                             ROOT / f'build/full_dsp_20261030/acceptance/{args.group or "all"}_results.json')
    write_json(output, finish(evidence, artifacts))
    print(f'PASS: {len(tasks)} new model stages, {count} tests; {output}')


if __name__ == '__main__':
    main()
