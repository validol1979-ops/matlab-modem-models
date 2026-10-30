#!/usr/bin/env python3
"""Exact-capacity synchronous FIFO and finite-burst integration with production Costas."""
from concurrent.futures import ThreadPoolExecutor
from itertools import product
from pathlib import Path
import argparse,csv,hashlib,json,re,subprocess,sys,tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths,require_pass
from mmse3_config_width_sweep import exact
sys.path.insert(0,str(ROOT/'common/python'))
import fifo_budget as budget
import sync_fixed

GEOMETRIES=((1,2),(37,2),(37,3),(37,5),(37,16),(37,17),(73,4),(73,256),(37,1024),(4096,2))
LENGTHS=(16,64,128,512)
LAYOUTS=('minimum','short','extra','small')
SCENARIOS=(0,1,2)
INVALID=((0,16),(4097,16),(37,1),(37,65537))
COLUMNS='cycle,s_valid,s_ready,s_last,f_valid,f_ready,f_last,m_valid,m_ready,m_last,level'.split(',')
SECTIONS=('unit','integration','negative','parameters','lint')

def require(ok,msg):
    if not ok:raise RuntimeError(msg)

def depth(b,layout):
    n=budget.finite_burst(b,8)['required_capacity']
    return dict(minimum=n,short=n-1,extra=n+1,small=2)[layout]

def vectors(folder,b):
    folder.mkdir(parents=True,exist_ok=True)
    lengths={16:(16,),64:(17,47),128:(1,7,120),512:(64,128,1,319)}[b]
    gains=sync_fixed.costas_gains(*((0,0) if b==16 else (.2,.01) if b==128 else (.08,.001)))
    state=0x392a71b3;inputs=[];outputs=[]
    for count in lengths:
        x=[]
        for _ in range(count):
            pair=[]
            for component in range(2):
                state=(1664525*state+1013904223)&0xffffffff;pair.append((state%262144)-131072)
            x.append(tuple(pair))
        y,phases=sync_fixed.costas(x,gains)
        inputs.extend((*p,int(i==count-1)) for i,p in enumerate(x))
        outputs.extend((*p,phase,int(i==count-1)) for i,(p,phase) in enumerate(zip(y,phases)))
    (folder/'input.txt').write_text(str(b)+'\n'+''.join(' '.join(map(str,r))+'\n' for r in inputs))
    (folder/'expected.txt').write_text(str(b)+'\n'+''.join(' '.join(map(str,r))+'\n' for r in outputs))
    (folder/'config.txt').write_text(' '.join(map(str,gains))+'\n')
    return dict(length=b,frames=list(lengths),gains=list(gains),lasts=[r[-1] for r in inputs],
                hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in folder.iterdir()})

def report():
    with tempfile.TemporaryDirectory() as tmp:records=[vectors(Path(tmp)/str(b),b) for b in LENGTHS]
    return dict(scope='Exact total-capacity single-clock RAM FIFO; finite input bursts into unchanged II8 Costas; no sustained1/cycle or physical timing claim',
        budget=budget.report(),vectors=records,rtl_verified=False,**{k:[] for k in SECTIONS})

def measure(path,b,d,scenario,lasts):
    streams={p:[] for p in ('s','f','m')};wait=peak=0;balance=0;previous=None
    with Path(path).open() as handle:
        reader=csv.DictReader(handle);require(reader.fieldnames==COLUMNS,'Incomplete FIFO trace pins')
        for raw in reader:
            require(set(raw)==set(COLUMNS) and all(type(v) is str for v in raw.values()),'Malformed trace row')
            # Payload is intentionally unreset; TLAST is only meaningful with VALID.
            for port in ('s','f','m'):
                if raw[port+'_valid']=='0' and raw[port+'_last'].lower() in ('x','z'):raw[port+'_last']='0'
            require(all(re.fullmatch(r'\d+',v) for v in raw.values()),'Unknown/invalid active trace value')
            row={k:int(v) for k,v in raw.items()};cycle=row['cycle']
            require(previous is None or cycle==previous+1,'Missing FIFO trace cycles');previous=cycle
            require(all(row[k] in (0,1) for k in COLUMNS[1:-1]),'Nonbinary FIFO pin')
            require(row['level']==balance and 0<=balance<=d,'Measured FIFO conservation')
            take=row['f_valid'] and row['f_ready'];push=row['s_valid'] and row['s_ready']
            require(row['s_ready']==int(balance<d or take),'Measured FIFO total capacity')
            if scenario!=1:require(row['m_ready']==1,'Output pressure policy')
            elif streams['s']:require(row['m_ready']==int((cycle-1)%8<5),'Output pressure policy')
            peak=max(peak,balance);balance+=int(push)-int(take)
            if row['s_valid'] and not row['s_ready']:wait+=1
            for p in streams:
                if row[p+'_valid'] and row[p+'_ready']:
                    require(len(streams[p])<b and row[p+'_last']==lasts[len(streams[p])],'Measured frame boundary/count')
                    if p=='f':require(len(streams['f'])<len(streams['s']),'FIFO noncausal transfer')
                    if p=='m':require(len(streams['m'])<len(streams['f']),'Core noncausal transfer')
                    streams[p].append(cycle)
    require(previous is not None and balance==0 and all(len(v)==b for v in streams.values()),'Incomplete FIFO trace')
    arrivals=streams['s'];service=streams['f'];intervals=[v-u for u,v in zip(service,service[1:])]
    require(service[0]-arrivals[0]==2 and min(intervals)>=8,'FIFO/Costas latency or II')
    span=arrivals[-1]-arrivals[0]+1
    if scenario!=1:
        need=budget.finite_burst(b,8)['required_capacity']
        require(set(intervals)=={8} and peak==min(d,need),'Measured service/burst bound')
        require((wait==0)==(d>=need) and (span==b)==(d>=need),'Measured minimal capacity')
    return dict(words=b,wait=wait,peak=peak,arrival_span=span,first_service=service[0]-arrivals[0],min_interval=min(intervals),max_interval=max(intervals))

def coverage(rows,keys,expected):
    require(len(rows)==len(expected) and {tuple(r[k] for k in keys) for r in rows}==expected,'Missing/duplicate '+str(keys))
    for r in rows:
        require(all(type(r[k]) is int for k in keys if k in ('width','depth','active','length','scenario')),'Invalid numeric identity')

def check_acceptance(d):
    expected=report()
    require(all(exact(d[k],expected[k]) for k in ('scope','budget','vectors')),'Changed FIFO model evidence')
    require(type(d['rtl_verified']) is bool,'Invalid verified flag')
    if not d['rtl_verified']:
        require(all(d[k]==[] for k in SECTIONS),'Unverified RTL rows');return
    coverage(d['unit'],('width','depth','active'),{(w,n,a) for (w,n),a in product(GEOMETRIES,(1,0))})
    for r in d['unit']:
        require(all(type(r[k]) is int and r[k]>=0 for k in ('pushed','popped','discarded','peak','swaps','full_swaps','resets','write_wraps','read_wraps','backlog_bubbles')),'Invalid unit counter')
        require(r['pushed']==r['popped']+r['discarded'] and r['discarded']>=2*r['depth'] and r['peak']==r['depth'] and
                r['full_swaps']>=4*r['depth'] and r['swaps']>=r['full_swaps'] and r['resets']>=2 and min(r['write_wraps'],r['read_wraps'])>=4 and r['backlog_bubbles']>=1,'Missing FIFO unit coverage')
    coverage(d['integration'],('length','layout','active','scenario'),{(b,l,a,s) for b,l,a,s in product(LENGTHS,LAYOUTS,(1,0),SCENARIOS)})
    for r in d['integration']:
        require(r['depth']==depth(r['length'],r['layout']) and type(r['depth']) is int,'Changed integration depth')
        require(all(type(r[k]) is int for k in ('words','wait','peak','arrival_span','first_service','min_interval','max_interval')),'Invalid measurement')
        require(r['words']==r['length'] and r['wait']>=0 and 0<r['peak']<=r['depth'] and r['arrival_span']==r['words']+r['wait'] and r['first_service']==2 and 8<=r['min_interval']<=r['max_interval'],'Bad integration measurements')
        if r['scenario']!=1:
            need=budget.finite_burst(r['length'],8)['required_capacity']
            require(r['min_interval']==r['max_interval']==8 and r['peak']==min(need,r['depth']) and ((r['wait']==0)==(r['depth']>=need)),'Unverified finite-burst budget')
    exp={('unit',w,n,a,t) for (w,n),a,t in product(((1,2),(73,256)),(1,0),('DATA','LAST','LEVEL'))}
    exp|={('costas',36,depth(64,'minimum' if t!='CAPACITY' else 'short'),a,t) for a,t in product((1,0),('NUMERIC','PHASE','CAPACITY'))}
    coverage(d['negative'],('bench','width','depth','active','tag'),exp)
    coverage(d['parameters'],('width','depth','active'),{(w,n,a) for (w,n),a in product(INVALID,(1,0))})
    require(all(type(r['returncode']) is int and r['returncode']==13 for k in ('negative','parameters') for r in d[k]),'Missing nonzero rejection')
    coverage(d['lint'],('width','depth'),set(GEOMETRIES))
    require(all(type(r['warnings']) is int and r['warnings']==0 for r in d['lint']),'FIFO lint warnings')

def parse_unit(text):
    names=('width','depth','pushed','popped','discarded','peak','swaps','full_swaps','resets','write_wraps','read_wraps','backlog_bubbles')
    pattern='PASS AXIS FIFO '+' '.join(k+r'=(\d+)' for k in names)
    matches=re.findall(pattern,text);require(len(matches)==1,'Missing FIFO unit summary')
    return dict(zip(names,map(int,matches[0])))


def verified_artifacts(d,root=ROOT):
    require_pass(d,root);check_acceptance(d);require(d['rtl_verified'],'Complete RTL FIFO matrix required')
    def artifact(suffix):
        matches=[root/name for name in d['artifact_hashes'] if name.endswith(suffix)]
        require(len(matches)==1,'Missing/duplicate FIFO artifact '+suffix);return matches[0]
    for r in d['unit']:
        p=artifact(f"/unit_{r['width']}_{r['depth']}_{r['active']}_/simulation.log")
        require(exact(dict(parse_unit(p.read_text()),active=r['active']),r),'Unit report differs from log')
    for r in d['integration']:
        p=artifact(f"/integration_{r['length']}_{r['layout']}_{r['active']}_{r['scenario']}/pins.csv")
        source=next(v for v in d['vectors'] if v['length']==r['length'])
        measured=measure(p,r['length'],r['depth'],r['scenario'],source['lasts'])
        require(exact(dict(measured,length=r['length'],layout=r['layout'],depth=r['depth'],active=r['active'],scenario=r['scenario']),r),'Report differs from FIFO trace')
    return [root/name for name in d['artifact_hashes']]


def verify_rtl(d,base,jobs):
    q,_=questa_paths();base.mkdir(parents=True,exist_ok=True);artifacts=[]
    def run(args,cwd,label,tag=None):
        cwd.mkdir(parents=True,exist_ok=True);p=subprocess.run(list(map(str,args)),cwd=cwd,capture_output=True,text=True,timeout=300)
        txt=p.stdout+p.stderr;log=cwd/(label+'.log');log.write_text(txt)
        if tag:require(p.returncode==13 and re.search(r'\*\* Fatal:.*\['+tag+r'\]',txt) and not re.search(r'PASS (?:AXIS FIFO|BUFFERED COSTAS)',txt),'Missed negative '+str(log)+'\n'+txt[-1800:])
        else:require(p.returncode==0 and not re.search(r'\*\* (?:Error|Fatal|Warning)|%Warning',txt),'Command failed '+str(log)+'\n'+txt[-2500:])
        return txt,p.returncode,[log]
    if not (base/'work').is_dir():_,_,logs=run([q/'vlib','work'],base,'vlib');artifacts+=logs
    pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';src=[ROOT/'rtl/common/mem/sync_ram.sv',ROOT/'rtl/common/mem/sync_rom.sv',ROOT/'rtl/common/axis_fifo.sv',pilot/'bpsk_rotate.sv',ROOT/'rtl/common/costas_loop.sv',ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/axis_fifo_tb.sv',ROOT/'rtl/tb/axis_fifo_costas_tb.sv']
    _,_,logs=run([q/'vlog','-64','-sv',f'+incdir+{pilot}',*src],base,'compile');artifacts+=logs
    def opt(top,name,w,n,a):
        args=[q/'vopt','-64','work.'+top,f'-gDEPTH={n}',f'-gRESET_ACTIVE={a}']
        if top=='axis_fifo_tb':args.append(f'-gWIDTH={w}')
        else:args.append(f'-gTABLE_DIR={pilot}/tables')
        _,_,logs=run([*args,'-o',name],base,'vopt_'+name);artifacts.extend(logs)
    for w,n in GEOMETRIES:
        _,_,logs=run(['verilator','--lint-only','-Wall','--top-module','axis_fifo',f'-GWIDTH={w}',f'-GDEPTH={n}',*src[:1],ROOT/'rtl/common/axis_fifo.sv'],base,f'lint_{w}_{n}');artifacts+=logs;d['lint'].append(dict(width=w,depth=n,warnings=0))
    for (w,n),a in product((*GEOMETRIES,*INVALID),(1,0)):opt('axis_fifo_tb',f'u_w{w}_d{n}_a{a}',w,n,a)
    for n,a in product(sorted({depth(b,l) for b,l in product(LENGTHS,LAYOUTS)}),(1,0)):opt('axis_fifo_costas_tb',f'c_d{n}_a{a}',36,n,a)
    for record in d['vectors']:
        folder=base/'vectors'/str(record['length']);require(exact(vectors(folder,record['length']),record),'Changed FIFO integration fixture');artifacts+=list(folder.iterdir())
    def sim(top,name,flags=(),tag=None):
        work=base/'runs'/name;work.mkdir(parents=True,exist_ok=True);script=work/'simulation.do'
        script.write_text('onfinish stop\nonerror {quit -code 13}\n'+('onbreak {quit -code 13}\n' if tag else '')+'run -all\nquit -code 0\n')
        text,rc,files=run([q/'vsim','-64','-c','-quiet','-lib',base/'work',top,*flags,'-do',script.name],work,'simulation',tag)
        return text,rc,files+[script],work
    tasks=[('unit',w,n,a,'') for (w,n),a in product(GEOMETRIES,(1,0))]
    tasks += [('parameters',w,n,a,'') for (w,n),a in product(INVALID,(1,0))]
    tasks += [('negative_unit',w,n,a,t) for (w,n),a,t in product(((1,2),(73,256)),(1,0),('DATA','LAST','LEVEL'))]
    tasks += [('integration',b,l,a,s) for b,l,a,s in product(LENGTHS,LAYOUTS,(1,0),SCENARIOS)]
    tasks += [('negative_costas',64,'short' if t=='CAPACITY' else 'minimum',a,t) for a,t in product((1,0),('NUMERIC','PHASE','CAPACITY'))]
    def job(task):
        mode,w,n,a,extra=task;name='_'.join(map(str,task));flags=[]
        if mode in ('unit','parameters','negative_unit'):
            tag='PARAMETER' if mode=='parameters' else 'NUMERIC' if extra in ('DATA','LAST') else extra or None
            if mode=='negative_unit':flags=['+INJECT_'+extra]
            txt,rc,files,_=sim(f'u_w{w}_d{n}_a{a}',name,flags,tag)
            if mode=='parameters':return 'parameters',dict(width=w,depth=n,active=a,returncode=rc),files
            if mode=='negative_unit':return 'negative',dict(bench='unit',width=w,depth=n,active=a,tag=extra,returncode=rc),files
            row=parse_unit(txt)
            require(row['width']==w and row['depth']==n,'Changed unit identity');return 'unit',dict(row,active=a),files
        b,l=w,n;capacity=depth(b,l);scenario=extra if mode=='integration' else 0
        work=base/'runs'/name;flags=[f'+VECTORS={base}/vectors/{b}',f'+TRACE={work}/pins.csv',f'+SCENARIO={scenario}']
        if mode=='negative_costas':flags.append('+REQUIRE_BURST' if extra=='CAPACITY' else '+INJECT_'+extra)
        txt,rc,files,work=sim(f'c_d{capacity}_a{a}',name,flags,extra if mode=='negative_costas' else None);files.append(work/'pins.csv')
        if mode=='negative_costas':return 'negative',dict(bench='costas',width=36,depth=capacity,active=a,tag=extra,returncode=rc),files
        record=next(r for r in d['vectors'] if r['length']==b);row=measure(work/'pins.csv',b,capacity,scenario,record['lasts'])
        match=re.findall(r'PASS BUFFERED COSTAS depth=(\d+) words=(\d+) wait=(\d+) peak=(\d+) arrival_span=(\d+) first_service=(\d+) min_interval=(\d+) max_interval=(\d+)',txt)
        require(len(match)==1,'Missing buffered Costas summary')
        summary=dict(zip(('depth','words','wait','peak','arrival_span','first_service','min_interval','max_interval'),map(int,match[0])))
        require(exact(summary,dict(row,depth=capacity)),'Costas summary differs from pin trace')
        return 'integration',dict(row,length=b,layout=l,depth=capacity,active=a,scenario=scenario),files
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for i,(section,row,files) in enumerate(pool.map(job,tasks),1):
            d[section].append(row);artifacts+=files
            if i%25==0:print('PASS FIFO jobs',i,'/',len(tasks),flush=True)
    d['rtl_verified']=True;return artifacts

def main():
    require_unoptimized();p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify-rtl',action='store_true');p.add_argument('--jobs',type=int,default=6);p.add_argument('--output',type=Path,default=ROOT/'build/rtl/axis_fifo_sweep/results.json');a=p.parse_args();require(1<=a.jobs<=8,'jobs1..8')
    e=begin();a.output=a.output.resolve();write_json(a.output,dict(e,status='RUNNING'));d={}
    try:
        d=report();check_acceptance(d);files=verify_rtl(d,a.output.parent/'rtl',a.jobs) if a.verify_rtl else []
        check_acceptance(d);write_json(a.output,dict(status='PASS',**finish(e,files),**d))
    except Exception as ex:write_json(a.output,dict(status='FAIL',error=str(ex),**e,**d));raise
    print('PASS FIFO sweep',flush=True)
if __name__=='__main__':main()
