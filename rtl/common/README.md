# Общая библиотека fixed-point RTL

Синтезируемые SystemVerilog-блоки для модемов и DSP: арифметика, потоковая буферизация, память, синхронизация, фильтры, преобразования, адаптация и декодирование. Ниже перечислены все `.sv` этого каталога и содержимое `cdc/` и `mem/`.

## Что это

Библиотека объединяет повторно используемые узлы и законченные DSP-ядра. Для большинства алгоритмов есть независимые вещественные реализации и целочисленные `*_fixed.py` в [common/python](../../common/python/), тесты — в [tests](../../tests/). Переносимые Octave/MATLAB и поведенческие SV-модели находятся в [common](../../common/); они не являются синтезируемыми fixed-point реализациями.

Происхождение алгоритмических аналогов и связи с историческими моделями описаны в [DSP_RTL.md](../../docs/DSP_RTL.md), [FFT_RTL.md](../../docs/FFT_RTL.md) и `model.json` соответствующих [алгоритмических моделей](../../algorithms/). Общая инфраструктура имеет собственный [RTL-контракт](../../docs/RTL_CONTRACT.md). Есть численные SV/UVM-проверки, но физическая проверка выполнена не для всех блоков и не для всех текущих изменений. В частности, `costas_stream`, MMSE 3×3/N×N и изменения разрядностей нельзя считать принятыми по таймингу на основании симуляции.

## Как работает

Типовая последовательность: сброс → загрузка конфигурации → ожидание `configured` → входная транзакция → обработка → выходная транзакция. У арифметических примитивов нет конфигурационного этапа; последовательные вычислители используют `start/done` вместо потока. Несколько блоков могут быть соединены через valid/ready или [axis_fifo.sv](axis_fifo.sv), если совпадают геометрия кадров и числовые форматы.

Общие числовые соглашения:

| Соглашение | Смысл |
| --- | --- |
| Запись `W/F` | W — полная разрядность со знаком, F — число дробных бит; вещественное значение `code/2^F` |
| Временные I/Q | Обычно signed 18/15, диапазон −4…4−2⁻¹⁵ |
| STFT/PFB-спектры | signed 24/19; это другой масштаб, напрямую соединять с 18/15 нельзя |
| FIR/PFB-коэффициенты | Обычно signed 18/17; notch использует signed 18/16 |
| Фаза | 32-битный циклический код, один оборот `2^32` |
| LDPC | signed 16/8 LLR и posterior |
| `fxp_round_sat` и арифметические `fxp_*` | Округление к ближайшему с точной серединой к чётному, затем насыщение |
| FFT, FIR и ряд DSP-узлов | Округление половины вверх `(v+2^(s−1)) >> s`; правило берётся из конкретного кода/эталона |
| `m_overflow` арифметики | bit 0 — Re, bit 1 — Im; переполнение округлённого результата до насыщения |

Насыщение и намеренное циклическое переполнение фазы — разные операции. Единого правила округления для всей библиотеки нет. Полные произведения/суммы сохраняются в предусмотренной разрядности до точки округления; параметры `*_WIDTH` ограничены проверками в `initial`, а не произвольны.

Потоковые соглашения AXI-Stream:

1. Вход передаёт слово на фронте `clk` при `s_valid && s_ready`, выход — при `m_valid && m_ready`.
2. Источник удерживает `valid`, данные и `last`, пока ожидающая передача не принята. `last` относится к конкретному слову; в FFT это конец N-точечного кадра, в STFT — последний бин всей транзакции.
3. Физические порты плоские: `s_re/s_im`, `s_label`, `s_llr` и т. п. Полноценная универсальная оболочка с `TDATA/TKEEP` не задаётся.
4. Конфигурация `cfg_valid/cfg_ready` обычно принимается между транзакциями. Значения `cfg_*`, длина и `cfg_last` имеют отдельный контракт каждого ядра; например, у scalar Kalman одна конфигурационная передача, у MMSE — матрица по строкам.
5. Синхронный сброс с полярностью `RESET_ACTIVE` отменяет ожидающую работу. Память обычно физически не обнуляется: доступность данных задают valid/счётчики. После сброса конфигурируемые блоки загружаются заново.

Арифметические конвейеры могут замораживаться целиком; MRC/beamform/Alamouti/MMSE резервируют выходной FIFO для слов в полёте. Поэтому наличие valid/ready не означает II=1 для любого алгоритма. LMS имеет второй независимый поток итоговых весов: основной результат не означает, что `w_*` уже опустошён.

Для примеров алгоритмов: MRC считает `Σw_i·x_i`; beamform — `X·conj(a)/(aᴴa)`; MMSE — `(HᴴH+λI)⁻¹Hᴴ·obs`; LMS предсказывает `conj(w)·h` и обновляет веса по ошибке. OM-LSA объединяет `reflect_pad → STFT → omlsa_gain → ISTFT → вырезка`. Точные масштабы и ограничения приведены в исходниках и профильных документах.

## Структура каталога

В таблице перечислены все модули непосредственно в `rtl/common/`. Если у модуля есть `RESET_ACTIVE`, его значение по умолчанию равно 1. Параметры файлов указывают на поставляемые `.mem`; при изменении размера FFT/окна нужно выбирать соответствующую таблицу.

| Файл | Назначение | Интерфейс | Параметры по умолчанию |
| --- | --- | --- | --- |
| [alamouti_rx.sv](alamouti_rx.sv) | Декодирование пары Alamouti с нормировкой по энергии канала | `cfg_re/im`: h0,h1; комплексный поток r0,r1 → y0,y1; `configured/error` | `RESET_ACTIVE`; `SUM_WIDTH=38`, `ENERGY_WIDTH=37`, `SCALE_WIDTH=61` |
| [axis_fifo.sv](axis_fifo.sv) | FIFO одного тактового домена с точной полезной ёмкостью и регистровым чтением RAM | Поток `s_data/m_data`, valid/ready/last, `level` | `WIDTH=36`, `DEPTH=16`, `RESET_ACTIVE`; WIDTH 1…4096, DEPTH 2…65536 |
| [beamform.sv](beamform.sv) | Нормированное формирование луча по снимкам M каналов | `cfg_re/im`: веса; M комплексных входов → один выход; `error` | `LOG2M=3`, `ENERGY_WIDTH=36+LOG2M`, `RESET_ACTIVE` |
| [costas_loop.sv](costas_loop.sv) | QPSK-петля без задержки ошибки по отсчётам, II=8 тактов | Однословная cfg K1/K2; комплексный поток → I/Q и `m_phase` | `RESET_ACTIVE`, `TABLE_DIR="rtl/modems/bpsk_costas_2008_08_25/tables"` |
| [costas_stream.sv](costas_stream.sv) | Непрерывная конвейерная QPSK-петля, II=1, задержка ошибки 10 продвижений | Те же cfg K1/K2 и I/Q/phase; состояние сохраняется через `s_last` | `RESET_ACTIVE`, `TABLE_DIR` как у `costas_loop` |
| [fft_delay.sv](fft_delay.sv) | Задержка SDF на DEPTH разрешённых тактов, регистры либо RAM | `s_data/m_data`, `ce`, без valid/ready | `WIDTH=21`, `DEPTH=8`, `RESET_ACTIVE` |
| [fft_r2sdf.sv](fft_r2sdf.sv) | Radix-2 DIF/SDF FFT/IFFT, естественный порядок выхода | Комплексный поток N слов, `s_inverse/m_inverse`, `error` | `LOG2N=6` (2…10), `IN_WIDTH=18`, `WIDTH=20`, `RESET_ACTIVE`, `TWIDDLE_FILE="rtl/common/mem/fft_twiddle_64.mem"`; `IN_WIDTH+1 <= WIDTH <= 24` |
| [fir_runtime.sv](fir_runtime.sv) | Полная комплексная свёртка, L+T−1 выходов | Поток комплексных cfg Q17 отводов, I/Q Q15; `configured/error` | `LOG2LANES=2`, `LOG2TMAX=6`, `ACC_WIDTH=38+LOG2TMAX`, `COMPACT_TREE=1`, `RESET_ACTIVE` |
| [fsk_rx.sv](fsk_rx.sv) | M корреляторов, решение по максимуму энергии | cfg шагов фазы/длины `cfg_n`; n I/Q → `m_label` | `LOG2M=2`, `LOG2NMAX=5`, `RESET_ACTIVE`, `TABLE_DIR` пилота |
| [fsk_tx.sv](fsk_tx.sv) | M-FSK, n отсчётов на метку | cfg шагов фазы/длины; `s_label` → I/Q | `LOG2M=2`, `LOG2NMAX=5`, `RESET_ACTIVE`, `TABLE_DIR` пилота |
| [fxp_complex_add.sv](fxp_complex_add.sv) | Комплексное сложение, латентность 2 такта | Две комплексные величины `s_ar/ai/br/bi` → I/Q, `m_overflow`, valid/ready/last | `WIDTH=18`, `FRAC=15`, `OUT_WIDTH=18`, `OUT_FRAC=15`, `RESET_ACTIVE` |
| [fxp_complex_mul.sv](fxp_complex_mul.sv) | Комплексное умножение, латентность 4 такта | Те же входы/выходы и флаги, что у сложения | `WIDTH=18`, `FRAC=15`, `OUT_WIDTH=18`, `OUT_FRAC=15`, `RESET_ACTIVE` |
| [fxp_divide_seq.sv](fxp_divide_seq.sv) | Restoring-деление signed числителя на положительный знаменатель | `start`, `numerator`, `denominator` → `busy/done/result` | `NUM_WIDTH=64`, `DEN_WIDTH=32`, `RESET_ACTIVE`; NUM_WIDTH+2 такта на вычисление |
| [fxp_mrc2.sv](fxp_mrc2.sv) | Две ветви MRC с известными усилениями и дисперсиями | cfg gains/variances и `cfg_enable`; общие valid/last двух ветвей → I/Q; `error/saturated` | `RESET_ACTIVE`; форматы фиксированы: I/Q 18/15, веса 18/14 |
| [fxp_round_sat.sv](fxp_round_sat.sv) | Комбинационное округление/насыщение одной компоненты | `s_data → m_data`, `overflow`; без такта | `IN_WIDTH=37`, `IN_FRAC=30`, `OUT_WIDTH=18`, `OUT_FRAC=15` |
| [fxp_stream_resize.sv](fxp_stream_resize.sv) | Преобразование комплексного формата, латентность 1 такт | I/Q valid/ready/last, `m_overflow` | `IN_WIDTH=37`, `IN_FRAC=30`, `OUT_WIDTH=18`, `OUT_FRAC=15`, `RESET_ACTIVE` |
| [gardner_timing.sv](gardner_timing.sv) | Кадровая петля Гарднера с кубической интерполяцией | cfg sps/count/позиции/K3/K4; входной кадр → I/Q и `m_position` | `RESET_ACTIVE`, `TABLE_DIR` пилота; вход до 16384 отсчётов, sps≥2 |
| [gf2_encoder.sv](gf2_encoder.sv) | Систематический кодер `[A·message; message]` над GF(2) | Матрица cfg по битам, `cfg_m/cfg_k`; битовый поток → m+k бит | `LOG2KMAX=6`, `LOG2MMAX=6`, `RESET_ACTIVE` |
| [kalman_scalar.sv](kalman_scalar.sv) | Скалярный Kalman отдельно для Re/Im | cfg Q/R/P0 unsigned Q24; I/Q → I/Q; `error` | `RESET_ACTIVE`; cfg передаётся одним словом, R>0 |
| [ldpc_decoder.sv](ldpc_decoder.sv) | Flooding: sum-product, min-sum, normalized/offset min-sum | cfg матрицы H, режима/итераций/alpha/beta; `s_llr` → `m_bit/m_posterior` | `LOG2NMAX=7`, `LOG2MMAX=6`, `LOG2EMAX=9`, `RESET_ACTIVE`, `PHI_FILE="rtl/common/mem/ldpc_phi.mem"`, `INV_FILE="rtl/common/mem/ldpc_inv.mem"` |
| [lms_filter.sv](lms_filter.sv) | LMS/NLMS, веса 34/30; около 8 тактов/отсчёт | cfg режима/T/MU/EPS; x,d → prediction/error; отдельный поток `w_*` | `LOG2N=2`, `RESET_ACTIVE`, `RECIP_FILE="rtl/common/mem/lms_reciprocal.mem"`, `ENERGY_WIDTH=36+LOG2N`; остальные ширины ниже |
| [mmse2.sv](mmse2.sv) | MMSE/ZF 2×2 через Gram/adj/det, веса Q24 | cfg 4 комплексных коэффициентов H и λ; пары наблюдений → пары решений | `RESET_ACTIVE`, `GRAM_WIDTH=38`, `DET_WIDTH=74`, `M_WIDTH=55`, `SCALE_WIDTH=78`, `SUM_WIDTH=68` |
| [mmse3.sv](mmse3.sv) | MMSE/ZF 3×3 с точными промежуточными Gram/adj/det | cfg 9 коэффициентов H и λ; тройки наблюдений → тройки решений | `RESET_ACTIVE`, `GRAM_WIDTH=38`, `SUM_WIDTH=84`, `ADJ_WIDTH=81`, `DET_WIDTH=126`, `M_WIDTH=104`, `SCALE_WIDTH=145` |
| [mmse_n.sv](mmse_n.sv) | MMSE/ZF N×N, нормализация и эрмитово исключение Гаусса | cfg N² коэффициентов H и λ; полные N-ки входа/выхода; `configured/error` | `N=4` (2…8), `RESET_ACTIVE`, `GRAM_ACC_WIDTH=36+$clog2(N+1)`, `SUM_WIDTH=82+$clog2(N+1)`; остальные ширины ниже |
| [norm_reciprocal.sv](norm_reciprocal.sv) | Нормированная обратная энергия: `Z=22+bit_length(E)`, `r=round_even(2^Z/E)` | `start/energy` → `done/zero/r/shift`, `shift=Z−15` | `WIDTH=40`, `SHIFT_WIDTH=max($clog2(WIDTH+23),7)`, `RESET_ACTIVE` |
| [notch_iir.sv](notch_iir.sv) | IIR notch 2-го порядка, 5 защитных дробных бит, II=1 | cfg B1/A1/A2 в 18/16; комплексный поток | `RESET_ACTIVE` |
| [omlsa.sv](omlsa.sv) | Полный OM-LSA, длина выхода равна входу | cfg nnoise/alpha; I/Q поток, `configured/error` | `LOG2N=5`, `LOG2HOP=3`, `RESET_ACTIVE`, `MEM_DIR="rtl/common/mem"`; ширины `omlsa_gain` ниже |
| [omlsa_gain.sv](omlsa_gain.sv) | Спектральное усиление OM-LSA, начальные кадры задают шум | `nnoise/alpha`, спектральный поток 24/19; `error` | `LOG2N=5`, `RESET_ACTIVE`, `MEM_DIR="rtl/common/mem"`, `UNSAFE_WIDTH_TEST=0`; арифметические ширины ниже |
| [pfb_analysis.sv](pfb_analysis.sv) | Полифазный анализ, FFT(q)/M, M=4…64 | cfg Q17 taps и decimation D=1…M; I/Q Q15 → спектр Q19 | `LOG2M=2`, `LOG2LANES=2`, `LOG2TMAX=6`, `RESET_ACTIVE`, `TWIDDLE_FILE="rtl/common/mem/fft_twiddle_4.mem"`, `ACC_WIDTH=36+max(LOG2TMAX−LOG2M,0)` |
| [reflect_pad.sv](reflect_pad.sv) | Отражённое дополнение по N с каждой стороны | I/Q поток L≥N+1 → L+2N слов; `error` | `LOG2N=5`, `RESET_ACTIVE`; кольцевая память 8N |
| [rls_filter.sv](rls_filter.sv) | RLS с эрмитовой ковариационной матрицей P 44/28 | cfg T/P0/λ/1λ; x,d → prediction/error и независимые `w_*` | `LOG2N=2`, `RESET_ACTIVE`; арифметические ширины ниже |
| [stft_analysis.sv](stft_analysis.sv) | sqrt-Hann и FFT; `F=1+floor((L−N)/HOP)` полных кадров | Временной I/Q 18/15 → F·N спектральных слов 24/19 | `LOG2N=6`, `LOG2HOP=4`, `RESET_ACTIVE`, `TWIDDLE_FILE="rtl/common/mem/fft_twiddle_64.mem"`, `WINDOW_FILE="rtl/common/mem/stft_window_64.mem"` |
| [stft_synthesis.sv](stft_synthesis.sv) | ISTFT, нормированный overlap-add | F·N спектральных слов 24/19 → `(F−1)·HOP+N` слов 18/15 | `LOG2N=6`, `LOG2HOP=4`, `RESET_ACTIVE`, `TWIDDLE_FILE`/`WINDOW_FILE` как у анализа, `RECIP_FILE="rtl/common/mem/stft_recip_64_16.mem"`, `ACC_WIDTH=41+LOG2N−LOG2HOP`, `PRODUCT_WIDTH=41` |
| [cdc/](cdc/) | Синхронизация одиночного бита и снятия сброса | Управляющие сигналы; потокового/многобитного CDC FIFO нет | Параметры отдельных модулей ниже |
| [mem/](mem/) | Синхронные RAM/ROM и числовые таблицы | Регистровое чтение; не AXI-Stream | Параметры отдельных модулей ниже |

Дополнительные параметры разрядностей перечислены полностью; они задают промежуточные выражения, а не произвольную смену формата внешнего порта:

| Модуль | Параметры по умолчанию | Обоснование/проверка |
| --- | --- | --- |
| `lms_filter` | `PRED_WIDTH=53+LOG2N`, `ERROR_WIDTH=19`, `STEP_WIDTH=46`, `COEFF_WIDTH=45`, `DELTA_WIDTH=63`, `WEIGHT_WIDTH=58`, `DUMP_WIDTH=35` | [RTL_LMS_WIDTHS.md](../../docs/RTL_LMS_WIDTHS.md) |
| `rls_filter` | `PRED_WIDTH=53+LOG2N`, `DOT_WIDTH=63+LOG2N`, `Q_WIDTH=67+LOG2N`, `GAIN_WIDTH=71`, `UPDATE_WIDTH=59`, `WEIGHT_WIDTH=44`, `PT_WIDTH=89`, `COV_WIDTH=79` | [RTL_RLS_WIDTHS.md](../../docs/RTL_RLS_WIDTHS.md), [RTL_RLS_UPDATES.md](../../docs/RTL_RLS_UPDATES.md) |
| `mmse_n` | `A_PRODUCT_WIDTH=83`, `B_PRODUCT_WIDTH=121`, `A_UPDATE_WIDTH=53`, `B_UPDATE_WIDTH=91`, `NORM_WIDTH=70`, `WEIGHT_WIDTH=87`, `MULT_NUM_WIDTH=65`, `BACK_PRODUCT_WIDTH=107`, `BACK_ACC_WIDTH=106+$clog2(N)` | [RTL_MMSE_N_WIDTHS.md](../../docs/RTL_MMSE_N_WIDTHS.md), [RTL_MMSE_N_NORM_BACK.md](../../docs/RTL_MMSE_N_NORM_BACK.md) |
| `omlsa`, `omlsa_gain` | `RECIP_WIDTH=18`, `GAMMA_WIDTH=72`, `XI_WIDTH=47`, `V_WIDTH=48`, `G1_WIDTH=37`, `T_WIDTH=48`, `A_WIDTH=37`, `OUT_WIDTH=41`, `GG_WIDTH=34`, `PREV_WIDTH=49` | [RTL_OMLSA_WIDTHS.md](../../docs/RTL_OMLSA_WIDTHS.md); `UNSAFE_WIDTH_TEST` есть только у gain и предназначен для отрицательных тестов |

Содержимое служебных подкаталогов:

| Файл/группа | Назначение и интерфейс | Параметры/условия |
| --- | --- | --- |
| [cdc/bit_sync.sv](cdc/bit_sync.sv) | Два регистра `async_bit → sync_bit` с `ASYNC_REG`; синхронный сброс | `RESET_ACTIVE=1`; только одиночный управляющий бит |
| [cdc/reset_sync.sv](cdc/reset_sync.sv) | `async_rst → rst`: внешний reset включает выход, снятие ждёт два регистра | `RESET_ACTIVE=1`; внешний сброс держать не менее трёх фронтов; ядра обрабатывают reset синхронно |
| [mem/sync_ram.sv](mem/sync_ram.sv) | Простой двухпортовый RAM: `wr_en/wr_addr/wr_data`, `rd_en/rd_addr/rd_data` | `WIDTH=18`, `ADDR_WIDTH=10`; чтение 1 такт; общий адрес чтения/записи возвращает старые данные |
| [mem/sync_rom.sv](mem/sync_rom.sv) | ROM через `$readmemb`, `rd_en/rd_addr/rd_data` | `WIDTH=18`, `ADDR_WIDTH=8`, `INIT_FILE="rtl/common/mem/test_rom.mem"`; чтение 1 такт |
| `mem/fft_twiddle_<N>.mem` | Cos/sin Q16 для FFT | Поставляются N=4,8,16,32,64,128,256,512,1024 |
| `mem/stft_window_<N>.mem` | sqrt-Hann Q17 | Поставляются N=4,8,16,32,64,256 |
| `mem/stft_recip_<N>_<HOP>.mem` | Нормировка overlap-add с учётом границ | Поставляются 4/1, 8/2, 16/4, 32/8, 32/32, 64/16, 64/32, 256/64; наличие таблицы проверять отдельно от допустимости параметров ядра |
| `mem/ldpc_phi.mem`, `mem/ldpc_inv.mem` | Таблицы sum-product в φ-области | Должны соответствовать целочисленному LDPC-эталону |
| [mem/lms_reciprocal.mem](mem/lms_reciprocal.mem) | Таблица нормирования NLMS | Адресуется старшими битами энергии |
| `mem/omlsa_recip.mem`, `omlsa_tf.mem`, `omlsa_te.mem`, `omlsa_ln.mem`, `omlsa_expn.mem` | Отношения и нелинейные функции OM-LSA | Поставляются вместе с `omlsa_gain` |
| [mem/test_rom.mem](mem/test_rom.mem) | Тестовая ROM инфраструктуры | Не коэффициенты модема |

RAM не инициализируется и не сбрасывается, при `rd_en=0` выход удерживается. `axis_fifo.DEPTH` включает регистровый выход RAM: это полная полезная ёмкость, не «глубина плюс выходной регистр». Минимальная передача от пустого входа до потребления выхода занимает 2 такта; при накопленной очереди возможен одновременный pop+push на каждом такте, в том числе при полной FIFO.

Важные темпы и ограничения: FFT делит прямое преобразование на N, обратное считает без 1/N; STFT поддерживает N=4…256 и `N/HOP`=1/2/4; OM-LSA — пары (16,4), (32,8), (64,16). `costas_loop` сбрасывает фазу/частоту на транзакции и имеет II=8; `costas_stream` сохраняет состояние через `last`, имеет II=1 и требует коэффициентов, устойчивых при задержке 10 продвижений. Агрессивные коэффициенты последовательной петли нельзя переносить автоматически: [RTL_COSTAS_STREAM.md](../../docs/RTL_COSTAS_STREAM.md).

## Как запустить

Команды из корня проекта. Python с NumPy/PyYAML: [requirements-rtl.txt](../../requirements-rtl.txt). Для lint нужен Verilator; для численной HDL/UVM-проверки — Questa/UVM 1.2. Параметры `QUESTA_HOME`/`UVM_HOME` и поиск через `PATH` описаны в [RTL README](../README.md). Octave/MATLAB не требуются целочисленным RTL-наборам.

```bash
python3 tools/run_rtl.py --suite all
python3 tools/run_rtl.py --suite hdl --block complex_mul
python3 tools/run_streaming_rtl.py --suite all
python3 tools/run_costas_stream.py --suite all
python3 tools/run_mmse_n.py --suite all
python3 tools/run_dsp_uvm.py --suite all
```

`run_rtl` проверяет начальные арифметические примитивы и служебные RAM/ROM/CDC; `--block` ограничивает арифметический HDL-набор. `run_streaming_rtl` объединяет 17 FFT/DSP/OQPSK-наборов, но не включает `costas_stream`; он показан отдельно. `run_mmse_n` проверяет параметризованный решатель. Полный DSP UVM проверяет 128 конфигураций внешних контактов; MMSE N×N и `costas_stream` имеют отдельные native-наборы. Для проверки Python без HDL заменить `all` на `python` в соответствующем runner.

Проверка FIFO и конечных нагрузок:

```bash
python3 tools/axis_fifo_sweep.py --verify-rtl
python3 tools/fifo_load_sweep.py --verify-rtl --output build/fifo_load_readme
python3 tools/lms_fifo_load_sweep.py --verify-rtl --output build/lms_fifo_load_readme
```

Последние два пути должны быть новыми. Первая команда проверяет ёмкость/порядок и интеграцию FIFO с Costas; две другие — конечные профили поступления данных, независимые остановки выхода и сопоставление с расчётным бюджетом буфера. Размер FIFO не превращает медленный потребитель в устойчивый бесконечный канал с большей средней скоростью.

## Что смотреть

Общая арифметика — `build/rtl/all_results.json`, `complex_mul/`, `complex_add/`, `resize/`, `support/`. Алгоритмы — `build/rtl/<block>/<suite>_results.json`; потоковая сводка — `build/rtl/streaming/`; DSP UVM — `build/rtl/dsp_uvm/`. Явно заданные output-пути содержат отдельные результаты экспериментов FIFO. Каталоги `build` создаются при запуске и могут отсутствовать в публикации.

Проверяйте завершённый PASS с актуальными хешами, число действительно принятых/выданных слов, сброшенные остатки и отрицательные контроли. Для арифметики важны побитные I/Q, overflow, last и латентность; для адаптивных фильтров — prediction/error и все итоговые веса; для LDPC — hard bit и полный posterior; для MMSE — веса, выходы и отказы непредставимых/вырожденных конфигураций. События насыщения нужно сравнивать с точками вычисления, а не только с достижением предельного выходного кода.

Документы: [RTL_DSP_UVM.md](../../docs/RTL_DSP_UVM.md), [RTL_STREAM_RATES.md](../../docs/RTL_STREAM_RATES.md), [RTL_SYNC_ADAPTIVE_RATES.md](../../docs/RTL_SYNC_ADAPTIVE_RATES.md), [RTL_INTERNAL_BOUNDS.md](../../docs/RTL_INTERNAL_BOUNDS.md), [RTL_PRECISION.md](../../docs/RTL_PRECISION.md). Визуальные иллюстрации алгоритмических моделей — в [типизированном отчёте](../../docs/typed_visual/index.html); они не заменяют отчётов RTL и STA.

## Ограничения

Общий формат 18/15 не подходит всем внутренним узлам, а допустимость параметров не означает наличия каждой таблицы `.mem` или проверки каждой комбинации. Конфигурационные ошибки, `last` не на границе пары/N-ки и переполнение внутренних диапазонов обрабатываются по контракту ядра; игнорировать `error` нельзя. У `fxp_divide_seq` нулевой знаменатель запрещён вызывающей стороной, определённого результата для него нет.

`bit_sync` не синхронизирует многобитные данные. CDC FIFO здесь нет, метастабильность симуляцией не моделируется; интеграция доменов требует отдельного решения и ограничений. Тесты на конечных последовательностях и пересчёт тактов в условные 100 МГц не доказывают бесконечного темпа или физического Fmax. Прежние результаты синтеза не распространяются автоматически на сокращённые арифметические ширины и новые расписания.

Исторические сторонние исходники в публичную версию не входят. Обычные целочисленные эталоны проверяют самостоятельный контракт; повторная проверка исходных MATLAB/Simulink-моделей требует этих материалов. Происхождение и доступные метаданные указаны в `model.json` переносимых алгоритмов либо в конфигурациях/извлечённых параметрах соответствующих модемов.
