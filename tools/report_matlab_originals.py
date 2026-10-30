#!/usr/bin/env python3
"""Фиксируем результаты запусков и отделяем частные совпадения от полной эквивалентности."""
from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json

from regression_evidence import require_pass, write_json

import numpy as np
from scipy.io import loadmat

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / 'build' / 'matlab_originals'


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mapper_checks(result, traces, configuration):
    table = np.asarray(configuration['constellation'])
    table = table[:, 0] + 1j * table[:, 1]
    by_name = {trace['name']: trace for trace in traces}
    checks = []
    for mapper in result['mapper_ports']:
        input_trace, output_trace = by_name[mapper['input']], by_name[mapper['output']]
        values = np.asarray(input_trace['data']).ravel()
        labels = values.astype(int)
        actual = np.asarray(output_trace['data']).ravel()
        assert np.array_equal(values, labels)
        assert np.array_equal(input_trace['time'], output_trace['time'])
        assert np.all((labels >= 0) & (labels < len(table)))
        expected = table[labels]
        if mapper['block'].endswith(' RE'):
            expected = expected.real
        if mapper['block'].endswith(' IM'):
            expected = expected.imag
        error = float(np.max(abs(expected - actual)))
        coverage = len(np.unique(labels))
        checks.append(dict(block=mapper['block'], samples=len(labels), maximum_error=error,
                           covered_labels=coverage, alphabet=len(table),
                           status='PASS' if error <= 1e-12 and coverage == len(table) else 'FAIL'))
    return checks


def qpsk_diagnostic(traces):
    signals = {trace['block'].split('/', 1)[1]: trace for trace in traces}
    tx = np.asarray(signals['From4']['data']).ravel().astype(int)
    rx = np.asarray(signals['From5']['data']).ravel().astype(int)
    rate_trace = next(value for key, value in signals.items() if 'Error Rate' in key)
    rate, errors, compared = np.asarray(rate_trace['data'])[-1]
    # Задержка 13 взята из исходного Error Rate Calculation, а не подогнана к данным.
    delay = 13
    tx, rx = tx[:-delay], rx[delay:]
    middle = len(tx) // 2
    # Фазовую гипотезу выбираем до середины записи, проверяем на независимом хвосте.
    offsets = (rx[middle//2:middle] - tx[middle//2:middle]) % 4
    offset = int(np.bincount(offsets, minlength=4).argmax())
    tail_errors = int(np.count_nonzero(rx[middle:] != (tx[middle:] + offset) % 4))
    return dict(status='QUADRANT_OFFSET', raw_symbol_error_rate=float(rate),
                raw_errors=int(errors), raw_compared_symbols=int(compared), delay_symbols=delay,
                inferred_label_offset_modulo_4=offset, held_out_symbols=len(tx)-middle,
                held_out_errors_after_offset=tail_errors,
                explanation='Raw decoding differs by a constant quadrant; the archived counter is unchanged. '
                            'This diagnostic phase correction is not part of the original receiver.')


def main():
    from regression_evidence import require_unoptimized
    require_unoptimized()
    evidence = {}
    for mode in ('audit','compatible'):
        evidence[mode] = json.loads((BUILD/mode/'evidence.json').read_text())
        require_pass(evidence[mode], ROOT)
    audit = {x['name']: x for x in json.loads((BUILD / 'audit' / 'results.json').read_text())}
    results = json.loads((BUILD / 'compatible' / 'results.json').read_text())
    configs = [p for p in sorted((ROOT / 'modems').glob('*/config.json'))
               if not json.loads(p.read_text()).get('research_addition')]
    assert {p.parent.name for p in configs} == {r['name'] for r in results}
    records = []
    for result in results:
        name = result['name']
        workspace = ROOT / 'modems' / name
        cfg = json.loads((workspace / 'config.json').read_text())
        source = next((workspace / 'original').glob('*.mdl'))
        assert digest(source) == cfg['source_sha256']
        migration = json.loads((workspace / 'matlab' / 'migration.json').read_text())
        assert digest(workspace / 'matlab' / source.name) == migration['prepared_sha256']
        assert result['simulation_status'] == 'PASS' and result['repeat_status'] == 'PASS', name
        capture = BUILD / 'compatible' / name / 'signals.mat'
        traces = loadmat(capture, simplify_cells=True)['traces']
        mappers = mapper_checks(result, traces, cfg)
        record = dict(name=name, original_sha256=digest(source),
                      original_load=audit[name]['load_status'],
                      original_compile='PASS' if audit[name]['compile_status'] == 'PASS' else 'FAIL',
                      original_error=audit[name]['error_message'],
                      migration=migration, runtime_changes=result['runtime_changes'],
                      runtime_status=result['simulation_status'], repeat_status=result['repeat_status'],
                      solver=result['solver'], time_quantum=result['step_size'],
                      stop_time=result['stop_time'], requested_steps=result['requested_steps'],
                      signal_count=result['signal_count'], finite=all(s['finite'] for s in result['signals']),
                      captured_values=sum(int(s['values']) for s in result['signals']),
                      capture_sha256=digest(capture), mapper_checks=mappers,
                      receiver_functional_status='NOT_ESTABLISHED', full_equivalence='NOT_ESTABLISHED')
        if name == 'qpsk_demod_with_phase_noise':
            record['receiver_diagnostic'] = qpsk_diagnostic(traces)
        if cfg['family'] in ('msk', 'gmsk'):
            block = 'Math Function1' if cfg['family'] == 'msk' else 'modulator'
            wave = next(s for s in traces if s['block'].split('/', 1)[1] == block)['data']
            error = float(np.max(abs(abs(wave) - 1)))
            record['constant_envelope'] = dict(maximum_error=error, status='PASS' if error < 1e-12 else 'FAIL')
            assert error < 1e-12
        write_json(workspace/'matlab/verification.json',record)
        records.append(record)
    checks = [check for r in records for check in r['mapper_checks']]
    assert all(c['status'] == 'PASS' for c in checks)
    msk = json.loads((ROOT / 'build' / 'matlab_msk_reference' / 'reference.json').read_text())
    uvm = json.loads((ROOT / 'build' / 'questa_matlab_msk' / 'results.json').read_text())
    require_pass(msk, ROOT)
    if len(uvm)!=1: raise RuntimeError('Expected one MSK UVM result')
    require_pass(uvm[0], ROOT)
    source_paths = ['tools/matlab_check_originals.m', 'tools/prepare_matlab_originals.py',
                'tools/check_matlab_msk.py', 'tools/report_matlab_originals.py', 'tools/run_hdl.py',
                'tools/matlab.sh', 'common/python/modem_core.py', 'common/octave/modem_core.m',
                'common/sv/modem_dsp_pkg.sv', 'common/sv/modem_uvm_pkg.sv']
    summary = dict(captured_at_utc=datetime.now(timezone.utc).isoformat(), matlab_version=results[0]['matlab_version'],
                   runtime_passed=len(records), repeat_passed=len(records),
                   original_compile_passed=sum(r['original_compile'] == 'PASS' for r in records),
                   mapper_models=sum(bool(r['mapper_checks']) for r in records), mapper_blocks=len(checks),
                   mapper_samples=sum(c['samples'] for c in checks),
                   mapper_maximum_error=max(c['maximum_error'] for c in checks),
                   captured_signals=sum(r['signal_count'] for r in records),
                   captured_values=sum(r['captured_values'] for r in records),
                   msk_reference=msk, msk_uvm=uvm[0], models=records,
                   full_equivalence='NOT_ESTABLISHED',
                   run_evidence=evidence,
                   evidence_sha256={name: digest(ROOT / name) for name in source_paths})
    write_json(ROOT/'docs/matlab_reference_results.json', summary)
    rows = []
    for r in records:
        label = f"[{r['name']}](../modems/{r['name']}/matlab/verification.json)"
        mapping = f"PASS ({len(r['mapper_checks'])})" if r['mapper_checks'] else 'Not checked'
        rows.append(f"| {label} | {r['original_compile']} | PASS | PASS | {mapping} |")
    qpsk = next(r['receiver_diagnostic'] for r in records if 'receiver_diagnostic' in r)
    report = f"""# MATLAB modem verification

Explore the [interactive signal report](visual/index.html) or the [PDF atlas](visual/modem_test_report.pdf) for original MATLAB captures and reference comparisons. [Plot conventions](VISUAL_TESTS.md) describe what each graph measures.

All 20 archived modem models load in MATLAB R2020b. Five compile without library or dimension changes; all 20 simulate successfully with the documented compatibility adjustments. Every captured signal contains finite values, and repeating each simulation reproduces the recorded timestamps and samples exactly.

This is runtime verification with partial numerical reference comparisons. Full receiver correctness and complete MATLAB/Octave/Python/SystemVerilog equivalence are not established.

## Results

| Check | Result |
| --- | --- |
| Original MDL hashes | 20 unchanged |
| Original models loaded | 20/20 |
| Original models compiled without adaptations | {summary['original_compile_passed']}/20 |
| Adapted models simulated | 20/20 |
| Exact repeatability after a new simulation start | 20/20 |
| Captured signals / numeric values | {summary['captured_signals']} / {summary['captured_values']} |
| Original mapper blocks checked against portable tables | {len(checks)} in {summary['mapper_models']} models |
| Mapper sample comparisons | {summary['mapper_samples']} |
| Maximum mapper difference | {summary['mapper_maximum_error']} |
| MSK and GMSK unit envelope checks | 2/2 |
| MATLAB MSK versus Python and Octave | {msk['samples']} samples; maximum error {msk['python_maximum_error']:.4g} |
| MSK UVM reference test | {uvm[0]['frames']} frames; {uvm[0]['samples']} complex comparisons; maximum error {uvm[0]['maximum_error']:.4g} |

Mapper checks cover every label of each tested alphabet and compare samples at identical timestamps. QAM64 has separate real and imaginary mapper blocks. CPM and pi/4 mapping/state chains are outside this table comparison.

| Model | Original compile | Adapted simulation | Exact repeat | Mapper blocks |
| --- | --- | --- | --- | --- |
{chr(10).join(rows)}

## Compatibility and execution conditions

The copies in `modems/<name>/matlab/` replace missing `commchan2` references with `commchan3` and missing `commdigbbndpm2` references with `commdigbbndpm3`. Original numeric parameters are retained. Every migrated PSK block has `numSamp=1`; the replacement block omits that obsolete parameter. The installed MathWorks helper `commdigbbndpm2ReplaceBlocks.m` documents the same PSK parameter mapping. Each workspace records exact changes and hashes in `matlab/migration.json`.

SIMO additionally needs explicit dimensions on the cubic Farrow subsystem input ports: two antenna channels and one scalar timing value. These settings are applied in memory and recorded in the results. Library replacements are not proof of equivalence to the historical MATLAB release, including its noise generator behavior.

Runs use normal simulation and the original solver, channel parameters, seeds and startup callbacks. Plot windows are disabled. Duration is limited to 16384 minimum discrete time intervals; the QPSK phase-noise example uses 262144 intervals, producing 10923 symbol observations. QAM64 retains its variable-step `ode45` solver. These are bounded tests, not full-duration BER sweeps. Logging observes top-level block outputs and selected mapper inputs/outputs; it does not cover every internal node.

The raw logs retain legacy-block, disconnected-port and headless-display warnings. These do not prevent the recorded simulations. No original MDL file is saved or changed by the checker.

## QPSK phase-noise finding

The original Error Rate Calculation block reports a symbol error rate of {qpsk['raw_symbol_error_rate']:.0%}: {qpsk['raw_errors']} errors in {qpsk['raw_compared_symbols']} comparisons. This is not a clean raw decoding result.

At the original block's delay of {qpsk['delay_symbols']} symbols, received labels have a constant offset of {qpsk['inferred_label_offset_modulo_4']} modulo 4. The phase hypothesis is selected from an earlier interval and tested on the held-out second half: {qpsk['held_out_errors_after_offset']} errors in {qpsk['held_out_symbols']} symbols after that correction. This is consistent with a quadrant/mapping ambiguity. The original transmitter uses phase zero and its demapper uses pi/2. No correction is inserted into the archived receiver or hidden in the raw counter.

## MSK waveform reference

The comparison starts after the original scrambler and uses {msk['symbols']} captured bits. The portable cores run at the original 32 samples per symbol, instead of the portable workspace's default eight. A fixed delay of 33 samples accounts for the original CIC delay of one symbol and the phase integrator delay of one sample. No fitted gain, phase or time resampling is applied. A one-sample wrong delay gives an error of {msk['wrong_latency_maximum_error']:.5g}, confirming that the test detects misalignment.

Python, Octave and SystemVerilog agree with the MATLAB transmitter samples at this interface. UVM reads its expected TX waveform directly from the MATLAB capture; its RX golden outputs still come from Python. This does not verify the archived scrambler or the other historical receivers.

## Reproduce

```bash
python3 tools/prepare_matlab_originals.py
python3 tools/run_matlab_evidence.py --suite audit
python3 tools/run_matlab_evidence.py --suite compatible
python3 tools/check_matlab_msk.py
./tools/run_questa.sh --modem msk_modulator_2008_06_22 --vectors build/matlab_msk_reference --output-dir build/questa_matlab_msk
python3 tools/report_matlab_originals.py
```

For one model, add its name as the second argument to `matlab_check_originals`, or add its `matlab` directory to the MATLAB path and run `test_original`. The third argument controls the number of minimum time intervals. `test_original` checks execution and repeatability, not receiver BER or full equivalence. The report command requires a complete 20-model run and fails on missing results or failed comparisons. Python reference analysis additionally uses SciPy to read MAT files.

Per-model captures and logs are in `build/matlab_originals/compatible/<name>/`. `signals.mat` contains plain timestamps and real/complex arrays readable by SciPy. [The durable JSON snapshot](matlab_reference_results.json) records source/capture hashes, compatibility changes, numerical checks and implementation hashes. Per-model [verification records](../modems/) are retained under each `matlab` folder. The UVM reference log is in `build/questa_matlab_msk/msk_modulator_2008_06_22.log`.

The checker uses the documented [programmatic simulation interface](https://www.mathworks.com/help/simulink/slref/sim.html), including a 180-second timeout for each simulation. A successful installation or simulation does not by itself demonstrate modem equivalence; the remaining algorithm differences are listed in [the porting contract](PORTING_CONTRACT.md).
"""
    (ROOT / 'docs' / 'MATLAB_MODEM_VERIFICATION.md').write_text(report)
    print(f'PASS MATLAB report: {len(records)} runtime checks, {len(checks)} mapper blocks, MSK reference in three languages')


if __name__ == '__main__':
    main()
