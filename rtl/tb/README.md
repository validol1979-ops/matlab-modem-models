# Проверка потокового RTL: SV и UVM

Самопроверяющие тестбенчи fixed-point модемов и DSP-блоков, UVM-окружения и независимые наблюдатели протокола, памяти, разрядностей и насыщения. Запуском, подготовкой векторов и проверкой полноты результатов управляют Python-раннеры в `tools/`.

## Что это

Каталог содержит проверочный код, который не входит в синтезируемый тракт. Эталонные целочисленные вычисления находятся в [common/python](../../common/python/), векторы и планы — в [tools](../../tools/), Python-тесты раннеров и арифметики — в [tests](../../tests/). Для ряда RX есть дополнительный независимый вещественный приёмник на тех же входных Q15-отсчётах.

Здесь используются два уровня проверки: самопроверяющие SV-тесты конкретных узлов и полноценные UVM sequence/sequencer/driver/monitor/scoreboard/env/test. Наличие `uvm_fatal` в численном тесте само по себе не превращает его в полноценное UVM-окружение. Историческая полная UVM-матрица описана в [RTL_DSP_UVM.md](../../docs/RTL_DSP_UVM.md), [RTL_BPSK_UVM.md](../../docs/RTL_BPSK_UVM.md) и [RTL_PACKET_RX_UVM.md](../../docs/RTL_PACKET_RX_UVM.md); результаты зависят от снимка исходников.

## Как работает

1. Python строит конфигурации, входные транзакции и независимые ожидаемые выходы. Полезная нагрузка хранится отдельно от решений приёмника.
2. Driver подаёт реальные конфигурационные и входные слова, соблюдая valid/ready. Монитор учитывает только принятые передачи на фронтах такта.
3. Scoreboard сравнивает все значащие биты результата, `last`, метки, состояния петель и оценки захвата; геометрия кадра проверяется независимо от длины ожидаемого файла.
4. Мониторы проверяют удержание ожидающей передачи, известность сигналов, индексы/доступность памяти, границы арифметики и реальные события насыщения.
5. Паузы и сбросы проверяют отмену действительно принятой работы и повторный запуск. Отрицательные контроли намеренно портят данные/протокол: тест обязан обнаружить нужную ошибку.
6. Runner сверяет код возврата, маркеры, счётчики и полноту сценариев; завершённый JSON связывает результат с хешами исходников и артефактов.

| Соглашение/параметр | Применение |
| --- | --- |
| `RESET_ACTIVE=1/0` | Обе полярности синхронного сброса в основных матрицах |
| `+VECTORS=<каталог/файл>` | Путь к подготовленным векторам; формат зависит от тестбенча |
| `valid && ready` | Единственное условие фактической передачи слова |
| I/Q signed 18/15 | Типовой временной формат DUT; спектры могут быть 24/19, LDPC LLR — 16/8 |
| `stream`, `gaps`, `stalled` | Плотный вход, паузы источника, противодавление; точный набор зависит от runner |
| `midreset`, `outreset`, `cfgreset` | Сброс принятого фрагмента, удерживаемого последнего выхода, незавершённой конфигурации — где применимо |
| `woutreset` | Отдельный сброс удерживаемого последнего веса адаптивного фильтра |
| SER пакетного RX | Ошибочные метки / полезные символы после 192 обучающих меток; при пустой нагрузке не определена |

В DSP UVM внешние поля упакованы в 512-битное слово с нулевым дополнением. Это представление для проверки, а не формат интерфейса DUT: исходные разрядности, знаковость и все поля сохраняются. У LMS/RLS отдельные монитор и очередь для `w_*`; нельзя считать тест законченным после одного только потока prediction/error.

## Структура каталога

Основные численные наборы:

| Файл/группа | Раннер `tools/*.py` | Что проверяется |
| --- | --- | --- |
| [stream_tb.sv](stream_tb.sv), [support_tb.sv](support_tb.sv) | [run_rtl.py](../../tools/run_rtl.py) | UVM начальной complex add/mul/resize: I/Q, overflow, last, латентность; отдельно RAM/ROM, округление и синхронизаторы |
| [bpsk_blocks_tb.sv](bpsk_blocks_tb.sv), [bpsk_rx_tb.sv](bpsk_rx_tb.sv), [mrc_blocks_tb.sv](mrc_blocks_tb.sv), [rx_cfg_priority_tb.sv](rx_cfg_priority_tb.sv) | [run_bpsk.py](../../tools/run_bpsk.py) | Общая PSK/QAM-арифметика, захват/RX, MRC-веса и отказы, приоритет конфигурации и данных |
| [bpsk_acquire_tb.sv](bpsk_acquire_tb.sv), [bpsk_divide_modes_tb.sv](bpsk_divide_modes_tb.sv) | [run_bpsk.py](../../tools/run_bpsk.py), [bpsk_acquisition_check.py](../../tools/bpsk_acquisition_check.py) | Прямой scoreboard захвата, повтор сразу после done, reset занятого блока; сравнение двух режимов делителя |
| [bpsk_rx_buffers_tb.sv](bpsk_rx_buffers_tb.sv), [bpsk_rx_rate_tb.sv](bpsk_rx_rate_tb.sv) | [run_bpsk.py](../../tools/run_bpsk.py) — guards; [bpsk_rx_continuous_rate.py](../../tools/bpsk_rx_continuous_rate.py) — guards/rate | Кольцо двух полных/одного короткого буфера, длины и ошибочный TLAST, конечные серии и обязательный FIR-хвост |
| [cpm_tb.sv](cpm_tb.sv) | [run_cpm.py](../../tools/run_cpm.py) | MSK/GMSK TX/RX, захват, когерентный GMSK и границы кадров |
| [cpm_acquisition_check.sv](cpm_acquisition_check.sv) | [run_packet_rx_uvm.py](../../tools/run_packet_rx_uvm.py) | Независимый наблюдатель эпох захвата CPM, в том числе повторного захвата при противодавлении |
| [cpm_tx_dump_tb.sv](cpm_tx_dump_tb.sv) | [check_msk_matlab_rtl.py](../../tools/check_msk_matlab_rtl.py) | MSK TX против `cpm_fixed` и сохранённого MATLAB-захвата с прореживанием 32→8 sps |
| [oqpsk_tb.sv](oqpsk_tb.sv) | [run_oqpsk.py](../../tools/run_oqpsk.py) | Сдвиг Q, TX/RX, захват, split Costas, loopback, фазовые возмущения и вложенные FIR/CORDIC/divider |
| [fft_tb.sv](fft_tb.sv), [ofdm_tb.sv](ofdm_tb.sv), [stft_tb.sv](stft_tb.sv), [pfb_tb.sv](pfb_tb.sv) | [run_fft.py](../../tools/run_fft.py), [run_ofdm.py](../../tools/run_ofdm.py), [run_stft.py](../../tools/run_stft.py), [run_pfb.py](../../tools/run_pfb.py) | FFT/IFFT, направление/порядок, CP, STFT/ISTFT, PFB; значения, границы памяти, насыщения и сброс |
| [fir_tb.sv](fir_tb.sv), [fir_protocol_tb.sv](fir_protocol_tb.sv) | [run_fir.py](../../tools/run_fir.py) | Полная свёртка L+T−1, комплексные отводы, число полос, частичные суммы, переконфигурация и FIFO |
| [oset_tb.sv](oset_tb.sv), [fsk_tb.sv](fsk_tb.sv), [beam_tb.sv](beam_tb.sv) | [run_oset.py](../../tools/run_oset.py), [run_fsk.py](../../tools/run_fsk.py), [run_beam.py](../../tools/run_beam.py) | Notch/Kalman; M-FSK TX/RX; beamforming и Alamouti, включая нормировку и отказы |
| [sync_tb.sv](sync_tb.sv), [costas_stream_tb.sv](costas_stream_tb.sv) | [run_sync.py](../../tools/run_sync.py), [run_costas_stream.py](../../tools/run_costas_stream.py), [run_costas_stream_acquisition.py](../../tools/run_costas_stream_acquisition.py) | Последовательные Costas/Gardner; непрерывный Costas II=1, фаза, продвижения конвейера, паузы и конечная сетка захвата |
| [lms_tb.sv](lms_tb.sv), [rls_tb.sv](rls_tb.sv), [ldpc_tb.sv](ldpc_tb.sv) | [run_lms.py](../../tools/run_lms.py), [run_rls.py](../../tools/run_rls.py), [run_ldpc.py](../../tools/run_ldpc.py) | LMS/NLMS/RLS: prediction/error и веса; LDPC: четыре режима, hard bit/posterior, GF(2)-кодер |
| [mmse_tb.sv](mmse_tb.sv), [mmse3_tb.sv](mmse3_tb.sv), [mmse_n_tb.sv](mmse_n_tb.sv), [mmse_protocol_tb.sv](mmse_protocol_tb.sv) | [run_mmse.py](../../tools/run_mmse.py), [run_mmse3.py](../../tools/run_mmse3.py), [run_mmse_n.py](../../tools/run_mmse_n.py) | Конфигурация/веса MMSE/ZF, выходы, пары/тройки/N-ки, вырожденность, частичный кадр и резервирование FIFO |
| [omlsa_tb.sv](omlsa_tb.sv) | [run_omlsa.py](../../tools/run_omlsa.py) | Отражённые края, спектральное усиление, восстановление исходной длины, численная точность и насыщения |

Полноценные UVM-окружения внешних контактов:

| Файл/группа | Раннер | Что проверяется |
| --- | --- | --- |
| [bpsk_rx_uvm_tb.sv](bpsk_rx_uvm_tb.sv) | [run_bpsk_uvm.py](../../tools/run_bpsk_uvm.py); пакетные адаптеры — [run_packet_rx_uvm.py](../../tools/run_packet_rx_uvm.py) | Все 14 PSK/QAM RX-профилей, включая SIMO; OQPSK/MSK/GMSK RX; принятые данные/захват, отдельная payload truth и независимая float SER |
| [bpsk_tx_uvm_tb.sv](bpsk_tx_uvm_tb.sv), [modem_tx_uvm.svh](modem_tx_uvm.svh) | [run_bpsk_uvm.py](../../tools/run_bpsk_uvm.py) | BPSK TX, геометрия кадров, реальные handshakes, противодавление, сбросы и число отброшенных слов |
| [psk_tx_uvm_tb.sv](psk_tx_uvm_tb.sv), [oqpsk_tx_uvm_tb.sv](oqpsk_tx_uvm_tb.sv), [cpm_tx_uvm_tb.sv](cpm_tx_uvm_tb.sv) | [run_psk_tx_uvm.py](../../tools/run_psk_tx_uvm.py), [run_oqpsk_uvm.py](../../tools/run_oqpsk_uvm.py), [run_cpm_uvm.py](../../tools/run_cpm_uvm.py) | 13 остальных PSK/QAM TX-профилей, OQPSK и MSK/GMSK TX, ширины меток и семейная геометрия `8N+tail` |
| [fft_uvm_tb.sv](fft_uvm_tb.sv) | [run_fft_uvm.py](../../tools/run_fft_uvm.py) | FFT на внешних контактах, направление, кадры, сбросы и отрицательные контроли |
| [dsp_stream_uvm_tb.sv](dsp_stream_uvm_tb.sv), [dsp_stream_uvm.svh](dsp_stream_uvm.svh) | [run_dsp_uvm.py](../../tools/run_dsp_uvm.py) | 128 конфигураций OFDM/STFT/FIR/PFB/notch/Kalman/FSK/beam/Alamouti/MMSE2/MMSE3/Costas/Gardner/OM-LSA/адаптивных фильтров/LDPC/GF(2) |

Протокол, темп, FIFO и исследования разрядностей:

| Файл/группа | Раннер | Что проверяется |
| --- | --- | --- |
| [axis_contract_tb.sv](axis_contract_tb.sv), [axis_check.sv](axis_check.sv) | [run_axis_contract.py](../../tools/run_axis_contract.py) | Законная удерживаемая передача/отмена сбросом и семь типов нарушений: valid, data, last и X |
| [adaptive_protocol_tb.sv](adaptive_protocol_tb.sv), [oset_gardner_protocol_tb.sv](oset_gardner_protocol_tb.sv), [costas_protocol_tb.sv](costas_protocol_tb.sv), [fsk_ldpc_protocol_tb.sv](fsk_ldpc_protocol_tb.sv) | [run_adaptive_protocol.py](../../tools/run_adaptive_protocol.py), [run_oset_gardner_protocol.py](../../tools/run_oset_gardner_protocol.py), [run_costas_protocol.py](../../tools/run_costas_protocol.py), [run_fsk_ldpc_protocol.py](../../tools/run_fsk_ldpc_protocol.py) | Приоритет/ожидание конфигурации, входы на свободной границе, TLAST и удержание итоговых выходов соответствующих семейств |
| [stream_cfg_priority_tb.sv](stream_cfg_priority_tb.sv), [omlsa_cfg_priority_tb.sv](omlsa_cfg_priority_tb.sv) | [run_stream_cfg_priority.py](../../tools/run_stream_cfg_priority.py); группы также вызываются `run_beam.py`, `run_pfb.py`, `run_omlsa.py` | Коллизия cfg/data у Alamouti/beamform/PFB, удержанный первый отсчёт, запрет смены OM-LSA-конфигурации до полного выхода сигнала и хвоста |
| [axis_fifo_tb.sv](axis_fifo_tb.sv), [axis_fifo_costas_tb.sv](axis_fifo_costas_tb.sv) | [axis_fifo_sweep.py](../../tools/axis_fifo_sweep.py) | Полная полезная ёмкость, порядок/TLAST, одновременный pop+push, reset, конечная интеграция с Costas II=8 |
| [axis_fifo_load_tb.sv](axis_fifo_load_tb.sv), [axis_fifo_lms_load_tb.sv](axis_fifo_lms_load_tb.sv) | [fifo_load_sweep.py](../../tools/fifo_load_sweep.py), [lms_fifo_load_sweep.py](../../tools/lms_fifo_load_sweep.py) | Детерминированные нагрузки и бюджет FIFO перед Costas или LMS/NLMS; независимые паузы выходов |
| [stream_rate_tb.sv](stream_rate_tb.sv), [mmse3_rate_tb.sv](mmse3_rate_tb.sv), [sync_adaptive_rate_tb.sv](sync_adaptive_rate_tb.sv) | [run_stream_rates.py](../../tools/run_stream_rates.py), [run_mmse3_rates.py](../../tools/run_mmse3_rates.py), [run_sync_adaptive_rates.py](../../tools/run_sync_adaptive_rates.py) | Реальные принятые слова/такты, burst и межкадровые паузы, заполнение/опустошение; это измерение симуляции, не Fmax |
| [fir_width_guard_tb.sv](fir_width_guard_tb.sv), [lms_width_bounds_tb.sv](lms_width_bounds_tb.sv), [rls_dot_bounds_tb.sv](rls_dot_bounds_tb.sv), [rls_update_bounds_tb.sv](rls_update_bounds_tb.sv) | [fir_width_sweep.py](../../tools/fir_width_sweep.py), [lms_width_sweep.py](../../tools/lms_width_sweep.py), [rls_width_sweep.py](../../tools/rls_width_sweep.py), [rls_update_sweep.py](../../tools/rls_update_sweep.py) | Достаточность выражений/накопителей, runtime guards и направленные предельные случаи |
| [mmse3_width_tb.sv](mmse3_width_tb.sv), [mmse3_config_width_tb.sv](mmse3_config_width_tb.sv), [mmse_n_width_tb.sv](mmse_n_width_tb.sv) | [mmse3_width_sweep.py](../../tools/mmse3_width_sweep.py), [mmse3_config_width_sweep.py](../../tools/mmse3_config_width_sweep.py), [mmse_n_width_sweep.py](../../tools/mmse_n_width_sweep.py) | Границы выходных dot products и конфигурационных Gram/adj/det/промежуточных выражений |
| [mmse3_scale_tb.sv](mmse3_scale_tb.sv), [mmse_n_update_tb.sv](mmse_n_update_tb.sv), [mmse_n_norm_back_tb.sv](mmse_n_norm_back_tb.sv) | [mmse_scale_update_sweep.py](../../tools/mmse_scale_update_sweep.py), [mmse_norm_back_sweep.py](../../tools/mmse_norm_back_sweep.py) | Масштабирование, обновления, нормировка и обратная подстановка MMSE |
| [omlsa_gain_bounds_tb.sv](omlsa_gain_bounds_tb.sv) | [omlsa_width_sweep.py](../../tools/omlsa_width_sweep.py) | Границы выражений/таблиц gain, включая отрицательную проверку недостаточной ширины |
| [sat_event_tb.sv](sat_event_tb.sv), [sat_event_check.sv](sat_event_check.sv), [sat_group_tb.sv](sat_group_tb.sv), [sat_group_check.sv](sat_group_check.sv) | [run_sat_event.py](../../tools/run_sat_event.py), [run_sat_group.py](../../tools/run_sat_group.py) | Проверка самих наблюдателей насыщения: число вычислений/событий, маски полос, warm-up/stall и инъекции X |
| [stream_cover.sv](stream_cover.sv) | Подключается численными `run_*.py`; сводка — [coverage_report.py](../../tools/coverage_report.py) | Covergroup и счётчики handshakes, stalls, last, нулей, предельных значений и режимов |

Файлы `*_bounds_check.sv`, `*_saturation_check.sv`, `*_check.svh`, `*_bounds.svh`, `fft_embedded_observer.svh`, `istft_observer.svh` подключаются соответствующими численными тестами. Они проверяют активные внутренние данные и индексы; это не самостоятельные верхние уровни. Среди них [bpsk_fir_bounds_check.sv](bpsk_fir_bounds_check.sv), [bpsk_cordic_bounds_check.sv](bpsk_cordic_bounds_check.sv), [bpsk_divide_bounds_check.sv](bpsk_divide_bounds_check.sv) наблюдают общие узлы пилота, а [fir_saturation_check.sv](fir_saturation_check.sv) — ограничители FIR. FFT/PFB/ISTFT и другие sweeps также переиспользуют основные численные тестбенчи, а не обязательно имеют отдельный `*_tb.sv`.

## Как запустить

Все команды из корня проекта. Требуются Python и зависимости [requirements-rtl.txt](../../requirements-rtl.txt), для lint — Verilator, для полного HDL/UVM — лицензированная Questa и UVM 1.2. Раннеры ищут Questa через `QUESTA_HOME`, `PATH` либо домашнюю установку; `UVM_HOME` задаёт каталог UVM. Python запускается без `-O`.

```bash
python3 tools/run_rtl.py --suite all
python3 tools/run_streaming_rtl.py --suite all
python3 tools/run_bpsk.py --suite all
python3 tools/run_cpm.py --suite all
```

Это начальная инфраструктура, объединённые 17 FFT/DSP/OQPSK-наборов, все PSK/QAM/SIMO и оба CPM-режима. Потоковый runner в режимах `all/hdl` также запускает тесты протокольного и обоих saturation-мониторов. Отдельные раннеры семейства из таблицы принимают `--suite python/lint/hdl/all`, если это предусмотрено их argparse; UVM-раннеры обычно имеют только `python/hdl/all`.

```bash
python3 tools/run_bpsk_uvm.py --suite all --pilot both --profile all
python3 tools/run_psk_tx_uvm.py --suite all
python3 tools/run_packet_rx_uvm.py --suite all
python3 tools/run_cpm_uvm.py --suite all
python3 tools/run_oqpsk_uvm.py --suite all
python3 tools/run_fft_uvm.py --suite all
python3 tools/run_dsp_uvm.py --suite all
```

Эти команды запускают полные UVM-матрицы. Для локальной диагностики допустимы, например, `--profile qpsk_diff` у BPSK RX или `--case ofdm_tx_n32_cp8` у DSP UVM; частичный прогон не заменяет полную матрицу.

У BPSK есть отдельный путь численной симуляции Verilator:

```bash
python3 tools/bpsk_acquisition_check.py --output build/bpsk_tb_acquisition_readme
python3 tools/bpsk_rx_continuous_rate.py --backend verilator --output build/bpsk_tb_rate_readme
```

Каталоги должны быть новыми. В этом пути адаптируется macro-only scoreboard; полноценный UVM остаётся за Questa. Генерация обычных тестовых векторов является частью проверочного runner, генераторы структуры проекта для запуска тестов не нужны.

`run_axis_contract.py`, `run_sat_event.py`, `run_sat_group.py` не имеют argparse: `--help` у них не является безопасным способом просмотра справки и запускает обычную работу. Их интерфейс следует читать в коде. Для MSK↔MATLAB нужны отдельные захваты, SciPy/Octave и исторические материалы; см. [CPM README](../modems/msk_modulator_2008_06_22/README.md).

## Что смотреть

Основные каталоги — `build/rtl/<семейство>/`, UVM — `bpsk_uvm/`, `psk_tx_uvm/`, `packet_rx_uvm/`, `cpm_uvm/`, `oqpsk_uvm/`, `fft_uvm/`, `dsp_uvm/`. Внутри находятся `<suite>_results.json`, журналы компиляции и сценариев, исходные/упакованные векторы, иногда CSV/VCD. При выборе профиля имя JSON получает префикс профиля. Явный `--output` меняет место результатов там, где поддерживается.

Положительный прогон должен закончиться нужной summary, без ошибок симулятора и с нулевыми UVM_ERROR/UVM_FATAL. PASS в JSON должен иметь время завершения и соответствующие текущему составу исходников хеши. У отрицательного прогона ненулевой код/ошибка ожидаются, но runner требует правильный диагностический тег, например `[NUMERIC]`, `[PROTOCOL]`, `[SATURATION]`, `[NESTED_BOUNDS]`, `[FLOAT_SER]`; произвольное падение не является успешным контролем. Конкретные требования к коду возврата различаются между раннерами.

Число сравнений, очередь ожидаемых данных, отброшенные reset-остатки, реальное покрытие stalls/TLAST и итоговые веса важнее одной строки PASS. SER/BER характеризуют качество приёма, а битоточное сравнение — правильность реализации: при шуме SER может быть ненулевой при успешном scoreboard. Rate-отчёты различают отсчёты, векторы и кадры, центральное окно, burst, заполнение и финальное опустошение. Covergroup из `stream_cover` не является полным кодовым/функциональным покрытием дизайна.

Документы по результатам: [RTL_COVERAGE.md](../../docs/RTL_COVERAGE.md), [RTL_INTERNAL_BOUNDS.md](../../docs/RTL_INTERNAL_BOUNDS.md), [RTL_EMBEDDED_FFT.md](../../docs/RTL_EMBEDDED_FFT.md), [RTL_STREAM_RATES.md](../../docs/RTL_STREAM_RATES.md), [RTL_SYNC_ADAPTIVE_RATES.md](../../docs/RTL_SYNC_ADAPTIVE_RATES.md), [RTL_DSP_PIN_RATES.md](../../docs/RTL_DSP_PIN_RATES.md), [RTL_MODEM_PIN_RATES.md](../../docs/RTL_MODEM_PIN_RATES.md). [Основной](../../docs/visual/index.html) и [типизированный](../../docs/typed_visual/index.html) визуальные отчёты помогают смотреть алгоритмические сигналы; это отдельные свидетельства от RTL/UVM.

## Ограничения

Симуляционные такты и коэффициенты условного пересчёта к 100 МГц не подтверждают физический тайминг. Конечная серия не доказывает бесконечный устойчивый поток, а совпадение с целочисленной моделью не доказывает эквивалентности историческому Simulink. Случайные паузы не покрывают все последовательности воздействий; полнота относится к явно заданной матрице.

Сборка и лицензия Questa должны быть доступны: отказ инструмента нельзя считать пропуском с PASS. Известная внутренняя ошибка Verilator при дополнительной проверке OQPSK с активным низким сбросом после изменения общего делителя описана в [BPSK_RTL.md](../../docs/BPSK_RTL.md); она не заменяет проверку этой полярности в Questa.

Исторические исходники в публичную версию не входят. MATLAB-проверки оригиналов и новое получение захватов, в частности MSK TX, доступны только при их наличии. После исключения сторонних материалов старые evidence JSON с хешами удалённых файлов перестают соответствовать составу репозитория; их нельзя выдавать за свежую проверку публичной версии.
