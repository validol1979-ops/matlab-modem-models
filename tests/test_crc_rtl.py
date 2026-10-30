"""CRC vectors and acceptance gates; these tests never launch an HDL simulator."""
from dataclasses import replace
import json
from pathlib import Path
import random
import subprocess
import sys
from unittest.mock import patch
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'common/python'), str(ROOT / 'tools')]
import crc_rtl_cases as cases
import run_crc as runner
from ext_code_basics import crc_parallel, crc_update


@pytest.mark.parametrize('width', [1, 7, 16, 32])
def test_independent_division_and_random_chunking(width):
    rng = random.Random(818 + width)
    for reflected in (False, True):
        for refout in (False, True):
            for _ in range(20):
                cfg = cases.Config(width, 0, rng.getrandbits(width), rng.getrandbits(width),
                                   rng.getrandbits(width), reflected, refout)
                bits = [rng.randrange(2) for _ in range(rng.randrange(140))]
                assert cases.model_crc(bits, cfg) == cases.divide_crc(bits, cfg)
                state = cfg.init
                at = 0
                while at < len(bits):
                    n = min(rng.choice((1, 8, 32)), len(bits)-at)
                    chunk = bits[at:at+n]
                    word = sum(b << (j if reflected else n-1-j) for j, b in enumerate(chunk))
                    state = crc_parallel(state, word, n, width, cfg.poly, reflected)
                    assert state == crc_update(cfg.init, bits[:at+n], width, cfg.poly, reflected)
                    at += n


@pytest.mark.parametrize('width,word_bits', runner.MATRIX)
def test_vector_matrix_and_wire_formats(tmp_path, width, word_bits):
    path = tmp_path / 'vectors.txt'
    report = cases.write_vectors(path, width, word_bits)
    entries = cases.cases(width, word_bits)
    assert int(path.read_text().splitlines()[0]) == report['frames'] == len(entries)
    assert report['outputs'] == sum(len(e['outputs']) for e in entries)
    assert report['rejected_fcs'] > 70
    assert {e['cfg'].mode for e in entries} == {0, 1, 2}
    assert any(e['inputs'] == [(0, 0, 1)] for e in entries)
    if word_bits > 1:
        assert any(0 < e['inputs'][-1][1] < word_bits for e in entries)
    for e in entries:
        assert sum(row[2] for row in e['outputs']) == 1
        assert e['outputs'][-1][2] == 1
        for d, n, last in e['inputs']:
            assert 0 <= n <= word_bits and 0 <= d < (1 << n)
            assert last or n == word_bits


@pytest.mark.parametrize('reflected,width,poly,known', [(True,32,0xedb88320,0xcbf43926),
                                                      (False,16,0x1021,0x29b1)])
def test_standard_fcs_single_errors_and_order(reflected, width, poly, known):
    cfg = cases.Config(width, 2, poly, (1 << width)-1,
                       (1 << width)-1 if reflected else 0, reflected)
    bits = cases.wire_bits(b'123456789', reflected)
    assert cases.model_crc(bits, cfg) == known
    packet = bits + cases.fcs_bits(known, cfg)
    assert cases.frame(packet, cfg, 32)['error'] == 0
    for j in range(len(packet)):
        bad = packet.copy(); bad[j] ^= 1
        assert cases.frame(bad, cfg, 32)['error'] == 1
    assert cases.frame(bits + cases.fcs_bits(known, cfg)[::-1], cfg, 32)['error'] == 1
    fcs_bytes = known.to_bytes(width//8, 'little' if reflected else 'big')
    wrong_bytes = cases.wire_bits(b'123456789' + fcs_bytes[::-1], reflected)
    assert cases.frame(wrong_bytes, cfg, 32)['error'] == 1
    assert cases.frame(packet[:width-1], cfg, 8)['error'] == 1
    empty = cases.fcs_bits(cases.model_crc([], cfg), cfg)
    assert cases.frame(empty, cfg, 1)['error'] == 0


def test_empty_and_partial_append():
    cfg = cases.Config(16, 1, 0x1021, 0xffff, 0)
    empty = cases.frame([], cfg, 32)
    assert empty['outputs'] == [(0xffff, 16, 1, 0xffff, 1)]
    partial = cases.frame([1, 0, 1], cfg, 8)
    assert partial['outputs'][0] == (5, 3, 0, 0, 0)
    assert sum(row[1] for row in partial['outputs']) == 19
    # Independent oracle must expose a changed polynomial.
    assert cases.divide_crc([1,0,1], cfg) != cases.divide_crc([1,0,1], replace(cfg, poly=0x1020))


def test_runner_strict_positive_and_negative_gates():
    report = dict(frames=3, inputs=8, outputs=5)
    marker = 'PASS CRC frames=3 inputs=8 outputs=5 collisions=3 pending=2 istall=1 ostall=2 rate=0 latency=0'
    assert runner.check_run(0, marker, report)['outputs'] == 5
    for rc, text in [(1, marker), (0, marker.replace('outputs=5','outputs=4')), (0, 'nothing'),
                     (0, marker+'\n%Error: fault')]:
        with pytest.raises(RuntimeError):
            runner.check_run(rc, text, report)
    for tag in ('[NUMERIC]', '[PROTOCOL]'):
        assert runner.check_run(13, tag+' fault', report, tag)['returncode'] == 13
        for rc, text in [(0, tag), (1, tag), (-6, tag), (13, '[TIMEOUT]'), (13, tag+marker),
                         (13, tag+' [CONTROL_MISSING]')]:
            with pytest.raises(RuntimeError):
                runner.check_run(rc, text, report, tag)


def test_output_directory_refusal_without_tools(tmp_path):
    existing = tmp_path / 'exists'; existing.mkdir()
    with patch.object(runner, 'execute', side_effect=AssertionError('must not execute')):
        with pytest.raises(FileExistsError):
            runner.main(['--suite','lint','--output-dir',str(existing)])


def test_failed_command_publishes_fail_json(tmp_path):
    output = tmp_path / 'failed'
    with patch.object(runner, 'checked_command', side_effect=RuntimeError('intentional failure')):
        with pytest.raises(RuntimeError, match='intentional failure'):
            runner.main(['--suite','lint','--output-dir',str(output)])
    result = json.loads((output / 'results.json').read_text())
    assert result['status'] == 'FAIL' and 'completed_at_utc' not in result


def test_cli_and_optimization_rejection(tmp_path):
    help_run = subprocess.run([sys.executable, ROOT/'tools/run_crc.py', '--help'], capture_output=True, text=True)
    assert help_run.returncode == 0 and '--simulator' in help_run.stdout
    output = tmp_path / 'optimized'
    result = subprocess.run([sys.executable, '-O', ROOT/'tools/run_crc.py', '--suite','python',
                             '--output-dir',output], capture_output=True, text=True)
    assert result.returncode != 0 and 'optimization' in result.stderr
    assert not output.exists()


def test_questa_command_and_negative_scripts_without_simulator(tmp_path):
    report = dict(frames=3, inputs=8, outputs=5)
    marker = 'PASS CRC frames=3 inputs=8 outputs=5 collisions=3 pending=2 istall=1 ostall=2 rate=0 latency=0'
    commands = []
    workdirs = {}

    def compile_mock(command, cwd, log, timeout=180):
        commands.append(list(map(str, command)))
        log.write_text('mock compile\n')
        return ''

    def simulate_mock(command, cwd, log, timeout=180):
        commands.append(list(map(str, command)))
        workdirs[len(commands)-1] = Path(cwd)
        negative = ('[NUMERIC]' if '+INJECT_MISMATCH' in command else
                    '[PROTOCOL]' if '+INJECT_PROTOCOL' in command else None)
        text = negative or marker
        log.write_text(text)
        return (13 if negative else 0), text

    artifacts = []
    with patch.object(runner, 'MATRIX', [(16,8)]), \
         patch.object(runner, 'questa_paths', return_value=(Path('/mock/questa'), None)), \
         patch.object(runner, 'checked_command', side_effect=compile_mock), \
         patch.object(runner, 'execute', side_effect=simulate_mock):
        records = runner.run_hdl(tmp_path, artifacts, 'questa', {(16,8): report})
    assert len(records) == 2
    simulations = [(i, cmd) for i, cmd in enumerate(commands) if cmd[0].endswith('/vsim')]
    assert len(simulations) == 8
    for i, command in simulations:
        # Скрипт передаётся относительно рабочего каталога (Questa не терпит кириллицу в путях).
        script = workdirs[i]/command[command.index('-do')+1]
        text = script.read_text()
        negative = any(flag.startswith('+INJECT_') for flag in command)
        assert ('onbreak {quit -code 13}' in text) == negative
        assert script.name == ('negative.do' if negative else 'run.do')
    assert all(path.exists() for path in artifacts)
