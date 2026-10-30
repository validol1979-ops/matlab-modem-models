#!/usr/bin/env python3
"""Exact beamformer coefficient energy and reciprocal widths over signed18 rails."""
import argparse
import hashlib
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from regression_evidence import ROOT,begin,finish,write_json,require_unoptimized,questa_paths
sys.path.insert(0,str(ROOT/'common/python'))
import beam_energy as energy
import beam_fixed as fixed
from beam_cases import save,BF_STAGES,AL_STAGES
from sat_diag import SatTrace,write_expected,save_json
CASES=tuple((f'm{1<<n}_min',n,1<<n,'min') for n in range(7))+(
    ('m3_capacity4',2,3,'min'),('m1_unit',0,1,'unit'),('m32_positive',5,32,'positive'),('m63_capacity64',6,63,'min'))
SCENARIOS={'stream':[],'stalled':['+STALL_INPUT','+STALL_OUTPUT'],
           'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}


def fixture(spec,folder):
    name,n,m,kind=spec
    coefficient={'min':(-131072,-131072),'positive':(131071,131071),'unit':(1,0)}[kind]
    weights=[coefficient]*m;h=[(32768,0),(0,32768)]
    bf_in=[];bf_out=[];al_in=[];al_out=[];stats=SatTrace()
    snapshots=[(-131072,-131072),(131071,131071),(131071,-131072),(0,1)]
    pairs=[(-131072,131071),(131071,-131072),(1,0),(0,-1),(0,0),(-1,1),(32768,0),(0,32768)]
    for tx in range(2):
        xs=[value for value in (snapshots if tx==0 else snapshots[::-1]) for _ in range(m)]
        out=fixed.beamform(xs,weights,stats=stats)
        bf_in.extend((*v,int(k==len(xs)-1)) for k,v in enumerate(xs))
        bf_out.extend((*v,int(k==len(out)-1)) for k,v in enumerate(out))
        xs=pairs if tx==0 else pairs[::-1];out=fixed.alamouti(xs,h,stats=stats)
        al_in.extend((*v,int(k==len(xs)-1)) for k,v in enumerate(xs))
        al_out.extend((*v,int(k==len(out)-1)) for k,v in enumerate(out))
    e=sum(re*re+im*im for re,im in weights);r,s=energy.exact_reciprocal(e)
    if (r,s+15)!=fixed.reciprocal(e):raise RuntimeError('Independent reciprocal differs')
    folder.mkdir(parents=True,exist_ok=True)
    for file,rows in (('bf_cfg',weights),('al_cfg',h),('bf_in',bf_in),('bf_out',bf_out),('al_in',al_in),('al_out',al_out)):
        save(folder/(file+'.txt'),rows)
    evaluations={};events={}
    for group,stages in (('beam',BF_STAGES),('alamouti',AL_STAGES)):
        rows=write_expected(folder/(group+'_expected.txt'),stats,stages)
        evaluations[group]=sum(row[0] for row in rows)
        events[group]=sum(row[1]+row[2] for row in rows)
    save_json(folder/'saturation.json',stats)
    return dict(case=name,log2m=n,channels=m,kind=kind,layout=energy.layout(n),energy=e,reciprocal=r,shift=s,
                old_energy=e% (1<<40),old_overflow=e>=(1<<40),bf_inputs=len(bf_in),bf_outputs=len(bf_out),
                al_outputs=len(al_out),evaluations=evaluations,events=events,
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(spec,Path(tmp)/spec[0]) for spec in CASES]
    return dict(scope='Exact beamformer coefficient energy and normalized reciprocal for full signed18 inputs; synthesis paused',
                records=records,rtl_verified=False,rtl_equivalence=[],rtl_parameters=[],rtl_negative=[])


def check_acceptance(result):
    if result['records']!=report()['records']:raise RuntimeError('Changed or incomplete beam energy fixtures')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_parameters','rtl_negative')):raise RuntimeError('Unverified beam energy records')
        return
    expected={(r['case'],w,a,s) for r in result['records'] for w in (r['layout']['selected_width'],r['layout']['control_width']) for a in (1,0) for s in SCENARIOS}
    rows=result['rtl_equivalence']
    if len(rows)!=len(expected) or {(r['case'],r['width'],r['active'],r['scenario']) for r in rows}!=expected:raise RuntimeError('Incomplete/duplicated beam energy RTL coverage')
    for row in rows:
        source=next(r for r in result['records'] if r['case']==row['case'])
        if (any(row[k]!=source[k] for k in ('bf_outputs','al_outputs','energy')) or row['energy_checks']!=source['channels']
                or row['reciprocal_checks']!=1 or row['observers_verified'] is not True
                or any(type(row[k]) is not int or row[k]<=0 for k in ('cycles','stream_cycles','configuration_cycles'))):raise RuntimeError('Missing beam energy observations')
    # Width changes the sequential divider's configuration time. The no-stall data pipeline is unchanged.
    for source in result['records']:
        for a in (1,0):
            if len({r['stream_cycles'] for r in rows if r['case']==source['case'] and r['active']==a and r['scenario']=='stream'})!=1:
                raise RuntimeError('Beam stream pipeline cycles differ with energy width')
    expected={(r['case'],w,a) for r in result['records'] for w in (r['layout']['selected_width']-1,64) for a in (1,0)}
    params=result['rtl_parameters']
    if len(params)!=len(expected) or {(r['case'],r['width'],r['active']) for r in params}!=expected or any(type(r['returncode']) is not int or r['returncode']==0 or r['tag']!='PARAMETER' for r in params):raise RuntimeError('Incomplete beam energy-width guards')
    controls=result['rtl_negative']
    if len(controls)!=6 or {(r['active'],r['tag']) for r in controls}!={(a,t) for a in (1,0) for t in ('ENERGY','NORMALIZATION','RECIPROCAL')} or any(type(r['returncode']) is not int or r['returncode']==0 for r in controls):raise RuntimeError('Incomplete beam energy fault controls')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    for spec,row in zip(CASES,result['records']):
        folder=base/'vectors'/spec[0]
        if fixture(spec,folder)!=row:raise RuntimeError('Changed beam energy vectors')
        artifacts.extend(folder.glob('*'))
    for active in (1,0):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
            ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/beam_tb.sv'],work,log);artifacts.append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        def run(row,width,scenario,bad=False):
            options=[f'-gLOG2M={row["log2m"]}',f'-gENERGY_WIDTH={width}',f'-gRESET_ACTIVE={active}',
                f'+VECTORS={base/"vectors"/row["case"]}','+CHECK_ENERGY',*SCENARIOS.get(scenario,[]),
                *(['+INJECT_'+scenario] if scenario in ('ENERGY','NORMALIZATION','RECIPROCAL') else [])]
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet','work.beam_tb',*options,'-do',negative.name if bad else positive.name])),cwd=work,capture_output=True,text=True,timeout=120)
            text=proc.stdout+proc.stderr;log=work/f'{row["case"]}_w{width}_{scenario}.log';log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        for row in result['records']:
            for width in (row['layout']['selected_width'],row['layout']['control_width']):
                if active==1:
                    log=work/f'{row["case"]}_w{width}_lint.log';execute(['verilator','--lint-only','-Wall','--top-module','beamform',f'-GLOG2M={row["log2m"]}',f'-GENERGY_WIDTH={width}',f'-I{pilot}',*SOURCES],ROOT,log);artifacts.append(log)
                for scenario in SCENARIOS:
                    text,_=run(row,width,scenario)
                    numeric=re.search(r'PASS BEAM: (\d+) beams, (\d+) symbols, (\d+) cycles',text)
                    raw=re.search(r'PASS BEAM ENERGY: (\d+) (\d+) (\d+) (\d+) (\d+)',text)
                    if not numeric or not raw:raise RuntimeError('Missing numeric/energy evidence')
                    for group in ('beam','alamouti'):
                        if f'PASS SATURATION {group}: {row["evaluations"][group]} evaluations, {row["events"][group]} events' not in text:raise RuntimeError('Missing beam saturation evidence')
                    if not re.search(r'PASS BOUNDS beam: [1-9]\d* checks',text):raise RuntimeError('Missing beam bounds evidence')
                    result['rtl_equivalence'].append(dict(case=row['case'],width=width,active=active,scenario=scenario,
                        bf_outputs=int(numeric[1]),al_outputs=int(numeric[2]),cycles=int(numeric[3]),energy_checks=int(raw[1]),
                        reciprocal_checks=int(raw[2]),energy=int(raw[3]),stream_cycles=int(raw[4]),configuration_cycles=int(raw[5]),observers_verified=True))
            for width in (row['layout']['selected_width']-1,64):
                text,rc=run(row,width,'parameter',True)
                if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS BEAM:' in text:raise RuntimeError('Unsafe beam energy width accepted')
                result['rtl_parameters'].append(dict(case=row['case'],width=width,active=active,tag='PARAMETER',returncode=rc))
            print('PASS beam energy',row['case'],'reset',active,flush=True)
        row=result['records'][5]
        for tag in ('ENERGY','NORMALIZATION','RECIPROCAL'):
            text,rc=run(row,row['layout']['selected_width'],tag,True)
            if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or 'PASS BEAM:' in text:raise RuntimeError('Beam energy fault missed')
            result['rtl_negative'].append(dict(active=active,tag=tag,returncode=rc))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/beam_energy_study/results.json');args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS beam energy study; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
