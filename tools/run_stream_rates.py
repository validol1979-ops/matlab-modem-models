#!/usr/bin/env python3
"""Actual FIR/FFT interface cycles; finite steady windows, burst and fill/drain separately."""
import argparse
import csv
from pathlib import Path
import re
import sys
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
from run_rtl import execute,SOURCES

FIR=[dict(taps=1,lanes=0,tmax=3),dict(taps=3,lanes=0,tmax=3),
     dict(taps=41,lanes=3,tmax=6),dict(taps=41,lanes=6,tmax=6),dict(taps=100,lanes=4,tmax=7)]
MODES=[('ready',0,False),('pressure_5of8',0,True),('frame_gap4',4,False)]
FRAMES=32


def longest_burst(cycles):
    run=maximum=0;previous=None
    for cycle in cycles:
        run=run+1 if previous is not None and cycle==previous+1 else 1
        maximum=max(maximum,run);previous=cycle
    return maximum


def frame_windows(rows,mode):
    valid,ready,last=('s_valid','s_ready','s_last') if mode=='input' else ('m_valid','m_ready','m_last')
    cycles=[r['cycle'] for r in rows if r[valid] and r[ready]]
    frames=[];current=[]
    for row in rows:
        if row[valid] and row[ready]:
            current.append(row['cycle'])
            if row[last]:
                mid=current[len(current)//4:3*len(current)//4]
                frames.append(dict(first=current[0],last=current[-1],samples=len(current),
                                   middle_rate=len(mid)/(mid[-1]-mid[0]+1),
                                   middle_max_gap=max((b-a for a,b in zip(mid,mid[1:])),default=1)))
                current=[]
    if current:raise RuntimeError('Unterminated measured frame')
    if not cycles or len(frames)!=FRAMES:raise RuntimeError('Incomplete measured frames')
    span=cycles[-1]-cycles[0]+1
    periods=[frames[i+1]['first']-frames[i]['first'] for i in range(len(frames)-1)]
    # Central half of 32 frame periods includes boundary pauses and precedes the final flush.
    start,stop=FRAMES//4,3*FRAMES//4
    steady_span=frames[stop]['first']-frames[start]['first'];steady_samples=sum(f['samples'] for f in frames[start:stop])
    return dict(accepted=len(cycles),first=cycles[0],last=cycles[-1],span_cycles=span,
                accepted_span_rate=len(cycles)/span,longest_consecutive_burst=longest_burst(cycles),
                frames=frames,frame_start_periods=periods,
                boundary_idle_cycles=[frames[i+1]['first']-frames[i]['last']-1 for i in range(len(frames)-1)],
                central_periods=dict(first_frame=start,stop_frame=stop,cycles=steady_span,samples=steady_samples,rate=steady_samples/steady_span))


def analyze(path,block,input_length,output_length,gap):
    with Path(path).open() as fd:rows=[{key:int(value) for key,value in row.items()}for row in csv.DictReader(fd)]
    if not rows or any(b['cycle']!=a['cycle']+1 for a,b in zip(rows,rows[1:])):raise RuntimeError('Incomplete per-cycle trace')
    for row in rows:
        if any(row[key] not in (0,1) for key in ('s_valid','s_ready','s_last','m_valid','m_ready','m_last')):raise RuntimeError('Invalid interface trace')
        if not 0<=row['fifo']<=row['fifo_capacity']:raise RuntimeError('Invalid FIFO occupancy')
        if block=='fir' and (row['extra']<0 or row['fifo']+row['extra']>row['fifo_capacity']):raise RuntimeError('Invalid FIR reservations')
    input_stats=frame_windows(rows,'input');output_stats=frame_windows(rows,'output')
    if any(f['samples']!=input_length for f in input_stats['frames']) or any(f['samples']!=output_length for f in output_stats['frames']):raise RuntimeError('Accepted per-frame sample count mismatch')
    offered=[r for r in rows if input_stats['first']<=r['cycle']<=input_stats['last']]
    if gap==0 and any(not r['s_valid']for r in offered):raise RuntimeError('Continuous offered input was interrupted')
    if output_stats['frames'][3*FRAMES//4]['first']>input_stats['last']:
        raise RuntimeError('Central output window extends into final flush; use more frames')
    full_span=output_stats['last']-input_stats['first']+1
    return dict(input=input_stats,output=output_stats,
                full_first_input_to_last_output=dict(cycles=full_span,input_rate=input_stats['accepted']/full_span,output_rate=output_stats['accepted']/full_span),
                frame_first_input_to_first_output=[o['first']-i['first'] for i,o in zip(input_stats['frames'],output_stats['frames'])],
                input_offered_stall_cycles=sum(r['s_valid'] and not r['s_ready']for r in offered),
                input_unoffered_cycles=sum(not r['s_valid']for r in offered),
                output_stall_cycles=sum(r['m_valid'] and not r['m_ready']for r in rows),
                fifo_capacity=max(r['fifo_capacity']for r in rows),fifo_peak=max(r['fifo']for r in rows),extra_peak=max(r['extra']for r in rows),
                full_banks_peak=max(r['full_banks']for r in rows),draining_cycles=sum(r['draining']for r in rows),
                central_input_at_hypothetical_100mhz_msps=100*input_stats['central_periods']['rate'],
                central_output_at_hypothetical_100mhz_msps=100*output_stats['central_periods']['rate'])


def specifications():
    rows=[]
    for parameters in FIR:
        for length in (32,512):rows.append(dict(block='fir',length=length,**parameters))
    for n in (2,6,10):rows.append(dict(block='fft',log2n=n,length=1<<n))
    return rows


def main(argv=None):
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--long-only',action='store_true',help='FIR T3/LANES4 and T41/LANES64, 8192 samples per frame')
    parser.add_argument('--require-inner-one',action='store_true',help='Require every inner-frame transfer on consecutive clocks in ready mode')
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/stream_rates')
    args=parser.parse_args(argv);output=args.output;output.mkdir(parents=True,exist_ok=True)
    target=output/'results.json';evidence=begin();write_json(target,dict(evidence,status='RUNNING'))
    records=[];artifacts=[]
    selected=[dict(block='fir',taps=3,lanes=2,tmax=3,length=8192),
              dict(block='fir',taps=41,lanes=6,tmax=6,length=8192)] if args.long_only else specifications()
    try:
        bindir,_=questa_paths();work=output/'workdir';work.mkdir(exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        compile_log=work/'compile.log'
        execute([bindir/'vlog','-64','-sv',f'+incdir+{ROOT}/rtl/modems/bpsk_costas_2008_08_25',*SOURCES,
                 ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_rate_tb.sv'],work,compile_log)
        artifacts.append(compile_log)
        for index,spec in enumerate(selected):
            for name,gap,pressure in MODES:
                for active in (1,0):
                    identifier=f'{index}_{spec["block"]}_{name}_reset{active}';trace=output/(identifier+'.csv');log=output/(identifier+'.log')
                    parameters=[f'-gFFT={int(spec["block"]=="fft")}',f'-gRESET_ACTIVE={active}',f'-gFRAMES={FRAMES}',f'-gGAP={gap}',f'-gBACKPRESSURE={int(pressure)}']
                    if spec['block']=='fir':parameters += [f'-gLENGTH={spec["length"]}',f'-gTAPS={spec["taps"]}',f'-gLOG2LANES={spec["lanes"]}',f'-gLOG2TMAX={spec["tmax"]}']
                    else:parameters += [f'-gLOG2N={spec["log2n"]}',f'-gTWIDDLE_FILE={ROOT}/rtl/common/mem/fft_twiddle_{spec["length"]}.mem']
                    text=execute([bindir/'vsim','-64','-c','-quiet','work.stream_rate_tb',*parameters,f'+TRACE={trace.resolve()}',
                                  '-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
                    output_length=spec['length'] if spec['block']=='fft' else spec['length']+spec['taps']-1
                    match=re.search(r'PASS STREAM RATES: (\d+) inputs, (\d+) outputs, (\d+) frames',text)
                    if not match or tuple(map(int,match.groups()))!=(FRAMES*spec['length'],FRAMES*output_length,FRAMES) or re.search(r'\*\* (?:Error|Fatal)',text):raise RuntimeError(f'Incomplete measured run: {identifier}')
                    measured=analyze(trace,spec['block'],spec['length'],output_length,gap)
                    if args.require_inner_one and name=='ready' and any(f['middle_max_gap']!=1 for mode in ('input','output') for f in measured[mode]['frames'][8:24]):
                        raise RuntimeError('Inner-frame transfers were not sustained at one per clock')
                    records.append(dict(specification=spec,mode=name,reset_active=active,metrics=measured));artifacts.extend([trace,log])
                    print(f'{identifier}: sustained input/output {measured["input"]["central_periods"]["rate"]:.4f}/{measured["output"]["central_periods"]["rate"]:.4f} samples/cycle',flush=True)
        expected=len(selected)*len(MODES)*2
        if len(records)!=expected:raise RuntimeError('Incomplete coverage')
        write_json(target,dict(finish(evidence,artifacts),status='PASS',records=records,
                              scope='Actual RTL interface cycle metering only; functional arithmetic correctness belongs to separate FIR/FFT regression. Finite 32-frame tests, central frame periods8..24, configured and held-valid inputs; no fitted timing or model trace.',
                              clocks='Clock period10ns is testbench stimulus. 100MHz converted rates are hypothetical; no synthesis/place/route timing claim.',
                              latency_scope='Per-frame first-input to first-output lag, not corresponding sample latency. FFT outputs are frequency bins; FIR appends convolution tail samples.',
                              limitations=dict(fir='ceil(TAPS/LANES) issue steps, tail processing stalls next input frame; FIFO slots reserve outputs across DEPTH=4+LOG2LANES pipeline; actual capacity is measured.',
                                               fft='Two reorder banks and output FIFO4; bounded ready duty constrains sustained output. A gap after a frame starts L=N-1+4*LOG2N flush advances before subsequent input.'),
                              sources=['rtl/common/fir_runtime.sv','rtl/common/fft_r2sdf.sv','rtl/tb/stream_rate_tb.sv']))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise
    print(f'PASS STREAM RATES {len(records)} runs');return records


if __name__=='__main__':main()
