#!/usr/bin/env python3
"""Accept Python CIC models against independent FIR references; no HDL tools."""
import argparse
from fractions import Fraction
import importlib.util
import math
from pathlib import Path
import random
import sys
import unittest

import numpy as np

from regression_evidence import ROOT, begin, digest, finish, write_json

sys.path.insert(0, str(ROOT / 'common/python'))
import cic_model as cic
import cic_reference as ref


def compare(actual, expected):
    if actual != expected:
        raise RuntimeError('CIC numeric comparison failed')


def normalized_reference(values, gain):
    # Rational arithmetic independently specifies rounding, including negative ties.
    return [tuple(max(-131072, min(131071, math.floor(Fraction(v, gain) + Fraction(1, 2))))
                  for v in pair) for pair in values]


def sweep():
    records = []
    controls = []
    for rate in range(1, 33):
        for stages in (1, 2, 3, 5):
            for delay in (1, 2):
                rng = random.Random(10000 * rate + 100 * stages + delay)
                for kind in ('decimate', 'interpolate'):
                    count = rate * (stages * delay + 8) if kind == 'decimate' else 2 * stages * delay + 8
                    signals = {
                        'impulse': [(131071, -131072)] + [(0, 0)] * (count - 1),
                        'dc': [(1024, -1024)] * count,
                        'alternating': [(131071, -131072) if k % 2 == 0 else (-131072, 131071) for k in range(count)],
                        'random': [(rng.randrange(-131072, 131072), rng.randrange(-131072, 131072)) for _ in range(count)],
                    }
                    gain = cic.cic_gain(rate, stages, delay, kind)
                    function = getattr(cic, kind)
                    reference = getattr(ref, kind + '_reference')
                    max_float_error = 0.0
                    words = 0
                    raw_peak = 0
                    for name, values in signals.items():
                        actual = function(values, rate, stages=stages, delay=delay)
                        expected = reference(values, rate, stages=stages, delay=delay)
                        compare(actual, expected)
                        want_count = count // rate if kind == 'decimate' else count * rate
                        if len(actual) != want_count:
                            raise RuntimeError('CIC output count mismatch')
                        normalized = function(values, rate, stages=stages, delay=delay, normalize=True)
                        compare(normalized, normalized_reference(expected, gain))
                        floating = np.asarray(ref.float_reference(values, rate, stages, delay, kind), dtype=complex)
                        integer = np.asarray([complex(*z) for z in expected])
                        if floating.shape != integer.shape:
                            raise RuntimeError('Floating FIR reference count mismatch')
                        error = float(np.max(np.abs(floating - integer))) if len(integer) else 0.0
                        tolerance = 128 * np.finfo(float).eps * gain * rate * 131072
                        if error > tolerance:
                            raise RuntimeError('Independent floating FIR mismatch')
                        max_float_error = max(max_float_error, error)
                        raw_peak = max(raw_peak, max((abs(v) for z in expected for v in z), default=0))
                        words += len(actual)
                        if name == 'dc':
                            compare(actual[-1], (1024 * gain, -1024 * gain))
                            compare(normalized[-1], (1024, -1024))
                        # Deliberately corrupt a result: both directions must reject it.
                        if rate == 3 and stages == 3 and delay == 2 and name == 'random':
                            damaged = list(actual)
                            damaged[-1] = (damaged[-1][0] + 1, damaged[-1][1])
                            try:
                                compare(damaged, expected)
                            except RuntimeError:
                                controls.append(dict(kind=kind, tag='NUMERIC', rejected=True))
                            else:
                                raise RuntimeError('CIC negative numeric control escaped')
                    records.append(dict(kind=kind, rate=rate, stages=stages, delay=delay,
                        gain=gain, register_width=cic.register_width(18, 32, stages, delay, kind),
                        signals=list(signals), output_words=words, peak_raw=raw_peak,
                        max_float_error=max_float_error))
    if len(records) != 512 or len(controls) != 2:
        raise RuntimeError('Incomplete CIC sweep')
    return records, controls


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'build/cic_models_20261030/results.json')
    args = parser.parse_args()
    if not __debug__:
        raise RuntimeError('Run model verification without -O')
    target = args.output.resolve()
    if target.exists():
        raise RuntimeError('Use a fresh output path; previous evidence is preserved')
    evidence = begin()
    original_rtl = {str(p.relative_to(ROOT)): digest(p) for p in sorted((ROOT / 'rtl').rglob('*'))
                    if p.is_file() and p.suffix in ('.sv', '.svh') and 'tb' not in p.relative_to(ROOT / 'rtl').parts}
    write_json(target, dict(status='RUNNING', scope='CIC Python models only', **evidence))
    log = target.with_suffix('.unittest.log')
    try:
        spec = importlib.util.spec_from_file_location('cic_independent_tests', ROOT / 'tests/test_cic_models.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        suite = unittest.defaultTestLoader.loadTestsFromModule(module)
        with log.open('w') as stream:
            result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
        if not result.wasSuccessful() or result.testsRun == 0:
            raise RuntimeError('CIC independent model tests failed: ' + str(log))
        records, controls = sweep()
        agent_dir = ROOT / 'build/model_agents_20261030'
        if not original_rtl or any(digest(ROOT / p) != value for p, value in original_rtl.items()):
            raise RuntimeError('Production RTL changed during the models-only stage')
        artifacts = [log]
        # Numerical acceptance also works in a clean checkout. Agent logs are
        # optional provenance from the authoring run, not required model inputs.
        artifacts.extend(p for p in (agent_dir / 'contract.txt', agent_dir / 'production_rtl_baseline.json',
                     agent_dir / 'qulab_models_found.json', agent_dir / 'qulab_models_api_check.json',
                     agent_dir / 'agent_manifest.json', agent_dir / 'deepseek/local_test_run.log') if p.is_file())
        artifacts.extend(p for p in (ROOT / 'build/model_agents_20261030/logs').glob('*.log'))
        artifacts.extend(p for p in (ROOT / 'build/model_agents_20261030').glob('*/report.txt'))
        write_json(target, dict(status='PASS', scope='CIC Python models only; no RTL or FPGA timing acceptance',
            python_tests=result.testsRun, profiles=len(records), signal_cases=sum(len(r['signals']) for r in records),
            output_words=sum(r['output_words'] for r in records), records=records,
            numeric_negative_controls=controls, production_rtl_unchanged=len(original_rtl),
            agent_provenance_available=(agent_dir / 'agent_manifest.json').is_file(),
            agents={'implementation':'pi openwebui/Qwen/Qwen3.8-Flash-Next-FP8',
                    'independent_reference':'OpenCode openwebui/~anthropic/claude-haiku-latest',
                    'independent_tests':'pi openwebui/~deepseek/deepseek-v4-flash-latest',
                    'endpoint':'<internal-llm-endpoint>'},
            **finish(evidence, artifacts)))
        print(f'PASS CIC models: {result.testsRun} tests, {len(records)} profiles, '
              f'{sum(r["output_words"] for r in records)} output words')
    except Exception as exc:
        write_json(target, dict(status='FAIL', error=f'{type(exc).__name__}: {exc}', **evidence))
        raise


if __name__ == '__main__':
    main()
