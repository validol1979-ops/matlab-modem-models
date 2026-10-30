#!/usr/bin/env python3
"""MMSE3 weight scaling and MMSE_N elimination arithmetic, exact before-clamp checks."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from itertools import product
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
from mmse3_config_width_sweep import exact
from spectral_evidence import check_observers
from mmse3_cases import vectors as vectors3,CASES as CASES3
from mmse_n_cases import vectors as vectorsn
sys.path.insert(0,str(ROOT/'common/python'))
import mmse_scale_update_widths as math

BASELINE=ROOT/'build/acceptance_20261026_mmse_scale_updates/baseline'
# Хеши замороженной базы встроены, чтобы отчёт модели строился без build/.
BASELINE_HASHES={
    'rtl/common/mmse3.sv':'296c3d30083a3797d645c5a0da1823ad57abf0dccc9ffcd811cd9adb0d3e7b83',
    'rtl/common/mmse_n.sv':'6e9fa44af96b8b951c6cb64338a0928767d2303a535dafae180e91b39d63f903',
    'rtl/tb/mmse3_tb.sv':'26f7e1a6d2d055c89f14c9566b7e87119cd62a7e4477364d85dff9ad746dad7d',
    'rtl/tb/mmse_n_tb.sv':'0e3e9b4fa866459624523eb9e6ae499e885415ad5f99896e5d0f55a4a0d67eee',
    'rtl/common/fxp_divide_seq.sv':'72f93fdbc742dd30397e7ae3f47e29bc1b7cfebb4ad5d5bcb8711713ee48766a',
    'rtl/common/norm_reciprocal.sv':'d95cb7c01c631a6496373b6948aea1b2d5ac39cf879d691018a50a5980a561b6',
    'common/python/mmse3_fixed.py':'64aa6d718af69caf276b0697bdf9fa4b09220909fd2129d629ee70a746a53323',
    'common/python/mmse_n_fixed.py':'4a4e54b83d78feddb51b43b75d9f1b8eb189a70d6efd2f4bdc57ac01bd43bcae',
    'tools/mmse3_cases.py':'57d3b3f1ec70b1b55008922f2d0caea025810c307d5d627ca54fe77995e5efd6',
    'tools/mmse_n_cases.py':'bb6c1f01b14913f6bde7fc941c3717ae5be367ab2c3a569ce50241a437c9f18b',
    'rtl/tb/mmse3_config_check.svh':'6278b555f23b99f8a672f73f8a7de140915bde51d140decc8d5179210cf82b0d',
    'rtl/tb/mmse3_width_check.svh':'038cf9b270ea0d38ed832815906c41cf711f9acfd6f4967be03056ac61aca691',
    'rtl/tb/mmse3_bounds_check.svh':'02ff33a103a14b1d76957b8efd4497a2fdf95e9c4bce18b1c7b68f99edbfce0b',
    'rtl/tb/mmse_n_width_check.svh':'77fada4e10a1d8b4cca0a6113ae78a01c017ed293dfd2c3243cde23b63df2ca5',
}
SPECS={'scale':dict(sizes=(3,),cases=(*CASES3,'gram_peak'),params=('SCALE_WIDTH',),layouts=(('selected',145),('legacy',156)),
                    direct='mmse3_scale_tb',tb='mmse3_tb',dut='mmse3',banks=4,tags=('PRODUCT','SCALE','OVERFLOW')),
       'updates':dict(sizes=(2,3,4,5,8),cases=('identity','wide','random_complex'),
           params=('A_PRODUCT_WIDTH','B_PRODUCT_WIDTH','A_UPDATE_WIDTH','B_UPDATE_WIDTH'),
           layouts=(('selected',83,121,53,91),('legacy',84,122,138,138),('old_ap',84,121,53,91),
                    ('old_bp',83,122,53,91),('old_au',83,121,138,91),('old_bu',83,121,53,138)),
           direct='mmse_n_update_tb',tb='mmse_n_tb',dut='mmse_n',banks=8,tags=('A_PRODUCT','A_UPDATE','B_PRODUCT','B_UPDATE'))}
SCENARIOS={'stream':[],'stalled':['+STALL_INPUT','+STALL_OUTPUT'],'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}
SECTIONS=('streams','frozen','directed','parameters','negative','lint')


def require(ok,msg):
    if not ok:raise RuntimeError(msg)


def fixture(kind,n,index,case,folder):
    spec=SPECS[kind]
    d=vectors3(folder,case,53+index) if kind=='scale' else vectorsn(folder,case,n,53+17*n+index)
    rows=lambda name:[tuple(map(int,s.split())) for s in (folder/name).read_text().splitlines() if s.strip()]
    cfg=rows('cfg.txt');h=cfg[:n*n];lam=cfg[n*n][0]
    trace=math.scale_trace(h,lam) if kind=='scale' else math.update_trace(h,lam,n)
    require(trace['weights']==rows('weights.txt'),'Independent configuration differs from fixed oracle')
    return dict(kind=kind,n=n,case=case,outputs=d['outputs'],banks=trace['banks'],
                hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()})


def invalid(kind):
    s=SPECS[kind];selected=list(s['layouts'][0][1:]);old=list(s['layouts'][1][1:]);out=[]
    for i,p in enumerate(s['params']):
        for label,v in (('low',selected[i]-1),('high',old[i]+1)):
            row=selected.copy();row[i]=v;out.append((p+'_'+label,*row))
    return out


def direct_banks(kind):
    b=math.layout()
    if kind=='scale':return [dict(count=2545,min=b['scale'][k]['min'],max=b['scale'][k]['max']) for k in ('product','product','scaled','scaled')]
    return [dict(count=67,min=x['min'],max=x['max']) for k in ('a','b') for x in b[k]['axes']]


def report():
    with tempfile.TemporaryDirectory() as tmp:
        records=[fixture(k,n,i,c,Path(tmp)/k/f'n{n}'/c) for k,s in SPECS.items() for n in s['sizes'] for i,c in enumerate(s['cases'])]
    return dict(scope='Independent full stored-code MMSE scale145 and update83/121/53/91 widths; fixed models/stored registers/dividers/FSM unchanged; synthesis paused',
                bounds=math.layout(),baseline_hashes=BASELINE_HASHES.copy(),records=records,rtl_verified=False,**{k:[] for k in SECTIONS})


def coverage(rows,keys,expected):
    require(len(rows)==len(expected) and {tuple(r[k] for k in keys) for r in rows}==expected,'Missing/duplicate '+str(keys))
    for r in rows:
        require(all(type(r[k]) is int for k in keys if k in ('n','active')),'Invalid numeric identifier')


def check_acceptance(d):
    m=report();require(all(exact(d[k],m[k]) for k in ('scope','bounds','baseline_hashes','records')),'Changed model evidence')
    require(type(d['rtl_verified']) is bool,'Invalid verified flag')
    if not d['rtl_verified']:
        require(all(d[k]==[] for k in SECTIONS),'Unverified observations');return
    expected={(k,n,c,l[0],a,s) for k,sp in SPECS.items() for n,c,l,a,s in product(sp['sizes'],sp['cases'],sp['layouts'],(1,0),SCENARIOS)}
    coverage(d['streams'],('kind','n','case','layout','active','scenario'),expected)
    for r in d['streams']:
        src=next(v for v in m['records'] if (v['kind'],v['n'],v['case'])==(r['kind'],r['n'],r['case']))
        layout=next(l for l in SPECS[r['kind']]['layouts'] if l[0]==r['layout'])
        factor=2 if r['scenario'] in ('midreset','outreset') else 1
        banks=[dict(b,count=b['count']*factor) for b in src['banks']]
        require(exact(r['banks'],banks) and exact(r['widths'],list(layout[1:])),'Changed raw observations')
        require(type(r['cycles']) is int and r['cycles']>0 and type(r['outputs']) is int and r['outputs']==src['outputs'] and
                type(r['config_cycles']) is int and r['config_cycles']>=(1 if r['kind']=='updates' else 0),'Missing numeric/timing proof')
    for src in m['records']:
        for a,s in product((1,0),SCENARIOS):
            rows=[r for r in d['streams'] if (r['kind'],r['n'],r['case'],r['active'],r['scenario'])==(src['kind'],src['n'],src['case'],a,s)]
            require(len({(r['cycles'],r['config_cycles']) for r in rows})==1,'Widths changed cycles')
    coverage(d['frozen'],('kind','n','case','active','scenario'),{(r['kind'],r['n'],r['case'],a,s) for r in m['records'] for a,s in product((1,0),SCENARIOS)})
    for r in d['frozen']:
        src=next(v for v in m['records'] if (v['kind'],v['n'],v['case'])==(r['kind'],r['n'],r['case']))
        require(all(type(r[k]) is int for k in ('old_cycles','new_cycles','old_outputs','new_outputs','old_config_cycles','new_config_cycles')) and
                r['old_cycles']==r['new_cycles']>0 and r['old_outputs']==r['new_outputs']==src['outputs'] and
                r['old_config_cycles']==r['new_config_cycles']>=(1 if r['kind']=='updates' else 0),'Frozen mismatch')
    coverage(d['directed'],('kind','layout','active'),{(k,l[0],a) for k,sp in SPECS.items() for l,a in product(sp['layouts'],(1,0))})
    for r in d['directed']:
        require(exact(r['banks'],direct_banks(r['kind'])),'Missing directed extrema/counts')
        require(type(r['checks']) is int and r['checks']==(5090 if r['kind']=='scale' else 536),'Missing directed checks')
    for section,keys,exp in [('parameters',('kind','layout','active'),{(k,l[0],a) for k in SPECS for l,a in product(invalid(k),(1,0))}),
        ('negative',('kind','bench','tag','active'),{(k,b,t,a) for k,sp in SPECS.items() for b,t,a in product(('stream','directed'),sp['tags'],(1,0))})]:
        coverage(d[section],keys,exp);require(all(type(r['returncode']) is int and r['returncode']==13 for r in d[section]),'Bad rejection process exit')
    coverage(d['lint'],('kind','n','layout'),{(k,n,l[0]) for k,sp in SPECS.items() for n,l in product(sp['sizes'],sp['layouts'])})
    require(all(type(r['warnings']) is int and r['warnings']==0 for r in d['lint']),'Lint warnings')


def parse(text,kind):
    found=re.findall(r'WIDTH BANK bank=(\d+) count=(\d+) min=(-?\d+) max=(-?\d+)',text)
    require([int(v[0]) for v in found]==list(range(SPECS[kind]['banks'])),'Missing/duplicate raw banks')
    require(text.count('PASS WIDTH OBSERVER '+kind)==1,'Missing width observer')
    return [dict(count=int(c),min=int(lo),max=int(hi)) for _,c,lo,hi in found]


def verify_rtl(d,base,jobs):
    q,_=questa_paths();base.mkdir(parents=True,exist_ok=True);artifacts=[];libraries={}
    for rel,h in d['baseline_hashes'].items():
        p=BASELINE/rel;require(hashlib.sha256(p.read_bytes()).hexdigest()==h,'Changed frozen baseline');artifacts.append(p)
    def run(args,cwd,label,tag=None,compiler=False):
        cwd.mkdir(parents=True,exist_ok=True);log=cwd/(label+'.log');p=subprocess.run(list(map(str,args)),cwd=cwd,capture_output=True,text=True,timeout=300)
        txt=p.stdout+p.stderr;log.write_text(txt)
        if tag:require(p.returncode==13 and re.search(r'\*\* Fatal:.*\['+tag+r'\]',txt) and 'PASS WIDTH DIRECTED' not in txt,'Negative missed: '+str(log)+'\n'+txt[-1600:])
        else:
            allowed=('vlog-13314','vopt-13314','vlog-2244','vopt-2244') if compiler else ()
            require(p.returncode==0 and not re.search(r'\*\* (?:Error|Fatal)|%Warning',txt) and
                    all(any(c in w for c in allowed) for w in re.findall(r'^.*\*\* Warning:.*$',txt,re.M)),'Command failed: '+str(log)+'\n'+txt[-2500:])
        return txt,p.returncode,[log]
    for kind,sp in SPECS.items():
        for label in ('current','old','new'):
            lib=base/kind/label;lib.mkdir(parents=True,exist_ok=True)
            if not (lib/'work').is_dir():_,_,logs=run([q/'vlib','work'],lib,'vlib');artifacts.extend(logs)
            dut=(BASELINE if label=='old' else ROOT)/f'rtl/common/{sp["dut"]}.sv'
            tb=(ROOT if label=='current' else BASELINE)/f'rtl/tb/{sp["tb"]}.sv'
            inc=(ROOT if label=='current' else BASELINE)/'rtl/tb'
            src=[ROOT/'rtl/common/fxp_divide_seq.sv']+([ROOT/'rtl/common/norm_reciprocal.sv'] if kind=='scale' else [])
            tbfiles=[ROOT/'rtl/tb'/f for f in ('axis_check.sv','stream_cover.sv','sat_event_check.sv')]
            _,_,logs=run([q/'vlog','-64','-sv',f'+incdir+{inc}',*src,dut,*tbfiles,tb,*([ROOT/f'rtl/tb/{sp["direct"]}.sv'] if label=='current' else [])],lib,'compile',compiler=True);artifacts.extend(logs)
            libraries[kind,label]=lib
        cur=libraries[kind,'current']
        def opt(lib,top,name,n,a,vals=()):
            args=[q/'vopt','-64','work.'+top,f'-gRESET_ACTIVE={a}']
            if kind=='updates' and top==sp['tb']:args.append(f'-gN={n}')
            args += [f'-g{k}={v}' for k,v in zip(sp['params'],vals)]
            _,_,logs=run([*args,'-o',name],lib,'vopt_'+name,compiler=True);artifacts.extend(logs)
        for n,l in product(sp['sizes'],sp['layouts']):
            flags=[f'-G{k}={v}' for k,v in zip(sp['params'],l[1:])]
            _,_,logs=run(['verilator','--lint-only','-Wall','--top-module',sp['dut'],*([f'-GN={n}'] if kind=='updates' else []),*flags,
                ROOT/'rtl/common/fxp_divide_seq.sv',*([ROOT/'rtl/common/norm_reciprocal.sv'] if kind=='scale' else []),ROOT/f'rtl/common/{sp["dut"]}.sv'],cur,f'lint_{n}_{l[0]}');artifacts.extend(logs)
            d['lint'].append(dict(kind=kind,n=n,layout=l[0],warnings=0))
            for a in (1,0):opt(cur,sp['tb'],f's_n{n}_{l[0]}_{a}',n,a,l[1:])
        for l,a in product(sp['layouts'],(1,0)):opt(cur,sp['direct'],f'd_{l[0]}_{a}',2,a,l[1:])
        for l,a in product(invalid(kind),(1,0)):opt(cur,sp['direct'],f'i_{l[0]}_{a}',2,a,l[1:])
        for label,n,a in product(('old','new'),sp['sizes'],(1,0)):opt(libraries[kind,label],sp['tb'],f'f_n{n}_{a}',n,a)
    for src in d['records']:
        folder=base/'vectors'/src['kind']/f'n{src["n"]}'/src['case']
        require(exact(fixture(src['kind'],src['n'],SPECS[src['kind']]['cases'].index(src['case']),src['case'],folder),src),'Fixture changed')
        artifacts.extend(p for p in folder.iterdir() if p.is_file())
    def sim(kind,label,top,name,flags=(),tag=None):
        cwd=base/'runs'/name;cwd.mkdir(parents=True,exist_ok=True);script=cwd/'simulation.do'
        script.write_text('onfinish stop\nonerror {quit -code 13}\n'+('onbreak {quit -code 13}\n' if tag else '')+'run -all\nquit -code 0\n')
        text,rc,logs=run([q/'vsim','-64','-c','-quiet','-lib',libraries[kind,label]/'work',top,*flags,'-do',script.name],cwd,'simulation',tag)
        return text,rc,logs+[script]
    def numeric(txt,kind):
        pat=r'PASS MMSE'+('3' if kind=='scale' else '_N')+r': (\d+) outputs, (\d+) cycles'+(r', (\d+) config cycles' if kind=='updates' else '')
        m=re.findall(pat,txt);require(len(m)==1,'Missing numeric summary');v=tuple(map(int,m[0]));return v if kind=='updates' else (*v,0)
    tasks=[]
    for src in d['records']:
        kind,n,c=src['kind'],src['n'],src['case'];sp=SPECS[kind]
        for l,a,s in product(sp['layouts'],(1,0),SCENARIOS):tasks.append(('stream',kind,n,c,l,a,s))
        for a,s in product((1,0),SCENARIOS):tasks.append(('frozen',kind,n,c,None,a,s))
    for k,sp in SPECS.items():
        tasks += [('directed',k,2,'',l,a,'') for l,a in product(sp['layouts'],(1,0))]
        tasks += [('parameter',k,2,'',l,a,'') for l,a in product(invalid(k),(1,0))]
        tasks += [('negative',k,sp['sizes'][0],b,t,a,'') for b,t,a in product(('stream','directed'),sp['tags'],(1,0))]
    def job(v):
        mode,k,n,c,l,a,s=v;sp=SPECS[k];name='_'.join(map(str,(mode,k,n,c,l[0] if isinstance(l,tuple) else l,a,s)))
        vec=base/'vectors'/k/f'n{n}'/c
        if mode=='stream':
            txt,_,logs=sim(k,'current',f's_n{n}_{l[0]}_{a}',name,[f'+VECTORS={vec}','+CHECK_SCALE_UPDATES',*SCENARIOS[s]])
            out,cy,cfg=numeric(txt,k);check_observers(txt,vec,'mmse3' if k=='scale' else 'mmse_n')
            return 'streams',dict(kind=k,n=n,case=c,layout=l[0],active=a,scenario=s,widths=list(l[1:]),outputs=out,cycles=cy,config_cycles=cfg,banks=parse(txt,k)),logs
        if mode=='frozen':
            matches=[];logs=[]
            for label in ('old','new'):
                txt,_,files=sim(k,label,f'f_n{n}_{a}',name+'_'+label,[f'+VECTORS={vec}',*SCENARIOS[s]]);matches.append(numeric(txt,k));logs+=files
            return 'frozen',dict(kind=k,n=n,case=c,active=a,scenario=s,old_outputs=matches[0][0],new_outputs=matches[1][0],old_cycles=matches[0][1],new_cycles=matches[1][1],old_config_cycles=matches[0][2],new_config_cycles=matches[1][2]),logs
        if mode=='directed':
            txt,_,logs=sim(k,'current',f'd_{l[0]}_{a}',name,['+CHECK_SCALE_UPDATES']);m=re.findall(r'PASS WIDTH DIRECTED '+k+r' checks=(\d+)',txt);require(len(m)==1,'Missing directed summary')
            return 'directed',dict(kind=k,layout=l[0],active=a,checks=int(m[0]),banks=parse(txt,k)),logs
        if mode=='parameter':
            _,rc,logs=sim(k,'current',f'i_{l[0]}_{a}',name,tag='PARAMETER');return 'parameters',dict(kind=k,layout=l[0],active=a,returncode=rc),logs
        flags=['+CHECK_SCALE_UPDATES','+INJECT_SCALE_UPDATE='+l]
        if c=='stream':flags.append(f'+VECTORS={base/"vectors"/k/f"n{n}"/sp["cases"][0]}')
        _,rc,logs=sim(k,'current',f's_n{n}_selected_{a}' if c=='stream' else f'd_selected_{a}',name,flags,l)
        return 'negative',dict(kind=k,bench=c,tag=l,active=a,returncode=rc),logs
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for i,(section,row,logs) in enumerate(pool.map(job,tasks),1):
            d[section].append(row);artifacts+=logs
            if i%100==0:print('PASS MMSE scale/update jobs',i,'/',len(tasks),flush=True)
    d['rtl_verified']=True;return artifacts


def main():
    require_unoptimized();p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify-rtl',action='store_true');p.add_argument('--jobs',type=int,default=8)
    p.add_argument('--output',type=Path,default=ROOT/'build/rtl/mmse_scale_update_sweep/results.json');a=p.parse_args();require(1<=a.jobs<=8,'jobs 1..8')
    a.output=a.output.resolve();e=begin();write_json(a.output,dict(e,status='RUNNING'));d={}
    try:
        d=report();check_acceptance(d);artifacts=verify_rtl(d,a.output.parent/'equivalence',a.jobs) if a.verify_rtl else []
        check_acceptance(d);write_json(a.output,dict(status='PASS',**finish(e,artifacts),**d))
    except Exception as ex:write_json(a.output,dict(status='FAIL',error=str(ex),**e,**d));raise
    print('PASS MMSE scale/update sweep',flush=True)
if __name__=='__main__':main()
