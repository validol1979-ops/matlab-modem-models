#!/usr/bin/env python3
"""Сравниваем MSK с реальными отсчётами Simulink и готовим их для UVM."""
from pathlib import Path
import json
import subprocess
import sys

import numpy as np
from scipy.io import loadmat

from generate_vectors import ROOT, complex_lines
from regression_evidence import begin, finish, write_json, require_pass

sys.path.insert(0, str(ROOT / 'common' / 'python'))
from modem_core import channel, receive, transmit

NAME = 'msk_modulator_2008_06_22'


def main():
    from regression_evidence import require_unoptimized
    require_unoptimized()
    native=json.loads((ROOT/'build/matlab_originals/compatible/evidence.json').read_text())
    require_pass(native, ROOT)
    evidence=begin()
    dest=ROOT/'build/matlab_msk_reference'
    dest.mkdir(exist_ok=True)
    write_json(dest/'reference.json',dict(evidence,status='RUNNING'))
    source = ROOT / 'build' / 'matlab_originals' / 'compatible' / NAME / 'signals.mat'
    traces = loadmat(source, simplify_cells=True)['traces']
    signals = {s['block'].split('/', 1)[1]: s for s in traces}
    bits = np.asarray(signals['Scrambler1']['data'], dtype=int).ravel()
    original = np.asarray(signals['Math Function1']['data']).ravel()
    # В исходнике CIC задерживает данные на символ, интегратор — ещё на такт.
    sps, latency = 32, 33
    assert np.max(abs(original[:latency] - 1)) < 1e-12
    count = (len(original) - latency) // sps
    bits = bits[:count]
    reference = original[latency:latency + count * sps]
    cfg = json.loads((ROOT / 'modems' / NAME / 'config.json').read_text())
    cfg['sps'] = sps
    computed = transmit(cfg, bits)['waveform']
    error = float(np.max(abs(computed - reference)))
    assert error < 1e-9, error
    # Контроль чувствительности: неверная задержка должна приводить к отказу.
    shifted_error = float(np.max(abs(computed - original[latency-1:latency-1+len(computed)])))
    assert shifted_error > 1e-3
    dest = ROOT / 'build' / 'matlab_msk_reference'
    dest.mkdir(exist_ok=True)
    (dest / 'config.json').write_text(json.dumps(cfg, indent=2) + '\n')
    np.savetxt(dest / 'data.txt', bits, fmt='%d')
    (dest / 'matlab_tx.txt').write_text(complex_lines(reference))
    from generate_vectors import config_text
    (dest / 'config.txt').write_text(config_text(cfg))
    # Golden TX взят из Simulink; эталон RX здесь по-прежнему вычисляет Python.
    for index, case in enumerate([{}, dict(snr_db=28, gain=.65, phase=.38),
                                  dict(snr_db=32, gain=1.3, phase=-.9, frequency=-.0003, delay=7.25)]):
        wave = channel(cfg, reference, seed=29 + index, **case)
        rx = receive(cfg, wave, bits[:192], len(bits))
        assert np.array_equal(rx['data'][192:], bits[192:]), index
        text = f'{len(bits)} {len(wave)} {len(reference)} 192 1\n'
        text += ''.join(f'{b}\n' for b in bits)
        text += complex_lines(wave) + complex_lines(reference)
        text += ''.join(f'{b}\n' for b in rx['data'])
        text += complex_lines(rx['symbols']) + f'{rx["delay"]:.17g} {rx["frequency"]:.17g}\n'
        (dest / f'case_{index}.txt').write_text(text)
    quote = lambda p: str(p).replace("'", "''")
    script = f"""addpath('{quote(ROOT / 'common' / 'octave')}');
cfg = jsondecode(fileread('{quote(dest / 'config.json')}'));
data = load('{quote(dest / 'data.txt')}');
expected = load('{quote(dest / 'matlab_tx.txt')}');
tx = modem_core('transmit', cfg, data);
actual = tx.waveform(:);
reference = expected(:,1) + 1i * expected(:,2);
maximum_error = max(abs(actual-reference));
assert(maximum_error < 1e-9, 'MATLAB and Octave MSK waveform mismatch');
fprintf('PASS MATLAB and Octave MSK: %d samples, maximum error %.17g\\n', numel(actual), maximum_error);
fid = fopen('{quote(dest / 'octave_error.txt')}', 'w');
fprintf(fid, '%.17g\\n', maximum_error); fclose(fid);
"""
    (dest / 'check_octave.m').write_text(script)
    run = subprocess.run(['octave-cli', '--quiet', str(dest / 'check_octave.m')], capture_output=True, text=True)
    (dest / 'octave.log').write_text(run.stdout + run.stderr)
    print(run.stdout, end='')
    if run.returncode:
        raise RuntimeError(run.stderr)
    result = dict(modem=NAME, status='PASS', source=str(source.relative_to(ROOT)),
                  symbols=len(bits), samples=len(reference), samples_per_symbol=sps,
                  original_latency_samples=latency, python_maximum_error=error,
                  octave_maximum_error=float((dest / 'octave_error.txt').read_text()),
                  wrong_latency_maximum_error=shifted_error,
                  scope='MSK transmitter after the original scrambler; receiver golden outputs come from Python.')
    result.update(finish(evidence,[source,*sorted(dest.glob('*.txt')),dest/'octave.log']))
    write_json(dest/'reference.json', result)
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
