# Сторонние материалы

Лицензия [MIT](LICENSE) распространяется только на собственный код и документацию проекта. Исторические и сторонние модели, на основе которых написаны переносимые модели, **в публичный репозиторий не входят**: часть из них прямо запрещает перераспространение, у части условия распространения не установлены. Публичная копия собирается командой `python3 tools/export_public.py <каталог>`, которая исключает перечисленное ниже.

## Что исключено

| Путь в рабочем репозитории | Содержимое |
| --- | --- |
| `arxiv/` | Исходные архивы моделей (RAR/7Z/ZIP) и отдельные исторические скрипты |
| `sources/` | Распакованные архивы и вспомогательные примеры |
| `modems/*/original/`, `algorithms/*/*/original/` | Побайтные копии исходных моделей и скриптов |
| `modems/*/matlab/*.mdl` | Подготовленные для MATLAB R2020b копии исторических Simulink-моделей |
| `research/*/{archives,sources,models,support}/` | Скачанный сторонний код и модели |
| `research/*/rag_evidence.json` | Дословные выдержки из книг, использованные при постановке задач |

Происхождение каждого исходника (путь, размер, SHA-256) сохранено в `modems/*/source_parameters.json`, `algorithms/*/*/model.json` и манифестах `research/*/manifest.json`, `research/*/findings.json`. Числовые эталоны, полученные запуском исходных моделей (`tests/data/`, `docs/matlab_reference_results.json`, графики `docs/visual/matlab/`), — результаты измерений проекта, а не сами модели.

## Источники

| Набор | Где взять | Условия |
| --- | --- | --- |
| Модели модемов Simulink/MATLAB (BPSK/DQPSK/QPSK/8PSK/π/4-QPSK/QAM/MSK/GMSK/OQPSK/SIMO, 2006–2021) | Форум ELECTRONIX, тема [«Модель 8PSK модема»](https://electronix.ru/forum/topic/23652-model-8psk-modema/) и FTP форума | Авторские модели; условия распространения не указаны |
| Symbol timing recovery | [igorauad/symbol_timing_sync](https://github.com/igorauad/symbol_timing_sync) @ `f78a565` | См. репозиторий автора |
| PFB/WOLA channelizer | [markagold1/channelizer](https://github.com/markagold1/channelizer) @ `052c136` | См. репозиторий автора |
| Windowed-sinc FIR | [markagold1/wsinc](https://github.com/markagold1/wsinc) @ `9126732` | См. репозиторий автора |
| QPSK reference for FPGA | [lauchinyuan/FPGA_QPSK-modem](https://github.com/lauchinyuan/FPGA_QPSK-modem) @ `b15ff1e` | См. репозиторий автора |
| LMS/NLMS/RLS, ANC | [LiXirong/AdaptiveFilterandActiveNoiseCancellation](https://github.com/LiXirong/AdaptiveFilterandActiveNoiseCancellation) @ `4f56a9a` | Anti-996 (по значку в README) |
| LDPC encoder/decoders | [PKU-HunterWu/LDPC-Encoder-Decoder](https://github.com/PKU-HunterWu/LDPC-Encoder-Decoder) @ `9e7363c` | GPL-3.0 |
| Signals & Systems exercises (FSK) | [ParsaBukani/Signals-Systems](https://github.com/ParsaBukani/Signals-Systems) @ `5b98c37` | MIT |
| OSET DSP subset | [alphanumericslab/OSET](https://github.com/alphanumericslab/OSET) @ `892968a` | BSD-3-Clause (отдельные файлы — GPL-2.0+) |
| MIMO simulations | [DSPLog](https://dsplog.com/about/) | Перераспространение запрещено без разрешения автора |
| STFT/ISTFT, OM-LSA/IMCRA, array processing | [Israel Cohen, software](https://israelcohen.com/software/) | Copyright автора, все права сохранены |
| Учебные примеры ЦОС (Harger) | FTP форума ELECTRONIX | Главы книги и файлы MathWorks; разрешения нет |
| DPD example | MathWorks File Exchange (Kerry Schutz) | BSD-2-Clause-подобная лицензия в `license.txt` |
| PolarM | [tavildar/Polar](https://github.com/tavildar/Polar) | MIT |
| MathWorks adaptive demos, AMS (Dick Benson) | Поставка MATLAB / MathWorks | Условия MathWorks |

Проверки, которым нужны исходники (побайтная сверка `original/`, запуск исторических моделей в MATLAB, `tools/inventory.py`, генераторы рабочих пространств), работают только в рабочей копии, где эти материалы есть локально.
