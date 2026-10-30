#!/usr/bin/env python3
"""Exact Alamouti energy, products, sums and scaled products before clipping."""
import argparse
import hashlib
from itertools import product
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
sys.path.insert(0,str(ROOT/'common/python'))
import alamouti_widths as widths
import beam_fixed as fixed
from beam_energy import exact_reciprocal
from beam_cases import save,BF_STAGES,AL_STAGES
from beam_energy_study import SCENARIOS
from sat_diag import SatTrace,write_expected,save_json
LO,HI=-131072,131071
CASES=(('all_min',(LO,LO,LO,LO)),('y0i_max',(LO,HI,HI,LO)),
       ('y1r_max',(HI,HI,LO,LO)),('y1i_max',(LO,HI,LO,HI)),
       ('unit_energy',(1,0,0,0)),('nominal',(13107,9830,32768,-6554)))
LAYOUTS=(('selected',38,37,61),('old_sum',39,37,61),('old_energy',38,40,61),
         ('old_scale',38,37,64),('old_all',39,40,64))
INVALID=(('sum_low',37,37,61),('sum_high',64,37,61),('energy_low',38,36,61),
         ('energy_high',38,64,61),('scale_low',38,37,60),('scale_high',38,37,97))
TAGS=('ENERGY','PRODUCT','SUM','SCALE','NORMALIZATION','RECIPROCAL')


def fixture(spec,folder):
    name,h=spec;taps=[h[:2],h[2:]];weights=[(32768,0)]
    stats=SatTrace();bf_in=[];bf_out=[];al_in=[];al_out=[];raw=[]
    signals=[list(product((LO,HI),repeat=4)),[(0,0,0,0),(1,-1,-1,1),(LO,0,0,HI),(HI,1,-1,LO)]]
    energy=sum(v*v for v in h);r,shift=exact_reciprocal(energy)
    if (r,shift+15)!=fixed.reciprocal(energy):raise RuntimeError('Independent Alamouti reciprocal differs')
    for pairs in signals:
        xs=[v for pair in pairs for v in (pair[:2],pair[2:])];out=fixed.alamouti(xs,taps,stats=stats)
        al_in.extend((*v,int(k==len(xs)-1)) for k,v in enumerate(xs));al_out.extend((*v,int(k==len(out)-1)) for k,v in enumerate(out))
        raw.extend(widths.sums(h,pair) for pair in pairs)
        xs=[(LO,HI),(HI,LO),(0,0),(1,-1)];out=fixed.beamform(xs,weights,stats=stats)
        bf_in.extend((*v,int(k==len(xs)-1)) for k,v in enumerate(xs));bf_out.extend((*v,int(k==len(out)-1)) for k,v in enumerate(out))
    folder.mkdir(parents=True,exist_ok=True)
    for file,rows in (('bf_cfg',weights),('al_cfg',taps),('bf_in',bf_in),('bf_out',bf_out),('al_in',al_in),('al_out',al_out),('al_raw',raw)):
        save(folder/(file+'.txt'),rows)
    evaluations={};events={}
    for group,stages in (('beam',BF_STAGES),('alamouti',AL_STAGES)):
        rows=write_expected(folder/(group+'_expected.txt'),stats,stages)
        evaluations[group]=sum(row[0] for row in rows);events[group]=sum(row[1]+row[2] for row in rows)
    save_json(folder/'saturation.json',stats)
    return dict(case=name,taps=list(h),energy=energy,reciprocal=r,shift=shift,pairs=len(raw),
                bf_outputs=len(bf_out),al_outputs=len(al_out),sum_max=max(v for row in raw for v in row),
                sum_min=min(v for row in raw for v in row),scale_peak=max(abs(v*r) for row in raw for v in row),
                field_bounds=[dict(min=min(row[k] for row in raw),max=max(row[k] for row in raw)) for k in range(4)],
                evaluations=evaluations,events=events,
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(spec,Path(tmp)/spec[0]) for spec in CASES]
    return dict(scope='Exact signed18 Alamouti energy/products/sums/scaled products before saturation; physical synthesis paused',
                bounds=widths.layout(),records=records,rtl_verified=False,rtl_equivalence=[],rtl_parameters=[],rtl_negative=[])


def check_acceptance(result):
    model=report()
    if any(result[k]!=model[k] for k in ('bounds','records')):raise RuntimeError('Changed or incomplete Alamouti fixtures/bounds')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_parameters','rtl_negative')):raise RuntimeError('Unverified Alamouti width records')
        return
    expected={(r['case'],label,a,s) for r in result['records'] for label,*_ in LAYOUTS for a in (1,0) for s in SCENARIOS}
    rows=result['rtl_equivalence']
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active'],r['scenario']) for r in rows}!=expected:raise RuntimeError('Incomplete/duplicated Alamouti RTL coverage')
    for row in rows:
        source=next(r for r in result['records'] if r['case']==row['case']);layout=next(r for r in LAYOUTS if r[0]==row['layout'])
        if (row['widths']!=list(layout[1:]) or any(row[k]!=source[k] for k in ('bf_outputs','al_outputs','energy','sum_max','sum_min','scale_peak'))
                or row['energy_checks']!=2 or row['reciprocal_checks']!=1 or row['product_checks']!=16*source['pairs']
                or row['sum_checks']!=4*source['pairs'] or row['scale_checks']!=4*source['pairs']
                or row['observers_verified'] is not True or row['configuration_cycles']!=layout[2]+31
                or any(type(row[k]) is not int or row[k]<=0 for k in ('cycles','stream_cycles','configuration_cycles'))):raise RuntimeError('Missing Alamouti raw observations')
    for source in result['records']:
        for a in (1,0):
            if len({r['stream_cycles'] for r in rows if r['case']==source['case'] and r['active']==a and r['scenario']=='stream'})!=1:raise RuntimeError('Alamouti data pipeline cycles differ')
    expected={(r['case'],label,a) for r in result['records'] for label,*_ in INVALID for a in (1,0)}
    params=result['rtl_parameters']
    if len(params)!=len(expected) or {(r['case'],r['layout'],r['active']) for r in params}!=expected or any(type(r['returncode']) is not int or not r['returncode'] or r['tag']!='PARAMETER' for r in params):raise RuntimeError('Incomplete Alamouti width guards')
    controls=result['rtl_negative']
    if len(controls)!=12 or {(r['active'],r['tag']) for r in controls}!={(a,t) for a in (1,0) for t in TAGS} or any(type(r['returncode']) is not int or not r['returncode'] for r in controls):raise RuntimeError('Incomplete Alamouti raw fault controls')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    for spec,row in zip(CASES,result['records']):
        folder=base/'vectors'/spec[0]
        if fixture(spec,folder)!=row:raise RuntimeError('Changed Alamouti vectors')
        artifacts.extend(folder.glob('*'))
    for active in (1,0):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
            ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/beam_tb.sv'],work,log);artifacts.append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        def run(row,layout,scenario,bad=False):
            label,sw,ew,qw=layout
            options=['-gLOG2M=0',f'-gAL_SUM_WIDTH={sw}',f'-gAL_ENERGY_WIDTH={ew}',f'-gAL_SCALE_WIDTH={qw}',f'-gRESET_ACTIVE={active}',
                f'+VECTORS={base/"vectors"/row["case"]}','+CHECK_ALAMOUTI_WIDTHS',*SCENARIOS.get(scenario,[]),
                *(['+INJECT_AL_'+scenario] if scenario in TAGS else [])]
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet','work.beam_tb',*options,'-do',negative.name if bad else positive.name])),cwd=work,capture_output=True,text=True,timeout=120)
            text=proc.stdout+proc.stderr;log=work/f'{row["case"]}_{label}_{scenario}.log';log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        if active==1:
            for label,sw,ew,qw in LAYOUTS:
                log=work/f'{label}_lint.log';execute(['verilator','--lint-only','-Wall','--top-module','alamouti_rx',f'-GSUM_WIDTH={sw}',f'-GENERGY_WIDTH={ew}',f'-GSCALE_WIDTH={qw}',f'-I{pilot}',*SOURCES],ROOT,log);artifacts.append(log)
        for row in result['records']:
            for layout in LAYOUTS:
                for scenario in SCENARIOS:
                    text,_=run(row,layout,scenario)
                    numeric=re.search(r'PASS BEAM: (\d+) beams, (\d+) symbols, (\d+) cycles',text)
                    raw=re.search(r'PASS ALAMOUTI WIDTHS: '+' '.join([r'(-?\d+)']*11),text)
                    if not numeric or not raw:raise RuntimeError('Missing Alamouti numeric/raw evidence')
                    for group in ('beam','alamouti'):
                        if f'PASS SATURATION {group}: {row["evaluations"][group]} evaluations, {row["events"][group]} events' not in text:raise RuntimeError('Missing Alamouti saturation evidence')
                    if not re.search(r'PASS BOUNDS beam: [1-9]\d* checks',text):raise RuntimeError('Missing beam/Alamouti bounds evidence')
                    names=('energy_checks','reciprocal_checks','product_checks','sum_checks','scale_checks','energy','sum_max','sum_min','scale_peak','stream_cycles','configuration_cycles')
                    result['rtl_equivalence'].append(dict(case=row['case'],layout=layout[0],widths=list(layout[1:]),active=active,scenario=scenario,
                        bf_outputs=int(numeric[1]),al_outputs=int(numeric[2]),cycles=int(numeric[3]),observers_verified=True,**dict(zip(names,map(int,raw.groups())))))
            for layout in INVALID:
                text,rc=run(row,layout,'parameter',True)
                if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS BEAM:' in text:raise RuntimeError('Unsafe Alamouti width accepted')
                result['rtl_parameters'].append(dict(case=row['case'],layout=layout[0],active=active,tag='PARAMETER',returncode=rc))
            print('PASS Alamouti widths',row['case'],'reset',active,flush=True)
        for tag in TAGS:
            text,rc=run(result['records'][0],LAYOUTS[0],tag,True)
            if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or 'PASS BEAM:' in text:raise RuntimeError('Alamouti raw fault missed')
            result['rtl_negative'].append(dict(active=active,tag=tag,returncode=rc))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/alamouti_width_sweep/results.json');args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS Alamouti width sweep; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
