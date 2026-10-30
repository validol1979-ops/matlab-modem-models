"""Model/runner tests; no simulator, compiler or synthesis is invoked here."""
import copy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import pytest
from scipy import signal

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
sys.path.insert(0, str(ROOT/'tools'))
from ext_signal_sos import SOSFilterFixed
from sos_rtl_cases import TracedSOS, cases, exhaustive_cases, write_vectors
from run_sos import PARAMETERS, check_run


@pytest.mark.parametrize('frac,bits', PARAMETERS)
def test_trace_independent_integer_recurrence(frac, bits):
    # Deliberately separate implementation: arbitrary-precision DF2T, exact rails.
    for _, sos, wave in cases():
        model = TracedSOS(sos, coef_bits=frac, state_bits=bits)
        history = [[[0, 0] for _ in model.sos] for _ in range(2)]
        count = 0
        for pair in wave:
            expected, trace = [], []
            for channel, value in enumerate(pair):
                for j, (b0, b1, b2, _, a1, a2) in enumerate(model.sos):
                    s1, s2 = history[channel][j]
                    raw_y = (b0*value+s1+2**(frac-1))//2**frac
                    y = max(-131071, min(131071, raw_y))
                    raw_s1, raw_s2 = b1*value-a1*y+s2, b2*value-a2*y
                    limit = 2**(bits-1)-1
                    ns1, ns2 = max(-limit, min(limit, raw_s1)), max(-limit, min(limit, raw_s2))
                    trace.extend(((raw_y, y), (raw_s1, ns1), (raw_s2, ns2)))
                    count += (raw_y != y)+(raw_s1 != ns1)+(raw_s2 != ns2)
                    history[channel][j] = [ns1, ns2]
                    value = y
                expected.append(value)
            actual, observed = model.sample(pair)
            assert actual == tuple(expected)
            assert observed == trace
            assert model.state == history
            assert model.clippings == count


def test_trace_does_not_change_fixed_model_and_stalls():
    sos = signal.butter(8, .3, output='sos')
    model, plain = TracedSOS(sos), SOSFilterFixed(sos)
    for pair in [(131071, -131072), (-1, 3), (0, 0)]*32:
        assert model.sample(pair)[0] == plain.push(pair)
        assert model.state == plain.state
        assert model.clippings == plain.clippings
        before = copy.deepcopy(plain.__dict__)
        plain.push(pair, accept=False)
        assert plain.__dict__ == before


def test_exhaustive_cases_cover_every_signed18_code():
    expected = -131072
    count = 0
    for _, sos, wave in exhaustive_cases():
        assert sos == [[.5, 0, 0, 1, 0, 0]]
        assert len(wave) == 8192
        for re, im in wave:
            assert re == expected
            assert im == -1-re
            assert -131072 <= im <= 131071
            expected += 1
            count += 1
    assert expected == 131072 and count == 262144


def test_scipy_and_limit_cycle_characterization():
    rng = np.random.default_rng(8202)
    wave = rng.integers(-3000, 3001, size=2048)
    for n in (1, 2, 4):
        for kind in ('lowpass', 'highpass'):
            sos = signal.butter(2*n, .3, btype=kind, output='sos')
            actual = np.asarray(SOSFilterFixed(sos).process(wave))[:, 0]
            assert np.sqrt(np.mean((actual-signal.sosfilt(sos, wave))**2)) < 12
    model = SOSFilterFixed([[1, 0, 0, 1, -.99, 0]])
    values = model.process([131071]+[0]*5000)
    assert max(abs(v[0]) for v in values[-1000:]) == 49
    r = .995
    sos = [[.001, 0, 0, 1, -2*r*np.cos(.19*np.pi), r*r]]
    wave = [20000]+[0]*7999
    values = np.asarray(SOSFilterFixed(sos).process(wave))[:, 0]
    assert max(abs(values-signal.sosfilt(sos, wave))) < 15
    assert max(abs(values[-1000:])) <= 15


@pytest.mark.parametrize('frac,bits', [(28, 40), (16, 64)])
def test_vector_format_and_determinism(tmp_path, frac, bits):
    path = tmp_path/'vectors.txt'
    report = write_vectors(path, frac, bits)
    original = path.read_bytes()
    assert write_vectors(path, frac, bits) == report
    assert path.read_bytes() == original
    assert json.loads(path.with_suffix('.json').read_text()) == report
    words = iter(path.read_text().split())
    number = int(next(words))
    total = 0
    for _ in range(number):
        ns, length = int(next(words)), int(next(words))
        assert ns in (1, 2, 4)
        for _ in range(ns*5):
            assert -(2**31) <= int(next(words)) <= 2**31-1
        for _ in range(length):
            re, im, last, yr, yi, sat = (int(next(words)) for _ in range(6))
            assert -131072 <= re <= 131071 and -131072 <= im <= 131071
            assert -131071 <= yr <= 131071 and -131071 <= yi <= 131071
            assert last in (0, 1) and sat in (0, 1)
            for _ in range(ns*2):
                y, s1, s2, ry, rs1, rs2 = (int(next(words)) for _ in range(6))
                assert y == max(-131071, min(131071, ry))
                assert s1 == max(-(2**(bits-1)-1), min(2**(bits-1)-1, rs1))
                assert s2 == max(-(2**(bits-1)-1), min(2**(bits-1)-1, rs2))
        total += length
    assert next(words, None) is None
    assert total == report['samples']
    assert report['clippings'] > 0


def test_result_gates():
    marker = 'PASS SOS: samples=7 raw_checks=42 input_stalls=1 output_stalls=1 cfg_blocked=2 collisions=1\n'
    rate = 'PASS RATE: latency=12,23,45 interval=13,24,46\n'
    assert check_run(0, marker+rate, 7, 42)['samples'] == 7
    assert check_run(13, '%Error: [NUMERIC] deliberate', 7, 42, '[NUMERIC]')['returncode'] == 13
    assert check_run(13, '** Fatal: [PROTOCOL] deliberate', 7, 42, '[PROTOCOL]')['returncode'] == 13
    for rc, text in ((0, '%Error: [NUMERIC]'), (-6, '%Error: [NUMERIC]'),
                     (1, '%Error: [NUMERIC]'), (13, '%Error: [OTHER]'),
                     (13, '[NUMERIC] no fatal'), (13, '%Error: [NUMERIC]\n'+marker)):
        with pytest.raises(RuntimeError):
            check_run(rc, text, 7, 42, '[NUMERIC]')
    for text in (marker, marker+rate+'%Error: other', marker.replace('samples=7', 'samples=6')+rate,
                 marker.replace('collisions=1', 'collisions=0')+rate):
        with pytest.raises(RuntimeError):
            check_run(0, text, 7, 42)


def test_output_refuses_existing_directory(tmp_path):
    result = subprocess.run([sys.executable, ROOT/'tools/run_sos.py', '--suite', 'python',
                             '--output-dir', tmp_path], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'FileExistsError' in result.stderr
    assert not (tmp_path/'results.json').exists()


def test_optimized_python_rejected(tmp_path):
    output = tmp_path/'not_created'
    result = subprocess.run([sys.executable, '-O', ROOT/'tools/run_sos.py', '--suite', 'python',
                             '--output-dir', output], capture_output=True, text=True)
    assert result.returncode != 0
    assert 'without Python optimization' in result.stderr
    assert not output.exists()
