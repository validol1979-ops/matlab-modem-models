#!/usr/bin/env python3
"""Measure actual accepted DSP beat cycles from an independent pre-edge VCD reader."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from datetime import datetime,timezone
import argparse,json,os,re,subprocess,sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from regression_evidence import begin,finish,write_json,require_pass,questa_paths,require_unoptimized
from dsp_uvm_plans import CASES
from run_dsp_uvm import parse_report

SIGNALS=('rst','configured','cfg_valid','cfg_ready','cfg_last','s_valid','s_ready','s_last','m_valid','m_ready','m_last','w_valid','w_ready','w_last')


def beats_summary(cycles):
    if not cycles:raise ValueError('Empty beat stream')
    intervals=[b-a for a,b in zip(cycles,cycles[1:])]
    if any(v<=0 for v in intervals):raise ValueError('Non-increasing beat cycles')
    longest=run=1
    for interval in intervals:
        run=run+1 if interval==1 else 1;longest=max(longest,run)
    return dict(beats=len(cycles),first_cycle=cycles[0],last_cycle=cycles[-1],span_cycles=cycles[-1]-cycles[0]+1,
                minimum_interval=min(intervals) if intervals else None,maximum_interval=max(intervals) if intervals else None,
                mean_interval=sum(intervals)/len(intervals) if intervals else None,
                adjacent_pairs=sum(v==1 for v in intervals),longest_consecutive=longest,
                every_cycle=all(v==1 for v in intervals) if intervals else None)


def read_vcd(path,active):
    """Apply each timestamp atomically; accepted pins come from BEFORE the clock/NBA group."""
    if type(active) is not int or active not in (0,1):raise ValueError('Reset polarity')
    selected={};scope=[];state={};changes={};time=None;scale=None;header=True
    edges=[];configs=[];configured=[];frames={key:[] for key in ('s','m','w')};current={key:[] for key in frames}
    def bit(pins,name):
        value=pins.get(name)
        if value not in ('0','1'):raise ValueError('Unknown/missing physical control '+name)
        return int(value)
    def consume():
        if time is None:return
        old=state.copy();state.update(changes)
        if old.get('clk')!='0' or state.get('clk')!='1':return
        cycle=len(edges);edges.append(time)
        if bit(old,'rst')==active:
            if any(current.values()):raise ValueError('Unexpected mid-stream reset in rate measurement')
            return
        for name in ('configured','cfg_valid','cfg_ready','s_valid','s_ready','m_valid','m_ready','w_valid','w_ready'):bit(old,name)
        if bit(old,'cfg_valid') and bit(old,'cfg_ready'):configs.append(cycle)
        if old.get('configured')=='0' and state.get('configured')=='1':configured.append(cycle)
        for stream in frames:
            if bit(old,stream+'_valid') and bit(old,stream+'_ready'):
                current[stream].append(cycle)
                if bit(old,stream+'_last'):
                    frames[stream].append(current[stream]);current[stream]=[]
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
                    fields=line.split();width,code,name=int(fields[2]),fields[3],fields[4]
                    if name=='clk' and scope==['dsp_uvm_top'] or name in SIGNALS and scope==['dsp_uvm_top','bus']:
                        if width!=1:raise ValueError('Scalar control width')
                        selected.setdefault(code,[]).append(name)
                elif line.startswith('$enddefinitions'):
                    names=[name for values in selected.values() for name in values]
                    if set(names)!=set(SIGNALS)|{'clk'} or len(names)!=len(set(names)) or scale is None:raise ValueError('Complete unique physical VCD controls required')
                    header=False
                continue
            if line.startswith('#'):
                next_time=int(line[1:])
                if time is not None and next_time<=time:raise ValueError('Non-increasing VCD time')
                consume();changes={};time=next_time
            elif line.startswith('$'):continue
            else:
                if line[0] in '01xXzZ':value,code=line[0].lower(),line[1:]
                elif line[0] in 'bB':
                    value,code=line[1:].split();value=value.lower()
                    if len(value)!=1:raise ValueError('Unexpected vector control')
                else:continue
                for name in selected.get(code,[]):changes[name]=value
    consume()
    if header or len(edges)<3 or any(current.values()):raise ValueError('Incomplete VCD stream')
    periods=[(b-a)*scale for a,b in zip(edges,edges[1:])]
    if any(abs(period-10)>1e-9 for period in periods):raise ValueError('Measured simulation clock must be10 ns')
    return dict(frames=frames,configs=configs,configured_cycles=configured,clock_period_ns=10,edges=len(edges))


def measure(path,model,active):
    trace=read_vcd(path,active);frames=trace['frames'];lengths=model['lengths']
    if [len(v) for v in frames['s']]!=[a for a,b in lengths] or [len(v) for v in frames['m']]!=[b for a,b in lengths]:
        raise RuntimeError('VCD accepted frame geometry differs from immutable vectors')
    if [len(v) for v in frames['w']]!=[count for count in model['weight_lengths'] if count]:raise RuntimeError('VCD weight frame geometry')
    if len(trace['configs'])!=model['config_rows']:raise RuntimeError('VCD configuration handshake count')
    rows=[]
    for f,(source,output) in enumerate(zip(frames['s'],frames['m'])):
        if output[0]<source[0] or output[-1]<source[-1]:raise RuntimeError('Non-causal DSP trace')
        row=dict(frame=f,input=beats_summary(source),output=beats_summary(output),
                 first_output_latency_cycles=output[0]-source[0],final_output_latency_cycles=output[-1]-source[-1],
                 transaction_window_cycles=max(output[-1],source[-1])-source[0]+1)
        if model['weight_port']:
            weights=frames['w'][f]
            if weights[0]<source[-1]:raise RuntimeError('Final weights preceded complete input frame')
            row['weights']=beats_summary(weights)
            row['final_weight_latency_cycles']=weights[-1]-source[-1]
            row['transaction_window_cycles']=max(weights[-1],output[-1],source[-1])-source[0]+1
        rows.append(row)
    cfg=trace['configs']
    config=None
    if cfg:
        if len(trace['configured_cycles'])!=1 or trace['configured_cycles'][0]<cfg[-1]:raise RuntimeError('VCD configuration completion event')
        config=dict(transfers=len(cfg),first_cycle=cfg[0],last_cycle=cfg[-1],transfer_span_cycles=cfg[-1]-cfg[0]+1,
                    configured_cycle=trace['configured_cycles'][0],final_transfer_to_configured_cycles=trace['configured_cycles'][0]-cfg[-1])
    return dict(case=model['name'],reset_active=active,clock_period_ns=trace['clock_period_ns'],per_frame=rows,configuration=config,
                input_interframe_gaps=[b[0]-a[-1]-1 for a,b in zip(frames['s'],frames['s'][1:])],
                output_interframe_gaps=[b[0]-a[-1]-1 for a,b in zip(frames['m'],frames['m'][1:])],
                scope='Accepted pins before each rising clock edge; source stream and ready=1 output. Simulated100 MHz, no physical timing claim.')


def run_case(output,name):
    bindir,_=questa_paths();records={};artifacts=[]
    folder=ROOT/'build/rtl/dsp_uvm'/(name+'_vectors');model=json.loads((folder/'model.json').read_text())
    for active in (1,0):
        work=output/f'{name}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
        library=ROOT/'build/rtl/dsp_uvm'/f'{name}_reset_{active}'/'work'
        ini=work/'modelsim.ini';ini.write_text(f'[Library]\nwork = {library}\nothers = {bindir.parent}/modelsim.ini\n')
        script=work/'run.do'
        pins=['/dsp_uvm_top/clk',*('/dsp_uvm_top/bus/'+name for name in SIGNALS)]
        script.write_text('onfinish stop\nonerror {quit -code 13}\nvcd file pins.vcd\nvcd add '+' '.join(pins)+'\nrun -all\nvcd flush\nquit -code 0\n')
        case=model['case'];n=1<<case.get('log2n',5);hop=1<<case.get('log2hop',3)
        args=[bindir/'vsim','-64','-c','-quiet','-voptargs=+acc','-modelsimini',ini,'-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.dsp_uvm_top',
              f'-gLMS_RECIP_FILE={ROOT}/rtl/common/mem/lms_reciprocal.mem',f'-gPHI_FILE={ROOT}/rtl/common/mem/ldpc_phi.mem',f'-gINV_FILE={ROOT}/rtl/common/mem/ldpc_inv.mem',
              f'-gMEM_DIR={ROOT}/rtl/common/mem',f'-gTABLE_DIR={ROOT}/rtl/modems/bpsk_costas_2008_08_25/tables',
              f'-gTWIDDLE_FILE={ROOT}/rtl/common/mem/fft_twiddle_{n}.mem',f'-gWINDOW_FILE={ROOT}/rtl/common/mem/stft_window_{n}.mem',
              f'-gRECIP_FILE={ROOT}/rtl/common/mem/stft_recip_{n}_{hop}.mem',f'+VECTORS={folder}','+SCENARIO=stream','-do',script.name]
        result=subprocess.run([str(v) for v in args],cwd=work,capture_output=True,text=True,timeout=180)
        log=work/'run.log';log.write_text(result.stdout+result.stderr)
        if re.search(r'UI-Msg \(Error\)|No objects found',log.read_text()):raise RuntimeError('Missing VCD objects')
        parse_report(log.read_text(),model,'stream',active,result.returncode)
        record=measure(work/'pins.vcd',model,active);records[f'{name}_reset_{active}']=record
        artifacts.extend([ini,script,log,work/'pins.vcd',folder/'model.json'])
    print('PASS DSP rates '+name,flush=True)
    return records,artifacts


def verified_artifacts(data,root=ROOT):
    require_pass(data,root)
    from run_tests import verified_dsp_uvm_artifacts
    child=root/'build/rtl/dsp_uvm/all_results.json'
    verified_dsp_uvm_artifacts(json.loads(child.read_text()),root)
    expected={f'{name}_reset_{active}' for name in CASES for active in (1,0)}
    if data.get('python_tests')!=5 or data.get('case_selection')!='all' or set(data.get('records',{}))!=expected:raise RuntimeError('Complete DSP rate matrix required')
    for name in CASES:
        model_path=root/'build/rtl/dsp_uvm'/(name+'_vectors')/'model.json';model=json.loads(model_path.read_text())
        if model.get('name')!=name:raise RuntimeError('DSP rate model identity')
        for active in (1,0):
            work=root/'build/rtl/dsp_rates'/f'{name}_reset_{active}'
            for path in (work/'pins.vcd',work/'run.log',model_path):
                if str(path.relative_to(root)) not in data.get('artifact_hashes',{}):raise RuntimeError('Missing DSP rate artifact')
            row=data['records'][f'{name}_reset_{active}']
            if type(row.get('reset_active')) is not int or row!=measure(work/'pins.vcd',model,active):raise RuntimeError('DSP rate record differs from physical VCD')
    return [root/name for name in data['artifact_hashes']]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--case',choices=('all',*CASES),default='all');parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args();require_unoptimized()
    if not 1<=args.jobs<=4:parser.error('--jobs must be1..4')
    child=ROOT/'build/rtl/dsp_uvm/all_results.json';data=json.loads(child.read_text());require_pass(data)
    from run_tests import verified_dsp_uvm_artifacts
    verified_dsp_uvm_artifacts(data)
    evidence=begin();output=ROOT/'build/rtl/dsp_rates';output.mkdir(parents=True,exist_ok=True)
    target=output/(('' if args.case=='all' else args.case+'_')+'results.json');records={};artifacts=[child]
    write_json(target,dict(evidence,status='RUNNING'))
    try:
        result=subprocess.run([sys.executable,ROOT/'tests/test_dsp_stream_rates.py'],cwd=ROOT,capture_output=True,text=True)
        log=output/'python.log';log.write_text(result.stdout+result.stderr);artifacts.append(log)
        if result.returncode or not re.search(r'Ran 5 tests',log.read_text()):raise RuntimeError('DSP timing parser tests failed')
        names=[name for name in CASES if args.case in ('all',name)]
        pool=ThreadPoolExecutor(max_workers=min(args.jobs,len(names)))
        futures=[pool.submit(run_case,output,name) for name in names]
        try:
            for result in as_completed(futures):
                rows,files=result.result();records.update(rows);artifacts.extend(files)
        except Exception:
            for future in futures:future.cancel()
            raise
        finally:pool.shutdown(wait=True,cancel_futures=True)
        write_json(target,dict(finish(evidence,sorted(set(artifacts))),status='PASS',case_selection=args.case,records=records,python_tests=5,
                               scope='Measured DSP pins at simulated100 MHz; per-frame cycle intervals, latency, cfg and weights; one beat/cycle is reported per frame and may fail. Physical timing remains deferred.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise


if __name__=='__main__':main()
