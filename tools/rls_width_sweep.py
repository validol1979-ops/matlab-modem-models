#!/usr/bin/env python3
"""RLS dot widths: arbitrary-code corners and operand-level shadow arithmetic on trajectories."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
sys.path.insert(0,str(ROOT/'common/python'))
import rls_widths as widths
import rls_fixed as fixed
from rls_cases import GROUPS,save,manual_transactions,read_saturation_expected,expected_file
from sat_diag import SatTrace,write_expected,save_json
from beam_energy_study import SCENARIOS
CASES=tuple((f'n{1<<n}',n,1<<n,None) for n in range(5))+(
    ('partial3_capacity4',2,3,None),('weight34',1,1,'weight34'),('p44',2,2,'p44'))
TAGS=('PREDICT','REGISTER','MATRIX','QUADRATIC','DENOMINATOR')


def layouts(n):
    p,d,q=53+n,63+n,67+n
    return [('selected',p,d,q),('old_pred',64,d,q),('old_dot',p,128,q),('old_q',p,d,128),('old_all',64,128,128)]


def invalid(n):
    p,d,q=53+n,63+n,67+n
    return [('pred_low',p-1,d,q),('pred_high',129,d,q),('dot_low',p,d-1,q),('dot_high',p,129,q),('q_low',p,d,q-1),('q_high',p,d,129)]


def fixture(spec,folder):
    name,n,taps,stress=spec;params=fixed.parameters(.5 if stress=='p44' else 1.,1/16384 if stress else .1)
    if stress:signals=manual_transactions(stress,taps)
    else:
        xs=([(-131072,-131072),(131071,-131072),(1,-1),(0,0)]*(taps+3))[:2*taps+8]
        signals=[(xs,[(a//2,b//2) for a,b in xs]),
                 ([(0,0),(1,-1),(-1,1),(131071,131071)],[(0,0),(131071,-131072),(-131072,131071),(1,-1)])]
    inputs=[];outputs=[];weights=[];stats=SatTrace()
    for xs,ds in signals:
        out,w=fixed.adapt(xs,ds,taps,params,stats=stats)
        inputs.extend((*v,*d,int(k==len(xs)-1)) for k,(v,d) in enumerate(zip(xs,ds)))
        outputs.extend((*p,*e,int(k==len(out)-1)) for k,(p,e) in enumerate(out))
        weights.extend((*v,int(k==len(w)-1)) for k,v in enumerate(w))
    folder.mkdir(parents=True,exist_ok=True);(folder/'cfg.txt').write_text(f'{taps} '+' '.join(map(str,params))+'\n')
    for name_,rows in (('in',inputs),('out',outputs),('w',weights)):save(folder/(name_+'.txt'),rows)
    for group,stages,_,_ in GROUPS:write_expected(folder/expected_file(group),stats,stages)
    save_json(folder/'saturation.json',stats)
    return dict(case=name,log2n=n,taps=taps,stress=stress,layout=widths.layout(n),inputs=len(inputs),outputs=len(outputs),weights=len(weights),
                transactions=len(signals),vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(spec,Path(tmp)/spec[0]) for spec in CASES]
    return dict(scope='RLS exact full-state dot bounds; arbitrary-code corners distinct from adaptive trajectories; synthesis paused',
                records=records,rtl_verified=False,rtl_equivalence=[],rtl_parameters=[],rtl_directed=[],rtl_negative=[])


def check_acceptance(result):
    if result['records']!=report()['records']:raise RuntimeError('Changed/incomplete RLS width fixtures')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_parameters','rtl_directed','rtl_negative')):raise RuntimeError('Unverified RLS raw records')
        return
    expected={(r['case'],l[0],a,s) for r in result['records'] for l in layouts(r['log2n']) for a in (1,0) for s in SCENARIOS}
    rows=result['rtl_equivalence']
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active'],r['scenario']) for r in rows}!=expected:raise RuntimeError('Incomplete/duplicated RLS raw coverage')
    for row in rows:
        source=next(r for r in result['records'] if r['case']==row['case']);layout=next(l for l in layouts(source['log2n']) if l[0]==row['layout']);count=source['inputs']
        if (row['widths']!=list(layout[1:]) or any(row[k]!=source[k] for k in ('outputs','weights','inputs'))
                or row['predictions']!=2*count or row['registers']!=2*count or row['matrices']!=2*source['taps']*count
                or row['quadratics']!=count or row['denominators']!=count or row['observers_verified'] is not True
                or type(row['cycles']) is not int or row['cycles']<=0):raise RuntimeError('Missing RLS raw observations')
        for key,bound in (('pred_peak','prediction'),('matrix_peak','matrix'),('q_peak','quadratic')):
            if type(row[key]) is not int or not 0<=row[key]<=source['layout']['bounds'][bound]['real_max']:raise RuntimeError('RLS raw peak outside proven range')
    for source in result['records']:
        matches=[r for r in rows if r['case']==source['case']]
        if len({(r['pred_peak'],r['matrix_peak'],r['q_peak']) for r in matches})!=1:raise RuntimeError('RLS raw values changed with widths/reset/stalls')
        for a in (1,0):
            for s in SCENARIOS:
                if len({r['cycles'] for r in matches if r['active']==a and r['scenario']==s})!=1:raise RuntimeError('RLS cycles changed with width')
    expected={(r['case'],l[0],a) for r in result['records'] for l in invalid(r['log2n']) for a in (1,0)}
    rows=result['rtl_parameters']
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active']) for r in rows}!=expected or any(type(r['returncode']) is not int or not r['returncode'] or r['tag']!='PARAMETER' for r in rows):raise RuntimeError('Incomplete RLS width guards')
    directed=result['rtl_directed'];expected={(n,l,a) for n in range(5) for l in ('selected','old_all') for a in (1,0)}
    if len(directed)!=20 or {(r['log2n'],r['layout'],r['active']) for r in directed}!=expected or any(r['predictions']!=32 or r['matrices']!=32*(1<<r['log2n']) or r['quadratics']!=16 for r in directed):raise RuntimeError('Incomplete arbitrary-code RLS corners')
    controls=result['rtl_negative'];expected={(a,t) for a in (1,0) for t in (*TAGS,'ARITHMETIC')}
    if len(controls)!=12 or {(r['active'],r['tag']) for r in controls}!=expected or any(type(r['returncode']) is not int or not r['returncode'] for r in controls):raise RuntimeError('Incomplete RLS raw fault controls')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    for spec,row in zip(CASES,result['records']):
        folder=base/'vectors'/spec[0]
        if fixture(spec,folder)!=row:raise RuntimeError('Changed RLS vectors')
        artifacts.extend(folder.glob('*'))
    def verify_active(active):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
            ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/rls_tb.sv',ROOT/'rtl/tb/rls_dot_bounds_tb.sv'],work,log);artifacts.append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        def run(top,n,layout,label,options=(),bad=False):
            _,p,d,q=layout;log=work/(label+'.log')
            args=[f'-gLOG2N={n}',f'-gRESET_ACTIVE={active}',f'-gPRED_WIDTH={p}',f'-gDOT_WIDTH={d}',f'-gQ_WIDTH={q}',*options]
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet',top,*args,'-do',negative.name if bad else positive.name])),cwd=work,capture_output=True,text=True,timeout=120)
            text=proc.stdout+proc.stderr;log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        for row in result['records']:
            n=row['log2n'];folder=base/'vectors'/row['case']
            for layout in layouts(n):
                if active==1:
                    _,p,d,q=layout;log=work/f'{row["case"]}_{layout[0]}_lint.log'
                    execute(['verilator','--lint-only','-Wall','--top-module','rls_filter',f'-GLOG2N={n}',f'-GPRED_WIDTH={p}',f'-GDOT_WIDTH={d}',f'-GQ_WIDTH={q}',f'-I{pilot}',*SOURCES],ROOT,log);artifacts.append(log)
                for scenario,options in SCENARIOS.items():
                    text,_=run('work.rls_tb',n,layout,f'{row["case"]}_{layout[0]}_{scenario}',[f'+VECTORS={folder}','+CHECK_DOT',*options])
                    numeric=re.search(r'PASS RLS: (\d+) outputs, (\d+) weights, (\d+) cycles',text)
                    raw=re.search(r'PASS RLS DOT: '+' '.join([r'(\d+)']*9),text)
                    if not numeric or not raw:raise RuntimeError('Missing RLS numeric/raw evidence')
                    for group,(_,evaluations,events) in read_saturation_expected(folder).items():
                        if f'PASS SATURATION {group}: {evaluations} evaluations, {events} events' not in text:raise RuntimeError('Missing RLS clamp evidence')
                    if not re.search(r'PASS BOUNDS rls: [1-9]\d* checks',text):raise RuntimeError('Missing RLS bounds evidence')
                    names=('inputs','predictions','registers','matrices','quadratics','denominators','pred_peak','matrix_peak','q_peak')
                    result['rtl_equivalence'].append(dict(case=row['case'],layout=layout[0],widths=list(layout[1:]),active=active,scenario=scenario,
                        outputs=int(numeric[1]),weights=int(numeric[2]),cycles=int(numeric[3]),observers_verified=True,**dict(zip(names,map(int,raw.groups())))))
            for layout in invalid(n):
                text,rc=run('work.rls_tb',n,layout,f'{row["case"]}_{layout[0]}_parameter',[f'+VECTORS={folder}'],True)
                if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS RLS:' in text:raise RuntimeError('Unsafe RLS width accepted')
                result['rtl_parameters'].append(dict(case=row['case'],layout=layout[0],active=active,tag='PARAMETER',returncode=rc))
            print('PASS RLS widths',row['case'],'reset',active,flush=True)
        for n in range(5):
            for layout in (layouts(n)[0],layouts(n)[-1]):
                text,_=run('work.rls_dot_bounds_tb',n,layout,f'directed_n{n}_{layout[0]}')
                match=re.search(r'PASS RLS DOT BOUNDS: (\d+) (\d+) (\d+)',text)
                if not match:raise RuntimeError('Missing arbitrary-code RLS corners')
                result['rtl_directed'].append(dict(log2n=n,layout=layout[0],active=active,predictions=int(match[1]),matrices=int(match[2]),quadratics=int(match[3])))
        row=result['records'][0]
        for tag in (*TAGS,'ARITHMETIC'):
            directed=tag=='ARITHMETIC';top='work.rls_dot_bounds_tb' if directed else 'work.rls_tb'
            options=['+INJECT_DIRECTED'] if directed else [f'+VECTORS={base/"vectors"/row["case"]}','+CHECK_DOT','+INJECT_DOT_'+tag]
            text,rc=run(top,0,layouts(0)[0],'negative_'+tag,options,True)
            if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or re.search(r'PASS RLS(?: DOT BOUNDS)?:',text):raise RuntimeError('RLS raw fault missed')
            result['rtl_negative'].append(dict(active=active,tag=tag,returncode=rc))
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(verify_active,(1,0)))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/rls_width_sweep/results.json');args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS RLS width sweep; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
