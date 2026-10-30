#!/usr/bin/env python3
"""MMSE3 actual config/input/output handshakes; finite rates without timing claims."""
import argparse
from collections import Counter
import csv
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys

from regression_evidence import ROOT, begin, finish, require_pass, require_unoptimized, write_json, questa_paths

FRAMES = 32
LENGTH = 3072
PROFILES = ('identity', 'complex_permutation')
MODES = ('ready', 'pressure_5of8')
FIELDS = ('cycle,rst,cfg_valid,cfg_ready,cfg_last,cfg_re,cfg_im,cfg_lambda,configured,error,'
          's_valid,s_ready,s_last,s_re,s_im,m_valid,m_ready,m_last,m_re,m_im,fifo,pending,index,'
          'p_valid,e_valid,frame_active,cfg_count,cstate,capacity').split(',')
BOOLS = ('rst','cfg_valid','cfg_ready','cfg_last','configured','error','s_valid','s_ready','s_last',
         'm_valid','m_ready','m_last','p_valid','e_valid','frame_active')
SOURCES = [ROOT/'rtl/common/fxp_divide_seq.sv', ROOT/'rtl/common/norm_reciprocal.sv', ROOT/'rtl/common/mmse3.sv']
SCOPE = ('Actual RTL pin cycles with independent sample/vector/frame denominators. Two unitary H configurations, '
         'lambda0, 32 frames of 3072 complex observation samples each. No general throughput, '
         'coefficient precision, physical 100MHz or post-route timing claim.')


def require(condition, reason):
    if not condition:
        raise ValueError('[RATE] ' + reason)


def configuration(profile):
    require(profile in PROFILES, 'unknown profile')
    if profile == 'identity':
        return [(32768 if k in (0,4,8) else 0, 0) for k in range(9)]
    return [(32768 if k == 3 else -32768 if k == 7 else 0, 32768 if k == 2 else 0) for k in range(9)]


def input_pair(serial):
    return serial, -serial


def output_pair(serial, profile):
    # Pure integer closed form for the chosen unitary matrices: W=H^H.
    # No fixed model, DUT weights, fitted gain or fitted time alignment is used.
    if profile == 'identity':
        return input_pair(serial)
    base, component = 3*(serial//3), serial%3
    return ((base+1, -base-1), (-base-2, base+2), (-base, -base))[component]


def read_trace(path):
    with Path(path).open() as fd:
        reader = csv.DictReader(fd)
        require(reader.fieldnames == FIELDS, 'CSV fields differ')
        rows = [{key:int(value) for key,value in row.items()} for row in reader]
    return rows


def longest_burst(cycles):
    best = run = 0
    previous = None
    for cycle in cycles:
        run = run+1 if previous is not None and cycle == previous+1 else 1
        best = max(best, run)
        previous = cycle
    return best


def windows(events, length, frames):
    require(len(events) == length*frames, 'accepted sample count')
    grouped = [events[k*length:(k+1)*length] for k in range(frames)]
    require(all(row['last'] == int((k+1)%length == 0) for k,row in enumerate(events)), 'TLAST/frame boundary')
    vectors = [events[k:k+3] for k in range(0,len(events),3)]
    require(all(len(v) == 3 for v in vectors), 'incomplete vector')
    first,last = events[0]['cycle'],events[-1]['cycle']
    span = last-first+1
    frame_stats = []
    for frame in grouped:
        interior = frame[length//4:3*length//4]
        cycles = interior[-1]['cycle']-interior[0]['cycle']+1
        # Quarter boundaries are explicit sample indices, divisible by vector size3.
        frame_stats.append(dict(first=frame[0]['cycle'],last=frame[-1]['cycle'],samples=length,vectors=length//3,
            middle_sample_indices=[length//4,3*length//4],middle_cycles=cycles,
            middle_samples=len(interior),middle_vectors=len(interior)//3,
            middle_samples_per_cycle=len(interior)/cycles,middle_vectors_per_cycle=(len(interior)//3)/cycles,
            middle_max_accepted_gap=max(b['cycle']-a['cycle'] for a,b in zip(interior,interior[1:]))))
    begin_frame,end_frame = frames//4,3*frames//4
    begin_cycle,end_cycle = grouped[begin_frame][0]['cycle'],grouped[end_frame][0]['cycle']
    # Independent counts in the actual half-open pin-cycle interval, not length*frames alone.
    central_samples = sum(begin_cycle <= row['cycle'] < end_cycle for row in events)
    completions = [v[-1]['cycle'] for v in vectors]
    central_vectors = sum(begin_cycle <= cycle < end_cycle for cycle in completions)
    central_frames = sum(begin_cycle <= f[-1]['cycle'] < end_cycle for f in grouped)
    require(central_samples == (end_frame-begin_frame)*length and central_vectors*3 == central_samples
            and central_frames == end_frame-begin_frame, 'central window denominators')
    period = end_cycle-begin_cycle
    return dict(samples=len(events),vectors=len(vectors),frames=len(grouped),first=first,last=last,span_cycles=span,
        accepted_span_samples_per_cycle=len(events)/span,accepted_span_vectors_per_cycle=len(vectors)/span,
        longest_consecutive_sample_burst=longest_burst([r['cycle'] for r in events]),
        frame_statistics=frame_stats,frame_start_periods=[b[0]['cycle']-a[0]['cycle'] for a,b in zip(grouped,grouped[1:])],
        boundary_idle_cycles=[b[0]['cycle']-a[-1]['cycle']-1 for a,b in zip(grouped,grouped[1:])],
        central_period=dict(first_frame=begin_frame,stop_frame=end_frame,start_cycle=begin_cycle,stop_cycle=end_cycle,
            cycles=period,samples=central_samples,vectors=central_vectors,frames=central_frames,
            samples_per_cycle=central_samples/period,vectors_per_cycle=central_vectors/period,frames_per_cycle=central_frames/period))


def analyze_rows(rows, profile, active, mode, length=LENGTH, frames=FRAMES):
    require(profile in PROFILES and active in (0,1) and mode in MODES, 'measurement specification')
    require(length >= 12 and length%12 == 0 and frames >= 8 and frames%4 == 0 and frames*length <= 131071, 'window geometry')
    require(rows and rows[0]['cycle'] == 2, 'missing initial reset trace')
    require(all(set(row) == set(FIELDS) for row in rows), 'trace shape')
    require(all(b['cycle'] == a['cycle']+1 for a,b in zip(rows,rows[1:])), 'missing/duplicate/nonconsecutive cycle')
    expected_cfg = configuration(profile)
    cfg_events, ins, outs = [], [], []
    configured_cycles = []
    for j,row in enumerate(rows):
        c = row['cycle']
        require(all(row[k] in (0,1) for k in BOOLS), 'unknown or nonbinary control')
        require(row['rst'] == (active if c <= 5 else 1-active), 'reset polarity/edge fence')
        require(row['m_ready'] == int(mode == 'ready' or (c-1)%8 < 5), 'ready pattern/cycle alignment')
        require(row['capacity'] == 16 and 0 <= row['fifo'] <= 16 and 0 <= row['pending'] <= 5
                and row['fifo']+3*row['pending'] <= 16 and row['index'] in (0,1,2)
                and 0 <= row['cfg_count'] <= 9 and 0 <= row['cstate'] <= 6, 'active index/FIFO reservation bounds')
        require(row['error'] == 0, 'DUT error')
        if c <= 5:
            require(not any(row[k] for k in ('cfg_valid','cfg_ready','configured','s_valid','s_ready','m_valid',
                'fifo','pending','index','p_valid','e_valid','frame_active','cfg_count','cstate')), 'reset did not clear active state')
            continue
        cfg_take = row['cfg_valid'] and row['cfg_ready']
        take = row['s_valid'] and row['s_ready']
        pop = row['m_valid'] and row['m_ready']
        require(row['m_valid'] == int(row['fifo'] != 0), 'FIFO/valid lifetime')
        expected_ready = (row['configured'] and row['cstate'] == 0 and row['cfg_count'] == 0 and not cfg_take
                          and (row['index'] != 0 or row['fifo']+3*row['pending'] <= 13))
        require(row['s_ready'] == int(expected_ready), 'input-ready/reservation contract')
        expected_cfg_ready = (row['cstate'] == 0 and not row['frame_active'] and row['index'] == 0
                              and row['fifo'] == 0 and row['pending'] == 0 and not row['p_valid'] and not row['e_valid'])
        require(row['cfg_ready'] == int(expected_cfg_ready), 'configuration guard')
        if row['configured']:
            configured_cycles.append(c)
        if cfg_take:
            k = len(cfg_events)
            require(k < 9 and (row['cfg_re'],row['cfg_im']) == expected_cfg[k]
                    and row['cfg_last'] == int(k == 8) and row['cfg_lambda'] == 0, 'actual accepted configuration words')
            cfg_events.append(c)
        if take:
            k = len(ins)
            require(k < frames*length and row['configured'] and (row['s_re'],row['s_im']) == input_pair(k), 'missing/duplicate/incorrect accepted input')
            ins.append(dict(cycle=c,last=row['s_last']))
            require(not row['s_last'] or row['index'] == 2, 'early input TLAST')
        if pop:
            k = len(outs)
            require(k < frames*length and (row['m_re'],row['m_im']) == output_pair(k,profile), 'missing/duplicate/incorrect accepted output')
            outs.append(dict(cycle=c,last=row['m_last']))
        if j+1 < len(rows):
            nxt = rows[j+1]
            require(nxt['fifo'] == row['fifo']+3*row['e_valid']-int(pop), 'FIFO push/pop transition')
            require(nxt['pending'] == row['pending']+int(take and row['index'] == 0)-row['e_valid'], 'vector reservation lifetime')
            require(nxt['index'] == ((row['index']+1)%3 if take else row['index']), 'triple index lifetime')
            require(nxt['p_valid'] == int(take and row['index'] == 2) and nxt['e_valid'] == row['p_valid'], 'pipeline progress')
            require(nxt['frame_active'] == (int(not row['s_last']) if take else row['frame_active']), 'input frame lifetime')
            require(nxt['cfg_count'] == (0 if cfg_take and row['cfg_last'] else row['cfg_count']+1 if cfg_take else row['cfg_count']), 'configuration count lifetime')
        # Protocol holds are checked from adjacent observed edges, independently of TB axis_check.
        if j:
            old = rows[j-1]
            if old['rst'] != active:
                for prefix,payload in (('cfg',('cfg_re','cfg_im','cfg_lambda','cfg_last')),('s',('s_re','s_im','s_last')),('m',('m_re','m_im','m_last'))):
                    if old[prefix+'_valid'] and not old[prefix+'_ready']:
                        require(row[prefix+'_valid'] and all(old[k] == row[k] for k in payload), 'stalled '+prefix+' changed')
    require(len(cfg_events) == 9 and configured_cycles and configured_cycles[0] > cfg_events[-1], 'configuration completion')
    require(configured_cycles == list(range(configured_cycles[0],rows[-1]['cycle']+1)), 'configured dropped')
    require(all(row['s_valid'] for row in rows if ins[0]['cycle'] <= row['cycle'] <= ins[-1]['cycle']), 'continuous offered input interrupted')
    input_stats,output_stats = windows(ins,length,frames),windows(outs,length,frames)
    require(rows[-1]['cycle'] >= outs[-1]['cycle']+20 and all(rows[-1][k] == 0 for k in ('fifo','pending','index','p_valid','e_valid','frame_active','s_valid','m_valid')), 'incomplete drain/quiet guard')
    require(output_stats['central_period']['stop_cycle'] <= ins[-1]['cycle'], 'central output window enters final flush')
    require(input_stats['first'] >= configured_cycles[0], 'data before configuration')
    phases = Counter(row['cstate'] for row in rows if cfg_events[-1] < row['cycle'] < configured_cycles[0])
    require(all(phases[key] == 9 for key in (1,2,5,6)) and phases[3] == 1 and phases[4] > 0, 'configuration matrix entry coverage')
    input_vectors = [ins[k:k+3] for k in range(0,len(ins),3)]
    output_vectors = [outs[k:k+3] for k in range(0,len(outs),3)]
    first_lags = [out[0]['cycle']-inp[-1]['cycle'] for inp,out in zip(input_vectors,output_vectors)]
    last_lags = [out[-1]['cycle']-inp[-1]['cycle'] for inp,out in zip(input_vectors,output_vectors)]
    require(min(first_lags) >= 0, 'output vector precedes complete input vector')
    full_cycles = outs[-1]['cycle']-ins[0]['cycle']+1
    offered = [row for row in rows if ins[0]['cycle'] <= row['cycle'] <= ins[-1]['cycle']]
    return dict(configuration=dict(accepted_words=len(cfg_events),accept_cycles=cfg_events,first=cfg_events[0],last=cfg_events[-1],
        accepted_span_cycles=cfg_events[-1]-cfg_events[0]+1,configured_cycle=configured_cycles[0],
        last_word_to_configured_cycles=configured_cycles[0]-cfg_events[-1],
        first_word_to_configured_cycles=configured_cycles[0]-cfg_events[0],phase_cycles={str(k):phases[k] for k in sorted(phases)}),
        input=input_stats,output=output_stats,
        full_first_input_to_last_output=dict(cycles=full_cycles,input_samples=len(ins),output_samples=len(outs),
            input_vectors=len(input_vectors),output_vectors=len(output_vectors),frames=frames,
            input_samples_per_cycle=len(ins)/full_cycles,output_samples_per_cycle=len(outs)/full_cycles,
            input_vectors_per_cycle=len(input_vectors)/full_cycles,output_vectors_per_cycle=len(output_vectors)/full_cycles),
        vector_latency=dict(scope='Corresponding complete triples; final input acceptance to first/last output acceptance, including backpressure',
            vectors=len(first_lags),last_input_to_first_output_min=min(first_lags),last_input_to_first_output_max=max(first_lags),
            last_input_to_first_output_mean=sum(first_lags)/len(first_lags),last_input_to_last_output_min=min(last_lags),
            last_input_to_last_output_max=max(last_lags),last_input_to_last_output_mean=sum(last_lags)/len(last_lags)),
        input_offered_stall_cycles=sum(row['s_valid'] and not row['s_ready'] for row in offered),
        output_stall_cycles=sum(row['m_valid'] and not row['m_ready'] for row in rows),
        fifo_capacity=16,fifo_peak=max(row['fifo'] for row in rows),pending_vector_peak=max(row['pending'] for row in rows),
        occupied_sample_slots_peak=max(row['fifo']+3*row['pending'] for row in rows),
        simultaneous_push_pop_cycles=sum(row['e_valid'] and row['m_valid'] and row['m_ready'] for row in rows),
        sampled_reset_cycles=sum(row['rst'] == active for row in rows),trace_first_cycle=2,trace_last_cycle=rows[-1]['cycle'])


def analyze(path, profile, active, mode, length=LENGTH, frames=FRAMES):
    return analyze_rows(read_trace(path),profile,active,mode,length,frames)


def specifications():
    return [dict(profile=profile,reset_active=active,mode=mode,length=LENGTH,frames=FRAMES)
            for profile in PROFILES for active in (1,0) for mode in MODES]


def validate_record(record):
    spec = record['specification']
    measured = analyze(record['trace'],spec['profile'],spec['reset_active'],spec['mode'],spec['length'],spec['frames'])
    require(record['metrics'] == measured, 'stored rates/counts/denominators differ from actual trace')
    return measured


def validate_report(report):
    require_pass(report)
    require(report['scope'] == SCOPE and report['physical_timing_verified'] is False
            and report.get('measurement_complete') is True and report['suite'] in ('hdl','all')
            and report['gates'].get('hdl') == 'PASS', 'report scope')
    expected = specifications()
    require(len(report['records']) == 8 and len({json.dumps(r['specification'],sort_keys=True) for r in report['records']}) == 8
            and {json.dumps(r['specification'],sort_keys=True) for r in report['records']} == {json.dumps(r,sort_keys=True) for r in expected}, 'eight-case coverage')
    require(len({r['trace'] for r in report['records']}) == 8, 'duplicate trace paths')
    for record in report['records']:
        validate_record(record)
    require(set(report['trace_fault_controls']) == {'count','drop','duplicate','cycle','reset'}, 'trace fault coverage')
    for control in report['trace_fault_controls'].values():
        text=Path(control['log']).read_text()
        require(isinstance(control['returncode'],int) and control['returncode'] != 0
                and '[RATE]' in text and 'PASS MMSE3' not in text, 'false passing trace fault control')
    return True


def run_command(command, cwd, log, timeout=90, allow_failure=False):
    process = subprocess.Popen([str(value) for value in command],cwd=cwd,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                               text=True,start_new_session=True)
    try:
        output,_ = process.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid,signal.SIGTERM)
        try:
            output,_ = process.communicate(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid,signal.SIGKILL)
            output,_ = process.communicate(timeout=3)
        Path(log).write_text(output+'\n[RATE] subprocess timeout\n')
        raise RuntimeError('[RATE] subprocess timeout: '+str(command[0]))
    Path(log).write_text(output)
    if allow_failure:
        return output,process.returncode
    if process.returncode:
        raise RuntimeError(f'[RATE] command rc{process.returncode}: {command[0]}\n{output[-4000:]}')
    return output


def trace_fault_controls(base, output):
    """Corrupt one actual measured CSV; each independent analyzer CLI must fail."""
    original=read_trace(base)
    point=next(k for k,row in enumerate(original) if k>=len(original)//2 and row['s_valid'] and row['s_ready'])
    folder=output/'trace_fault_controls';folder.mkdir(exist_ok=True)
    controls={};artifacts=[]
    for kind in ('count','drop','duplicate','cycle','reset'):
        rows=list(original)
        if kind=='drop':
            del rows[point]
        elif kind=='duplicate':
            rows.insert(point+1,rows[point])
        else:
            rows[point]=dict(rows[point])
            if kind=='count':rows[point]['s_valid']=0
            elif kind=='cycle':rows[point]['cycle']+=1
            else:rows[point]['rst']=1
        if kind in ('drop','duplicate'):
            rows=[dict(row,cycle=k+2) for k,row in enumerate(rows)]
        trace=folder/(kind+'.csv');log=folder/(kind+'.log')
        with trace.open('w') as fd:
            writer=csv.DictWriter(fd,fieldnames=FIELDS);writer.writeheader();writer.writerows(rows)
        text,code=run_command([sys.executable,ROOT/'tools/run_mmse3_rates.py','--analyze-trace',trace],ROOT,log,
                             timeout=30,allow_failure=True)
        require(code != 0 and '[RATE]' in text and 'PASS MMSE3' not in text, 'trace '+kind+' corruption accepted')
        controls[kind]=dict(returncode=code,log=str(log),trace=str(trace),scope='CSV mutation after actual normal DUT run; no RTL injection')
        artifacts.extend((trace,log))
    return controls,artifacts


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--suite',choices=('python','lint','hdl','all'),default='all')
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/mmse3_rates')
    parser.add_argument('--validate',type=Path,help='Reparse existing completed report and verify source/artifact freshness')
    parser.add_argument('--analyze-trace',type=Path,help='Analyze one CSV only; does not create completed regression evidence')
    parser.add_argument('--profile',choices=PROFILES,default='identity')
    parser.add_argument('--reset-active',type=int,choices=(0,1),default=1)
    parser.add_argument('--mode',choices=MODES,default='ready')
    parser.add_argument('--length',type=int,default=LENGTH)
    parser.add_argument('--frames',type=int,default=FRAMES)
    args = parser.parse_args(argv)
    if args.analyze_trace:
        require_unoptimized();measured=analyze(args.analyze_trace,args.profile,args.reset_active,args.mode,args.length,args.frames)
        print('PASS MMSE3 RATE TRACE');print(json.dumps(measured));return measured
    if args.validate:
        require_unoptimized();validate_report(json.loads(args.validate.read_text()));print('PASS MMSE3 RATE EVIDENCE');return
    output = args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    target = output/'results.json';evidence = begin();write_json(target,dict(evidence,status='RUNNING'))
    records,artifacts,gates = [],[],{}
    controls={}
    try:
        require_unoptimized()
        if args.suite in ('python','all'):
            log = output/'python.log'
            text = run_command([sys.executable,ROOT/'tests/test_mmse3_rates.py'],ROOT,log)
            require(re.search(r'Ran \d+ tests',text) and '\nOK' in text, 'unit tests incomplete')
            artifacts.append(log);gates['python']='PASS'
        if args.suite in ('lint','all'):
            log = output/'lint.log'
            text = run_command(['verilator','--lint-only','-Wall','--top-module','mmse3',*SOURCES],ROOT,log)
            require('%Warning' not in text, 'strict lint warning')
            artifacts.append(log);gates['lint']='PASS'
        if args.suite in ('hdl','all'):
            bindir,_ = questa_paths();work = output/'workdir';work.mkdir(exist_ok=True)
            for name,command in [('vlib',[bindir/'vlib','work']),('compile',[bindir/'vlog','-64','-sv',*SOURCES,
                    ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/mmse3_rate_tb.sv'])]:
                log = work/(name+'.log')
                if name != 'vlib' or not (work/'work').is_dir():
                    text = run_command(command,work,log)
                    require(not re.search(r'\*\* (?:Warning|Error)|(?:Errors|Warnings):\s*[1-9]',text), 'simulator compile diagnostic')
                artifacts.append(log)
            script = work/'mmse3_rates.do'
            script.write_text('onfinish exit\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
            artifacts.append(script)
            for spec in specifications():
                identifier = f'{spec["profile"]}_{spec["mode"]}_reset{spec["reset_active"]}'
                trace,log = output/(identifier+'.csv'),output/(identifier+'.log')
                command = [bindir/'vsim','-64','-c','-quiet','work.mmse3_rate_tb',
                    f'-gPROFILE={PROFILES.index(spec["profile"])}',f'-gRESET_ACTIVE={spec["reset_active"]}',
                    f'-gBACKPRESSURE={int(spec["mode"]!="ready")}',f'-gLENGTH={LENGTH}',f'-gFRAMES={FRAMES}',
                    f'+TRACE={trace}','-do',script.name]
                text = run_command(command,work,log)
                match = re.search(r'PASS MMSE3 RATES: (\d+) cfg, (\d+) inputs, (\d+) outputs, (\d+) frames',text)
                require(match and tuple(map(int,match.groups())) == (9,LENGTH*FRAMES,LENGTH*FRAMES,FRAMES)
                        and not re.search(r'\*\* (?:Error|Fatal|Warning)',text), 'missing/false HDL completion')
                metrics = analyze(trace,spec['profile'],spec['reset_active'],spec['mode'])
                records.append(dict(specification=spec,trace=str(trace),metrics=metrics));artifacts.extend((trace,log))
                print(identifier+': central input/output '+f'{metrics["input"]["central_period"]["samples_per_cycle"]:.6f}/'
                      +f'{metrics["output"]["central_period"]["samples_per_cycle"]:.6f} samples/cycle',flush=True)
            require(len(records) == 8, 'incomplete measurements')
            base=next(r['trace'] for r in records if r['specification']==dict(profile='identity',reset_active=1,mode='ready',length=LENGTH,frames=FRAMES))
            controls,control_artifacts=trace_fault_controls(base,output);artifacts.extend(control_artifacts)
            gates['hdl']='PASS'
        result = dict(finish(evidence,artifacts),status='PASS',suite=args.suite,gates=gates,records=records,scope=SCOPE,
            physical_timing_verified=False,measurement_complete=len(records)==8,trace_fault_controls=controls,
            status_scope='PASS applies to selected suite; actual eight-case measurements require hdl/all and measurement_complete=true',clock='10ns simulation stimulus only; no MHz conversion',
            reset_scope='Initial reset both polarities; trace starts cycle2 after first reset update, includes four reset edges2..5',
            units='One sample is one complex pin transfer; three samples form one observation/output vector; each frame has 3072 samples / 1024 vectors',
            matrix_scope='H=I or H=[[0,0,j],[1,0,0],[0,-1,0]], Q15 coefficients, lambda0; exact W=H^H for integrity tagging only. Other matrices/configurations not measured.')
        write_json(target,result)
    except Exception as error:
        write_json(target,dict(evidence,status='FAIL',error=str(error)));raise
    print('PASS MMSE3 RATE '+args.suite);return result


if __name__ == '__main__':
    main()
