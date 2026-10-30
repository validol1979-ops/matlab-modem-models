#!/usr/bin/env python3
"""Finite WIDTH72 FIFO loads with production LMS/NLMS and independent output stalls."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import csv
import os
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,require_pass,require_unoptimized,questa_paths,write_json
from mmse3_config_width_sweep import exact
sys.path.insert(0,str(ROOT/'common/python'))
import fifo_budget
import lms_fixed

SCOPE='Finite deterministic offered loads into initially empty configured WIDTH72 axis_fifo and production LMS/NLMS; independent sample/weight backpressure; exact total capacity, no sustained-rate or physical timing claim'
FRAMES=[1,7,8]
COLUMNS='cycle,s_valid,s_ready,s_last,s_re,s_im,s_dre,s_dim,f_valid,f_ready,f_last,f_re,f_im,f_dre,f_dim,m_valid,m_ready,m_last,m_pre,m_pim,m_ere,m_eim,w_valid,w_ready,w_last,w_re,w_im,level,configured,error'.split(',')
CONTROL='cycle,s_valid,s_ready,s_last,f_valid,f_ready,f_last,m_valid,m_ready,m_last,w_valid,w_ready,w_last,level'.split(',')
PASS=r'PASS LMS FIFO LOAD depth=(\d+) words=(\d+) weights=(\d+) wait=(\d+) peak=(\d+) held_data=(\d+) held_weights=(\d+) held_fifo=(\d+)'
KINDS=('NUMERIC','WEIGHTS','CAPACITY','M_HOLD','W_HOLD')


def require(condition,message):
    if not condition:raise RuntimeError(message)


def profiles():
    return [dict(name=f'{mode}_t{taps}',mode=mode,taps=taps,log2n=(taps-1).bit_length(),step=.05 if mode=='lms' else .5,eps=.01) for mode in ('lms','nlms') for taps in (1,3,8,16)]


def loads():
    base=dict(m_ready_pattern=[1],w_ready_pattern=[1],m_stall_windows=[],w_stall_windows=[])
    dense=list(range(sum(FRAMES)))
    return [dict(base,name='dense',arrivals=dense),
        dict(base,name='paced',arrivals=list(range(4))+[12+9*j for j in range(12)]),
        dict(base,name='mstall',arrivals=dense,m_ready_pattern=[int(not 10<=j<26) for j in range(41)],m_stall_windows=[[4,42]]),
        dict(base,name='wstall',arrivals=dense,w_ready_pattern=[int(j==20) for j in range(29)]),
        dict(base,name='mixed',arrivals=dense,w_ready_pattern=[int(j==20) for j in range(29)],m_stall_windows=[[4,42]])]


def model(profile,load,depth=None,trace=False):
    return fifo_budget.lms_fifo_load(load['arrivals'],frame_lengths=FRAMES,taps=profile['taps'],mode=profile['mode'],
        m_ready_pattern=load['m_ready_pattern'],w_ready_pattern=load['w_ready_pattern'],m_stall_windows=load['m_stall_windows'],w_stall_windows=load['w_stall_windows'],depth=depth,trace=trace)


def fixture(profile):
    state=0x79183c25+profile['taps'];inputs=[];outputs=[];weights=[]
    params=lms_fixed.parameters(profile['step'],profile['eps'])
    for frame,length in enumerate(FRAMES):
        x=[];d=[]
        for j in range(length):
            values=[]
            for _ in range(4):
                state=(1664525*state+1013904223)&0xffffffff;values.append(state%262144-131072)
            if frame==0 and j==0:values=[-131072,131071,131071,-131072]
            x.append(tuple(values[:2]));d.append(tuple(values[2:]));inputs.append([*values,int(j==length-1)])
        result,ws=lms_fixed.adapt(x,d,profile['taps'],profile['mode'],params)
        outputs.extend([*prediction,*error,int(j==length-1)] for j,(prediction,error) in enumerate(result))
        weights.extend([*w,int(j==profile['taps']-1)] for j,w in enumerate(ws))
    return dict(input=inputs,expected=outputs,weights=weights,config=[int(profile['mode']=='nlms'),profile['taps'],*params])


def report():
    return dict(scope=SCOPE,frame_lengths=list(FRAMES),profiles=profiles(),loads=loads(),budgets=[dict(profile=p['name'],load=l['name'],budget=model(p,l)) for p in profiles() for l in loads()],rtl_verified=False,rows=[],negative=[],lint=[])


def ready(load,port,cycle):
    return int(load[port+'_ready_pattern'][cycle%len(load[port+'_ready_pattern'])] and not any(a<=cycle<b for a,b in load[port+'_stall_windows']))


def write_fixture(folder,profile,load):
    folder.mkdir(parents=True,exist_ok=True);values=fixture(profile);minimum=model(profile,load)['minimum_depth']
    horizon=max(model(profile,load,d)['drained_cycle'] for d in (minimum,minimum-1))+32
    (folder/'load.txt').write_text(f"{len(load['arrivals'])} {horizon}\n"+'\n'.join(map(str,load['arrivals']))+'\n'+''.join(f"{ready(load,'m',j)} {ready(load,'w',j)}\n" for j in range(horizon)))
    for filename,key in [('input.txt','input'),('expected.txt','expected'),('weights.txt','weights')]:
        rows=values[key];(folder/filename).write_text(str(len(rows))+'\n'+''.join(' '.join(map(str,r))+'\n' for r in rows))
    (folder/'config.txt').write_text(' '.join(map(str,values['config']))+'\n')
    return list(folder.glob('*.txt'))


def schedule_coverage(rows,taps):
    weights=[r['cycle'] for r in rows if r['w_valid'] and r['w_ready']]
    outputs=[r['cycle'] for r in rows if r['m_valid'] and r['m_ready']]
    services=[r['cycle'] for r in rows if r['f_valid'] and r['f_ready']]
    return dict(held_last_weights=sum(r['w_valid'] and r['w_last'] and not r['w_ready'] for r in rows),
        simultaneous_output_holds=sum(r['m_valid'] and not r['m_ready'] and r['w_valid'] and not r['w_ready'] for r in rows),
        singleton_weights_before_data=int(weights[taps-1]<outputs[0] and services[1]>=outputs[0]+1))


def measured(path,profile,load,depth,log):
    replay=model(profile,load,depth,trace=True);reference=fixture(profile)
    with Path(path).open() as handle:
        reader=csv.DictReader(handle);require(reader.fieldnames==COLUMNS,'Missing/changed LMS FIFO trace columns');raw=list(reader)
    require(len(raw)>=len(replay['trace'])+3,'Missing LMS completed trace/quiet drain')
    rows=[]
    for cycle,row in enumerate(raw):
        require(set(row)==set(COLUMNS) and all(type(v) is str and re.fullmatch(r'-?\d+',v) for v in row.values()),'Unknown/invalid active LMS trace')
        row={k:int(v) for k,v in row.items()}
        require(row['cycle']==cycle and row['configured']==1 and row['error']==0,'Missing cycle/LMS configuration')
        require(all(row[k] in (0,1) for k in ('s_valid','s_ready','s_last','f_valid','f_ready','f_last','m_valid','m_ready','m_last','w_valid','w_ready','w_last')),'Nonbinary LMS pins')
        require(row['m_ready']==ready(load,'m',cycle) and row['w_ready']==ready(load,'w',cycle),'Changed independent LMS sink schedule')
        if cycle<len(replay['trace']):
            require({k:row[k] for k in CONTROL}=={k:replay['trace'][cycle][k] for k in CONTROL},f'LMS control mismatch at{cycle}: actual={row}, expected={replay["trace"][cycle]}')
        else:require(all(row[k]==0 for k in ('s_valid','f_valid','m_valid','w_valid','level')),'Nonempty LMS quiet drain')
        rows.append(row)
    specs=[('s','input',('s_re','s_im','s_dre','s_dim','s_last'),'accepted_cycles'),('f','input',('f_re','f_im','f_dre','f_dim','f_last'),'service_cycles'),('m','expected',('m_pre','m_pim','m_ere','m_eim','m_last'),'output_cycles'),('w','weights',('w_re','w_im','w_last'),'weight_cycles')]
    for port,key,fields,cycle_key in specs:
        accepted=[r for r in rows if r[port+'_valid'] and r[port+'_ready']]
        require([[r[k] for k in fields] for r in accepted]==reference[key],'LMS numeric/order/TLAST mismatch '+port)
        require([r['cycle'] for r in accepted]==replay[cycle_key],'LMS accepted schedule mismatch '+port)
        held=None
        for row in rows:
            if held is not None:require(row[port+'_valid']==1 and tuple(row[k] for k in fields)==held,'LMS held data/valid changed '+port)
            held=tuple(row[k] for k in fields) if row[port+'_valid'] and not row[port+'_ready'] else None
    matches=re.findall(PASS,log);require(len(matches)==1 and not re.search(r'\*\* (?:Error|Fatal)|%Error',log),'Missing/failed LMS scoreboard')
    measured_counts=dict(zip(('depth','words','weights','wait','peak','held_data','held_weights','held_fifo'),map(int,matches[0])))
    counts=dict(depth=depth,words=len(reference['input']),weights=len(reference['weights']),wait=replay['blocked_cycles'],peak=replay['peak'],held_data=sum(r['m_valid'] and not r['m_ready'] for r in rows),held_weights=sum(r['w_valid'] and not r['w_ready'] for r in rows),held_fifo=sum(r['f_valid'] and not r['f_ready'] for r in rows))
    require(measured_counts==counts,'LMS summary differs from raw/model replay')
    counts.update(schedule_coverage(rows,profile['taps']))
    if depth==replay['minimum_depth']:require(replay['blocked_cycles']==0 and replay['accepted_cycles']==load['arrivals'],'Minimum LMS depth blocked nominal load')
    else:require(depth==replay['minimum_depth']-1 and replay['blocked_cycles']>0,'Short LMS depth did not block')
    if load['name']=='mstall':
        require(counts['held_data']>0 and counts['singleton_weights_before_data']==1,'Missing singleton data-held after complete weight dump')
    if load['name'] in ('wstall','mixed'):
        require(counts['held_weights']>0 and counts['held_last_weights']>0,'No pending final-weight stall reached')
    if load['name']=='mixed':require(counts['simultaneous_output_holds']>0,'No simultaneous-output stall reached')
    return dict(counts,profile=profile['name'],load=load['name'],drained_cycle=replay['drained_cycle'])


def checked_negative(text,code,kind):
    targets=dict(NUMERIC='LMS LOAD DATA TARGET',WEIGHTS='LMS LOAD WEIGHTS TARGET',CAPACITY='LMS LOAD CAPACITY TARGET',M_HOLD='LMS LOAD HOLD DATA TARGET',W_HOLD='LMS LOAD HOLD WEIGHTS TARGET')
    tag='PROTOCOL' if kind in ('M_HOLD','W_HOLD') else kind
    target=targets[kind]
    require(type(code) is int and code==13 and target in text and re.search(r'\*\* Fatal:[^\n]*\['+tag+r'\]',text) and 'PASS LMS FIFO LOAD' not in text,'Invalid directed LMS negative '+kind)
    require(text.index(target)<text.index('** Fatal:'),'LMS negative failed before target')
    if kind in ('M_HOLD','W_HOLD'):
        message='LMS load '+('data' if kind=='M_HOLD' else 'weight')+' output: data changed while stalled'
        require(message in text,'Wrong LMS held-output rejection')


def configurations():
    return {(p['log2n'],model(p,l)['minimum_depth']+offset,a) for p in profiles() for l in loads() for offset in (0,-1) for a in (0,1)}


def check_acceptance(data):
    expected=report()
    require(all(exact(data.get(k),expected[k]) for k in ('scope','frame_lengths','profiles','loads','budgets')) and type(data.get('rtl_verified')) is bool,'Changed LMS FIFO model report')
    if not data['rtl_verified']:
        require(all(data.get(k)==[] for k in ('rows','negative','lint')),'Unverified report contains LMS RTL rows');return
    identities={(p['name'],l['name'],model(p,l)['minimum_depth']+o,a) for p in profiles() for l in loads() for o in (0,-1) for a in (0,1)}
    require(len(data['rows'])==len(identities) and {(r['profile'],r['load'],r['depth'],r['active']) for r in data['rows']}==identities,'Incomplete/duplicate LMS load matrix')
    for row in data['rows']:
        require(all(type(row.get(k)) is int and row[k]>=0 for k in ('depth','words','weights','wait','peak','held_data','held_weights','held_fifo','drained_cycle','active','held_last_weights','singleton_weights_before_data','simultaneous_output_holds')),'Invalid LMS counter/identity')
        profile=next(p for p in profiles() if p['name']==row['profile']);load=next(l for l in loads() if l['name']==row['load']);replay=model(profile,load,row['depth'],trace=True)
        require(row['words']==sum(FRAMES) and row['weights']==len(FRAMES)*profile['taps'] and row['wait']==replay['blocked_cycles'] and row['peak']==replay['peak'] and row['drained_cycle']==replay['drained_cycle'],'Changed LMS model measurement')
        for key,port in [('held_data','m'),('held_weights','w'),('held_fifo','f')]:require(row[key]==sum(r[port+'_valid'] and not r[port+'_ready'] for r in replay['trace']),'Changed LMS hold counter')
        require(all(row[k]==v for k,v in schedule_coverage(replay['trace'],profile['taps']).items()),'Changed LMS directed output coverage')
        if load['name']=='mstall':require(row['singleton_weights_before_data']==1,'Missing singleton independent dump coverage')
        if load['name'] in ('wstall','mixed'):require(row['held_last_weights']>0,'Missing final-weight hold coverage')
        if load['name']=='mixed':require(row['simultaneous_output_holds']>0,'Missing simultaneous-output hold coverage')
    required={(kind,a) for kind in KINDS for a in (0,1)}
    require(len(data['negative'])==len(required) and {(r['kind'],r['active']) for r in data['negative']}==required and all(type(r['active']) is int and type(r['returncode']) is int and r['returncode']==13 for r in data['negative']),'Missing LMS negative matrix')
    require(len(data['lint'])==len(configurations()) and {(r['log2n'],r['depth'],r['active']) for r in data['lint']}==configurations() and all(all(type(r[k]) is int for k in ('log2n','depth','active','warnings')) and r['warnings']==0 for r in data['lint']),'Incomplete LMS FIFO lint matrix')


def verified_artifacts(data,root=ROOT):
    require_pass(data,root);check_acceptance(data);require(data['rtl_verified'],'Complete LMS FIFO RTL matrix required')
    def artifact(suffix):
        candidates=[root/name for name in data['artifact_hashes'] if name.endswith(suffix)];require(len(candidates)==1,'Missing/duplicate LMS artifact '+suffix);return candidates[0]
    for row in data['rows']:
        name=f"{row['profile']}_{row['load']}_d{row['depth']}_a{row['active']}"
        profile=next(p for p in profiles() if p['name']==row['profile']);load=next(l for l in loads() if l['name']==row['load'])
        actual=dict(measured(artifact('/'+name+'/pins.csv'),profile,load,row['depth'],artifact('/'+name+'/simulation.log').read_text()),active=row['active'])
        require(exact(actual,row),'LMS report differs from saved raw trace')
    for row in data['negative']:checked_negative(artifact(f"/negative_{row['kind']}_a{row['active']}/simulation.log").read_text(),row['returncode'],row['kind'])
    return [root/name for name in data['artifact_hashes']]


def verify_rtl(data,out,jobs):
    q,_=questa_paths();artifacts=[]
    sources=[ROOT/'rtl/common/mem/sync_ram.sv',ROOT/'rtl/common/mem/sync_rom.sv',ROOT/'rtl/common/axis_fifo.sv',ROOT/'rtl/common/lms_filter.sv',ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/axis_fifo_lms_load_tb.sv']
    def run(args,cwd,filename,kind=None):
        proc=subprocess.run(list(map(str,args)),cwd=cwd,capture_output=True,text=True,timeout=120)
        text=proc.stdout+proc.stderr;path=cwd/filename;path.write_text(text)
        if kind:checked_negative(text,proc.returncode,kind)
        else:require(proc.returncode==0 and not re.search(r'\*\* (?:Error|Fatal)|%Warning|%Error',text),f'LMS FIFO command failed rc={proc.returncode} {path}\n{text[-2500:]}')
        return text,path,proc.returncode
    _,p,_=run([q/'vlib','work'],out,'vlib.log');artifacts.append(p)
    _,p,_=run([q/'vlog','-64','-sv',*sources],out,'compile.log');artifacts.append(p)
    for log2n,depth,active in sorted(configurations()):
        _,p,_=run(['verilator','--lint-only','-Wall','--top-module','axis_fifo','-GWIDTH=72',f'-GDEPTH={depth}',f'-GRESET_ACTIVE={active}',*sources[:3]],out,f'lint_fifo_n{log2n}_d{depth}_a{active}.log');artifacts.append(p)
        _,p,_=run(['verilator','--lint-only','-Wall','--top-module','lms_filter',f'-GLOG2N={log2n}',f'-GRESET_ACTIVE={active}',*sources[:2],sources[3]],out,f'lint_lms_n{log2n}_d{depth}_a{active}.log');artifacts.append(p)
        data['lint'].append(dict(log2n=log2n,depth=depth,active=active,warnings=0))
        _,p,_=run([q/'vopt','-64','work.axis_fifo_lms_load_tb',f'-gLOG2N={log2n}',f'-gDEPTH={depth}',f'-gRESET_ACTIVE={active}',f'-gRECIP_FILE={ROOT}/rtl/common/mem/lms_reciprocal.mem','-o',f'load_n{log2n}_d{depth}_a{active}'],out,f'vopt_n{log2n}_d{depth}_a{active}.log');artifacts.append(p)
    for profile in profiles():
        for load in loads():artifacts.extend(write_fixture(out/'vectors'/profile['name']/load['name'],profile,load))
    def sim(profile,load,depth,active,kind=None):
        name=f'negative_{kind}_a{active}' if kind else f"{profile['name']}_{load['name']}_d{depth}_a{active}"
        work=out/name;work.mkdir();script=work/'simulation.do'
        script.write_text('onfinish stop\nonerror {quit -code 13}\n'+('onbreak {quit -code 13}\n' if kind else '')+'run -all\nquit -code 0\n')
        flags=[] if kind is None else ['+'+dict(NUMERIC='INJECT_DATA',WEIGHTS='INJECT_WEIGHTS',CAPACITY='REQUIRE_UNBLOCKED',M_HOLD='INJECT_HOLD_DATA',W_HOLD='INJECT_HOLD_WEIGHTS')[kind]]
        text,log,rc=run([q/'vsim','-64','-c','-quiet','-suppress','7032','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'-lib',out/'work',f"load_n{profile['log2n']}_d{depth}_a{active}",f'+VECTORS={out}/vectors/{profile["name"]}/{load["name"]}',f'+TRACE={work}/pins.csv',*flags,'-do',script.name],work,'simulation.log',kind)
        row=dict(kind=kind,active=active,returncode=rc) if kind else dict(measured(work/'pins.csv',profile,load,depth,text),active=active)
        return ('negative' if kind else 'rows'),row,[script,log,work/'pins.csv']
    tasks=[(p,l,model(p,l)['minimum_depth']+o,a,None) for p in profiles() for l in loads() for o in (0,-1) for a in (0,1)]
    special=next(p for p in profiles() if p['name']=='nlms_t16')
    for kind in KINDS:
        load=next(l for l in loads() if l['name']==('wstall' if kind=='W_HOLD' else 'mstall'))
        for active in (0,1):tasks.append((special,load,model(special,load)['minimum_depth']-(kind=='CAPACITY'),active,kind))
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for key,row,files in pool.map(lambda task:sim(*task),tasks):data[key].append(row);artifacts.extend(files)
    data['rtl_verified']=True;check_acceptance(data);return artifacts


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path);parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args();require_unoptimized();require(1<=args.jobs<=4,'jobs must be1..4')
    out=args.output.resolve() if args.output else ROOT/'build/rtl/lms_fifo_load_sweep';out.mkdir(parents=True,exist_ok=args.output is None)
    target=out/'results.json';evidence=begin();write_json(target,dict(evidence,status='RUNNING'))
    try:
        data=report();artifacts=verify_rtl(data,out,args.jobs) if args.verify_rtl else [];check_acceptance(data)
        write_json(target,dict(data,**finish(evidence,artifacts),status='PASS'))
    except Exception as exc:write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise
    print('PASS LMS FIFO loads:',target)


if __name__=='__main__':main()
