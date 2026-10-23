# Модели модемов и алгоритмов ЦОС для MATLAB/Simulink

Сборник учебных моделей цифровой связи: Simulink-модемы с символьной и фазовой синхронизацией, АРУ и эквалайзерами, а также MATLAB-скрипты по модуляции, кодированию, адаптивной фильтрации и канализации. У каждой модели есть описание на русском языке и `run_demo.m`, который запускает её одной командой.

## Быстрый старт

1. Скачайте репозиторий (`Code → Download ZIP` или `git clone https://github.com/validol1979-ops/matlab-modem-models.git`).
2. В MATLAB перейдите в папку нужной модели.
3. Выполните:

```matlab
run_demo
```

Simulink-модели открываются вместе с осциллографами и диаграммами созвездий. Длительность можно задать аргументом, например `run_demo(50000)` — это модельное время, подробности в README модели.

В папке каждого Simulink-модема есть и **наша собственная реализация того же модема кодом**, без тулбоксов. Она есть в двух версиях: MATLAB/GNU Octave и Python:

```matlab
run_own                 % MATLAB или Octave
```

```bash
pip install -r requirements.txt
python run_own.py       # Python
```

Она строит созвездия до и после петель приёмника, сходимость ошибки и кривую вероятности ошибки SER от SNR. Для модемов с эквалайзером, петлёй Гарднера и MRC она дополнительно сравнивает приём с включённым и выключенным узлом.

## Требования

Проверено в **MATLAB R2020b**. Для Simulink-модемов нужны Simulink, Communications Toolbox и DSP System Toolbox (с ними Signal Processing Toolbox). Скриптовые примеры в основном работают в базовом MATLAB; точный список продуктов указан в README каждой модели. Собственной реализации (`run_own`) тулбоксы не нужны, её Python-версии нужны NumPy и Matplotlib. Многие скрипты также запускаются в GNU Octave.

## Simulink-модемы

| Модель | Папка |
| --- | --- |
| [BPSK: восстановление тактовой частоты и фазы петлёй Костаса](modems/bpsk_costas_2008_08_25/) | `bpsk_costas_2008_08_25` |
| [Дифференциальная 8-PSK: выделение символьного такта и декодирование](modems/dqpsk_19_09_2006/) | `dqpsk_19_09_2006` |
| [DQPSK: прямая тактовая и фазовая синхронизация с быстрой АРУ](modems/dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12/) | `dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12` |
| [GMSK: когерентный приём с тактовым детектором Mengali и петлёй Костаса](modems/gmsk_coherent_demodulation_2010_10_03/) | `gmsk_coherent_demodulation_2010_10_03` |
| [MSK: формирование сигнала с непрерывной фазой и постоянной огибающей](modems/msk_modulator_2008_06_22/) | `msk_modulator_2008_06_22` |
| [OQPSK: совместная тактовая и фазовая синхронизация при 2 отсчётах на символ](modems/oqpsk_2_sps_timing_recovery_2019_12_05/) | `oqpsk_2_sps_timing_recovery_2019_12_05` |
| [π/4-QPSK: прямая синхронизация при 8 отсчётах на символ на смеси двух сигналов](modems/pi4_qpsk_8_sps_ff_sync_2021_05_27/) | `pi4_qpsk_8_sps_ff_sync_2021_05_27` |
| [π/4-QPSK: прямая фазовая синхронизация по четвёртой степени](modems/pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15/) | `pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15` |
| [8-PSK: быстрая прямая синхронизация без обучающей последовательности](modems/psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15/) | `psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15` |
| [8-PSK: тактовая и фазовая синхронизация с обратной связью и АРУ](modems/psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19/) | `psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19` |
| [64-QAM: квадратное созвездие и тактовая синхронизация Gardner](modems/QAM64_2008_11_21/) | `QAM64_2008_11_21` |
| [16-QAM: синхронизация Гарднера, интерполяция Фарроу и АРУ](modems/qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18/) | `qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18` |
| [16-QAM: синхронизация, АРУ и эквалайзер с обратной связью по решениям](modems/qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26/) | `qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26` |
| [16-QAM: слежение за переменной задержкой канала](modems/qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10/) | `qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10` |
| [16-QAM: переменная задержка и адаптивный линейный эквалайзер](modems/qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21/) | `qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21` |
| [QPSK: синхронизация с обратной связью при 8 отсчётах на символ](modems/qpsk_8_sps_fb_sync_2020_11_25/) | `qpsk_8_sps_fb_sync_2020_11_25` |
| [QPSK: петля Костаса при фазовом шуме](modems/qpsk_demod_with_phase_noise/) | `qpsk_demod_with_phase_noise` |
| [QPSK: быстрая тактовая и фазовая синхронизация без обратной связи](modems/qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06/) | `qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06` |
| [QPSK: тактовая и фазовая синхронизация с обратной связью и АРУ](modems/qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15/) | `qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15` |
| [QPSK: прямая тактовая синхронизация с интерполятором Фарроу](modems/qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20/) | `qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20` |
| [QPSK: подавление фазового шума прямой оценкой фазы](modems/qpsk_phase_noise_phase_sync_2009_04_12/) | `qpsk_phase_noise_phase_sync_2009_04_12` |
| [QPSK с двумя приёмными ветвями: адаптивное объединение SIMO/MRC](modems/simo_maximal_ratio_combining_2010_08_27/) | `simo_maximal_ratio_combining_2010_08_27` |

## Скриптовые модемы

| Модель | Папка |
| --- | --- |
| [Частотная манипуляция FSK: передача и восстановление текста](scripts/fsk_text/) | `fsk_text` |
| [QPSK: квадратурный модем и восстановление несущей петлёй Costas](scripts/qpsk_scripts/) | `qpsk_scripts` |

## Алгоритмы ЦОС

| Модель | Папка |
| --- | --- |
| [Адаптивные фильтры LMS, NLMS и RLS: восстановление сигнала и компенсация шума](algorithms/adaptive/lms_nlms_rls/) | `lms_nlms_rls` |
| [Формирование луча микрофонной решётки: диаграммы направленности и усиление по белому шуму](algorithms/arrays/beamforming/) | `beamforming` |
| [PFB и WOLA: разбиение широкополосного сигнала на частотные каналы](algorithms/channelizers/pfb_wola/) | `pfb_wola` |
| [BPSK с LDPC: сравнение четырёх алгоритмов декодирования](algorithms/coding/ldpc/) | `ldpc` |
| [Оконные sinc-ФНЧ: сравнение АЧХ и числа коэффициентов](algorithms/filters/windowed_sinc/) | `windowed_sinc` |
| [4-QAM: восстановление символьной синхронизации петлёй ZCTED](algorithms/synchronization/symbol_timing/) | `symbol_timing` |
| [Учебные примеры Harger: фильтрация импульса и спектральный анализ сигналов связи](algorithms/teaching/harger/) | `harger` |

## Собственная реализация

Папка [common/](common/) — наш код, написанный с нуля:

- `modem_core.m`: передатчик (PSK, QAM, π/4-QPSK, OQPSK, MSK, GMSK, дифференциальное кодирование, RRC и гауссов фильтры), кубический интерполятор Фарроу, оценка задержки и частоты по преамбуле, петля Гарднера, ФАПЧ/Костас, АРУ, адаптивные линейный эквалайзер и DFE, объединение MRC;
- `modem_channel.m`: канал с задержкой, уходом тактовой частоты, сдвигом частоты, фазовым шумом, эхом и белым шумом;
- `modem_own_demo.m`: демонстрация, кривые SER(SNR) и сравнение с отключёнными узлами.

Папка [common/python/](common/python/) — тот же модем на Python (NumPy): `modem_core.py`, `modem_own_demo.py` с графиками в Matplotlib и `cross_vectors.py` для перекрёстной проверки.

Параметры каждого модема (созвездие, отсчёты на символ, тип синхронизации и эквалайзера) извлечены из оригинальной схемы и лежат в его `config.json`. Обе версии читают один и тот же файл. MATLAB-код проверен в R2020b и GNU Octave 8.4, Python-код — в Python 3 с NumPy 2.4. Поведенческая модель того же алгоритма на SystemVerilog с UVM-тестами в этот репозиторий не входит.

### Перекрёстная проверка Python ↔ MATLAB/Octave

Python формирует для каждого модема три принятых сигнала с разными каналами, сам их принимает и сохраняет результат. Затем MATLAB или Octave принимает те же сигналы своим кодом и сравнивает передатчик, символы приёмника, решения и оценки задержки и частоты:

```bash
python common/python/cross_vectors.py      # создаёт папку cross_vectors/ (~36 МБ)
```

```matlab
addpath common
cross_check                                % PASS по каждому модему
```

Результат: совпадают все 22 модема в MATLAB R2020b и в Octave. Максимальное расхождение символов приёмника 3,4·10⁻¹⁴, допуск 10⁻⁷.

Результаты сравнения узлов в MATLAB R2020b:

| Модем | Узел | Ошибок с узлом | Ошибок без узла |
| --- | --- | ---: | ---: |
| 16-QAM с DFE | эквалайзер, эхо 0,45 | 0 | 1052 из 1344 |
| 16-QAM с линейным эквалайзером | эквалайзер, эхо 0,45 | 0 | 1052 из 1344 |
| 16-QAM, переменная задержка | петля Гарднера, уход такта 6·10⁻⁴ | 0 | 789 из 1344 |
| SIMO QPSK | объединение MRC, SNR 4 дБ | 0 | 257 из 1344 |

## Что изменено и что проверено

Старые `.mdl` 2006–2010 годов адаптированы для R2020b: заменены устаревшие библиотеки блоков (например, `commchan2` → `commchan3`), в модели SIMO заданы размерности портов интерполятора Фарроу. Все изменения перечислены в README соответствующей модели. Все `run_demo` и `run_own` запускались в MATLAB R2020b, `run_own.py` — в Python, и отработали без ошибок. Это проверка запуска и наглядности, а не доказательство полной корректности каждого приёмника. Известные особенности (например, фазовая неоднозначность счётчика ошибок) описаны в README моделей.

## Авторы и лицензии

Модели созданы разными авторами, в основном это Александр Петров (форум [ELECTRONIX](https://electronix.ru/)). Скрипты и алгоритмы взяты из открытых репозиториев и учебных материалов. Автор и источник указаны в README каждой модели, оригинальные файлы `LICENSE` сохранены.

Если автор не указал лицензию, материал публикуется в учебных целях с указанием авторства. **Если вы автор и против публикации, создайте issue: материал будет удалён или оформлен так, как вы скажете.** Права на оригинальные модели принадлежат их авторам. Описания, `run_demo.m`, `run_own.m`, `run_own.py`, папку `common/` и адаптации для R2020b можно свободно использовать.
