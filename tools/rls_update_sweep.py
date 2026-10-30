#!/usr/bin/env python3
"""Exact RLS update products, rounding, weights and covariance writes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
sys.path.insert(0,str(ROOT/'common/python'))
import rls_update_widths as widths
from rls_width_sweep import CASES as DOT_CASES,fixture
from rls_cases import read_saturation_expected
from beam_energy_study import SCENARIOS
CASES=tuple(DOT_CASES[k] for k in (0,4,5,6,7))
PARAMETERS=('GAIN_WIDTH','UPDATE_WIDTH','WEIGHT_WIDTH','PT_WIDTH','COV_WIDTH')
SELECTED=(71,59,44,89,79)
LAYOUTS=[('selected',SELECTED)]+[('old_'+name.lower(),tuple(128 if j==i else v for j,v in enumerate(SELECTED))) for i,name in enumerate(PARAMETERS)]+[('old_all',(128,)*5)]
INVALID=[(name.lower()+suffix,tuple(value if j==i else v for j,v in enumerate(SELECTED))) for i,name in enumerate(PARAMETERS) for suffix,value in (('_low',SELECTED[i]-1),('_high',129))]
TAGS=('GAIN','PRODUCT','WEIGHT','PT','COV')
COUNTS=('gain','gain_regs','products','weights','weight_regs','pt','pt_regs','cov','cov_regs')
PEAKS=('gain_peak','product_peak','weight_peak','pt_peak','cov_peak')


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(spec,Path(tmp)/spec[0]) for spec in CASES]
    for row in records:row['weights_total']=row['weights']
    return dict(scope='RLS exact update intermediates, operand-level trajectory reference and separate arbitrary-code corners; synthesis paused',
                bounds=widths.layout(),records=records,rtl_verified=False,rtl_equivalence=[],rtl_parameters=[],rtl_directed=[],rtl_negative=[])


def check_acceptance(result):
    model=report()
    if any(result[k]!=model[k] for k in ('bounds','records')):raise RuntimeError('Changed/incomplete RLS update fixtures/bounds')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_parameters','rtl_directed','rtl_negative')):raise RuntimeError('Unverified update observations')
        return
    expected={(r['case'],l[0],a,s) for r in result['records'] for l in LAYOUTS for a in (1,0) for s in SCENARIOS}
    rows=result['rtl_equivalence']
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active'],r['scenario']) for r in rows}!=expected:raise RuntimeError('Incomplete/duplicated RLS update coverage')
    bound=result['bounds'];peak_limits=[-bound['gain_min'],bound['update'][0]['max'],max(abs(r[k]) for r in bound['weights'] for k in ('min','max')),bound['pt'][0]['max'],bound['cov_max']]
    for row in rows:
        source=next(r for r in result['records'] if r['case']==row['case']);layout=next(l for l in LAYOUTS if l[0]==row['layout']);s=source['inputs'];t=source['taps']
        expected_counts=[2*s*t]*5+[s*t*(t+1)]*2+[s*t*t,2*s*t*t]
        if (row['widths']!=list(layout[1]) or any(row[k]!=source[k] for k in ('outputs','weights_total'))
                or [row[k] for k in COUNTS]!=expected_counts or row['observers_verified'] is not True
                or type(row['cycles']) is not int or row['cycles']<=0):raise RuntimeError('Missing RLS update observations')
        if any(type(row[k]) is not int or not 0<=row[k]<=limit for k,limit in zip(PEAKS,peak_limits)):raise RuntimeError('Update peak outside proven range')
    for source in result['records']:
        matches=[r for r in rows if r['case']==source['case']]
        if len({tuple(r[k] for k in PEAKS) for r in matches})!=1:raise RuntimeError('Update raw values changed with widths/reset/stalls')
        for a in (1,0):
            for s in SCENARIOS:
                if len({r['cycles'] for r in matches if r['active']==a and r['scenario']==s})!=1:raise RuntimeError('Update cycles changed with widths')
    expected={(r['case'],l[0],a) for r in result['records'] for l in INVALID for a in (1,0)}
    rows=result['rtl_parameters']
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active']) for r in rows}!=expected or any(type(r['returncode']) is not int or not r['returncode'] or r['tag']!='PARAMETER' for r in rows):raise RuntimeError('Incomplete update width guards')
    rows=result['rtl_directed'];expected={(n,l,a) for n in (0,4) for l in ('selected','old_all') for a in (1,0)}
    if len(rows)!=8 or {(r['log2n'],r['layout'],r['active']) for r in rows}!=expected or any([r[k] for k in ('gain','updates','pt','cov')]!=[16*(1<<r['log2n']),192*(1<<r['log2n']),64*(1<<r['log2n'])**2,48*(1<<r['log2n'])**2] for r in rows):raise RuntimeError('Incomplete update corners')
    rows=result['rtl_negative'];expected={(a,t) for a in (1,0) for t in (*TAGS,'ARITHMETIC')}
    if len(rows)!=12 or {(r['active'],r['tag']) for r in rows}!=expected or any(type(r['returncode']) is not int or not r['returncode'] for r in rows):raise RuntimeError('Incomplete update fault controls')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    for spec,row in zip(CASES,result['records']):
        folder=base/'vectors'/spec[0]
        generated=fixture(spec,folder);generated['weights_total']=generated['weights']
        if generated!=row:raise RuntimeError('Changed update vectors')
        artifacts.extend(folder.glob('*'))
    def verify_active(active):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
            ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/rls_tb.sv',ROOT/'rtl/tb/rls_update_bounds_tb.sv'],work,log);artifacts.append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        def run(top,n,layout,label,options=(),bad=False):
            args=[f'-gLOG2N={n}',f'-gRESET_ACTIVE={active}',*(f'-g{k}={v}' for k,v in zip(PARAMETERS,layout[1])),*options]
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet',top,*args,'-do',negative.name if bad else positive.name])),cwd=work,capture_output=True,text=True,timeout=120)
            text=proc.stdout+proc.stderr;log=work/(label+'.log');log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        for row in result['records']:
            n=row['log2n'];folder=base/'vectors'/row['case']
            for layout in LAYOUTS:
                if active==1:
                    log=work/f'{row["case"]}_{layout[0]}_lint.log';execute(['verilator','--lint-only','-Wall','--top-module','rls_filter',f'-GLOG2N={n}',*(f'-G{k}={v}' for k,v in zip(PARAMETERS,layout[1])),f'-I{pilot}',*SOURCES],ROOT,log);artifacts.append(log)
                for scenario,options in SCENARIOS.items():
                    text,_=run('work.rls_tb',n,layout,f'{row["case"]}_{layout[0]}_{scenario}',[f'+VECTORS={folder}','+CHECK_UPDATES','+CHECK_DOT',*options])
                    numeric=re.search(r'PASS RLS: (\d+) outputs, (\d+) weights, (\d+) cycles',text)
                    raw=re.search(r'PASS RLS UPDATES: '+' '.join([r'(\d+)']*14),text)
                    if not numeric or not raw or 'PASS RLS DOT:' not in text:raise RuntimeError('Missing update numeric/raw evidence')
                    for group,(_,evaluations,events) in read_saturation_expected(folder).items():
                        if f'PASS SATURATION {group}: {evaluations} evaluations, {events} events' not in text:raise RuntimeError('Missing update clamp evidence')
                    if not re.search(r'PASS BOUNDS rls: [1-9]\d* checks',text):raise RuntimeError('Missing update bounds evidence')
                    result['rtl_equivalence'].append(dict(case=row['case'],layout=layout[0],widths=list(layout[1]),active=active,scenario=scenario,
                        outputs=int(numeric[1]),weights_total=int(numeric[2]),cycles=int(numeric[3]),observers_verified=True,**dict(zip((*COUNTS,*PEAKS),map(int,raw.groups())))))
            for layout in INVALID:
                text,rc=run('work.rls_tb',n,layout,f'{row["case"]}_{layout[0]}_parameter',[f'+VECTORS={folder}'],True)
                if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS RLS:' in text:raise RuntimeError('Unsafe update width accepted')
                result['rtl_parameters'].append(dict(case=row['case'],layout=layout[0],active=active,tag='PARAMETER',returncode=rc))
            print('PASS RLS updates',row['case'],'reset',active,flush=True)
        for n in (0,4):
            for layout in (LAYOUTS[0],LAYOUTS[-1]):
                text,_=run('work.rls_update_bounds_tb',n,layout,f'directed_n{n}_{layout[0]}')
                match=re.search(r'PASS RLS UPDATE BOUNDS: (\d+) (\d+) (\d+) (\d+)',text)
                if not match:raise RuntimeError('Missing directed update evidence')
                result['rtl_directed'].append(dict(log2n=n,layout=layout[0],active=active,**dict(zip(('gain','updates','pt','cov'),map(int,match.groups())))))
        row=result['records'][0]
        for tag in (*TAGS,'ARITHMETIC'):
            directed=tag=='ARITHMETIC';top='work.rls_update_bounds_tb' if directed else 'work.rls_tb'
            options=['+INJECT_DIRECTED_UPDATE'] if directed else [f'+VECTORS={base/"vectors"/row["case"]}','+CHECK_UPDATES','+INJECT_UPDATE_'+tag]
            text,rc=run(top,0,LAYOUTS[0],'negative_'+tag,options,True)
            if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or re.search(r'PASS RLS(?: UPDATE BOUNDS)?:',text):raise RuntimeError('Update fault missed')
            result['rtl_negative'].append(dict(active=active,tag=tag,returncode=rc))
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(verify_active,(1,0)))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/rls_update_sweep/results.json');args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report()
        check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS RLS update sweep; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
