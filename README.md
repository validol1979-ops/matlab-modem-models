# Модемы и DSP: переносимые модели и потоковый RTL

*English summary: portable re-implementations of 26 historical MATLAB/Simulink modems and 11 DSP algorithm workspaces in Python, Octave/MATLAB and behavioral SystemVerilog with UVM, plus a fixed-point streaming RTL library (FFT, FIR, PFB, STFT, OFDM, FSK, LDPC, LMS/RLS, MMSE, beamforming, Costas/Gardner, BPSK/MSK/OQPSK receivers) verified bit-exactly against integer Python models in Questa and Verilator. Documentation is in Russian; diagnostics are in English. Licensed under MIT; third-party source models are not included, see [THIRD_PARTY.md](THIRD_PARTY.md).*

## Что это

Проект переносит набор исторических моделей модемов (Simulink/MATLAB, 2006–2021) и учебных DSP-алгоритмов в независимые исполняемые реализации с явным контрактом и автоматической проверкой:

- **26 рабочих пространств модемов** в [`modems/`](modems/): DQPSK, BPSK, QPSK, 8PSK, π/4-QPSK, QAM16/QAM64, MSK, GMSK, OQPSK, SIMO с MRC, OFDM, FSK. Каждый модем реализован на Python, Octave/MATLAB и поведенческом SystemVerilog и проверяется UVM-окружением.
- **11 рабочих пространств алгоритмов** в [`algorithms/`](algorithms/): адаптивные фильтры, beamforming, STFT и OM-LSA, PFB/WOLA, LDPC, фильтры, MIMO, тактовая синхронизация, учебные примеры.
- **Синтезируемый fixed-point RTL** в [`rtl/`](rtl/): потоковые блоки с рукопожатием `valid/ready/last` и модемы BPSK (14 профилей PSK/QAM), MSK/GMSK, OQPSK, OFDM, SIMO. Каждый блок побитно сверяется с целочисленной Python-моделью из [`common/python/`](common/python/).
- **Расширенные DSP-модели** (коды BCH/RS/полярные/турбо, CIC, DDC, Farrow, DPD, Kalman, радар и др.) — Python-модели с независимыми эталонами, см. [EXTENDED_DSP_MODELS.md](docs/EXTENDED_DSP_MODELS.md).

Модели — это **переносимые аналоги**, а не побайтные копии исторических схем: приёмник получает известную обучающую преамбулу и принятый сигнал, но не истинную полезную нагрузку; отличия от оригиналов перечислены в [контракте переноса](docs/PORTING_CONTRACT.md). Полная эквивалентность историческим приёмникам не заявляется. Синтез под FPGA (Vivado/Quartus) приостановлен; физический тайминг и работа на плате не подтверждены.

## Как это устроено

```
config.json / model.json ──► Python-модель ──► векторы ──► Octave ──┐
                                   │                                ├─► сравнение, JSON-отчёт со статусом и хешами
                                   └─► ожидания ──► SV/UVM (Questa) ┘
целочисленная модель common/python/*_fixed.py ──► RTL (Questa, Verilator) ──► побитное сравнение, отрицательные контроли
```

Кадровый модем: TX (кодирование, отображение, RRC) → канал (задержка, усиление, сдвиг фазы и частоты, AWGN, фазовый шум) → RX (захват по преамбуле, Gardner, Costas, АРУ, эквалайзер) → SER/BER. Каждый прогон фиксирует хеши исходников; результат с изменившимися исходниками, пропущенным сценарием или не сработавшим отрицательным контролем считается непройденным. Подробно — в README каждого каталога и в [карте документации](docs/README.md).

## Структура репозитория

| Путь | Содержимое |
| --- | --- |
| [`modems/`](modems/) | Рабочие пространства модемов: `config.json`, `python/`, `octave/`, `sv/`, `tb/`, `tests/`, `matlab/` |
| [`algorithms/`](algorithms/) | Рабочие пространства DSP-алгоритмов по категориям |
| [`common/`](common/) | Общие DSP-ядра Python, Octave и SystemVerilog, целочисленные модели RTL |
| [`rtl/`](rtl/) | Синтезируемые блоки (`rtl/common`), модемы (`rtl/modems`), тестбенчи (`rtl/tb`), ограничения |
| [`tools/`](tools/) | Раннеры регрессий, генераторы векторов, отчёты, экспорт публичной копии |
| [`tests/`](tests/) | pytest/unittest: примитивы, модели, раннеры, защита от регрессий |
| [`docs/`](docs/) | Контракты, результаты проверок, визуальные отчёты, дневник проекта |
| [`research/`](research/) | Манифесты происхождения, планы и сводки исследований (без стороннего кода) |
| `build/` | Регенерируемые векторы, журналы симуляторов, JSON-результаты (не в репозитории) |

## Установка

Нужен Python 3 (проверялось на 3.13) и, в зависимости от уровня проверки, внешние инструменты:

| Уровень | Что нужно |
| --- | --- |
| Python-модели и тесты | `pip install -r requirements.txt` (NumPy, SciPy, PyYAML, pytest) |
| Графики и визуальные отчёты | `pip install -r requirements-visual.txt` (Matplotlib) |
| Octave-реализации | GNU Octave (`octave-cli`) со встроенными функциями |
| Поведенческий SV/UVM и RTL | Questa с UVM 1.2 и системный GCC; Verilator 5 для lint и части тестов |
| MATLAB-проверки | MATLAB R2020b с Simulink и тулбоксами, см. [MATLAB_INSTALLATION.md](docs/MATLAB_INSTALLATION.md) |

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-visual.txt
```

Пути к инструментам задаются переменными `QUESTA_HOME`, `UVM_HOME`, `DPI_CC`, `MATLAB_ROOT`, `VIVADO_ROOT`, `QUARTUS_ROOT` (см. [tools/README.md](tools/README.md)).

## Как запустить

Все команды — из корня проекта.

```bash
# Один модем: демонстрация Python и Octave
python3 modems/bpsk_costas_2008_08_25/python/modem.py
octave-cli --quiet --eval "addpath('modems/bpsk_costas_2008_08_25/octave'); run_modem;"

# Python-регрессия (без симуляторов)
python3 -m pytest -q tests
python3 tools/run_tests.py --suite python

# Сравнение Octave с Python-векторами
python3 tools/run_tests.py --suite cross

# Поведенческие модели в UVM (Questa)
./tools/run_questa.sh --all

# Полная переносимая регрессия: Python, Octave, UVM, блочные модели
python3 tools/run_tests.py --suite all

# Потоковый RTL: 17 наборов (Python-модели, строгий lint, Questa)
python3 tools/run_streaming_rtl.py --suite all
python3 tools/run_bpsk.py --suite all

# Один алгоритм
python3 tools/run_research.py --suite all --workspace coding/ldpc
```

Регрессия завершается ошибкой, если нужный инструмент отсутствует или любая проверка не прошла; молча пропущенных HDL-тестов нет. Исключения в pytest: две проверки целостности исторических исходников в `tests/test_primitives.py` без каталога `sources/` и перекрёстная проверка `tests/test_own_models.py` без `octave-cli` явно помечаются как skipped.

## Быстрый старт в MATLAB

В 22 каталогах исторических модемов поддерживаются `run_demo.m`, `run_own.m`, `run_own.py` и `images/`. Выберите модель в [modems/](modems/); алгоритмы ЦОС описаны в [algorithms/](algorithms/).

Перейдите в MATLAB в папку модели, например `modems/bpsk_costas_2008_08_25`, и выполните:

```matlab
run_demo                           % историческая схема с осциллографами
run_demo(2048)                     % своё конечное модельное время
run_own                            % автономный код, графики и SER(SNR)
run_own(struct('snr_db',12))        % свой SNR на отсчёт, дБ
r = run_own(struct('plot',false))  % численный отчёт без графиков
```

`run_demo` требует локальную подготовленную R2020b-модель из `matlab/`, Simulink, Communications Toolbox и DSP System Toolbox с их зависимостями. Исторические модели исключены из публичной копии: [THIRD_PARTY.md](THIRD_PARTY.md). Без модели функция сообщает об этом до запуска Simulink. Аргумент — модельное время, а не число символов; длительность по умолчанию указана в README модема.

`run_own` работает в MATLAB и GNU Octave без тулбоксов и исторических материалов. Общий код находится в [common/own/](common/own/), Python — в [common/own/python/](common/own/python/). Параметры читаются из существующего `config.json`. Сценарий строит созвездия до и после петель, сходимость ошибки и SER(SNR); для эквалайзера, слежения за переменной задержкой и MRC сравнивает включённый и отключённый узел. Это приёмник с известной преамбулой, его результаты не устанавливают эквивалентность исторической схеме.

Python из той же папки модели (NumPy из `requirements.txt`, Matplotlib для графиков из `requirements-visual.txt`):

```bash
python3 run_own.py
python3 run_own.py --snr 12
python3 run_own.py --no-plot --json
python3 run_own.py --no-plot --save images/generated
python3 run_own.py --no-plot --sweep -10 10 24
```

Без `--sweep` сохраняется исходная сетка от −10 до 24 дБ с шагом 2. Перекрёстная проверка использует один и тот же принятый сигнал и сравнивает TX, RX, решения, задержку и частоту всех 22 модемов. Из корня проекта:

```bash
python3 common/own/python/own_cross_vectors.py build/own_cross_vectors
octave-cli --quiet --eval "addpath('common/own'); own_cross_check('build/own_cross_vectors');"
python3 -m pytest -q tests/test_own_models.py
```

В MATLAB вместо второй команды: `addpath('common/own'); own_cross_check('build/own_cross_vectors');`. Генератор без аргумента также пишет в `build/own_cross_vectors`. Тест создаёт векторы во временном каталоге; отсутствие Octave означает явный skip только перекрёстной проверки.

## Что смотреть

- **Состояние проекта и следующие шаги** — [docs/CURRENT_STATUS.md](docs/CURRENT_STATUS.md), задачи RTL — [docs/RTL_TODO.md](docs/RTL_TODO.md).
- **Каталог модемов и результаты** — [docs/MODEM_CATALOG.md](docs/MODEM_CATALOG.md), [docs/VERIFICATION.md](docs/VERIFICATION.md).
- **Визуальные отчёты (работают офлайн)** — [атлас исторических модемов](docs/visual/index.html) с PDF и [атлас блочных моделей](docs/typed_visual/index.html).
- **Контракты RTL** — [docs/RTL_CONTRACT.md](docs/RTL_CONTRACT.md), BPSK-пилот — [docs/BPSK_RTL.md](docs/BPSK_RTL.md), общая библиотека — [rtl/common/README.md](rtl/common/README.md).
- **История контрольных точек** — [docs/CHECKPOINTS.md](docs/CHECKPOINTS.md) и [дневник](docs/PROJECT_DIARY.md).
- **Результаты прогонов** — JSON и журналы в `build/` после запуска; статус `PASS` в `all_results.json` раннера означает завершённую проверку с неизменными исходниками.

## Лицензия и сторонние материалы

Собственный код и документация распространяются по лицензии [MIT](LICENSE). Исторические модели и сторонние коллекции, послужившие прототипами, в репозиторий не входят; их происхождение, размеры и SHA-256 сохранены в метаданных, а ссылки на источники и их условия перечислены в [THIRD_PARTY.md](THIRD_PARTY.md). Проверки, которым нужны эти исходники (побайтная сверка оригиналов, запуск исторических Simulink-моделей, генераторы рабочих пространств), работают только при их локальном наличии.

Как вносить изменения — [CONTRIBUTING.md](CONTRIBUTING.md).
