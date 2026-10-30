# Portable modem contract

The three implementations define the same executable frame model. Their agreement is verified numerically, independently of whether the archived Simulink models behave identically. All 20 originals now run in MATLAB R2020b with recorded compatibility adjustments. Partial reference checks cover 17 mapper blocks in 16 models and the MSK transmitter after its scrambler; see [MATLAB verification](MATLAB_MODEM_VERIFICATION.md). These checks do not establish full receiver or historical-release equivalence.

## Data and waveform conventions

Input is a nonempty vector of integer symbol labels from zero through `order - 1`. Labels represent binary words with the most significant bit first when converted to bits. Configuration contains the complete complex constellation table as real and imaginary pairs. Original table amplitudes are retained, including the half amplitude diagonal BPSK constellation and the integer 64-QAM constellation.

PSK differential coding accumulates Gray encoded input labels modulo the constellation size. QAM differential coding accumulates the Gray encoded quadrant and retains the amplitude group within that quadrant. Pi/4 DQPSK adds `pi/4 + pi/2 * Gray(label)` to the phase. Each frame starts from differential state zero. The historical custom 64-QAM quadrant coder is not reproduced exactly.

Linear modulation uses eight samples per symbol and a unit energy RRC pulse of order 32 with rolloff one. The complete FIR tail is returned. These common pulse settings are a portable baseline; not every historical variant used these exact filters. MSK integrates bipolar NRZ data with modulation index one half. GMSK additionally applies a Gaussian filter with BT 0.3 and four symbol span, normalized to unit DC gain. CPM phase starts from zero and its envelope is one.

## Receiver interface

`receive(configuration, received_waveform, training_labels, frame_symbol_count)` uses only the training prefix to estimate synchronization parameters. The regression uses 192 training symbols in a 512 symbol frame; the minimum accepted training length is 32. Frame length and a coarse frame boundary are supplied by the caller. This is not an arbitrary length burst detector.

The linear receiver applies the matched RRC filter, searches a delay range from zero through two symbol intervals in quarter sample steps and uses four point cubic Lagrange interpolation. Carrier phase is unwrapped over the training sequence; linear regression estimates frequency and complex correlation estimates phase and gain. This feedforward acquisition replaces historical blind acquisition and resolves PSK phase ambiguity through the preamble.

The `gardner` timing option adds a bounded Gardner timing correction. `feedforward` timing keeps the acquired sampling phase. Feedback carrier tracking uses a decision directed second order loop; BPSK Costas tracking uses the rotated sign detector. The `feedforward` carrier option means training based acquisition followed by a first order residual decision directed correction. It is not a transcription of the original fourth or eighth power blind estimator.

The linear equalizer has seven feedforward taps. DFE adds three decision feedback taps. Both use normalized LMS, with training targets in the preamble and decision targets afterwards. Historical Godard blind adaptation, Muller and Mueller timing, and original coefficients are replaced by this explicit shared design.

The portable CPM receiver uses a frequency discriminator after training based delay, phase and frequency correction. GMSK includes Gaussian group delay compensation. It replaces the historical coherent Mengali and Costas receiver. The MSK original is a modulator; its receiver is an added verification companion.

SIMO combining uses known complex branch gains and positive branch noise variances. Channel estimation itself is outside the combining block contract.

## Historical features outside this abstraction

Original scramblers, descramblers, CIC interpolation stages, scopes, passband hardware, exact Simulink block scheduling and initial transients are preserved as source evidence but are not simulated by the portable frame model. Several archives with different synchronization realizations therefore share a portable configuration. A folder per archive preserves their identity and source evidence without claiming that these historical differences have been fully recreated.

All source block fields in `source_parameters.json` are extracted as data; the extraction tool does not evaluate MATLAB expressions. The separate MATLAB reference checker executes the models and their startup callbacks. `source_line` refers to the original MDL line. The archive named `dqpsk_19_09_2006` actually specifies 8-PSK with `M=8` and `Ph=pi/8`; this is retained.

## Tested operating conditions

The tests cover noiseless loopback; AWGN at 28 to 35 dB sample SNR; gains from 0.2 to 1.3; phase offsets from -1.1 to 0.38 radians; frequency offsets from -0.0005 to 0.00015 cycles per sample; and fractional delays up to 7.25 samples. Variant tests add an echo of 0.4 or 0.45 at one symbol delay, clock drift of 100 ppm, phase noise and two branch diversity.

Sample SNR is measured from the average waveform power and is not Eb/N0. These deterministic cases establish a regression envelope, not a measured acquisition range or a BER performance guarantee. A negative test at -8 dB confirms that demodulation can produce errors; payload truth is not copied to the result.

## SystemVerilog and UVM

`modem_dsp_pkg` independently implements complex arithmetic, mapper and differential state, transmit filtering, acquisition, interpolation, tracking, equalization and CPM demodulation. `modem_model` wraps the functions in a clocked frame interface. Processing completes within one simulated request cycle; this latency is an abstraction, not a hardware throughput claim.

The testbench uses actual UVM 1.2 classes: a sequence, sequencer, driver, passive monitor, environment and scoreboard. Python generates noisy input samples and golden results. The transmitter receives the complete input label vector; the receiver receives only the waveform and its training prefix. Expected outputs are read by the sequence and sent to the scoreboard. Four transactions exercise three channel scenarios, gaps between requests and a repeat after reset. A watchdog catches missing completion. The runner requires zero simulator errors, zero UVM errors and fatals, and an exact checked frame count.

Complex samples are compared with an absolute tolerance of `1e-7`; delay and frequency estimates use `1e-8` samples and `1e-10` cycles per sample. Integer labels must match exactly. The default reference set is generated by Python. An additional MSK UVM run uses captured MATLAB transmitter samples, with 32 samples per symbol and a documented 33-sample startup delay; its receiver references still come from Python.

The testbench structure follows the [Accellera UVM 1.2 user guide](https://www.accellera.org/images/downloads/standards/uvm/uvm_users_guide_1.2.pdf). Octave documents that MDL and SLX files are unsupported in its [compatibility notes](https://docs.octave.org/v4.4.1/Status-of-Variables.html); this project runs ordinary M functions instead.
# New typed models

The research additions have a separate [typed model contract](TYPED_MODELS.md). It covers the explicit OQPSK half-symbol offset, four new frame-modem workspaces and 13 block-algorithm suites. Frame OQPSK estimates the channel from a known preamble before combining independently timed I/Q samples; it does not reproduce the original blind loop or scrambler. The old frame-modem substitutions below still apply.
