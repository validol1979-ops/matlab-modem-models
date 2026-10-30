# Modem verification results

All 24 portable frame-modem configurations passed the Python, Octave and Questa UVM regressions. These results validate the portable contract and cross-language agreement. They do not establish equivalence to the original Simulink simulations.

The [historical visual report](visual/index.html) covers the original 20 workspaces. The [typed visual report](typed_visual/index.html) covers the new modems and separate DSP algorithms. Both provide PDF and PNG/SVG figures. Original MATLAB execution and partial numerical comparisons are recorded separately from portable agreement.

## Recorded results

| Check | Result |
| --- | --- |
| Python unit and per modem tests | 191 passed |
| Octave standalone modem tests | 24 passed |
| Python and Octave shared channel cases | 72 passed |
| Questa UVM modem runs | 24 passed |
| UVM frame transactions | 96 passed |
| UVM complex sample comparisons | 445328 passed |
| Maximum Python and Octave TX difference | 2.85437454388e-14 |
| Maximum Python and Octave RX difference | 2.4930457878e-13 |
| Maximum Python and SystemVerilog difference | 1.78579088794e-13 |
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

Raw logs are in `build/logs/cross/octave.log` and `build/questa/<modem>.log`; generated input and golden vectors are in `build/vectors/<modem>/`. The durable [JSON snapshot](verification_results.json) includes per modem UVM results, start/completion times, hashes recorded before execution, and log/vector hashes. Runners reject source changes during execution; report generation rejects stale or missing evidence. Single-modem runs use separate `build/single/<name>` and `build/questa/single/<name>` directories. The [archive inventory](archive_inventory.json) preserves source provenance.

Validated tools: Octave 8.4.0, NumPy 2.4.4 and Questa 2024.1 in 64 bit mode with UVM 1.2. This portable regression does not run MATLAB; original-model execution is documented in the separate reference report. Octave prints `ignoring const execution_exception` while exiting in this environment despite a zero exit code; test assertions and the process exit code determine success. Questa emits installation and license deprecation warnings, but all recorded regressions have zero simulator errors and zero UVM errors or fatals.

The SystemVerilog model is behavioral and has not been synthesized. Blind acquisition equivalence, historical transient response, fixed point precision and FPGA timing remain unverified. See [the porting contract](PORTING_CONTRACT.md) for all substitutions.
