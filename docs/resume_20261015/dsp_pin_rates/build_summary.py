"""Summarize a completed source-bound DSP timing acceptance, without modifying sources."""
from pathlib import Path
import csv,json,sys,shutil
from collections import defaultdict
root=Path('');sys.path.insert(0,str(root/'tools'))
from regression_evidence import require_pass
from run_tests import verified_dsp_rates_artifacts
from dsp_uvm_plans import CASES
path=root/'build/rtl/dsp_rates/results.json';data=json.loads(path.read_text());verified_dsp_rates_artifacts(data)
main=json.loads((root/'build/all_results.json').read_text());require_pass(main)
families=defaultdict(list);rows=[];polarity_differences=[]
for name,case in CASES.items():
    a,b=(data['records'][f'{name}_reset_{active}'] for active in (1,0))
    if {k:v for k,v in a.items() if k!='reset_active'}!={k:v for k,v in b.items() if k!='reset_active'}:polarity_differences.append(name)
    kind=case['kind']
    group=case['mode'] if kind==20 else {1:'fir_runtime',2:'ofdm_tx',3:'ofdm_rx',4:'stft_analysis',5:'stft_synthesis',6:'pfb_analysis',7:'notch_iir',8:'kalman_scalar',9:'fsk_tx',10:'fsk_rx',11:'beamform',12:'alamouti_rx',13:'costas_loop',14:'gardner_timing',15:'mmse2',16:'mmse3',17:'omlsa',18:'ldpc_decoder',19:'gf2_encoder',21:'rls_filter'}[kind]
    families[group].append(a)
    for record in (a,b):
        for frame in record['per_frame']:
            row=dict(case=name,family=case['family'],reset_active=record['reset_active'],frame=frame['frame'],
                first_output_latency_cycles=frame['first_output_latency_cycles'],final_output_latency_cycles=frame['final_output_latency_cycles'],
                transaction_window_cycles=frame['transaction_window_cycles'],
                final_weight_latency_cycles=frame.get('final_weight_latency_cycles'),
                configuration_completion_cycles=None if record['configuration'] is None else record['configuration']['final_transfer_to_configured_cycles'])
            for direction in ('input','output','weights'):
                fields=frame.get(direction,{})
                for key in ('beats','first_cycle','last_cycle','span_cycles','minimum_interval','maximum_interval','mean_interval','adjacent_pairs','longest_consecutive','every_cycle'):
                    row[direction+'_'+key]=fields.get(key)
            rows.append(row)
csv_path=root/'docs/rtl_dsp_pin_rates_20261015.csv'
with csv_path.open('w',newline='') as handle:
    writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
def span(values):return str(min(values)) if min(values)==max(values) else f'{min(values)}–{max(values)}'
lines=['## Полная матрица: измеренные результаты',
       f'\nЗавершение измерений: `{data["completed_at_utc"]}`. Проверены все {len(data["records"])} трассы и исходная геометрия. '
       f'В таблице одна полярность, без удвоения кадров; различающихся между полярностями конфигураций: {len(polarity_differences)}. '
       '[Полные строки CSV](rtl_dsp_pin_rates_20261015.csv).',
       '\n| Семейство | Конфигураций | Вход: каждый такт / измеримых кадров | Выход: каждый такт / измеримых кадров | Интервал входа, тактов | Интервал выхода, тактов | Первый выход, тактов | cfg после последней передачи, тактов |',
       '| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |']
for family,records in families.items():
    frames=[frame for record in records for frame in record['per_frame']]
    measured={direction:[frame[direction] for frame in frames if frame[direction]['beats']>1] for direction in ('input','output')}
    coverage=[f'{sum(r["every_cycle"] for r in measured[d])}/{len(measured[d])}' for d in ('input','output')]
    intervals=[span([value for r in measured[d] for value in (r['minimum_interval'],r['maximum_interval'])]) if measured[d] else '—' for d in ('input','output')]
    configs=[r['configuration']['final_transfer_to_configured_cycles'] for r in records if r['configuration'] is not None]
    latency=span([f['first_output_latency_cycles'] for f in frames])
    lines.append(f'| {family} | {len(records)} | {coverage[0]} | {coverage[1]} | {intervals[0]} | {intervals[1]} | {latency} | {span(configs) if configs else "—"} |')
lines.append('\nОдиночные передачи исключены из знаменателя. Это проверка измеренных кадров сценария stream: промежутки между кадрами и полный интервал транзакции приведены в JSON/CSV. Даже когда обе границы передают каждый такт внутри кадра, вычисление блока и ожидание следующего кадра могут ограничивать среднюю скорость. Число тактов configured — разность фронтов, без прибавления единицы для последней конфигурационной передачи.')
if polarity_differences:lines.append('\nРазличия полярностей: '+', '.join(polarity_differences)+'.')
doc=root/'docs/RTL_DSP_PIN_RATES.md';text=doc.read_text();marker='## Полная матрица: измеренные результаты'
if marker in text:text=text[:text.index(marker)].rstrip()+'\n'
text+='\n'+'\n'.join(lines)+'\n';doc.write_text(text)
archive=root/'docs/resume_20261015/dsp_pin_rates';archive.mkdir(parents=True,exist_ok=True)
shutil.copy2(__file__,archive/'build_summary.py')
print(json.dumps(dict(traces=len(data['records']),frames=len(rows),polarity_differences=polarity_differences,csv=str(csv_path)),ensure_ascii=False))
