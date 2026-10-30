"""CIC RTL vector/runner contract, no simulator invocation."""
import json
from pathlib import Path
import sys
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
sys.path.insert(0, str(ROOT / 'tools'))
from cic_rtl_cases import (PROFILES, Profile, cases, independent_format, vectors, wave)
import run_cic


def test_matrix_and_exact_widths():
    assert len(PROFILES) == 18
    assert len({p.name for p in PROFILES}) == 18
    for p in PROFILES[:16]:
        assert p.width == 18 + p.stages * (5 if p.delay == 1 else 6)
    assert PROFILES[-1].width == 18


@pytest.mark.parametrize('profile', PROFILES)
def test_fir_fixed_equivalence_and_continuous_frames(profile):
    generated = list(cases(profile))
    assert len(generated) == 161
    assert {r for r, *_ in generated} == set(range(1, 33))
    assert {kind for _, kind, *_ in generated} == set(('impulse', 'dc', 'alternating', 'rails', 'random', 'ties'))
    assert sum(len(outs) for _, _, _, outs in generated) == 2564
    for rate, _kind, inputs, outputs in generated:
        assert len(inputs) == rate * len(outputs)
        assert sum(row[2] for row in inputs) == sum(row[2] for row in outputs) == 2
        assert [i for i, row in enumerate(inputs) if row[2]] == [len(inputs)//2-1, len(inputs)-1]
        assert all(-131072 <= v <= 131071 for row in inputs for v in row[:2])


def test_independent_half_ties_and_wrap():
    p = Profile(1, 1, True)
    assert [independent_format(v, p, 2) for v in (-5, -3, -1, 1, 3, 5)] == [-2, -1, 0, 1, 2, 3]
    p = Profile(5, 2, False, 18)
    assert independent_format(131072, p, 1) == -131072
    assert independent_format(-131073, p, 1) == 131071
    assert wave('random', 64, 1) == wave('random', 64, 1)
    with pytest.raises(ValueError):
        wave('bogus', 4, 1)


def test_vector_serialization(tmp_path):
    p = Profile(1, 1)
    path = tmp_path / 'vectors.txt'
    report = vectors(path, p)
    assert report == dict(profile=p.name, cases=161, inputs=42248, outputs=2564, frames=322)
    rows = iter(path.read_text().splitlines())
    count = 0
    while (header := next(rows, None)) is not None:
        rate, ni, no = map(int, header.split())
        assert ni == rate * no
        for _ in range(ni + no):
            assert len(list(map(int, next(rows).split()))) == 3
        count += 1
    assert count == 161


def success_log(active=1):
    return '\n'.join(f'PASS CIC profile={p.name} reset={active} cases=161 outputs=2564 adjacent=1 stalls_in=2 stalls_out=3'
                     for p in PROFILES) + f'\nPASS CIC ALL reset={active} profiles=18\n'


def test_runner_success_gate():
    log = success_log()
    assert len(run_cic.check_run(0, log, 1)['profiles']) == 18
    for rc, text in ((13, log), (0, 'PASS CIC ALL reset=1 profiles=18'),
                     (0, log.replace('outputs=2564', 'outputs=2563')),
                     (0, log + '\n%Error fail'), (0, log.replace('reset=1', 'reset=0'))):
        with pytest.raises(RuntimeError):
            run_cic.check_run(rc, text, 1)


@pytest.mark.parametrize('kind,tag', [('numeric', '[NUMERIC]'), ('protocol', '[PROTOCOL]')])
def test_runner_exact_negative_failure_code(kind, tag):
    for prefix in ('%Error: tb.sv:10: ', '%Fatal: tb.sv:10: ', '** Fatal: '):
        assert run_cic.check_run(13, prefix + tag, 0, kind)['returncode'] == 13
        for rc in (0, 1, -6, 134):
            with pytest.raises(RuntimeError):
                run_cic.check_run(rc, prefix + tag, 0, kind)
    for text in (tag, '%Error: [TIMEOUT]', '%Error: ' + tag + '\nPASS CIC ALL'):
        with pytest.raises(RuntimeError):
            run_cic.check_run(13, text, 0, kind)


def test_runner_refuses_existing_output(tmp_path):
    path = tmp_path / 'existing'
    path.mkdir()
    sentinel = path / 'sentinel'
    sentinel.write_text('unchanged')
    with patch.object(run_cic, 'begin', side_effect=AssertionError('must not start')):
        with pytest.raises(FileExistsError):
            run_cic.main(['--suite', 'python', '--output-dir', str(path)])
    assert sentinel.read_text() == 'unchanged'


def test_runner_lint_status_and_evidence(tmp_path):
    path = tmp_path / 'fresh'
    with patch.object(run_cic, 'lint', return_value={'status': 'PASS'}) as lint:
        run_cic.main(['--suite', 'lint', '--simulator', 'verilator', '--output-dir', str(path)])
    assert lint.call_count == 1
    result = json.loads((path / 'results.json').read_text())
    assert result['status'] == 'PASS'
    assert result['source_hashes'] and result['completed_at_utc']
    assert result['simulator'] == 'verilator'


def test_runner_failure_status(tmp_path):
    path = tmp_path / 'failed'
    with patch.object(run_cic, 'lint', side_effect=RuntimeError('injected lint failure')):
        with pytest.raises(RuntimeError, match='injected lint failure'):
            run_cic.main(['--suite', 'lint', '--output-dir', str(path)])
    result = json.loads((path / 'results.json').read_text())
    assert result['status'] == 'FAIL' and 'injected lint failure' in result['error']
    assert 'completed_at_utc' not in result
