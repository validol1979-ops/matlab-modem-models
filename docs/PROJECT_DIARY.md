# Modem project diary

This diary records the archive audit, portable modem implementations and verification evidence. Original archives remain in `arxiv`; extracted originals and their hashes are recorded in `archive_inventory.json`.

## 2026-10-30: все44 модельных этапа расширенной DSP-библиотеки — PASS

Выполнены оставшиеся 40 задач из локальной RAG-библиотеки: фильтры/модуляторы, FEC/последовательности/LLR, каналы/антенны/аудио/радар. Три координатора использовали реальные pi/OpenCode-вызовы через Qulab; неполные внешние попытки с output-length явно отделены от проверенных результатов. Источники и ТЗ сохранены, библиотека/индекс не изменялись.

Итог: 280 численных тестов, 280 в изолированной копии и 1093 зарегистрированных Python-теста по 24 модемным конфигурациям — PASS на одном снимке 1560 исходников. Review выявил и исправил float AM stall и переполнение finite LLR до quantizer clip; финальные прогоны выполнены после исправлений. Все 225 RTL-файлов побайтно сохранены, компиляция/синтез и HDL-симуляция не выполнялись. Модельная очередь 44/44 закрыта, аппаратные пункты TODO остаются отдельными этапами.

[Модели и ограничения](EXTENDED_DSP_MODELS.md), [итоговая приёмка](extended_dsp_models_20261030_results.json), [план/прогресс](../research/full_dsp_20261030/progress.json). Предыдущие свидетельства остаются историческими снимками и не переподписываются под новую ревизию. Коммит не создавался.

## 2026-10-29: третий короткий буфер BPSK RX и приоритет конфигурации — PASS

В общий `bpsk_rx` добавлен третий короткий буфер захвата 2048×36 (`SHORT_SAMPLES`), два полноразмерных сохранены. Он используется только при `8N+96 ≤ 2048` (N ≤ 244, N задан `cfg_count` заранее), кольцо 0→1→2→0, иначе прежнее 0→1→0; выдача в порядке приёма, переполнение исключено, отсутствующий TLAST даёт прежний sticky error. Память +73 728 бит, оценка +2 BRAM Artix-7 / +8 M10K Cyclone V (без синтеза). Результат: пачка 4×192 — **0** дополнительных тактов блокировки вместо 975; 768/2048 без регрессии; серия 16×192 по-прежнему блокируется (6147 тактов), данные верны. Причина ограничения — захват 1341 такт на кадр; бесконечный поток N=192 требует ускорения захвата до ≲722 тактов, решение не принято.

Независимое ревью нашло давний дефект: пустой настроенный RX одновременно принимал первый бит новой конфигурации и первый отсчёт кадра и зависал до сброса. Теперь принятый cfg handshake снимает `s_ready` в этом такте; исправлено в `bpsk_rx` (все 14 профилей, включая SIMO — у `simo_rx` +1 такт латентности из-за входного регистра), `fxp_mrc2`, `cpm_rx` (MSK/GMSK) и `oqpsk_rx`. Добавлены 28 коллизий с отрицательными контролями (код 13), побитное восстановление короткого банка после сброса и смены N 244↔245 (5130 символов, 21 захват), освобождение банка после ошибочного TLAST.

Questa 2024.1, обе полярности — **PASS**: `run_bpsk.py --suite all` (`build/bpsk_rx_short3_all_20261029_review3`), темп (`build/bpsk_rx_short3_rate_20261029_review3`), UVM RX всех профилей (`build/bpsk_rx_short3_uvm_rx_20261029_review2`), `run_cpm`/`run_oqpsk` (`build/{cpm,oqpsk}_rx_cfg_20261029_review2`), UVM OQPSK/CPM/packet RX; общий lint PASS. Каталоги `_review2` BPSK all/rate — сохранённый FAIL компиляции тестбенча (использование до объявления), исправлен. Попутно: убраны значения по умолчанию входных портов `cfg_enable` (переносимость в Quartus Standard) и исправлено предупреждение VARHIDDEN в `lms_filter.sv` (переименование genvar, без изменения логики), из-за которого падал общий lint. Работа выполнена подагентами Codex (реализация, ревью), Questa — куратором: в sandbox Codex `vsim` получает SIGSYS. Синтез на паузе; подробности — [BPSK_RTL.md](BPSK_RTL.md), [RTL_BPSK_RX_CONTINUOUS_RATE.md](RTL_BPSK_RX_CONTINUOUS_RATE.md).

## 2026-10-29: RTL-подтверждение конечного исследования захвата Costas — PASS

Добавлен `tools/run_costas_stream_acquisition.py` и 11 Python-тестов в `tests/test_costas_stream_acquisition_rtl.py`. Раннер генерирует те же 72 траектории идеального QPSK и нулевой контроль исходным генератором исследования, воспроизводит сохранённые модельные метрики и предусматривает 146 плотных Questa-прогонов при `RESET_ACTIVE=1/0`: 448512 выходных слов `{re, im, phase, last}`. Существующий тестбенч пишет принятые выходы через `+OBSERVED`; раннер повторно сверяет каждое слово, считает метрики из этих RTL-фаз и сравнивает каждую запись с историческим JSON. `+INJECT_MISMATCH` предусмотрен на первой траектории при каждой полярности, шлюз требует ровно код 13 и численный Fatal нужного scoreboard. Каталог результата должен быть новым; при отказе записывается FAIL с фактическими счётчиками и хешами.

Выполнены `python3 -m pytest -q tests/test_costas_stream_*.py tests/test_sync_fixed.py` и `python3 tools/run_costas_stream_acquisition.py`. Итог Python на финальном снимке — **34 теста и 42 подтеста PASS**; строгий Verilator 5.050 — PASS без предупреждений. Сгенерированы **73 × 3072 = 224256** входных отсчётов, ограниченных компонент нет; все 73 записи модели полностью совпали со старым JSON. Questa остановлен средой: уже `vsim -version` получает SIGSYS, Python-код процесса **−31**, вывод пуст. В этой сессии запуск вне sandbox запрещён. Поэтому выполнено **0 положительных RTL-прогонов, 0 сверок RTL-слов и 0 отрицательных контролей**; успешное RTL-подтверждение пока не получено.

Свидетельство отказа — `build/rtl/costas_stream_acquisition_rtl/acquisition_results.json`, статус **FAIL**, **1463 исходника и 227 артефактов** с хешами. `regression_evidence.verify` подтвердил хеши; `require_pass` ожидаемо отверг FAIL. Начальные локальные попытки сохранены отдельно в каталогах с суффиксами `_attempt1/2`; исторические свидетельства и модельный JSON не переписывались. [Отчёт исследования](RTL_COSTAS_STREAM_ACQUISITION.md) явно сохраняет модельный статус чисел захвата и команду повторного запуска в новом каталоге. Арифметика RTL и `sync_fixed.costas_pipelined` не менялась. Открыты запуск Questa, измерение двух кодов 13 и сверка RTL-метрик для всей сетки. Синтез, Fmax, полная область захвата и общая проектная регрессия не выполнялись; коммит не создавался.

Повторный запуск вне sandbox: `python3 tools/run_costas_stream_acquisition.py --output-dir build/rtl/costas_stream_acquisition_rtl_20261029` — **PASS** за 72 с. 146/146 положительных прогонов, 448512 слов побитно, метрики из RTL-фаз совпали с модельным JSON для всех 73 записей при обеих полярностях, оба отрицательных контроля — код 13. `require_pass` прошёл (1463 исходника, 525 артефактов). Каталог FAIL первого запуска сохранён как есть.

## 2026 September 30 Archive audit

The collection contains 28 unique archives and 37 duplicate occurrences, including nested archives. Twenty modem workspaces were created under `modems`. The remaining material consists of archive collections, adaptive filtering examples, analog and mixed signal examples, digital predistortion, polar coding, a graphic equalizer and a sequence generator.

The modem originals are Simulink MDL models. They require algorithm reimplementation to run in Octave. Original block parameters and mapper tables are retained alongside each portable configuration. The archive named `dqpsk_19_09_2006` actually configures an 8-PSK mapper with phase offset pi/8.

Installed tools: GNU Octave 8.4.0, Python with NumPy 2.4.4 and SciPy 1.17.1, Verilator 5.050 and Questa 2024.1. Questa needs execution outside the process sandbox. Some solid RAR files require UnRAR; a local Ubuntu package was extracted under `<local-tmp>`, without system installation.

## 2026 September 30 Portable implementations

Each modem now has original source, extracted block parameters with original line numbers, configuration, Octave demo and tests, a Python entry point and tests, a SystemVerilog wrapper and UVM testbench launcher. DSP implementations in the three languages are maintained under `common`.

The portable frame contract covers differential coding, original constellation tables where recovered, pulse shaping, noisy complex channels, fractional delay, timing and carrier estimation, Gardner timing tracking, carrier and gain tracking, linear equalization, DFE and MSK/GMSK modulation and reception. SIMO has two branch maximal ratio combining. The receiver uses only known preamble symbols for training; payload labels are reserved for checking.

This is an algorithm reimplementation with explicit substitutions. Training based acquisition replaces historical blind estimators, CPM uses a discriminator receiver, and several related variants share a portable baseline. Historical scramblers, internal CIC stages, original loop coefficients and exact Simulink transients are not reproduced. These limits are recorded in [the porting contract](PORTING_CONTRACT.md), not hidden behind passing tests.

## 2026 September 30 Verification completion

148 Python tests passed. All 20 Octave modem tests and 60 shared Python and Octave channel cases passed. All 20 Questa UVM runs passed, checking 80 frames and 371072 complex samples. The largest Python and Octave difference was about 2.5e-13; the largest Python and SystemVerilog difference was about 1.8e-13, against a 1e-7 absolute tolerance.

The UVM environment contains a sequence, sequencer, driver, passive monitor and scoreboard. It tests channel variations, transaction gaps, output lengths, decoded labels, numerical waveforms and repetition after reset. SIMO stimuli use separate noisy branches, so combining is exercised inside the HDL model. A negative Python test confirms that severe noise causes errors; equalizer tests also fail when the equalizer is disabled on the same echo channel.

Questa required 64 bit execution and `-dpicpppath /usr/bin/gcc`: its bundled compiler could not link against the host libc. The launcher implements this locally and supports overrides. No system simulator settings were changed. The Octave shutdown diagnostic is retained in raw logs; assertions and process exit status all passed.

Reproduction commands, raw log locations and a durable result snapshot are in [verification results](VERIFICATION.md). The snapshot records hashes of implementations and configurations. The [catalog](MODEM_CATALOG.md) links all 20 workspaces.

## Remaining equivalence and hardware work

Full block by block equivalence to the archived Simulink diagrams remains unverified. Establishing it requires original simulation reference vectors and restoring the historical blind synchronization, scrambling and filter details where they differ from the portable contract. The SystemVerilog implementation is a tested behavioral model; fixed point design, synthesis and FPGA timing analysis are separate work.

The auxiliary DSP, polar coding, predistortion and analog archives were inventoried and extracted, but were not converted into modem workspaces.

## Verification policy

Tests must distinguish original source evidence, portable model correctness and agreement between languages. Passing cross-language tests does not establish equivalence to the original Simulink simulation. Original MATLAB runs and partial waveform comparisons are recorded separately in [MATLAB verification](MATLAB_MODEM_VERIFICATION.md).

Documentation and application output use English. New code comments use Russian. Historical sources are preserved byte for byte, including their original language.

## 2026 September 30 MATLAB installation

MATLAB R2020b with MATLAB, Simulink, Communications Toolbox, DSP System Toolbox, Signal Processing Toolbox, Stateflow and Fixed-Point Designer was installed for the reference checks. A project launcher and a MATLAB installation smoke test were added under `tools`.

The first smoke run exposed a conflict between MATLAB's bundled FreeType and the host HarfBuzz library (`FT_Get_Color_Glyph_Layer`). The project launcher now preloads the system FreeType for R2020b; this affects only the launched process. With that adjustment the smoke test passed, including Communications and DSP functions, fixed point arithmetic and a temporary Simulink simulation. All seven installed products appear in MATLAB's product list.

See [MATLAB installation status](MATLAB_INSTALLATION.md) for commands. This verifies the installed runtime; original modem compatibility and MATLAB reference equivalence remain unverified.

## 2026 September 30 Original MATLAB modem verification

All 20 originals loaded in R2020b. Five compiled directly; fourteen required migration of missing Communications Toolbox library references, and SIMO required explicit two-channel/scalar dimensions at its cubic Farrow input ports. Prepared copies, manifests, per-model tests and verification records are under `modems/<name>/matlab`. Original MDL hashes remain unchanged.

All 20 adapted models completed bounded simulations with finite captured signals and reproduced timestamps and samples exactly on a second simulation start. Original solver and channel settings were retained. The QPSK phase-noise example ran for 262144 minimum time intervals; the others ran for 16384. The new checker disables plots and exports plain MAT arrays for independent analysis.

Seventeen mapper blocks across sixteen modems matched portable constellation tables exactly, covering every label. MSK and GMSK preserved unit envelope. The MSK transmitter, fed with 511 bits captured after the original scrambler, matched Python and Octave over 16352 samples to about 4.8e-14. This uses the original 32 samples per symbol and a fixed 33-sample startup delay. UVM then checked the same MATLAB TX reference over four transactions, with 67452 complex comparisons and a maximum error of about 4.8e-14. UVM RX expectations still come from Python.

The original QPSK phase-noise error counter reports 10910 symbol errors out of 10910 comparisons. With its existing 13-symbol delay, the decoded labels differ by a constant offset of three modulo four. A phase hypothesis selected from an earlier interval gives zero errors on 5455 held-out symbols after correction. That diagnostic correction is not inserted into the receiver; raw decoding remains incorrect under the archived counter's convention.

These are successful runtime checks and partial numerical equivalence results, not full verification of every receiver. Historical blind loops, scramblers, transients and exact old-release library behavior remain outside the established equivalence claim. Reproduction commands and durable evidence are in [the reference report](MATLAB_MODEM_VERIFICATION.md) and [its JSON snapshot](matlab_reference_results.json).

## 2026 September 30 Visual verification atlas

An [offline HTML report](visual/index.html) now presents all 20 modems with search, modulation-family filtering, three portable channel cases per modem and a separate original MATLAB view. The output includes 84 figures in both PNG and SVG, a 44-page PDF atlas, CSV metrics, structured report data and source/image hashes. Every modem README links to its report view and embeds a channel-test preview.

The renderer replayed all 60 saved portable cases using the unchanged Python core, checking TX samples, decoded labels and receiver symbol estimates against the recorded vectors. It verified the MATLAB captures against their stored hashes. No MATLAB or UVM simulations were rerun for rendering. Figures distinguish oversampled channel clouds, recovered symbol constellations, CPM discriminator values and real control outputs; graph units and training exclusions are documented in [visual test conventions](VISUAL_TESTS.md).

Dedicated figures show the original MSK waveform agreement and the QPSK label rotation before and after diagnostic correction. A fresh BPSK negative control at -8 dB sample SNR produces 50 errors in 320 payload symbols, visibly demonstrating that the checking path detects bad reception. Its numerical signals are saved with the report.

Firefox integration checks opened all 80 modem/view combinations and checked name/family filtering, an empty search result, section switching, image loading and the narrow layout. The measured narrow viewport was 500 pixels; there was no horizontal page overflow or JavaScript error. The 168 image files, local links and provenance hashes passed validation. Browser screenshots and results are retained under `build/visual_browser/`.

## 2026 September 30 Review of new research downloads

Reviewed the separately collected `research/electronix_20260930` and `research/dsp_global_20260930` directories. Independently checked 435 manifest records by size and SHA-256 and all 11 ZIP archives by CRC. No checked file duplicated an existing `sources/` or `arxiv/` file by hash. The additions comprise two Simulink models and 293 MATLAB files; 188 MATLAB files belong to a book's array-processing examples, rather than separate modems.

The new `oqpsk_2_sps_timing_recovery_2019_12_05` and `qpsk_8_sps_fb_sync_2020_11_25` originals load and compile directly in MATLAB R2020b. A separate checker runs each for 16384 compiled base intervals and checks finite output values, final time and exact repeatability after restarting with the same seed. It captured 65 signals and 989267 values. The final headless launch in a terminal returned exit code 0. Earlier launches without a terminal returned 129 after successful numerical checks; the initial run also exposed graphical diagnostic-window errors. Original files were closed without saving and their hashes were verified again.

Static review confirmed six missing OFDM helper functions, MATLAB-specific fixed-point filter constructors in the QPSK scripts, a missing local RTL tree for the FPGA QPSK reference, and toolbox dependencies in the timing-loop demo. The research material remains separate from the 20 portable workspaces and their existing regression/visual totals. No receiver BER or cross-language equivalence is claimed for the new sources. Details, priorities, commands and evidence are in [the research review](RESEARCH_REVIEW.md).

## 2026 September 30 Typed model implementation and visual verification

Added 17 workspaces from the research collections: six modems and eleven separate algorithm groups. Modems remain under `modems/`; synchronization, channelizers, FIR/interference filters, adaptive filters, LDPC coding, MIMO/diversity, audio processing, array processing and teaching examples are under `algorithms/<type>/`. There are now 26 modem directories: 24 frame-engine configurations plus OFDM and FSK block models. Every one of the 295 downloaded MATLAB/Simulink files is assigned to a workspace and preserved byte for byte. Source packages include helpers and book figures, so this inventory does not claim 295 independently converted executable models.

The new QPSK/OQPSK frame workspaces provide Python, Octave/MATLAB and behavioral SystemVerilog models with UVM. OQPSK explicitly delays Q by half a symbol; a separate analytic test checks that offset against ordinary QPSK. Carrier acquisition uses only the preamble, followed by distinct I/Q sampling instants. Script-derived QPSK examples use the documented portable frame abstraction, not original passband fixed-point arithmetic.

A typed block engine implements 24 operations in Python, Octave/MATLAB and SystemVerilog. Forty seeded and analytic scenarios check FIR responses, DFT, channelization, adaptive convergence, LDPC decoding, STFT reconstruction, OM-LSA gain, beamforming, MIMO/Alamouti, OFDM/FSK and synchronization. The UVM sequence sends each scenario twice with reset between passes; the driver and passive monitor feed a scoreboard that checks metadata, lengths and every output. Expected values are not connected to the DUT. A deliberately corrupted expectation causes a numeric fatal and is recorded as a successful negative control.

The final unified regression completed successfully: 177 Python modem tests, 24 Octave modem checks, 72 cross-language channel cases and 96 modem UVM transactions with 445328 complex comparisons. The typed suite passed all 40 cases in MATLAB and Octave and 80 UVM transactions with 32084 comparisons. Maximum typed errors were approximately 4.09e-12 for MATLAB/Octave and 2.51e-13 for SystemVerilog. A standalone LDPC workspace UVM invocation also passed and detected its injected mismatch.

Original MATLAB reference checks separately verified LMS/NLMS/RLS, PFB/WOLA, PI loop constants and the original LDPC (2016,1008) encoder/four decoders. Nine independent Python comparisons matched the captured adaptive/channelizer outputs and full-length decoded LDPC words. Four new portable frame models also passed MATLAB checks. Source-function order conventions are documented. Full historical receiver equivalence, all original toolbox variants and individual execution of every book figure remain unestablished.

The new offline atlas contains 55 PNG/SVG figures and a 55-page PDF, including original captures of the two new Simulink models. Visual inspection exposed an edge-window amplification artifact in the noise suppressor; reflected padding fixed it in all three implementations, and an amplitude assertion now covers that failure. The corrected seeded example improves mean-square error by about 6.46 dB. Firefox verified all 54 selectable model views, ten category filters, search/empty-search behavior and a measured 500-pixel narrow viewport without horizontal overflow or JavaScript errors. All workspace READMEs link the atlas and embed a test preview.

The historical 20-modem atlas was regenerated separately. Generators retain the expanded frame catalog; historical MATLAB reporting keeps its original scope, while new original-reference checks have their own commands. The complete portable entry point `python3 tools/run_tests.py --suite all` now includes typed algorithms as well as frame modems. See [typed model contracts](TYPED_MODELS.md), [the visual atlas](typed_visual/index.html) and [durable evidence](typed_verification_results.json).


## 2026-09-30 Review corrections

Addressed the findings in `CODE_REVIEW.md`; the disposition and reproducible evidence are in [REVIEW_FIXES.md](REVIEW_FIXES.md) and [review_fix_results.json](review_fix_results.json). Regression evidence is captured before execution, checked after execution and verified when reports are built. Logs and vector hashes are checked too. Single-model runs have isolated output locations; actual frame and MATLAB runs left aggregate hashes unchanged. MATLAB now exits nonzero after a model failure, confirmed with an incompatible original QAM64 model (exit 1 and saved FAIL diagnostics).

Converted all 13 typed workspace tests to passive-import unittest modules. Added a shared generated input contract for Python, M and SV, optional LDPC alpha/beta defaults, explicit rejection of unsupported boundaries, nonfinite checks and consistent integer dimensions. Fixed root-search termination, optional M auxiliary input, shell forwarding, installation discovery/compiler overrides, M path quoting, MSK configuration serialization and selection of exactly one new original model. Generator overwrites are documented.

Strengthened Gardner and phase-noise checks with the same-signal disabled-loop controls. LDPC acceptance rejects deliberately flipped output bits and bypassed decoding through the same checker. Every frame-modem UVM run now has an injected wrong expectation; fatal detection requires both the numeric fatal message and a nonzero fatal count. Reset claims are limited to output clearing and block repeatability. Regression entry points reject `python -O`.

Final portable regression passed 185 Python tests, 24 Octave modems, 72 cross-language channel cases, 96 frame UVM transactions (445,328 complex comparisons) and all 24 frame negative controls. Typed checks passed 40 scenarios in Python/Octave/MATLAB and 80 UVM transactions (32,084 values). The 27 boundary transactions passed in Python, Octave, MATLAB and SV: 21 expected rejections and six valid boundaries. All 13 standalone typed unittest entry points passed. The final full portable run took 86.21 seconds.

Re-ran 20 prepared historical MATLAB models, two new original models, 14 original-reference/MATLAB checks and nine original-MATLAB/Python comparisons. The original MSK reference again matched Python, Octave and SV within 4.82e-14 over 16,352 TX samples. The native negative and selected-model runs retained aggregate evidence. All 435 research-file hashes and 11 ZIP checks passed.

Regenerated the historical and typed atlases (84 and 55 figures; 44 and 55 PDF pages). Startup JavaScript, resource and Promise errors are captured before application code. A browser-test image-decode race exposed during verification was fixed by waiting for the currently selected image. Final Firefox checks passed 80 historical and 54 typed views without JavaScript errors or horizontal overflow. Deliberate startup, Promise and missing-image failures were detected in both collectors. All 278 PNG/SVG hashes and PNG decoding checks passed. Pytest was unavailable; unittest discovery, direct workspace execution and import isolation were verified instead.

The work improves the trustworthiness and coverage of the portable contract. It does not establish full historical-model equivalence, persistent streaming-state reset correctness or synthesizable RTL.

## 2026-09-30 Follow-up review and RTL gap

A read-only follow-up review of the corrections is recorded in [CODE_REVIEW_FOLLOWUP.md](CODE_REVIEW_FOLLOWUP.md). Most corrections were confirmed: evidence capture, isolated runs, passive typed tests, UVM fatal detection, loop ablation controls and the generated input contract. The regression passed 185 Python tests, and the channel stress test of all 24 modems was unchanged. Remaining issues:

- the MATLAB-original and typed reports do not check freshness or status;
- `assert` checks outside the three regression entry points are disabled under `python -O`;
- a singular MIMO matrix is handled differently in each language;
- the `audit` mode always exits with an error.

At the initial planning checkpoint the project contained only behavioral frame-at-once SystemVerilog models with real arithmetic. The task list for fixed-point streaming RTL for all 37 models is in [RTL_TODO.md](RTL_TODO.md).

The RTL must be portable between Altera (Intel) and Xilinx (AMD) FPGAs. Vivado 2024.2, Quartus Prime Standard 25.1 and 18.1, and Verilator 5.050 are installed. A probe module passed synthesis in Vivado (Artix-7) and Quartus Standard 25.1 (Cyclone V) and Verilator lint; the probe used a package, a packed struct, generate, a `$readmemh` ROM, inferred RAM, a complex multiply and an AXI-Stream handshake. The portability rules are in section 0.1 of [RTL_TODO.md](RTL_TODO.md):

- the SV subset is limited to what Quartus Standard accepts;
- no vendor primitives or IP cores in the core;
- DSP and memory are inferred, with 18×18 multiplier widths as the baseline;
- synchronous reset;
- constraints come from a single source for both XDC and SDC;
- every module must synthesize in both tools.

The reference devices are Artix-7 `xc7a35tcpg236-1` and Cyclone V `5CSEMA5F31C6`, with one 192 MHz clock domain per model. After place and route of the probe at a 5.208 ns period, the worst setup slack was +2.698 ns in Vivado (about 398 MHz) and +0.302 ns on the Cyclone V slow model (about 204 MHz). Cyclone V is the limiting device. Multiply and add must be in separate pipeline stages, and feedback-loop latency must be modeled in the bit-accurate Python reference. Throughput has not been agreed yet. The working assumption is one complex sample per clock (24 Msym/s at 8 samples per symbol), with loops updated once per symbol.

The clock was changed to 100 MHz, replacing 192 MHz. Throughput is one complex sample per clock (100 MS/s, 12.5 Msym/s at 8 samples per symbol), with loops updated once per symbol. At a 10 ns period the probe has +7.450 ns setup slack in Vivado (Artix-7) and +4.876 ns on Cyclone V across all timing models. The acceptance target is at least 1 ns of slack on Cyclone V.


## 2026-10-01: начальная инфраструктура RTL

Добавлены `common/python/fixed_point.py`, переносимая арифметика 18/15, шаблоны RAM/ROM и одиночных синхронизаторов. Потоковое UVM-окружение проверяет побитовое совпадение, насыщение, TLAST, остановки и сбросы обеих полярностей; отдельный SV-тест проверяет память и преобразования форматов. Добавлены строгий lint, единый YAML → XDC/SDC, пакетный синтез с размещением/трассировкой обоих вендоров и `tools/run_tests.py --suite rtl`.

Подробности и границы этапа — в [RTL_CONTRACT.md](RTL_CONTRACT.md). Исследование квантования входа 24 приёмников не является полной fixed-point моделью. Первым целым RTL-модемом остаётся BPSK-пилот. Дополнительная Questa FSE пока не запускается из-за лицензии; основной Questa хватает без вендорных библиотек. Более ранние результаты MATLAB и атласов относятся к прежним снимкам исходников и этим этапом заново не подтверждались.

Итоговая контрольная точка: `--suite rtl` PASS, 14 физических сборок при 100 МГц, 6 874 побитовых UVM-сравнения, 205 тестов общей Python-регрессии. Худшие setup/hold: Artix-7 +0.424/+0.018 нс, Cyclone V +1.445/+0.132 нс. Свежесть всех итоговых JSON и их артефактов подтверждена `require_pass`.

## 2026-10-01: потоковый BPSK-пилот

Добавлен полный переносимый код BPSK TX/RX и целочисленный эталон. RRC, таблицы cosine/cubic, CORDIC, делитель, двухкадровый буфер, захват по публичной преамбуле, Costas, early-late, AGC и дифференциальный декодер проверяются отдельно и вместе. Фазовая/временная обратная связь задержана на четыре символа, AGC — на восемь; Python воспроизводит расписание петель.

Функциональный комплект проверяет обе полярности сброса, паузы, сброс внутри кадра, повторные кадры, ошибки протокола, второй seed, длины 192/768/2048 и настоящий RTL TX → RX. Проверяются каждый отсчёт, параметры захвата и состояния петель. В шести номинальных случаях оба приёмника дают 0/576 ошибок полезных символов; отрицательные каналы дают ошибки, а испорченные ожидания вызывают UVM_FATAL. Внутренний SQNR измеряется отдельно от ошибок захвата.

При физической проверке устранены длинные пути от памяти к DSP, через широкое округление/ограничение и через управляющие сигналы. Таблицы читаются синхронно, выборка банков и арифметика разделены регистрами. Целевая частота и ограничения не ослаблялись. Текущая версия RX прошла Vivado на 100 МГц с setup/hold +0.138/+0.008 нс; приёмка Quartus продолжается. Результаты TX и общих блоков обновляются на том же снимке.

Контракт, схема и команды — в [BPSK_RTL.md](BPSK_RTL.md). Полная отметка пилота требует завершения обоих вендоров. Входная скорость подтверждается внутри кадров 768/2048 символов, с паузой очистки FIR 32 такта; повторные короткие кадры на полной скорости не подтверждены. Это физическая IO-обвязка, без проверки готовой платы.

Работа остановлена на сегодня по указанию пользователя. Quartus RX прерван на map, завершённой физической приёмки обоих вендоров нет. Текущий Vivado RX: +0.138/+0.008 нс. Свежая полная вещественная регрессия прошла за 116.04 с, включая 212 Python-тестов; BPSK и общая RTL-симуляция также PASS. Обновление физических доказательств выполнено частично. Точный порядок продолжения сохранён в BPSK_RTL.md.

## 2026-10-09: проверка выходной перегрузки

Продолжена контрольная точка 2026-10-08 из RTL_TODO.md. С агентами Qwen в pi и MiMo в OpenCode проверены вчерашние изменения генераторов и завершены случаи OM-LSA/OQPSK. Агенты работали в отдельных копиях; их расчёты и векторы проверены координатором. Сверка 74 конфигураций и 325 файлов с c1ddfb0 подтвердила сохранность прежних строк и конфигураций. Уточнены ограничения FIR, PFB, FSK TX, STFT analysis и OQPSK TX/loopback, исправлено число транзакций в отчётах.

Добавлена общая команда tools/run_streaming_rtl.py без синтеза. Все 15 наборов Python/Verilator/Questa прошли, включая отрицательные контроли, обе полярности сброса, остановы и сбросы внутри транзакций. Полная переносимая регрессия прошла за 133.24 с: 308 Python-тестов, 24 модема в Octave, 96 кадров UVM и 445328 комплексных сравнений; 40 типизированных случаев и 80 UVM-транзакций с 32084 сравнениями. Свежесть исходников и артефактов подтверждена require_pass.

Обновлена RTL_COVERAGE.md: обе границы полной шкалы проверены на 19 числовых потоках. У четырёх остальных полная шкала недостижима по конструкции; у отдельных конфигураций также действуют числовые ограничения. Значение на границе не тождественно срабатыванию ограничения, поэтому для FIR добавлено отдельное поле output_clipping. Синтез остаётся на паузе. Следующий этап — внутренние счётчики насыщения и сценарии захвата/срыва синхронизации. Подробности и свидетельства — [RTL_OVERLOAD.md](RTL_OVERLOAD.md) и [rtl_overload_results.json](rtl_overload_results.json).

## 2026-10-12: входные протоколы, диагностика насыщений и слежения

Продолжена контрольная точка 2026-10-09 с агентами в opencode, pi и kilo. Агенты работали в отдельных копиях `build/rtl/continuation_20261012/`; журнал и завершение каждого контролировались. OpenCode был перезапущен после зависания расчёта и подготовил входные проверки 15 тестбенчей. Pi подготовил счётчики FIR/FFT; координатор исправил подсчёт симметричной отрицательной границы FFT и добавил монитор фактического ограничителя FIR. Kilo исследовал сценарии синхронизации; повторные ошибки эталона потребовали остановки и завершения работы координатором.

В 15 тестбенчах теперь 65 протокольных контроллеров: 23 входа данных, 17 конфигураций и 25 выходов. Драйверы удерживают valid до ready; проверяется X полезных данных при valid. Корректные передачи и сброс ожидающей передачи проходят, 14 намеренных нарушений отвергаются. FIR непосредственно сверяет события ограничения с моделью во всех сценариях; FFT сохраняет модельную диагностику ступеней. Costas после скачка 30° восстанавливается до 0.073° RMS, Gardner после временной задержки +2 отсчёта — до 0.00357 RMS символов. Отключённые петли на тех же входах не проходят критерии восстановления; новые транзакции проверены бит в бит в Questa.

Итоговая регрессия: все 15 потоковых наборов Python/lint/Questa, протокольные отрицательные контроли, 318 Python-тестов переносимой регрессии, 24 модема Octave, 96 кадров UVM, типизированные наборы и контракты — PASS. Переносимая регрессия заняла 135.03 с. Свежесть исходников и артефактов подтверждена `require_pass`. 345 векторных файлов сохранены байт в байт; в четырёх sync-файлах прежние строки сохранены префиксом. Обновлены RTL_COVERAGE.md и RTL_TODO.md; подробности — [RTL_TRACKING_AND_PROTOCOL.md](RTL_TRACKING_AND_PROTOCOL.md) и [rtl_tracking_results.json](rtl_tracking_results.json).

Далее: непосредственные счётчики ступеней FFT, диагностика остальных блоков, OQPSK и внутренние индексы. Синтез остаётся на паузе. Агенты завершены/остановлены; коммит не создавался.

## 2026-10-12 (продолжение): насыщения ступеней FFT и OQPSK

Продолжен TODO с агентами opencode, pi, kilo. Запуски имели лимит 600 с и остановку после 180 с отсутствия активности. OpenCode подготовил ожидания и тесты FFT; после ошибочного определения каталога Git первый запуск остановлен и перенесён в /tmp, правки перепроверены. Pi подготовил прототип монитора; pi и Kilo остановлены по лимиту, незавершённые части исправлены и доведены координатором.

В fft_tb подключён симуляционный монитор ограничителей всех ступеней, с метками реальных операций через SDF-линии и конвейер. Разогрев/flush и прогрев перед сбросом исключены, X в реальной операции отвергается. Все строки счётчиков совпадают с Python; 70 нормальных прогонов и четыре новых отрицательных контроля прошли. Точные симметричные границы отдельно проверены допустимыми 18-битными словами. Арифметический FFT RTL и числовая модель неизменны.

Добавлен чистый OQPSK-сигнал с известным CFO и скачком 30° на символе 300; прежние входные строки сохранены. Начальный захват проходит; EVM возрастает примерно до 23% и восстанавливается до 1.9–2.0%, тогда как без обратной связи остаётся 33–39%. Два размера кадра и все RTL-сценарии проверены. Это выход из допуска слежения, не доказательство битовых ошибок или cycle slip.

Полная проверка: 15/15 потоковых наборов Python/lint/Questa, протокольные отрицательные контроли, 321 Python-тест переносимой регрессии, Octave, 96 кадров UVM, типизированные наборы и контракты — PASS (159.71 с для переносимой регрессии). Свежесть подтверждена require_pass. 40 прежних векторных файлов не изменились; десять OQPSK-файлов сохраняют прежние строки префиксом. Отчёт — [RTL_FFT_SATURATION.md](RTL_FFT_SATURATION.md), свидетельства — [rtl_fft_saturation_results.json](rtl_fft_saturation_results.json).

Следующие пункты: диагностика насыщений остальных блоков, внутренние индексы/адреса и расширенные сценарии синхронизации. Синтез остаётся на паузе; коммит не создавался.

## 2026-10-12 (DSP): ограничители, FIFO и неверный знак notch

Продолжен TODO с агентами opencode, pi и kilo в отдельных /tmp-копиях. OpenCode завершил beam/Alamouti, pi — notch/Kalman и нашёл ошибку округления. Kilo остановлен из-за неверного размещения проверок внутри DUT и проверки несбрасываемых данных; координатор исправил проверки границ и добавил MMSE. Все запуски имели лимит времени.

Добавлен SatTrace со счётом вычислений и общий симуляционный контроллер фактических ограничителей. 140 прогонов пяти блоков, 12 отрицательных контролей событий/вычислений и шесть проверок неверных индексов — PASS. Общий контроллер проверен на 72-битных словах: четыре положительных и 12 отрицательных случаев, включая X. FIFO учитывают одновременные pop/push и две записи на пару Alamouti/MMSE. Контроли индексов идут через тот же проверяющий код, что реальные значения.

В notch исправлено прибавление смещения округления в недостаточной 25-битной ширине. Исходный модуль независимо собран из Git с теми же стресс-векторами: −131072 вместо +131071 на выходе 4, затем NUMERIC fatal. Исправление расширяет промежуточное значение до 26 бит, сохраняя интерфейс и задержку. Стресс зарегистрированных коэффициентов маркирован отдельно; четыре прежних стабильных профиля не изменены.

Итоговый снимок: 15/15 потоковых наборов, контроллеры протокола/насыщений, 335 Python-тестов переносимой регрессии, 24 Octave-модема, 96 кадров UVM, типизированные наборы и контракты — PASS (136.41 с). Свежесть подтверждена require_pass; 78 прежних векторных файлов не изменились. Документы — [RTL_DSP_SATURATION.md](RTL_DSP_SATURATION.md) и [rtl_dsp_saturation_results.json](rtl_dsp_saturation_results.json).

Далее — насыщения адаптивных фильтров и других оставшихся блоков, их внутренние индексы. Синтез остаётся на паузе; физический тайминг исправленного notch ещё не проверен. Коммит не создавался.

## 2026-10-12 — продолжение: LMS/NLMS/RLS

Добавлена прямая сверка внутренних ограничителей адаптивных фильтров: предсказание/ошибка, обновление и выдача весов; у RLS также u/q/gain, верхний треугольник g·conj(u) и P. Независимые формулы исключают зеркальные записи и неиспользуемые отводы. Новый 128-битный монитор проверен на ±2^100, масках, точных границах и X. Семь конфигураций каждого фильтра дают 140 проходящих запусков; восемь отрицательных контролей счётчиков и четыре контроля индексов отклонены. RTL-ядра и 52 прежних файла векторов сохранены.

OpenCode остановлен после 180 с без событий, Kilo превысил время аудита, pi остановлен по лимиту 600 с после подготовки RLS. Координатор проверил его файлы и завершил недостающую работу. Все процессы остановлены; журналы — build/rtl/continuation_20261012_adaptive/.

Полная регрессия: 15/15 потоковых наборов, 340 Python-тестов, 24 модема Octave, 96 кадров UVM, типизированные наборы и контракты — PASS (153.96 с). Свежесть подтверждена require_pass. [Отчёт](RTL_ADAPTIVE_SATURATION.md), [свидетельства](rtl_adaptive_saturation_results.json). Далее — ограничения и индексы оставшихся DSP-блоков. Синтез на паузе; коммит не создавался.

## 2026-10-12 — продолжение: спектральные блоки

Для PFB, OFDM, STFT и OM-LSA добавлены счётчики операций и событий фактических ограничителей. Ожидания строятся по целочисленным моделям до ограничения, а SystemVerilog-наблюдатели читают операнды в реальных состояниях DUT. В OM-LSA проверены девять скалярных ограничителей и вложенный ISTFT; в PFB и OFDM ступени встроенного FFT пока остаются отдельной задачей. Добавлены проверки FIFO, сроков жизни кольцевых буферов, индексов окна, префикса и адресов таблиц. Инъекции событий, числа операций и индекса обязаны завершать симуляцию с ошибкой.

Новые сценарии дают 228 событий ограничения фаз PFB, полный циклический префикс OFDM, точные границы спектрального ограничителя STFT и тихий участок с последующей полной комплексной шкалой OM-LSA. Для минимального STFT созданы две недостающие ROM-таблицы; RTL-арифметика восьми основных ядер не менялась. Проверка базового снимка подтвердила неизменность 100 прежних файлов векторов. Всего прошли 234 нормальных запуска четырёх runner, 16 отрицательных контролей ограничителей, восемь контролей границ и расширенный общий монитор (8 положительных, 32 отрицательных).

Pi завершил узкую задачу PFB за 176 секунд, OpenCode — OFDM за 356 секунд; Kilo остановлен по жёсткому лимиту 150 секунд без отчёта. Его незавершённую часть дописал координатор. Статусы и журналы сохранены в build/rtl/continuation_20261012_spectral/. Полная регрессия: 15/15 потоковых наборов, 347 Python-тестов, 24 модема Octave, 96 кадров UVM, типизированные наборы и контракты — PASS. [Отчёт](RTL_SPECTRAL_SATURATION.md), [свидетельства](rtl_spectral_saturation_results.json). Синтез остаётся на паузе; коммит не создавался.

## 2026-10-12 — продолжение: встроенные FFT PFB/OFDM

Отдельные необязательные счётчики в моделях PFB и OFDM передаются в их вызовы `fft_fixed`. Ожидания разделены по направлению, ступени, ветви суммы/разности и компоненте. Общий тестовый наблюдатель переносит метки действительных операций через линии задержки и четыре ступени конвейера `fft_r2sdf`, исключает разогрев и flush, читает значения до ограничения, а число кадров получает с внутреннего интерфейса FFT. Инъекции неверного числа событий и вычислений отвергаются в обоих блоках и при обеих полярностях сброса.

В 128 нормальных запусках PFB и OFDM получено 40 реальных событий ограничения обратного FFT передатчика OFDM на шести наборах векторов. Прямые FFT PFB/RX дали ноль событий при ненулевом, независимо сверенном числе вычислений. 75 прежних текстовых файлов PFB/OFDM побайтно сохранены; четыре основных RTL-ядра не менялись. Pi завершил ожидания PFB за 146 секунд, OpenCode — OFDM за 262 секунды. Kilo остановлен по лимиту 150 секунд без аудита; его незавершённый результат не использовался. Журналы и статусы — build/rtl/continuation_20261012_embedded_fft/.

Полная регрессия: 15/15 потоковых наборов, 352 Python-теста, 24 модема Octave, 96 кадров UVM, типизированные наборы и контракты — PASS. [Отчёт](RTL_EMBEDDED_FFT.md), [свидетельства](rtl_embedded_fft_results.json). Далее — FSK/LDPC и другие оставшиеся ограничители, сценарии синхронизации и точность/SER. Синтез остаётся на паузе; коммит не создавался.

## 2026-10-12 — продолжение: границы FSK и ограничители LDPC

Для FSK добавлен наблюдатель активных адресов таблицы шагов, индекса `t<n`, сдвига округления и резервирования FIFO; арифметического ограничителя в этом блоке нет. Для LDPC целочисленная модель и RTL-наблюдатель сверяют реальные операции и события двух ограничителей `v` и `post`; монитор границ проверяет также декодер и GF(2)-кодер. Новый отдельный стрессовый случай вызывает 57 положительных событий `v` при 675 вычислениях в режиме 0; прежние конфигурации проверяют отсутствие событий `v` при ненулевых вычислениях. Инъекции неверного события, числа операций и индекса отвергаются.

FSK прошёл 60 нормальных запусков, LDPC — 70. Старые 83 текстовых файла векторов совпали побайтно; хеши четырёх RTL-ядер не изменились. Pi подготовил модель LDPC, OpenCode — проверки FSK, Kilo завершил независимый аудит; все три процесса завершились штатно, журналы и статусы — `build/rtl/continuation_20261012_fsk_ldpc/`.

Полная регрессия: 15/15 потоковых наборов, 356 Python-тестов, 24 модема Octave, 96 кадров UVM, типизированные наборы и контракты — PASS. [Отчёт](RTL_FSK_LDPC.md), [свидетельства](rtl_fsk_ldpc_results.json). Далее — другие блоки, сценарии синхронизации, точность/SER и MMSE для `n>2`. Синтез остаётся на паузе; коммит не создавался.

## 2026-10-12 — продолжение: ограничитель ошибки Gardner

В `sync_fixed.timing` добавлен необязательный счётчик значения ошибки до симметричного ограничения `±2³⁰`. Текстовые векторы четырёх конфигураций не менялись: 24 прежних файла совпали побайтно. Эта же ошибка наблюдается непосредственно в состоянии `GRADIENT` RTL перед записью `clipped`; счётчики операций и обоих знаков сверяются с моделью. Получены `55/70`, `0/1`, `0/0`, `5/9` положительных/отрицательных событий при `2100`, `160`, `120`, `100` вычислениях. Добавлены проверки индекса записи, активных тегов интерполяции и числа выходов; инъекции ошибок события, числа операций и границы отклонены.

Целевой набор прошёл 40 нормальных сценариев с обеими полярностями сброса. Pi завершил модель за 210 секунд. OpenCode остановлен по лимиту 420 секунд без изменений файлов, Kilo — по лимиту 150 секунд без аудита; их результаты не использовались. Статусы и журналы — `build/rtl/continuation_20261012_sync_grad/`.

Полная регрессия: 15/15 потоковых наборов, 359 Python-тестов, 24 модема Octave, 96 кадров UVM, типизированные наборы и контракты — PASS. [Отчёт](RTL_SYNC_GRADIENT.md), [свидетельства](rtl_sync_gradient_results.json). Далее — cycle slip и область захвата, точность/SER и MMSE для `n>2`. Синтез остаётся на паузе; коммит не создавался.

## 2026-10-13 — поиск Questa через симлинки

Исправлен остаточный дефект `questa_paths()`: при штатной вложенной раскладке Siemens `bin/vsim → ../vco/bin/vsim` и дополнительном симлинке `vsim` в PATH функция выбирала `vco` вместо корня установки. Pi воспроизвёл ошибку на временном макете и изменил выбор корня; координатор проверил diff, два новых сценария и существующие защитные тесты: 16 passed, 73 subtests passed. На установленной Questa функция возвращает `questasim/bin` и `questasim/verilog_src/uvm-1.2`. Поведение `run_hdl.py` и следующая задача по cycle slip остаются на рассмотрении.

Kilo предложил сценарий +100° для выявления ложного захвата Costas в соседнем квадранте. Координатор проверил гипотезу численно, добавил измерение истинной ошибки и ошибки по модулю 90° в Python, а также контроль без скачка. OpenCode читал `run_hdl.py`, но завершился по лимиту 90 секунд без заключения; его неполный аудит не принят. Отдельный сценарий пока не включён в Questa-векторы.

Проверка после изменений: 25 целевых тестов и 73 подслучая, затем общий Python-набор из 360 тестов — PASS. Все запущенные процессы агентов завершены.

## 2026-10-13 — синхронизация, точность, MMSE3 и скорость

Продолжен TODO с кураторами opencode, pi и kilo в изолированных /tmp копиях. Внешние CLI запускались с пределами простоя/общего времени; зависшие попытки остановлены, ошибки Open WebUI не выдавались за результат. Работу завершали кураторы, координатор принимал diff и запускал проверки в основном проекте. Read-only OpenCode аудит actual-DUT SER завершился самостоятельно за 84 секунды. Отказ автоматического разрешения Kilo ранее не обходился.

Costas получил реально наблюдаемые RTL фазы для скачка 100°, шумового участка, глубокого замирания с частотным возмущением и 12 точек фазы/CFO. Проверяются истинная ошибка и остаток по модулю 90°, другой квадрант и контроли отключённой петли/повреждённой записи. Это конечные сценарии; полная граница захвата остаётся открытой. 26 старых sync файлов совпали побайтно; два сохраняют старые строки префиксом и получили по 31700 строк.

Полные fixed/floating тракты PSK/QAM, MSK/GMSK, OQPSK/MRC дали 62 кадровых случая; отдельно измерены Costas/Gardner, FFT/FIR. Исследование FFT WIDTH на 75 случаях выбрало 19 для объявленного номинального диапазона, но все ширины клиппируют coherent inverse stress. 48 фактических RTL-проверок кандидата и WIDTH20 прошли; default не изменён. В FFT и MMSE модели теперь проверяют входные форматы портов.

Добавлен функциональный MMSE3 с точными кофакторами и 128-битным определителем, 80 обычными сценариями, отрицательными контролями и отказами конфигурации/неполной тройки. MMSE2 исправляет отрицательный/нулевой сдвиг, тихое усечение веса, оборачивание счётчика конфигурации и частичную пару. FIR/MMSE/LMS/RLS получили 28 самостоятельных протокольных сценариев: конфигурация и данные одновременно, открытый кадр, задержанный выход/веса, неверная длина cfg и восстановление.

90 измерений реальных тактов FIR/FFT отделяют burst, середину кадра, периоды между кадрами и полный вывод хвоста. FIFO FIR теперь `max(8,nextpow2(DEPTH+3))`; для T41/LANES64 выдача длинных кадров выросла 0.6154→0.9999 отсчёта/такт. Внутри кадра каждый такт принимаются вход и выход; межкадровый входной rate 0.9950 из-за хвоста. Физические 100 MHz не измерены. Отчёт покрытия теперь читает только обычные артефакты свежего последнего PASS и исключает старые/инъекционные журналы.

Приёмка снимка 12:10 UTC: 468 Python-тестов, 24 Octave-модема, 96 поведенческих UVM кадров, типизированные наборы/контракты, общие RTL/UVM, 16/16 потоковых наборов и полные BPSK/PSK/QAM/SIMO/CPM RTL — PASS. Actual-DUT SER сохранён в 170 сценариях, 1212 кадрах, 789504 payload symbols; 28 записей без payload имеют undefined SER. 32 модемных отрицательных контроля завершились rc13. Дополнительно подтверждены 42 старых FFT, 140 LMS/RLS, 242 BPSK, 40 FIR и 25 MMSE текстовых векторов. Свежесть источников и всех артефактов проверена. [Сводное свидетельство](rtl_continuation_20261013_results.json).

Следующий этап уже выполняется: полноценный UVM пилот BPSK RX, независимая точность LMS/NLMS/RLS и регистровая история вложенного FIR в OQPSK. Синтез остаётся на согласованной паузе; коммит не создавался.

## 2026-10-13 — UVM пилот и адаптивная точность

Добавлено полноценное UVM окружение одного BPSK RX: sequence/sequencer/driver/monitor/scoreboard/env/test. Все события монитора взяты из pre-edge clocking inputs; очередь эталона публикуется до входных данных. Независимый Kilo аудит воспроизвёл ложный PASS ранней версии при позднем m_valid=X. Исправленный monitor отвергает X в controls и valid data; тот же bind дал PROTOCOL/rc13 без summary. Аудит задержался на 986 секунд в approval tool до запуска симулятора; координатор прервал ожидание и направил after probe через уже разрешённый испытательный runner.

Восемь обычных и восемь отрицательных UVM прогонов проходят обе полярности. Сброс активного noisy frame3 реально отбрасывает 96 принятых payload symbols и 13 ошибок: 3360 checked + 480 discarded = 3840 expected. Четыре полных кадра после replay сохраняют SER 58/2304. NUMERIC, отдельное повреждение truth при неизменённой numeric колонке и actual valid/ready X дают rc13 без summary. Этот пилот теперь запускается автоматически из run_tests all/hdl; расширение на остальные модемы остаётся в TODO.

Для LMS/NLMS/RLS независимо сравниваются полные fixed/floating петли на общих once-quantized x/d. Девять обычных случаев дают prediction SQNR 79.49–91.48 дБ, discrepancy RMS 1.25–2.58×10⁻⁵ signal units, exported-weight RMS 0.87–1.75×10⁻⁵ coefficient units, clamp events 0. Три clipping stress дали 2/2/10 событий и не признаны качественной nominal обработкой. Метаданные операций и измеряемых интервалов проверяются независимо.

В OQPSK добавлен наблюдатель вложенного bpsk_fir: живые регистровые history cells, принадлежность кадру, восьмитактные valid/last stages и CE pauses. По 31.56/31.74 млн компонентов TX/RX проверены при каждой полярности; динамических RAM/ROM в этом FIR нет. 35 прежних файлов векторов и ядра сохранены. Контроли активного индекса и paused valid отвергнуты.

Приёмка снимка 13:04 UTC: 483 Python-теста, 24 Octave-модема, поведенческие UVM/типизированные наборы/контракты, реальные восемь UVM RX сценариев, общие RTL, 16/16 потоковых наборов и полные BPSK/PSK/QAM/SIMO/CPM — PASS. Повторены 48 FFT WIDTH и 90 actual cycle measurements. Parent evidence сохраняет 280 дочерних артефактов. [Свидетельства](rtl_continuation_20261013_uvm_results.json).

Следующие пункты выполняются в /tmp: MMSE/beam/Alamouti precision, actual rates Costas/Gardner/LMS/RLS и nested CORDIC/divider checks с zero-energy bypass. Внешние CLI с backend errors остановлены; кураторы продолжают самостоятельно. Синтез остаётся на согласованной паузе; коммит не создавался.

## 2026-10-13 — полная точность DSP и границы конфигурации

Приняты независимые MMSE2/3/beam/Alamouti, notch/Kalman/FSK, LDPC/GF(2) и PFB/STFT/OFDM/OM-LSA precision отчёты. Clipping и случаи ниже SQNR бюджета сохранены явно. Для спектральных трактов 29 из 46 случаев выполняют 45 dB, 17 не выполняют; PASS измерения не подменяет качество. LDPC аналитическая phi исправлена после независимого аудита; максимум ошибки на 11 точках 7.11×10⁻¹⁵. Согласованные подмены bits/BER/ранней остановки и FSK решений/корреляций теперь отклоняются.

Измерены 84 потока Costas/Gardner/LMS/NLMS/RLS. Costas исправлен с II=9 на II=8 без изменения дискретной модели; 12 directed protocol cases проверяют конфигурацию и непрерывные границы кадров. У Kalman исправлены старая gain FIFO и приоритет конфигурации; у Gardner — начальная позиция concurrent singleton LAST и восстановление после invalid configuration. Notch сохранён. Before12 дефектов и8 coherent controls сохранены; after32 probes и exact24/8 mandatory parent gates проходят. Helper отверг32 повреждённых отчёта.

OQPSK теперь проверяет также реальные21 CE-ступень вложенного CORDIC и64 итерации divider, округление/знак и zero-energy bypass. Два zero-energy сценария отделены от обычных20; новые negative controls требуют Fatal нужного класса, ненулевой rc и отсутствие завершённого PASS.

Приёмка свежего снимка: 523 Python-теста, 24 Octave-модема, поведенческий и реальный RX UVM, типизированные алгоритмы/контракты, общие RTL, полные BPSK/PSK/QAM/SIMO/CPM и16/16 streaming suites — PASS. Повторены48 FFT WIDTH proofs,90 FIR/FFT rate runs и84 sync/adaptive rate runs. Проверены источник и все артефакты, сохранены прежние векторы. [Сводное свидетельство](rtl_continuation_20261013_precision_results.json).

Questa FSE2025.2 из Quartus25.1std компилирует маленький SV, но vsim возвращает rc4 при выдаче лицензии; вне sandbox подтверждено то же. Статус UNAVAILABLE, полная FSE приёмка остаётся открытой. Синтез на согласованной паузе; коммит не создавался.

Следующие пункты продолжаются в отдельных копиях: полноценный BPSK TX UVM, actual MMSE3 rates и независимый аудит конфигурации FSK/LDPC/GF(2). Внешние CLI без прогресса останавливаются через90сек; кураторы завершают работу самостоятельно.

## 2026-10-13 — финальный статус перед продолжением завтра

Приняты BPSK TX UVM, QPSK/SIMO и PSK8 feedback RX UVM, MMSE3 actual rates и исправления конфигурации FSK/LDPC/GF(2). Независимый аудит закрыл invalid-H recovery; после допустимой замены удержанный LLR принимается ровно один раз, sticky error сохраняется. Все 79 прежних FSK/LDPC TXT сохранены. Полные parent gates содержат точные 36/38 случаи и все child hashes.

Финальная приёмка: 546 Python-тестов, 24 Octave-модема, 16/16 streaming, расширенный UVM (34 обычных/48 отрицательных), полный BPSK/PSK/QAM/SIMO/CPM и общие RTL — PASS. Свежие WIDTH48, FIR/FFT90, sync/adaptive84 и MMSE3 rates8 прошли; источник и все артефакты проверены. [Сводное свидетельство](rtl_continuation_20261013_final_results.json).

По просьбе пользователя работа остановлена после этого пункта. [Статус и первый шаг завтра](CURRENT_STATUS.md); draft floating SER сохранён в docs/resume_20261014, не интегрирован и не имеет приёмки. Подагенты завершены, активных внешних CLI нет. Синтез не запускался, коммит не создавался.

## 2026-10-15 — UVM передатчика OQPSK

По просьбе пользователя просмотрен проект и продолжен следующий доступный пункт: [UVM передатчика OQPSK](RTL_OQPSK_UVM.md). Общее окружение BPSK TX вынесено в `rtl/tb/modem_tx_uvm.svh`, обёртки задают DUT, ширину метки и хвост. Новый набор сверяет реальные входные/выходные рукопожатия, обе компоненты, TLAST и независимую геометрию `8*N+36`. Пять кадров из 1/2/33/192/768 меток также сравнены с независимым floating TX. Десять обычных сценариев и восемнадцать отрицательных контролей охватывают обе полярности, паузы, backpressure и сброс ожидающего/терминального выхода. Parent `run_tests all/hdl` требует полного набора и проверенных артефактов.

В `midreset` до сброса приняты 111 отсчётов и 16 меток; отброшены 6069 ожидаемых отсчётов и 752 оставшиеся метки. В `outreset` приняты 299 отсчётов кадра из 33 меток; удерживаемый последний отсчёт с TLAST отброшен, затем все пять кадров повторены полностью. Оба баланса независимо проверяются парсером. Повреждение I/Q, старшего входного бита, X controls/data и held data даёт требуемый Fatal с ненулевым rc без успешной summary.

Общая регрессия `python3 tools/run_tests.py --suite all`: PASS, 2026-10-15T08:26:32Z, 767.99 с. 562 Python-теста, 24 Octave-модема и поведенческий UVM; RTL UVM — 122 обычных/264 отрицательных BPSK/PSK/QAM и 10/18 OQPSK TX, 42 отказа float-валидатора. Прошли 13 типизированных workspace, 28 отклонений входных контрактов и девять precision-отчётов. Проверены 1340 исходников и 1251 артефакт. [Свидетельство](rtl_oqpsk_uvm_20261015_results.json). Набор из десяти корневых раннеров целиком в этот день не повторялся.

Следующий пункт — UVM приёмника OQPSK, затем CPM и блоков раздела 5. Синтез остаётся на согласованной паузе. Продолжение сохранено в рабочем дереве, коммит не создавался.

## 2026-10-15 — OQPSK/CPM RX, CPM TX, FFT и первая DSP UVM-матрица

По просьбе продолжать без остановок реализованы полноценные UVM OQPSK/MSK/GMSK RX с независимым floating SER (36/112), MSK/GMSK TX (20/36), FFT всех семи планов (84/154) и OFDM/STFT/FIR всех 34 планов (356/728). Общее окружение считает реальные принятые конфигурации, входы/выходы, частичные и терминальные сбросы. Directed отказы требуют правильного Fatal и ненулевого rc. В GMSK обнаружен и исправлен перенос старых CORDIC data-токенов в следующий pass1; монитор требует индексы 0..1041 каждого захвата. Before/after и исходные векторы сохранены в `resume_20261015/gmsk_backpressure/`.

Общая приёмка c: PASS 2026-10-15T11:06:47Z за 1664.79 с, 588 Python-тестов, 24 Octave-модема, UVM 628/1312, 51 отказ float-валидатора. Отдельно PASS всех 16 streaming suites и CPM с lint; проверены 1354 исходника и 6736 артефактов. [Свидетельство](rtl_uvm_continuation_20261015c_results.json). Предыдущий пробный b сохранил FAIL из-за класса детекции held-data FFT; ready в инъекции теперь удерживается в нуле, полный FFT повторён успешно. Параллельные PSK/QAM профили используют независимые библиотеки; root runner при исключении закрывает свои RUNNING-отчёты с исходным снимком.

После сохранения c перенесены ещё 66 DSP-конфигураций, всего 100. Целевые пробы PFB/notch/Kalman/FSK/beam/Alamouti/MMSE2/3/Costas/Gardner/OM-LSA проходят. Сохраняются знаковые/беззнаковые физические поля, в том числе метки и 32-битные фаза/позиция. Atomic cfg без cfg_last и отсутствие error отмечаются как неприменимые соответствующие пробы. Полная матрица 1102/2442 запущена отдельно; до завершения статус расширения не PASS. Оставшиеся адаптивные/кодирующие UVM готовятся вне зафиксированных исходников. Синтез на паузе, коммит не создавался.

## 2026-10-15 — полный DSP UVM и PSK/QAM TX, измерения задержек

Матрица из 100 DSP-конфигураций прошла 1102 обычных/2442 отрицательных, общий Python runner — 589 тестов ([d](rtl_dsp_uvm_20261015d_results.json)). Затем добавлены 14 LDPC/GF(2) и 14 LMS/NLMS/RLS конфигураций. Адаптивные фильтры проверяют два независимых физических потока — prediction/error и итоговые веса; `woutreset` удерживает последний вес и сбрасывает ровно одну ожидающую передачу. Signed16 posterior LDPC и hard bit сохранены отдельно, исходные матрицы и stress не менялись.

Общая приёмка e завершена PASS 2026-10-15T12:13:21Z за 2585.5 с: 590 Python-тестов, UVM модемов/FFT/DSP 1710/3992, 51 float-валидатор. DSP-часть — 128 конфигураций и 1438/3408. Отдельно прошли 16/16 streaming, CPM и общие RTL-примитивы с lint. Проверены 1354 исходника и 12146 артефактов. [Свидетельство e](rtl_uvm_continuation_20261015e_results.json).

Аудит выявил непокрытые параметрические TX общего bpsk_tx. Все 13 PSK/QAM профилей прошли изолированные UVM 130/234 и независимое сравнение floating TX (максимум 8.93e-5, бюджет1e-4). Счётчик покрытия меток расширен до unsigned64, чтобы учитывать QAM64 bit63. Прежние BPSK/OQPSK/MSK/GMSK TX прошли проверку совместимости. Пять новых Python-тестов и обязательный parent gate включены в root.

Добавлены независимые VCD-измерения всех 128 DSP при обеих полярностях: значения читаются до фронта, NBA применяется после. Родитель пересчитывает задержки/интервалы по трассам, не доверяя итоговому JSON. Пять тестов отвергают пропущенный clk, неправильный период, unknown controls, неполные кадры и подменённые метрики. Целевые OFDM/FIR/MMSE3/LMS/RLS/LDPC/Gardner проходят; измерения показывают ограничения прежних последовательных архитектур. Подробности — [DSP pin rates](RTL_DSP_PIN_RATES.md).

Общая приёмка f нового снимка запущена: ожидаются 600 Python-тестов, UVM1840/4226 и256 VCD-измерений. До завершения статус снимка не PASS. Синтез остаётся на паузе; коммит не создавался.

## 2026-10-15 — приёмка f завершена

Общая функциональная приёмка f завершена **PASS** `2026-10-15T13:25:50.541530+00:00` за 2466.31 с: 600 Python-тестов, 24 Octave-модема, 1840 обычных/4226 отрицательных UVM модемов/FFT/DSP и 51 отказ float-валидатора. Дополнительно выполнены 256 VCD-измерений всех 128 DSP-конфигураций с повторной числовой проверкой. Все 16 streaming suites, CPM и общие RTL-примитивы с lint прошли. Проверены 1359 исходников и 13660 артефактов. [Сводное свидетельство](rtl_uvm_continuation_20261015f_results.json); архив — `build/acceptance_20261015f/`.

Полноценное UVM существующих модемных TX/RX и DSP закрыто в TODO. [PSK/QAM TX](RTL_PSK_TX_UVM.md), [DSP UVM](RTL_DSP_UVM.md), [фактические интервалы/задержки и CSV](RTL_DSP_PIN_RATES.md). Измерения сохраняют ограничения последовательных архитектур; передача каждый такт внутри конечного кадра не подменяет непрерывную среднюю скорость. Синтез остаётся на согласованной паузе. Открыты систематический выбор разрядностей, архитектуры под требуемый темп, оставшиеся модемные производные параметры, общий n×n MMSE и физическая приёмка. Продолжение 15 октября сохранено в рабочем дереве, коммит не создавался.

## 2026-10-15 — модемный темп и предельные кадры, приёмка g

Общая функциональная приёмка g завершена **PASS** `2026-10-15T15:18:35.094780+00:00` за 2324.65 с: 608 Python-тестов, 24 Octave-модема, 1840 обычных/4226 отрицательных UVM модемов/FFT/DSP и 51 отказ float-валидатора. Все 16 streaming suites, CPM и общие RTL-примитивы с lint прошли. Повторены 256 DSP VCD-трасс и добавлены 68 обязательных модемных трасс с проверкой захвата/буферов. Отдельно прошли 68 граничных TX/RX-прогонов с максимальным кадром 2048 символов и 10 отказов проверяющего TX-скрипта. [Свидетельство g](rtl_modem_rates_20261015g_results.json); архив — `build/acceptance_20261015g/`.

[Темп, задержки и буферы всех 17 TX и 17 RX](RTL_MODEM_PIN_RATES.md) опубликованы с CSV на 612 строк. Максимальный OQPSK-кадр полностью занимает буфер 16512 отсчётов; MSK/GMSK имеют запас 32, PSK/QAM — 160. Внутри TX-кадра подтверждены 8 тактов на символ и один комплексный выход за такт. Ограничения RX, последовательных DSP и межкадровые паузы сохранены явно. Следующие пункты TODO: систематический выбор внутренних разрядностей, архитектуры и внешние FIFO для непрерывного темпа, общий n×n MMSE, физическая приёмка. Синтез остаётся на согласованной паузе. Изменения сохранены в рабочем дереве, коммит не создавался.

## 2026-10-16 — параметризованный MMSE N×N

Закрыт функциональный пункт «общий n×n MMSE». Точный подход `mmse3` (кофакторы и определитель) не масштабируется: разрядности растут линейно с N. Поэтому `mmse_n` нормирует матрицу Грама по наибольшей диагонали и ведёт исключение Гаусса в Q30 с действительными пивотами и одним округлением на операцию. Первая версия брала обратную величину пивота из 24-битного `norm_reciprocal`; при cond(H) ≈ 40 ошибка весов доходила до 7·10⁻⁴. Переход на точный `fxp_divide_seq` снизил её до 2·10⁻⁶ ценой более длинной конфигурации (22549 тактов при N = 8).

При первом запуске Questa выход FIFO содержал X: запись `fifo[FW'(int'(fifo_tail)+row)]` в цикле не выполнялась начиная с третьей N-ки. Индекс переписан как `fifo_tail + FW'(row)`. Контроль `s_last` на втором отсчёте при N = 2 оказался легальным концом N-ки, поэтому он заменён проверкой на отсчёте N−2 и выполняется при N ≥ 3. Итог: `tools/run_mmse_n.py --suite all` PASS. 400 нормальных прогонов, 100 отрицательных, 58 отказов, lint N = 2…8, 9 Python-тестов. Подробности — [RTL_MMSE_N.md](RTL_MMSE_N.md).

Общая функциональная приёмка после добавления `mmse_n` завершена **PASS** `2026-10-16T13:47:31Z` за 2378.43 с. Те же четыре корневых раннера, что в приёмке g: 617 Python-тестов, 24 Octave-модема, UVM 1840/4226 и 51 отказ float-валидатора; потоковые наборы 17/17, CPM, общие RTL. [Свидетельство](rtl_mmse_n_20261016_results.json), архив — `build/acceptance_20261016/`. Работа 15–16 октября закоммичена.

## 2026-10-16 — задержка петель обратной связи

Обзор показал, что задержки петель уже заложены в RTL и Python бит в бит; не хватало проверки устойчивости. `tools/loop_delay_study.py` измеряет крутизну детекторов на самих моделях (скачок фазы, задержки или амплитуды после преамбулы при разомкнутой петле), строит характеристические полиномы по точному порядку обновлений и прогоняет приёмники по задержкам 1…64. Неожиданная находка: у OQPSK крутизна равна 0.52 вместо 1, потому что угол в момент перехода второй ветви часто упирается в ограничение 0.5 рад. Первая версия искала предельную задержку по корням полиномов степени в тысячи и работала больше 10 минут; поиск по запасу фазы с проверкой корней у границы занимает секунды. Первые сценарии оказались слишком мягкими: без ошибок даже у порога, так как ОСШ в `channel` задаётся на отсчёт. Их пришлось откалибровать по каждому приёмнику. Итог — [RTL_LOOP_DELAY.md](RTL_LOOP_DELAY.md).

## 2026-10-19 — сокращение задержки OQPSK и проверка полного пути ошибки

Продолжено исследование петель: задержка OQPSK уменьшена с 10 до 8 символов. В RX и Costas введён общий параметр `LOOP_DELAY`; границы кольца ошибок дают диапазон 1…16. Битоточная модель принимает отдельный аргумент `loop_delay`, и исследование больше не меняет глобальную настройку OQPSK. Монитор хранит ошибки по полным номерам символов независимо от кольца DUT, проверяет готовность до запроса и точное значение при чтении. Контроль порчи завершается с `[FEEDBACK]`; неправильные параметры — с `[PARAMETER]`.

Измерение показало 45 разрешённых тактов от запроса zI к памяти до записи ошибки. Прежняя оценка 27 относилась только к части тракта и не задаёт минимальную задержку всей петли. Генератор запросов ждёт готовности ошибки. Парные серии используют общую преамбулу и одинаковые входные файлы при D = 8 и 10; на 3456 полезных символов фазовый шум дал 7 против 12 ошибок, пороговый канал — 17 против 15. Без пауз время серии выросло на 2.5%; прежний предел ожидания входа проходит. Границы D = 1 и 16 проверены с паузами, без заявления их входного темпа.

Приёмка изменения **PASS** `2026-10-19T09:51:14Z`: 624 Python-теста, 10 независимых отчётов (включая 2184 кадра исследования петель), нативные Questa 34/28, UVM OQPSK/MSK/GMSK RX 36/112, чистый lint. [Сводное свидетельство](rtl_oqpsk_delay_20261019_results.json) содержит хэши 1369 исходников и 574 артефактов; отчёты и журналы сохранены в `build/acceptance_20261019_oqpsk/`. Полная многотульная приёмка 16 октября остаётся исторической; новый физический тайминг не проверялся. Синтез на согласованной паузе, коммит не создавался.

## 2026-10-19 — точные границы и выбор аккумулятора FIR

Продолжена задача подбора внутренних разрядностей. `fir_widths.py` перебирает четыре угла signed18 диапазона для каждого коэффициента и складывает точные интервалы обеих компонент. RTL-проверка `ACC_WIDTH` вычисляет те же границы сдвигами и сложениями/вычитаниями при конфигурации. Для большинства штатных наборов получены 35–36 бит вместо прежних 39–45; при слишком большой норме загруженных коэффициентов возникает sticky error до приёма входа. Прежний default сохранён как контроль. Дробная точность и выходная арифметика прежние; произведения и дерево пока не сокращались.

Существенная граница — добавка округления в `sat18`. Для одного коэффициента 0.5 сырые суммы помещаются в signed34, а прибавка 65536 к максимальной сумме уже переполняется. Поэтому подбор требует 35 бит, а RTL отклоняет 34. Отрицательная полная шкала комплексных коэффициентов проверяет дополнительный знаковый разряд. Монитор сырых сумм сравнивает их с независимой NumPy convolution до округления и clipping. Четыре специальных угловых кадра действительно достигают аналитических экстремумов каждой компоненты.

Первый интеграционный запуск прошёл все числовые RTL-случаи, но проверка сохранённого JSON различала исходные tuple и прочитанные list. Формат нормализован, добавлен JSON roundtrip в тесты. Итоговые прогоны повторены на неизменных исходниках; прежние журналы сохранены отдельно. Чистый итог **PASS** `2026-10-19T10:33:02Z`: 635 Python-тестов, 11 отчётов, 220 RTL-прогонов ширины и 62260 сырых комплексных сумм, 42 проверки защит/повторной конфигурации/сброса и два отрицательных контроля. Прежние FIR 80/6 плюс восемь протокольных случаев проходят; все восемь FIR UVM-конфигураций дали 96/208. Stream-такты выбранной и прежней ширины совпадают, lint чистый.

Документ — [RTL_FIR_WIDTHS.md](RTL_FIR_WIDTHS.md), [свидетельство](rtl_fir_widths_20261019_results.json) проверяет 1373 исходника и 995 артефактов; архив — `build/acceptance_20261019_fir_widths/`. Нативный FIR runner автоматически требует полную ширинную матрицу и защиты; общий Python runner выполняет аналитический этап и тесты. Синтез остаётся на согласованной паузе, ресурсы и физический тайминг уменьшенных ширин не заявляются. Коммит не создавался.

## 2026-10-19 — завершение компактного дерева FIR

При продолжении найден незавершённый вариант дерева с отдельными ширинами Re/Im на каждом уровне. Проверены точные границы: signed18×signed18 требует signed36; разность двух произведений помещается в signed36, а сумма требует signed37 из-за положительного предела `2^35`. Каждый уровень добавляет один бит. Компактное дерево включено по умолчанию, прежнее равномерное доступно с `COMPACT_TREE=0` для парного контроля. При 64 полосах объявлено 9511 вместо 10922 бит регистров дерева; это расчёт RTL, без утверждения о физических ресурсах.

Независимый монитор получает произведения и суммы каждого узла из исходных файлов коэффициентов и входа, задерживая эталон до нужной ступени. Он проверяет также фактические ширины узлов. Матрица расширена случаем 64×64 с мнимой суммой `2^41`, сравнением обоих деревьев и отрицательными контролями `[PRODUCT]`, `[TREE]`, `[ACCUMULATOR]`. Первый запуск Questa внутри sandbox завершился SIGSYS при компиляции; проверка повторена вне sandbox с разрешения пользователя.

Итог **PASS**, `2026-10-19T11:21:26Z`: 636 Python-тестов, 11 отчётов, 480 числовых RTL-прогонов, 46 проверок защит, шесть отрицательных контролей, 155480 сырых комплексных сумм, 18941480 комплексных узлов и 39028320 вещественных произведений. Stream-такты всех пар совпадают, lint чистый. Прежняя FIR-регрессия 80/6 плюс восемь протокольных случаев и UVM восьми конфигураций 96/208 прошли. [Свидетельство](rtl_fir_tree_20261019_results.json) содержит 1374 исходника и 1271 артефакт; отчёты, журналы и скрипт сводки — `build/acceptance_20261019_fir_tree/`.

Синтез на согласованной паузе; полная многотульная приёмка всех модемов/17 потоковых наборов 16 октября остаётся исторической. Следующие задачи — внутренние разрядности остальных блоков и архитектуры/внешние FIFO для непрерывного темпа. Коммит не создавался.

## 2026-10-19 — точные разрядности полифазных аккумуляторов PFB

Продолжен выбор внутренних ширин. Каждая фаза PFB содержит не более `ceil(TMAX/M)` вещественных signed18 произведений. Точный верхний предел — `ceil(TMAX/M)·2^34`; нижний — `ceil(TMAX/M)·(−2^34+2^17)`. Default `ACC_WIDTH=36+max(LOG2TMAX−LOG2M,0)` представляет оба предела и добавку округления 4096, а ширина на бит меньше не представляет положительный экстремум. Для M=64, TMAX=256 получены 38 вместо 44 бит, на 768 объявленных бит аккумуляторов меньше. Прежняя ширина допустима явно; ограничения входов/коэффициентов, дробные форматы и протокол не менялись. Физические ресурсы не оценивались.

Новый монитор пересчитывает обе сырые суммы каждой фазы по исходным файлам до насыщения. К восьми штатным геометриям добавлены два full-scale случая с TMAX=256 и случай TMAX<M; они достигают обеих точных границ. Матрица проверяет обе ширины, обе полярности, пять сценариев сбросов/пауз, одинаковое число тактов и отказы параметров. Гейт встроен в `run_pfb.py`, а аналитический отчёт и тесты — в общий Python runner.

Первые интеграционные запуски выявили две ошибки нового скрипта: относительный путь к векторам из каталога симуляции и `onbreak`, возвращавший rc13 на штатном `$finish`. Путь нормализован, положительный и отрицательный `.do` разделены. Запуски Python/UVM, начатые до изменения скрипта, были отклонены проверкой исходного снимка и повторены; их журналы сохранены отдельно. Итоговая приёмка **PASS**, `2026-10-19T11:59:14Z`: 643 Python-теста, 12 отчётов, 220 сравнительных RTL-прогонов, 44 отказа параметров, два отрицательных контроля и 142160 сырых комплексных сумм фаз. Прежние PFB 80/12 и UVM восьми конфигураций 96/208 прошли; lint чистый. [Свидетельство](rtl_pfb_widths_20261019_results.json) содержит 1378 исходников и 1050 артефактов; архив — `build/acceptance_20261019_pfb_widths/`.

По просьбе пользователя подключён Codex 6 Luna для read-only ревью. За 31 с он проверил доказательство ширины, signed-пути и независимость монитора; дефектов не нашёл, 14 целевых тестов и 36 подслучаев прошли, файлы не менял. [Сравнение с историческими Pi/OpenCode/Kilo](AGENT_EFFICIENCY_20261019.md) использует все 21 сохранившихся статуса 12 октября, с хэшами и оговоркой о разных задачах/лимитах. Оценка не выдаёт частоту rc0 за качество кода и не сравнивает стоимость без токенов/цен.

Синтез на согласованной паузе; последняя полная многотульная приёмка 16 октября историческая. Следующие работы — внутренние ширины остальных блоков, архитектуры и внешние FIFO для непрерывного темпа. Коммит не создавался.

## 2026-10-19 — произведения и кольцо ISTFT overlap-add

Сокращены default ширины `stft_synthesis`: произведения signed41 вместо42, аккумуляторы 41/42/43 вместо44 при R=N/HOP=1/2/4. Выход FFT симметрично ограничен ±(2^23−1), поэтому даже любое signed18 окно даёт `|u*W|<=2^40−2^17`. Кольцо очищается при INIT и выдаче HOP ячеек после каждого кадра; DRAIN завершает записи до EMIT, противодавление не допускает нового кадра до выдачи. Поэтому до очистки живы не более R вкладов. Для N=256 объявленный объём кольца уменьшен на 1536/1024/512 бит. Масштабирование, округление, FFT, порты и прежние значения параметров сохранены; физических ресурсов не заявляем.

Независимый эталон строится по исходным спектрам, integer inverse FFT и overlap-add по абсолютным индексам. Сверяется каждое произведение, предыдущая/новая сумма записи RAM и прочитанный аккумулятор до scaling. Матрица охватывает семь штатных геометрий и три отрицательных окна, достигающие обеих точных границ при R=1/2/4, несколько оборотов кольца, начальные/финальные области, паузы и сбросы. Проверяются две ширины произведения, два аккумулятора, обе полярности и четыре сценария, одинаковое число тактов, отказы параметров и три типа отрицательных контролей.

Интеграция обнаружила ошибки тестового набора: hex-окно для `$readmemb` и отсутствующую reciprocal ROM новой геометрии. Окно/reciprocal теперь генерируются локально в binary, добавлен тест их декодирования/полноты. Шесть коротких signed-window проверок прошли до повторения полной матрицы. Лишний знаковый бит контрольного PRODUCT_WIDTH=42 при ACC_WIDTH=41 получил локальное исключение UNUSEDSIGNAL с пояснением; raw-монитор продолжает сверять все 42 бита. Исторические неудачные запуски и прогоны, начатые до изменения исходников, не принимались как PASS; итоговые наборы повторены на неизменном снимке.

Итог **PASS**, `2026-10-19T12:31:44Z`: 651 Python-тест/13 отчётов, 320 сравнительных RTL-прогонов, 80 отказов параметров, шесть отрицательных контролей, 279040 комплексных записей и 162656 чтений. Все парные такты совпали. Прежние STFT 56/8, OM-LSA 50/8 и UVM семи ISTFT/пяти OM-LSA конфигураций 120/270 прошли; lint прошёл с описанным локальным исключением. [Свидетельство](rtl_istft_widths_20261019_results.json): 1382 исходника, 1559 артефактов; архив — `build/acceptance_20261019_istft_widths/`. Документ — [RTL_ISTFT_WIDTHS.md](RTL_ISTFT_WIDTHS.md).

Luna подключён как независимый read-only ревьюер. Его первое заключение неверно прочитало MIN FFT как −2^23; основной агент указал на численное определение `1−2^23`, после чего Luna исправил доказательство. Далее агент верно проверил signed-срезы/выравнивание мониторов и выполнил 13 целевых тестов; ошибки ROM обнаружила Questa в основном потоке. [Оценка эффективности](AGENT_EFFICIENCY_20261019_ISTFT.md) учитывает и пользу, и ошибки, без рейтинга по одному времени ответа. Пользователь отдельно попросил учитывать уровень агента при раздаче задач: для Luna — конкретные проверяемые участки; архитектура, интеграция и приёмка остаются у основного агента.

Синтез на согласованной паузе. Полная многотульная приёмка всех модемов/17 потоковых наборов 16 октября остаётся исторической. Следующие пункты — остальные внутренние ширины, архитектуры/внешние FIFO непрерывного темпа. Коммит не создавался.

## 2026-10-19: исправление переполнения энергии NLMS16 — PASS

В ходе подбора разрядностей обнаружена реальная ошибка: энергия 16 комплексных signed18 отсчётов может достигнуть 2^39, переполняя прежний unsigned39 регистр. Сумма с unsigned34 EPS тоже требует запаса. [Исправление LMS/NLMS](RTL_LMS_ENERGY.md) задаёт `ENERGY_WIDTH=36+LOG2N`: 36/37/38/39/40 бит при N=1/2/4/8/16. При N=16 ширина увеличена, поиск старшего бита расширен соответственно; недостаточная ширина отклоняется. Integer-модель адаптации не менялась.

Старая версия сохранена и воспроизводит ошибку при обеих полярностях сброса: на 17-м выходе предсказание (−131072,−131072) вместо (4,−178). Исправленная версия проходит побайтно те же входы и эталоны. Независимый монитор заново строит историю по исходным файлам, проверяет энергию, сумму с EPS, показатель, адрес/результат reciprocal ROM и сдвиг. Отдельно проверено переполнение суммы с EPS без переполнения самой энергии.

Приёмка **PASS**, `2026-10-19T13:07:33.531366+00:00`: **659 Python-тестов и 14 отчётов, 240 сравнительных RTL-прогонов, 48 отказов параметров и 6 отрицательных контролей**; 11580 проверок энергии и 11580 reciprocal. Такты парных ширин совпали; прежние LMS/NLMS 70 обычных/8 отрицательных, 6 протокольных сценариев и UVM всех семи конфигураций 84/294 прошли, lint чистый. [Свидетельство](rtl_lms_energy_20261019_results.json): 1386 исходников, 1166 артефактов; архив `build/acceptance_20261019_lms_energy/`.

Luna успешно выполнил узкие read-only задачи по целочисленным границам и 512 значениям reciprocal. [Оценка с историческим сравнением Pi/OpenCode/Kilo](AGENT_EFFICIENCY_20261019_LMS.md) учитывает различие задач и отсутствие измерения стоимости. Архитектура, интеграция и приёмка остались у основного агента, согласно предпочтению пользователя учитывать уровень агента.

Синтез на согласованной паузе, физические ресурсы/частота не измерялись. Полная приёмка проекта от 16 октября историческая. Продолжается подбор остальных ширин, архитектур и FIFO для непрерывного темпа. Коммит не создавался.

## 2026-10-19: энергия коэффициентов beamformer — PASS

Продолжение подбора ширин выявило переполнение энергии при 32 и более каналах: прежние unsigned40 не вмещают сумму `M*2^35` для полного signed18 диапазона. [Исправление beamformer](RTL_BEAM_ENERGY.md) задаёт `ENERGY_WIDTH=36+LOG2M` и передаёт её в reciprocal: 36…42 бита для M=1…64. Недостаточная ширина отклоняется. Модель и алгоритм reciprocal не менялись.

Старая версия сохранена: при M=32 полная энергия превращается в ноль, DUT поднимает error; при 63 коэффициентах в массиве 64 ненулевой остаток даёт первый выход (66593,0) вместо (32768,0). Обе ошибки воспроизведены при двух полярностях. Исправленный RTL проходит побайтно те же конфигурации, входы, выходы и ожидаемые насыщения. Независимый монитор сверяет каждое накопление энергии и целочисленно вычисленные reciprocal/shift; монитор насыщений расширен для LOG2M>4.

Приёмка **PASS**, `2026-10-19T13:27:53.083273+00:00`: **666 Python-тестов и 15 отчётов, 220 сравнительных RTL-прогонов, 44 отказа параметров и 6 отрицательных контролей**; 4520 проверок энергии и 220 reciprocal. прежние beamformer/Alamouti 50 обычных/8 отрицательных и все 10 UVM-конфигураций (120/260) прошли, lint чистый. Без пауз интервалы потока парных ширин совпали; время конфигурации зависит от ширины последовательного делителя и записано отдельно. Для default 36/41/42 бит измерено 67/72/73 такта от последнего коэффициента до наблюдения norm_done.

[Свидетельство](rtl_beam_energy_20261019_results.json): 1390 исходников, 1184 артефактов; архив `build/acceptance_20261019_beam_energy/`. Первоначальная ошибка объявления счётчика нового монитора исправлена до итоговой регрессии; все 11 коротких проверок повторены. Luna верно выполнил узкую read-only задачу по границам энергии и интерфейсу reciprocal; [оценка с историческим сравнением Pi/OpenCode/Kilo](AGENT_EFFICIENCY_20261019_BEAM.md) не выдаёт разные задачи за одинаковый benchmark.

Синтез на согласованной паузе, физические ресурсы/частота не измерялись. Полная приёмка проекта от 16 октября историческая. Следующие работы — остальные внутренние ширины, архитектуры и FIFO непрерывного темпа. Коммит не создавался.

## 2026-10-19: точные ширины Alamouti — PASS

В [Alamouti](RTL_ALAMOUTI_WIDTHS.md) default SUM_WIDTH/ENERGY_WIDTH/SCALE_WIDTH уменьшены с 39/40/64 до **38/37/61**. Сумма y0.re достигает +2^36, энергия двух комплексных коэффициентов — 2^36; после масштабирования получается до 2^59 и добавляется не более 2^43 перед округлением. Все границы доказаны для полного signed18 диапазона; модель не менялась. Прежние размеры доступны для контроля, недостаточные отклоняются.

Независимый монитор сверяет каждое накопление энергии, reciprocal/shift, все 16 произведений и четыре сырые суммы/масштабированных значения на пару до clipping. Шесть наборов достигают всех точных минимумов/максимумов сумм и масштаба 2^59, включают единичную энергию и номинальные коэффициенты. Пять раскладок проверяют новую/прежнюю и возврат каждого отдельного параметра к старому значению; обе полярности, паузы и три вида сброса охвачены. Сохранённый старый RTL прошёл 12 сравнений; шесть новых коротких проверок прошли до полной матрицы. Все десять файлов векторов/ожиданий на набор побайтно сохранены.

Приёмка **PASS**, `2026-10-19T13:45:17.130787+00:00`: **672 Python-теста и 16 отчётов, 300 сравнительных RTL-прогонов, 72 отказа параметров и 12 отрицательных контролей**; проверены 96000 сырых произведений, 24000 сумм и 24000 масштабированных значений, 600 энергий и 300 reciprocal. Парные интервалы данных без пауз совпали; конфигурация reciprocal занимает 68 вместо 71 такта от последнего коэффициента до наблюдения norm_done. Повторные матрица энергии beamformer 220/44/6, прежние native 50/8 и все 10 UVM-конфигураций 120/260 прошли, lint чистый.

[Свидетельство](rtl_alamouti_widths_20261019_results.json): 1394 исходника, 1689 артефактов; архив `build/acceptance_20261019_alamouti_widths/`. Luna выполнил узкий арифметический перебор и доказательство scaled-width, основной агент — интеграцию/приёмку. [Оценка с историческим сравнением Pi/OpenCode/Kilo](AGENT_EFFICIENCY_20261019_ALAMOUTI.md) учитывает три инструментальных вызова первого этапа, включая один пустой, и отсутствие достоверного измерения стоимости/времени.

Синтез на согласованной паузе, реальные ресурсы и частота не измерены. Полная приёмка проекта от 16 октября историческая. Далее — остальные внутренние ширины, архитектуры и FIFO непрерывного темпа. Коммит не создавался.

## 2026-10-19: точные ширины сумм RLS — PASS

В [RLS](RTL_RLS_WIDTHS.md) default PRED_WIDTH/DOT_WIDTH/Q_WIDTH теперь `53+LOG2N`, `63+LOG2N`, `67+LOG2N` вместо 64/128/128. При N=1…16 это 53…57, 63…67, 67…71 бит. Существующий общий тракт предсказания/строки матрицы и число тактов сохранены. Недостаточные ширины отклоняются; старые доступны для контроля. Знаменателю по-прежнему нужны signed51; модель и остальные 128-битные этапы не менялись.

На траекториях монитор строит историю из исходных файлов и 128-битно пересчитывает суммы по фактическим ограниченным w/P/u операндам DUT; независимыми копиями адаптивных состояний они не объявляются. Полные выходы/веса сверяются с неизменённой fixed-моделью, девять групп насыщений и границы проверяются отдельно. Тест произвольных кодов через force без фронтов такта достигает предельных сумм, в том числе 2^65 и 2^69 при N=16; их достижимость из reset адаптации не утверждается. Проверяются пять раскладок, обе полярности, паузы и три вида сброса.

Приёмка **PASS**, `2026-10-19T14:30:42.090523+00:00`: **678 Python-тестов и 17 отчётов, 400 сравнительных RTL-прогонов, 96 отказов параметров, 20 направленных прогонов и 12 отрицательных контролей**. Сверены 21200 компонентов сырых предсказаний, 21200 регистров, 118800 компонентов матричных сумм, 10600 hᴴu и 10600 знаменателей. Направленно проверены ещё 640/3968/320 компонентов prediction/matrix/quadratic. Все парные такты и сырые пики совпали; прежние native 70/8, 6 протокольных сценариев и все 7 RLS UVM-конфигураций 84/294 прошли, lint чистый.

[Свидетельство](rtl_rls_widths_20261019_results.json): 1399 исходников, 1646 артефактов; архив `build/acceptance_20261019_rls_widths/`. Сохранённый старый RTL прошёл 16 коротких сравнений, новый — восемь траекторий и пять арифметических конфигураций до итоговой регрессии; все 14 файлов на каждый из восьми наборов сохранены побайтно. Первоначальный тестовый конфликт владельцев always_ff исправлен заменой процедурных записей на force, исходный журнал сохранён.

Luna верно выполнил ограниченный расчёт целочисленных границ/округления и явно указал границу между произвольными кодами и reset-достижимостью. [Оценка с историческим сравнением Pi/OpenCode/Kilo](AGENT_EFFICIENCY_20261019_RLS.md) учитывает четыре вычислительных вызова и отсутствие измерения стоимости/времени. Интеграция и приёмка выполнены основным агентом.

Синтез на согласованной паузе; физические ресурсы и частота не измерены. Полная приёмка проекта от 16 октября историческая. Далее — остальные внутренние ширины, архитектуры и FIFO непрерывного темпа. Коммит не создавался.

## 2026-10-19: точные промежуточные обновления RLS — PASS

После коммита `46a2f61` продолжен [подбор ширин обновления RLS](RTL_RLS_UPDATES.md). GAIN/UPDATE/WEIGHT/PT/COV теперь **71/59/44/89/79** вместо 128 бит для каждого промежуточного выражения. Разность P−t явно signed47. Хранимые g40/w34/t46/P44, fixed-модель, общий тракт и число тактов сохранены. Переменное округление gain остаётся 128-битным; для 71-битного продукта используется проверяемый контракт нормированного R. Прежние размеры доступны для контроля, недостаточные отклоняются.

Монитор насыщений читает реальные входы ограничителей. Отдельный 128-битный пересчёт по ограниченным операндам DUT проверяет сырые продукты, фиксированное округление, сумму с весом и записи g/w/t/P, включая зеркала и мнимую диагональ. Состояния не объявляются независимой копией модели: полные выходы/веса сверяются отдельно с fixed-моделью. Force-тест без тактов проверяет углы операндов на N=1/16; достижимость этих кодов из reset не утверждается. На траекториях охвачены N=1/16, неполная история 3/4 и оба clamp-stress. Семь раскладок возвращают по одному параметру к 128 и все сразу; обе полярности, паузы и три вида сброса проверены.

Приёмка **PASS**, `2026-10-19T15:04:36.643311+00:00`: **684 Python-теста и 18 отчётов, 350 сравнительных RTL-прогонов, 100 отказов параметров, 8 направленных прогонов и 12 отрицательных контролей**. По 119280 компонентов проверены gain, g-регистры, произведения обновления, суммы с весом и w-регистры; 867160 компонентов PT и столько же t-регистров, 807520 компонентов ковариации и 1615040 записей P. Направленно проверены ещё 129280 значений. Сырые пики и парные такты совпали; повторные прежняя матрица сумм RLS 400/96/20/12, native 70/8, 6 протокольных сценариев и все 7 UVM-конфигураций 84/294 прошли, lint чистый.

[Свидетельство](rtl_rls_updates_20261019_results.json): 1404 исходника, 2195 артефактов; архив `build/acceptance_20261019_rls_updates/`. Все 14 файлов на каждый из пяти наборов совпали побайтно со сравнением сохранённого RTL. Короткая приёмка до итоговых прогонов: 10 старых сравнений, пять новых траекторий, два направленных теста и семь lint-раскладок.

Luna верно выполнил узкую арифметическую задачу, два инструментальных вызова; [оценка с историческим сравнением Pi/OpenCode/Kilo](AGENT_EFFICIENCY_20261019_RLS_UPDATES.md) не смешивает разные условия и не заявляет измеренную стоимость/скорость. Интеграция, ограничения переменного сдвига и приёмка выполнены основным агентом.

Синтез на согласованной паузе; физические ресурсы и частота не измерены. Полная приёмка проекта от 16 октября историческая. Следующие работы — остальные внутренние ширины, архитектуры и FIFO непрерывного темпа. Изменения этого этапа в рабочем дереве, новый коммит не создавался.

## 2026-10-20: точные промежуточные ширины LMS/NLMS — PASS

После коммита `d42b0dd` продолжен [подбор ширин LMS/NLMS](RTL_LMS_WIDTHS.md). Округление предсказания, ошибка, k·e с переменным округлением, регистры c и dl, сумма с весом перед sat34 и выдача весов теперь используют **53+LOG2N/19/46/45/63/58/35** бит вместо 64/64/64/47/65/64/64. Регистры произведений signed53 и суммы 53+LOG2N уже были точными: это доказано и проверено, но не сокращено. Хранимые w34/h18/e18/k28, энергия, fixed-модель, интерфейс и число тактов сохранены. Прежняя раскладка остаётся допустимым параметром, недостаточные ширины отклоняются `[PARAMETER]`.

Границы выведены из контракта конфигурации (1≤MU≤2^17, ROM 513…1024, k≤2^27, 1≤shift≤27+LOG2N) и полных кодов signed18/sat34; |c|≤2^43 достигается при пустой истории и EPS=512. Это интервалы независимых операндов: реальный NLMS |h·c| около 2^47 против доказанных 2^61, более узкая корреляционная граница не используется.

Монитор насыщений читает фактические входы ограничителей. Новый 128-битный монитор строит историю из исходных файлов, заново вычисляет reciprocal/сдвиг и проверяет каждую ступень и запись pr/sum/e/c/dl/w по реальным операндам DUT; независимая Python-трасса воспроизводит выходы/веса fixed-модели и все пики, которые должны совпасть в каждом прогоне. Force-тест без тактов проверяет углы интервалов на N=1/16, их достижимость из reset не утверждается.

Первая матрица выявила различие тактов с замороженным RTL в 414 прогонах с паузами — причина в тестбенче (новый монитор сдвигал seed `$urandom` блоков пауз). После переноса подключения монитора в конец модуля такты совпали во всех 540 прогонах.

Приёмка **PASS**, `2026-10-20T07:39:25Z`: **692 Python-теста и 19 отчётов, 540 сравнительных RTL-прогонов (6 наборов × 9 раскладок × 2 полярности × 5 сценариев), 168 отказов параметров, 8 направленных прогонов и 18 отрицательных контролей**. Наборы: LMS N=1/16, NLMS N=16, NLMS N=4 с тремя отводами, LMS clamp-stress весов и NLMS16 с границей c. Проверено по 9131400 компонентов произведений/h·c/dl/сумм с весом/записей w, по 1235880 сумм/предсказаний/ошибок/шагов/c и 33840 выдач. Замороженный RTL прошёл те же наборы (60 прогонов), векторы до/после побайтно совпали. Повторные энергия 240/48/6, native 70/8, 6 протокольных сценариев, все 7 LMS/NLMS UVM-конфигураций (392 записи) и 84 rate-прогона прошли; lint чистый.

[Свидетельство](rtl_lms_widths_20261020_results.json): 1409 исходников; архив `build/acceptance_20261020_lms_widths/`. Синтез на согласованной паузе: ресурсы и частота не измерены, умножители по ширине операндов не изменились. Полная приёмка проекта от 16 октября историческая. Изменения закоммичены в ветке worktree.


## 2026-10-26: ширины Gram и выходных сумм MMSE 3×3 — PASS

Продолжен [подбор разрядностей MMSE3](RTL_MMSE3_WIDTHS.md): арифметика Gram38 при прежнем хранении40, выходные суммы84 вместо85. Доказаны полные кодовые границы, прежние ширины доступны параметрами; fixed-модель, интерфейс и такты сохранены. Три подагента работали на high/medium/low по задачам доказательства, RTL и ревью. Интеграция и приёмка выполнены основным агентом.

[Приёмка](rtl_mmse3_widths_20261026_results.json) PASS: 723 Python-теста и 22 отчёта, 360 сравнительных RTL-прогонов, 8 направленных, 8 отказов параметров, 12 отрицательных контролей; 90 пар с исходным RTL и тестбенчем 1d22c17 совпали по выходам и тактам. Штатные MMSE3 80/20/12, UVM восьми конфигураций 96/208, восемь измерений темпа и строгий lint прошли. Архив build/acceptance_20261026_mmse3_widths/ содержит свидетельство для 1423 исходников и 1330 артефактов; хеши проверены. Синтез на согласованной паузе, физические ресурсы и частота не измерены. Далее — остальные стадии MMSE3, mmse_n и архитектуры непрерывного темпа. Коммит не создавался.


## 2026-10-26: параллельный этап конфигурации MMSE3 и аккумуляторов MMSE N×N — PASS

[MMSE3](RTL_MMSE3_CONFIG_WIDTHS.md): выражения adj/det/M используют 81/126/104 вместо 84/128/106 при прежнем хранении. [MMSE N×N](RTL_MMSE_N_WIDTHS.md): Gram 38…40 вместо 44 и выходные суммы 83+floor(log2 N), сужение последних на один бит при N=3,5,6,7. Эталонные модели, делители, FSM и интерфейсы сохранены. Три подагента high/high/medium параллельно выполнили RTL, независимые доказательства и проверочные runners; основной агент интегрировал и принял изменения.

[Приёмка](rtl_mmse_configuration_20261026_results.json) PASS: 746 Python-тестов и 24 отчёта; новые матрицы MMSE3 450/10/12/12 и MMSE N×N 400/20/40/60 (численные/направленные/отказы параметров/отрицательные). Все 90+150 пар с сохранённым RTL совпали по выходам и тактам, конфигурационные такты MMSE N×N также совпали. Штатные suites 80/20/12 и 400/100/58, UVM MMSE3 96/208, восемь измерений темпа и прежний sweep Gram/выходов прошли повторно. Архив build/acceptance_20261026_mmse_configuration/: 1433 исходника, 4908 артефактов, 16 отчётов; хеши проверены. Синтез остаётся на согласованной паузе, физические ресурсы и частота не измерены. Далее — масштабирование весов MMSE3 и остальные внутренние стадии MMSE N×N. Коммит не создавался.


## 2026-10-26: Pi/OpenCode и масштабирование/обновления MMSE — PASS

Завершены [масштабирование весов MMSE3 и A/B-обновления MMSE N×N](RTL_MMSE_SCALE_UPDATES.md): 145 вместо 156, произведения 83/121 вместо 84/122 и обновления 53/91 вместо 138/138. Хранимые состояния, fixed-модели, делители и такты сохранены; синтез на согласованной паузе.

По запросу пользователя запущены DeepSeek/Qwen в Pi/OpenCode, а также Kimi/GLM/MiniMax, без выбора Claude/Codex/ChatGPT/OpenAI. Не все ответы пригодны: неверные границы Qwen отклонены, DeepSeek/MiniMax приняты лишь в отдельно проверенной части, GLM недоступен, ряд OpenCode-ответов исчерпал лимит. Выход OpenCode за назначенный каталог и shell-команда выявлены по журналу; правка не применилась, результат отклонён. Последующий аудит запущен в /tmp с явными запретами shell/правок. Код и итоговое доказательство выполнены основным агентом, неподтверждённые изменения не переносились.

[Приёмка](rtl_mmse_scale_updates_20261026_results.json) PASS: 752 Python-теста и 25 отчётов, 1080 численных RTL-прогонов, 240 frozen-пар, 16 направленных, 20 отказов параметров, 28 отрицательных, 32 lint. Сверены 440496 сырых и 47152 направленных компонента. Штатные MMSE3/MMSE N×N, UVM 96/208 и 8 измерений темпа прошли. Архив build/acceptance_20261026_mmse_scale_updates/: 1440 исходников, 5258 артефактов, 13 отчётов, хеши проверены. Следующие работы — нормировка/обратная подстановка MMSE N×N и непрерывный темп. Коммит не создавался.


## 2026-10-26: нормировка и обратная подстановка MMSE N×N — PASS

Завершены [ширины нормировки и обратной подстановки](RTL_MMSE_N_NORM_BACK.md): **70/87/65/107/(106+clog2N)** вместо 138/138/112/112/112. Делитель 112 и его такты сохранены; аккумулятор теперь 107…109. Положительный мнимый продукт двух отрицательных кодов равен 2^105, поэтому 106 бит недостаточно. Для каждого префикса аккумулятора доказан минимум −2^101−t·2^105, t≤N−1. На смешанной старой/новой ширине lint выявил неиспользуемые старшие биты произведения: добавлена проверка полного кода перед сужением. Штатные результаты и такты сохранены.

Pi/OpenCode запускались с DeepSeek/MiniMax/Qwen, без Claude/Codex/ChatGPT/OpenAI, в отдельных Git-каталогах /tmp. DeepSeek принят только по проверенным границам 70/87/65; неверные побочные утверждения отклонены. MiniMax/OpenCode завершились по лимиту без итогового доказательства; Qwen предложил неверные 106 бит и был отклонён. Автоматические правки в проект не переносились. Итоговый RTL, доказательства и интеграция выполнены основным агентом.

[Приёмка](rtl_mmse_norm_back_20261026_results.json) PASS: 758 Python-тестов и 26 отчётов; 1470 численных RTL-прогонов, 210 frozen-пар, 98 направленных, 140 отказов параметров, 20 отрицательных и 49 lint. Сверены 1000188 сырых компонент и 410816 направленных проверок, выходы и такты совпали. Штатная MMSE N×N 400/100/58 прошла. Архив build/acceptance_20261026_mmse_norm_back/: 1445 исходников, 5892 артефакта, 3 отчёта; хеши проверены. Следующие работы — непрерывный темп, внешние FIFO и остальные внутренние ширины. Синтез на согласованной паузе; коммит не создавался.


## 2026-10-26: `axis_fifo` для конечных пачек и неизменный Costas II=8 — PASS

Завершена ограниченная задача буферизации конечных входных пачек перед неизменной петлёй Costas II=8. Однотактовый RAM FIFO сохраняет одновременные `pop+push` при полном состоянии. `DEPTH` включает зарегистрированный выход, а минимальная задержка от входного до выходного рукопожатия в пустом FIFO равна двум тактам. При `level==1` одновременные `pop+push` намеренно оставляют `read_word` нулевым и дают один выходной пробел. Направленный стимул исправлен, cycle-accurate монитор отдельно учитывает сбросы и требует фактического покрытия пробела; условие — `backlog_bubbles >= 1`, поскольку общее число пробелов не обязано равняться одному.

Аналитический бюджет принят для изначально пустого FIFO, отсутствия пауз приёмника, одного входного слова за такт, первого обслуживания в такте 2 и последующего обслуживания каждые восемь тактов. Пачки 16/64/128/512 требуют точных ёмкостей 14/56/112/448; для RAM выбраны глубины 16/64/128/512. При неограниченном входе один за такт очередь растёт на семь слов за восемь тактов, поэтому `finite_fifo_suffices=False`, а допустимый средний интервал поступления — не менее восьми тактов. Сквозной непрерывный темп `1/cycle` этим результатом не доказан.

Свежий focused набор `python -m unittest tests.test_axis_fifo` прошёл: восемь тестов. `python tools/axis_fifo_sweep.py --verify-rtl` завершился **PASS FIFO sweep: 142/142 jobs**: **20 unit / 96 integration / 18 negative / 8 parameter**, плюс **10 lint** без предупреждений для 11 общих верхних уровней. Unit-счётчики — 77476 принятых и 5324 отброшенных слова, integration — 17280 принятых слов. Replay проверил 463 артефакта. Опубликованное [свидетельство](rtl_axis_fifo_20261026_results.json) содержит хеши 1451 исходника и 463 артефактов; повторная проверка дала PASS и строки 20/96/18/8/10. Его `python_tests: 766` и `precision_reports: 27` сохранены как исторические метаданные, не как результаты нового полного прогона.

Полная проектная регрессия заново не выполнялась, другие конфигурации/нагрузки и физический тайминг не проверялись; синтез остаётся на согласованной паузе. Просмотрены все 24 незакрытых пункта `RTL_TODO.md`: общий пункт производных параметров остаётся открытым. Следующий рекомендуемый незаблокированный шаг — архитектура непрерывного темпа Costas с функциональной симуляцией и lint, без утверждений о Fmax. Размеры внешних FIFO для других условий, оставшиеся внутренние разрядности и физическая приёмка также остаются открытыми. Коммит не создавался.


## 2026-10-27: Costas с непрерывным темпом — PASS

Снят открытый вопрос «архитектура непрерывного темпа»: добавлен [RTL_COSTAS_STREAM.md](RTL_COSTAS_STREAM.md) и модуль `rtl/common/costas_stream.sv`, который принимает один отсчёт за такт при неизменной поразрядной арифметике. Те же операции, что в `costas_loop`: ротатор `bpsk_rotate` с таблицей cos, детектор `sign(re)·im − sign(im)·re`, произведения `K1·error`/`K2·error` (51 бит), округление half-up и 32-битный wrap, порядок «сначала `frequency`, потом `phase`». Меняется только размещение: ступени разнесены по конвейеру, поэтому ошибка отсчёта `n` входит в регистры петли перед отсчётом `n+10` — задержка **10 продвижений**, то есть 1.25 символа при SPS 8. `costas_loop` не менялся и сохраняет II=8 для покадрового захвата.

Эталон — новый `sync_fixed.costas_pipelined(x, gains, delay)` с той же рекуррентностью и задержкой в продвижениях; при `delay=1` он побитно равен старому `costas()` (отдельный тест). Общий `ce = !stall` замораживает все ступени, поэтому выходные паузы не меняют слов; входной пузырь — это пропущенное продвижение, и такой прогон сверяется с моделью, которой переданы логированные такты приёмов, а не с плотными векторами. Конфигурация принимается только при пустом конвейере, `s_last` только копируется — остановки потока нет. Кейсы: model 768, limit 512, slow 1200, corners 400 (оба края wrap), frames 203 (группы 37/1/128/37), off 64, каждый при обеих полярностях сброса.

Задержка отнимает запас по усилению — это измерено дважды: по корням полинома `z^10(z−1)^2 + a z(z−1) + b z^2` с `a = Kd·k1/2^15`, `b = Kd·k2/2^15` и по целочисленной модели. При измеренном наклоне дискриминатора `Kd = 32740 ≈ A√2` ρ = **0.9853/1.0583/0.9922** и запас по фазе **37.0°/−83.5°/65.2°** для (.08,.001)/(.3,.01)/(.02,.0001); модель локится до задержки **12/3/48** продвижений. Наибольшее `k1` при `k2 = k1/80`, устойчивое при задержке 10, — **0.1556**, запас **1.94×**. Набор (.3,.01) при такой задержке не захватывает, поэтому переименован в `limit` и оставлен как документированная граница применимости: арифметика на нём побитно верна, а высокоусиленный захват остаётся за `costas_loop`.

Приёмка `python3 tools/run_costas_stream.py --suite all` — **PASS**: модель/устойчивость/lock, lint `verilator -Wall` без предупреждений (модуль включён в общий список верхних уровней `tools/run_rtl.py`) и 12 наборов × 5 сценариев в Questa; каждое выходное слово `{re, im, phase, last}` сверено с моделью, отрицательный контроль `+INJECT_MISMATCH` даёт `** Fatal: [NUMERIC]` и код 13. Свидетельство `build/rtl/costas_stream/all_results.json` связывает **110 артефактов и 1455 исходников**, `require_pass` проверил хеши повторно. Три новых теста `tests/test_sync_fixed.py` (всего 16) проверяют сведение к `costas()`, семантику задержки/пузырей и отказ при некорректных аргументах.

Работа велась с подагентами в изолированных копиях `<local-tmp>`, режим только чтения. Codex/Terra независимо вывела ту же архитектуру и поправила форму полинома на `+b z^2` (RTL кладёт в фазу уже обновлённую частоту) — поправка принята; её числа воспроизвелись точно при её масштабе `2A = 46340`, но в проекте используется измеренный `A√2 = 32740`, поскольку точки созвездия лежат на ±45°, поэтому её ρ и максимальные задержки — верхние границы. Qwen подтвердил порядок обновления, `K1/K2`, правило `rnd` и различие двух округлений (`round_shift` в ротаторе, `f.rnd` в петле). Codex/Luna нашла две оговорки к прошлой приёмке `axis_fifo`: накопительный `backlog_bubbles >= 1` против ровно одного пузыря в directed-тесте и расхождение **40 слов** между `counts.unit_output_words = 77476` и суммой `popped = 77516`; артефакт не переписывался, расхождение зафиксировано текстом, доверять следует построчным данным.

### Второй круг: аудит приёмки и design review

Аудит уже записанных свидетельств (а не повторный прогон) нашёл один реальный дефект — в проверке, а не в RTL. Шлюз негативного контроля в `tools/run_costas_stream.py` требовал лишь *ненулевой* код возврата, поэтому утверждение «код 13» опиралось на текст `.do`-скрипта, а не на измерение: подошёл бы любой ненулевой код. Проверено вручную, что Questa действительно выходит с кодом 13 (`onerror {quit -code 13}`, `Errors: 1`), шлюз ужесточён до `vsim_exit_code == 13`, код пишется в `records.hdl.*.negative`, и приёмка **перезапущена целиком** новым раннером, а не перетегирована. Все функциональные числа обоих прогонов совпали побитно — изменилось только это поле, что само по себе служит проверкой детерминизма. `require_pass` пройден, 110 артефактов и 1455 исходников. Вторая правка по тому же аудиту — терминологическая: поле `stall_in.max_gap_advances` смешивало интервал между приёмами и длину пузыря (интервал 5 = 4 пропущенных продвижения), теперь это два поля — `max_accept_interval_advances` и `max_input_bubble_advances`, и документ говорит то же самое.

Остальные вердикты аудита не изменили статус: логи приёма (768 строк, строго возрастающие номера, `first_advance = 6`, максимальный интервал 5 тактов = пузырь в 4 пропущенных продвижения, без потери и повтора строк — похожий дефект «первая строка как заголовок» здесь отсутствует, чтение идёт без заголовка); совпадение всех чисел разделов 3–4 документа с JSON (12 наборов, ρ, запасы по фазе, maxD, `k1 = 0.1556`, запас 1.94×); общий `ce = !stall`, `cfg_ready` только при пустом конвейере, копирование `s_last`, достаточность 5 бит `busy` для измеренной задержки 10; отсутствие в `check_stalled` ветви, списывающей расхождение на модель. Оговорка про «сквозной тег» учтена в документе: у Terra тег должен был нести и `phase_used`, и `last`, а в написанном модуле фаза идёт отдельным 7-ступенчатым `phase_pipe`, тег ротатора 32-битный с `last` в младшем бите и нулями выше (`tag_ok`), так что две величины не смешиваются.

Design review готового модуля дал три `OK` — рукопожатия и `busy` (до backpressure максимум 8 принятых слов, переполнения нет, при `cfg_valid` вместе с `s_valid` при занятом конвейере конфигурация отвергается, а отсчёт принимается), сброс и непрерывность (`stall` не продвигает состояние частично; сброс при pending-выходе намеренно отменяет его — доставляющей системе нужен слив перед сбросом), арифметика (51-битные произведения, half-up `>>>16`, 32-битный wrap, порядок `frequency` → `phase` совпадают со `costas_loop`) — и один `RISK` без изменения статуса: это не семантически прозрачная замена `costas_loop`, поэтому живая переконфигурация требует останова входа и слива. Риск записан в заголовке модуля и в разделе 6 документа, то есть является контрактом, а не дефектом.

Физический тайминг не проверялся: путь фаза → ROM → умножители → регистры петли не ограничивался, синтез остаётся на согласованной паузе. Не проверены также захват вне трёх наборов коэффициентов, сквозной темп всей приёмной цепочки и размеры внешних FIFO. Полная проектная регрессия заново не запускалась. Изменения в рабочем дереве, коммит не создавался.


## 2026-10-29: BPSK захват acq1/acq3 — статус без приёмки Questa

Незакоммиченная работа по ускорению захвата BPSK ([BPSK_RTL.md](BPSK_RTL.md#захват-ускорение-acq1-2026-10-29)) доведена до локальной проверки: захват **A=677** (цель A≤686), делитель `STEPS_PER_CYCLE=2` (34 такта), покрытие сбросов в шести сценариях.

Проверено в этой сессии:
- pytest (захват, review, SER, PSK/BPSK/MRC, RTL-инструменты): **64 теста, 201 подтест — PASS**.
- Прямой численный scoreboard захвата на Verilator 5.050, все 14 профилей, обе полярности reset, 6 сценариев: **PASS**, повтор сегодня (`<local-tmp>`, 28 профилей-полярностей).

**Не проверено: Questa/UVM-приёмка acq3 не запускалась.** `tools/run_bpsk.py --suite all --output build/bpsk_all_20261029_acq3` упал на первом `vsim`: DPI-библиотека Questa не линкуется (встроенный gcc 10.3 Questa не читает системный glibc 2.39, `libc.so.6` с секцией `.relr.dyn`). Это ошибка окружения; RTL не причина. Каталог `build/bpsk_all_20261029_acq3` содержит `status=RUNNING` и не является приёмкой. Прежний незавершённый прогон сохранён как `build/bpsk_all_20261029_acq3_interrupted_0315`.

Не выполнено: Questa `run_bpsk --suite all`, `bpsk_rx_continuous_rate --backend questa`, `run_bpsk_uvm`, `run_oqpsk --suite all`; синтез и физический тайминг acq1; полная регрессия проекта. Коммит не создавался. Для перехода к приёмке нужно исправить окружение Questa (64-битный glibc RPM либо внешний линкер).

## 2026-10-29: приёмка ускоренного захвата BPSK acq3 — PASS

Ускоренный захват BPSK acq1/acq3 принят в Questa 2024.1. Прежний отказ DPI-линковки устранён явным `-dpicpppath /usr/bin/gcc` во всех вызовах трёх затронутых runner'ов; в новых отдельных сценариях захвата/делителя этого параметра не было. Настройка `DPI_CC` сохранена.

Полные `run_bpsk.py --suite all`, `run_bpsk_uvm.py --suite all --pilot rx --profile all`, `run_oqpsk.py --suite all`, проверка темпа с `--backend questa` и общий RTL lint — **PASS**. Прямой захват: 14 профилей × 6 сценариев × 2 полярности, **4368** точных результатов; делитель — **3089** операндов, оба режима и обе полярности; в общем BPSK-наборе **266** численных отрицательных контролей с кодом 13. UVM RX: **112** положительных сценариев и **250** отрицательных с кодом 13, включая SIMO/QAM. Полный `python3 -m pytest -q tests`: **636 тестов и 3382 подтеста PASS**.

Темп: все десять сценариев (4×192/768/2048 и две серии 16×192, включая `d=0`) при обеих полярностях дали **A=677**, **0 дополнительных блокировок**, межкадровый промежуток ровно **32 такта**. Побитно проверены 88 захватов и 36 352 выходных символа. Период обработки при очереди — 1559 тактов при минимальном интервале поступления 1568; обобщение на произвольный порядок длин остаётся аналитическим при готовом выходе.

Итоговое [свидетельство](rtl_bpsk_acquisition_20261029_results.json) и `build/acceptance_20261029_bpsk_acq3_gcc/results.json` прошли `require_pass`: **1473 исходника, 2276 артефактов**. Каталоги новых прогонов имеют суффикс `_20261029_acq3_gcc`; прежние незавершённые отчёты не переименовывались в PASS. Синтез и физический тайминг остаются на паузе; полная HDL-регрессия всего проекта не выполнялась. Коммит не создавался.

## 2026-10-29: внешние FIFO для повторных нагрузок и пауз — PASS

Продолжен первый открытый TODO по производным параметрам: добавлен независимый расчёт ёмкости `common/python/fifo_budget.py::costas_fifo_load` и проверка `tools/fifo_load_sweep.py` на production `axis_fifo` + неизменном Costas II=8. Четыре конечные нагрузки — перекрывающиеся пачки, пачки с полным сливом, разреженный вход после начальной пачки и пачки с остановками выхода — требуют **50 / 14 / 14 / 21** слов. При DEPTH−1 измерены **3 / 9 / 48 / 7** тактов блокировки, все данные сохраняются. Учтены зарегистрированный выход FIFO, двухтактовый старт, одновременные pop/push и реальная реакция Costas на ожидающий выход. Старые бюджеты одиночных пачек **14 / 56 / 112 / 448** сохранены.

Свежая Questa 2024.1: **16 положительных прогонов, 960 побитно точных выходных слов, 8 направленных отрицательных контролей с кодом 13**; обе полярности сброса, минимальная глубина и на слово меньше. Verilator: **12 конфигураций FIFO и 12 общих верхних уровней без предупреждений**. Весь зарегистрированный `run_tests.python_tests`-набор, включая 24 конфигурации модемов: **796 тестов PASS**. Новые тесты, модельный отчёт и обязательная RTL-матрица подключены к штатному runner.

Работу распараллелили на трёх подагентов: расчёт/независимые модельные тесты, RTL/раннер/проверки свидетельств, независимое ревью. Основной агент выполнил интеграцию и финальную приёмку после заморозки исходников; reviewer отдельно проверил свежие CSV/журналы через `verified_artifacts`. Все **104 файла RTL вне тестбенчей** побитно совпадают со снимком acq3. [Итоговое свидетельство](rtl_fifo_loads_20261029_results.json) и `build/acceptance_20261029_fifo_loads/results.json` прошли `require_pass`: **1477 исходников, 138 артефактов**. Расписания, таблица размеров и команда повторения — в [RTL_STREAM_RATES.md](RTL_STREAM_RATES.md#внешний-fifo-перед-costas-повторные-пачки-и-паузы-2026-10-29).

Граница результата — четыре заданных конечных расписания при изначально пустом FIFO и настроенном потребителе. Тест скорости даёт лишь необходимое ограничение 1/8 слова за такт, без обещания достаточности конечного FIFO при иных пачках или паузах. Общий TODO производных параметров для остальных DSP-архитектур/нагрузок остаётся открытым. Полная проектная HDL-регрессия не выполнялась; синтез и физический тайминг остаются на паузе. Коммит не создавался.

## 2026-10-29: FIFO перед LMS/NLMS с двумя независимыми выходами — PASS

Продолжен общий TODO производных параметров для остальных DSP: добавлены `fifo_budget.lms_fifo_load`, необходимая граница `lms_rate_bound` и `tools/lms_fifo_load_sweep.py`. FIFO WIDTH=72 несёт комплексные x и d вместе с TLAST. Учитываются ранний data output, продолжающаяся арифметика, отдельная выгрузка T весов и завершение обоих выходов перед следующим кадром. Режимы LMS/NLMS, T=1/3/8/16 и кадры `[1,7,8]` проверены на пяти конечных нагрузках: плотный вход, разреженный вход, паузы data, паузы weights, совместные паузы. Минимумы **3…15 слов**; при DEPTH−1 блокировка источника действительно достигается, данные и веса не теряются. Таблицы размеров, задержек и расписания — в [RTL_SYNC_ADAPTIVE_RATES.md](RTL_SYNC_ADAPTIVE_RATES.md#внешний-fifo-lmsnlms-кадры-и-два-выхода-2026-10-29).

Свежая Questa: **160 положительных прогонов, 2560 побитно точных результатов prediction/error, 3360 точных итоговых весов**, **10 направленных отрицательных контролей с кодом 13**, обе полярности сброса и минимум/минимум−1. Доказано фактическое удержание последнего веса и одновременных pending выходов; отдельный singleton-сценарий выдаёт все веса до первого data handshake. Verilator: **36 парных конфигураций FIFO/LMS, 72 lint-команды без предупреждений** и отдельно 12 общих верхних уровней. Полный зарегистрированный Python-набор с 24 конфигурациями модемов — **813 тестов PASS**. Старый FIFO/Costas-набор на текущем снимке также прошёл: 16 прогонов / 960 слов / 8 отрицательных контролей / 12 lint-конфигураций.

Необходимый идеальный период обработки повторяемого набора кадров равен `sum(8*N+T+1)`. Для `[1,7,8]` это **134/140/155/179 тактов** при T=1/3/8/16. Следовательно, повторение набора каждые 128 тактов не обслуживается никаким конечным FIFO даже при готовых выходах; прохождение границы не гарантирует достаточность FIFO для иных пачек и пауз.

Работа выполнена параллельно тремя подагентами: модель и независимые queue/FSM-тесты, RTL/раннер/проверки свидетельств, независимый review и аудит свежих артефактов. Основной агент интегрировал набор и провёл финальную приёмку после freeze. Исправлен повторный запуск общего HDL-runner: оба FIFO child получают уникальный явный `--output`, старые job directories и опубликованные свидетельства сохраняются. Все **104 production RTL-файла** и **138 артефактов предыдущей FIFO-приёмки** неизменны. [Новое свидетельство](rtl_lms_fifo_loads_20261029_results.json) и `build/acceptance_20261029_lms_fifo_loads/results.json` прошли `require_pass`: **1481 исходник, 960 артефактов**; `verified_artifacts` заново проверил все 160 CSV и отрицательные журналы.

Общий TODO размеров FIFO и задержек для RLS и остальных DSP остаётся открытым. Доказательство относится к пяти конечным расписаниям при постоянных корректных конфигурациях; полная проектная HDL-регрессия не выполнялась. Синтез и физический тайминг остаются на паузе. Коммит не создавался.

## 2026-10-29: расширение TODO по локальной RAG-библиотеке

По запросу пользователя изучены инструкции локальной RAG-системы в `local-library/MY_PROJECT`; выполнены каталогизация запросов, lexical search и чтение настоящего контекста через существующий CLI без изменения библиотеки или индекса. Три подагента исследовали фильтры/multirate, модуляцию/FEC и дополнительные аудио/антенные алгоритмы; основной агент добавил канальные генераторы и OFDM CFO/ICI по оригиналам. Архивная копия документации текущего проекта исключена из доказательств новизны. Для частичного индекса отдельно указаны прямые оригиналы; IMCRA и graphic EQ опираются на сохранённые исходники проекта.

В [RTL_TODO.md](RTL_TODO.md) добавлен раздел 8 с **29 открытыми заданиями**, точными местами получения ТЗ, предлагаемыми профилями, зависимостями и проверками. [task_catalog.json](../research/library_dsp_20261029/task_catalog.json) отделяет факты источника от проектных требований; проверены **52 файла** с SHA256/размерами. rag_evidence.json (не входит в публичную копию) сохраняет контекст и хеши фактического поиска/чтения. Независимый review проверил ссылки, диапазоны строк, граф зависимостей, отсутствие дублей готовых модулей и ограничения источников. Уточнены многократное продвижение входа при Q>P, фактические Viterbi generators 171/133 вопреки README 171/131, обратная связь prior-SNR/gain в исходном IMCRA, нормировка MVDR и исследовательский статус OFDM CFO/ICI. Реализация новых алгоритмов этим этапом не выполнялась; синтез остаётся на паузе.

## 2026-10-30: модельный этап CIC через Qulab, pi и OpenCode — PASS

Пользователь ограничил работу моделями и указал найти Haiku, DeepSeek и Qwen от Qulab. Конфигурации pi/OpenCode и реальный `/api/v1/models` на `<internal-llm-endpoint>` подтвердили ID `~anthropic/claude-haiku-latest`, `~deepseek/deepseek-v4-flash-latest`, `Qwen/Qwen3.8-Flash-Next-FP8`. Модели запускались явно через provider `openwebui`; ключи и конфигурации доступа в проект не копировались. Недоступный default OpenCode, зависший MiMo и исчерпавший reasoning limit Qwen/OpenCode не засчитаны как выполненные задания.

В изолированных каталогах Qwen/pi реализовал fixed CIC, Haiku/OpenCode — независимый exact/FIR и NumPy floating эталон, DeepSeek/pi — unit tests. Координатор нашёл и поручил исправить математическую ошибку comb (задержка выхода вместо входа) и ошибочные ожидаемые значения gain/rounding/TLAST в тестах; после исправлений повторно проверил файлы и реальные прогоны. В проект перенесены `common/python/cic_model.py`, `common/python/cic_reference.py`, `tests/test_cic_models.py`; добавлен `tools/run_cic_models.py`, тест зарегистрирован в общем Python-наборе.

Модельная приёмка: **16 тестов, 512 профилей, 2048 сигнальных случаев, 286976 комплексных выходов**, raw и normalized, 2 направленных отрицательных контроля. Покрыты R=1…32, N=1/2/3/5, M=1/2, независимая rational rounding, modular wrap, непрерывность кадров, reset, смена R и атомарный отказ неверного TLAST/конфигурации. Модели следуют явно заданному causal accepted-sample контракту; цикл исторического Verilog и аппаратные ready/valid не воспроизводятся. Документация — [TYPED_MODELS.md](TYPED_MODELS.md), модельные этапы отмечены в TODO при сохранённых открытых общих пунктах. [Итоговое свидетельство](cic_models_20261030_results.json).

Окончательный зарегистрированный Python-набор: **829 тестов / 24 конфигурации модемов — PASS**. Отдельная проверка из изолированной рабочей копии без логов агентов и конфигураций провайдеров тоже прошла: 16 тестов / 512 профилей / 286976 выходов.

Все 104 production RTL-файла совпали с прежним снимком; это 64 SV/SVH и 40 таблиц/конфигураций. RTL не изменялся и HDL/vendor инструменты не запускались. Более ранние HDL-свидетельства не переподписываются под новую Python-ревизию. Синтез и компиляция в Quartus/Vivado/ISE остаются на паузе.

## 2026-10-30: второй поиск DSP по локальной RAG и расширение очереди

По повторному запросу пользователя выполнены новые локальные catalog/search/read через документированный home-rag CLI. Снимок индекса: 7039 документов против 6472 в первом проходе; индекс всё ещё частичный. Поиск исключал архив текущего проекта, словари/OS false matches и дубли уже реализованных/запланированных блоков. DeepSeek/pi подготовил спектральные и аудиокандидаты; после широкого поиска его работа была ограничена синтезом выбранных источников. OpenCode/Haiku сначала получил отказ на внешний каталог, затем HTTP400; эти попытки не засчитаны как выполненный поиск. Координатор выполнил RAG-вызовы и прямое чтение известных оригиналов; Haiku/pi проверил шесть коммуникационных кандидатов. Его первоначальный FAIL-отчёт сохранён вместе с явными исправлениями: shared CRC, отсутствие PRBS-зависимости у fixed PLS scramble, 128 входных меток PLS и точный Chase scope.

В TODO добавлены **15 открытых модельных задач**, общий список расширения теперь 44, из них 2 модельных этапа CIC готовы. [task_additions.json](../research/library_dsp_20261030_round2/task_additions.json) содержит контракты/новизну/зависимости/приёмку и SHA256 27 источников. rag_evidence.json (не входит в публичную копию) сохраняет 46 фактических проверенных чтений и метаданные широкого поиска; неудачные/неполные raw JSON явно отмечены и не используются как подтверждение задач. В [validation_report.json](../research/library_dsp_20261030_round2/validation_report.json) проверены все 15 ID, граф зависимостей объединённых 44 задач, 37 ссылок на источники и 40 ссылок нового TODO-раздела.

Прочитанные оригиналы выявили важные ограничения: CFAR в PLFM — лишь фиксированный порог; overlap128 при FFT1024 не является общей корректной схемой для chirp3000; Hamming(32,26,5) не доказывает dmin5; BTC допускает нестандартный bit-order; формула Kalman gain в исходном EPUB не показывает innovation inverse. Эти материалы не приняты за безошибочный golden. CFAR/SAR отмечены как исследовательские постановки, цифровые compressor/gate — как наши производные спецификации на основе аналоговой монографии. Goertzel/DWT/AR-LPC и другие неподтверждённые варианты отложены до нахождения полноценного ТЗ.

Изменения только в документации и исследовательских JSON. Старый каталог 29 задач и привязанные к нему файлы не переписывались; CIC-свидетельство осталось PASS по 1485 исходникам и 36 артефактам. Реализация, HDL/vendor compilation, импорт/OCR и изменения RAG/оригиналов не выполнялись.

## 2026-10-30: модели компенсации CIC и полифазного P/Q — PASS

Продолжены два пункта P1 из TODO: `DSP-CIC-COMP` и `DSP-RATIONAL`. Готовы [cic_compensation.py](../common/python/cic_compensation.py), [rational_model.py](../common/python/rational_model.py), независимые [эталоны](../common/python/filter_references.py), [19 тестов](../tests/test_filter_models.py) и переносимый [runner](../tools/run_filter_models.py). Модели создали Haiku/pi и Qwen/pi, проверки — DeepSeek/pi; ограниченный аудит состояния выполнил Haiku/OpenCode. Исправлены смысл LS-веса/сетки, единицы частоты в эталоне и тестовая нормировка Q17; убраны нестандартная equality у I/Q и двойное наследование исключений. Исходные контракты, отчёты и ограничения review сохранены.

Приёмка: **12 профилей CIC compensation**, **480 rational случаев в floating/fixed (960 численных сравнений), 38355 точных fixed-выходов**, плюс **9 low-pass/tone профилей и 82913 дополнительных точных fixed-выходов**. Для Q17 худшая неравномерность на сетке8193 точек — **0.00121047 dB**, худшая FIR stopband — **-63.42146 dB**, при заранее заданных≤0.05 dB/≤−50 dB. В24 cascade-прогонах отдельно охарактеризованы **180 насыщенных компонент**, все выходы совпали с эталоном. Bypass компенсации и намеренно испорченный результат отклонены. Последующий FIR не объявляется средством удаления уже свернувшихся alias-компонент.

Общий зарегистрированный Python-набор: **848 тестов / 24 модемных конфигурации — PASS**. Отдельная изолированная копия без файлов агентов/провайдеров воспроизвела численные проверки. [Контракты и таблицы](TYPED_MODELS.md#cic-compensation-and-rational-models-2026-10-30), [прогресс](../research/filter_models_20261030/progress.json), [итоговое свидетельство](filter_models_20261030_results.json).

В расширенном TODO44 задачи: **4 модельных этапа готовы, 40 открыты**. Общие RTL-пункты остаются открытыми. Режим пользователя «только модели» сохранён; RTL/HDL, Quartus/Vivado/ISE и физический тайминг не выполнялись. Все 106 файлов RTL-набора вне тестбенчей совпали с исходным снимком этого этапа. Предыдущие JSON-приёмки остаются историческими снимками и не переподписываются под текущую Python-ревизию.
