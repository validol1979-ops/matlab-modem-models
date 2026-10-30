# Инструменты запуска и проверки модемов и DSP

Каталог содержит команды регрессии, генерацию тестовых векторов, измерения точности и интерфейсных тактов, средства UVM и отдельные MATLAB/vendor flows. Таблицы ниже перечисляют все скрипты непосредственно в `tools/`, включая импортируемые вспомогательные модули.

## Что это

Главные точки входа — `run_tests.py`, `run_research.py`, `run_streaming_rtl.py`, `run_rtl.py`, `run_bpsk.py` и `run_questa.sh`. Они проверяют разные уровни: кадровые модели, отдельные операции, потоковые DSP-блоки, базовые RTL-примитивы и модемный BPSK-пилот. Поведенческий SV/UVM и синтезируемый fixed-point RTL имеют разные интерфейсы и критерии приёмки.

Исторические MATLAB/Simulink-прототипы и сторонние коллекции в публичный репозиторий не входят. Происхождение, размер и SHA-256 блочных источников сохранены в `model.json`, например [filters/windowed_sinc](../algorithms/filters/windowed_sinc/model.json). У кадровых модемов [source_parameters.json](../modems/bpsk_costas_2008_08_25/source_parameters.json) содержит поля блоков и номера строк, [config.json](../modems/bpsk_costas_2008_08_25/config.json) — путь и SHA-256, [archive_inventory.json](../docs/archive_inventory.json) — размеры. Аудит исходников, MATLAB-проверка оригинала и повторная публикация некоторых сводных отчётов доступны только при наличии этих материалов.

## Как работает

Типичный путь — выбор конфигурации → воспроизводимые входы → независимая Python-опора → Octave или HDL DUT → сравнение принятых результатов → отрицательные контроли → JSON со статусом и хешами. При измерении темпа используются фактические `valid && ready`, CSV/VCD и занятость памяти; арифметическая корректность проверяется отдельным численным scoreboard.

`regression_evidence.py` фиксирует снимок исходников перед запуском, проверяет его неизменность и сохраняет хеши артефактов. Завершённый `PASS` включает `completed_at_utc`. `RUNNING`, ненулевой код возврата, пропущенный сценарий, устаревшие хеши или не сработавший отрицательный контроль не являются успешной приёмкой.

| Точка входа | Выбор режима и особенности |
| --- | --- |
| `run_tests.py` | `--suite python/octave/cross/hdl/all/rtl`, по умолчанию `all`; `--modem NAME` выбирает кадровую конфигурацию. `python` загружает unittest и без выбора модема выполняет дополнительные исследования точности/разрядностей. `cross` включает Octave-тесты и сравнение Python-векторов. `hdl` без выбора модема добавляет потоковые UVM, FIFO и измерения интерфейсов. `all` дополнительно запускает блочные модели и контракты входов. |
| `run_tests.py --suite rtl` | Отдельная инфраструктурная приёмка: `run_rtl.py --suite all`, `run_bpsk.py --suite all`, затем `run_rtl_synth.py`; нужны обе системы синтеза. `--modem` здесь не поддерживается. |
| `run_research.py` | `--suite python/octave/matlab/hdl/all`, `--workspace filters/windowed_sinc` или другой ID из каталога. `all` объединяет Python, Octave и HDL; MATLAB выбирается отдельно. Название research не означает, что обычный численный запуск исполняет сторонний код. |
| `run_streaming_rtl.py` | `--suite python/lint/hdl/all`, `--blocks` с одним или несколькими именами. 17 наборов: `fft ofdm stft pfb fir oset fsk beam sync lms ldpc mmse mmse3 mmse_n rls omlsa oqpsk`. В HDL/all также проверяются потоковый и saturation-checker. Синтез не запускается. |
| `run_rtl.py` | `--suite python/lint/hdl/all`; `--block complex_mul/complex_add/resize` выбирает HDL-проверку примитива. Lint проверяет полный список top. Есть `--questa-bin` и новый изолированный `--output`. |
| `run_bpsk.py` | `--suite python/lint/hdl/all`, необязательный новый `--output`; BPSK TX/RX, точность и численные HDL-scoreboard. Для классового UVM используется отдельный `run_bpsk_uvm.py`. |
| `run_questa.sh` | Bash-обёртка `run_hdl.py`; `--all` или `--modem NAME`, а также `--vectors` для одного модема и `--output-dir`. Это поведенческие кадровые модели. |

Базовый формат отсчётов RTL-примитивов — signed18 Q15; правила округления/насыщения конкретных блоков различаются. Полные контракты находятся в [common/README.md](../common/README.md), [RTL_CONTRACT.md](../docs/RTL_CONTRACT.md) и профильных документах [docs/README.md](../docs/README.md). Общей формулы латентности для всех runner нет.

## Структура каталога

В столбце опций приведены имена аргументов, объявленные в коде; допустимые значения смотрите через `--help`. «Импортируемый модуль» не является самостоятельной командой запуска. Обозначение `NumPy/SciPy` у вспомогательных модулей относится к используемым ими моделям и опорам; не каждому модулю нужны обе библиотеки.

### Главные точки входа

| Скрипт | Назначение | Основные опции | Требуемые инструменты |
| --- | --- | --- | --- |
| [run_tests.py](run_tests.py) | Общая регрессия кадровых/блочных моделей и расширенных проверок. | `--suite`, `--modem` | Python, NumPy/SciPy, pytest, PyYAML; Octave/Questa/UVM по suite; Vivado+Quartus для rtl |
| [run_research.py](run_research.py) | Блочные DSP-модели Python/Octave/MATLAB и поведенческий UVM. | `--suite`, `--workspace` | Python, NumPy/SciPy; Octave, MATLAB или Questa/UVM по suite |
| [run_streaming_rtl.py](run_streaming_rtl.py) | Объединение 17 потоковых FFT/DSP/OQPSK-наборов без синтеза Vivado/Quartus. | `--suite`, `--blocks` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_rtl.py](run_rtl.py) | Базовые fixed-point примитивы: Python, строгий lint, потоковый UVM и support-проверки. | `--suite`, `--block`, `--questa-bin`, `--output` | Python, NumPy, PyYAML; Verilator для lint, Questa/UVM для hdl |
| [run_bpsk.py](run_bpsk.py) | BPSK TX/RX: integer-опора, точность, строгий lint и Questa scoreboard. | `--suite`, `--output` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_questa.sh](run_questa.sh) | Запуск кадрового поведенческого SV/UVM через run_hdl.py. | `--all`, `--modem`, `--vectors`, `--output-dir` | Bash, Python, NumPy, Questa/UVM 1.2, GCC |

### Запускаемые проверки моделей, HDL, протокола и темпа

| Скрипт | Назначение | Основные опции | Требуемые инструменты |
| --- | --- | --- | --- |
| [run_stream_cfg_priority.py](run_stream_cfg_priority.py) | Направленные проверки приоритета конфигурации beamformer/Alamouti, PFB и OM-LSA; обе полярности reset и численные отрицательные контроли. | `--blocks`, `--simulator`, `--output-dir` | Python, NumPy; Questa либо Verilator, make и компилятор C++ |
| [bpsk_acquisition_check.py](bpsk_acquisition_check.py) | Битовые проверки BPSK acquisition/RX в Verilator; без Questa и без заявления UVM. | `--output`, `--profiles`, `--direct-only`, `--jobs`, `--quick` | Python, NumPy, Verilator, make и компилятор C++ |
| [bpsk_rx_continuous_rate.py](bpsk_rx_continuous_rate.py) | Конечное непрерывное предложение кадров BPSK RX с измерением backpressure. | `--backend`, `--output` | Python, NumPy; Questa или Verilator/make/C++ по backend |
| [dsp_stream_rates.py](dsp_stream_rates.py) | Реальные такты принятых DSP-передач из независимого VCD-reader. | `--case`, `--jobs` | Python, NumPy/SciPy, Questa |
| [modem_stream_rates.py](modem_stream_rates.py) | Измерение модемных интерфейсов и записей capture RAM по UVM VCD. | `--case`, `--jobs` | Python, NumPy/SciPy, Questa |
| [run_adaptive_protocol.py](run_adaptive_protocol.py) | Независимые valid/ready-источники для границ конфигурации/данных LMS/RLS. | `--core`, `--expect-failure`, `--label` | Python, NumPy/SciPy, Questa |
| [run_axis_contract.py](run_axis_contract.py) | Удержание передачи, отмена сбросом и отрицательные контроли потокового checker. | Без CLI-опций | Python, NumPy/SciPy, Questa |
| [run_beam.py](run_beam.py) | Beamformer/Alamouti: integer-опора, строгий lint, Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_bpsk_uvm.py](run_bpsk_uvm.py) | Классовый UVM потоковых BPSK RX/TX и всех зарегистрированных общих RX-профилей. | `--suite`, `--pilot`, `--profile`, `--jobs`, `--output` | Python, NumPy/SciPy; Questa/UVM для hdl |
| [run_cic_models.py](run_cic_models.py) | Независимая численная приёмка Python CIC, без запуска HDL. | `--output` | Python, NumPy/SciPy по используемой модели |
| [run_costas_protocol.py](run_costas_protocol.py) | Направленные границы конфигурации/кадров Costas с независимой численной сверкой. | `--expect-rejection`, `--output` | Python, NumPy/SciPy, Questa |
| [run_costas_stream.py](run_costas_stream.py) | Конвейерный Costas: модель, строгий lint, Questa, возмущения и измерение задержки петли. | `--suite`, `--output-dir` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_costas_stream_acquisition.py](run_costas_stream_acquisition.py) | Questa-подтверждение конечной сетки захвата QPSK; без синтеза. | `--output-dir` | Python, NumPy/SciPy, Questa |
| [run_cpm.py](run_cpm.py) | MSK/GMSK TX/RX: integer-опора, строгий lint, Questa scoreboard. | `--suite`, `--output` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_cpm_uvm.py](run_cpm_uvm.py) | UVM передатчиков MSK/GMSK: геометрия отсчётов и reset при удерживаемом выходе. | `--suite`, `--profile` | Python, NumPy/SciPy; Questa/UVM для hdl |
| [run_dsp_uvm.py](run_dsp_uvm.py) | UVM production DSP-потоков, конфигураций, весов и дополнительных физических выходов. | `--suite`, `--case`, `--jobs` | Python, NumPy/SciPy; Questa/UVM для hdl |
| [run_extended_dsp_models.py](run_extended_dsp_models.py) | Приёмка 44 Python-модельных этапов; нужны планы, каталоги, baseline и эталонные данные сверх манифестов. | `--group`, `--output` | Python, NumPy/SciPy, pytest; полный комплект приёмочных метаданных |
| [run_fft.py](run_fft.py) | FFT: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_fft_uvm.py](run_fft_uvm.py) | UVM FFT: геометрии, ширины, направления, границы, сбросы и неверный TLAST. | `--suite`, `--case` | Python, NumPy/SciPy; Questa/UVM для hdl |
| [run_filter_models.py](run_filter_models.py) | Численная приёмка компенсации CIC и рационального ресэмплинга, без HDL. | `--output` | Python, NumPy/SciPy по используемой модели |
| [run_fir.py](run_fir.py) | Runtime FIR: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_fsk.py](run_fsk.py) | M-FSK TX/RX: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_fsk_ldpc_protocol.py](run_fsk_ldpc_protocol.py) | Границы потоковой конфигурации FSK и LDPC/GF(2) на физических портах. | `--before`, `--block`, `--case`, `--output` | Python, NumPy/SciPy, Questa |
| [run_hdl.py](run_hdl.py) | Поведенческий кадровый SV/UVM с общими векторами и отрицательным контролем. | `--modem`, `--all`, `--vectors`, `--output-dir` | Python, NumPy, Questa/UVM 1.2, GCC |
| [run_ldpc.py](run_ldpc.py) | LDPC/GF(2): integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_lms.py](run_lms.py) | LMS/NLMS: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_matlab_evidence.py](run_matlab_evidence.py) | Фиксация хешей до MATLAB и публикация свидетельства после проверки результата. | `--suite`, `--modem` | Python, NumPy; исторические исходники/результаты; MATLAB/Simulink для исполнения оригиналов |
| [run_mmse.py](run_mmse.py) | MMSE2/ZF: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_mmse3.py](run_mmse3.py) | MMSE3: integer-опора, lint, потоковые/reset/error-проверки Questa. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_mmse3_rates.py](run_mmse3_rates.py) | Измерения реальных конфигураций и отсчётов MMSE3; отдельная валидация отчёта или CSV. | `--suite`, `--output`, `--validate`, `--analyze-trace`, `--profile`, `--reset-active`, `--mode`, `--length`, `--frames` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_mmse_n.py](run_mmse_n.py) | MMSE_N: integer-опора, строгий lint и Questa; векторами покрыты N=2,3,4,5,8. | `--suite`, `--jobs` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_ofdm.py](run_ofdm.py) | OFDM TX/RX: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_omlsa.py](run_omlsa.py) | OM-LSA: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_oqpsk.py](run_oqpsk.py) | OQPSK TX/RX: integer-опора, строгий lint и Questa scoreboard. | `--suite`, `--output` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_oqpsk_uvm.py](run_oqpsk_uvm.py) | UVM OQPSK TX: рукопожатия, сбросы и отрицательные контроли. | `--suite` | Python, NumPy/SciPy; Questa/UVM для hdl |
| [run_oset.py](run_oset.py) | Notch/Kalman: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_oset_gardner_protocol.py](run_oset_gardner_protocol.py) | Границы конфигурации notch/Kalman/Gardner и численные трассы физических портов. | `--before`, `--block`, `--output` | Python, NumPy/SciPy, Questa |
| [run_packet_rx_uvm.py](run_packet_rx_uvm.py) | UVM OQPSK/MSK/GMSK RX на production-волнах с независимым floating SER. | `--suite`, `--profile` | Python, NumPy/SciPy; Questa/UVM для hdl |
| [run_pfb.py](run_pfb.py) | PFB: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_psk_tx_uvm.py](run_psk_tx_uvm.py) | UVM всех PSK/QAM TX-профилей: метки, волна и геометрия кадров. | `--suite`, `--profile`, `--jobs` | Python, NumPy/SciPy; Questa/UVM для hdl |
| [run_rls.py](run_rls.py) | RLS: integer-опора, lint, Questa и прямая сверка девяти групп ограничителей. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_rtl_synth.py](run_rtl_synth.py) | Размещение/трассировка RTL в Vivado и Quartus с приёмкой предупреждений и timing. | `--quartus-phase`, `--block`, `--vendor` | Python, PyYAML, Vivado и/или Quartus |
| [run_sat_event.py](run_sat_event.py) | Checker signed72 насыщения: реальные наблюдения, gating и отрицательные контроли. | Без CLI-опций | Python, NumPy/SciPy, Questa |
| [run_sat_group.py](run_sat_group.py) | Checker групп signed128: агрегация lanes, разрешения и отрицательные контроли. | Без CLI-опций | Python, NumPy/SciPy, Questa |
| [run_stft.py](run_stft.py) | STFT/ISTFT: integer-опора, строгий lint и Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_stream_rates.py](run_stream_rates.py) | Такты FIR/FFT: отдельные burst, fill/drain и конечные стационарные окна. | `--long-only`, `--require-inner-one`, `--output` | Python, NumPy/SciPy, Questa |
| [run_sync.py](run_sync.py) | Costas/Gardner: integer-опора, строгий lint, Questa scoreboard. | `--suite` | Python, NumPy/SciPy; Verilator для lint, Questa для hdl |
| [run_sync_adaptive_rates.py](run_sync_adaptive_rates.py) | Фактические такты Costas/Gardner/LMS/NLMS/RLS по интерфейсным CSV. | `--profile`, `--output` | Python, NumPy/SciPy, Questa |

### Точность, разрядности и исследования нагрузок

| Скрипт | Назначение | Основные опции | Требуемые инструменты |
| --- | --- | --- | --- |
| [adaptive_precision.py](adaptive_precision.py) | Точность полных LMS/NLMS/RLS-петель на общих квантованных данных. | `--output` | Python, NumPy/SciPy по используемой модели |
| [alamouti_width_sweep.py](alamouti_width_sweep.py) | Точные границы энергии, произведений и сумм Alamouti до ограничения. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [axis_fifo_sweep.py](axis_fifo_sweep.py) | Точная вместимость FIFO и интеграция конечной нагрузки с Costas. | `--verify-rtl`, `--jobs`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [beam_energy_study.py](beam_energy_study.py) | Границы энергии коэффициентов beamformer и reciprocal. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [bpsk_precision.py](bpsk_precision.py) | Локальные SQNR BPSK и payload SER с независимой floating-опорой. | `--output` | Python, NumPy/SciPy по используемой модели |
| [costas_acquisition.py](costas_acquisition.py) | Конечная сетка захвата обычной integer Costas с известной фазой несущей. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [costas_stream_acquisition.py](costas_stream_acquisition.py) | Конечная модельная сетка захвата delayed Costas; новый JSON, без RTL-приёмки. | `--output` | Python, NumPy/SciPy по используемой модели |
| [cpm_precision.py](cpm_precision.py) | Полный fixed CPM TX/канал/RX, локальная точность и независимый итоговый SER. | `--output` | Python, NumPy/SciPy по используемой модели |
| [fft_fir_precision.py](fft_fir_precision.py) | Точность FFT/FIR и диапазоны значений до ограничения относительно NumPy. | `--output` | Python, NumPy/SciPy по используемой модели |
| [fft_width_sweep.py](fft_width_sweep.py) | Перебор WIDTH FFT при неизменных Q15-входах и Q16 twiddle. | `--output`, `--verify-rtl` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [fifo_load_sweep.py](fifo_load_sweep.py) | Конечные детерминированные нагрузки FIFO перед production Costas с II=8. | `--verify-rtl`, `--output`, `--jobs` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [fir_width_sweep.py](fir_width_sweep.py) | Точные интервалы FIR и сравнение сокращённого дерева с прежней арифметикой. | `--output`, `--verify-rtl` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [istft_width_sweep.py](istft_width_sweep.py) | Точные границы произведений и overlap-add ISTFT до насыщения. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [ldpc_precision.py](ldpc_precision.py) | Полный LDPC относительно независимого floating decoder и точная проверка GF(2). | `--output` | Python, NumPy/SciPy по используемой модели |
| [linear_precision.py](linear_precision.py) | Независимая точность MMSE2/MMSE3, beamformer и Alamouti на общих Q15-словах. | `--output` | Python, NumPy/SciPy по используемой модели |
| [lms_energy_study.py](lms_energy_study.py) | Границы энергии истории LMS/NLMS и reciprocal-нормировки. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [lms_fifo_load_sweep.py](lms_fifo_load_sweep.py) | Конечные нагрузки WIDTH72 FIFO с LMS/NLMS и независимыми остановками выходов. | `--verify-rtl`, `--output`, `--jobs` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [lms_width_sweep.py](lms_width_sweep.py) | Точные промежуточные ширины LMS/NLMS: оценка, ошибка, шаг, веса и dump. | `--verify-rtl`, `--jobs`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [loop_delay_study.py](loop_delay_study.py) | Линейная устойчивость и прогон битоточных приёмников по задержкам обратной связи. | `--frames`, `--jobs`, `--output` | Python, NumPy/SciPy по используемой модели |
| [mmse2_width_sweep.py](mmse2_width_sweep.py) | Границы Gram/determinant/M, весов и сырых выходных сумм MMSE2. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [mmse3_config_width_sweep.py](mmse3_config_width_sweep.py) | Ширины конфигурационных выражений MMSE3, наблюдения и сравнение с прежним RTL. | `--verify-rtl`, `--jobs`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [mmse3_width_sweep.py](mmse3_width_sweep.py) | Границы Gram/выходов MMSE3 и проверка сырых промежуточных результатов. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [mmse_n_width_sweep.py](mmse_n_width_sweep.py) | Точные границы Gram и выходных аккумуляторов MMSE_N. | `--verify-rtl`, `--jobs`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [mmse_norm_back_sweep.py](mmse_norm_back_sweep.py) | Нормировка и обратная подстановка MMSE_N до преобразования ширины. | `--verify-rtl`, `--jobs`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [mmse_scale_update_sweep.py](mmse_scale_update_sweep.py) | Масштабирование весов MMSE3 и исключение MMSE_N до ограничения. | `--verify-rtl`, `--jobs`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [omlsa_width_sweep.py](omlsa_width_sweep.py) | Границы промежуточных выражений усиления OM-LSA и небезопасные сужения. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [oqpsk_mrc_precision.py](oqpsk_mrc_precision.py) | Полные OQPSK и двухветвевые MRC-эксперименты с независимой floating-опорой. | `--output` | Python, NumPy/SciPy по используемой модели |
| [pfb_width_sweep.py](pfb_width_sweep.py) | Фазовые аккумуляторы PFB и сравнение прежних/новых ширин. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [psk_precision.py](psk_precision.py) | Полные PSK/QAM fixed TX/RX и независимые floating-приёмники для каждого integer-профиля. | `--output` | Python, NumPy/SciPy по используемой модели |
| [rls_update_sweep.py](rls_update_sweep.py) | Точные RLS gain/update-произведения, округление, веса и ковариация. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [rls_width_sweep.py](rls_width_sweep.py) | Границы RLS dot-трактов на полных кодах и на адаптивных траекториях. | `--verify-rtl`, `--output` | Python, NumPy/SciPy; Questa при --verify-rtl |
| [rtl_precision.py](rtl_precision.py) | Исходное исследование квантования ADC; не полная симуляция fixed-point RX. | `--modem` | Python, NumPy/SciPy по используемой модели |
| [spectral_precision.py](spectral_precision.py) | Независимая точность PFB/STFT/OFDM/OM-LSA на общих квантованных входах. | `--output` | Python, NumPy/SciPy по используемой модели |
| [state_precision.py](state_precision.py) | Точность notch/Kalman/FSK на общих квантованных данных. | `--output` | Python, NumPy/SciPy по используемой модели |
| [sync_precision.py](sync_precision.py) | Независимые floating и fixed Costas-петли, SQNR и ошибки решений. | `--output` | Python, NumPy/SciPy по используемой модели |
| [timing_precision.py](timing_precision.py) | Полные floating/fixed timing-петли, индексы решений и проверка соответствия выходов. | `--output` | Python, NumPy/SciPy по используемой модели |

### Векторы, сценарии и общие проверки результатов

| Скрипт | Назначение | Основные опции | Требуемые инструменты |
| --- | --- | --- | --- |
| [beam_cases.py](beam_cases.py) | Векторы beamformer/Alamouti, коэффициенты и стресс перегрузки. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [bpsk_acquire_review.py](bpsk_acquire_review.py) | Направленные векторы захвата/делителя и строгие критерии покрытия состояний. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [bpsk_cases.py](bpsk_cases.py) | Детерминированные BPSK RX/TX/MRC-векторы и независимый шумовой канал. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [bpsk_rx_review.py](bpsk_rx_review.py) | Направленные сценарии арбитража и восстановления RX, проверка покрытия. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [bpsk_verilator.py](bpsk_verilator.py) | Сборка и запуск существующих макро-scoreboard через Verilator; вспомогательный адаптер. | Импортируемый модуль; без CLI | Python, NumPy, Verilator, make и компилятор C++ |
| [costas_stream_cases.py](costas_stream_cases.py) | Векторы конвейерного Costas с учётом задержек, пауз и возмущений. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [cpm_cases.py](cpm_cases.py) | Целочисленные MSK/GMSK TX/RX-векторы и результаты захвата. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [dsp_uvm_plans.py](dsp_uvm_plans.py) | Упаковка физических полей production DSP в UVM-транзакции без потери битов. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [fft_cases.py](fft_cases.py) | Векторы FFT, границы кадров, направления и ожидаемые насыщения ступеней. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [fir_cases.py](fir_cases.py) | Runtime FIR-векторы, комплексные коэффициенты и перегрузочные планы. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [fsk_cases.py](fsk_cases.py) | Конфигурация и TX/RX-векторы целочисленного M-FSK. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [ldpc_cases.py](ldpc_cases.py) | Векторы LDPC decoder и GF(2) encoder, матрицы и события ограничения. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [lms_cases.py](lms_cases.py) | Векторы LMS/NLMS, желаемый сигнал, выходы, ошибки, веса и насыщения. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [mmse3_cases.py](mmse3_cases.py) | Точные веса и тройки MMSE3, независимая floating-проверка. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [mmse_cases.py](mmse_cases.py) | Конфигурация и данные MMSE2/ZF, веса и перегрузочные сценарии. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [mmse_n_cases.py](mmse_n_cases.py) | Конфигурации, веса и N-компонентные потоки MMSE_N. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [ofdm_cases.py](ofdm_cases.py) | OFDM TX/RX-векторы, циклический префикс и встроенные FFT-ограничители. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [omlsa_cases.py](omlsa_cases.py) | Векторы конфигурации, шумового профиля и сигнала OM-LSA. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [oqpsk_cases.py](oqpsk_cases.py) | OQPSK TX/RX-векторы, захват, задержки и стресс необработанного входа RX. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [oqpsk_tracking.py](oqpsk_tracking.py) | Возмущение фазы OQPSK с известной несущей и контролем без обратной связи. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [oset_cases.py](oset_cases.py) | Notch/Kalman-векторы, конфигурации и перегрузочные случаи. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [pfb_cases.py](pfb_cases.py) | Полифазный анализирующий банк: коэффициенты, децимация, FFT и насыщения. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [regression_evidence.py](regression_evidence.py) | Хеши кода/артефактов, завершение и актуальность свидетельств, поиск Questa и UVM. | Импортируемый модуль; без CLI | Python; для таблиц также NumPy |
| [research_cases.py](research_cases.py) | Воспроизводимые блочные DSP-стимулы и независимые NumPy/SciPy-опоры. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [rls_cases.py](rls_cases.py) | Runtime RLS-векторы, веса/ковариация и девять групп насыщений. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [rtl_cases.py](rtl_cases.py) | Воспроизводимые integer-векторы complex add/multiply/resize и support-блоков. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [spectral_evidence.py](spectral_evidence.py) | Общая сверка спектральных ограничителей, встроенного FFT и отрицательных контролей. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [stft_cases.py](stft_cases.py) | Векторы STFT/ISTFT, overlap, длины, полная шкала и насыщения. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [sync_cases.py](sync_cases.py) | Векторы Costas/Gardner, петли, конфигурации и стресс ошибки. | Без CLI-опций | Python, NumPy/SciPy по используемой модели |
| [sync_scenarios.py](sync_scenarios.py) | Сценарии возмущения/срыва/восстановления Costas и Gardner с известной опорой. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [sync_slip_evidence.py](sync_slip_evidence.py) | Проверка реальных RTL-наблюдений срыва, возмущений и захвата Costas. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |
| [uvm_floating_reference.py](uvm_floating_reference.py) | Независимые floating-решения и валидаторы payload SER для UVM-приёмников. | Импортируемый модуль; без CLI | Python, NumPy/SciPy по используемой модели |

### Отчёты, исторические материалы и служебная подготовка

| Скрипт | Назначение | Основные опции | Требуемые инструменты |
| --- | --- | --- | --- |
| [export_public.py](export_public.py) | Копирование tracked и новых неигнорируемых файлов в новый внешний каталог с исключением исторических материалов и заменой локальных путей в тексте; правила очистки заданы в коде. | Позиционный `target`, `--git-init` | Python, Git; целевой каталог должен отсутствовать и находиться вне проекта |
| [audit_research.py](audit_research.py) | Аудит манифестов и целостности сторонних коллекций без исполнения их кода; нужны исходники. | Без CLI-опций | Python, манифесты и локальные сторонние материалы |
| [bpsk_tables.py](bpsk_tables.py) | Построение или проверка неизменности целочисленных таблиц BPSK. | `--check` | Python; для таблиц также NumPy |
| [check_contracts.py](check_contracts.py) | Допустимые границы и отказ неверных DSP-входов до вычислений в разных языках. | `--suite` | Python, NumPy/SciPy; Octave, MATLAB или Questa/UVM по suite |
| [check_matlab_msk.py](check_matlab_msk.py) | Сравнение переносимого MSK с реальными Simulink-отсчётами и подготовка UVM-векторов. | Без CLI-опций | Python, NumPy; исторические исходники/результаты; MATLAB/Simulink для исполнения оригиналов |
| [check_msk_matlab_rtl.py](check_msk_matlab_rtl.py) | Сравнение MSK RTL TX с сохранённым захватом исходной Simulink-схемы. | `--suite` | Python, NumPy, Questa; подготовленный MATLAB-захват MSK |
| [check_research_references.py](check_research_references.py) | Сравнение Python-аналогов с результатами отдельно исполненных исторических MATLAB-функций. | Без CLI-опций | Python, NumPy; исторические исходники/результаты; MATLAB/Simulink для исполнения оригиналов |
| [check_typed_browser.py](check_typed_browser.py) | Проверка представлений блочного HTML-атласа через Firefox Marionette, порт 2841. | Без CLI-опций | Python, Firefox с Marionette; готовый атлас |
| [check_visual_browser.py](check_visual_browser.py) | Проверка исторического HTML-атласа через уже запущенный Firefox Marionette. | `--port` | Python, Firefox с Marionette; готовый атлас |
| [coverage_report.py](coverage_report.py) | Сбор stream_cover из журналов завершённых Questa-наборов и проверка mode bins. | `blocks`, `--require-mode-bins` | Python; завершённые Questa-отчёты/журналы |
| [create_workspaces.py](create_workspaces.py) | Служебное создание кадровых рабочих каталогов и извлечение параметров; не требуется для запуска моделей. | Без CLI-опций | Python; локальные исторические материалы |
| [fft_tables.py](fft_tables.py) | Построение или проверка ROM twiddle FFT и окон STFT. | `--check` | Python; для таблиц также NumPy |
| [generate_validation.py](generate_validation.py) | Перезапись общих валидаторов входного контракта Python/Octave/SV из единого описания. | Без CLI-опций | Python; для таблиц также NumPy |
| [generate_vectors.py](generate_vectors.py) | Кадровые Python-стимулы и ожидаемые результаты для Octave и SV. | `--modem` | Python, NumPy/SciPy по используемой модели |
| [inventory.py](inventory.py) | Инвентаризация и безопасная распаковка исторических архивов; изменяет каталог извлечённых материалов. | Без CLI-опций | Python, 7z; UnRAR для solid RAR, переменная UNRAR |
| [prepare_matlab_originals.py](prepare_matlab_originals.py) | Создание совместимых с R2020b копий исторических MDL и migration-записей; нужны исходники. | Без CLI-опций | Python, NumPy; исторические исходники/результаты; MATLAB/Simulink для исполнения оригиналов |
| [report_matlab_originals.py](report_matlab_originals.py) | Формирование отчёта MATLAB: частичные совпадения mapper/MSK и ограничения эквивалентности. | Без CLI-опций | Python, NumPy; исторические исходники/результаты; MATLAB/Simulink для исполнения оригиналов |
| [report_results.py](report_results.py) | Сводный сохранённый отчёт из завершённой кадровой регрессии и связанных проверок. | Без CLI-опций | Python, NumPy; завершённые отчёты и исторические копии |
| [report_typed_results.py](report_typed_results.py) | Сводный блочный отчёт с проверкой исходников, MATLAB, контрактов и браузерных результатов. | Без CLI-опций | Python, NumPy; завершённые отчёты и исторические копии |
| [research_layout.py](research_layout.py) | Служебное создание блочных рабочих каталогов, source catalog и языковых обёрток. | Без CLI-опций | Python; локальные исторические материалы |
| [rtl_constraints.py](rtl_constraints.py) | Преобразование общего YAML timing-контракта в согласованные XDC/SDC. | `--source`, `--output` | Python, PyYAML |
| [setup_new_models.py](setup_new_models.py) | Служебное добавление новых кадровых моделей и обновление каталога. | Без CLI-опций | Python; локальные исторические материалы |
| [typed_visual_report.py](typed_visual_report.py) | Создание блочного HTML/PDF/PNG/SVG-атласа из проверенных численных результатов. | Без CLI-опций | Python, NumPy/SciPy, Matplotlib; готовые численные результаты и исторические данные |
| [visual_report.py](visual_report.py) | Создание исторического HTML/PDF/PNG/SVG-атласа и записи происхождения данных. | `--output` | Python, NumPy/SciPy, Matplotlib; готовые численные результаты и исторические данные |

### MATLAB, Bash, Tcl и ресурсы отчётов

| Файл / подкаталог | Назначение | Основные аргументы / среда |
| --- | --- | --- |
| [matlab.sh](matlab.sh) | Запускает выбранный MATLAB; настройка системной FreeType для R2020b действует только на дочерний процесс. | Аргументы передаются MATLAB; `MATLAB_ROOT`, `MATLAB_SYSTEM_FREETYPE`; Bash, MATLAB |
| [matlab_check_originals.m](matlab_check_originals.m) | Аудит, оригинальный или совместимый запуск исторических кадровых схем в памяти. | `matlab_check_originals(mode, modem_name, steps)`; режимы `audit`, `original`, `compatible`, default steps 16384; MATLAB/Simulink и исходники |
| [matlab_check_research.m](matlab_check_research.m) | Проверка двух дополнительных исторических Simulink-моделей. | `matlab_check_research(steps, model_name)`; default steps 16384; MATLAB/Simulink и исходники |
| [matlab_research_references.m](matlab_research_references.m) | Исполнение выбранных исторических DSP-функций для независимых эталонов. | `matlab_research_references()`; MATLAB и сторонние исходники |
| [matlab_smoke.m](matlab_smoke.m) | Контроль доступности MATLAB/Simulink и лицензий. | MATLAB; служебный скрипт, без argparse |
| [rtl_synth_vivado.tcl](rtl_synth_vivado.tcl) | Синтез/размещение/трассировка в Vivado и формирование отчётов. | Tcl-аргументы формирует `run_rtl_synth.py`; Vivado |
| [rtl_synth_quartus.tcl](rtl_synth_quartus.tcl) | Проект, параметры, назначения и компиляция Quartus. | Tcl-аргументы формирует `run_rtl_synth.py`; Quartus |
| [rtl_timing_quartus.tcl](rtl_timing_quartus.tcl) | Timing-отчёты Quartus/TimeQuest. | Проект и выходной каталог от vendor runner; Quartus |
| [rtl_resources_quartus.tcl](rtl_resources_quartus.tcl) | Извлечение ресурсов из отчётов Quartus. | Проект от vendor runner; Quartus report API |
| [rtl_pins_quartus.tcl](rtl_pins_quartus.tcl) | Детерминированный выбор package pins для измерительного стенда; это не распиновка платы. | Part и файл назначений от vendor runner; Quartus advanced_device API |
| [visual_report_assets](visual_report_assets) | HTML/CSS/JS-шаблоны исторического атласа. | Используются `visual_report.py` |
| [typed_visual_assets](typed_visual_assets) | HTML/CSS/JS-шаблоны блочного атласа. | Используются `typed_visual_report.py` |

`create_workspaces.py`, `research_layout.py` и `setup_new_models.py` — служебные генераторы рабочих каталогов. Они записывают конфигурации, обёртки и другие файлы проекта; для обычного запуска и чтения вручную поддерживаемых README их выполнять не требуется. `generate_validation.py`, ROM-генераторы, подготовка MATLAB-копий и публикация отчётов также имеют файловые побочные эффекты, указанные в таблицах.

## Как запустить

Команды ниже выполняются из корня проекта. Все Python-зависимости (NumPy, SciPy, PyYAML, Matplotlib, pytest) находятся в [requirements.txt](../requirements.txt). Для Questa нужны `vlib`, `vlog`, `vsim` и UVM 1.2. Поиск установки использует `QUESTA_HOME` либо `vsim` в PATH, библиотека выбирается через `UVM_HOME`, GCC — через `DPI_CC`. Строгий lint требует Verilator; компиляция C++-scoreboard также требует make и компилятор C++.

```bash
# Уточнить интерфейс основной команды
python3 tools/run_tests.py --help

# Публичная поставка: выбранные независимые Python-тесты без исторических исходников
PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -p no:cacheprovider -q tests/test_fixed_point.py tests/test_cic_models.py tests/test_filter_models.py

# Полная локальная поставка с исходниками: кадровые unittest и точностные исследования
python3 tools/run_tests.py --suite python

# Кадровая проверка Python/Octave на общих векторах
python3 tools/run_tests.py --suite cross --modem bpsk_costas_2008_08_25

# Поведенческий SV/UVM одного кадрового модема
bash tools/run_questa.sh --modem bpsk_costas_2008_08_25

# Независимая блочная модель Python
python3 tools/run_research.py --suite python --workspace coding/ldpc

# Все 17 потоковых наборов: integer-опора, lint, Questa; без синтеза
python3 tools/run_streaming_rtl.py --suite all

# Базовые RTL-примитивы; затем BPSK TX/RX
python3 tools/run_rtl.py --suite all
python3 tools/run_bpsk.py --suite all
```

`all` у разных runner имеет разный состав — используйте таблицу режимов выше. У `run_tests.py --suite python/all` два теста из `test_primitives.py` читают непубличные исторические файлы; без каталога `sources/` они явно пропускаются.

MATLAB запускается отдельными режимами `run_matlab_evidence.py` или `run_research.py --suite matlab`. Для исполнения исторических схем нужны исходники, Simulink и используемые ими toolbox; состав локальной установки R2020b зафиксирован в [MATLAB_INSTALLATION.md](../docs/MATLAB_INSTALLATION.md). Обычные M-функции из `common/octave` не загружают MDL/SLX.

`--verify-rtl` у sweep/study добавляет настоящие Questa-прогоны к модельному расчёту. `--output` у разных инструментов означает либо JSON-файл, либо каталог; точный тип смотрите в `--help`. Например, `run_bpsk.py`/`run_rtl.py` требуют новый каталог при явном `--output`, `run_cic_models.py`/`run_filter_models.py` — новый JSON-путь; существующие результаты в этих режимах не перезаписываются. Runner без изолированного пути часто используют фиксированный `build/…`, поэтому параллельные запуски одного набора могут конфликтовать.

Vendor synthesis запускается только отдельным `run_rtl_synth.py` или через `run_tests.py --suite rtl`. Настройки установок — `VIVADO_ROOT`, `QUARTUS_ROOT`; дополнительные требования и ограничения — в [RTL_CONTRACT.md](../docs/RTL_CONTRACT.md). Режимы `--before`, `--expect-failure` и `--expect-rejection` предназначены для направленных исторических/отрицательных экспериментов согласно коду конкретного runner и не должны подменять штатную приёмку.

## Что смотреть

| Запуск | Результаты |
| --- | --- |
| `run_tests.py --suite SUITE` | `build/SUITE_results.json`, журналы в `build/logs/`; при `--modem` — `build/single/NAME/` |
| `run_questa.sh` / `run_hdl.py` | `build/questa/results.json`, compile/simulation/negative-журналы; при одном модеме — `build/questa/single/NAME/` |
| `run_research.py` | `build/typed/SUITE_results.json`, `cases.json`, `case_*.npz`, `vectors.txt`, языковые журналы; `--workspace` добавляет каталог с `/`, заменённым на `__` |
| `run_streaming_rtl.py` | `build/rtl/streaming/SUITE_results.json` и журналы блоков; дочерние отчёты в `build/rtl/BLOCK/` |
| `run_rtl.py` | `build/rtl/SUITE_results.json`; `--block` — `build/rtl/single/BLOCK/`, явный `--output` меняет корень |
| `run_bpsk.py` | `build/rtl/bpsk/SUITE_results.json`, `precision_results.json`, журналы и векторы |
| UVM и sweep/study | Собственный каталог `build/rtl/…`; точные default-пути заданы в соответствующем скрипте |
| `run_cic_models.py`, `run_filter_models.py` | По умолчанию `build/cic_models_20261030/results.json`, `build/filter_models/results.json` и соседний `.unittest.log` |
| `run_extended_dsp_models.py` | Без группы default — `docs/extended_dsp_models_20261030_results.json`; с группой — `build/full_dsp_20261030/acceptance/GROUP_results.json`; `--output` меняет файл |
| `run_rtl_synth.py` | `build/rtl/synth/results.json`, vendor-журналы, отчёты ресурсов и timing |

Успешный запуск возвращает 0 и публикует завершённый `PASS`. Штатные UVM-журналы требуют нулевых ошибок/fatal и полного числа транзакций; отрицательные контроли должны обнаруживать конкретное нарушение. Число насыщений сравнивается вместе с числом вычислений: ноль событий сам по себе не доказывает работу наблюдателя.

BER/SER измеряют доли ошибочных битов/символов полезной части, SQNR — мощность опоры относительно ошибки. Локальная арифметическая точность и качество полной независимой петли описаны отдельно в [RTL_PRECISION.md](../docs/RTL_PRECISION.md). Измерения темпа разделяют принятие данных, латентность, burst и fill/drain; они не определяют физический Fmax.

Для просмотра готовых графиков откройте [кадровый атлас](../docs/visual/index.html), [блочный атлас](../docs/typed_visual/index.html) или соответствующие [PDF кадров](../docs/visual/modem_test_report.pdf) и [PDF блоков](../docs/typed_visual/modem_test_report.pdf). Указатель всех технических отчётов — [docs/README.md](../docs/README.md).

## Ограничения

Все режимы с именем Python не равнозначны: где-то это unit-тесты и независимые численные проверки, где-то подготовка векторов для последующего HDL. Полный HDL-прогон обязателен для подтверждения совпадения с RTL. Поведенческая обработка кадра за один такт не является аппаратной пропускной способностью.

Сохранённые отчёты привязаны к снимку исходников. После удаления сторонних материалов, изменения кода или состава файлов проверка актуальности старых результатов может отказать. `report_results.py`, `report_typed_results.py`, аудит коллекций и проверки MATLAB-оригиналов требуют полного набора предусмотренных входов; просмотр уже опубликованных HTML/PDF их не требует.

`run_extended_dsp_models.py` читает не только манифесты, но и план, каталоги задач, baseline-файлы, контракты и эталонные JSON. Публичная очистка с сохранением одних манифестов не сохраняет работоспособность этого сводного приёмочного runner; отдельные численные тесты расширенных моделей используют собственный код и `tests/data/`.

Проверка команд в этом README выполнена по исходникам и `--help`; она не означает повторный прогон симуляторов, MATLAB или синтеза. Исторические PASS и длительности относятся к конкретным контрольным точкам; универсальное время исполнения не установлено.
