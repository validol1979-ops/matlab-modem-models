# Review corrections and verification

The actionable findings in [the September 30 review](CODE_REVIEW.md) are addressed. The fixes cover reliable evidence, process exit status, isolated runs, input contracts, test discovery and negative controls. Historical sources remain unchanged. Passing these checks validates the documented portable models; complete historical-model equivalence and streaming RTL reset behavior remain outside that claim.

## Corrections

| Review finding | Resolution |
| --- | --- |
| Typed tests execute during import and discover zero tests | All 13 block-model workspaces now expose a `unittest.TestCase`; importing a module does not launch a process. Direct execution and unittest discovery pass. A pytest configuration selects importlib mode for repeated test filenames; pytest was not installed in the verification environment. |
| MATLAB hides model failures behind exit code zero | Both original-model runners save diagnostics, reject empty selections and fail if any selected model fails. An incompatible original QAM64 model produced saved FAIL diagnostics and MATLAB exit code 1. |
| Reports attach current hashes to old PASS results | Runners capture hashes before execution and verify them afterwards. Reports verify those saved hashes and the relevant log/vector hashes. A changed implementation or artifact is rejected. Results are invalidated at run start and written atomically after success. |
| Single-model runs overwrite aggregate evidence | Frame runs use `build/single/<name>` and `build/questa/single/<name>`. Original MATLAB runs use `<mode>/single/<name>`; research originals use `research_review/single/<name>`. Aggregate hashes remained unchanged after actual single-model runs. |
| SystemVerilog rounds fractional dimensions | Integer dimensions must be exact integers in all languages. Invalid fractions are rejected before allocation; SystemVerilog uses `$rtoi` after validation. |
| Timing and phase-noise tests do not require tracking | Specialized tests compare enabled and disabled loops on identical inputs. Gardner handles both signs of 6e-4 clock drift; carrier tests use phase-noise increments with standard deviation 0.005 radians. Enabled loops have zero payload errors; disabled loops have errors. |
| LDPC negative control overstates coverage | All four decoder scenarios use the same decoded-word and syndrome checker for normal acceptance and deliberate rejection. Mutations flip a decoded bit or bypass decoding. Decoder controls are no longer attributed to the encoder. |
| UVM fatal detection accepts a summary heading | The checker requires a real `UVM_FATAL ... [NUMERIC]` message and a nonzero fatal count. Transaction coverage uses an explicit exception. Regression entry points reject Python `-O`. |
| Frame-modem UVM lacks negative control | Every modem runs once more with a corrupted expected TX sample. Each run must produce the expected numeric scoreboard failure. Reset documentation describes interface output clearing and block repeatability, not persistent filter-state reset. |
| Browser checks miss startup errors | Error and unhandled-Promise collectors are installed in the page head before application code. Resource load failures are captured as well. Browser checks require the collector and inspect its accumulated errors. |
| Carrier fit accepts zero references | Python, M and SystemVerilog reject zero or nonfinite reference values and invalid gain explicitly. |
| DSP kernels disagree on malformed input | A generated contract validates parameter counts, integer sizes, dimensions, finite values and algorithm-specific constraints before computation. The three numeric implementations remain separate. |
| Infinite root search and missing argument forwarding | Shell and M entry points stop with `Project root not found` at the filesystem root. Shell wrappers forward arguments. `run_model` accepts an omitted auxiliary input. |
| Installation paths and compiler are fixed | Questa honors `QUESTA_HOME`, PATH and `UVM_HOME`; both HDL runners honor `DPI_CC`. MATLAB honors `MATLAB_ROOT` and PATH, with user-home installation fallbacks. M command paths escape apostrophes. |
| Weak SV modem configuration validation | The model checks allowed alphabets/enums, filter parameters, even OQPSK SPS, constellation size and finite constellation/received values before processing. |
| Handwritten MSK vector configuration | Both portable and MATLAB-reference vectors use `generate_vectors.config_text(cfg)`. The original MSK waveform comparison and UVM run passed again. |
| New original entry point checks both models | Each generated `test_original.m` selects its own model. The OQPSK entry point was executed and produced exactly one selected-model result. |
| Generator overwrites are undocumented | The root README and generated workspace READMEs identify the files overwritten and direct customizations to the generators. |

LDPC accepts four to six parameters, using default alpha 0.8 and beta 0.15. Zero decoding iterations and parity-check rows of degree less than two are rejected. OM-LSA requires input longer than its FFT size and a calibration-frame count within the padded analysis. These boundaries are documented in [the model contract](TYPED_MODELS.md).

## Verification

- 185 frame-modem Python tests, including eight regression guards, passed.
- All 13 typed workspace unittest entry points were executed and passed; imports were checked separately for side effects.
- 24 Octave modem checks and 72 Python/Octave channel comparisons passed.
- 24 frame-modem UVM runs checked 96 frames, with a separate detected numeric mismatch for every modem.
- 40 DSP scenarios passed in Python, Octave and MATLAB; UVM checked 80 transactions and detected the injected mismatch.
- 27 boundary scenarios passed in Python, Octave, MATLAB and SystemVerilog: 21 expected rejections and six accepted numerical comparisons.
- 20 prepared historical models and two new original models passed bounded MATLAB simulation and repeatability checks. Fourteen original-reference/MATLAB checks and nine original-MATLAB/Python comparisons passed.
- The original MSK transmitter again matched Python, Octave and SystemVerilog over 16,352 samples, within 4.82e-14.
- Actual single-model executions preserved aggregate report hashes. Missing-root wrappers terminated, shell arguments were forwarded, and the three-argument M entry point worked.
- Both regenerated atlases passed Firefox checks: 80 historical views and 54 typed views, with no recorded JavaScript errors or horizontal overflow. Deliberate startup exceptions, Promise rejections and missing images were detected in both collectors. All 278 PNG/SVG artifact hashes passed; PNG files decoded successfully.
- All 435 downloaded-file hashes and 11 ZIP archives passed integrity checks.

Reproduce the main portable checks with `python3 tools/run_tests.py --suite all`. MATLAB uses `python3 tools/run_research.py --suite matlab` and `python3 tools/check_contracts.py --suite matlab`; on this host these commands require a terminal. Full numerical evidence is in [the frame report](VERIFICATION.md), [typed verification JSON](typed_verification_results.json), and `build/contracts/`.

## Clarifications to the review

Python 3.13 unittest returns exit code 5 when it runs no tests; pytest also uses exit code 5 for no collected tests. Root unittest discovery finds no tests because the workspace directories are not Python packages; use `tools/run_tests.py` or the explicit workspace entry points. Custom `norecursedirs` in `pytest.ini` replaces the pytest defaults. Fractional Python operation identifiers already raised `ValueError`; integer identifiers outside the range now do so as well. The previous reset test did check interface clearing, although it did not establish internal streaming-state reset correctness. The previous snapshot's 353 source hashes matched the repository when reviewed; the evidence defect was a reproducible path to falsely attaching old results to future changes.

The [machine-readable correction report](review_fix_results.json) includes aggregate hashes before and after isolated runs, current evidence hashes, the expected MATLAB failure record and browser results.
