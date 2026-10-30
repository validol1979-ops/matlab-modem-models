import re, json, sys
from pathlib import Path
S = Path(sys.argv[1]); ROOT = Path(sys.argv[2])
reports = {'dsp': 'D', 'fpga': 'F', 'radio': 'R'}
blocks, legends, refdefs = {}, [], []
for name, pre in reports.items():
    text = (S/f'lib/r_{name}.md').read_text()
    # Легенды вида "- **RF** — ..." / "- **B1.** ..." с префиксом отчёта.
    for m in re.finditer(r'^- \*\*([A-Z]{1,3}[0-9]?)\.?\*\*\.?\s*[—-]?\s*(.+)$', text, re.M):
        legends.append((f'{pre}:{m.group(1)}', m.group(2).strip()))
    refdefs += re.findall(r'^(\[[^\]]+\]:\s*<.+>)\s*$', text, re.M)
    keys = {k.split(':')[1] for k, _ in legends if k.startswith(pre+':')}
    for blk in re.split(r'\n### ', text)[1:]:
        head, _, body = blk.partition('\n')
        m = re.match(r'([A-Z0-9-]+)\s+—\s+(.+?)\s+\((P[123])[^)]*\)', head)
        if not m: continue
        body = body.split('\nСводная таблица')[0].split('\n| ID')[0].split('\n## ')[0]
        for k in keys:
            body = re.sub(rf'\*\*{k}\*\*', f'**{pre}:{k}**', body)
        fields = dict(re.findall(r'^- \*\*([^:*]+):\*\*\s*(.+)$', body, re.M))
        blocks.setdefault(m.group(1), []).append(dict(id=m.group(1), title=m.group(2), priority=m.group(3), report=name, fields=fields))
# Слияние дублей: (итоговый ID, исходные ID, название, приоритет).
MERGE = [
    ('DSP-GOERTZEL', ['DSP-GOERTZEL'], None, 'P1'),
    ('SYNC-OFDM-SC', ['SYNC-OFDM-SC', 'SYNC-OFDM-ACQ'], 'Захват OFDM по повторной преамбуле (Schmidl–Cox): обнаружение пакета, грубая синхронизация и CFO', 'P1'),
    ('MOD-IQ-BALANCE', ['DSP-IQ-CAL', 'MOD-IQ-BALANCE'], 'Компенсация I/Q-дисбаланса: сначала частотно-независимая амплитуда/фаза, затем частотно-зависимая', 'P1'),
    ('DSP-DWT', ['DSP-DWT-HAAR', 'DSP-DWT'], 'Вейвлет-преобразование: целочисленный Haar/лифтинг, затем многоуровневое разложение и восстановление', 'P2'),
    ('MOD-MIMO-DET', ['MOD-MIMO-FSD', 'MOD-MIMO-SPHERE'], 'MIMO-детекторы: фиксированной сложности (FSD), затем сферический ML 2×2', 'P2'),
]
used, items = set(), []
for new, olds, title, prio in MERGE:
    parts = [b for o in olds for b in blocks.get(o, [])]
    used.update(olds)
    f = {}
    for p in parts:
        for k, v in p['fields'].items():
            f[k] = (f[k] + ' **Дополнительно:** ' + v) if k in f and v not in f[k] else f.get(k, v)
    items.append(dict(id=new, title=title or parts[0]['title'], priority=prio, reports=sorted({p['report'] for p in parts}), merged_from=olds, fields=f))
for k, lst in blocks.items():
    if k in used: continue
    b = lst[0]; items.append(dict(id=k, title=b['title'], priority=b['priority'], reports=[b['report']], merged_from=[k], fields=b['fields']))
order = {'P1': 0, 'P2': 1, 'P3': 2}
items.sort(key=lambda i: (order[i['priority']], i['id']))
group = lambda i: i['id'].split('-')[0]
names = {'SYNC': '10.2 Синхронизация', 'MOD': '10.3 Модуляция, эквализация и MIMO', 'CHANNEL': '10.4 Оценка канала',
         'DSP': '10.5 Спектральные и общие блоки ЦОС', 'AUDIO': '10.6 Аудио', 'RADAR': '10.7 Радар и решётки',
         'ARRAY': '10.7 Радар и решётки', 'CTRL': '10.8 Управление'}
fieldorder = ['Что', 'Почему нового нет в проекте', 'Источник', 'Предлагаемый контракт', 'Проверка', 'Зависимости']
label = {'Почему нового нет в проекте': 'Новизна/переиспользование', 'Предлагаемый контракт': 'Контракт', 'Что': 'Что'}
out = ['## 10. Третий обход локальной библиотеки — новые DSP-задачи (2026-10-30)', '',
       f'По поручению пользователя библиотека `local-library/BYBLIOTEKA` просмотрена тремя подагентами Codex (только чтение): ЦОС/DSP, FPGA/ПЛИС-ядра, радиотехника/РЛС/ТАУ. Каждый кандидат сверен со списком уже существующих блоков, моделей и задач разделов 8–9; источник подтверждён файлом и страницей. Дубли между агентами объединены. Полнотекстовый RAG-обход через OpenCode (Qulab) не дал результата: 16 из 20 семантических запросов к `home_library` завершились таймаутом, лексический режим вернул в основном нерелевантные фрагменты. Итог — **{len(items)} задач** ({sum(i["priority"]=="P1" for i in items)} P1, {sum(i["priority"]=="P2" for i in items)} P2, {sum(i["priority"]=="P3" for i in items)} P3). Машинный каталог: [task_catalog.json](../research/library_dsp_20261030_round3/task_catalog.json).',
       '', 'Порядок работы как в разделах 8–9: сначала Python floating/fixed-модель с независимым эталоном, затем потоковый RTL с побитной сверкой в Questa/Verilator; синтез — после снятия паузы. Длинные фрагменты книг не копируются: указаны библиография, страницы и собственное описание.', '',
       '### 10.1 Источники', '']
out += [f'- **{k}** — {v}' for k, v in legends] + ['']
current = None
for sec in sorted({names.get(group(i), '10.9 Прочее') for i in items}):
    out += [f'### {sec}', '']
    for i in items:
        if names.get(group(i), '10.9 Прочее') != sec: continue
        out.append(f'- [ ] **{i["id"]} — {i["title"]} ({i["priority"]}).** {i["fields"].get("Что", "")}')
        out.append('')
        for k in fieldorder[1:]:
            if k in i['fields']:
                out += [f'    **{label.get(k, k)}:** {i["fields"][k]}', '']
out += refdefs + ['']
(S/'lib/section10.md').write_text('\n'.join(out))
cat = dict(created='2026-10-30', method='three read-only Codex library surveys; duplicates merged; RAG survey failed (MCP timeouts)',
           library_root='local-library/BYBLIOTEKA', legends=[dict(key=k, source=v) for k, v in legends],
           tasks=[dict(id=i['id'], title=i['title'], priority=i['priority'], survey_reports=i['reports'], merged_from=i['merged_from'],
                       **{k: i['fields'].get(k) for k in fieldorder}) for i in items])
d = ROOT/'research/library_dsp_20261030_round3'; d.mkdir(parents=True, exist_ok=True)
(d/'task_catalog.json').write_text(json.dumps(cat, ensure_ascii=False, indent=1) + '\n')
for n in ('dsp', 'fpga', 'radio'):
    (d/f'survey_{n}.md').write_text((S/f'lib/r_{n}.md').read_text())
print(len(items), [ (i['id'], i['priority']) for i in items])
