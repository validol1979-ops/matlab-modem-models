#!/usr/bin/env python3
"""Measure modem pin timing and actual capture-memory writes on immutable UVM waves."""
from concurrent.futures import ThreadPoolExecutor, as_completed
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from regression_evidence import begin, finish, write_json, require_pass, questa_paths, require_unoptimized
from dsp_stream_rates import beats_summary
from run_bpsk_uvm import RX_PROFILES, parse_report as parse_rx, parse_profile_report, parse_tx_report
from run_packet_rx_uvm import parse_packet_report
from run_psk_tx_uvm import parse_report as parse_psk_tx, parameters, PROFILES as TX_PROFILES

PROFILES = ('bpsk', *RX_PROFILES, 'oqpsk', 'msk', 'gmsk')
CASES = tuple(name + '_' + direction for direction in ('tx', 'rx') for name in PROFILES)
CHILDREN = ('bpsk_uvm', 'oqpsk_uvm', 'cpm_uvm', 'psk_tx_uvm', 'packet_rx_uvm')
PYTHON_TESTS = 8
BASE = ('rst', 's_valid', 's_ready', 's_last', 'm_valid', 'm_ready', 'm_last')
RX = ('configured', 'cfg_valid', 'cfg_ready', 'cfg_last', 'acquisition_valid', 'error')
GAIN = ('gain_valid', 'gain_ready', 'gain_configured', 'gain_error')


def case_spec(name, root=ROOT):
    """Resolve the existing compiled production UVM library; never regenerate its waves."""
    if name not in CASES:
        raise ValueError('Unknown modem case')
    profile, direction = name.rsplit('_', 1)
    tx = direction == 'tx'
    if tx:
        suite = 'bpsk_uvm' if profile == 'bpsk' else 'oqpsk_uvm' if profile == 'oqpsk' else 'cpm_uvm' if profile in ('msk', 'gmsk') else 'psk_tx_uvm'
        folder = 'tx_vectors' if profile == 'bpsk' else 'vectors' if profile == 'oqpsk' else profile + '_vectors'
        work = 'tx_reset_{active}' if profile == 'bpsk' else 'reset_{active}' if profile == 'oqpsk' else profile + '_reset_{active}'
        prefix = 'tx_' if profile in ('bpsk', 'oqpsk') else profile + '_'
        top = ('bpsk' if profile == 'bpsk' else 'oqpsk' if profile == 'oqpsk' else 'cpm' if profile in ('msk', 'gmsk') else 'psk') + '_tx_uvm_top'
    else:
        suite = 'packet_rx_uvm' if profile in ('oqpsk', 'msk', 'gmsk') else 'bpsk_uvm'
        folder = 'vectors' if profile == 'bpsk' else profile + '_vectors'
        work = 'reset_{active}' if profile == 'bpsk' else profile + '_reset_{active}'
        prefix = '' if profile == 'bpsk' else profile + '_'
        top = 'bpsk_rx_uvm_top'
    parent = root / 'build/rtl' / suite
    report = parent / 'all_results.json'
    return dict(name=name, profile=profile, direction=direction, suite=suite, folder=parent/folder,
                library_pattern=str(parent/work/'work'), prefix=prefix, top=top, report=report)


def vector_lengths(path, columns, last_column=-1):
    lines=Path(path).read_text().splitlines()
    if not lines or int(lines[0]) != len(lines)-1:
        raise ValueError('Malformed immutable vector row count')
    lengths=[]; count=0
    for line in lines[1:]:
        row=[int(v) for v in line.split()]
        if len(row)!=columns or row[last_column] not in (0,1):
            raise ValueError('Malformed immutable vector geometry')
        count+=1
        if row[last_column]:lengths.append(count);count=0
    if count or not lengths:raise ValueError('Missing vector TLAST')
    return lengths


def model_for(spec, active):
    records=json.loads(spec['report'].read_text())['records']
    expected=records[f'{spec["prefix"]}stream_reset_{active}']
    profile=spec['profile']; tx=spec['direction']=='tx'; folder=spec['folder']
    if tx:
        lengths=[1,2,33,192,768];tail=36 if profile=='oqpsk' else 0 if profile=='msk' else 32
        source_file,output_file=('bits.txt','tx.txt') if profile=='bpsk' else ('tx_symbols.txt','tx_out.txt')
        if vector_lengths(folder/source_file,2)!=lengths or vector_lengths(folder/output_file,3)!=[8*n+tail for n in lengths]:
            raise RuntimeError('Independent modem TX frame geometry')
        model=dict(frames=5,frame_symbols=lengths,input_symbols=sum(lengths),output_samples=sum(8*n+tail for n in lengths))
        if profile in TX_PROFILES:
            p=TX_PROFILES[profile]
            model.update(profile=profile,tx_parameters=parameters(profile),alphabet=p.alphabet,
                         label_bits=(p.alphabet-1).bit_length(),labels_seen_mask=(1<<p.alphabet)-1)
        inputs=lengths;outputs=[8*n+tail for n in lengths]
    else:
        inputs=vector_lengths(folder/'rx_wave.txt',5 if profile=='qpsk_diff' else 3)
        if profile=='bpsk':
            model=dict(frames=4,symbols=3072,samples=sum(inputs),
                       payload_errors=[r['payload_errors'] for r in expected['per_frame']],
                       float_payload_errors=[r['float_errors'] for r in expected['float_per_frame']],
                       float_payload_symbols=[r['payload_symbols'] for r in expected['float_per_frame']])
        else:model=records[f'{profile}_model_reset_{active}']
        outputs=vector_lengths(folder/'rx_trace.txt',10,8)
        if len(inputs)!=4 or outputs!=[768]*4 or sum(inputs)!=model['samples'] or model['symbols']!=3072:
            raise RuntimeError('Independent modem RX frame geometry')
    if spec['direction']=='rx':
        source_names=('rx_wave.txt','rx_trace.txt','preamble.txt','float_reference.json','float_expected.txt','float_decisions.txt')
    else:source_names=(source_file,output_file)
    return dict(name=spec['name'],profile=profile,direction=spec['direction'],input_lengths=inputs,output_lengths=outputs,
                simo=not tx and profile=='qpsk_diff',memory_depth=(16512 if profile in ('oqpsk','msk','gmsk') else 16640) if not tx else None,
                filter_tail=32 if not tx and profile not in ('msk','gmsk') else 0,
                numeric_model=model,expected_numeric_record=expected),[folder/file for file in source_names]


def pin_spec(spec):
    top=spec['top']; result={'clk':(f'{top}/clk',1)}
    signals=BASE + (RX if spec['direction']=='rx' else ()) + (GAIN if spec['name']=='qpsk_diff_rx' else ())
    result.update({name:(f'{top}/bus/{name}',1) for name in signals})
    if spec['direction']=='rx':
        profile=spec['profile']
        branch='g_simo/dut/receiver' if profile=='qpsk_diff' else 'g_packet/g_oqpsk/dut' if profile=='oqpsk' else 'g_packet/g_cpm/dut' if profile in ('msk','gmsk') else 'g_single/dut'
        receiver=f'{top}/{branch}'
        result['occupied']=(receiver+'/occupied',2)
        result.update({key:(receiver+'/samples/'+key,width) for key,width in (('wr_en',1),('wr_frame',1),('wr_index',15))})
    return result


def read_vcd(path, active, pins):
    """Sample the old pin state before *all* changes at a rising-edge timestamp."""
    if type(active) is not int or active not in (0,1):raise ValueError('Reset polarity')
    by_path={p:(name,width) for name,(p,width) in pins.items()}
    if len(by_path)!=len(pins):raise ValueError('Duplicate physical pin path')
    scope=[];selected={};found={};state={};changes={};time=None;scale=None;header=True
    edges=[];frames={'s':[],'m':[]};current={'s':[],'m':[]};waits=[];offers=[];acquisitions=[];configs=[];cfg_ends=[];configured=[];gains=[];gain_configured=[]
    writes=[];memory_frames=[];max_occupied=0;released=False;traffic=False;source_waits=0;first_offer=None
    def value(values,name):
        raw=values.get(name)
        if raw is None or re.search('[^01]',raw):raise ValueError('Unknown/missing sampled physical pin '+name)
        return int(raw,2)
    def consume():
        nonlocal max_occupied,released,traffic,source_waits,first_offer,writes
        if time is None:return
        old=state.copy();state.update(changes)
        if old.get('clk')!='0' or state.get('clk')!='1':return
        cycle=len(edges);edges.append(time)
        if value(old,'rst')==active:
            if released:raise ValueError('Unexpected reset after release')
            return
        released=True
        for name in ('s_valid','s_ready','m_valid','m_ready'):value(old,name)
        if not value(old,'m_ready'):raise ValueError('Timing replay requires an always-ready output')
        if 'configured' in pins:
            for name in ('configured','cfg_valid','cfg_ready','acquisition_valid','error'):value(old,name)
            if value(old,'error'):raise ValueError('Receiver error during timing replay')
            if value(old,'cfg_valid') and value(old,'cfg_ready'):
                configs.append(cycle)
                if value(old,'cfg_last'):cfg_ends.append(cycle)
            if old.get('configured')=='0' and state.get('configured')=='1':configured.append(cycle)
            if value(old,'acquisition_valid'):acquisitions.append(cycle)
        if 'gain_valid' in pins:
            for name in GAIN:value(old,name)
            if value(old,'gain_error'):raise ValueError('Gain configuration error')
            if value(old,'gain_valid') and value(old,'gain_ready'):gains.append(cycle)
            if old.get('gain_configured')=='0' and state.get('gain_configured')=='1':gain_configured.append(cycle)
        if value(old,'s_valid'):
            traffic=True
            if first_offer is None:first_offer=cycle
            if not value(old,'s_ready'):source_waits+=1
        for stream in frames:
            if value(old,stream+'_valid') and value(old,stream+'_ready'):
                current[stream].append(cycle)
                if value(old,stream+'_last'):
                    frames[stream].append(current[stream]);current[stream]=[]
                    if stream=='s':
                        waits.append(source_waits);offers.append(first_offer);source_waits=0;first_offer=None
        if 'occupied' in pins:
            max_occupied=max(max_occupied,value(old,'occupied').bit_count(),value(state,'occupied').bit_count())
            if value(old,'wr_en'):
                index,bank=value(old,'wr_index'),value(old,'wr_frame')
                if index==0:
                    if writes:memory_frames.append(writes)
                    writes=[]
                if index!=len(writes) or bank!=len(memory_frames)%2:raise ValueError('Non-sequential or wrong capture-memory address')
                writes.append(cycle)
    with Path(path).open() as handle:
        for line in handle:
            line=line.strip()
            if not line:continue
            if header:
                if line.startswith('$timescale'):
                    expression=line
                    while '$end' not in expression:expression+=' '+next(handle).strip()
                    match=re.fullmatch(r'\$timescale\s+(1|10|100)\s*(s|ms|us|ns|ps|fs)\s+\$end',expression)
                    if not match:raise ValueError('Unsupported VCD timescale')
                    scale=int(match[1])*dict(s=1e9,ms=1e6,us=1e3,ns=1,ps=1e-3,fs=1e-6)[match[2]]
                elif line.startswith('$scope'):scope.append(line.split()[2])
                elif line.startswith('$upscope'):scope.pop()
                elif line.startswith('$var'):
                    fields=line.split();width,code=int(fields[2]),fields[3];full='/'.join([*scope,fields[4]])
                    if full in by_path:
                        name,expected=by_path[full]
                        bit_match=re.fullmatch(r'\[(\d+)\]',fields[5]) if len(fields)>6 else None
                        bit_index=int(bit_match[1]) if bit_match else None
                        bits={bit_index} if bit_index is not None else set(range(expected))
                        if (width!=(1 if bit_index is not None else expected) or not bits<=set(range(expected)) or bits & found.get(name,set())):
                            raise ValueError('Duplicate/wrong-width VCD pin')
                        found.setdefault(name,set()).update(bits)
                        selected.setdefault(code,[]).append((name,expected,bit_index))
                elif line.startswith('$enddefinitions'):
                    if any(found.get(name)!=set(range(width)) for name,(path,width) in pins.items()) or scale is None:raise ValueError('Complete unique physical VCD pins required')
                    header=False
                continue
            if line.startswith('#'):
                next_time=int(line[1:])
                if time is not None and next_time<=time:raise ValueError('Non-increasing VCD time')
                consume();changes={};time=next_time
            elif line.startswith('$'):continue
            else:
                if line[0] in '01xXzZ':raw,code=line[0].lower(),line[1:]
                elif line[0] in 'bB':raw,code=line[1:].split();raw=raw.lower()
                else:continue
                for name,width,bit_index in selected.get(code,[]):
                    if len(raw)>(1 if bit_index is not None else width):raise ValueError('Oversized VCD value')
                    if bit_index is None:changes[name]=raw.rjust(width,raw[0] if raw[0] in 'xz' else '0')
                    else:
                        bits=list(changes.get(name,state.get(name,'x'*width)))
                        bits[width-1-bit_index]=raw;changes[name]=''.join(bits)
    consume()
    if writes:memory_frames.append(writes)
    if header or len(edges)<3 or not traffic or any(current.values()) or source_waits or first_offer is not None:raise ValueError('Incomplete modem VCD stream')
    if any(abs((b-a)*scale-10)>1e-9 for a,b in zip(edges,edges[1:])):raise ValueError('Measured clock must be10 ns')
    return dict(frames=frames,source_waits=waits,first_offers=offers,configs=configs,cfg_ends=cfg_ends,configured=configured,gains=gains,gain_configured=gain_configured,
                acquisitions=acquisitions,max_occupied=max_occupied,memory_frames=memory_frames,clock_period_ns=10)


def configuration_summary(transfers,completions):
    if len(completions)!=1 or not transfers or completions[0]<transfers[-1]:raise RuntimeError('Configuration completion geometry')
    return dict(transfers=len(transfers),first_cycle=transfers[0],last_cycle=transfers[-1],configured_cycle=completions[0],
                final_transfer_to_configured_cycles=completions[0]-transfers[-1])


def measure(path,model,active,pins):
    trace=read_vcd(path,active,pins);source,output=trace['frames']['s'],trace['frames']['m'];rx=model['direction']=='rx'
    if [len(f) for f in source]!=model['input_lengths'] or [len(f) for f in output]!=model['output_lengths']:raise RuntimeError('VCD immutable frame geometry')
    if rx:
        if len(trace['acquisitions'])!=len(source) or len(trace['configs'])!=192 or trace['cfg_ends']!=[trace['configs'][-1]]:raise RuntimeError('Receiver acquisition/configuration count or cfg TLAST')
        if [len(f) for f in trace['memory_frames']]!=[n+model['filter_tail'] for n in model['input_lengths']]:raise RuntimeError('Capture-memory write count differs from immutable frame plus filter flush')
        if trace['max_occupied'] not in (1,2):raise RuntimeError('Capture buffer occupancy')
    elif trace['configs'] or trace['acquisitions'] or trace['memory_frames']:raise RuntimeError('Unexpected TX configuration/capture ports')
    rows=[]
    for f,(s,m) in enumerate(zip(source,output)):
        if m[0]<s[0]:raise RuntimeError('Non-causal modem output')
        row=dict(frame=f,input=beats_summary(s),output=beats_summary(m),first_offer_cycle=trace['first_offers'][f],
                 first_offer_to_accept_cycles=s[0]-trace['first_offers'][f],input_stall_cycles=trace['source_waits'][f],
                 input_source_gap_cycles=s[-1]-s[0]+1-len(s)-(trace['source_waits'][f]-(s[0]-trace['first_offers'][f])),
                 first_output_latency_cycles=m[0]-s[0],final_output_latency_cycles=m[-1]-s[-1],
                 transaction_window_cycles=max(s[-1],m[-1])-s[0]+1)
        if row['input_source_gap_cycles']!=0:raise RuntimeError('Timing stream source has gaps within a frame')
        if rx:
            acquisition=trace['acquisitions'][f];writes=trace['memory_frames'][f]
            if not s[0]<=acquisition<=m[0]:raise RuntimeError('Non-causal acquisition')
            if len(writes)>model['memory_depth']:raise RuntimeError('Capture memory capacity exceeded')
            row.update(acquisition_cycle=acquisition,acquisition_latency_cycles=acquisition-s[0],
                       input_samples_at_acquisition=sum(cycle<=acquisition for cycle in s),capture_writes=beats_summary(writes),
                       capture_high_water_samples=len(writes),capture_headroom_samples=model['memory_depth']-len(writes))
        rows.append(row)
    result=dict(case=model['name'],reset_active=active,clock_period_ns=10,input_unit='complex sample pair (two SIMO branches)' if model['simo'] else 'complex sample' if rx else 'symbol label',
                output_unit='symbol label with soft values' if rx else 'complex sample',per_frame=rows,
                configuration=configuration_summary(trace['configs'],trace['configured']) if rx else None,
                gain_configuration=configuration_summary(trace['gains'],trace['gain_configured']) if model['simo'] else None,
                capture_memory=dict(buffers=2,samples_per_buffer=model['memory_depth'],sample_bits=36,total_storage_bits=2*model['memory_depth']*36,peak_occupied_buffers=trace['max_occupied']) if rx else None,
                input_interframe_gaps=[b[0]-a[-1]-1 for a,b in zip(source,source[1:])],output_interframe_gaps=[b[0]-a[-1]-1 for a,b in zip(output,output[1:])],
                scope='Accepted physical pins before each rising edge; always-ready sink and production stream source without gaps within frames. Simulated100 MHz; finite frames and source interframe gaps do not prove sustained throughput or physical timing.')
    if model['simo'] and len(trace['gains'])!=1:raise RuntimeError('SIMO gain tuple count')
    window=max(source[-1][-1],output[-1][-1])-source[0][0]+1
    result['observation']=dict(window_cycles=window,input_beats=sum(map(len,source)),output_beats=sum(map(len,output)),
                               input_beats_per_cycle=sum(map(len,source))/window,output_beats_per_cycle=sum(map(len,output))/window)
    return result


def numeric_record(spec,model,text,active,rc):
    profile=spec['profile'];native=model['numeric_model']
    if spec['direction']=='tx':
        if profile in TX_PROFILES:row=parse_psk_tx(text,native,'stream',active,rc)
        else:row=parse_tx_report(text,native,'stream',active,rc,modulation=profile.upper())
    elif profile in ('oqpsk','msk','gmsk'):row=parse_packet_report(text,native,'stream',active,rc)
    elif profile=='bpsk':row=parse_rx(text,native,'stream',active,rc)
    else:row=parse_profile_report(text,native,'stream',active,rc)
    if row!=model['expected_numeric_record']:raise RuntimeError('Replay numeric/protocol report differs from accepted original UVM stream')
    return row


def validate_children(root=ROOT):
    from run_tests import verified_bpsk_uvm_artifacts,verified_oqpsk_uvm_artifacts,verified_cpm_uvm_artifacts,verified_psk_tx_uvm_artifacts,verified_packet_rx_uvm_artifacts
    functions=(verified_bpsk_uvm_artifacts,verified_oqpsk_uvm_artifacts,verified_cpm_uvm_artifacts,verified_psk_tx_uvm_artifacts,verified_packet_rx_uvm_artifacts)
    reports=[]
    for suite,validator in zip(CHILDREN,functions):
        path=root/'build/rtl'/suite/'all_results.json';validator(json.loads(path.read_text()),root);reports.append(path)
    return reports


def run_case(output,name):
    spec=case_spec(name);bindir,_=questa_paths();pins=pin_spec(spec);records={};artifacts=[]
    for active in (1,0):
        model,files=model_for(spec,active);artifacts.extend(files)
        work=output/f'{name}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
        model_path=work/'model.json';write_json(model_path,model)
        ini=work/'modelsim.ini';ini.write_text(f'[Library]\nwork = {spec["library_pattern"].format(active=active)}\nothers = {bindir.parent}/modelsim.ini\n')
        script=work/'run.do';script.write_text('onfinish stop\nonerror {quit -code 13}\nvcd file pins.vcd\nvcd add '+' '.join('/'+p for p,width in pins.values())+'\nrun -all\nvcd flush\nquit -code 0\n')
        args=[bindir/'vsim','-64','-c','-quiet','-voptargs=+acc','-modelsimini',ini,'-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.'+spec['top'],
              f'+VECTORS={spec["folder"]}','+SCENARIO=stream','-do',script.name]
        if spec['direction']=='rx' or spec['profile'] in ('msk','gmsk'):args.append(f'-gTABLE_DIR={ROOT}/rtl/modems/bpsk_costas_2008_08_25/tables')
        if spec['direction']=='rx':args.extend(['+SYMBOLS=768','+FLOAT_SER',*(['+CHECK_RESET_PREFIX'] if spec['profile']!='bpsk' else [])])
        result=subprocess.run([str(v) for v in args],cwd=work,capture_output=True,text=True,timeout=180)
        text=result.stdout+result.stderr;log=work/'run.log';log.write_text(text)
        if re.search(r'UI-Msg \(Error\)|No objects found',text):raise RuntimeError('Missing modem VCD pins')
        numeric_record(spec,model,text,active,result.returncode)
        records[f'{name}_reset_{active}']=measure(work/'pins.vcd',model,active,pins)
        artifacts.extend([ini,script,log,work/'pins.vcd',model_path])
    print('PASS modem rates '+name,flush=True)
    return records,artifacts


def verified_artifacts(data,root=ROOT):
    require_pass(data,root);children=validate_children(root)
    expected={f'{name}_reset_{active}' for name in CASES for active in (1,0)}
    if data.get('python_tests')!=PYTHON_TESTS or data.get('case_selection')!='all' or set(data.get('records',{}))!=expected:raise RuntimeError('Complete modem timing matrix required')
    required=list(children)
    for name in CASES:
        spec=case_spec(name,root)
        for active in (1,0):
            work=root/'build/rtl/modem_rates'/f'{name}_reset_{active}';model,files=model_for(spec,active)
            required.extend([work/'pins.vcd',work/'run.log',work/'model.json',*files])
            if json.loads((work/'model.json').read_text())!=model:raise RuntimeError('Modem timing model differs from immutable child vectors')
            numeric_record(spec,model,(work/'run.log').read_text(),active,0)
            record=data['records'][f'{name}_reset_{active}']
            if type(record.get('reset_active')) is not int or record!=measure(work/'pins.vcd',model,active,pin_spec(spec)):raise RuntimeError('Modem timing record differs from physical VCD')
    if any(str(path.relative_to(root)) not in data.get('artifact_hashes',{}) for path in required):raise RuntimeError('Missing modem timing artifact')
    return [root/name for name in data['artifact_hashes']]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=('all',*CASES),default='all');parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args();require_unoptimized()
    if not 1<=args.jobs<=4:parser.error('--jobs must be1..4')
    children=validate_children();evidence=begin();output=ROOT/'build/rtl/modem_rates';output.mkdir(parents=True,exist_ok=True)
    target=output/(('' if args.case=='all' else args.case+'_')+'results.json');records={};artifacts=list(children)
    write_json(target,dict(evidence,status='RUNNING'))
    try:
        result=subprocess.run([sys.executable,ROOT/'tests/test_modem_stream_rates.py'],cwd=ROOT,capture_output=True,text=True)
        log=output/'python.log';log.write_text(result.stdout+result.stderr);artifacts.append(log)
        if result.returncode or not re.search(r'Ran '+str(PYTHON_TESTS)+r' tests',log.read_text()):raise RuntimeError('Modem timing parser tests failed')
        selected=[name for name in CASES if args.case in ('all',name)]
        pool=ThreadPoolExecutor(max_workers=min(args.jobs,len(selected)))
        futures=[pool.submit(run_case,output,name) for name in selected]
        try:
            for future in as_completed(futures):
                rows,files=future.result();records.update(rows);artifacts.extend(files)
        except Exception:
            for future in futures:future.cancel()
            raise
        finally:pool.shutdown(wait=True,cancel_futures=True)
        write_json(target,dict(finish(evidence,sorted(set(artifacts))),status='PASS',records=records,case_selection=args.case,python_tests=PYTHON_TESTS,
                               scope='Physical modem TX/RX VCD replays; actual acquisition/capture/configuration/stream timings with repeat numeric UVM checks. Physical synthesis remains deferred.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise


if __name__=='__main__':main()
