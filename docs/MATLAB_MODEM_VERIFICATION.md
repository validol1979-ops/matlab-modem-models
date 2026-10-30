# MATLAB modem verification

Explore the [interactive signal report](visual/index.html) or the [PDF atlas](visual/modem_test_report.pdf) for original MATLAB captures and reference comparisons. [Plot conventions](VISUAL_TESTS.md) describe what each graph measures.

All 20 archived modem models load in MATLAB R2020b. Five compile without library or dimension changes; all 20 simulate successfully with the documented compatibility adjustments. Every captured signal contains finite values, and repeating each simulation reproduces the recorded timestamps and samples exactly.

This is runtime verification with partial numerical reference comparisons. Full receiver correctness and complete MATLAB/Octave/Python/SystemVerilog equivalence are not established.

## Results

| Check | Result |
| --- | --- |
| Original MDL hashes | 20 unchanged |
| Original models loaded | 20/20 |
| Original models compiled without adaptations | 5/20 |
| Adapted models simulated | 20/20 |
| Exact repeatability after a new simulation start | 20/20 |
| Captured signals / numeric values | 556 / 10698392 |
| Original mapper blocks checked against portable tables | 17 in 16 models |
| Mapper sample comparisons | 60091 |
| Maximum mapper difference | 0.0 |
| MSK and GMSK unit envelope checks | 2/2 |
| MATLAB MSK versus Python and Octave | 16352 samples; maximum error 4.813e-14 |
| MSK UVM reference test | 4 frames; 67452 complex comparisons; maximum error 4.813e-14 |

Mapper checks cover every label of each tested alphabet and compare samples at identical timestamps. QAM64 has separate real and imaginary mapper blocks. CPM and pi/4 mapping/state chains are outside this table comparison.

| Model | Original compile | Adapted simulation | Exact repeat | Mapper blocks |
| --- | --- | --- | --- | --- |
| [QAM64_2008_11_21](../modems/QAM64_2008_11_21/matlab/verification.json) | FAIL | PASS | PASS | PASS (2) |
| [bpsk_costas_2008_08_25](../modems/bpsk_costas_2008_08_25/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [dqpsk_19_09_2006](../modems/dqpsk_19_09_2006/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12](../modems/dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [gmsk_coherent_demodulation_2010_10_03](../modems/gmsk_coherent_demodulation_2010_10_03/matlab/verification.json) | PASS | PASS | PASS | Not checked |
| [msk_modulator_2008_06_22](../modems/msk_modulator_2008_06_22/matlab/verification.json) | PASS | PASS | PASS | Not checked |
| [pi4_qpsk_8_sps_ff_sync_2021_05_27](../modems/pi4_qpsk_8_sps_ff_sync_2021_05_27/matlab/verification.json) | PASS | PASS | PASS | Not checked |
| [pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15](../modems/pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15/matlab/verification.json) | PASS | PASS | PASS | Not checked |
| [psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15](../modems/psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19](../modems/psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18](../modems/qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26](../modems/qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10](../modems/qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21](../modems/qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [qpsk_demod_with_phase_noise](../modems/qpsk_demod_with_phase_noise/matlab/verification.json) | PASS | PASS | PASS | PASS (1) |
| [qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06](../modems/qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15](../modems/qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20](../modems/qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [qpsk_phase_noise_phase_sync_2009_04_12](../modems/qpsk_phase_noise_phase_sync_2009_04_12/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |
| [simo_maximal_ratio_combining_2010_08_27](../modems/simo_maximal_ratio_combining_2010_08_27/matlab/verification.json) | FAIL | PASS | PASS | PASS (1) |

## Compatibility and execution conditions

The copies in `modems/<name>/matlab/` replace missing `commchan2` references with `commchan3` and missing `commdigbbndpm2` references with `commdigbbndpm3`. Original numeric parameters are retained. Every migrated PSK block has `numSamp=1`; the replacement block omits that obsolete parameter. The installed MathWorks helper `commdigbbndpm2ReplaceBlocks.m` documents the same PSK parameter mapping. Each workspace records exact changes and hashes in `matlab/migration.json`.

SIMO additionally needs explicit dimensions on the cubic Farrow subsystem input ports: two antenna channels and one scalar timing value. These settings are applied in memory and recorded in the results. Library replacements are not proof of equivalence to the historical MATLAB release, including its noise generator behavior.

Runs use normal simulation and the original solver, channel parameters, seeds and startup callbacks. Plot windows are disabled. Duration is limited to 16384 minimum discrete time intervals; the QPSK phase-noise example uses 262144 intervals, producing 10923 symbol observations. QAM64 retains its variable-step `ode45` solver. These are bounded tests, not full-duration BER sweeps. Logging observes top-level block outputs and selected mapper inputs/outputs; it does not cover every internal node.

The raw logs retain legacy-block, disconnected-port and headless-display warnings. These do not prevent the recorded simulations. No original MDL file is saved or changed by the checker.

## QPSK phase-noise finding

The original Error Rate Calculation block reports a symbol error rate of 100%: 10910 errors in 10910 comparisons. This is not a clean raw decoding result.

At the original block's delay of 13 symbols, received labels have a constant offset of 3 modulo 4. The phase hypothesis is selected from an earlier interval and tested on the held-out second half: 0 errors in 5455 symbols after that correction. This is consistent with a quadrant/mapping ambiguity. The original transmitter uses phase zero and its demapper uses pi/2. No correction is inserted into the archived receiver or hidden in the raw counter.

## MSK waveform reference

The comparison starts after the original scrambler and uses 511 captured bits. The portable cores run at the original 32 samples per symbol, instead of the portable workspace's default eight. A fixed delay of 33 samples accounts for the original CIC delay of one symbol and the phase integrator delay of one sample. No fitted gain, phase or time resampling is applied. A one-sample wrong delay gives an error of 0.049082, confirming that the test detects misalignment.

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
