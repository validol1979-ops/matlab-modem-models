"""Build modem timing tables from completed, source-bound pin evidence."""
from collections import defaultdict
import csv
import json
from pathlib import Path
import sys
ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
from regression_evidence import require_pass
from modem_stream_rates import verified_artifacts,CASES

def span(values):
    values=[v for v in values if v is not None]
    if not values:return '—'
    return str(min(values)) if min(values)==max(values) else f'{min(values)}–{max(values)}'

def interval(frames,stream):
    return span([f[stream][key] for f in frames for key in ('minimum_interval','maximum_interval')])

def main():
    data=json.loads((ROOT/'build/rtl/modem_rates/results.json').read_text());verified_artifacts(data)
    parent=json.loads((ROOT/'build/all_results.json').read_text());require_pass(parent)
    groups=defaultdict(list);rows=[];differences=[];total_traces=len(data['records'])
    measured=[]
    for case in CASES:
        pair=[data['records'][f'{case}_reset_{a}'] for a in (1,0)]
        if [{k:v for k,v in r.items() if k!='reset_active'} for r in pair][0]!={k:v for k,v in pair[1].items() if k!='reset_active'}:differences.append(case)
        groups[case.rsplit('_',1)[1]].append(pair[0]);measured.extend(('production',r) for r in pair)
    for family,expected in (('maximum_capture',6),('maximum_capture_psk',28),('maximum_tx',34)):
        path=ROOT/'build/acceptance_20261015g'/family/'results.json';extra=json.loads(path.read_text());require_pass(extra)
        if len(extra['records'])!=expected:raise RuntimeError('Incomplete maximum-capture evidence')
        for record in extra['records'].values():measured.append(('maximum_2048',record['timing']))
        total_traces+=len(extra['records'])
    for plan,record in measured:
        for frame in record['per_frame']:
            row=dict(plan=plan,case=record['case'],reset_active=record['reset_active'],frame=frame['frame'],input_unit=record['input_unit'],output_unit=record['output_unit'],
                     first_offer_cycle=frame['first_offer_cycle'],first_offer_to_accept_cycles=frame['first_offer_to_accept_cycles'],input_stall_cycles=frame['input_stall_cycles'],
                     input_source_gap_cycles=frame['input_source_gap_cycles'],first_output_latency_cycles=frame['first_output_latency_cycles'],final_output_latency_cycles=frame['final_output_latency_cycles'],
                     transaction_window_cycles=frame['transaction_window_cycles'],acquisition_latency_cycles=frame.get('acquisition_latency_cycles'),input_samples_at_acquisition=frame.get('input_samples_at_acquisition'),
                     capture_high_water_samples=frame.get('capture_high_water_samples'),capture_headroom_samples=frame.get('capture_headroom_samples'),
                     peak_occupied_buffers=(record['capture_memory'] or {}).get('peak_occupied_buffers'),
                     configuration_completion_cycles=(record['configuration'] or {}).get('final_transfer_to_configured_cycles'),
                     gain_configuration_completion_cycles=(record['gain_configuration'] or {}).get('final_transfer_to_configured_cycles'),
                     input_gap_before_frame=record['input_interframe_gaps'][frame['frame']-1] if frame['frame'] else None,
                     output_gap_before_frame=record['output_interframe_gaps'][frame['frame']-1] if frame['frame'] else None)
            for stream in ('input','output','capture_writes'):
                for key in ('beats','first_cycle','last_cycle','span_cycles','minimum_interval','maximum_interval','mean_interval','adjacent_pairs','longest_consecutive','every_cycle'):
                    row[stream+'_'+key]=frame.get(stream,{}).get(key)
            rows.append(row)
    if total_traces!=136 or len(rows)!=612:raise RuntimeError('Incomplete modem timing tables')
    target=ROOT/'docs/rtl_modem_pin_rates_20261015.csv'
    with target.open('w',newline='') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    lines=['## Полная матрица: результаты',
           f'\nОбязательная матрица завершена `{data["completed_at_utc"]}`: 68 трасс, 306 кадров. Дополнительно 68 граничных трасс включают 306 кадров: у каждого TX последний кадр содержит 2048 символов, у каждого RX все четыре кадра содержат 2048 символов. '
           f'Всего {total_traces} трасс и {len(rows)} строк в [CSV](rtl_modem_pin_rates_20261015.csv). Различий метрик обязательной матрицы между полярностями: {len(differences)}.',
           '\nВ таблицах одна полярность. Интервалы и задержки выражены в тактах; один такт симуляции равен 10 нс. Таблицы относятся к исходной матрице, граничные кадры отмечены отдельным plan в CSV.',
           '\n### Передатчики',
           '\n| Профиль | Интервал входных символов | Интервал выходных отсчётов | Первый выход от первого входа | Межкадровой промежуток выхода |',
           '| --- | ---: | ---: | ---: | ---: |']
    for record in groups['tx']:
        frames=record['per_frame']
        lines.append(f'| {record["case"]} | {interval(frames,"input")} | {interval(frames,"output")} | {span([f["first_output_latency_cycles"] for f in frames])} | {span(record["output_interframe_gaps"])} |')
    lines.extend(['\n### Приёмники',
                  '\n| Профиль | Интервал входных передач | Интервал выходных символов | Первый выход от первого входа | Захват от первого входа | Записано отсчётов на кадр |',
                  '| --- | ---: | ---: | ---: | ---: | ---: |'])
    for record in groups['rx']:
        frames=record['per_frame']
        lines.append(f'| {record["case"]} | {interval(frames,"input")} | {interval(frames,"output")} | {span([f["first_output_latency_cycles"] for f in frames])} | {span([f["acquisition_latency_cycles"] for f in frames])} | {span([f["capture_high_water_samples"] for f in frames])} |')
    lines.append('\nОба capture-буфера бывают заняты одновременно у всех измеренных RX. Метрики целого конечного окна и отдельные ожидания первого входа доступны в JSON; межкадровые промежутки также включены в CSV. Внешние FIFO для неограниченного потока и выбор архитектуры остаются отдельной задачей.')
    doc=ROOT/'docs/RTL_MODEM_PIN_RATES.md';text=doc.read_text();marker='## Полная матрица: результаты'
    if marker in text:text=text[:text.index(marker)].rstrip()+'\n'
    text+='\n'+'\n'.join(lines)+'\n';doc.write_text(text)
    print(json.dumps(dict(traces=total_traces,mandatory_traces=len(data['records']),frames=len(rows),polarity_differences=differences,csv=str(target)),ensure_ascii=False))

if __name__=='__main__':main()
