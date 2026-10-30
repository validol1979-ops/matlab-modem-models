Follow-up: [Corrections and verified results](REVIEW_FIXES.md). The review below is preserved as the original snapshot.

# Ревью кода — 2026-09-30

Ревью выполнено только чтением, файлы проекта не менялись. Охват:

- `common/` на Python, Octave и SystemVerilog;
- UVM-окружение;
- `tools/`;
- точки входа typed workspace.

Каталоги `original/`, `sources/` и `research/` не проверялись.

## Что проверено и работает

- **Python-регрессия:** `python3 tools/run_tests.py --suite python` прошла, 24 модема, 177 тестов, PASS.
- **SystemVerilog сверен с Python построчно, расхождений в алгоритмах нет.** Проверены `encode`/`decode` (psk, quadrant, pi4), RRC, кубическая интерполяция, `fit_carrier`, `symbol_receiver` (none/linear/dfe, costas, feedforward/feedback, AGC), Gardner, OQPSK, MSK/GMSK и MRC. Максимальная ошибка UVM 1.8e-13 для модемов и 2.5e-13 для typed-алгоритмов. Цифры взяты из логов Questa, которые записаны позже последнего изменения исходников. Заново Questa не запускался.
- **Octave совпадает с Python на основном пути.** Все 40 векторов `research_cases` прошли `research_check.m`, максимальная ошибка 4.1e-12.
- **Стресс-тест Python-ядра** проведён для всех 24 модемов в 11 сценариях: задержка 0–17.3 отсчёта, частота 1e-3, фаза 3 рад, дрейф 2e-4, SNR 15 дБ, фазовый шум, эхо, усиление 5. Ошибки появляются только в ожидаемых случаях:
  - эхо 0.3 без эквалайзера (QAM16, QAM64);
  - фазовый шум 0.01 рад/отсчёт для QAM64 и OQPSK.
- **Петля Gardner работает.** При дрейфе ±6e-4 с ней 0 ошибок, без неё 55–109.
- **Счётчики в README и docs совпадают с фактом:** 26/17/13 workspace, 55 рисунков, 295 строк coverage, 177 тестов.

## Средняя серьёзность

1. **Typed-тесты не являются unittest-тестами.** Затронуты `algorithms/*/*/tests/test_model.py` и `modems/{ofdm_awgn,fsk_text}/tests/test_model.py`, генератор — `tools/research_layout.py`.
   - В модуле нет `TestCase`, а `subprocess.run(..., check=True)` выполняется при импорте.
   - Под `python -m unittest` или pytest результат «Ran 0 tests» (код выхода 5), а падение прогона выглядит как ошибка импорта.
   - Правильно работает только прямой запуск файла.
2. **`tools/matlab_check_originals.m` не передаёт отказ в код выхода.** `catch` записывает FAIL, но итогового `assert` нет (в `matlab_check_research.m` он есть). Поэтому `matlab.sh -batch "matlab_check_originals('compatible')"` возвращает 0 даже при упавших моделях.
3. **Отчёт может приписать PASS непротестированному коду.** В `tools/report_results.py` хэши исходников считаются в момент создания отчёта, а не в момент прогона. Следствия:
   - `docs/verification_results.json` может приписать PASS коду, изменённому после тестов;
   - проверка «Stale portable evidence» в `tools/visual_report.py` на это не срабатывает.

   В `run_research.py` хэши пишутся во время прогона, то есть правильно.
4. **Прогон одной модели перезаписывает общие файлы результатов:**
   - `run_hdl.py --modem` (его вызывают `modems/*/tb/run.sh`) → `build/questa/results.json`;
   - `run_tests.py --modem` → `python_results.json` и `cross_results.json`;
   - `test_original.m` одной модели → `build/matlab_originals/<mode>/results.json`, после чего `report_matlab_originals.py` падает.
5. **В SV `int'(real)` округляет, а Python `int()` отбрасывает дробную часть.** Затронуты `common/sv/research_dsp_pkg.sv:86,95,119,121,142,…`. При нецелом параметре размеры и индексы разойдутся. Сейчас все параметры целые. Исправление: `$rtoi(...)`.

## Слабые места тестов

- **Контракт `variable_delay` не проверяет Gardner.** В `common/python/modem_checks.py` дрейф 1e-4, при нём и без петли 0 ошибок. Для эквалайзера тест устроен правильно и сравнивает с выключенным вариантом. Для Gardner и `phase_noise` нужно так же: больший дрейф и шум плюс проверка, что без контура появляются ошибки.
- **Негативный контроль LDPC не может провалиться** (`tools/research_cases.py:146`). Инвертированное кодовое слово с |LLR|=20 даёт `decoded != word` для любого декодера. Флаг `negative_control_detected` ставится и для `systematic_encode`.
- **Проверки UVM в `tools/run_research.py:73-76` частично не работают:**
  - число транзакций проверяется через `assert`, который отключается при `python -O`;
  - условие `'UVM_FATAL' in bad` всегда истинно, потому что сводка UVM печатает `UVM_FATAL : N`. Реально работает только проверка `[NUMERIC]`.
- **В модемном UVM нет негативного контроля**, аналогичного `+INJECT_MISMATCH`. Тест сброса для кадра 3 (`common/sv/modem_uvm_pkg.sv:73-77`) ничего не доказывает, потому что у `modem_dsp` нет состояния между кадрами.
- **Браузерные проверки пропускают ошибки загрузки.** В `tools/check_visual_browser.py:267` и `tools/check_typed_browser.py:166` обработчик `window.onerror` ставится после загрузки страницы, поэтому ошибки JS при загрузке не ловятся.

## Низкая серьёзность

- **`fit_carrier` не защищён от нулей в эталоне** (`common/python/modem_core.py:176`). Нулевой отсчёт эталона даёт NaN (проверено). Python тогда молча выбирает задержку 0, Octave падает на неопределённом `best_delay`.
- **Python и Octave `research_core` расходятся на граничных входах:**
  - `lms/nlms/rls` при `len(a) < len(x)`: Python обрезает через `zip`, Octave падает;
  - `ldpc` с 4 параметрами: Python падает с IndexError даже в режимах 0/1;
  - `omlsa` при `len(x) <= n` или `nnoise` больше числа кадров: Python работает, Octave падает;
  - `ldpc` с 0 итераций: падают обе реализации;
  - нецелый код операции: Python выдаёт IndexError вместо ValueError.

  В SV для тех же случаев есть чтение за границей массива: `research_dsp_pkg.sv:18,100,147-155`. Также в SV `timing` использует нецелый `p[0]`, а LDPC-узел степени 1 даёт 1e300.
- **Бесконечный цикл поиска корня проекта**, если корень не найден (`dirname /` возвращает `/`). Затронуты `algorithms/*/*/tb/run.sh`, `modems/{ofdm_awgn,fsk_text}/tb/run.sh` и `run_model.m`. Эти `run.sh` также не передают `"$@"`.
- **`run_model.m` требует ровно 4 аргумента.** В Python `auxiliary` необязателен.
- **Жёстко прописанные пути:**
  - `QUESTA_HOME=~/questasim` (`run_research.py:59`, `run_hdl.py:37,39`, `matlab.sh:4`);
  - `-dpicpppath /usr/bin/gcc` в `run_research.py:67`, `DPI_CC` игнорируется.
- **Нет экранирования `'` в путях**, которые `run_research.py:50` вставляет в команду Octave/MATLAB.
- **SV-модем проверяет конфигурацию слабее Python** (`common/sv/modem_dsp_pkg.sv:67`): нет проверки чётного sps для OQPSK, допустимого `order` и конечности данных.
- **Строка UVM-конфига прописана вручную.** В `tools/check_matlab_msk.py:260` она задана строкой, а не генерируется из `cfg`.
- **Проверка не «своей» модели.** `test_original.m` новых .mdl-модемов (`setup_new_models.py:276`) проверяет обе research-модели и перезаписывает общий `matlab_results.json`.
- **Генераторы перезаписывают файлы без предупреждения в README.** `research_layout.py` и `setup_new_models.py` перезаписывают README, `model.json`/`config.json`, точки входа и каталоги. В README предупреждение есть только для `create_workspaces.py`.

## Рекомендуемый порядок исправлений

1. Пункты 1–4 средней серьёзности: код выхода, свежесть отчётов, изоляция результатов одиночных прогонов.
2. Слабые места тестов: Gardner и фазовый шум, негативные контроли LDPC и UVM.
3. `$rtoi` в SV и выравнивание граничного поведения Python, Octave и SV.
