# Общие временные ограничения RTL

Единая спецификация тактирования и внешних бюджетов для проверок RTL в Vivado и Quartus. Из YAML формируются эквивалентные XDC/SDC, а runner проверяет результаты размещения и трассировки.

## Что это

Каталог содержит [common.yaml](common.yaml) — контракт физической проверки переносимых fixed-point блоков. Это инфраструктура проекта, собственного исторического прототипа или модуляции у неё нет. Python-код генерации находится в [rtl_constraints.py](../../tools/rtl_constraints.py), вендорный запуск и критерии приёмки — в [run_rtl_synth.py](../../tools/run_rtl_synth.py).

Тесты [test_rtl_tools.py](../../tests/test_rtl_tools.py) проверяют эквивалентность частоты/IO-бюджетов, отклонение неверных значений и небезопасных Tcl-идентификаторов, политику предупреждений и пороги slack. Исторические результаты физической проверки относятся к конкретным снимкам исходников и не подтверждают тайминг последующих изменений.

## Как работает

1. `load()` читает YAML и проверяет имя clock-порта, конечность/допустимость чисел, имена FPGA и пороги приёмки.
2. `generate()` рассчитывает период `T=1000/f_MHz` и записывает `timing.xdc`/`timing.sdc`.
3. Вендорные Tcl-сценарии синтезируют [rtl_synth_top.sv](../rtl_synth_top.sv), назначают выводы тестовой обвязки, размещают и трассируют проект.
4. Python проверяет setup/hold, предупреждения, ресурсы и создаёт завершённое свидетельство с хешами.

| Поле `common.yaml` | Значение | Назначение |
| --- | --- | --- |
| `clock.port` | `clk` | Вход тактового сигнала |
| `clock.frequency_mhz` | 100 | Период 10 нс |
| `clock.uncertainty_ns` | 0.2 | Неопределённость тактового сигнала |
| `io.input_delay_ns` | 1.0 | Максимальная внешняя задержка входов; минимум в XDC/SDC — 0 |
| `io.output_delay_ns` | 1.0 | Максимальный внешний бюджет выходов; минимум — 0 |
| `io.output_load_pf` | 5.0 | Нагрузка выходов; XDC `set_load`, Quartus `BOARD_MODEL_FAR_C` |
| `targets.xilinx` | `xc7a35tcpg236-1` | Artix-7 |
| `targets.altera` | `5CSEMA5F31C6` | Cyclone V |
| `acceptance.setup_slack_ns` | 0.0 | Общий порог; runner дополнительно требует строго положительный setup |
| `acceptance.hold_slack_ns` | 0.0 | Hold должен быть строго больше порога |
| `acceptance.altera_setup_margin_ns` | 1.0 | Для Quartus setup не менее 1 нс |

Входные ограничения применяются ко всем входам, кроме `clk`, выходные — ко всем выходам. Широких `false_path` нет. Для Quartus берутся независимые минимумы setup и hold по доступным рабочим углам. Неизвестные и критические предупреждения запрещены; исключения заданы в [warnings.json](../warnings.json).

## Структура каталога

| Файл/подкаталог | Назначение |
| --- | --- |
| [common.yaml](common.yaml) | Исходные параметры частоты, IO и FPGA |
| [../../tools/rtl_constraints.py](../../tools/rtl_constraints.py) | Проверка YAML и преобразование в XDC/SDC |
| [../../tools/run_rtl_synth.py](../../tools/run_rtl_synth.py) | Вендорные сборки и численная приёмка |
| [../../tools/rtl_synth_vivado.tcl](../../tools/rtl_synth_vivado.tcl) | Поток Vivado |
| [../../tools/rtl_synth_quartus.tcl](../../tools/rtl_synth_quartus.tcl) | Поток Quartus |
| [../../tools/rtl_timing_quartus.tcl](../../tools/rtl_timing_quartus.tcl) | Итоговая временная проверка Quartus |

## Как запустить

Команды из корня проекта. Для преобразования YAML нужны Python и PyYAML из [requirements-rtl.txt](../../requirements-rtl.txt); для физических сборок дополнительно нужны установленные и доступные по лицензии Vivado/Quartus.

```bash
python3 tools/rtl_constraints.py --source rtl/constraints/common.yaml --output build/rtl/constraints
python3 tools/run_rtl_synth.py --block complex_mul --vendor xilinx
python3 tools/run_rtl_synth.py --block ram --vendor altera
```

Первая команда создаёт только XDC/SDC. Две следующие выполняют физические проверки выбранных блоков. Пути инструментов задаются `VIVADO_ROOT` и `QUARTUS_ROOT`; значения по умолчанию видны в runner. Полный набор обоих вендоров запускается без фильтров:

```bash
python3 tools/run_rtl_synth.py
```

Quartus допускает поэтапный запуск одного блока:

```bash
python3 tools/run_rtl_synth.py --block ram --vendor altera --quartus-phase map
python3 tools/run_rtl_synth.py --block ram --vendor altera --quartus-phase fit
python3 tools/run_rtl_synth.py --block ram --vendor altera --quartus-phase finish
```

Этапы выполняются последовательно с неизменными исходниками. Только `finish` после успешных проверок даёт итоговый PASS; успешный `map` или `fit` не завершает приёмку. Время размещения/трассировки зависит от блока и инструмента, общего норматива нет.

## Что смотреть

Генерация по первой команде: `build/rtl/constraints/timing.xdc` и `timing.sdc`. Синтез: `build/rtl/synth/constraints/`, `build/rtl/synth/<block>/<vendor>/` и JSON по вендорам. Полная сводка — `build/rtl/synth/results.json`; при фильтрации — `<block>_<vendor>_results.json`. Внутри — part, частота, setup/hold, ресурсы, принятые предупреждения, хеши и время завершения.

Для Vivado полезны `timing.rpt`, `critical.rpt`, `utilization.rpt`; для Quartus — `setup.rpt`, `hold.rpt`, `unconstrained.rpt`, `fmax.rpt`, `timing.tsv`, `resources.tsv`. Положительный setup при 100 МГц вместе с положительным hold и допустимыми предупреждениями — необходимые условия PASS. Оценка Fmax по запасу не заменяет отдельной сборки с другой частотой. Подробности об обвязке и прежних результатах — в [RTL_CONTRACT.md](../../docs/RTL_CONTRACT.md).

## Ограничения

Назначение IO детерминировано для стенда инструментов и не является разводкой готовой платы. Ресурсы включают регистровую обвязку. CDC-исключения для интеграции нескольких доменов нужно разрабатывать отдельно: этот контракт описывает один `clk`. Форматы fixed-point и AXI-Stream определяются RTL-модулями, а не YAML.

Quartus получает идентичные копии исходников во временном ASCII-пути: это обход проблемы Tcl с кириллицей в пути проекта. Проверка ограничений и наличие сгенерированного XDC/SDC сами по себе не означают успешной физической реализации.
