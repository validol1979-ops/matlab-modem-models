#!/usr/bin/env python3
"""Exact LMS/NLMS history energy and reciprocal normalization over signed18 rails."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
sys.path.insert(0,str(ROOT/'common/python'))
import lms_energy as energy
import lms_fixed as fixed
from lms_cases import GROUPS,save,read_saturation_expected
from sat_diag import SatTrace,write_expected,save_json
CASES=tuple((f'n{1<<n}_eps{eps}',n,eps,False) for n in range(5) for eps in (512,(1<<34)-1))+(
    ('n16_positive_epsmax',4,(1<<34)-1,True),('repro_n16_eps512',4,512,None))
SCENARIOS={'stream':[],'stalled':['+STALL_INPUT','+STALL_OUTPUT'],
           'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}


def fixture(spec,folder):
    name,n,eps,positive=spec;taps=1<<n;mu=131072
    full=(131071,131071) if positive else (-131072,-131072)
    xs=[full]*(2*taps+3)+[(131071,-131072),(-131072,131071)]*(taps+1)+[(0,0)]*(taps+3)
    ds=[(131071 if k%3 else -131072,-131072 if k%2 else 131071) for k in range(len(xs))]
    signals=[(xs,ds),([(0,0),(1,-1),(-1,1)],[(0,0),(131071,-131072),(-131072,131071)])]
    if positive is None:
        xs=[(-131072,-131072)]*24+[(131071,-131072),(-131072,131071)]*12+[(0,0)]*20
        ds=[(131071 if k%3 else -131072,-131072 if k%2 else 131071) for k in range(len(xs))]
        signals=[(xs,ds)]
    inputs=[];outputs=[];weights=[];trace=[];stats=SatTrace()
    for x,d in signals:
        out,w=fixed.adapt(x,d,taps,'nlms',(mu,eps),stats=stats)
        inputs.extend((*z,*target,int(k==len(x)-1)) for k,(z,target) in enumerate(zip(x,d)))
        outputs.extend((*p,*e,int(k==len(out)-1)) for k,(p,e) in enumerate(out))
        weights.extend((*v,int(k==len(w)-1)) for k,v in enumerate(w))
        trace.extend(energy.history_trace(x,taps,eps))
    layout=energy.layout(n);peak=max(row[0] for row in trace);total_peak=max(row[1] for row in trace)
    if not positive and (peak!=layout['power_max'] or total_peak!=layout['power_max']+eps):raise RuntimeError('Full history corner not reached')
    if max(row[2] for row in trace)>layout['selected_width']:raise RuntimeError('Unsafe NLMS energy width')
    folder.mkdir(parents=True,exist_ok=True)
    (folder/'cfg.txt').write_text(f'1 {taps} {mu} {eps}\n')
    for name_,rows in (('in',inputs),('out',outputs),('w',weights),('energy_trace',trace)):save(folder/(name_+'.txt'),rows)
    for group,stages,_ in GROUPS:write_expected(folder/(group+'_expected.txt'),stats,stages)
    save_json(folder/'saturation.json',stats)
    return dict(case=name,log2n=n,taps=taps,eps=eps,positive_rail=positive,layout=layout,
                transactions=len(signals),inputs=len(inputs),outputs=len(outputs),weights=len(weights),
                observed_power_max=peak,observed_total_max=total_peak,observed_bits_max=max(row[2] for row in trace),
                old_power_overflow=any(row[0]>=(1<<39) for row in trace),
                old_total_overflow=any(row[1]>=(1<<39) for row in trace),
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(spec,Path(tmp)/spec[0]) for spec in CASES]
    return dict(scope='Exact signed18 LMS history power plus unsigned34 EPS, reciprocal exponent/address/result; physical synthesis paused',
                records=records,rtl_verified=False,rtl_equivalence=[],rtl_parameters=[],rtl_negative=[])


def check_acceptance(result):
    if result['records']!=report()['records']:raise RuntimeError('Changed or incomplete LMS energy fixtures')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_parameters','rtl_negative')):raise RuntimeError('Unverified LMS energy records')
        return
    expected={(r['case'],w,a,s) for r in result['records'] for w in (r['layout']['selected_width'],r['layout']['control_width']) for a in (1,0) for s in SCENARIOS}
    rows=result['rtl_equivalence']
    if len(rows)!=len(expected) or {(r['case'],r['width'],r['active'],r['scenario']) for r in rows}!=expected:raise RuntimeError('Incomplete/duplicated LMS energy RTL coverage')
    for row in rows:
        source=next(r for r in result['records'] if r['case']==row['case'])
        if (any(row[k]!=source[k] for k in ('outputs','weights')) or row['energy_checks']!=source['inputs'] or row['rom_checks']!=source['inputs']
                or row['power_peak']!=source['observed_power_max'] or row['observers_verified'] is not True
                or type(row['cycles']) is not int or row['cycles']<=0):raise RuntimeError('Missing LMS energy observations')
    for source in result['records']:
        for a in (1,0):
            for s in SCENARIOS:
                if len({r['cycles'] for r in rows if r['case']==source['case'] and r['active']==a and r['scenario']==s})!=1:raise RuntimeError('LMS cycles differ with energy width')
    expected={(r['case'],w,a) for r in result['records'] for w in (r['layout']['selected_width']-1,64) for a in (1,0)}
    params=result['rtl_parameters']
    if len(params)!=len(expected) or {(r['case'],r['width'],r['active']) for r in params}!=expected or any(type(r['returncode']) is not int or r['returncode']==0 or r['tag']!='PARAMETER' for r in params):raise RuntimeError('Incomplete energy-width guards')
    controls=result['rtl_negative']
    if len(controls)!=6 or {(r['active'],r['tag']) for r in controls}!={(a,t) for a in (1,0) for t in ('ENERGY','NORMALIZATION','RECIPROCAL')} or any(type(r['returncode']) is not int or r['returncode']==0 for r in controls):raise RuntimeError('Incomplete energy normalization fault controls')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    for spec,row in zip(CASES,result['records']):
        folder=base/'vectors'/spec[0]
        if fixture(spec,folder)!=row:raise RuntimeError('Changed LMS energy vectors')
        artifacts.extend(folder.glob('*'))
    for active in (1,0):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
            ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/lms_tb.sv'],work,log);artifacts.append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        def run(row,width,scenario,bad=False):
            folder=base/'vectors'/row['case']
            options=[f'-gLOG2N={row["log2n"]}',f'-gENERGY_WIDTH={width}',f'-gRESET_ACTIVE={active}',f'-gRECIP_FILE={ROOT/"rtl/common/mem/lms_reciprocal.mem"}',
                f'+VECTORS={folder}','+CHECK_ENERGY',*SCENARIOS.get(scenario,[]),
                *([{'ENERGY':'+INJECT_ENERGY','NORMALIZATION':'+INJECT_MANTISSA','RECIPROCAL':'+INJECT_RECIPROCAL'}[scenario]] if scenario in ('ENERGY','NORMALIZATION','RECIPROCAL') else [])]
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet','work.lms_tb',*options,'-do',negative.name if bad else positive.name])),cwd=work,capture_output=True,text=True,timeout=120)
            text=proc.stdout+proc.stderr;log=work/f'{row["case"]}_w{width}_{scenario}.log';log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        for row in result['records']:
            for width in (row['layout']['selected_width'],row['layout']['control_width']):
                if active==1:
                    log=work/f'{row["case"]}_w{width}_lint.log';execute(['verilator','--lint-only','-Wall','--top-module','lms_filter',f'-GLOG2N={row["log2n"]}',f'-GENERGY_WIDTH={width}',f'-I{pilot}',*SOURCES],ROOT,log);artifacts.append(log)
                for scenario in SCENARIOS:
                    text,_=run(row,width,scenario)
                    numeric=re.search(r'PASS LMS: (\d+) outputs, (\d+) weights, (\d+) cycles',text)
                    raw=re.search(r'PASS LMS ENERGY: (\d+) (\d+) (\d+)',text)
                    if not numeric or not raw:raise RuntimeError('Missing numeric/energy evidence')
                    for group,(evaluations,events) in read_saturation_expected(base/'vectors'/row['case']).items():
                        if f'PASS SATURATION {group}: {evaluations} evaluations, {events} events' not in text:raise RuntimeError('Missing LMS saturation evidence')
                    if not re.search(r'PASS BOUNDS lms: [1-9]\d* checks',text):raise RuntimeError('Missing LMS bounds evidence')
                    result['rtl_equivalence'].append(dict(case=row['case'],width=width,active=active,scenario=scenario,
                        outputs=int(numeric[1]),weights=int(numeric[2]),cycles=int(numeric[3]),energy_checks=int(raw[1]),rom_checks=int(raw[2]),power_peak=int(raw[3]),observers_verified=True))
            for width in (row['layout']['selected_width']-1,64):
                text,rc=run(row,width,'parameter',True)
                if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS LMS:' in text:raise RuntimeError('Unsafe LMS energy width accepted')
                result['rtl_parameters'].append(dict(case=row['case'],width=width,active=active,tag='PARAMETER',returncode=rc))
            print('PASS LMS energy',row['case'],'reset',active,flush=True)
        row=result['records'][-1]
        for tag in ('ENERGY','NORMALIZATION','RECIPROCAL'):
            text,rc=run(row,row['layout']['selected_width'],tag,True)
            if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or 'PASS LMS:' in text:raise RuntimeError('Energy normalization fault missed')
            result['rtl_negative'].append(dict(active=active,tag=tag,returncode=rc))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/lms_energy_study/results.json');args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS LMS energy study; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
