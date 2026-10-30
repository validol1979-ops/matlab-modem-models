#!/usr/bin/env python3
"""Finite deterministic FIFO loads against production II8 Costas (no synthesis)."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import os
from pathlib import Path
import re
import subprocess
import sys

from regression_evidence import ROOT, begin, finish, require_pass, require_unoptimized, questa_paths, write_json
from mmse3_config_width_sweep import exact
sys.path.insert(0, str(ROOT/'common/python'))
import fifo_budget
import sync_fixed

SCOPE = 'Finite deterministic offered loads into initially empty configured axis_fifo/production II8 Costas; exact total capacities, no sustained-rate or physical timing claim'
COLUMNS = 'cycle,s_valid,s_ready,s_last,s_re,s_im,f_valid,f_ready,f_last,f_re,f_im,m_valid,m_ready,m_last,m_re,m_im,m_phase,level,configured'.split(',')
CONTROL = 'cycle,s_valid,s_ready,f_valid,f_ready,m_valid,m_ready,level'.split(',')
PASS = r'PASS FIFO LOAD depth=(\d+) words=(\d+) wait=(\d+) peak=(\d+) held_outputs=(\d+) held_fifo=(\d+)'


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def loads():
    return [
        dict(name='overlap', arrivals=[b*32+j for b in range(4) for j in range(16)], ready_pattern=[1], stall_windows=[]),
        dict(name='drained', arrivals=[b*160+j for b in range(3) for j in range(16)], ready_pattern=[1], stall_windows=[]),
        dict(name='paced_initial', arrivals=list(range(8))+[15+8*j for j in range(56)], ready_pattern=[int(not 16<=j<23) for j in range(37)], stall_windows=[]),
        dict(name='stalled_bursts', arrivals=[b*128+j for b in range(4) for j in range(16)], ready_pattern=[1], stall_windows=[[40,64],[170,194],[310,334]]),
    ]


def model(load, depth=None, trace=False):
    return fifo_budget.costas_fifo_load(load['arrivals'], ready_pattern=load['ready_pattern'], stall_windows=load['stall_windows'], depth=depth, trace=trace)


def fixture(load):
    state=0x439927ab
    inputs=[]
    for j in range(len(load['arrivals'])):
        values=[]
        for _ in range(2):
            state=(1664525*state+1013904223)&0xffffffff
            values.append(state%262144-131072)
        inputs.append([*values, int(j%16==15)])
    gains=list(sync_fixed.costas_gains(.08,.001))
    outputs=[]
    for start in range(0,len(inputs),16):
        chunk=inputs[start:start+16]
        y, phases=sync_fixed.costas([tuple(row[:2]) for row in chunk],gains)
        outputs.extend([int(pair[0]),int(pair[1]),int(phase),int(row[2])] for pair,phase,row in zip(y,phases,chunk))
    return dict(input=inputs, expected=outputs, gains=gains)


def report():
    return dict(scope=SCOPE, loads=[dict(load,budget=model(load)) for load in loads()], rtl_verified=False, rows=[], negative=[], lint=[])


def write_fixture(folder, load):
    folder.mkdir(parents=True, exist_ok=True)
    values=fixture(load)
    horizon=max(model(load,model(load)['minimum_depth']-1)['drained_cycle']+32, model(load)['drained_cycle']+32)
    ready=[load['ready_pattern'][j%len(load['ready_pattern'])] and not any(a<=j<b for a,b in load['stall_windows']) for j in range(horizon)]
    (folder/'load.txt').write_text(f"{len(load['arrivals'])} {horizon}\n"+'\n'.join(map(str,load['arrivals']))+'\n'+'\n'.join(str(int(v)) for v in ready)+'\n')
    for filename,key in [('input.txt','input'),('expected.txt','expected')]:
        rows=values[key]
        (folder/filename).write_text(str(len(rows))+'\n'+''.join(' '.join(map(str,row))+'\n' for row in rows))
    (folder/'config.txt').write_text(' '.join(map(str,values['gains']))+'\n')
    return list(folder.glob('*.txt'))


def measured(path, load, depth, log):
    expected=model(load,depth,trace=True)
    reference=fixture(load)
    with Path(path).open() as handle:
        reader=csv.DictReader(handle)
        require(reader.fieldnames==COLUMNS, 'Missing/changed FIFO load trace columns')
        raw=list(reader)
    require(len(raw)>=len(expected['trace'])+3, 'Missing complete trace and quiet drain')
    samples=[]
    for i,row in enumerate(raw):
        require(set(row)==set(COLUMNS) and all(type(v) is str and re.fullmatch(r'-?\d+',v) for v in row.values()), 'Unknown/invalid active FIFO load trace')
        row={k:int(v) for k,v in row.items()}
        require(row['cycle']==i and row['configured']==1, 'Missing trace cycle/configuration')
        require(all(row[k] in (0,1) for k in ('s_valid','s_ready','s_last','f_valid','f_ready','f_last','m_valid','m_ready','m_last')), 'Nonbinary load pins')
        pattern=load['ready_pattern'][i%len(load['ready_pattern'])]
        require(row['m_ready']==int(pattern and not any(a<=i<b for a,b in load['stall_windows'])), 'Changed sink-ready schedule')
        if i<len(expected['trace']):
            require({k:row[k] for k in CONTROL}==expected['trace'][i], f'Control model mismatch at cycle {i}: actual={row}, expected={expected["trace"][i]}')
        else:
            require(all(row[k]==0 for k in ('s_valid','f_valid','m_valid','level')), 'Nonempty quiet drain')
        samples.append(row)
    for port,key,fields in [('s','input',('s_re','s_im','s_last')),('f','input',('f_re','f_im','f_last')),('m','expected',('m_re','m_im','m_phase','m_last'))]:
        rows=[r for r in samples if r[port+'_valid'] and r[port+'_ready']]
        require([[r[k] for k in fields] for r in rows]==reference[key], 'Changed numeric/phase/order/TLAST trace '+port)
        require([r['cycle'] for r in rows]==expected[dict(s='accepted_cycles',f='service_cycles',m='output_cycles')[port]], 'Changed accepted transfer schedule '+port)
        held=None
        for row in samples:
            if held is not None:
                require(row[port+'_valid']==1 and tuple(row[k] for k in fields)==held, 'Changed held trace word '+port)
            held=tuple(row[k] for k in fields) if row[port+'_valid'] and not row[port+'_ready'] else None
    matches=re.findall(PASS,log)
    require(len(matches)==1 and not re.search(r'\*\* (?:Error|Fatal)|%Error',log), 'Missing/failed load numeric scoreboard')
    actual=dict(zip(('depth','words','wait','peak','held_outputs','held_fifo'),map(int,matches[0])))
    counts=dict(depth=depth, words=len(load['arrivals']), wait=expected['blocked_cycles'], peak=expected['peak'], held_outputs=sum(r['m_valid'] and not r['m_ready'] for r in samples), held_fifo=sum(r['f_valid'] and not r['f_ready'] for r in samples))
    require(actual==counts, 'Summary differs from independent trace replay')
    if depth==expected['minimum_depth']:
        require(expected['blocked_cycles']==0 and expected['accepted_cycles']==load['arrivals'], 'Exact minimum blocked nominal arrivals')
    else:
        require(depth==expected['minimum_depth']-1 and expected['blocked_cycles']>0, 'Short depth did not exercise backpressure')
    if load['name'] in ('paced_initial','stalled_bursts'):
        require(counts['held_outputs']>0, 'Output-stall load did not reach pending output')
    return dict(counts,name=load['name'],drained_cycle=expected['drained_cycle'])


def checked_negative(text, code, tag):
    target={'NUMERIC':'LOAD OUTPUT TARGET','PHASE':'LOAD OUTPUT TARGET','CAPACITY':'LOAD CAPACITY TARGET','PROTOCOL':'LOAD HOLD TARGET'}[tag]
    require(type(code) is int and code==13 and target in text and re.search(r'\*\* Fatal:[^\n]*\['+tag+r'\]',text) and 'PASS FIFO LOAD' not in text, 'Invalid directed load negative control '+tag)
    require(text.index(target)<text.index('** Fatal:'), 'Negative control failed before target')
    if tag=='PROTOCOL':
        require('load Costas output: data changed while stalled' in text, 'Wrong protocol negative rejection')


def check_acceptance(data):
    expected=report()
    require(data.get('scope')==SCOPE and exact(data.get('loads'),expected['loads']) and type(data.get('rtl_verified')) is bool, 'Changed FIFO load model report')
    if not data['rtl_verified']:
        require(all(data.get(k)==[] for k in ('rows','negative','lint')), 'Unverified report contains RTL rows')
        return
    identities={(l['name'],d,a) for l in loads() for d in (model(l)['minimum_depth'],model(l)['minimum_depth']-1) for a in (0,1)}
    require(len(data['rows'])==16 and {(r['name'],r['depth'],r['active']) for r in data['rows']}==identities, 'Missing/duplicate load matrix rows')
    for row in data['rows']:
        load=next(l for l in loads() if l['name']==row['name']);expected=model(load,row['depth'],trace=True)
        require(all(type(row.get(k)) is int and row[k]>=0 for k in ('depth','words','wait','peak','held_outputs','held_fifo','drained_cycle','active')), 'Invalid load row counter')
        require(row['words']==expected['words'] and row['wait']==expected['blocked_cycles'] and row['peak']==expected['peak'] and row['drained_cycle']==expected['drained_cycle'] and
                row['held_outputs']==sum(r['m_valid'] and not r['m_ready'] for r in expected['trace']) and
                row['held_fifo']==sum(r['f_valid'] and not r['f_ready'] for r in expected['trace']), 'Changed load model measurement')
    controls={(a,t) for a in (0,1) for t in ('NUMERIC','PHASE','CAPACITY','PROTOCOL')}
    require(len(data['negative'])==8 and {(r['active'],r['tag']) for r in data['negative']}==controls and all(type(r['active']) is int and type(r['returncode']) is int and r['returncode']==13 for r in data['negative']), 'Missing directed load controls')
    lint_expected={(d,a) for d in {model(l)['minimum_depth']+o for l in loads() for o in (0,-1)} for a in (0,1)}
    require(len(data['lint'])==len(lint_expected) and {(r['depth'],r['active']) for r in data['lint']}==lint_expected and all(type(r['depth']) is int and type(r['active']) is int and type(r['warnings']) is int and r['warnings']==0 for r in data['lint']), 'Incomplete FIFO lint matrix')


def verified_artifacts(data, root=ROOT):
    require_pass(data,root);check_acceptance(data);require(data['rtl_verified'], 'Full RTL FIFO load matrix required')
    def artifact(suffix):
        matches=[root/name for name in data['artifact_hashes'] if name.endswith(suffix)]
        require(len(matches)==1,'Missing/duplicate load artifact '+suffix);return matches[0]
    for row in data['rows']:
        name=f"{row['name']}_d{row['depth']}_a{row['active']}"
        load=next(l for l in loads() if l['name']==row['name'])
        got=dict(measured(artifact('/'+name+'/pins.csv'),load,row['depth'],artifact('/'+name+'/simulation.log').read_text()),active=row['active'])
        require(got==row,'Load row differs from saved raw trace')
    for row in data['negative']:
        checked_negative(artifact(f"/negative_{row['tag']}_a{row['active']}/simulation.log").read_text(),row['returncode'],row['tag'])
    return [root/name for name in data['artifact_hashes']]


def verify_rtl(data,out,jobs):
    q,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    sources=[ROOT/'rtl/common/mem/sync_ram.sv',ROOT/'rtl/common/mem/sync_rom.sv',ROOT/'rtl/common/axis_fifo.sv',pilot/'bpsk_rotate.sv',ROOT/'rtl/common/costas_loop.sv',ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/axis_fifo_load_tb.sv']
    def run(args,cwd,filename,tag=None):
        p=subprocess.run(list(map(str,args)),cwd=cwd,capture_output=True,text=True,timeout=120)
        text=p.stdout+p.stderr;path=cwd/filename;path.write_text(text)
        if tag: checked_negative(text,p.returncode,tag)
        else: require(p.returncode==0 and not re.search(r'\*\* (?:Error|Fatal)|%Warning|%Error',text), f'FIFO load command failed rc={p.returncode} '+str(path)+'\n'+text[-2000:])
        return text,path,p.returncode
    _,p,_=run([q/'vlib','work'],out,'vlib.log');artifacts.append(p)
    _,p,_=run([q/'vlog','-64','-sv',f'+incdir+{pilot}',*sources],out,'compile.log');artifacts.append(p)
    for depth in sorted({model(l)['minimum_depth']+o for l in loads() for o in (0,-1)}):
        for active in (0,1):
            _,p,_=run(['verilator','--lint-only','-Wall','--top-module','axis_fifo',f'-GDEPTH={depth}',f'-GRESET_ACTIVE={active}',*sources[:3]],out,f'lint_d{depth}_a{active}.log')
            artifacts.append(p);data['lint'].append(dict(depth=depth,active=active,warnings=0))
            _,p,_=run([q/'vopt','-64','work.axis_fifo_load_tb',f'-gDEPTH={depth}',f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={pilot}/tables','-o',f'load_d{depth}_a{active}'],out,f'vopt_d{depth}_a{active}.log');artifacts.append(p)
    for load in loads(): artifacts.extend(write_fixture(out/'vectors'/load['name'],load))
    def sim(load,depth,active,tag=None):
        name=f'negative_{tag}_a{active}' if tag else f"{load['name']}_d{depth}_a{active}"
        work=out/name;work.mkdir();script=work/'simulation.do'
        script.write_text('onfinish stop\nonerror {quit -code 13}\n'+('onbreak {quit -code 13}\n' if tag else '')+'run -all\nquit -code 0\n')
        flags=[] if tag is None else ['+'+dict(NUMERIC='INJECT_NUMERIC',PHASE='INJECT_PHASE',CAPACITY='REQUIRE_UNBLOCKED',PROTOCOL='INJECT_HOLD')[tag]]
        text,log,rc=run([q/'vsim','-64','-c','-quiet','-suppress','7032','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'-lib',out/'work',f'load_d{depth}_a{active}',f'+VECTORS={out}/vectors/{load["name"]}',f'+TRACE={work}/pins.csv',*flags,'-do',script.name],work,'simulation.log',tag)
        files=[script,log,work/'pins.csv']
        row=dict(active=active,tag=tag,returncode=rc) if tag else dict(measured(work/'pins.csv',load,depth,text),active=active)
        return ('negative' if tag else 'rows'),row,files
    tasks=[(l,d,a,None) for l in loads() for d in (model(l)['minimum_depth'],model(l)['minimum_depth']-1) for a in (0,1)]
    special=next(l for l in loads() if l['name']=='stalled_bursts')
    tasks.extend((special,model(special)['minimum_depth']-(tag=='CAPACITY'),a,tag) for a in (0,1) for tag in ('NUMERIC','PHASE','CAPACITY','PROTOCOL'))
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for key,row,files in pool.map(lambda task:sim(*task),tasks):data[key].append(row);artifacts.extend(files)
    data['rtl_verified']=True;check_acceptance(data)
    return artifacts


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path);parser.add_argument('--jobs',type=int,default=2)
    args=parser.parse_args();require_unoptimized();require(1<=args.jobs<=4,'jobs must be1..4')
    out=args.output.resolve() if args.output else ROOT/'build/rtl/fifo_load_sweep'
    out.mkdir(parents=True,exist_ok=args.output is None)
    target=out/'results.json';evidence=begin();write_json(target,dict(evidence,status='RUNNING'))
    try:
        data=report();artifacts=verify_rtl(data,out,args.jobs) if args.verify_rtl else []
        check_acceptance(data);write_json(target,dict(data,**finish(evidence,artifacts),status='PASS'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise
    print('PASS FIFO loads:',target)


if __name__=='__main__':main()
