# Общие DSP-ядра и эталонные модели

Каталог содержит общие реализации модемов и DSP-алгоритмов на Python, Octave/MATLAB и поведенческом SystemVerilog. Здесь также находятся целочисленные модели для проверки потокового RTL и отдельные Python-модели новых алгоритмов.

## Что это

Код используется рабочими каталогами `modems/`, `algorithms/`, тестами `tests/` и средствами проверки из `tools/`. Исторические схемы и учебные программы послужили прототипами, но общий переносимый контракт содержит явно описанные замены: совпадение трёх реализаций само по себе не доказывает эквивалентность историческому приёмнику. Подробности — в [контракте переноса](../docs/PORTING_CONTRACT.md), [каталоге блочных моделей](../docs/TYPED_MODELS.md) и [описании расширенных Python-моделей](../docs/EXTENDED_DSP_MODELS.md).

Есть три разных уровня реализации:

| Уровень | Где находится | Что проверяется |
| --- | --- | --- |
| Кадровая модель с плавающей точкой | `python/modem_core.py`, `octave/modem_core.m`, `sv/modem_dsp_pkg.sv` | Общий контракт TX/канал/RX и численное согласие языков |
| Блочные DSP-операции с плавающей точкой | `python/research_core.py`, `octave/research_core.m`, `sv/research_dsp_pkg.sv` | Плоский контракт массивов и независимые численные опоры |
| Целочисленные и расширенные модели | `python/*_fixed.py`, `python/ext_*.py`, модели CIC и ресэмплинга | Битовые результаты RTL либо отдельная численная приёмка Python; область проверки указана для каждого семейства |

Синтезируемые модули находятся в [rtl/common](../rtl/common), а не в `common/sv`. Поведенческий SV использует `real`, динамические массивы и обработку кадра внутри одного запроса. Для новых `ext_*` наличие Python-модели с плавающей или фиксированной точкой не означает наличие Octave/SV/RTL-реализации.

Исторические исходные модели в публичный репозиторий не входят. У блочных рабочих каталогов происхождение, размер `bytes` и SHA-256 сохранены в `model.json`, например [filters/windowed_sinc/model.json](../algorithms/filters/windowed_sinc/model.json). У кадровых модемов [source_parameters.json](../modems/bpsk_costas_2008_08_25/source_parameters.json) содержит извлечённые поля блоков и номера строк; путь происхождения и SHA-256 записаны в соседнем [config.json](../modems/bpsk_costas_2008_08_25/config.json), размеры архивных файлов — в [archive_inventory.json](../docs/archive_inventory.json). MATLAB-проверка оригиналов и проверки целостности исторических копий доступны только при наличии этих исходников.

## Автономные демонстрации common/own

Каталог [own/](own/) содержит автономную реализацию для 22 исторических модемов, перенесённую из MATLAB-сборника и поддерживаемую вместе с проектом. MATLAB/Octave работает без тулбоксов, Python использует NumPy и Matplotlib для графиков. Имена `own_*` позволяют одновременно пользоваться существующими `octave/modem_core.m` и `python/modem_core.py`.

| MATLAB/Octave | Python | Назначение |
| --- | --- | --- |
| [own/own_core.m](own/own_core.m) | [own/python/own_core.py](own/python/own_core.py) | Модуляция, фильтры, захват по преамбуле, Gardner, фазовая петля, АРУ, эквалайзеры и MRC |
| [own/own_channel.m](own/own_channel.m) | `channel` в `own_core.py` | AWGN, задержка, дрейф, частотный сдвиг, фазовый шум и эхо |
| [own/own_demo.m](own/own_demo.m) | [own/python/own_demo.py](own/python/own_demo.py) | Численный отчёт, созвездия, SER(SNR), сравнение узлов |
| [own/own_cross_check.m](own/own_cross_check.m) | [own/python/own_cross_vectors.py](own/python/own_cross_vectors.py) | Проверка одинакового входного сигнала на обеих реализациях |

Точки входа — `modems/<имя>/run_own.m` и `run_own.py`. Они читают существующий `config.json`; дополнительные поля `source` и `source_sha256` не влияют на расчёт. Исторические модели для этого не нужны. Параметры по умолчанию: 1536 символов, преамбула 192, SNR 28 дБ на отсчёт, сетка −10:2:24 дБ. Python CLI позволяет сократить сетку через `--sweep`; MATLAB/Octave — через `struct('sweep',[-10 10 24])`.

Из корня проекта:

```bash
python3 common/own/python/own_cross_vectors.py build/own_cross_vectors
octave-cli --quiet --eval "addpath('common/own'); own_cross_check('build/own_cross_vectors');"
python3 -m pytest -q tests/test_own_models.py
```

Генератор выбирает только модемы с `run_own.py`. Проверяются три канала для каждого модема: TX и RX с допуском `1e-7`, решения точно, задержка `1e-8`, частота `1e-10`. Численные алгоритмы перенесены без изменений; переименованы функции, исправлены пути и добавлен выбор точек SNR в CLI. Согласие языков не доказывает эквивалентность историческим слепым приёмникам.

## Как работает

Кадровая цепочка:

1. `load_config` загружает и проверяет конфигурацию; `frame_data` формирует воспроизводимые целочисленные метки.
2. `encode` выполняет табличное отображение и выбранное дифференциальное кодирование. Линейный TX добавляет RRC-фильтрацию; MSK/GMSK используют накопление фазы, GMSK — также Gaussian-фильтр. У OQPSK квадратуры сдвинуты на полсимвола.
3. `channel` добавляет заданные шум, усиление, фазу, частотное смещение, дробную задержку и, по сценарию, эхо, дрейф или фазовый шум.
4. `receive(cfg, waveform, preamble, count)` получает волну, известную преамбулу и длину кадра. Линейный RX выполняет согласованную фильтрацию, поиск задержки с кубической интерполяцией, оценку частоты/фазы/усиления по преамбуле, слежение и, при выборе профиля, эквализацию.
5. Решения декодируются в метки; тест сравнивает только полезную часть. SIMO использует MRC с известными коэффициентами ветвей: `sum(conj(h)*x/variance) / sum(abs(h)**2/variance)`.

Блочный API `research_core.run(operation, parameters, signal, auxiliary=())` сначала проверяет входы, затем выполняет операцию. В `OPERATIONS` зарегистрированы `fir`, `dft`, `pfb`, `lms`, `nlms`, `rls`, `ldpc`, `stft`, `istft`, `omlsa`, `beamform`, `mimo`, `ofdm_tx`, `ofdm_rx`, `fsk_tx`, `fsk_rx`, `costas`, `timing`, `notch`, `kalman`, `wola`, `wsinc`, `alamouti`, `gf2_encode`. Порядок элементов плоских массивов согласован между языками; параметризация и ограничения проверяются `research_validate`.

| Параметр / правило | Значение и область действия |
| --- | --- |
| Переносимый кадровый baseline | `sps=8`, `rrc_order=32`, `rolloff=1.0`, `gaussian_bt=0.3`; см. пример [BPSK config](../modems/bpsk_costas_2008_08_25/config.json) |
| Обучение в общих векторах | 192 символа из кадра 512; минимальная преамбула `receive` — 32 символа |
| Поиск линейного RX | Задержка от 0 до двух символьных интервалов, шаг 0.25 отсчёта; четырёхточечная кубическая интерполяция |
| Эквалайзер кадровой модели | 7 прямых отводов; у DFE дополнительно 3 отвода обратной связи |
| `fixed_point.SAMPLE` | `QFormat(18, 15)`: 18 бит со знаком, 15 дробных; значение raw / `2**15` |
| Округление `fixed_point.round_shift` | К ближайшему, половина к чётному; переполнение ограничивается диапазоном Q-формата |
| Модель FIR `fir_fixed` | Отсчёты signed18 Q15, комплексные коэффициенты signed18 Q17; `y = sat18((acc + 2**16) >> 17)`, длина полной свёртки `L+T-1` |
| Модель FFT `fft_fixed` | Вход по умолчанию 18 бит, данные 20 бит, twiddle Q16; прямое преобразование `FFT(x)/N`, обратное без деления на N |
| BPSK fixed | Отсчёты 18/15, RRC и тригонометрия 18/17, кубические коэффициенты 18/16; фаза uint32 в долях оборота |
| Costas `sync_fixed` | `e = sign(Re)*Im - sign(Im)*Re`; частота обновляется перед фазой, фаза оборачивается по 32 битам |
| Gardner `sync_fixed` | `Re((late-early)*conj(mid))`; ограничение ошибки до `±2**30`, позиции накапливаются в Q32 |

Округление и насыщение задаются конкретной моделью: FIR/FFT и многие DSP-модели используют `(v + 2**(s-1)) >> s`, а FFT имеет симметричные границы насыщения. Правило `fixed_point.round_shift` нельзя автоматически переносить на все `*_fixed.py`.

Кадровый `modem_if` имеет `rst_n`, `valid`, `done`, массивы меток и отсчётов, оценки задержки и частоты. У `research_if` аналогичный запрос содержит `operation`, `parameters`, `signal_in`, `auxiliary`, `result`. Завершение внутри одного моделируемого такта — поведенческая условность. Потоковые `valid/ready/last`, форматы, задержки и остановки конкретного RTL описаны в [RTL_CONTRACT.md](../docs/RTL_CONTRACT.md), [RTL_STREAM_RATES.md](../docs/RTL_STREAM_RATES.md) и [RTL_DSP_PIN_RATES.md](../docs/RTL_DSP_PIN_RATES.md); единой латентности для всей библиотеки нет.

## Структура каталога

| Файл / подкаталог | Назначение и основные потребители |
| --- | --- |
| [python/modem_core.py](python/modem_core.py) | Кадровые TX, канал, RX, фильтры, отображение, MRC; обёртки `modems/*/python/`, генерация векторов |
| [python/modem_checks.py](python/modem_checks.py) | Общий `ModemContract` для `modems/*/tests/test_modem.py` |
| [python/research_core.py](python/research_core.py), [python/research_validate.py](python/research_validate.py) | Блочные операции и их контракт; `algorithms/`, OFDM/FSK, `run_research.py` |
| [python/fixed_point.py](python/fixed_point.py) | Q-форматы, округление, complex add/multiply, маски переполнения; RTL-примитивы и integer-модели |
| [python/bpsk_fixed.py](python/bpsk_fixed.py), [python/psk_fixed.py](python/psk_fixed.py) | Битовые TX/RX BPSK, PSK/QAM; `run_bpsk.py`, PSK/QAM UVM и отчёты точности |
| [python/cpm_fixed.py](python/cpm_fixed.py), [python/gmsk_coherent.py](python/gmsk_coherent.py) | MSK/GMSK и независимый coherent GMSK RX; CPM runner и приёмные UVM-проверки |
| [python/oqpsk_fixed.py](python/oqpsk_fixed.py), [python/mrc_fixed.py](python/mrc_fixed.py) | OQPSK и двухветвевое MRC; OQPSK/SIMO-проверки |
| [python/fft_fixed.py](python/fft_fixed.py), [python/fir_fixed.py](python/fir_fixed.py) | FFT и FIR; собственные RTL-наборы и составные спектральные блоки |
| [python/pfb_fixed.py](python/pfb_fixed.py), [python/stft_fixed.py](python/stft_fixed.py), [python/ofdm_fixed.py](python/ofdm_fixed.py), [python/omlsa_fixed.py](python/omlsa_fixed.py) | PFB, STFT/ISTFT, OFDM, OM-LSA; одноимённые runner и UVM |
| [python/sync_fixed.py](python/sync_fixed.py), [python/oset_fixed.py](python/oset_fixed.py), [python/fsk_fixed.py](python/fsk_fixed.py) | Costas/Gardner, notch/Kalman, M-FSK; `run_sync.py`, `run_oset.py`, `run_fsk.py` |
| [python/lms_fixed.py](python/lms_fixed.py), [python/rls_fixed.py](python/rls_fixed.py) | Адаптивные фильтры; сравнение выходов, ошибок, весов и внутренних ограничителей RTL |
| [python/beam_fixed.py](python/beam_fixed.py), [python/mmse_fixed.py](python/mmse_fixed.py), [python/mmse3_fixed.py](python/mmse3_fixed.py), [python/mmse_n_fixed.py](python/mmse_n_fixed.py) | Beamformer/Alamouti и MMSE/ZF 2×2, 3×3, N×N; линейные DSP-наборы |
| [python/ldpc_fixed.py](python/ldpc_fixed.py) | LDPC и систематическое кодирование GF(2); `run_ldpc.py` |
| [python/sat_diag.py](python/sat_diag.py) | Необязательные счётчики насыщений и диапазонов до ограничения; генераторы векторов и точностные исследования |
| `python/*_widths.py`, [python/lms_energy.py](python/lms_energy.py), [python/beam_energy.py](python/beam_energy.py) | Точные границы промежуточных выражений FIR/PFB/ISTFT/LMS/RLS/Alamouti/MMSE/OM-LSA; инструменты `*_width_sweep.py` и исследования энергии |
| [python/fifo_budget.py](python/fifo_budget.py) | Бюджеты конечной нагрузки FIFO; Costas/LMS load sweeps и BPSK RX rate |
| [python/cic_model.py](python/cic_model.py), [python/cic_reference.py](python/cic_reference.py) | CIC decimator/interpolator и независимая FIR-опора; `run_cic_models.py` |
| [python/cic_compensation.py](python/cic_compensation.py), [python/rational_model.py](python/rational_model.py), [python/filter_references.py](python/filter_references.py) | Компенсация спада CIC, рациональный ресэмплинг и независимые опоры; `run_filter_models.py` |
| `python/ext_signal_*.py` | DDS/Hilbert, SOS, Farrow, PSD, DCT, FFT-свёртка, AM/FM/SSB, DDC; `tests/test_ext_signal_*.py` |
| `python/ext_code_*.py` | CRC/PRBS/Hamming, GF/BCH/RS, Golay, Viterbi, Polar, Turbo, LLR, PLS, TCM, BTC; `tests/test_ext_code_*.py` |
| `python/ext_advanced_*.py` | Каналы, DPD, MVDR/MUSIC/ESPRIT, IMCRA, EQ16, dynamics, matrix Kalman, CFO, радар и SAR; `tests/test_ext_advanced_*.py` |
| [octave/modem_core.m](octave/modem_core.m), [octave/modem_demo.m](octave/modem_demo.m) | Кадровое ядро и демонстрация; обёртки `modems/*/octave/` |
| [octave/modem_test.m](octave/modem_test.m), [octave/modem_cross_test.m](octave/modem_cross_test.m) | Собственные проверки Octave и сравнение общих Python-векторов |
| [octave/research_core.m](octave/research_core.m), [octave/research_validate.m](octave/research_validate.m) | Блочные операции Octave/MATLAB и проверка входов |
| [octave/research_check.m](octave/research_check.m), [octave/research_contract_check.m](octave/research_contract_check.m) | Сравнение общих результатов и проверка допустимых/недопустимых входов |
| [sv/modem_dsp_pkg.sv](sv/modem_dsp_pkg.sv) | Независимая поведенческая DSP-реализация кадровых модемов |
| [sv/modem_if.sv](sv/modem_if.sv), [sv/modem_model.sv](sv/modem_model.sv) | Интерфейс кадров и модель под тестом |
| [sv/modem_uvm_pkg.sv](sv/modem_uvm_pkg.sv), [sv/tb_top.sv](sv/tb_top.sv) | UVM sequence, driver, monitor, scoreboard и общий верхний уровень |
| [sv/research_dsp_pkg.sv](sv/research_dsp_pkg.sv), [sv/research_validate.svh](sv/research_validate.svh) | Поведенческие блочные операции и валидация входов |
| [sv/research_tb.sv](sv/research_tb.sv), [sv/research_contract_tb.sv](sv/research_contract_tb.sv) | UVM-сравнение блочных результатов и негативные проверки контракта |

## Как запустить

Все команды выполняются из корня проекта. Для Python-моделей нужны Python 3 и NumPy; блочные опоры и расширенные тесты используют также SciPy, часть тестов — pytest. Проверки RTL-инфраструктуры импортируют PyYAML из [requirements-rtl.txt](../requirements-rtl.txt). Для `cross` нужен `octave-cli`, для HDL — Questa и UVM 1.2, для строгого lint — Verilator. `QUESTA_HOME`, `UVM_HOME`, `DPI_CC` позволяют выбрать установку Questa, библиотеку UVM и GCC. MATLAB нужен только для отдельных MATLAB-запусков.

```bash
# Кадровая демонстрация Python
python3 modems/bpsk_costas_2008_08_25/python/modem.py

# Численные тесты отдельного блочного рабочего каталога
python3 tools/run_research.py --suite python --workspace filters/windowed_sinc

# Octave: собственные тесты и общие Python-векторы одного модема
python3 tools/run_tests.py --suite cross --modem bpsk_costas_2008_08_25

# Поведенческий SV/UVM одного модема
bash tools/run_questa.sh --modem bpsk_costas_2008_08_25

# Целочисленная FFT-модель; затем lint и Questa для того же блока
python3 tools/run_fft.py --suite python
python3 tools/run_fft.py --suite all

# Независимые Python-проверки CIC и рационального ресэмплинга
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q tests/test_cic_models.py tests/test_filter_models.py
```

Общие команды и зависимости перечислены в [tools/README.md](../tools/README.md), группы тестов — в [tests/README.md](../tests/README.md). `run_tests.py --suite python` дополнительно выполняет исследования точности и разрядностей; это более широкий запуск, чем один unit-тест. Запускайте проверяющие команды без `python -O`.

## Что смотреть

Кадровая демонстрация печатает оценки задержки, частоты и число ошибок. Общие векторы и их `manifest.json` появляются в `build/vectors/<modem>/`; результаты одиночного `cross` — в `build/single/<modem>/cross_results.json` и журнале Octave. Результаты Questa кадровой модели находятся в `build/questa/single/<modem>/results.json`, блочных моделей — в `build/typed/<workspace с /, заменённым на __>/`, integer FFT — в `build/rtl/fft/`.

`PASS` требует успешного завершения и всех заявленных сравнений. Для UVM нужны нулевые `UVM_ERROR`/`UVM_FATAL` в штатных запусках, точное число транзакций и обнаружение намеренно испорченного результата в отрицательном контроле. `source_hashes` и `artifact_hashes` связывают отчёт с кодом и результатами конкретного запуска.

BER — доля неверных битов меток, SER — доля неверных символов; преамбула исключается из payload-метрик. SQNR сравнивает мощность опорного сигнала с мощностью ошибки квантования. Совпадение с integer-опорой, локальный SQNR узла и качество полного независимого RX — разные проверки. Число насыщений считает выход за границу до ограничения; значение точно на границе само по себе событием не является.

Для просмотра сигналов откройте [атлас кадровых модемов](../docs/visual/index.html), [атлас блочных моделей](../docs/typed_visual/index.html) и [карту документации](../docs/README.md). Методика качества приведена в [RTL_PRECISION.md](../docs/RTL_PRECISION.md), новые Python-ограничения — в [EXTENDED_DSP_MODELS.md](../docs/EXTENDED_DSP_MODELS.md).

## Ограничения

Кадровые модели используют известную преамбулу и заданные длину/грубую границу кадра. Их захват заменяет часть исторических слепых алгоритмов; скремблеры, точный порядок Simulink-блоков и исходные переходные процессы в общий контракт не входят. В частности, кадровый GMSK RX использует частотный дискриминатор; coherent GMSK — отдельная реализация.

Форматы, таблицы, задержки обратной связи и насыщения отдельных integer-моделей различаются. Полное совпадение Python с RTL проверяется только соответствующим HDL-набором; отдельный запуск Python не заменяет его. Измеренные интервалы в тактах не устанавливают Fmax и физическую пригодность FPGA. Ограниченные профили расширенных Python-моделей, включая предварительное обучение/решение и частичную целочисленную обработку, описаны в их коде и профильной документации.

Удаление исторических исходников меняет снимок `source_hashes`: сохранённые отчёты полной локальной версии могут не пройти проверку актуальности в публичной копии. Два теста происхождения из `tests/test_primitives.py`, MATLAB-запуски оригиналов и сверки исторических копий требуют отсутствующих в публичной поставке материалов.
