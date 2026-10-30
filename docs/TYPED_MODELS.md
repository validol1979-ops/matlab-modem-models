# Typed modem and DSP models

## CIC compensation and rational models (2026-10-30)

Model stages `DSP-CIC-COMP` and `DSP-RATIONAL` are complete. Work remains **Python models only**: the overall RTL tasks stay open; no HDL/vendor compilation or physical timing acceptance is claimed. The expansion backlog now has 44 tasks, with four model stages complete and 40 open. [Evidence](filter_models_20261030_results.json) and [durable contracts/progress](../research/filter_models_20261030/progress.json) record source provenance, numerical scope and limitations.

[cic_compensation.py](../common/python/cic_compensation.py) provides `cic_response`, `design`, `quantize`, `metrics` and `cascade_fixed`. Frequencies are **cycles per decimated output sample**; normalized CIC magnitude is `abs(sinc(M*f)/sinc(f/R))**N`, with exact DC limit 1. The symmetric odd FIR is designed by constrained weighted least squares: unit DC is imposed algebraically, each band has 512 samples, and passband residuals receive weight 10. This is our numerical specification motivated by Harris PDF file pages 490–491, rather than a bit-exact copy of its historic coefficients.

Coefficient export is signed 18-bit Q17 with nearest rounding toward positive infinity on ties, symmetric pairs and a centre adjustment making the integer sum exactly 131072. Unrepresentable coefficients are rejected. The fixed cascade reuses the existing CIC decimator with signed18 normalization, then `fir_fixed.filter` with its full FIR tail. A full-scale transient may saturate; these cases are compared exactly and counted separately. A post-decimation FIR cannot remove aliases already folded into its passband.

The frozen quality matrix uses R=4/10/32, N=3/5, M=1 and 31/63 taps, passband 0…0.16 and stopband 0.32…0.5. Both floating and Q17 designs must have passband ripple/max error ≤0.05 dB and FIR stopband ≤−50 dB on 8193 frequency points. Independent SciPy frequency responses and finite boxcar kernels verify the production metrics.

| R | N | Taps | Uncompensated droop, dB | Float ripple, dB | Q17 ripple, dB | Q17 FIR stop, dB |
| --- | --- | --- | --- | --- | --- | --- |
| 4 | 3 | 31 | 1.0377 | 0.0008708 | 0.0009212 | -65.162 |
| 4 | 3 | 63 | 1.0377 | 0.0000001 | 0.0005324 | -86.181 |
| 4 | 5 | 31 | 1.7295 | 0.0009794 | 0.0009953 | -63.888 |
| 4 | 5 | 63 | 1.7295 | 0.0000001 | 0.0005724 | -86.588 |
| 10 | 3 | 31 | 1.0953 | 0.0008793 | 0.0008931 | -64.979 |
| 10 | 3 | 63 | 1.0953 | 0.0000001 | 0.0007589 | -80.767 |
| 10 | 5 | 31 | 1.8256 | 0.0009950 | 0.0012105 | -63.579 |
| 10 | 5 | 63 | 1.8256 | 0.0000001 | 0.0007094 | -88.308 |
| 32 | 3 | 31 | 1.1052 | 0.0008807 | 0.0008963 | -65.577 |
| 32 | 3 | 63 | 1.1052 | 0.0000001 | 0.0005591 | -83.748 |
| 32 | 5 | 31 | 1.8421 | 0.0009978 | 0.0010121 | -63.421 |
| 32 | 5 | 63 | 1.8421 | 0.0000001 | 0.0006444 | -81.967 |

[rational_model.py](../common/python/rational_model.py) provides `RationalFloat`, `RationalFixed`, batch `resample_float`/`resample_fixed` and `accumulator_width`. P and Q are coprime integers in 1…32; taps are supplied by the caller. There is no implicit gain normalization. For unity-gain interpolation, prototype coefficients normally sum to P. Fixed taps are signed18 real integers, with configurable fraction bits; inputs/outputs are signed integer I/Q pairs. Each polyphase dot product uses exact integer accumulation, one rounding shift and final signed saturation. The accumulator-width function derives exact signed extrema for every branch.

The first output is at high-rate index zero: `y[k] = Σ_j h[(kQ)%P+jP] x[floor(kQ/P)-j]`. `push` emits every available output, including cases where Q>P skips several input indices; history holds at most `ceil(len(h)/P)` original samples. After N inputs the causal output count is `ceil(NP/Q)`. `flush(tail=True)` closes the frame at `ceil((NP+len(h)-1)/Q)` outputs, deliberately retaining the final P−1 inserted zeros; `tail=False` closes at the causal count. SciPy `upfirdn` uses minimal support and therefore needs explicit zero-padding/cropping for this convention. An empty frame has no tail. Repeated valid flush is empty; invalid flags are rejected even after close. Reset and between-frame reconfiguration clear state, while bad samples/configuration leave it unchanged.

[filter_references.py](../common/python/filter_references.py) and [test_filter_models.py](../tests/test_filter_models.py) provide independent finite-DTFT, explicit zero-insert/convolution and exact rational-rounding oracles. The focused acceptance passes 19 tests, 12 compensation profiles, 480 rational data/tail cases in both arithmetics (960 numerical comparisons), 38355 exact fixed outputs, and nine caller-supplied low-pass/tone profiles (82913 further fixed outputs). Deliberately bypassed compensation and a corrupted output are rejected. Both raw FIR quality and folded-alias behavior are recorded; physical throughput is not inferred.

```sh
python3 tools/run_filter_models.py --output build/filter_models_trial/results.json
```

The final registered Python set passed **848 tests over 24 modem configurations**. The isolated source copy reproduced the same model matrices without any authoring/provider files.

Use a fresh output path. The same numerical runner works without authoring logs, provider credentials or library files; those are optional provenance. Source links remain in [the library task catalog](../research/library_dsp_20261029/task_catalog.json). Qwen/pi implemented the rational model, Haiku/pi the compensation model, DeepSeek/pi independent tests/references; Haiku/OpenCode supplied a limited state audit. Coordinator corrections and review limitations are preserved with the acceptance artifacts.

## CIC models added on 2026-10-30

The current user instruction is **models only**, using pi and OpenCode agents. No new RTL, HDL simulation or Quartus/Vivado/ISE compilation is part of this stage. Tasks `DSP-CIC-DEC` and `DSP-CIC-INT` in [the library backlog](RTL_TODO.md#82-фильтры-частота-дискретизации-и-спектральные-блоки) retain their later implementation requirements.

The integer API is [cic_model.py](../common/python/cic_model.py): `CICDecimator`, `CICInterpolator`, batch `decimate`/`interpolate`, `cic_gain`, `register_width` and `quantize`. Samples are signed integer `(re, im)` pairs, initially 18 bits. Supported rates are 1…32, stages 1…5 and differential delay 1 or 2. Parameter and sample validation rejects booleans/floats in integer fields, out-of-range components and incomplete decimation frames.

This is a causal accepted-sample model with zero initial state and no convolution-tail flush. Decimation emits at indices `R-1, 2R-1, …`; interpolation emits phases `0…R-1` per input. `push(sample, last=False)` returns a list of `(sample_pair, last_flag)` results. A premature decimator `last` fails before changing state; interpolation marks only its final output phase. Frame boundaries retain numerical state. `reset()` clears it; `configure(rate)` is legal only between frames and clears it even if the rate is unchanged. No cycle latency, backpressure or FPGA throughput is established by this API.

All integrator and comb states wrap at one common signed accumulator width. Default width is sized at `max_rate`, using `input_width + ceil(log2(G))` computed with integer arithmetic. Raw DC gains are `(R*M)^N` for decimation and `(R*M)^N/R` for interpolation. `normalize=True` divides by that exact integer gain, rounds ties toward positive infinity and saturates to the input width. Explicit narrower accumulator widths are permitted for wrap experiments; normalization cannot recover already wrapped data.

The independent [cic_reference.py](../common/python/cic_reference.py) builds the FIR kernel by repeated boxcar convolution, with exact integer and NumPy floating implementations. It does not import the integrator/comb model. [test_cic_models.py](../tests/test_cic_models.py) covers arithmetic, configuration and frame state; [run_cic_models.py](../tools/run_cic_models.py) records the full numerical sweep and deliberate corrupt-output controls under source/artifact hashes:

```sh
python3 tools/run_cic_models.py --output build/cic_models_run/results.json
```

Acceptance: **16 unit tests, 512 direction/rate/stage/delay profiles, 2048 signal cases and 286976 complex output samples** matched both exact FIR and floating convolution; every case also checks normalized output with an independent rational rounding reference. Maximum measured floating difference is zero for these integer-valued profiles. Two deliberately corrupted outputs were rejected. Model evidence is recorded in [cic_models_20261030_results.json](cic_models_20261030_results.json). Qwen through pi implemented the fixed model, Haiku through OpenCode supplied the independent reference and DeepSeek through pi supplied tests; all three use the configured Qulab endpoint. The coordinator corrected agent defects before acceptance.

The final registered Python unit set also passed: **829 tests across 24 modem configurations**. A separate model checkout without agent logs, provider configuration or library originals reproduced all 16 tests and 512 numerical profiles.

Use a fresh output path on each run. The source pipeline has different phase/register scheduling: this mathematical model intentionally follows the explicit contract above and does not claim cycle-exact reproduction of the historical Verilog. Original paths and hashes remain in [task_catalog.json](../research/library_dsp_20261029/task_catalog.json).

## Earlier typed workspaces

The September 30 additions are organized into **17 new workspaces**: six modem workspaces and eleven separate algorithm workspaces. The six modems comprise two Simulink-derived QPSK/OQPSK models, two script-derived QPSK analogues, OFDM and FSK. There are now 26 modem directories: 24 use the frame-modem engine, while OFDM and FSK use the typed block engine.

Open the [interactive atlas](typed_visual/index.html), [55-page PDF](typed_visual/modem_test_report.pdf) or [CSV metrics](typed_visual/metrics.csv). The atlas provides 55 figures in PNG and SVG, organized by model type and scenario. [Source coverage](typed_source_coverage.csv) accounts for every one of the 295 new MATLAB/Simulink files (292 M-files, one live script and two MDL models). The [machine-readable catalog](typed_model_catalog.json) records original copies and hashes.

The units of organization are functional models and source packages, not individual teaching figures. All source files are preserved. Portable analogues cover selected algorithms in each package; they do not reproduce every helper, plot or historical parameter set. Each workspace and atlas view states its substitutions. Source preservation, original execution, portable correctness and numerical agreement are distinct claims.

## Directory layout

| Directory | Model type | Implemented analogue |
| --- | --- | --- |
| `modems/oqpsk_2_sps_timing_recovery_2019_12_05` | OQPSK | Half-symbol quadrature staggering, preamble acquisition, matched filtering and symbol recovery |
| `modems/qpsk_8_sps_fb_sync_2020_11_25` | QPSK | Portable QPSK frame receiver |
| `modems/qpsk_script_basic` | QPSK script | Complex-baseband frame analogue of the passband example |
| `modems/qpsk_script_costas` | QPSK script | Frame analogue; an explicit Costas-loop test is also under synchronization |
| `modems/ofdm_awgn` | OFDM | Complete block TX/RX with cyclic prefix, BPSK/QPSK/16QAM/64QAM tests |
| `modems/fsk_text` | FSK | Orthogonal four-FSK transmitter and correlation receiver |
| `algorithms/synchronization/symbol_timing` | Synchronization | Gardner timing loop and QPSK Costas loop |
| `algorithms/channelizers/pfb_wola` | Channelizers | FIR/DFT analysis bank with critical and oversampled decimation |
| `algorithms/filters/windowed_sinc` | FIR filters | Hamming-window low-pass design and complex convolution |
| `algorithms/filters/oset` | Interference/noise filters | Notch filter and scalar Kalman estimator |
| `algorithms/adaptive/lms_nlms_rls` | Adaptive filters | Complex LMS, NLMS and RLS |
| `algorithms/coding/ldpc` | Channel coding | Systematic GF(2) encoding, SP/MS/NMS/OMS decoding |
| `algorithms/mimo/dsplog` | MIMO/diversity | ZF/MMSE spatial detection and Alamouti combining |
| `algorithms/audio/stft` | Time-frequency analysis | STFT and normalized overlap-add reconstruction |
| `algorithms/audio/omlsa` | Noise suppression | Decision-directed OM-LSA gain with calibrated noise |
| `algorithms/arrays/beamforming` | Array processing | Complex delay-and-sum steering and spatial-null test |
| `algorithms/teaching/harger` | Teaching examples | DFT/inverse DFT and FIR impulse checks |

Every new workspace provides original files, Python and Octave/MATLAB entry points, a SystemVerilog model wrapper, a UVM launcher and tests. Shared numerical implementations are in `common/python/research_core.py`, `common/octave/research_core.m` and `common/sv/research_dsp_pkg.sv`. The four QPSK/OQPSK frame workspaces use the existing modem cores, extended with an explicit OQPSK path.

## Verification and limits

The frame-modem regression snapshot of 2026-10-01 records 191 Python tests, 24 Octave modem checks and 72 shared channel cases. The 24 Questa UVM runs check 96 frame transactions. The typed algorithm suite passes 40 analytic/seeded scenarios in Python, Octave and MATLAB and 80 UVM transactions, including a full second sequence after reset. A separately injected wrong expectation produces a numeric UVM fatal, proving that the scoreboard detects a disagreement.

The [durable verification snapshot](typed_verification_results.json) includes the completed combined regression, original-reference comparisons, browser results, preserved-source hashes and evidence-file hashes. Frame UVM compares 445328 complex values; typed UVM compares 32084. The largest typed difference is about 4.09e-12 for MATLAB/Octave and 2.51e-13 for SystemVerilog.

The typed UVM environment has an actual sequence, sequencer, driver, passive monitor and scoreboard. The driver sends operation, parameters, signal and auxiliary data; expected outputs are never passed to the DUT. It checks transaction metadata, output length, every complex value, response timing, transaction gaps, reset clearing and repetition. The tolerance is `1e-8 * (1 + abs(expected))`. SystemVerilog uses real arithmetic and block transactions; synthesis, fixed-point rounding and FPGA timing are not established.

Independent acceptance checks include analytic impulse and tone responses, SciPy FIR/filter references, direct mixer/filter-bank equations, adaptive coefficient recovery and error reduction, a zero LDPC syndrome and corrected bit, full STFT reconstruction, noise-MSE reduction, spatial interference rejection, recovered MIMO symbols and OFDM/FSK labels. Severe-noise OFDM controls must produce errors. Each LDPC decoder uses the same decoded-word/syndrome checker for acceptance and for rejecting a flipped output bit or a bypassed decoder; the encoder is not assigned a decoder-control result. The OM-LSA test also bounds edge amplitude; reflected padding prevents edge-window division from amplifying reconstruction errors.

Original reference checks separately execute the downloaded LMS/NLMS/RLS functions and PFB/WOLA functions in MATLAB, then compare their outputs with Python. Adaptive coefficient order is mapped explicitly; the original RLS covariance is matched by the portable initialization parameter. Channelizer comparisons reverse frequency-bin order and use the original output count. The original (2016,1008) encoder has zero syndrome; all four original decoders and all four Python decoders recover a nonzero random word with one weakly inverted LLR. Portable UVM uses a short code, so full-size LDPC HDL equivalence is not claimed. Four new frame-modem portable functions also pass in MATLAB.

The two new MDL originals have separate bounded simulation, finite-value and exact-repeatability evidence from [the initial review](RESEARCH_REVIEW.md). The script-derived QPSK frame analogues do not reproduce original fixed-point passband filtering. The missing OFDM helpers are replaced by a documented independent block contract; original pilot placement is not inferred. The OM-LSA analogue calibrates noise from a noise-only prefix and does not implement the historical IMCRA tracker. The 188 array-processing book files and Harger exercises are preserved and grouped; their individual figures have not all been ported or executed.

## Numeric transaction contract

The shared input contract rejects nonfinite values before computation. Beamforming and Alamouti require channel energy between 1e-24 and 1e300. MIMO validates finite normal equations and rejects elimination pivots below 1e-12, including singular unregularized matrices; regularization can make them admissible. OFDM receive block length must fit a signed 32-bit integer. Carrier fitting requires each reference magnitude and recovered gain magnitude to be at least 1e-12.

All indices below are zero-based. Frequencies are cycles per input sample unless stated otherwise. Complex arrays are flattened in row-major order. Python exposes `run(operation, parameters, signal, auxiliary)`; the M-file equivalent is `research_core` or the workspace's `run_model`. SystemVerilog uses the operation index in the following table and the same arrays. The actual case files supply all parameters and record the expected output length.

| ID / operation | Parameters | Signal and auxiliary arrays | Output |
| --- | --- | --- | --- |
| 0 `fir` | none | signal; FIR coefficients | Full convolution, length N+L-1 |
| 1 `dft` | inverse flag | signal; unused | Unnormalized forward DFT or 1/N inverse DFT |
| 2 `pfb`, 20 `wola` | channels M, decimation D | signal; prototype FIR taps | Channel blocks at input indices 0,D,2D…; M values per block |
| 3 `lms`, 4 `nlms`, 5 `rls` | taps, step/forgetting factor, epsilon/initial inverse covariance | input; desired output | N estimates, N errors, final complex weights; prediction is wᴴu |
| 6 `ldpc` | checks M, bits N, max iterations, mode, alpha, beta | N LLRs; flattened M×N binary H | N hard bits, N posterior LLRs; modes 0=SP, 1=MS, 2=NMS, 3=OMS |
| 7 `stft` | FFT size, hop | signal; unused | Full complex spectra, frame-major order |
| 8 `istft` | FFT size, hop | frame-major spectra; unused | Finite-frame normalized overlap-add waveform |
| 9 `omlsa` | FFT size, hop, noise-only frames, prior-SNR smoothing | noisy signal; unused | Same-length waveform, reflected edge padding; calibration prefix must contain noise only |
| 10 `beamform` | channels M | time-major channel observations; steering vector | Matched steering sum divided by steering energy |
| 11 `mimo` | square channel size M, regularization | time-major observations; row-major channel H | `(HᴴH + regularization I)⁻¹Hᴴr` |
| 12 `ofdm_tx`, 13 `ofdm_rx` | FFT size N, prefix CP | carrier blocks or received blocks; unused | Unitary-scale IFFT plus CP, or CP removal and unitary-scale FFT |
| 14 `fsk_tx`, 15 `fsk_rx` | samples/symbol, base bin, bin spacing, alphabet | labels or waveform; unused | Per-symbol integer-bin tones, or noncoherent correlation labels |
| 16 `costas` | proportional gain, frequency gain | QPSK symbol-rate samples; unused | N corrected samples followed by N phase estimates |
| 17 `timing` | nominal SPS, output count, initial sample position, proportional gain, integral gain | matched-filtered samples; unused | Recovered complex symbols followed by their sample positions; cubic interpolation |
| 18 `notch` | notch frequency, pole radius | signal; unused | Causal second-order notch output |
| 19 `kalman` | process variance, measurement variance, initial variance | scalar observations; unused | Random-walk posterior means |
| 21 `wsinc` | odd tap count, cutoff | nonempty placeholder; unused | Unit-DC Hamming-window low-pass FIR |
| 22 `alamouti` | none | paired receive slots; two channel coefficients | Recovered symbol pairs for the stated 2-TX/1-RX code |
| 23 `gf2_encode` | parity rows M, information bits K | K bits; row-major binary A | `[A·bits mod 2, bits]`, parity matrix `[I A]` |

STFT uses `sqrt(0.5 - 0.5*cos(2*pi*(k+0.5)/N))`; only complete frames are included. Reconstruction tests use lengths aligned to the hop. PFB and WOLA expose the same analysis transform, implemented as phase accumulation followed by DFT; they are not two distinct historical scheduling replicas. In OQPSK, the portable Q branch is delayed by half a symbol; carrier correction precedes independently timed I/Q sampling.

## Reproduce

```bash
# All frame modems and typed algorithms, including UVM:
python3 tools/run_tests.py --suite all

# Typed algorithms independently:
python3 tools/run_research.py --suite all
python3 tools/run_research.py --suite matlab

# Original-function comparisons (MATLAB in a terminal):
python3 tools/run_matlab_evidence.py --suite references
python3 tools/check_research_references.py

# One model, any supported suite:
python3 tools/run_research.py --suite octave --workspace coding/ldpc

# Scientific figures and offline HTML:
python3 tools/typed_visual_report.py
python3 tools/report_typed_results.py
```

MATLAB should inherit a terminal on this host; the agent execution option is `tty=true`. New M-files require no extra Octave package. Figure rendering and analytic Python checks use NumPy, SciPy and Matplotlib from [the visual requirements](../requirements-visual.txt). Raw captures, language results and UVM logs are in `build/typed/`; original-reference arrays are in `build/typed/originals/`. Generated reports retain hashes and link every view to its workspace.


## Input validation and evidence

Integer dimensions must be positive exact integers; fractional dimensions are rejected in all three kernels. LDPC requires positive iterations and parity-check rows of degree at least two; optional alpha/beta default to 0.8/0.15. Adaptive desired-signal length must match input length. OM-LSA requires more input samples than the FFT size and a noise-frame count within the padded STFT. Invalid dimensions and nonfinite values are rejected before kernel execution. The validator contract is maintained in `tools/generate_validation.py`; Python, M and SystemVerilog validation files are generated together.

`python3 tools/check_contracts.py --suite all` checks 27 boundary transactions in Python, Octave and SystemVerilog: 21 required rejections and six accepted boundaries. Use `--suite matlab` for the same MATLAB checks. SystemVerilog rejects invalid transactions through `$fatal`; valid transactions are compared numerically. Integer casts use `$rtoi` after validation.

Run a workspace test through its script, `python3 -m unittest discover -s algorithms/coding/ldpc/tests -v`, or pytest. Imports do not execute regressions. Workspace `run_model` accepts an omitted auxiliary argument; shell wrappers forward command arguments and fail if the project root is missing.

Source hashes are taken before execution and verified afterwards. Reports refuse stale sources and vector/log changes. Full and single-workspace results use separate directories. MATLAB original checks fail the process after saving diagnostics if any selected model fails; a single-model run cannot overwrite the full collection report. Python optimization (`-O`) is rejected by regression entry points because it would disable analytic assertions.

Both visual pages install resource, JavaScript and Promise error collectors before loading application scripts. Browser checks require that collector and inspect its complete error list.


## Полный проход расширенной библиотеки DSP — 2026-10-30

Завершены модельные этапы всех44 задач расширения: прежние четыре и новые40. [Карта реализаций, ТЗ, ограничений и повторения](EXTENDED_DSP_MODELS.md), [общая приёмка](extended_dsp_models_20261030_results.json). Полные RTL-пункты продолжают отслеживаться отдельно в RTL_TODO.md.
