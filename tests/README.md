# Проверки модемов, DSP-моделей и RTL

В этом каталоге находятся численные unit-тесты, независимые опорные расчёты и проверки средств регрессии. Тесты отдельных рабочих каталогов также расположены в `modems/*/tests/` и `algorithms/*/*/tests/`.

## Что это

Большинство тестов написано как `unittest.TestCase`; pytest собирает их вместе с обычными pytest-функциями. [pytest.ini](../pytest.ini) задаёт `testpaths = tests algorithms modems`, режим импорта `importlib` и исключает из рекурсивного поиска исторические копии, результаты сборки и сторонние материалы.

Проверяются переносимые кадровые модели Python/Octave/поведенческого SV, отдельные блочные DSP-операции, целочисленные опоры потокового RTL и расширенные Python-модели с плавающей и фиксированной точкой. Исторические схемы служат источником параметров и частичных эталонов; полная эквивалентность всех приёмников оригиналам не установлена. Область проверки — в [PORTING_CONTRACT.md](../docs/PORTING_CONTRACT.md), [TYPED_MODELS.md](../docs/TYPED_MODELS.md) и [EXTENDED_DSP_MODELS.md](../docs/EXTENDED_DSP_MODELS.md).

## Как работает

1. Тест выбирает конфигурацию/профиль, фиксированные векторы либо воспроизводимый генератор.
2. Для модемов выполняется TX → канал → RX с известной преамбулой. Для DSP-блоков вход и параметры передаются в функцию операции или в целочисленную модель.
3. Результат сравнивается с аналитическим ответом, независимым NumPy/SciPy-расчётом, точной целочисленной арифметикой либо сохранённой тестовой фикстурой.
4. Проверки границ, неверных входов, состояния, сбросов и намеренно испорченных данных подтверждают, что проверяющий код обнаруживает ошибку.
5. HDL-runner отдельно запускает настоящий DUT, сравнивает принятые передачи и проверяет покрытие; тесты самого runner часто используют mock, синтетические CSV/VCD и временные каталоги.

| Правило | Значение / следствие |
| --- | --- |
| Кадровый `ModemContract` | Перебор меток/переходов, noiseless loopback, шум/усиление/фаза/задержка, повторяемость, неверные входы и проверки особенностей варианта |
| Преамбула общих кадровых тестов | 192 символа; ошибки полезной части считаются после неё |
| Проверка чувствительности RX | При `snr_db=-8` тест требует более 20 ошибочных payload-символов |
| Integer-опора | Сравнение сырых слов, форматов и насыщений; допуски floating задаются конкретным тестом |
| Полнота свидетельств | Завершённый `PASS`, дата окончания, неизменные хеши кода и артефактов |
| Штатный UVM | Нулевые `UVM_ERROR`/`UVM_FATAL`, ожидаемое число результатов; отрицательные контроли обязаны обнаружить внесённое нарушение |
| Оптимизация Python | Проверяющие runner требуют включённых `assert`; `python -O` не используется |

`run_tests.py` загружает явно перечисленные unit-тесты и все `test_ext_*.py` через `unittest.defaultTestLoader`. Он не является оболочкой над pytest: обычные pytest-функции этим способом не собираются. С `--modem` выбираются контрактные тесты одного кадрового модема, а общие unit-тесты всё равно выполняются; дополнительные исследования точности запускаются только без `--modem`.

## Структура каталога

| Файл / группа | Назначение |
| --- | --- |
| [test_primitives.py](test_primitives.py) | Аналитические проверки RRC/Gaussian, кубической интерполяции, отображения, MSK/OQPSK/MRC; также два теста происхождения, требующие исторических файлов |
| [test_regression_guards.py](test_regression_guards.py), [test_suite_evidence.py](test_suite_evidence.py) | Отказ устаревших/незавершённых свидетельств, корректность импорта, входных контрактов и численных отрицательных контролей |
| [test_fixed_point.py](test_fixed_point.py), [test_rtl_tools.py](test_rtl_tools.py) | Q-арифметика и требования к ограничениям/предупреждениям/отчётам синтеза |
| `test_bpsk*.py`, [test_psk_fixed.py](test_psk_fixed.py), [test_cpm_fixed.py](test_cpm_fixed.py), [test_oqpsk_fixed.py](test_oqpsk_fixed.py), [test_mrc_fixed.py](test_mrc_fixed.py), [test_fsk_fixed.py](test_fsk_fixed.py) | Целочисленные модемы, захват, решения, восстановление и проверки отчётов RX |
| [test_fft_fixed.py](test_fft_fixed.py), [test_fir_fixed.py](test_fir_fixed.py), [test_pfb_fixed.py](test_pfb_fixed.py), [test_stft_fixed.py](test_stft_fixed.py), [test_ofdm_fixed.py](test_ofdm_fixed.py), [test_omlsa_fixed.py](test_omlsa_fixed.py) | Спектральные и фильтрующие integer-модели, масштабирование и ограничения |
| [test_sync_fixed.py](test_sync_fixed.py), [test_oset_fixed.py](test_oset_fixed.py), `test_costas*.py`, `test_sync_*.py` | Costas/Gardner, notch/Kalman, конечные сетки захвата и критерии восстановления |
| [test_lms_fixed.py](test_lms_fixed.py), [test_rls_fixed.py](test_rls_fixed.py), [test_beam_fixed.py](test_beam_fixed.py), `test_mmse*.py`, [test_ldpc_fixed.py](test_ldpc_fixed.py) | Адаптация, линейные системы, MMSE/ZF и кодирование |
| `test_*precision.py`, `test_*width_sweep.py`, [test_rls_update_sweep.py](test_rls_update_sweep.py), `test_*energy_study.py` | Независимая точность и доказанные границы промежуточной арифметики, отказы небезопасных ширин |
| [test_axis_fifo.py](test_axis_fifo.py), [test_fifo_budget.py](test_fifo_budget.py), [test_fifo_load_sweep.py](test_fifo_load_sweep.py), [test_lms_fifo_budget.py](test_lms_fifo_budget.py), [test_lms_fifo_load_sweep.py](test_lms_fifo_load_sweep.py) | Вместимость FIFO, конечные нагрузки, независимые остановки выходов и отрицательные контроли |
| `test_*uvm*.py`, [test_packet_rx_uvm.py](test_packet_rx_uvm.py), [test_uvm_floating_reference.py](test_uvm_floating_reference.py) | Подготовка транзакций, физические поля, полнота сценариев, независимый floating payload SER и чувствительность валидаторов |
| [test_stream_rates.py](test_stream_rates.py), [test_dsp_stream_rates.py](test_dsp_stream_rates.py), [test_modem_stream_rates.py](test_modem_stream_rates.py), [test_mmse3_rates.py](test_mmse3_rates.py) | Разбор трасс и определение задержек/интервалов по принятым передачам |
| [test_cic_models.py](test_cic_models.py), [test_filter_models.py](test_filter_models.py) | CIC decimation/interpolation, компенсация спада и рациональный ресэмплинг с независимыми опорами |
| `test_ext_signal_*.py` | DDS/Hilbert, SOS/Farrow, PSD/DCT, FFT-свёртки, AM/FM/SSB/DDC и независимые SciPy-опоры |
| `test_ext_code_*.py` | CRC/PRBS/Hamming, Viterbi, GF/BCH/RS/Golay, Polar/Turbo/TCM/PLS/BTC/LLR; в том числе крайние случаи soft quantization |
| `test_ext_advanced_*.py` | DPD, каналы, антенные алгоритмы, IMCRA/EQ16, dynamics, Kalman, CFO, радар и SAR |
| [test_ext_cross_models.py](test_ext_cross_models.py) | Сквозные сочетания кодирования, скремблирования, мягких решений и канала |
| [data](data) | Численные фикстуры IMCRA/DPD в NPZ и прототип EQ16 в JSON; тесты читают эти данные, а не исходные MATLAB-функции |
| [../common/python/modem_checks.py](../common/python/modem_checks.py) | Общий mixin кадровых тестов; локальные `test_modem.py` задают свой `config_path` |
| [Пример блочного test_model.py](../algorithms/filters/windowed_sinc/tests/test_model.py) | Локальный тест запускает `run_research.py --suite python --workspace ...` |

### Автономные модели run_own

[test_own_models.py](test_own_models.py) запускает `main` каждой `modems/*/run_own.py` с `--no-plot`, проверяет численный отчёт и полноту структуры (`run_own.m`, `run_own.py`, `run_demo.m`, README со ссылкой на `run_own`). Для быстрого прогона выбираются три точки SNR через `--sweep`; поведение демонстраций по умолчанию сохраняется. Перекрёстная проверка создаёт Python-векторы всех автономных модемов во временном каталоге и вызывает `common/own/own_cross_check.m`. Без `octave-cli` только эта проверка явно пропускается с причиной. Сторонние модели и MATLAB/Simulink для этих тестов не нужны.

```bash
python3 -m pytest -q tests/test_own_models.py tests/test_primitives.py
```

## Как запустить

Команды выполняются из корня проекта. Все Python-зависимости (NumPy, SciPy, PyYAML, Matplotlib, pytest) ставятся одной командой `pip install -r requirements.txt`. Octave нужен для `octave`/`cross`, Questa с UVM 1.2 — для `hdl`, Verilator — для lint. Для `--suite rtl` дополнительно нужны Vivado и Quartus: этот режим включает размещение и трассировку.

```bash
# Численные проверки без исторических моделей: быстрый выбранный набор
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q tests/test_fixed_point.py tests/test_cic_models.py tests/test_filter_models.py

# Все тесты из testpaths pytest.ini (в публичной копии две проверки исходников пропускаются)
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q

# Зарегистрированные unittest и исследования точности/разрядностей
python3 tools/run_tests.py --suite python

# Octave и общие Python-векторы выбранного кадрового модема
python3 tools/run_tests.py --suite cross --modem bpsk_costas_2008_08_25

# Отдельная блочная модель Python
python3 tools/run_research.py --suite python --workspace coding/ldpc

# 17 потоковых FFT/DSP/OQPSK-наборов: Python, lint, Questa; без синтеза Vivado/Quartus
python3 tools/run_streaming_rtl.py --suite all

# Общая переносимая регрессия, включая UVM; нужны исторические файлы
python3 tools/run_tests.py --suite all
```

У `run_tests.py` есть режимы `python`, `octave`, `cross`, `hdl`, `all`, `rtl`. `all` объединяет кадровые Python/Octave/HDL, точностные исследования, расширенные HDL-проверки, блочные модели и контракты входов; он не включает отдельный vendor synthesis из `rtl`. У `run_research.py --suite all` выполняются Python, Octave и HDL; MATLAB выбирается отдельно через `--suite matlab`. Отсутствующий инструмент является ошибкой, а не основанием тихо пропустить HDL.

Сам pytest не создаёт единого приёмочного JSON для всего проекта. Часть тестов вызывает runner, создающие `build/`; для параллельных запусков нужно учитывать совпадение их выходных путей. Значения `--output` и поддержка изолированных каталогов перечислены в [tools/README.md](../tools/README.md).

## Что смотреть

Для pytest признак успеха — код возврата 0 и отсутствие failed/error; для unittest — `OK`. Сводки `run_tests.py` записываются в `build/<suite>_results.json`, а для выбранного модема — в `build/single/<modem>/`. В `build/logs/` находятся журналы дополнительных исследований. Блочные результаты лежат в `build/typed/`, потоковые — в `build/rtl/<block>/` и `build/rtl/streaming/`.

В приёмочном JSON проверяйте `status`, `completed_at_utc`, число выполненных проверок и хеши. Одного текста `PASS` из старого журнала недостаточно. В штатном UVM-запуске ошибки и fatal равны нулю; в отрицательном контроле ожидается отказ с конкретной причиной, который runner принимает как успешное обнаружение нарушения.

BER/SER отражают доли ошибочных битов/символов полезной части; SQNR — отношение мощности опоры к мощности ошибки. События насыщения и число арифметических операций проверяются отдельно. Совпадение integer-модели и RTL не устанавливает качество независимого floating-приёмника; проверки полных петель и локальной арифметики разделены в [RTL_PRECISION.md](../docs/RTL_PRECISION.md).

Сохранённые результаты описаны в [VERIFICATION.md](../docs/VERIFICATION.md), [CURRENT_STATUS.md](../docs/CURRENT_STATUS.md) и [карте документации](../docs/README.md). Сигналы можно посмотреть в [историческом атласе](../docs/visual/index.html) и [атласе блочных моделей](../docs/typed_visual/index.html); эти статические материалы не означают, что тесты запускались в текущей копии.

## Ограничения

Исторические исходники не входят в публичную поставку. Два метода [test_primitives.py](test_primitives.py) требуют их явно:

| Тест | Что необходимо |
| --- | --- |
| `TestPrimitives.test_source_integrity` | Исходный файл из `config.json` и его историческая копия в рабочем каталоге; проверяются SHA-256 и побайтовое равенство |
| `TestPrimitives.test_extracted_mapping_and_source_locations` | Текст исторической схемы; проверяются строки блоков из `source_parameters.json` и таблицы mapper |

Без каталога `sources/` оба теста явно пропускаются (`skipTest` со ссылкой на THIRD_PARTY.md), поэтому полный pytest и `run_tests.py --suite python` проходят и в публичной копии; в выводе pytest они видны как `2 skipped`.

Происхождение, размеры и SHA-256 блочных оригиналов записаны в `model.json`, например [filters/windowed_sinc](../algorithms/filters/windowed_sinc/model.json). Для кадровых моделей [source_parameters.json](../modems/bpsk_costas_2008_08_25/source_parameters.json) содержит извлечённые поля и номера строк; SHA-256 находится в [config.json](../modems/bpsk_costas_2008_08_25/config.json), размеры — в [archive_inventory.json](../docs/archive_inventory.json). MATLAB-проверки оригиналов, аудит сторонних коллекций и публикация отчётов с повторной сверкой исторических копий также доступны только при наличии исходников.

`run_extended_dsp_models.py` читает планы, каталоги задач и манифесты из `research/` (они входят в публичную копию) и фикстуры `tests/data/`. Флаг `--frozen-baseline` дополнительно сверяет RTL и прежние Python-файлы с замороженной базой кампании 2026-10-30; после последующих изменений эта сверка намеренно не проходит.

Unit-тесты парсеров, mock и синтетические VCD не заменяют реальную HDL-регрессию. Численные модельные проверки не подтверждают vendor timing, ресурсы FPGA или универсальный диапазон захвата/BER. Исторические даты и количества PASS относятся к указанным в документации снимкам.
