# Visual modem tests

Open the [interactive HTML report](visual/index.html). It works directly from the filesystem without a server, an internet connection or MATLAB. Select a modem by name or modulation family, choose one of three portable channel cases, and switch to the original MATLAB capture. Each figure opens as SVG and downloads as PNG.

The [PDF atlas](visual/modem_test_report.pdf) contains 44 pages: coverage, the QPSK finding, the MSK reference, a negative control, and an original-capture page plus a portable stress-case page for each modem. All 84 figures are available separately. [CSV metrics](visual/summary.csv), [report data](visual/report_data.json) and [source and image hashes](visual/provenance.json) accompany the report.

## Reading the portable plots

| Plot | What it shows |
| --- | --- |
| Waveforms | Transmitted I/Q and received channel I over the first 24 symbol periods; no fitted time/phase correction is applied to this overlay. |
| Channel I/Q cloud | Oversampled channel points, or the combined SIMO input. These points are not symbol decisions. |
| Recovered constellation | Payload receiver symbols against the ideal alphabet, after the portable receiver's synchronization and equalization. |
| CPM discriminator | For MSK/GMSK, integrated phase increments grouped by transmitted bit. The threshold is zero; this is not a QAM/PSK constellation. |
| Spectral density | Welch estimates with a common reference: the peak TX spectral density. Frequency is divided by the symbol rate. |
| Symbol estimate error | Linear modulation: absolute symbol error divided by RMS ideal-symbol magnitude. CPM: deviation from the ideal binary phase increment of ±pi/2. Gaussian shaping can produce nonzero CPM metric deviations without bit errors. |
| Decoded labels | Transmitted and decoded integer labels for the first 64 payload symbols, with actual errors marked in red. |

BER and SER exclude the 192-symbol training prefix. Each case contains 320 payload symbols. BER counts differing bits in the binary integer labels; the bit order does not change that count. A measured BER of zero on this finite frame is not an upper bound or a long-run performance guarantee. SNR here is sample SNR, not Eb/N0.

All 60 saved vector cases are replayed by the current Python core before plotting. The renderer checks the TX samples, decoded labels and receiver symbol estimates against the stored reference. The original portable Octave/SystemVerilog regression results are read from the recorded evidence; the renderer does not rerun those tools.

## Reading the MATLAB plots

These are actual R2020b captures, verified against the stored capture hashes. The original archive files remain unchanged. The model's library migration and SIMO dimension settings remain visible in the evidence panel.

The plots show the native transmitter, its envelope, a named receiver/control monitor and the mapper or I/Q trajectory. Complex receiver monitor values may be oversampled or held, so their cloud is not a BER measurement. A real-valued control output is plotted against model time rather than being presented as an I/Q constellation. Dense traces/clouds are thinned for display; checks and error metrics use the full relevant arrays.

## Findings and negative control

- **MSK reference:** 16,352 MATLAB samples after the original scrambler match Python and Octave at 32 samples per symbol, after a fixed 33-sample startup delay. The error curve is computed from those samples; the SystemVerilog maximum comes from the recorded UVM check, whose receiver reference still comes from Python.
- **QPSK phase ambiguity:** confusion matrices expose the constant offset of three modulo four. The raw result and the diagnostic correction are both shown. The correction is selected before the held-out interval and is not inserted into the original receiver.
- **BPSK negative control:** a fresh deterministic Python channel at −8 dB sample SNR produces 50 errors in 320 payload symbols. This demonstrates that the checking path detects bad reception. The generated numerical signals are saved in `visual/negative_control_data.npz`.

## Rebuild

The current environment already has the plotting dependencies. On another machine, install `requirements-visual.txt` in the project's Python environment. First produce the portable vectors and MATLAB reference captures using the commands in [portable verification](VERIFICATION.md) and [MATLAB verification](MATLAB_MODEM_VERIFICATION.md), then run:

```bash
python3 tools/visual_report.py
```

The renderer verifies implementation/configuration hashes and capture hashes before using the saved results. Missing or stale evidence causes a nonzero exit rather than a fabricated pass. It writes `docs/visual/`; `--output PATH` can redirect the generated report. All displayed metrics and figures come from numerical data; no illustrations replace measured signals.

Firefox integration checks exercise all 80 modem/view combinations, name and family filtering, the empty search result, section switching and the narrow layout. The browser results and screenshots are saved in `build/visual_browser/`. `tools/check_visual_browser.py` connects to a separately launched test Firefox profile with Marionette on localhost port 2841; it does not use the user's normal browser profile.
