#!/usr/bin/env python3
"""Сохранение проверяемого отчёта из фактических результатов регрессии."""
from pathlib import Path
from datetime import datetime, timezone
import hashlib
import json
import re
from regression_evidence import require_pass, write_json

ROOT=Path(__file__).resolve().parents[1]


def main():
    catalog=json.loads((ROOT/'modems/catalog.json').read_text())
    python=json.loads((ROOT/'build/python_results.json').read_text())
    cross=json.loads((ROOT/'build/cross_results.json').read_text())
    hdl=json.loads((ROOT/'build/questa/results.json').read_text())
    expected={c['name'] for c in catalog}
    for evidence in [python,cross,*hdl]: require_pass(evidence,ROOT)
    if (python['status']!='PASS' or cross['status']!='PASS' or {r['modem'] for r in hdl}!=expected
            or python['modems']!=len(catalog) or cross['modems']!=len(catalog)
            or any(r['status']!='PASS' for r in hdl)):
        raise RuntimeError('Complete passing regression results are required')
    text=(ROOT/cross['octave_log']).read_text()
    matches=re.findall(r'PASS (\S+) cross-language TX ([\deE.+-]+) RX ([\deE.+-]+)',text)
    if {m[0] for m in matches}!=expected: raise RuntimeError('Incomplete cross-language log')
    max_tx=max(float(m[1]) for m in matches); max_rx=max(float(m[2]) for m in matches)
    max_sv=max(r['maximum_error'] for r in hdl)
    snapshot=dict(recorded_utc=datetime.now(timezone.utc).isoformat(),python=python,cross=cross,hdl=hdl,
                  octave_max_tx_error=max_tx,octave_max_rx_error=max_rx,source_hashes={})
    snapshot['source_hashes']=python['source_hashes']
    write_json(ROOT/'docs/verification_results.json',snapshot)
    lines=['# Modem catalog','',
           'Each row is a separate workspace with preserved original source, a portable configuration and Octave, Python and SystemVerilog entry points. Related historical variants can share a portable algorithm; see the porting contract for differences.','',
           '| Workspace | Modulation | Alphabet | Equalizer |','| --- | --- | --- | --- |']
    for row in catalog:
        cfg=json.loads((ROOT/row['config']).read_text())
        lines.append(f'| [{row["name"]}](../modems/{row["name"]}/README.md) | {row["family"].upper()} | {row["order"]} | {cfg["equalizer"]} |')
    lines+=['','The separate [typed model catalog](TYPED_MODELS.md) includes OFDM and FSK modem workspaces plus synchronization, filtering, coding, MIMO, audio and array-processing algorithms. Their regression uses `tools/run_research.py`.','','## Auxiliary archives','',
            '`DPD_Example`, `adaptdemos`, `ams_r2006a_2007a`, `polar_code`, `graphic_equalizer_16_band_2011_05_17` and `milewski_sequence_2011_05_19` are extracted under `sources`. They are supporting DSP, coding, analog or demonstration material, not additional modem workspaces. Their full conversion and testing is outside this modem implementation scope. `Modems` and `petrov_modems_electronix` are archive collections with duplicate modem archives.','',
            'Standalone CIC, decimator and stereo scripts remain in `arxiv`. Reference books remain in `matlab`. [The inventory](archive_inventory.json) records every unique archive, nested origin, duplicate alias and extracted file hash.']
    (ROOT/'docs/MODEM_CATALOG.md').write_text('\n'.join(lines)+'\n')
    report=f'''# Modem verification results

All {len(catalog)} portable frame-modem configurations passed the Python, Octave and Questa UVM regressions. These results validate the portable contract and cross-language agreement. They do not establish equivalence to the original Simulink simulations.

The [historical visual report](visual/index.html) covers the original 20 workspaces. The [typed visual report](typed_visual/index.html) covers the new modems and separate DSP algorithms. Both provide PDF and PNG/SVG figures. Original MATLAB execution and partial numerical comparisons are recorded separately from portable agreement.

## Recorded results

| Check | Result |
| --- | --- |
| Python unit and per modem tests | {python['python_tests']} passed |
| Octave standalone modem tests | {len(catalog)} passed |
| Python and Octave shared channel cases | {3*len(catalog)} passed |
| Questa UVM modem runs | {len(hdl)} passed |
| UVM frame transactions | {sum(r['frames'] for r in hdl)} passed |
| UVM complex sample comparisons | {sum(r['samples'] for r in hdl)} passed |
| Maximum Python and Octave TX difference | {max_tx:.12g} |
| Maximum Python and Octave RX difference | {max_rx:.12g} |
| Maximum Python and SystemVerilog difference | {max_sv:.12g} |
| Absolute complex sample tolerance | 1e-7 |

The three shared cases are clean transmission, an impaired channel, and a variant specific impaired channel. The fourth UVM transaction checks repeatability after clearing interface outputs. Each modem also runs with an intentionally corrupted expectation and must report a numeric UVM fatal. This block model has no persistent filter or loop state between transactions; the reset test does not establish streaming-state reset correctness. SIMO vectors include two independently perturbed branches with known complex gains; combining executes inside both the Octave and SystemVerilog receiver paths. Python also verifies diversity improvement and rejects invalid gains and variances.

Python tests exercise all adjacent input label pairs, noiseless waveform loopback, gain and carrier offsets, fractional delay, reset repeatability, invalid input and intentionally poor SNR. Equalizer tests check that disabling equalization causes errors on the same echo channel. Timing tests use positive and negative 6e-4 clock drift; phase-noise tests use 0.005 radian increments. Each specialized test requires zero payload errors with tracking and errors with that same loop disabled. Primitive tests use analytic RRC, cubic interpolation, MSK phase and known BPSK and pi/4 differential vectors.

## Reproduction and evidence

```bash
python3 tools/run_tests.py --suite python
python3 tools/run_tests.py --suite cross
./tools/run_questa.sh --all
python3 tools/report_results.py
```

Raw logs are in `{cross['octave_log']}` and `build/questa/<modem>.log`; generated input and golden vectors are in `build/vectors/<modem>/`. The durable [JSON snapshot](verification_results.json) includes per modem UVM results, start/completion times, hashes recorded before execution, and log/vector hashes. Runners reject source changes during execution; report generation rejects stale or missing evidence. Single-modem runs use separate `build/single/<name>` and `build/questa/single/<name>` directories. The [archive inventory](archive_inventory.json) preserves source provenance.

Validated tools: Octave 8.4.0, NumPy 2.4.4 and Questa 2024.1 in 64 bit mode with UVM 1.2. This portable regression does not run MATLAB; original-model execution is documented in the separate reference report. Octave prints `ignoring const execution_exception` while exiting in this environment despite a zero exit code; test assertions and the process exit code determine success. Questa emits installation and license deprecation warnings, but all recorded regressions have zero simulator errors and zero UVM errors or fatals.

The SystemVerilog model is behavioral and has not been synthesized. Blind acquisition equivalence, historical transient response, fixed point precision and FPGA timing remain unverified. See [the porting contract](PORTING_CONTRACT.md) for all substitutions.
'''
    (ROOT/'docs/VERIFICATION.md').write_text(report)
    print(f'Recorded {len(hdl)} UVM runs and {python["python_tests"]} Python tests')


if __name__=='__main__': main()
