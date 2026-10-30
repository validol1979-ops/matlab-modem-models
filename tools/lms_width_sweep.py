#!/usr/bin/env python3
"""Exact LMS/NLMS estimate, error, step, tap-update, weight and dump intermediate widths."""
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
import lms_widths as widths
import lms_fixed as fixed
from lms_cases import GROUPS,vectors,save,read_saturation_expected
from lms_energy_study import SCENARIOS
from sat_diag import SatTrace,write_expected,save_json
PARAMETERS=('PRED_WIDTH','ERROR_WIDTH','STEP_WIDTH','COEFF_WIDTH','DELTA_WIDTH','WEIGHT_WIDTH','DUMP_WIDTH')
OLD=tuple(widths.OLD[name.lower()] for name in PARAMETERS)
# (case, LOG2N, generator, arguments); lms_cases arguments are (mode, step, eps, taps, seed, stress).
CASES=(('lms_n1',0,'cases',('lms',.02,.01,1,101,False)),
       ('lms_n16',4,'cases',('lms',.2,.01,16,102,False)),
       ('nlms_n16',4,'cases',('nlms',1,.001,16,103,False)),
       ('nlms_n4_t3',2,'cases',('nlms',.6,.01,3,104,False)),
       ('lms_weight34',1,'cases',('lms',1,.01,2,105,True)),
       ('nlms_coeff_n16',4,'coeff',()))
TAGS=('PRODUCT','PREDICT','ERROR','STEP','COEFF','DELTA','WEIGHT','DUMP')
COUNTS=('products','sums','preds','errors','steps','coeff_regs','taps','weight_sums','delta_regs','weight_regs','dumps')
PEAKS=tuple(stage+'_peak' for stage in widths.STAGES)
NEGATIVE_CASE='nlms_n4_t3'


def selected(log2n):return tuple(widths.layout(log2n)['selected'][name.lower()] for name in PARAMETERS)


def layouts(log2n):
    chosen=selected(log2n)
    return ([('selected',chosen)]+[('old_'+name.lower(),tuple(OLD[j] if j==i else v for j,v in enumerate(chosen))) for i,name in enumerate(PARAMETERS)]
            +[('old_all',OLD)])


def invalid(log2n):
    chosen=selected(log2n)
    return [(name.lower()+suffix,tuple(value if j==i else v for j,v in enumerate(chosen)))
            for i,name in enumerate(PARAMETERS) for suffix,value in (('_low',chosen[i]-1),('_high',129))]


def coefficient_fixture(folder):
    """NLMS16 with MU=2^17, EPS=512: an empty history gives P=512, s=10 and |c|=2^43 (the
    proven coefficient bound), followed by small and full-rail histories."""
    taps=16;mu=1<<17;eps=512;stats=SatTrace()
    xs=[(0,0),(0,0),(1,0),(22,-23),(-16,16)]+[(-131072,-131072)]*18+[(131071,-131072),(-131072,131071)]*5+[(0,0)]*17
    ds=[(-131072,-131072),(131071,131071)]+[(131071 if k%3 else -131072,-131072 if k%2 else 131071) for k in range(len(xs)-2)]
    signals=[(xs,ds),([(0,0),(3,-3)],[(131071,-131072),(-131072,131071)])]
    inputs=[];outputs=[];weights=[]
    for x,d in signals:
        out,w=fixed.adapt(x,d,taps,'nlms',(mu,eps),stats=stats)
        inputs.extend((*z,*t,int(k==len(x)-1)) for k,(z,t) in enumerate(zip(x,d)))
        outputs.extend((*p,*e,int(k==len(out)-1)) for k,(p,e) in enumerate(out))
        weights.extend((*v,int(k==len(w)-1)) for k,v in enumerate(w))
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'cfg.txt').write_text(f'1 {taps} {mu} {eps}\n')
    for name,rows in (('in',inputs),('out',outputs),('w',weights)):save(folder/(name+'.txt'),rows)
    for group,stages,_ in GROUPS:write_expected(folder/(group+'_expected.txt'),stats,stages)
    save_json(folder/'saturation.json',stats)


def read_rows(path):
    lines=path.read_text().split('\n');count=int(lines[0])
    rows=[tuple(map(int,line.split())) for line in lines[1:1+count]]
    if len(rows)!=count:raise RuntimeError('Truncated vector file '+path.name)
    return rows


def fixture(spec,folder):
    name,log2n,kind,args=spec
    if kind=='cases':
        mode,step,eps,taps,seed,stress=args
        vectors(folder,mode,step,eps,taps,transactions=3,seed=seed,stress=stress)
    else:coefficient_fixture(folder)
    nlms,taps,mu,eps=map(int,(folder/'cfg.txt').read_text().split())
    mode='nlms' if nlms else 'lms'
    inputs=read_rows(folder/'in.txt');outputs=read_rows(folder/'out.txt');weights=read_rows(folder/'w.txt')
    # Replay every transaction from the pin files and compare with the fixed-model files.
    peaks=[0]*len(widths.STAGES);start=0;out_rows=[];w_rows=[];transactions=0
    for k,row in enumerate(inputs):
        if not row[4]:continue
        block=inputs[start:k+1];start=k+1;transactions+=1
        out,w,p=widths.trace([r[0:2] for r in block],[r[2:4] for r in block],taps,mode,mu,eps)
        out_rows.extend((*a,*b,int(j==len(out)-1)) for j,(a,b) in enumerate(out))
        w_rows.extend((*v,int(j==len(w)-1)) for j,v in enumerate(w))
        peaks=[max(a,b) for a,b in zip(peaks,p)]
    if start!=len(inputs) or out_rows!=outputs or w_rows!=weights:raise RuntimeError('Width trace differs from lms_fixed vectors: '+name)
    layout=widths.layout(log2n);bound=layout['bounds']
    limits=dict(product=max(map(abs,bound['product'])),sum=max(map(abs,bound['sum'])),pred=max(map(abs,bound['pred_raw'])),
                error=max(map(abs,bound['error'])),step=max(map(abs,bound['step_raw'])),coeff=max(map(abs,bound['coeff'])),
                delta=max(map(abs,bound['delta_raw'])),weight=max(map(abs,bound['weight'])),dump=max(map(abs,bound['dump_raw'])))
    if any(p>limits[s] for p,s in zip(peaks,widths.STAGES)):raise RuntimeError('Trajectory exceeds proven interval: '+name)
    return dict(case=name,log2n=log2n,mode=mode,taps=taps,mu=mu,eps=eps,transactions=transactions,inputs=len(inputs),
                outputs=len(outputs),weights=len(weights),selected=list(selected(log2n)),peaks=peaks,limits=[limits[s] for s in widths.STAGES],
                coefficient_bound_reached=peaks[5]==limits['coeff'],
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(spec,Path(tmp)/spec[0]) for spec in CASES]
    return dict(scope='LMS/NLMS exact intermediate widths from the configuration contract; operand-level trajectory reference and separate interval corners; synthesis paused',
                bounds={str(n):widths.layout(n) for n in range(5)},records=records,
                rtl_verified=False,rtl_equivalence=[],rtl_parameters=[],rtl_directed=[],rtl_negative=[])


def expected_counts(source):
    s=source['inputs'];t=source['taps']
    return [2*s*t,2*s,2*s,2*s,2*s,2*s,2*s*t,2*s*t,2*s*t,2*s*t,2*source['weights']]


DIRECTED=lambda n:[32*(1<<n),32,32,144,32*(1<<n),64*(1<<n),24]


def check_acceptance(result):
    model=report()
    if any(result[k]!=model[k] for k in ('bounds','records')):raise RuntimeError('Changed/incomplete LMS width fixtures/bounds')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_parameters','rtl_directed','rtl_negative')):raise RuntimeError('Unverified LMS width observations')
        return
    expected={(r['case'],l[0],a,s) for r in result['records'] for l in layouts(r['log2n']) for a in (1,0) for s in SCENARIOS}
    rows=result['rtl_equivalence']
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active'],r['scenario']) for r in rows}!=expected:raise RuntimeError('Incomplete/duplicated LMS width coverage')
    for row in rows:
        source=next(r for r in result['records'] if r['case']==row['case']);layout=dict(layouts(source['log2n']))[row['layout']]
        if (row['widths']!=list(layout) or any(row[k]!=source[k] for k in ('outputs','weights'))
                or [row[k] for k in COUNTS]!=expected_counts(source) or [row[k] for k in PEAKS]!=source['peaks']
                or row['energy_checks']!=source['inputs'] or row['observers_verified'] is not True
                or type(row['cycles']) is not int or row['cycles']<=0):raise RuntimeError('Missing LMS width observations')
    for source in result['records']:
        for a in (1,0):
            for s in SCENARIOS:
                if len({r['cycles'] for r in rows if r['case']==source['case'] and r['active']==a and r['scenario']==s})!=1:raise RuntimeError('LMS cycles changed with widths')
    expected={(r['case'],l[0],a) for r in result['records'] for l in invalid(r['log2n']) for a in (1,0)}
    rows=result['rtl_parameters']
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active']) for r in rows}!=expected or any(type(r['returncode']) is not int or not r['returncode'] or r['tag']!='PARAMETER' for r in rows):raise RuntimeError('Incomplete LMS width guards')
    rows=result['rtl_directed'];expected={(n,l,a) for n in (0,4) for l in ('selected','old_all') for a in (1,0)}
    if len(rows)!=8 or {(r['log2n'],r['layout'],r['active']) for r in rows}!=expected or any(r['checks']!=DIRECTED(r['log2n']) for r in rows):raise RuntimeError('Incomplete LMS width corners')
    rows=result['rtl_negative'];expected={(a,t) for a in (1,0) for t in (*TAGS,'ARITHMETIC')}
    if len(rows)!=18 or {(r['active'],r['tag']) for r in rows}!=expected or any(type(r['returncode']) is not int or not r['returncode'] for r in rows):raise RuntimeError('Incomplete LMS width fault controls')


def verify_rtl(result,base,jobs=12):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[];rom=ROOT/'rtl/common/mem/lms_reciprocal.mem'
    for spec,row in zip(CASES,result['records']):
        folder=base/'vectors'/spec[0]
        if fixture(spec,folder)!=row:raise RuntimeError('Changed LMS width vectors')
        artifacts.extend(p for p in folder.glob('*') if p.is_file())
    def job(active,row,first):
        found=dict(equivalence=[],parameters=[],directed=[],negative=[],artifacts=[])
        work=base/f'reset_{active}'/row['case'];work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
            ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/lms_tb.sv',ROOT/'rtl/tb/lms_width_bounds_tb.sv'],work,log)
        found['artifacts'].append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
        found['artifacts'].extend([positive,negative])
        def run(top,n,layout,label,options=(),bad=False):
            args=[f'-gLOG2N={n}',f'-gRESET_ACTIVE={active}',f'-gRECIP_FILE={rom}',*(f'-g{k}={v}' for k,v in zip(PARAMETERS,layout[1])),*options]
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet',top,*args,'-do',negative.name if bad else positive.name])),cwd=work,capture_output=True,text=True,timeout=600)
            text=proc.stdout+proc.stderr;log=work/(label+'.log');log.write_text(text);found['artifacts'].append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(label+'\n'+text[-4000:])
            return text,proc.returncode
        n=row['log2n'];folder=base/'vectors'/row['case']
        for layout in layouts(n):
            if active==1:
                log=work/f'{layout[0]}_lint.log'
                text=execute(['verilator','--lint-only','-Wall','--top-module','lms_filter',f'-GLOG2N={n}',*(f'-G{k}={v}' for k,v in zip(PARAMETERS,layout[1])),f'-I{pilot}',*SOURCES],ROOT,log)
                if '%Warning' in text:raise RuntimeError('LMS width lint warning '+layout[0])
                found['artifacts'].append(log)
            for scenario,options in SCENARIOS.items():
                text,_=run('work.lms_tb',n,layout,f'{layout[0]}_{scenario}',[f'+VECTORS={folder}','+CHECK_WIDTHS','+CHECK_ENERGY',*options])
                numeric=re.search(r'PASS LMS: (\d+) outputs, (\d+) weights, (\d+) cycles',text)
                raw=re.search(r'PASS LMS WIDTHS: '+' '.join([r'(\d+)']*20),text)
                energy=re.search(r'PASS LMS ENERGY: (\d+) (\d+) (\d+)',text)
                if not numeric or not raw or not energy:raise RuntimeError('Missing LMS width numeric/raw evidence')
                for group,(evaluations,events) in read_saturation_expected(folder).items():
                    if f'PASS SATURATION {group}: {evaluations} evaluations, {events} events' not in text:raise RuntimeError('Missing LMS width clamp evidence')
                if not re.search(r'PASS BOUNDS lms: [1-9]\d* checks',text):raise RuntimeError('Missing LMS width bounds evidence')
                found['equivalence'].append(dict(case=row['case'],layout=layout[0],widths=list(layout[1]),active=active,scenario=scenario,
                    outputs=int(numeric[1]),weights=int(numeric[2]),cycles=int(numeric[3]),energy_checks=int(energy[1]),observers_verified=True,
                    **dict(zip((*COUNTS,*PEAKS),map(int,raw.groups())))))
        for layout in invalid(n):
            text,rc=run('work.lms_tb',n,layout,f'{layout[0]}_parameter',[f'+VECTORS={folder}'],True)
            if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS LMS:' in text:raise RuntimeError('Unsafe LMS width accepted')
            found['parameters'].append(dict(case=row['case'],layout=layout[0],active=active,tag='PARAMETER',returncode=rc))
        if first:
            for d in (0,4):
                for layout in (layouts(d)[0],layouts(d)[-1]):
                    text,_=run('work.lms_width_bounds_tb',d,layout,f'directed_n{d}_{layout[0]}')
                    match=re.search(r'PASS LMS WIDTH BOUNDS: '+' '.join([r'(\d+)']*7),text)
                    if not match:raise RuntimeError('Missing directed LMS width evidence')
                    found['directed'].append(dict(log2n=d,layout=layout[0],active=active,checks=list(map(int,match.groups()))))
        if row['case']==NEGATIVE_CASE:
            for tag in (*TAGS,'ARITHMETIC'):
                directed=tag=='ARITHMETIC';top='work.lms_width_bounds_tb' if directed else 'work.lms_tb'
                options=['+INJECT_DIRECTED_WIDTH'] if directed else [f'+VECTORS={folder}','+CHECK_WIDTHS','+INJECT_WIDTH_'+tag]
                text,rc=run(top,n,layouts(n)[0],'negative_'+tag,options,True)
                if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or re.search(r'PASS LMS(?: WIDTH BOUNDS)?:',text):raise RuntimeError('LMS width fault missed '+tag)
                found['negative'].append(dict(active=active,tag=tag,returncode=rc))
        print('PASS LMS widths',row['case'],'reset',active,flush=True)
        return found
    tasks=[(a,row,i==0) for a in (1,0) for i,row in enumerate(result['records'])]
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        for found in pool.map(lambda t:job(*t),tasks):
            result['rtl_equivalence'].extend(found['equivalence']);result['rtl_parameters'].extend(found['parameters'])
            result['rtl_directed'].extend(found['directed']);result['rtl_negative'].extend(found['negative']);artifacts.extend(found['artifacts'])
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--jobs',type=int,default=12)
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/lms_width_sweep/results.json');args=parser.parse_args();args.output=args.output.resolve()
    if not 1<=args.jobs<=16:parser.error('--jobs must be 1..16')
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report()
        check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence',args.jobs) if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS LMS width sweep; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
