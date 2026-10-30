#!/usr/bin/env python3
"""MMSE_N normalization and back substitution, independent pre-cast arithmetic."""
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
from mmse_n_cases import vectors as vectorsn
sys.path.insert(0,str(ROOT/'common/python'))
import mmse_norm_back_widths as math

BASELINE=ROOT/'build/acceptance_20261026_mmse_norm_back/baseline'
# Хеши замороженной базы встроены, чтобы отчёт модели строился без build/.
BASELINE_HASHES={
    'rtl/common/mmse_n.sv':'5a7fee7549608ecc5a17eebcaced5f0881aa1091ed4bbece4cb83cc782b1511c',
    'rtl/tb/mmse_n_tb.sv':'b3321c196845622e6bf96e61b1e55c9f5674150d92658436f11cbd77d7b3f3cd',
    'common/python/mmse_n_fixed.py':'4a4e54b83d78feddb51b43b75d9f1b8eb189a70d6efd2f4bdc57ac01bd43bcae',
    'common/python/mmse_scale_update_widths.py':'6471b1819d00b75d831574e94765d40ac7bf25f7a5a8903ded8d5edf0539e269',
    'rtl/tb/mmse_n_width_check.svh':'77fada4e10a1d8b4cca0a6113ae78a01c017ed293dfd2c3243cde23b63df2ca5',
    'rtl/tb/mmse_n_update_check.svh':'7fbc16149f19de6c23d172b7b9b2381ca0c9d3d59a25cf71fef6686c721abec2',
}
SPECS={'norm_back':dict(sizes=(2,3,4,5,6,7,8),cases=('identity','wide','random_complex'),
    params=('NORM_WIDTH','WEIGHT_WIDTH','MULT_NUM_WIDTH','BACK_PRODUCT_WIDTH','BACK_ACC_WIDTH'),
    layouts=(('selected',70,87,65,107,0),('legacy',138,138,112,112,112),
             ('old_norm',138,87,65,107,0),('old_weight',70,138,65,107,0),
             ('old_mult',70,87,112,107,0),('old_product',70,87,65,112,0),('old_acc',70,87,65,107,112)),
    direct='mmse_n_norm_back_tb',tb='mmse_n_tb',dut='mmse_n',banks=10,tags=('NORM','WEIGHT','MULT','PRODUCT','ACC'))}
def values(layout,n):return tuple(v if v else 106+(n-1).bit_length() for v in layout[1:])
SCENARIOS={'stream':[],'stalled':['+STALL_INPUT','+STALL_OUTPUT'],'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}
SECTIONS=('streams','frozen','directed','parameters','negative','lint')


def require(ok,msg):
    if not ok:raise RuntimeError(msg)


def fixture(kind,n,index,case,folder):
    d=vectorsn(folder,case,n,53+17*n+index)
    rows=lambda name:[tuple(map(int,s.split())) for s in (folder/name).read_text().splitlines() if s.strip()]
    cfg=rows('cfg.txt');h=cfg[:n*n];lam=cfg[n*n][0]
    trace=math.trace(h,lam,n)
    require(trace['weights']==rows('weights.txt'),'Independent configuration differs from fixed oracle')
    return dict(kind=kind,n=n,case=case,outputs=d['outputs'],banks=trace['banks'],
                hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()})


def invalid(kind,n=2):
    s=SPECS[kind];selected=list(values(s['layouts'][0],n));old=list(values(s['layouts'][1],n));out=[]
    for i,p in enumerate(s['params']):
        for label,v in (('low',selected[i]-1),('high',old[i]+1)):
            row=selected.copy();row[i]=v;out.append((p+'_'+label,*row))
    return out


def report():
    with tempfile.TemporaryDirectory() as tmp:
        records=[fixture(k,n,i,c,Path(tmp)/k/f'n{n}'/c) for k,s in SPECS.items() for n in s['sizes'] for i,c in enumerate(s['cases'])]
    return dict(scope='MMSE_N full independent stored-code norm70/weight87/mult65/product107/acc106+clog2(N); shared divider112 and clocks unchanged; synthesis paused',
                bounds={str(n):math.bounds(n) for n in range(2,9)},baseline_hashes=BASELINE_HASHES.copy(),records=records,rtl_verified=False,**{k:[] for k in SECTIONS})


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
        require(exact(r['banks'],banks) and exact(r['widths'],list(values(layout,r['n']))),'Changed raw observations')
        require(type(r['cycles']) is int and r['cycles']>0 and type(r['outputs']) is int and r['outputs']==src['outputs'] and
                type(r['config_cycles']) is int and r['config_cycles']>0,'Missing numeric/timing proof')
    for src in m['records']:
        for a,s in product((1,0),SCENARIOS):
            rows=[r for r in d['streams'] if (r['kind'],r['n'],r['case'],r['active'],r['scenario'])==(src['kind'],src['n'],src['case'],a,s)]
            require(len({(r['cycles'],r['config_cycles']) for r in rows})==1,'Widths changed cycles')
    coverage(d['frozen'],('kind','n','case','active','scenario'),{(r['kind'],r['n'],r['case'],a,s) for r in m['records'] for a,s in product((1,0),SCENARIOS)})
    for r in d['frozen']:
        src=next(v for v in m['records'] if (v['kind'],v['n'],v['case'])==(r['kind'],r['n'],r['case']))
        require(all(type(r[k]) is int for k in ('old_cycles','new_cycles','old_outputs','new_outputs','old_config_cycles','new_config_cycles')) and
                r['old_cycles']==r['new_cycles']>0 and r['old_outputs']==r['new_outputs']==src['outputs'] and
                r['old_config_cycles']==r['new_config_cycles']>0,'Frozen mismatch')
    coverage(d['directed'],('kind','n','layout','active'),{(k,n,l[0],a) for k,sp in SPECS.items() for n,l,a in product(sp['sizes'],sp['layouts'],(1,0))})
    for r in d['directed']:
        require(type(r['checks']) is int and r['checks']==3808+96*(r['n']-1),'Missing directed checks')
    for section,keys,exp in [('parameters',('kind','n','layout','active'),{(k,n,l[0],a) for k,sp in SPECS.items() for n in sp['sizes'] for l,a in product(invalid(k,n),(1,0))}),
        ('negative',('kind','bench','tag','active'),{(k,b,t,a) for k,sp in SPECS.items() for b,t,a in product(('stream','directed'),sp['tags'],(1,0))})]:
        coverage(d[section],keys,exp);require(all(type(r['returncode']) is int and r['returncode']==13 for r in d[section]),'Bad rejection process exit')
    coverage(d['lint'],('kind','n','layout'),{(k,n,l[0]) for k,sp in SPECS.items() for n,l in product(sp['sizes'],sp['layouts'])})
    require(all(type(r['warnings']) is int and r['warnings']==0 for r in d['lint']),'Lint warnings')


def parse(text,kind):
    found=re.findall(r'NORM BACK BANK bank=(\d+) count=(\d+) min=(-?\d+) max=(-?\d+)',text)
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
            if kind=='norm_back':args.append(f'-gN={n}')
            args += [f'-g{k}={v}' for k,v in zip(sp['params'],vals)]
            _,_,logs=run([*args,'-o',name],lib,'vopt_'+name,compiler=True);artifacts.extend(logs)
        for n,l in product(sp['sizes'],sp['layouts']):
            flags=[f'-G{k}={v}' for k,v in zip(sp['params'],values(l,n))]
            _,_,logs=run(['verilator','--lint-only','-Wall','--top-module',sp['dut'],*([f'-GN={n}'] if kind=='norm_back' else []),*flags,
                ROOT/'rtl/common/fxp_divide_seq.sv',*([ROOT/'rtl/common/norm_reciprocal.sv'] if kind=='scale' else []),ROOT/f'rtl/common/{sp["dut"]}.sv'],cur,f'lint_{n}_{l[0]}');artifacts.extend(logs)
            d['lint'].append(dict(kind=kind,n=n,layout=l[0],warnings=0))
            for a in (1,0):opt(cur,sp['tb'],f's_n{n}_{l[0]}_{a}',n,a,values(l,n))
        for n,l,a in product(sp['sizes'],sp['layouts'],(1,0)):opt(cur,sp['direct'],f'd_n{n}_{l[0]}_{a}',n,a,values(l,n))
        for n in sp['sizes']:
            for l,a in product(invalid(kind,n),(1,0)):opt(cur,sp['direct'],f'i_n{n}_{l[0]}_{a}',n,a,l[1:])
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
        pat=r'PASS MMSE'+('3' if kind=='scale' else '_N')+r': (\d+) outputs, (\d+) cycles'+(r', (\d+) config cycles' if kind=='norm_back' else '')
        m=re.findall(pat,txt);require(len(m)==1,'Missing numeric summary');v=tuple(map(int,m[0]));return v if kind=='norm_back' else (*v,0)
    tasks=[]
    for src in d['records']:
        kind,n,c=src['kind'],src['n'],src['case'];sp=SPECS[kind]
        for l,a,s in product(sp['layouts'],(1,0),SCENARIOS):tasks.append(('stream',kind,n,c,l,a,s))
        for a,s in product((1,0),SCENARIOS):tasks.append(('frozen',kind,n,c,None,a,s))
    for k,sp in SPECS.items():
        tasks += [('directed',k,n,'',l,a,'') for n,l,a in product(sp['sizes'],sp['layouts'],(1,0))]
        tasks += [('parameter',k,n,'',l,a,'') for n in sp['sizes'] for l,a in product(invalid(k,n),(1,0))]
        tasks += [('negative',k,sp['sizes'][0],b,t,a,'') for b,t,a in product(('stream','directed'),sp['tags'],(1,0))]
    def job(v):
        mode,k,n,c,l,a,s=v;sp=SPECS[k];name='_'.join(map(str,(mode,k,n,c,l[0] if isinstance(l,tuple) else l,a,s)))
        vec=base/'vectors'/k/f'n{n}'/c
        if mode=='stream':
            txt,_,logs=sim(k,'current',f's_n{n}_{l[0]}_{a}',name,[f'+VECTORS={vec}','+CHECK_NORM_BACK',*SCENARIOS[s]])
            out,cy,cfg=numeric(txt,k);check_observers(txt,vec,'mmse3' if k=='scale' else 'mmse_n')
            return 'streams',dict(kind=k,n=n,case=c,layout=l[0],active=a,scenario=s,widths=list(values(l,n)),outputs=out,cycles=cy,config_cycles=cfg,banks=parse(txt,k)),logs
        if mode=='frozen':
            matches=[];logs=[]
            for label in ('old','new'):
                txt,_,files=sim(k,label,f'f_n{n}_{a}',name+'_'+label,[f'+VECTORS={vec}',*SCENARIOS[s]]);matches.append(numeric(txt,k));logs+=files
            return 'frozen',dict(kind=k,n=n,case=c,active=a,scenario=s,old_outputs=matches[0][0],new_outputs=matches[1][0],old_cycles=matches[0][1],new_cycles=matches[1][1],old_config_cycles=matches[0][2],new_config_cycles=matches[1][2]),logs
        if mode=='directed':
            txt,_,logs=sim(k,'current',f'd_n{n}_{l[0]}_{a}',name,['+CHECK_NORM_BACK']);m=re.findall(r'PASS WIDTH DIRECTED '+k+r' n='+str(n)+r' checks=(\d+)',txt);require(len(m)==1,'Missing directed summary')
            return 'directed',dict(kind=k,n=n,layout=l[0],active=a,checks=int(m[0])),logs
        if mode=='parameter':
            _,rc,logs=sim(k,'current',f'i_n{n}_{l[0]}_{a}',name,tag='PARAMETER');return 'parameters',dict(kind=k,n=n,layout=l[0],active=a,returncode=rc),logs
        flags=['+CHECK_NORM_BACK','+INJECT_NORM_BACK='+l]
        if c=='stream':flags.append(f'+VECTORS={base/"vectors"/k/f"n{n}"/sp["cases"][0]}')
        _,rc,logs=sim(k,'current',f's_n{n}_selected_{a}' if c=='stream' else f'd_n{n}_selected_{a}',name,flags,l)
        return 'negative',dict(kind=k,bench=c,tag=l,active=a,returncode=rc),logs
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for i,(section,row,logs) in enumerate(pool.map(job,tasks),1):
            d[section].append(row);artifacts+=logs
            if i%100==0:print('PASS MMSE norm/back jobs',i,'/',len(tasks),flush=True)
    d['rtl_verified']=True;return artifacts


def main():
    require_unoptimized();p=argparse.ArgumentParser(description=__doc__);p.add_argument('--verify-rtl',action='store_true');p.add_argument('--jobs',type=int,default=8)
    p.add_argument('--output',type=Path,default=ROOT/'build/rtl/mmse_norm_back_sweep/results.json');a=p.parse_args();require(1<=a.jobs<=8,'jobs 1..8')
    a.output=a.output.resolve();e=begin();write_json(a.output,dict(e,status='RUNNING'));d={}
    try:
        d=report();check_acceptance(d);artifacts=verify_rtl(d,a.output.parent/'equivalence',a.jobs) if a.verify_rtl else []
        check_acceptance(d);write_json(a.output,dict(status='PASS',**finish(e,artifacts),**d))
    except Exception as ex:write_json(a.output,dict(status='FAIL',error=str(ex),**e,**d));raise
    print('PASS MMSE norm/back sweep',flush=True)
if __name__=='__main__':main()
