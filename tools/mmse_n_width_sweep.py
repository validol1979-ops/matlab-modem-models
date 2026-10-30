#!/usr/bin/env python3
"""Bounded MMSE_N Gram/output widths: exact proof and native RTL observations."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from itertools import product
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
from mmse_n_cases import vectors,SIZES
from run_mmse_n import SCENARIOS,PASS
from spectral_evidence import check_observers
sys.path.insert(0,str(ROOT/'common/python'))
import mmse_n_widths as widths

CASES=('identity','wide','min_imag','random_complex')
LAYOUTS=('selected','legacy')
TAGS=('GRAM','SUM','ROUND')
SOURCES=[ROOT/'rtl/common/fxp_divide_seq.sv',ROOT/'rtl/common/mmse_n.sv']
SECTIONS=('rtl_equivalence','rtl_directed','rtl_parameters','rtl_negative','rtl_lint')


def layout(n,label):
    return [widths.layout(n)['gram']['required_bits'],widths.layout(n)['sum']['required_bits']] if label=='selected' else [44,83+(n-1).bit_length()]


def invalid(n):
    g,y=layout(n,'selected');_,oldy=layout(n,'legacy')
    return (('gram_low',g-1,y),('gram_high',45,y),('sum_low',g,y-1),('sum_high',g,oldy+1))


def directed_counts(n):
    return dict(gram_checks=1088*n,sum_checks=544*n*n,round_checks=544*n+23)


def rows(path):
    return [tuple(map(int,line.split())) for line in path.read_text().splitlines() if line.strip()]


def bank(values):
    return dict(count=len(values),min=min(values),max=max(values))


def fixture(n,index,case,folder):
    data=vectors(folder,case,n,seed=53+17*n+index)
    cfg=rows(folder/'cfg.txt');h=cfg[:n*n];lam=cfg[n*n][0]
    w=rows(folder/'weights.txt');x=[v[:2] for v in rows(folder/'in.txt')]
    gram=widths.gram_partials(h,lam,n)
    partials=[];final=[]
    for k in range(0,len(x),n):
        p=widths.sum_partials(w,x[k:k+n],n);partials.extend(p);final.append(p[-1])
    clipped=[(widths.rounded(t[2*i],True),widths.rounded(t[2*i+1],True)) for t in final for i in range(n)]
    require(clipped==[v[:2] for v in rows(folder/'out.txt')],'Independent MMSE_N raw model differs')
    banks=[bank([v[c] for v in gram]) for c in range(2)]
    banks += [bank([v[c] for v in partials]) for c in range(2*n)]
    banks += [bank([widths.rounded(v[c]) for v in final]) for c in range(2*n)]
    return dict(n=n,case=case,outputs=data['outputs'],tuples=len(final),banks=banks,
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:
        records=[fixture(n,i,c,Path(tmp)/f'n{n}'/c) for n in SIZES for i,c in enumerate(CASES)]
    return dict(scope='MMSE_N Gram accumulator and streaming output sums only; stored G40, divider112, fixed model and FSM unchanged',
                bounds=[widths.layout(n) for n in range(2,9)],records=records,rtl_verified=False,
                **{section:[] for section in SECTIONS})


def require(ok,reason):
    if not ok:raise RuntimeError(reason)


def coverage(records,keys,expected):
    require(len(records)==len(expected) and {tuple(r[k] for k in keys) for r in records}==expected,
            'Missing or duplicate MMSE_N coverage '+','.join(keys))
    for r in records:
        require(all(type(r[k]) is int for k in keys if k in ('n','active')),'Invalid MMSE_N coverage type')


def check_acceptance(result):
    model=report()
    require(all(result[k]==model[k] for k in ('scope','bounds','records')),'Changed MMSE_N model evidence')
    require(type(result['rtl_verified']) is bool,'Invalid verified flag')
    if not result['rtl_verified']:
        require(not any(result[k] for k in SECTIONS),'Unverified MMSE_N evidence');return
    scenarios=[s for s,_ in SCENARIOS]
    coverage(result['rtl_equivalence'],('n','case','layout','active','scenario'),set(product(SIZES,CASES,LAYOUTS,(1,0),scenarios)))
    for r in result['rtl_equivalence']:
        source=next(v for v in model['records'] if (v['n'],v['case'])==(r['n'],r['case']))
        require(r['widths']==layout(r['n'],r['layout']) and all(type(v) is int for v in r['widths']),'Changed MMSE_N widths')
        require(type(r['outputs']) is int and r['outputs']==source['outputs'] and r['observers_verified'] is True,'Missing numeric MMSE_N evidence')
        require(all(type(r[k]) is int and r[k]>0 for k in ('cycles','config_cycles')),'Missing MMSE_N timing')
        require(r['banks']==source['banks'] and len(r['banks'])==2+4*r['n'],'Changed MMSE_N raw bank')
        require(all(type(b[k]) is int for b in r['banks'] for k in ('count','min','max')),'Invalid MMSE_N raw bank type')
    for n,c,a,s in product(SIZES,CASES,(1,0),scenarios):
        group=[r for r in result['rtl_equivalence'] if (r['n'],r['case'],r['active'],r['scenario'])==(n,c,a,s)]
        require(len({(r['cycles'],r['config_cycles']) for r in group})==1,'MMSE_N widths changed cycles')
    coverage(result['rtl_directed'],('n','layout','active'),set(product(SIZES,LAYOUTS,(1,0))))
    for r in result['rtl_directed']:
        require(r['passed'] is True and r['widths']==layout(r['n'],r['layout']) and all(type(v) is int for v in r['widths']), 'Missing MMSE_N directed pass')
        require(all(type(r[k]) is int and r[k]==v for k,v in directed_counts(r['n']).items()),'Changed MMSE_N directed counts')
    coverage(result['rtl_parameters'],('n','layout','active'),{(n,l,a) for n in SIZES for l,_,_ in invalid(n) for a in (1,0)})
    coverage(result['rtl_negative'],('n','bench','tag','active'),set(product(SIZES,('stream','directed'),TAGS,(1,0))))
    for key in ('rtl_parameters','rtl_negative'):
        require(all(type(r['returncode']) is int and r['returncode']==13 for r in result[key]),'Missing MMSE_N rejection')
    coverage(result['rtl_lint'],('n','layout'),set(product(range(2,9),LAYOUTS)))
    require(all(type(r['warnings']) is int and r['warnings']==0 for r in result['rtl_lint']),'MMSE_N lint warnings')


def parse_raw(text,n):
    found=re.findall(r'PASS MMSE_N WIDTHS N=(\d+) GRAM_ACC_WIDTH=(\d+) SUM_WIDTH=(\d+)',text)
    require(len(found)==1 and int(found[0][0])==n,'Missing MMSE_N raw summary')
    banks=re.findall(r'MMSE_N WIDTHS BANK bank=(\d+) count=(\d+) min=(-?\d+) max=(-?\d+)',text)
    require(len(banks)==2+4*n and [int(v[0]) for v in banks]==list(range(2+4*n)),'Missing MMSE_N raw banks')
    return dict(widths=list(map(int,found[0][1:])),banks=[dict(count=int(c),min=int(lo),max=int(hi)) for _,c,lo,hi in banks])


def verify_rtl(result,base,jobs=8):
    base.mkdir(parents=True,exist_ok=True);artifacts=[];bindir,_=questa_paths()
    def command(args,work,name,tag=None):
        log=work/(name+'.log')
        proc=subprocess.run(list(map(str,args)),cwd=work,capture_output=True,text=True,timeout=300)
        text=proc.stdout+proc.stderr;log.write_text(text)
        if tag:
            require(proc.returncode==13 and re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) and 'PASS MMSE_N:' not in text and 'PASS MMSE_N WIDTH DIRECTED' not in text,'MMSE_N negative missed '+str(log))
        else:
            warnings=re.findall(r'^.*\*\* Warning:.*$',text,re.MULTILINE)
            require(proc.returncode==0 and not re.search(r'\*\* (?:Error|Fatal)|%Warning',text) and all('(vopt-13314)' in v or '(vopt-2244)' in v or '(vlog-13314)' in v or '(vlog-2244)' in v for v in warnings),'MMSE_N command failed '+str(log)+'\n'+text[-4000:])
        return text,proc.returncode,log
    for n in range(2,9):
        for label in LAYOUTS:
            g,y=layout(n,label)
            _,_,log=command(['verilator','--lint-only','-Wall','--top-module','mmse_n',f'-GN={n}',f'-GGRAM_ACC_WIDTH={g}',f'-GSUM_WIDTH={y}',*SOURCES],base,f'lint_{n}_{label}')
            artifacts.append(log);result['rtl_lint'].append(dict(n=n,layout=label,warnings=0))
    for n in SIZES:
        work=base/f'n{n}';work.mkdir(exist_ok=True)
        if not (work/'work').is_dir():
            _,_,log=command([bindir/'vlib','work'],work,'vlib');artifacts.append(log)
        _,_,log=command([bindir/'vlog','-64','-sv',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,*[ROOT/'rtl/tb'/name for name in ('axis_check.sv','stream_cover.sv','sat_event_check.sv','mmse_n_tb.sv','mmse_n_width_tb.sv')]],work,'compile');artifacts.append(log)
        for filename,extra in (('run.do',''),('negative.do','onbreak {quit -code 13}\n')):
            p=work/filename;p.write_text('onfinish stop\nonerror {quit -code 13}\n'+extra+'run -all\nquit -code 0\n');artifacts.append(p)
        for label,a in product(LAYOUTS,(1,0)):
            g,y=layout(n,label)
            for bench in ('mmse_n_tb','mmse_n_width_tb'):
                _,_,log=command([bindir/'vopt','-64','work.'+bench,f'-gN={n}',f'-gRESET_ACTIVE={a}',f'-gGRAM_ACC_WIDTH={g}',f'-gSUM_WIDTH={y}','-o',f'{bench}_{label}_{a}'],work,f'vopt_{bench}_{label}_{a}');artifacts.append(log)
        for i,c in enumerate(CASES):
            folder=base/'vectors'/f'n{n}'/c
            require(fixture(n,i,c,folder)==next(v for v in result['records'] if (v['n'],v['case'])==(n,c)),'MMSE_N fixture changed')
            artifacts.extend(p for p in folder.iterdir() if p.is_file())
    def simulate(job):
        n,c,label,a,scenario,flags=job;work=base/f'n{n}';folder=base/'vectors'/f'n{n}'/c
        run=work/'runs'/f'{c}_{label}_{a}_{scenario}';run.mkdir(parents=True,exist_ok=True)
        text,_,log=command([bindir/'vsim','-64','-c','-quiet','-lib',work/'work',f'mmse_n_tb_{label}_{a}',f'+VECTORS={folder}','+CHECK_MMSE_N_WIDTHS',*flags,'-do',(work/'run.do').read_text()],run,'simulation')
        matches=re.findall(PASS,text);require(len(matches)==1,'Missing MMSE_N numeric summary')
        out,cycles,cfg=map(int,matches[0]);check_observers(text,folder,'mmse_n')
        require(re.search(r'PASS BOUNDS mmse_n: [1-9]\d* checks',text),'Missing MMSE_N bounds')
        return dict(n=n,case=c,layout=label,active=a,scenario=scenario,outputs=out,cycles=cycles,config_cycles=cfg,observers_verified=True,**parse_raw(text,n)),log
    streamjobs=[(n,c,l,a,s,f) for n,c,l,a,(s,f) in product(SIZES,CASES,LAYOUTS,(1,0),SCENARIOS)]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for record,log in pool.map(simulate,streamjobs):result['rtl_equivalence'].append(record);artifacts.append(log)
    for n in SIZES:
        work=base/f'n{n}'
        for label,a in product(LAYOUTS,(1,0)):
            text,_,log=command([bindir/'vsim','-64','-c','-quiet',f'work.mmse_n_width_tb_{label}_{a}','-do','run.do'],work,f'directed_{label}_{a}');artifacts.append(log)
            matches=re.findall(r'PASS MMSE_N WIDTH DIRECTED N=(\d+) GRAM_ACC_WIDTH=(\d+) SUM_WIDTH=(\d+) gram=(\d+) sum=(\d+) round=(\d+)',text)
            require(len(matches)==1,'Missing MMSE_N directed summary');rn,g,y,gc,sc,rc=map(int,matches[0]);require(rn==n,'Wrong directed size')
            result['rtl_directed'].append(dict(n=n,layout=label,active=a,passed=True,widths=[g,y],gram_checks=gc,sum_checks=sc,round_checks=rc))
        for a in (1,0):
            for label,g,y in invalid(n):
                _,rc,log=command([bindir/'vsim','-64','-c','-quiet','work.mmse_n_width_tb',f'-gN={n}',f'-gRESET_ACTIVE={a}',f'-gGRAM_ACC_WIDTH={g}',f'-gSUM_WIDTH={y}','-do','negative.do'],work,f'parameter_{label}_{a}','PARAMETER');artifacts.append(log)
                result['rtl_parameters'].append(dict(n=n,layout=label,active=a,returncode=rc))
            for bench,tag in product(('stream','directed'),TAGS):
                top='mmse_n_tb' if bench=='stream' else 'mmse_n_width_tb'
                flags=[f'+VECTORS={base/"vectors"/f"n{n}"/CASES[0]}','+CHECK_MMSE_N_WIDTHS'] if bench=='stream' else []
                _,rc,log=command([bindir/'vsim','-64','-c','-quiet',f'work.{top}_selected_{a}',*flags,'+INJECT_MMSE_N='+tag,'-do','negative.do'],work,f'negative_{bench}_{tag}_{a}',tag);artifacts.append(log)
                result['rtl_negative'].append(dict(n=n,bench=bench,tag=tag,active=a,returncode=rc))
        print(f'PASS MMSE_N widths N={n}',flush=True)
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--jobs',type=int,default=8)
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/mmse_n_width_sweep/results.json')
    args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result)
        artifacts=verify_rtl(result,args.output.parent/'equivalence',args.jobs) if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),**result));raise
    print('PASS MMSE_N width study',flush=True)


if __name__=='__main__':main()
