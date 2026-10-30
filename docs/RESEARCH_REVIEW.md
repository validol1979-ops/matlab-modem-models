# Research collection review — 2026-09-30

This document records the initial intake review. The additions were subsequently organized into 17 typed workspaces with portable implementations and visual tests; see [the current model guide](TYPED_MODELS.md) and [typed atlas](typed_visual/index.html). The counts and integration status below describe the intake stage.

The new downloads contain two additional Simulink modem models and 293 MATLAB files (292 `.m`, one `.mlx`). Both Simulink models now pass bounded MATLAB R2020b simulation and exact restart-repeatability checks. The other downloaded algorithms received an integrity and static review only.

There are still **20 portable modem workspaces** with Octave, Python and SystemVerilog tests. The two new research models are not yet portable workspaces and are not included in the existing 20-modem visual atlas or regression totals. Successful MATLAB simulation does not establish receiver correctness, BER performance or cross-language equivalence.

## Download integrity

| Collection | Files checked against manifest size and SHA-256 | ZIP archives with valid CRC | New MATLAB files | New Simulink models |
| --- | ---: | ---: | ---: | ---: |
| [ELECTRONIX](../research/electronix_20260930/findings.json) | 121 | 3 | 35 | 2 |
| [Global DSP collection](../research/dsp_global_20260930/manifest.json) | 314 | 8 | 258 | 0 |
| Total | 435 | 11 | 293 | 2 |

Every recorded file matched its manifest. None of those 435 file hashes matched an existing file under `arxiv/` or `sources/`. This checks byte duplication, not algorithmic novelty. Integrity checks were repeated after simulation; the downloaded sources remain unchanged. The collection metadata records source URLs and, where available, repository commits. Network availability and upstream revisions were not rechecked in this review.

## Two new modem models

| Model | Relevant addition | Compiled base step | Stop time | Captured signals | Captured values | Result |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| oqpsk_2_sps_timing_recovery_2019_12_05 (не входит в публичную копию) | OQPSK with joint carrier/timing recovery, 2 samples per symbol at the recovery input | 0.25 | 4096 | 33 | 426029 | PASS |
| qpsk_8_sps_fb_sync_2020_11_25 (не входит в публичную копию) | QPSK with feedback synchronization, 8 samples per symbol | 0.125 | 2048 | 32 | 563238 | PASS |

Both originals declare R2016b/model format 8.8 and compile directly in the installed R2020b with Communications Toolbox and DSP System Toolbox. No library-reference substitution or algorithm edit was necessary. The original solver is `FixedStepDiscrete`; both archived stop times are infinite.

The checker changes logging, display settings and stop time in memory, then closes each model without saving. Each run spans 16384 compiled base intervals. These intervals are not necessarily the receiver's symbol or sample intervals. Every connected top-level output is logged, all captured samples must be finite, and the requested final time must be reached. A second simulation starts with the same RNG seed; timestamps and values must agree exactly. The two models produced 65 captured signals and 989267 values in total.

Raw arrays and per-model results are under `build/research_review/<model>/`. The [durable result snapshot](research_review_results.json) records source, checker, capture and log hashes. These checks do not compare transmitted and decoded payload labels, measure acquisition robustness, or validate every internal block.

The terminal-backed headless run completed with process exit code 0. Two earlier launches without a terminal completed numerical checks but returned code 129; the first also reported CEF diagnostic-window launch errors. Use `-nodisplay` and a terminal for this host's launcher. The successful log retains warnings about obsolete `randseed`, unconnected outputs and graphical scopes unavailable without a display.

## MATLAB collection triage

| Source directory | MATLAB files | Contents and practical status |
| --- | ---: | --- |
| `electronix_20260930/support/ofdm` | 1 | OFDM/AWGN with BPSK, QPSK, 16QAM and 64QAM branches; incomplete dependencies |
| `electronix_20260930/support/harger` | 34 | Teaching examples for filters and spectral analysis; also contains Mathcad material |
| `dsp_global_20260930/sources/timing` | 12 | Symbol timing loop with five timing error detectors and four interpolation options; MATLAB System Object dependencies |
| `dsp_global_20260930/sources/channelizer` | 4 | PFB and WOLA channelizers; demos need the adjacent `wsinc` package |
| `dsp_global_20260930/sources/wsinc` | 6 | Windowed-sinc FIR design and filter comparison helpers |
| `dsp_global_20260930/sources/china_qpsk` | 4 | Basic passband QPSK and Costas-loop scripts, plus two fixed-point filter constructors |
| `dsp_global_20260930/sources/china_adaptive` | 6 | LMS, NLMS, RLS and noise/echo cancellation examples |
| `dsp_global_20260930/sources/china_ldpc` | 9 | LDPC (2016,1008), four decoding algorithms and BER/FER simulations; parity-check matrix included |
| `dsp_global_20260930/sources/iran_tehran` | 6 | FFT, frequency-coded text and amplitude-coded communication exercises |
| `dsp_global_20260930/sources/iran_oset` | 13 | Selected generic adaptive, Kalman and spectral filtering functions |
| `dsp_global_20260930/sources/india_dsplog` | 4 | MIMO ZF, MMSE-SIC, Alamouti and BPSK/ISI equalization examples |
| `dsp_global_20260930/sources/israel_stft` | 5 | STFT/ISTFT and supporting functions |
| `dsp_global_20260930/sources/israel_omlsa` | 1 | OM-LSA/IMCRA audio noise suppression |
| `dsp_global_20260930/sources/israel_beamforming` | 188 | Book figures and helper functions for array processing; these are not 188 modem implementations |

## Concrete integration issues

- **Incomplete OFDM source.** `tx_make_int_num_ofdm_syms`, `tx_modulate`, `tx_add_pilot`, `tx_freq_to_time`, `rx_time_to_freq` and `rx_demodulate` are called but their `.m` definitions were not found anywhere under `research/`, `arxiv/` or `sources/`.
- **MATLAB-specific QPSK filters.** `rcosfilter.m` and `demo_lowpass.m` construct `dfilt.dffir` objects with `Arithmetic='fixed'`; the former also calls `firrcos`. An Octave port must explicitly preserve coefficient quantization, arithmetic behavior and filter delay. The Costas script processes whole 24000-sample vectors inside every sample iteration and writes `dataI.txt`/`dataQ.txt` in the working directory. It needs a bounded test wrapper and stateful filtering before scaling up.
- **FPGA QPSK download scope.** Only the MATLAB directory and author README were downloaded. The described Verilog design is not present locally, and the MATLAB scripts do not establish RTL equivalence. A fresh portable/UVM implementation would need its own reference contract.
- **Timing-loop dependency boundary.** `timing/main.m` uses `comm.RaisedCosineTransmitFilter`, `comm.RaisedCosineReceiveFilter`, `dsp.Delay`, `comm.SymbolSynchronizer`, `comm.MER` and modulation/noise functions. The explicit loop in `symbolTimingSync.m` is useful source material for studying historical blind timing recovery, but the demo is not a standalone Octave test.
- **Path collisions.** Harger's directory includes its own `freqz.m`, `freqs.m` and `zplane.m`. Do not add the entire research tree recursively to the modem regression path; use one collection's dependencies at a time.
- **Unavailable candidates.** The ELECTRONIX findings list 22 new unavailable attachment candidates. These are links and metadata, not downloaded models or passing tests.

## Recommended integration order

1. Add the two Simulink modems as separate workspaces, with preserved originals, parameter extraction and explicit TX/RX checkpoints. OQPSK requires an explicit staggered I/Q waveform contract before any portable implementation is accepted.
2. Turn the timing-loop and QPSK scripts into callable, seeded tests with explicit signal inputs/outputs, acquisition checks and error-count assertions. Establish MATLAB references before converting each algorithm to Octave/Python/SystemVerilog.
3. Add channelizers, equalizers, MIMO and LDPC as separately named DSP/coding suites, with algorithm-appropriate assertions and plots. Keep audio and book examples in the supporting research catalog.
4. Complete the OFDM dependencies before treating that script as executable evidence.

## Reproduction

From the project root:

```bash
python3 tools/audit_research.py
tools/matlab.sh -nodisplay -batch "addpath('tools'); matlab_check_research;" -logfile build/research_review/matlab_headless.log
python3 tools/audit_research.py
```

The MATLAB command should run in a terminal (with `tty=true` when invoked through the agent execution tool). Integrity results are written to `build/research_review/integrity.json`; MATLAB results are written to `build/research_review/matlab_results.json`. The existing portable regression and visual atlas were not regenerated for this review.
