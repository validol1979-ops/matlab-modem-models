# Расширенные DSP-модели: 44 модельных этапа

В очереди из локальной библиотеки завершены четыре прежних и сорок новых модельных этапов. Здесь описана численная приёмка Python; аппаратные требования исходных TODO остаются отдельными этапами. Исходные ТЗ и точные места в библиотеке сохранены в [первом каталоге](../research/library_dsp_20261029/task_catalog.json) и [дополнении](../research/library_dsp_20261030_round2/task_additions.json).

Общий проверяемый результат: [extended_dsp_models_20261030_results.json](extended_dsp_models_20261030_results.json). Численная приёмка всех 44 этапов — **280 тестов PASS**; те же 280 тестов повторены в отдельной копии с 1560 совпадающими исходниками. Повторение в обычной копии репозитория:

```bash
python3 tools/run_extended_dsp_models.py
```

Результат пишется в `build/full_dsp_20261030/acceptance/all_results.json`. Флаг `--frozen-baseline` дополнительно сверяет RTL и прежние Python-файлы с замороженной базой кампании 2026-10-30 и перезаписывает исторический отчёт выше; после последующих изменений RTL эта сверка намеренно не проходит.

Runner требует все 44 уникальных ID, запускает реальные тесты без пропусков и expected failures, проверяет неизменность источников, контрактов и эталонных данных за время прогона. План приёмки неизменяемый — [model_plan.json](../research/full_dsp_20261030/model_plan.json); изменяемый журнал работы — [progress.json](../research/full_dsp_20261030/progress.json). Внешняя RAG-библиотека, provider configuration и рабочие каталоги агентов для повторения численных тестов не требуются.

## Ранее принятые четыре этапа

| ID | Реализация | Независимые проверки |
|---|---|---|
| DSP-CIC-DEC, DSP-CIC-INT | [cic_model.py](../common/python/cic_model.py) | [test_cic_models.py](../tests/test_cic_models.py) |
| DSP-CIC-COMP | [cic_compensation.py](../common/python/cic_compensation.py) | [test_filter_models.py](../tests/test_filter_models.py) |
| DSP-RATIONAL | [rational_model.py](../common/python/rational_model.py) | [test_filter_models.py](../tests/test_filter_models.py) |

## Сигналы, фильтры и модуляторы

[Контракты, исходные источники, численные результаты и ограничения](../research/full_dsp_20261030/signal/manifest.json); [фактические запуски pi/OpenCode](../research/full_dsp_20261030/signal/external_agents.json).

| ID | Модель | Тесты |
|---|---|---|

| DSP-DDS | [ext_signal_core.py](../common/python/ext_signal_core.py) | [test_ext_signal_core.py](../tests/test_ext_signal_core.py) |

| DSP-HILBERT | [ext_signal_core.py](../common/python/ext_signal_core.py) | [test_ext_signal_hilbert.py](../tests/test_ext_signal_hilbert.py), [test_ext_signal_oracles.py](../tests/test_ext_signal_oracles.py) |

| DSP-SOS | [ext_signal_sos.py](../common/python/ext_signal_sos.py) | [test_ext_signal_sos.py](../tests/test_ext_signal_sos.py) |

| DSP-FARROW | [ext_signal_farrow.py](../common/python/ext_signal_farrow.py) | [test_ext_signal_farrow.py](../tests/test_ext_signal_farrow.py), [test_ext_signal_spectral_oracles.py](../tests/test_ext_signal_spectral_oracles.py) |

| DSP-PSD | [ext_signal_psd.py](../common/python/ext_signal_psd.py) | [test_ext_signal_psd.py](../tests/test_ext_signal_psd.py), [test_ext_signal_spectral_oracles.py](../tests/test_ext_signal_spectral_oracles.py) |

| DSP-DCT | [ext_signal_dct.py](../common/python/ext_signal_dct.py) | [test_ext_signal_dct.py](../tests/test_ext_signal_dct.py), [test_ext_signal_spectral_oracles.py](../tests/test_ext_signal_spectral_oracles.py) |

| DSP-FFT-CONV | [ext_signal_spectral.py](../common/python/ext_signal_spectral.py) | [test_ext_signal_spectral.py](../tests/test_ext_signal_spectral.py), [test_ext_signal_spectral_oracles.py](../tests/test_ext_signal_spectral_oracles.py) |

| MOD-AM | [ext_signal_am.py](../common/python/ext_signal_am.py) | [test_ext_signal_am.py](../tests/test_ext_signal_am.py) |

| MOD-FM | [ext_signal_fm.py](../common/python/ext_signal_fm.py) | [test_ext_signal_fm.py](../tests/test_ext_signal_fm.py) |

| MOD-SSB | [ext_signal_ssb.py](../common/python/ext_signal_ssb.py) | [test_ext_signal_ssb.py](../tests/test_ext_signal_ssb.py) |

| DSP-DDC | [ext_signal_ddc.py](../common/python/ext_signal_ddc.py) | [test_ext_signal_ddc.py](../tests/test_ext_signal_ddc.py) |

## Коды, последовательности и мягкие решения

[Контракты, исходные источники, численные результаты и ограничения](../research/full_dsp_20261030/coding/manifest.json); [фактические запуски pi/OpenCode](../research/full_dsp_20261030/coding/external_agents.json).

| ID | Модель | Тесты |
|---|---|---|

| FEC-VIT | [ext_code_trellis.py](../common/python/ext_code_trellis.py) | [test_ext_code_trellis.py](../tests/test_ext_code_trellis.py), [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py) |

| FEC-RS | [ext_code_gf.py](../common/python/ext_code_gf.py), [ext_code_rs.py](../common/python/ext_code_rs.py) | [test_ext_code_block.py](../tests/test_ext_code_block.py) |

| FEC-BCH | [ext_code_gf.py](../common/python/ext_code_gf.py), [ext_code_bch.py](../common/python/ext_code_bch.py) | [test_ext_code_block.py](../tests/test_ext_code_block.py) |

| FEC-POLAR | [ext_code_polar.py](../common/python/ext_code_polar.py) | [test_ext_code_polar.py](../tests/test_ext_code_polar.py), [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py) |

| FEC-TURBO | [ext_code_turbo.py](../common/python/ext_code_turbo.py) | [test_ext_code_turbo.py](../tests/test_ext_code_turbo.py), [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py) |

| MOD-LLR | [ext_code_llr.py](../common/python/ext_code_llr.py) | [test_ext_code_llr.py](../tests/test_ext_code_llr.py), [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py) |

| MOD-TCM | [ext_code_tcm.py](../common/python/ext_code_tcm.py) | [test_ext_code_tcm.py](../tests/test_ext_code_tcm.py), [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py) |

| FEC-CRC | [ext_code_basics.py](../common/python/ext_code_basics.py) | [test_ext_code_basics_oracles.py](../tests/test_ext_code_basics_oracles.py) |

| DSP-PRBS-SCRAMBLER | [ext_code_basics.py](../common/python/ext_code_basics.py) | [test_ext_code_basics_oracles.py](../tests/test_ext_code_basics_oracles.py) |

| FEC-DVB-PLS | [ext_code_pls.py](../common/python/ext_code_pls.py) | [test_ext_code_pls.py](../tests/test_ext_code_pls.py), [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py) |

| FEC-HAMMING | [ext_code_basics.py](../common/python/ext_code_basics.py) | [test_ext_code_basics_oracles.py](../tests/test_ext_code_basics_oracles.py) |

| FEC-GOLAY24 | [ext_code_golay.py](../common/python/ext_code_golay.py) | [test_ext_code_golay.py](../tests/test_ext_code_golay.py), [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py) |

| FEC-BTC | [ext_code_btc.py](../common/python/ext_code_btc.py) | [test_ext_code_btc.py](../tests/test_ext_code_btc.py), [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py) |

## Каналы, аудио, антенны и радар

[Контракты, исходные источники, численные результаты и ограничения](../research/full_dsp_20261030/advanced/manifest.json); [фактические запуски pi/OpenCode](../research/full_dsp_20261030/advanced/external_agents.json).

| ID | Модель | Тесты |
|---|---|---|

| RF-DPD | [ext_advanced_dpd.py](../common/python/ext_advanced_dpd.py) | [test_ext_advanced_dpd.py](../tests/test_ext_advanced_dpd.py) |

| ARRAY-MVDR | [ext_advanced_arrays.py](../common/python/ext_advanced_arrays.py) | [test_ext_advanced_arrays.py](../tests/test_ext_advanced_arrays.py) |

| ARRAY-DOA | [ext_advanced_arrays.py](../common/python/ext_advanced_arrays.py) | [test_ext_advanced_arrays.py](../tests/test_ext_advanced_arrays.py) |

| AUDIO-IMCRA | [ext_advanced_imcra.py](../common/python/ext_advanced_imcra.py), [ext_advanced_imcra_fixed.py](../common/python/ext_advanced_imcra_fixed.py) | [test_ext_advanced_imcra.py](../tests/test_ext_advanced_imcra.py), [test_ext_advanced_imcra_fixed.py](../tests/test_ext_advanced_imcra_fixed.py) |

| AUDIO-EQ16 | [ext_advanced_eq.py](../common/python/ext_advanced_eq.py) | [test_ext_advanced_eq.py](../tests/test_ext_advanced_eq.py) |

| CHANNEL-AWGN | [ext_advanced_channels.py](../common/python/ext_advanced_channels.py) | [test_ext_advanced_channels.py](../tests/test_ext_advanced_channels.py) |

| CHANNEL-RAYLEIGH | [ext_advanced_channels.py](../common/python/ext_advanced_channels.py) | [test_ext_advanced_channels.py](../tests/test_ext_advanced_channels.py) |

| OFDM-CFO-ICI | [ext_advanced_cfo.py](../common/python/ext_advanced_cfo.py) | [test_ext_advanced_cfo.py](../tests/test_ext_advanced_cfo.py) |

| AUDIO-COMPLIMIT | [ext_advanced_dynamics.py](../common/python/ext_advanced_dynamics.py) | [test_ext_advanced_dynamics.py](../tests/test_ext_advanced_dynamics.py) |

| AUDIO-NOISEGATE | [ext_advanced_dynamics.py](../common/python/ext_advanced_dynamics.py) | [test_ext_advanced_dynamics.py](../tests/test_ext_advanced_dynamics.py) |

| RADAR-CHIRP | [ext_advanced_radar.py](../common/python/ext_advanced_radar.py) | [test_ext_advanced_radar.py](../tests/test_ext_advanced_radar.py) |

| RADAR-PULSE-COMP | [ext_advanced_radar.py](../common/python/ext_advanced_radar.py) | [test_ext_advanced_radar.py](../tests/test_ext_advanced_radar.py) |

| RADAR-DOPPLER-MTI | [ext_advanced_radar.py](../common/python/ext_advanced_radar.py) | [test_ext_advanced_radar.py](../tests/test_ext_advanced_radar.py) |

| RADAR-CFAR | [ext_advanced_radar.py](../common/python/ext_advanced_radar.py) | [test_ext_advanced_radar.py](../tests/test_ext_advanced_radar.py) |

| DSP-KALMAN-MATRIX | [ext_advanced_kalman.py](../common/python/ext_advanced_kalman.py) | [test_ext_advanced_kalman.py](../tests/test_ext_advanced_kalman.py) |

| SAR-OMEGA-K | [ext_advanced_sar.py](../common/python/ext_advanced_sar.py) | [test_ext_advanced_sar.py](../tests/test_ext_advanced_sar.py) |

## Границы моделей

Farrow выполняет интерполяцию; антиалиас-фильтр выбирается отдельно. В SOS охарактеризованы ограниченные limit cycles. AM/FM/SSB используют заданные конфигурации и границы насыщения; SSB требует когерентного приёмника. У DDS с адресом ROM12 невыровненный coherent-профиль даёт SFDR около72.19 dB; значение130 dB относится только к выровненной частоте и квантованию амплитуды.

GF(2)/GF(2^m) кодеры являются точными дискретными моделями. Soft-декодеры имеют floating и квантованные метрики; коррекция за пределами заявленного радиуса не гарантируется. Polar использует исходный порядок reliability table, TCM — исходный 4D mapper и differential convention, Turbo — конкретную CCSDS rate1/6 архитектуру и четыре исходных размера блока. Это ограниченные профили моделей.

Обучение DPD и решения/eigenspaces антенных алгоритмов выполняются offline; fixed runtime оговорён отдельно. IMCRA воспроизводит исходные M512/Fs16k и весь feedback schedule, а fixed Q48 относится к спектральному tracker/gain. SAR использует небольшую нормализованную геометрию, явные Stolt support/interpolation и проверку внутренних насыщений FFT; радиометрическая калибровка этим этапом не принимается.

Для CFO отдельно воспроизводится непериодическая sinc-модель статьи и адаптация к конечному FFT. При шуме возможны отказ и ложная оценка: [количественная характеристика](../research/full_dsp_20261030/advanced/cfo_characterization.json) публикует accepted/rejected cases и conditional metrics. Алгоритм не заявляется универсальным средством компенсации CFO.

Независимые данные из исходных алгоритмов: [IMCRA](../research/full_dsp_20261030/imcra_reference.json), [DPD](../research/full_dsp_20261030/dpd_reference.json), [EQ16](../research/full_dsp_20261030/eq16_reference.json). Три [сквозных теста](../tests/test_ext_cross_models.py) проверяют совместные соглашения CRC/PRBS/Viterbi/LLR/AWGN, CRC/Polar и PLS/фазовой модуляции.

Крайние случаи soft quantization проверяются в [test_ext_code_quantization.py](../tests/test_ext_code_quantization.py): конечные LLR ±1e308 и предельно малые/большие scale обрабатываются через точное рациональное масштабирование перед насыщением. Отдельный AM regression проверяет удержание ненулевого выхода при паузе.

## Общая Python-регрессия

Зарегистрированный набор старых и новых тестов прошёл 1093 проверки по 24 модемным конфигурациям на том же снимке. [Свидетельство](../research/full_dsp_20261030/project_python_results.json). Для повторения только этого unittest-набора из корня проекта:

```bash
python3 -c 'import sys; sys.path.insert(0, "tools"); import run_tests; run_tests.python_tests(sorted((run_tests.ROOT/"modems").glob("*/config.json")))'
```

Отдельная генерация прежних precision reports и аппаратные suites не входят в эту команду.
