# Контрольные точки проекта (история)

Архив прежнего корневого README: последовательность контрольных точек разработки со ссылками на отчёты. Актуальное описание — в [README](../README.md).

## Portable modem models

The project provides 26 modem workspaces and 11 separate DSP algorithm workspaces, grouped by type. Implementations run in Python, Octave/MATLAB and behavioral SystemVerilog with UVM tests. The models use explicit portable contracts and documented substitutions; they are not verified replicas of every historical source.

Start with the [project diary](PROJECT_DIARY.md), [modem catalog](MODEM_CATALOG.md) and [porting contract](PORTING_CONTRACT.md). Actual test results are recorded in [verification results](VERIFICATION.md).

Open the [typed visual atlas](typed_visual/index.html) for the 17 new workspaces, with model-type filters, 55 PNG/SVG figures and a [55-page PDF](typed_visual/modem_test_report.pdf). The [historical modem atlas](visual/index.html) retains the original 20 modems and 84 figures. Both reports work offline. [Model contracts and commands](TYPED_MODELS.md) explain the tested scope.

All 20 archived models now simulate in MATLAB R2020b with documented compatibility adjustments and reproduce their captured signals exactly after restart. Original mapper tables and the MSK transmitter have partial numerical reference checks; see [MATLAB modem verification](MATLAB_MODEM_VERIFICATION.md). Full receiver equivalence remains unverified. Launch details are in [installation status](MATLAB_INSTALLATION.md).

The two new Simulink modems and the QPSK script analogues now join the frame-modem suite. OFDM and FSK have separate block-model suites. Synchronization, channelizers, filters, coding, MIMO, audio and array processing live under `algorithms/<type>/`. All 295 new MATLAB/Simulink source files are assigned to workspaces in [the source coverage table](typed_source_coverage.csv); group analogues do not imply that every teaching script has been individually ported.

## Quick start

Run these commands from the project root:

```bash
python3 tools/run_tests.py --suite python
python3 tools/run_tests.py --suite cross
./tools/run_questa.sh --all
```

The complete portable regression is `python3 tools/run_tests.py --suite all`, covering 24 frame modems and all 13 typed block-model suites. It fails if a tool is missing or any check fails. There are no silently skipped HDL tests. Add `--modem bpsk_costas_2008_08_25` for one frame modem, or use `python3 tools/run_research.py --suite all --workspace coding/ldpc` for a typed suite. MATLAB and original-reference commands are in [the typed model guide](TYPED_MODELS.md).

```bash
python3 modems/bpsk_costas_2008_08_25/python/modem.py
octave-cli --quiet --eval "addpath('modems/bpsk_costas_2008_08_25/octave'); run_modem;"
```

## Requirements

The frame-modem suite requires Python with NumPy, GNU Octave with built-in functions, and Questa with UVM 1.2. The typed suites additionally use SciPy for independent numeric checks; visual reports also need Matplotlib. MATLAB is used for separate runtime/reference checks. The current machine has these tools. Questa uses 64-bit execution and system GCC; a restricted sandbox may require permission to start the simulators.

Original archives have already been extracted. Rebuilding the archive inventory requires `7z` and UnRAR for solid RAR files:

```bash
UNRAR=/path/to/unrar python3 tools/inventory.py
```

`tools/create_workspaces.py` regenerates configurations, source parameter reports and entry point wrappers. It overwrites those generated files; do not use it to preserve manual edits to them.

## Directory layout

| Path | Contents |
| --- | --- |
| `arxiv/` | Original archives and standalone legacy scripts, unchanged |
| `matlab/` | Existing reference books, unchanged |
| `sources/` | Extracted archives, including auxiliary examples |
| `research/` | Additional downloaded modem and DSP sources with provenance manifests; reviewed separately |
| `algorithms/<type>/<model>/` | Separate DSP workspaces, preserved sources, language entry points and UVM tests |
| `modems/<name>/original/` | Byte identical original modem model |
| `modems/<name>/matlab/` | R2020b compatibility copy, original-model test and verification record |
| `modems/<name>/octave/` | Octave demo and tests |
| `modems/<name>/python/` | Python modem entry point |
| `modems/<name>/sv/` | SystemVerilog modem wrapper |
| `modems/<name>/tb/` | UVM testbench entry point and launcher |
| `modems/<name>/tests/` | Per modem Python tests |
| `modems/ofdm_awgn/`, `modems/fsk_text/` | Typed block-modem suites with `model.json` instead of frame-engine `config.json` |
| `common/` | Independently implemented DSP cores in three languages |
| `tests/` | Analytic primitive and source integrity checks |
| `tools/` | Inventory, generation and regression commands |
| `build/` | Regenerable vectors, simulator libraries, logs and JSON results |
| `docs/` | Diary, catalog, contract and verification evidence |

## Scope

The models include differential PSK and quadrant coding, recovered QAM tables, RRC filtering, MSK/GMSK modulation, cubic interpolation, preamble based acquisition, Gardner timing tracking, carrier tracking, automatic gain adjustment and linear or decision feedback equalization. The SIMO workspace includes maximal ratio combining. Each receiver sees the training labels and received waveform; it does not receive payload truth.

The behavioral SystemVerilog models use real arithmetic and frame transactions. A separate streaming fixed point BPSK TX/RX is described in [the pilot contract](BPSK_RTL.md). Other modem families still require FPGA implementations. Differences from the archives, including the GMSK receiver replacement and shared implementations of related variants, are explicit in the porting contract. Original archives may contain their own license conditions; extraction does not relicense them.

Run `python3 tools/run_streaming_rtl.py --suite all` for the 16 streaming FFT/DSP/OQPSK suites, including MMSE 3×3 (Python, strict lint and Questa, without vendor synthesis). [Output overload verification](RTL_OVERLOAD.md) records the added full-scale cases, proven output bounds and [current coverage](RTL_COVERAGE.md).

The [protocol and tracking checkpoint](RTL_TRACKING_AND_PROTOCOL.md) adds checks on all streaming data/configuration inputs, direct FIR clipping-event comparisons, optional FFT model counters and measured Costas/Gardner recovery scenarios. The streaming command also runs 14 protocol negative controls.

The [FFT saturation and OQPSK checkpoint](RTL_FFT_SATURATION.md) directly compares all FFT stage clamp events with Python and exercises an OQPSK phase excursion with a disabled-feedback control.

The [DSP saturation checkpoint](RTL_DSP_SATURATION.md) adds direct notch/Kalman/beamformer/Alamouti/MMSE event comparisons and FIFO/index checks, and fixes a reproduced notch rounding overflow that reversed the output sign.

The [adaptive filter checkpoint](RTL_ADAPTIVE_SATURATION.md) directly compares LMS/NLMS/RLS internal clamps, verifies active indices and RLS triangle operation counts, and adds weight/covariance stress cases. Vendor synthesis remains paused.

The [spectral checkpoint](RTL_SPECTRAL_SATURATION.md) compares actual PFB/OFDM/STFT/OM-LSA clamp events with fixed-point models, verifies buffer and FIFO bounds, and adds full-prefix, spectral-boundary and quiet-burst cases. The 15 streaming suites and full portable regression pass; vendor synthesis remains paused.

The [embedded FFT checkpoint](RTL_EMBEDDED_FFT.md) checks stage-by-stage clamp operations inside PFB and OFDM against the fixed-point model, including inverse FFT clipping in the OFDM transmitter and negative controls for event and operation counts.

The [FSK and LDPC checkpoint](RTL_FSK_LDPC.md) verifies active FSK table/FIFO bounds and directly compares both LDPC decoder clamp stages with the integer model, including a stress case and negative controls. Vendor synthesis remains paused.

The [Gardner gradient checkpoint](RTL_SYNC_GRADIENT.md) directly compares the timing loop's Q30 error clamp with its integer model and checks active interpolation bounds, including negative controls for event, operation, and index counts.

The continuation adds [Costas quadrant relocking and sampled acquisition](RTL_SYNC_ACQUISITION.md), [full fixed receiver precision and raw SER](RTL_PRECISION.md), [FIR/FFT/OQPSK active bounds and truncated-frame checks](RTL_INTERNAL_BOUNDS.md), and [MMSE 3×3 with MMSE 2×2 corrections](RTL_MMSE3.md). Vendor synthesis remains paused.

[MMSE 3×3 expression widths](RTL_MMSE3_WIDTHS.md) now use 38 bits for Gram arithmetic and 84 bits for output sums (formerly 40/85), with unchanged results and cycles. The former widths remain selectable for comparison. The sweep checks full-code bounds, raw arithmetic, reset/stall scenarios and frozen-RTL equivalence.

The next width step covers [MMSE3 configuration expressions](RTL_MMSE3_CONFIG_WIDTHS.md) at 81/126/104 bits for adjugate/determinant/M, retaining their stored widths, and [MMSE N×N accumulators](RTL_MMSE_N_WIDTHS.md) with exact bounds for N=2…8. The fixed models and configuration divider widths are preserved.

Границы конфигурационных транзакций FIR/MMSE/LMS/RLS и независимые проверки — [RTL_CONFIGURATION_PROTOCOL.md](RTL_CONFIGURATION_PROTOCOL.md).

Workspace generators `tools/research_layout.py` and `tools/setup_new_models.py` overwrite generated configurations, tests and entry points; existing README files are kept. They need the third-party sources, which are not in the public repository.

[Review corrections and verification](REVIEW_FIXES.md) records evidence freshness checks, isolated runs, input rejection tests and strengthened negative controls.

The [follow-up review](CODE_REVIEW_FOLLOWUP.md) lists the remaining defects. Initial portable RTL primitives, fixed-point Python arithmetic, streaming UVM checks and dual-vendor place/route flows are described in [RTL_CONTRACT.md](RTL_CONTRACT.md). Run `python3 tools/run_tests.py --suite rtl` for this separate suite (additional dependencies: `requirements-rtl.txt`). The BPSK pilot has functional RTL coverage and its physical acceptance status is recorded in [BPSK_RTL.md](BPSK_RTL.md); the remaining scope is listed in [RTL_TODO.md](RTL_TODO.md).

Продолжение 2026-10-13: [такты FIR/FFT](RTL_STREAM_RATES.md), [FFT guard bits](RTL_FFT_WIDTH_SWEEP.md), [SER по выходу RTL](RTL_PAYLOAD_SER.md).

Новый [UVM пилот BPSK RX](RTL_BPSK_UVM.md) включён в общую регрессию; [точность LMS/NLMS/RLS](RTL_ADAPTIVE_PRECISION.md) измеряется независимыми полными петлями.

Независимая точность DSP: [LDPC/GF(2)](RTL_LDPC_PRECISION.md) и [PFB/STFT/OFDM/OM-LSA](RTL_SPECTRAL_PRECISION.md); бюджет качества и полнота измерения показаны отдельно.

Продолжение 2026-10-15: [UVM передатчика OQPSK](RTL_OQPSK_UVM.md), включённое в общую регрессию.

[UVM OQPSK/MSK/GMSK RX](RTL_PACKET_RX_UVM.md) и [потоковых DSP](RTL_DSP_UVM.md) продолжают тот же общий набор; [контрольная точка 15 октября](rtl_uvm_continuation_20261015c_results.json) фиксирует завершённую приёмку перед следующим расширением.

Текущий статус и следующие шаги — [CURRENT_STATUS.md](CURRENT_STATUS.md).

[PSK/QAM TX UVM](RTL_PSK_TX_UVM.md) проверяет все профили общего mapper; [DSP pin rates](RTL_DSP_PIN_RATES.md) измеряет реальные интервалы и задержки по VCD. [Модемные pin rates](RTL_MODEM_PIN_RATES.md) покрывают все TX/RX и максимальные кадры 2048 символов.

Итоговая функциональная [приёмка 15 октября g](rtl_modem_rates_20261015g_results.json): PASS — 608 Python-тестов, UVM1840/4226, 256 DSP и 136 модемных VCD-трасс, 16/16 streaming suites. Синтез остаётся на паузе.

Продолжение 2026-10-16: [параметризованный MMSE N×N](RTL_MMSE_N.md) для 2 ≤ N ≤ 8 — битоточен с моделью в Questa, выходы в пределах одного LSB от плавающего решения; 17-й потоковый набор. [Приёмка 16 октября](rtl_mmse_n_20261016_results.json): PASS — 617 Python-тестов, UVM 1840/4226, streaming 17/17.

[Устойчивость петель с задержкой](RTL_LOOP_DELAY.md): линейные запасы по измеренной крутизне детекторов и прогон битоточных приёмников по задержкам 1…64.

Продолжение 2026-10-19: задержка обратной связи OQPSK уменьшена с 10 до 8 символов в RTL и Python. [Парная проверка](RTL_LOOP_DELAY.md) даёт 7 вместо 12 ошибок при сильном фазовом шуме; полный путь запроса к ошибке измерен в 45 разрешённых тактов. [Приёмка изменения](rtl_oqpsk_delay_20261019_results.json) PASS: 624 Python-теста, 10 отчётов точности, Questa 34/28 и RX UVM 36/112. Синтез на паузе.

[Подбор аккумулятора FIR](RTL_FIR_WIDTHS.md): точные границы для signed18 входа позволяют использовать 35–36 бит на штатных коэффициентах, с отказом небезопасной конфигурации. [Приёмка](rtl_fir_widths_20261019_results.json) PASS: 635 Python-тестов, 11 отчётов, 220 RTL-прогонов ширины, 42 проверки защит, FIR UVM 96/208. Синтез остаётся на паузе.

Продолжение FIR: компактное дерево использует `36+level` бит для Re и `37+level` для Im; точным произведениям нужны 36 бит. Для 64 полос объявленный объём регистров дерева уменьшен на 12.9%, без округления внутри дерева. Прежняя раскладка доступна с `COMPACT_TREE=0`; проверяется каждый внутренний узел и каждое произведение. [Границы и метод проверки](RTL_FIR_WIDTHS.md). [Приёмка дерева](rtl_fir_tree_20261019_results.json) PASS: 636 Python-тестов, 480 числовых RTL-прогонов, 46 проверок защит и шесть отрицательных контролей; FIR UVM 96/208.

[Аккумуляторы PFB](RTL_PFB_WIDTHS.md) рассчитаны по числу отводов одной фазы: `36+max(LOG2TMAX−LOG2M,0)` бит. При M=64, TMAX=256 достаточно 38 вместо 44 бит, без ограничения коэффициентов или входного диапазона. Прежняя ширина доступна через `ACC_WIDTH`; сырые суммы проверяются до округления и насыщения. [Приёмка](rtl_pfb_widths_20261019_results.json) PASS: 643 Python-теста, 220 сравнительных RTL-прогонов, 44 отказа параметров и UVM 96/208. [Аудит Luna и сравнение агентов](AGENT_EFFICIENCY_20261019.md).

[ISTFT overlap-add](RTL_ISTFT_WIDTHS.md): произведения занимают 41 бит, аккумуляторы — 41/42/43 при перекрытии 1/2/4 вместо 44. Для N=256 объявленное кольцо сокращается на 1536/1024/512 бит. Сырые произведения, записи и чтения RAM сверяются до масштабирования и насыщения. [Приёмка ISTFT](rtl_istft_widths_20261019_results.json) PASS: 651 Python-тест, 320 RTL-прогонов, UVM ISTFT/OM-LSA 120/270.

[Энергия LMS/NLMS](RTL_LMS_ENERGY.md): исправлено переполнение NLMS16, default `ENERGY_WIDTH=36+LOG2N` даёт 36–40 бит. Прежняя ошибка воспроизведена, те же векторы проходят после исправления. [Приёмка](rtl_lms_energy_20261019_results.json) PASS: 659 Python-тестов и 14 отчётов, 240 сравнительных RTL-прогонов, 48 отказов параметров и 6 отрицательных контролей, UVM 84/294. [Оценка узкой задачи Luna](AGENT_EFFICIENCY_20261019_LMS.md).

[Энергия beamformer](RTL_BEAM_ENERGY.md): исправлено переполнение при 32 и более каналах, `ENERGY_WIDTH=36+LOG2M` даёт 36…42 бита для M=1…64. [Приёмка](rtl_beam_energy_20261019_results.json) PASS: 666 Python-тестов и 15 отчётов, 220 сравнительных RTL-прогонов, 44 отказа параметров и 6 отрицательных контролей, UVM 120/260. Время конфигурации делителя измеряется отдельно от потока. [Оценка задачи Luna](AGENT_EFFICIENCY_20261019_BEAM.md).

[Ширины Alamouti](RTL_ALAMOUTI_WIDTHS.md): суммы/энергия/масштабирование — 38/37/61 вместо 39/40/64 бит, с доказанными границами полного signed18 диапазона. [Приёмка](rtl_alamouti_widths_20261019_results.json) PASS: 672 Python-теста и 16 отчётов, 300 сравнительных RTL-прогонов, 72 отказа параметров и 12 отрицательных контролей, UVM 120/260. Интервал данных сохранён, конфигурация reciprocal короче на три такта. [Оценка Luna](AGENT_EFFICIENCY_20261019_ALAMOUTI.md).

[Ширины RLS](RTL_RLS_WIDTHS.md): регистры prediction, общий dot-тракт и hᴴu используют 53+LOG2N, 63+LOG2N, 67+LOG2N вместо 64/128/128 бит. Проверки произвольных кодов и адаптивных траекторий разделены. [Приёмка](rtl_rls_widths_20261019_results.json) PASS: 678 Python-тестов и 17 отчётов, 400 сравнительных RTL-прогонов, 96 отказов параметров, 20 направленных прогонов и 12 отрицательных контролей, UVM 84/294; такты сохранены. [Оценка Luna](AGENT_EFFICIENCY_20261019_RLS.md).

[Обновления RLS](RTL_RLS_UPDATES.md): промежуточные GAIN/UPDATE/WEIGHT/PT/COV — 71/59/44/89/79 вместо 128 бит; хранимые состояния и переменное округление gain сохранены. [Приёмка](rtl_rls_updates_20261019_results.json) PASS: 684 Python-теста и 18 отчётов, 350 сравнительных RTL-прогонов, 100 отказов параметров, 8 направленных прогонов и 12 отрицательных контролей; UVM 84/294, такты совпали. [Оценка Luna](AGENT_EFFICIENCY_20261019_RLS_UPDATES.md).

[Ширины LMS/NLMS](RTL_LMS_WIDTHS.md): округление предсказания, ошибка, шаг, c, dl, сумма с весом и выдача — 53+LOG2N/19/46/45/63/58/35 вместо 64/64/64/47/65/64/64 бит; состояния и такты сохранены. [Приёмка](rtl_lms_widths_20261020_results.json) PASS: 692 Python-теста и 19 отчётов, 540 сравнительных RTL-прогонов, 168 отказов параметров, 8 направленных прогонов и 18 отрицательных контролей; native, протокол, UVM и rate-прогоны прошли.
[Ширины MMSE 2×2](RTL_MMSE2_WIDTHS.md): Gram/det/M/масштабирование — 38/74/55/78 вместо 39/76/58/84 бит; выходные суммы 68 бит — точный минимум. [Приёмка](rtl_mmse2_widths_20261020_results.json) PASS: 692 Python-теста, 420 сравнительных RTL-прогонов, 24/20/14 отказов, параметров и отрицательных контролей; UVM 60/130, такты совпали.
[Ширины OM-LSA](RTL_OMLSA_WIDTHS.md): десять промежуточных выражений усиления — 18…72 бит вместо 128; регистры, модель и такты сохранены. [Приёмка](rtl_omlsa_widths_20261020_results.json) PASS: 694 Python-теста и 19 отчётов, 600 сравнительных RTL-прогонов, 120 отказов параметров, 8 направленных, 20 «на бит меньше» и 24 отрицательных контроля; native 50/8, UVM 50/130.

[MMSE N×N normalization and back substitution](RTL_MMSE_N_NORM_BACK.md): 70/87/65/107-bit paths and a 107–109-bit accumulator preserve the shared 112-bit divider and all cycles. The [acceptance record](rtl_mmse_norm_back_20261026_results.json) covers 758 Python tests, 1470 numeric RTL runs, 210 frozen comparisons and 1000188 raw component checks.

[MMSE weight scaling and elimination updates](RTL_MMSE_SCALE_UPDATES.md): MMSE3 scaling uses 145 instead of 156 bits; MMSE N×N products use 83/121 and updates use 53/91 instead of 84/122 and 138/138, preserving stored state and cycles. The [acceptance record](rtl_mmse_scale_updates_20261026_results.json) binds 752 Python tests, 1080 numeric runs and 240 frozen comparisons to archived sources and artifacts.

The [finite-burst `axis_fifo` checkpoint](rtl_axis_fifo_20261026_results.json) accepts a single-clock RAM FIFO feeding the unchanged II=8 Costas loop. For initially empty operation without sink stalls, one arrival per cycle, service every eight cycles starting at cycle 2, and registered FIFO output, bursts of 16/64/128/512 words require exact capacities 14/56/112/448 and RAM depths 16/64/128/512. `DEPTH` includes the output register; the minimum empty-input-to-output-handshake latency is two clocks. Fresh evidence covers eight focused Python tests, 20 unit, 96 integration, 18 negative, eight parameter and ten warning-free lint jobs. Full-FIFO `pop+push` throughput is accepted; at `level==1`, simultaneous `pop+push` intentionally leaves a one-cycle output bubble, and the directed monitor requires at least one. This does not establish sustained one-sample-per-cycle Costas operation: an unbounded one-per-cycle source accumulates seven queued words per eight cycles and needs a mean arrival interval of at least eight. No new full-project regression or physical timing run is claimed; vendor synthesis remains paused.
