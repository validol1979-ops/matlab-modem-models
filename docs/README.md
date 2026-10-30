# Карта документации проекта модемов и DSP

Здесь собраны контракты моделей, инструкции проверок, численные отчёты и история разработки. Этот указатель охватывает все Markdown-документы непосредственно в `docs/`; вложенные каталоги описаны отдельно.

## Что это

Документация относится к кадровым Python/Octave/MATLAB/поведенческим SV-моделям, отдельным DSP-операциям, потоковому fixed-point RTL и расширенным Python-алгоритмам. Начните с [CURRENT_STATUS.md](CURRENT_STATUS.md), затем выберите [каталог модемов](MODEM_CATALOG.md), [блочные модели](TYPED_MODELS.md) или [новые DSP-модели](EXTENDED_DSP_MODELS.md).

У каждого отчёта своя область приёмки и дата. Численное согласие реализаций, частичное сравнение с историческим прототипом, UVM-проверка интерфейса и физический timing FPGA являются разными результатами. Состояние текущих аппаратных задач указано в [RTL_TODO.md](RTL_TODO.md).

Исторические исходные модели в публичный репозиторий не входят. Происхождение, размер и SHA-256 блочных источников сохранены в `model.json`, например [filters/windowed_sinc](../algorithms/filters/windowed_sinc/model.json). У кадровых моделей [source_parameters.json](../modems/bpsk_costas_2008_08_25/source_parameters.json) хранит поля блоков и номера строк, [config.json](../modems/bpsk_costas_2008_08_25/config.json) — путь и SHA-256; размеры записаны в [archive_inventory.json](archive_inventory.json). MATLAB-проверки оригиналов и повторный аудит исторических копий возможны только при наличии исходников.

## Как работает

Порядок чтения соответствует цепочке проверки: контракт входов и обработки → реализация → команда runner → журнал/численные результаты → критерии приёмки и ограничения. В кадровых моделях это TX → канал → захват/слежение RX → payload BER/SER; в DSP — входные массивы и параметры → операция → сравнение с независимой опорой. Потоковый RTL дополнительно проверяется по фактическим `valid/ready/last`, сбросам, насыщениям и границам памяти.

| Где искать | Что определяет |
| --- | --- |
| `modems/*/config.json` | Созвездие, `sps`, фильтры, синхронизацию, эквалайзер и особенности кадрового варианта |
| `algorithms/*/*/model.json`, `modems/ofdm_awgn/model.json`, `modems/fsk_text/model.json` | Операции, сценарии, ограничения и происхождение блочных моделей |
| [PORTING_CONTRACT.md](PORTING_CONTRACT.md) | Кадровый baseline: 8 отсчётов/символ, RRC порядка 32, преамбула 192 из 512 символов и документированные замены |
| [RTL_CONTRACT.md](RTL_CONTRACT.md) и профильные RTL-документы | Fixed-point форматы, интерфейсы, округление/насыщение и ограничения отдельных блоков |
| `build/…/*results.json` | Итог конкретного запуска: статус, завершение, счётчики, хеши кода и артефактов |
| `docs/*results.json` | Сохранённые контрольные точки; их дата и состав важнее одного слова PASS |

## Структура каталога

### Обзор проекта и перенос моделей

| Документ | Содержание |
| --- | --- |
| [CURRENT_STATUS.md](CURRENT_STATUS.md) | Текущий статус, принятые результаты и ближайшие задачи; начало чтения перед воспроизведением проверок. |
| [PROJECT_DIARY.md](PROJECT_DIARY.md) | Хронология переносов, решений и проверок с привязкой к контрольным точкам. |
| [MODEM_CATALOG.md](MODEM_CATALOG.md) | Каталог кадровых модемов и связь с каталогом отдельных DSP-алгоритмов. |
| [TYPED_MODELS.md](TYPED_MODELS.md) | Контракты и команды блочных моделей, ограничения аналогов, модели CIC и рационального ресэмплинга. |
| [EXTENDED_DSP_MODELS.md](EXTENDED_DSP_MODELS.md) | 44 модельных этапа Python: сигналы, коды, прикладные алгоритмы и границы численной приёмки. |
| [PORTING_CONTRACT.md](PORTING_CONTRACT.md) | Общий контракт кадровых моделей, замены исторических алгоритмов и условия сравнений. |
| [RESEARCH_REVIEW.md](RESEARCH_REVIEW.md) | Аудит происхождения дополнительных коллекций и область проверки их переносимых аналогов. |
| [VERIFICATION.md](VERIFICATION.md) | Сохранённые результаты переносимой кадровой регрессии и критерии согласия реализаций. |
| [VISUAL_TESTS.md](VISUAL_TESTS.md) | Как читать интерактивные атласы, графики, BER/SER и ограничения визуальных сравнений. |
| [MATLAB_INSTALLATION.md](MATLAB_INSTALLATION.md) | Историческая запись установки MATLAB R2020b и настроек локального запуска. |
| [MATLAB_MODEM_VERIFICATION.md](MATLAB_MODEM_VERIFICATION.md) | Запуски исторических схем, изменения совместимости и частичные численные сравнения; нужны исходники. |
| [CODE_REVIEW.md](CODE_REVIEW.md) | Первое ревью кода и найденные дефекты переносов и проверок. |
| [CODE_REVIEW_FOLLOWUP.md](CODE_REVIEW_FOLLOWUP.md) | Повторное ревью, исправленные и оставшиеся проблемы. |
| [REVIEW_FIXES.md](REVIEW_FIXES.md) | Проверки исправлений: актуальность свидетельств, неверные входы и отрицательные контроли. |

### Реализации RTL и UVM

| Документ | Содержание |
| --- | --- |
| [RTL_CONTRACT.md](RTL_CONTRACT.md) | Базовые fixed-point примитивы, потоковый контракт, сбросы и отдельные vendor flows. |
| [RTL_TODO.md](RTL_TODO.md) | Объём незавершённых аппаратных задач и история функциональной приёмки; текущий режим работы указан в начале. |
| [BPSK_RTL.md](BPSK_RTL.md) | Потоковый BPSK TX/RX, общие профили PSK/QAM, форматы и функциональная/физическая область приёмки. |
| [OQPSK_RTL.md](OQPSK_RTL.md) | Потоковый OQPSK TX/RX, полусимвольный сдвиг, захват и ограничения. |
| [CPM_RTL.md](CPM_RTL.md) | Потоковые MSK/GMSK, целочисленная арифметика и варианты приёмника. |
| [FFT_RTL.md](FFT_RTL.md) | Потоковое FFT и OFDM: масштабирование, интерфейсы и проверка. |
| [DSP_RTL.md](DSP_RTL.md) | Каталог потоковых DSP-блоков, их контракты и запуск численных проверок. |
| [RTL_MMSE3.md](RTL_MMSE3.md) | MMSE 3×3 и связанные исправления MMSE 2×2; веса, конфигурация и численные сравнения. |
| [RTL_MMSE_N.md](RTL_MMSE_N.md) | Параметризованный MMSE/ZF N×N для 2 ≤ N ≤ 8 и проверенные конфигурации. |
| [RTL_BPSK_UVM.md](RTL_BPSK_UVM.md) | UVM BPSK RX/TX: сценарии, физические интерфейсы, reset и отрицательные контроли. |
| [RTL_OQPSK_UVM.md](RTL_OQPSK_UVM.md) | UVM передатчика OQPSK: метки, геометрия отсчётов и удержание передачи. |
| [RTL_PACKET_RX_UVM.md](RTL_PACKET_RX_UVM.md) | UVM приёмников OQPSK/MSK/GMSK и независимый floating payload SER. |
| [RTL_PSK_TX_UVM.md](RTL_PSK_TX_UVM.md) | UVM передатчиков PSK/QAM, покрытие всех меток и профилей mapper. |
| [RTL_DSP_UVM.md](RTL_DSP_UVM.md) | UVM потоковых DSP, конфигурационные транзакции и дополнительные выходы. |

### Протокол, насыщения и функциональное покрытие

| Документ | Содержание |
| --- | --- |
| [RTL_COVERAGE.md](RTL_COVERAGE.md) | Как собирается функциональное покрытие потоковых блоков и какие сценарии учтены. |
| [RTL_OVERLOAD.md](RTL_OVERLOAD.md) | Полная шкала входов/выходов, перегрузочные векторы и границы выходных значений. |
| [RTL_TRACKING_AND_PROTOCOL.md](RTL_TRACKING_AND_PROTOCOL.md) | Проверки потоковых данных/конфигураций, восстановление синхронизации и ранняя диагностика насыщений. |
| [RTL_CONFIGURATION_PROTOCOL.md](RTL_CONFIGURATION_PROTOCOL.md) | Атомарность конфигурации и границы транзакций FIR/MMSE/LMS/RLS. |
| [RTL_COSTAS_RATE_PROTOCOL.md](RTL_COSTAS_RATE_PROTOCOL.md) | Восьмитактный Costas: измеренный темп, конфигурация и независимые протокольные проверки. |
| [RTL_FSK_LDPC_PROTOCOL.md](RTL_FSK_LDPC_PROTOCOL.md) | Граничные конфигурационные сценарии FSK и LDPC/GF(2), отказы и восстановление. |
| [RTL_OSET_GARDNER_PROTOCOL.md](RTL_OSET_GARDNER_PROTOCOL.md) | Конфигурация notch/Kalman/Gardner на границах кадра и проверка удержания входов. |
| [RTL_INTERNAL_BOUNDS.md](RTL_INTERNAL_BOUNDS.md) | Активные индексы и границы памяти FIR/FFT/OQPSK, в том числе усечённые кадры. |
| [RTL_OQPSK_NESTED_BOUNDS.md](RTL_OQPSK_NESTED_BOUNDS.md) | Проверки вложенных FIR, CORDIC и divider внутри OQPSK. |
| [RTL_FFT_SATURATION.md](RTL_FFT_SATURATION.md) | Прямое сравнение насыщений ступеней FFT и проверка слежения OQPSK. |
| [RTL_DSP_SATURATION.md](RTL_DSP_SATURATION.md) | Внутренние ограничители notch/Kalman/beamformer/Alamouti/MMSE и исправление знака notch. |
| [RTL_ADAPTIVE_SATURATION.md](RTL_ADAPTIVE_SATURATION.md) | Ограничители LMS/NLMS/RLS, активные индексы и стресс состояния. |
| [RTL_SPECTRAL_SATURATION.md](RTL_SPECTRAL_SATURATION.md) | Ограничители PFB/OFDM/STFT/OM-LSA и границы их буферов/FIFO. |
| [RTL_EMBEDDED_FFT.md](RTL_EMBEDDED_FFT.md) | Прямая сверка ступеней FFT, встроенных в PFB и OFDM. |
| [RTL_FSK_LDPC.md](RTL_FSK_LDPC.md) | Границы FSK и сравнение обоих этапов насыщения LDPC. |
| [RTL_SYNC_GRADIENT.md](RTL_SYNC_GRADIENT.md) | Ограничитель ошибки Gardner в Q30 и активные границы интерполяции. |

### Точность, синхронизация и задержки петель

| Документ | Содержание |
| --- | --- |
| [RTL_PRECISION.md](RTL_PRECISION.md) | Точность полных fixed-приёмников и разделение локального SQNR от независимого payload SER. |
| [RTL_PAYLOAD_SER.md](RTL_PAYLOAD_SER.md) | Подсчёт SER по меткам, действительно принятым с выхода RTL. |
| [RTL_ADAPTIVE_PRECISION.md](RTL_ADAPTIVE_PRECISION.md) | Полные LMS/NLMS/RLS-петли на общих квантованных входах с независимым состоянием опоры. |
| [RTL_LINEAR_PRECISION.md](RTL_LINEAR_PRECISION.md) | MMSE2/MMSE3, beamformer и Alamouti относительно независимой NumPy-опоры. |
| [RTL_STATE_PRECISION.md](RTL_STATE_PRECISION.md) | Notch, Kalman и FSK на общих квантованных данных. |
| [RTL_LDPC_PRECISION.md](RTL_LDPC_PRECISION.md) | LDPC: решения/posterior независимого декодера; точность GF(2) encoder. |
| [RTL_SPECTRAL_PRECISION.md](RTL_SPECTRAL_PRECISION.md) | PFB/STFT/OFDM/OM-LSA: масштабирование, независимые опоры и выполнение бюджета качества. |
| [RTL_SYNC_ACQUISITION.md](RTL_SYNC_ACQUISITION.md) | Измеренные захват, скачок квадранта и повторная синхронизация Costas. |
| [RTL_COSTAS_STREAM.md](RTL_COSTAS_STREAM.md) | Конвейерный Costas с приёмом одного отсчёта за такт, задержкой обратной связи и остановками. |
| [RTL_COSTAS_STREAM_ACQUISITION.md](RTL_COSTAS_STREAM_ACQUISITION.md) | Конечная сетка захвата QPSK потоковой петлёй: модельные и RTL-подтверждения без доказательства универсального диапазона. |
| [RTL_LOOP_DELAY.md](RTL_LOOP_DELAY.md) | Устойчивость петель при задержке: линейные оценки и битоточные численные эксперименты. |

### Разрядности и точные границы арифметики

| Документ | Содержание |
| --- | --- |
| [RTL_FFT_WIDTH_SWEEP.md](RTL_FFT_WIDTH_SWEEP.md) | Выбор защитных битов FFT на заданных входах и проверка насыщений. |
| [RTL_FIR_WIDTHS.md](RTL_FIR_WIDTHS.md) | Точные интервалы аккумуляторов и компактного дерева FIR, проверка сырых произведений/сумм. |
| [RTL_PFB_WIDTHS.md](RTL_PFB_WIDTHS.md) | Фазовые аккумуляторы PFB и сравнение прежних/сокращённых разрядностей. |
| [RTL_ISTFT_WIDTHS.md](RTL_ISTFT_WIDTHS.md) | Произведения и overlap-add ISTFT до масштабирования и ограничения. |
| [RTL_LMS_ENERGY.md](RTL_LMS_ENERGY.md) | Границы энергии истории LMS/NLMS и исправление переполнения. |
| [RTL_LMS_WIDTHS.md](RTL_LMS_WIDTHS.md) | Промежуточные ширины оценки, ошибки, обновления и выдачи весов LMS/NLMS. |
| [RTL_BEAM_ENERGY.md](RTL_BEAM_ENERGY.md) | Энергия коэффициентов beamformer и ширины нормировки/reciprocal. |
| [RTL_ALAMOUTI_WIDTHS.md](RTL_ALAMOUTI_WIDTHS.md) | Границы энергии, комплексных сумм и масштабирования Alamouti. |
| [RTL_RLS_WIDTHS.md](RTL_RLS_WIDTHS.md) | Ширины prediction, dot-тракта и hᴴu RLS для полных кодов состояний. |
| [RTL_RLS_UPDATES.md](RTL_RLS_UPDATES.md) | Точные произведения gain/update и обновления весов/ковариации RLS. |
| [RTL_MMSE2_WIDTHS.md](RTL_MMSE2_WIDTHS.md) | Gram, determinant, веса и выходные суммы MMSE 2×2. |
| [RTL_MMSE3_WIDTHS.md](RTL_MMSE3_WIDTHS.md) | Gram и выходные выражения MMSE 3×3, сырые наблюдения и сравнение с прежним RTL. |
| [RTL_MMSE3_CONFIG_WIDTHS.md](RTL_MMSE3_CONFIG_WIDTHS.md) | Разрядности adjugate/determinant/M конфигурационного тракта MMSE 3×3. |
| [RTL_MMSE_N_WIDTHS.md](RTL_MMSE_N_WIDTHS.md) | Границы Gram и выходных аккумуляторов MMSE N×N. |
| [RTL_MMSE_SCALE_UPDATES.md](RTL_MMSE_SCALE_UPDATES.md) | Масштабирование весов MMSE3 и промежуточная арифметика исключения MMSE N×N. |
| [RTL_MMSE_N_NORM_BACK.md](RTL_MMSE_N_NORM_BACK.md) | Нормировка и обратная подстановка MMSE N×N, проверки до преобразования разрядности. |
| [RTL_OMLSA_WIDTHS.md](RTL_OMLSA_WIDTHS.md) | Промежуточные разрядности спектрального усиления OM-LSA и отрицательные контроли. |

### Измерения потока и буферов

| Документ | Содержание |
| --- | --- |
| [RTL_STREAM_RATES.md](RTL_STREAM_RATES.md) | Принятые такты FIR/FFT, заполнение/опустошение и исследования конечных нагрузок FIFO. |
| [RTL_SYNC_ADAPTIVE_RATES.md](RTL_SYNC_ADAPTIVE_RATES.md) | Измеренные такты Costas/Gardner/LMS/NLMS/RLS и нагрузки FIFO адаптивных фильтров. |
| [RTL_DSP_PIN_RATES.md](RTL_DSP_PIN_RATES.md) | Задержки и интервалы DSP по независимому разбору VCD физических интерфейсов. |
| [RTL_MODEM_PIN_RATES.md](RTL_MODEM_PIN_RATES.md) | Темп модемных TX/RX, конфигурационные задержки и записи памяти захвата. |
| [RTL_MMSE3_RATES.md](RTL_MMSE3_RATES.md) | Реальные передачи конфигурации, скалярных отсчётов и троек MMSE3. |
| [RTL_BPSK_RX_CONTINUOUS_RATE.md](RTL_BPSK_RX_CONTINUOUS_RATE.md) | Конечный эксперимент непрерывного предложения кадров BPSK RX, backpressure и ограничения буферизации. |

### История оценки работы агентов

| Документ | Содержание |
| --- | --- |
| [AGENT_EFFICIENCY_20261019.md](AGENT_EFFICIENCY_20261019.md) | Историческое сравнение запусков агентов и аудит задачи PFB; не критерий качества DSP. |
| [AGENT_EFFICIENCY_20261019_ISTFT.md](AGENT_EFFICIENCY_20261019_ISTFT.md) | Оценка работы по разрядностям ISTFT и исправлениям проверки. |
| [AGENT_EFFICIENCY_20261019_LMS.md](AGENT_EFFICIENCY_20261019_LMS.md) | Оценка узкой задачи энергии LMS/NLMS. |
| [AGENT_EFFICIENCY_20261019_BEAM.md](AGENT_EFFICIENCY_20261019_BEAM.md) | Оценка задачи энергии beamformer. |
| [AGENT_EFFICIENCY_20261019_ALAMOUTI.md](AGENT_EFFICIENCY_20261019_ALAMOUTI.md) | Оценка задачи точных границ Alamouti. |
| [AGENT_EFFICIENCY_20261019_RLS.md](AGENT_EFFICIENCY_20261019_RLS.md) | Оценка задачи скалярных произведений RLS. |
| [AGENT_EFFICIENCY_20261019_RLS_UPDATES.md](AGENT_EFFICIENCY_20261019_RLS_UPDATES.md) | Оценка задачи промежуточных выражений обновления RLS. |

### Подкаталоги и машиночитаемые данные

| Файл / подкаталог | Назначение |
| --- | --- |
| [visual/index.html](visual/index.html) | Автономный атлас исторических кадровых модемов; графики PNG/SVG, таблицы метрик и сохранённые сравнения MATLAB |
| [visual/modem_test_report.pdf](visual/modem_test_report.pdf) | PDF исторического атласа для последовательного просмотра |
| [visual/report_data.json](visual/report_data.json), [visual/provenance.json](visual/provenance.json) | Данные и происхождение визуального отчёта |
| [typed_visual/index.html](typed_visual/index.html) | Автономный атлас новых модемов и отдельных DSP-алгоритмов; фильтры по типам и сценариям |
| [typed_visual/modem_test_report.pdf](typed_visual/modem_test_report.pdf), [typed_visual/metrics.csv](typed_visual/metrics.csv) | PDF и сводные метрики блочного атласа |
| [typed_visual/report_data.json](typed_visual/report_data.json), [typed_visual/provenance.json](typed_visual/provenance.json) | Данные и происхождение блочного атласа |
| [resume_20261014](resume_20261014) | Исторические контрольные точки floating SER, эксперименты QPSK и копии кода до исправлений |
| [resume_20261015](resume_20261015) | Контрольные точки FFT/CPM/GMSK, staged PSK TX и измерений модемных/DSP-интерфейсов |
| [typed_model_catalog.json](typed_model_catalog.json), [typed_source_coverage.csv](typed_source_coverage.csv) | Каталог рабочих моделей и учёт происхождения источников |
| [verification_results.json](verification_results.json), [typed_verification_results.json](typed_verification_results.json) | Сохранённые сводные свидетельства кадровой и блочной регрессии |
| [matlab_reference_results.json](matlab_reference_results.json), [matlab_audit_expectations.json](matlab_audit_expectations.json) | Результаты MATLAB и ожидаемые результаты аудита совместимости |
| [archive_inventory.json](archive_inventory.json), [research_review_results.json](research_review_results.json) | Инвентарь происхождения и сохранённые результаты аудита дополнительных материалов |
| [cic_models_20261030_results.json](cic_models_20261030_results.json), [filter_models_20261030_results.json](filter_models_20261030_results.json), [extended_dsp_models_20261030_results.json](extended_dsp_models_20261030_results.json) | Численная приёмка CIC, компенсации/ресэмплинга и расширенных Python-моделей |
| `rtl_*results.json`, `rtl_*.csv` | Датированные результаты RTL-проверок и таблицы; смысл каждого набора объясняет профильный Markdown-документ |

## Как запустить

Для чтения Markdown достаточно GitHub или локального просмотрщика. HTML-атласы открываются непосредственно как файлы: сервер, доступ к сети и MATLAB для просмотра не нужны. PDF открываются обычным PDF-просмотрщиком.

Следующие команды запускают проверки из корня проекта. Python-моделям нужны Python 3, NumPy и SciPy; выбранному блочному `all` дополнительно нужны Octave, Questa и UVM 1.2. Потоковый `all` использует Verilator и Questa. Описание зависимостей и всех скриптов — в [tools/README.md](../tools/README.md).

```bash
# Численная проверка одной блочной модели
python3 tools/run_research.py --suite python --workspace filters/windowed_sinc

# Проверка той же модели в Python, Octave и поведенческом SV/UVM
python3 tools/run_research.py --suite all --workspace filters/windowed_sinc

# Проверка потоковых FFT и FIR: integer-опоры, lint, Questa
python3 tools/run_streaming_rtl.py --suite all --blocks fft fir
```

Готовые атласы можно читать без повторной генерации. Скрипты `visual_report.py`, `typed_visual_report.py`, `report_results.py` и `report_typed_results.py` заново проверяют входные результаты и/или исторические файлы; их нельзя считать автономной процедурой пересборки отчётов в публичной копии без исходников. MATLAB-проверки в [MATLAB_MODEM_VERIFICATION.md](MATLAB_MODEM_VERIFICATION.md) также требуют исторических схем и соответствующих продуктов MATLAB/Simulink.

## Что смотреть

В начале исследования проверяйте дату документа и область заявленного результата. Для численного сравнения ищите параметры входа, независимую опору, единицы и знаменатель метрики, затем отрицательные контроли и ограничения. BER — доля ошибочных битов, SER — доля ошибочных символов, SQNR — отношение мощности опорного сигнала к мощности ошибки. Метрики по преамбуле и полезной части нельзя смешивать.

В UVM штатные сценарии требуют нулевых `UVM_ERROR` и `UVM_FATAL`, а отрицательные контроли должны завершаться ожидаемым отказом. В JSON проверяйте `status=PASS`, `completed_at_utc`, полноту сценариев и соответствие `source_hashes`/`artifact_hashes`. Фактические такты определяются по принятым передачам, а конфигурация, заполнение/опустошение и стационарный участок измеряются отдельно.

В [историческом атласе](visual/index.html) и [блочном атласе](typed_visual/index.html) выбирайте модель и сценарий, затем открывайте PNG/SVG или PDF. Как интерпретировать созвездия, спектры, синхронизацию и частичные исторические сравнения, объясняет [VISUAL_TESTS.md](VISUAL_TESTS.md).

## Ограничения

Этот README является указателем; численные значения, формулы и ограничения алгоритмов нужно читать в профильных документах и коде. Старые контрольные точки могут описывать меньше блоков и проверок, чем текущий код. Измеренные такты симуляции не определяют Fmax, а модельная приёмка новых Python-алгоритмов не означает завершение RTL.

В существующих исторических документах встречаются локальные пути и ссылки на материалы, исключённые из публичной поставки; они остаются свидетельством происхождения. Этот указатель ведёт на сохраняемые документы и отчёты. Вложенные `resume_*` содержат исторические копии и не являются текущими точками запуска.

После исключения сторонних файлов меняется снимок исходников. Сохранённые полные отчёты могут не пройти автоматическую проверку актуальности в публичной версии; повторный запуск поддерживаемого численного набора создаёт свидетельство для нового состава файлов. Планы и baseline-данные специализированного `run_extended_dsp_models.py` шире одних манифестов: без них следует запускать отдельные численные тесты, описанные в [tests/README.md](../tests/README.md).
