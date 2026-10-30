#!/usr/bin/env python3
"""Exact 2x2 MMSE Gram, determinant, M, M*R/scaled weights and raw output sums (mmse2.sv)."""
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
import mmse2_widths as widths
from mmse_cases import vectors,CASES

SEED=37
LAYOUTS=(('selected',38,74,55,78,68),('old_all',39,76,58,84,68),('old_gram',39,74,55,78,68),
         ('old_det',38,76,55,78,68),('old_m',38,74,58,78,68),('old_scale',38,74,55,84,68))
INVALID=(('gram_low',37,74,55,78,68),('gram_high',65,74,55,78,68),('det_low',38,73,55,78,68),('det_high',38,129,55,78,68),
         ('m_low',38,74,54,78,68),('m_high',38,74,129,78,68),('scale_low',38,74,55,77,68),('scale_high',38,74,55,129,68),
         ('sum_low',38,74,55,78,67),('sum_high',38,74,55,78,129))
SCENARIOS={'stream':[],'stalled':['+STALL_INPUT','+STALL_OUTPUT'],'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}
CONFIGS={'stream':1,'stalled':1,'midreset':2,'outreset':2,'cfgreset':1}
EXTRA={'singular':('+SINGULAR','PASS MMSE SINGULAR'),'overflow':('+COEFFICIENT_OVERFLOW','PASS MMSE COEFFICIENT_OVERFLOW')}
TAGS=('GRAM','DET','RECIPROCAL','M','SCALE','WEIGHT','SUM')
NAMES=('gram_checks','det_checks','reciprocal_checks','m_checks','product_checks','scale_checks','weight_checks','sum_checks',
       'det_peak','m_peak','product_peak','scale_peak','sum_peak','reciprocal_cycles','configuration_cycles')
PEAKS=('det_peak','m_peak','product_peak','scale_peak','sum_peak')
# Direct traces of the two fixed rejection configurations of mmse_tb.
SINGULAR_H=((32768,0),)*4
OVERFLOW_H=((131071,0),(131070,0),(1,0),(1,0))


def read_rows(path):return [tuple(map(int,line.split())) for line in path.read_text().split('\n') if line.strip()]


def peaks(t,observations=()):
    m=t['m'] or [0];scaled=t['scaled'] or [0];r=t['reciprocal'] or 0
    sums=[abs(v) for k in range(0,len(observations),2) for v in widths.sums(t['weights'],observations[k],observations[k+1])]
    return dict(det_peak=abs(t['det']),m_peak=max(map(abs,m)),product_peak=max(abs(v*r) for v in m),
                scale_peak=max(map(abs,scaled)),sum_peak=max(sums,default=0))


def fixture(index,case,folder):
    report=vectors(folder,case,transactions=3,seed=SEED+index)
    rows=read_rows(folder/'cfg.txt');h=tuple(rows[:4]);lam=rows[4][0]
    t=widths.trace(h,lam)
    if t['overflow'] or t['det']<=0:raise RuntimeError('Unrepresentable MMSE2 fixture')
    obs=[row[:2] for row in read_rows(folder/'in.txt')]
    return dict(case=case,h=[list(v) for v in h],lambda_int=lam,pairs=report['pairs'],outputs=report['outputs'],
                reciprocal=t['reciprocal'],z=t['z'],**peaks(t,obs),
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()})


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(k,case,Path(tmp)/case) for k,case in enumerate(CASES)]
    extra=dict(singular=dict(det=widths.trace(SINGULAR_H,0)['det']),overflow=peaks(widths.trace(OVERFLOW_H,0)))
    return dict(scope='Exact mmse2 Gram/det/M/M*R/scaled/raw-sum widths from signed18 H and unsigned34 LAMBDA; physical synthesis paused',
                bounds=widths.layout(),records=records,extra=extra,rtl_verified=False,rtl_equivalence=[],rtl_extra=[],
                rtl_parameters=[],rtl_negative=[],rtl_lint=[])


def check_acceptance(result):
    model=report()
    if any(result[k]!=model[k] for k in ('bounds','records','extra')):raise RuntimeError('Changed or incomplete MMSE2 fixtures/bounds')
    b=model['bounds']
    if b['widths']!=dict(gram=38,det=74,m=55,m_interval=56,scale=78,sum=68):raise RuntimeError('Changed MMSE2 width proof')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_extra','rtl_parameters','rtl_negative','rtl_lint')):raise RuntimeError('Unverified MMSE2 width records')
        return
    rows=result['rtl_equivalence']
    expected={(r['case'],label,a,s) for r in result['records'] for label,*_ in LAYOUTS for a in (1,0) for s in SCENARIOS}
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active'],r['scenario']) for r in rows}!=expected:raise RuntimeError('Incomplete/duplicated MMSE2 RTL coverage')
    for row in rows:
        source=next(r for r in result['records'] if r['case']==row['case']);layout=next(r for r in LAYOUTS if r[0]==row['layout'])
        configs=CONFIGS[row['scenario']]
        if (row['widths']!=list(layout[1:]) or row['outputs']!=source['outputs'] or any(row[k]!=source[k] for k in PEAKS)
                or row['gram_checks']!=4*configs or row['det_checks']!=configs or row['reciprocal_checks']!=configs
                or any(row[k]!=8*configs for k in ('m_checks','product_checks','scale_checks','weight_checks'))
                or (row['sum_checks']!=4*source['pairs'] if configs==1 else row['sum_checks']<=4*source['pairs'])
                or row['observers_verified'] is not True
                or any(type(row[k]) is not int or row[k]<=0 for k in ('cycles','reciprocal_cycles','configuration_cycles'))):
            raise RuntimeError('Missing MMSE2 raw observations')
    for source in result['records']:
        for a,s in product((1,0),SCENARIOS):
            group=[r for r in rows if r['case']==source['case'] and r['active']==a and r['scenario']==s]
            if len({(r['cycles'],r['reciprocal_cycles'],r['configuration_cycles']) for r in group})!=1:raise RuntimeError('MMSE2 cycles differ between layouts')
    extra=result['rtl_extra']
    if len(extra)!=2*2*len(LAYOUTS) or {(r['scenario'],r['layout'],r['active']) for r in extra}!={(s,l[0],a) for s in EXTRA for l in LAYOUTS for a in (1,0)}:
        raise RuntimeError('Incomplete MMSE2 rejection coverage')
    for row in extra:
        if row['scenario']=='singular':
            if (row['gram_checks'],row['det_checks'],row['reciprocal_checks'],row['m_checks'],row['det_peak'])!=(4,1,0,0,model['extra']['singular']['det']):raise RuntimeError('MMSE2 singular observations')
        elif ((row['gram_checks'],row['det_checks'],row['reciprocal_checks'],row['m_checks'],row['product_checks'],row['scale_checks'],row['weight_checks'])!=(4,1,1,8,8,8,0)
              or any(row[k]!=model['extra']['overflow'][k] for k in PEAKS)):raise RuntimeError('MMSE2 overflow observations')
    expected={(label,a) for label,*_ in INVALID for a in (1,0)}
    params=result['rtl_parameters']
    if len(params)!=len(expected) or {(r['layout'],r['active']) for r in params}!=expected or any(type(r['returncode']) is not int or not r['returncode'] or r['tag']!='PARAMETER' for r in params):raise RuntimeError('Incomplete MMSE2 width guards')
    controls=result['rtl_negative']
    if len(controls)!=2*len(TAGS) or {(r['active'],r['tag']) for r in controls}!={(a,t) for a in (1,0) for t in TAGS} or any(type(r['returncode']) is not int or not r['returncode'] for r in controls):raise RuntimeError('Incomplete MMSE2 raw fault controls')
    if sorted(r['layout'] for r in result['rtl_lint'])!=sorted(l[0] for l in LAYOUTS) or any(r['warnings']!=0 for r in result['rtl_lint']):raise RuntimeError('Incomplete MMSE2 lint')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    for k,(case,row) in enumerate(zip(CASES,result['records'])):
        folder=base/'vectors'/case
        if fixture(k,case,folder)!=row:raise RuntimeError('Changed MMSE2 vectors')
        artifacts.extend(folder.glob('*'))
    for label,gw,dw,mw,sw,yw in LAYOUTS:
        log=base/f'{label}_lint.log'
        text=execute(['verilator','--lint-only','-Wall','--top-module','mmse2',f'-GGRAM_WIDTH={gw}',f'-GDET_WIDTH={dw}',f'-GM_WIDTH={mw}',
                      f'-GSCALE_WIDTH={sw}',f'-GSUM_WIDTH={yw}',f'-I{pilot}',*SOURCES],ROOT,log);artifacts.append(log)
        result['rtl_lint'].append(dict(layout=label,warnings=text.count('%Warning')))
    for active in (1,0):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
            ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/mmse_tb.sv'],work,log);artifacts.append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        def run(case,layout,scenario,options,bad=False):
            label,gw,dw,mw,sw,yw=layout
            command=[bindir/'vsim','-64','-c','-quiet','work.mmse_tb',f'-gRESET_ACTIVE={active}',f'-gGRAM_WIDTH={gw}',f'-gDET_WIDTH={dw}',
                     f'-gM_WIDTH={mw}',f'-gSCALE_WIDTH={sw}',f'-gSUM_WIDTH={yw}',f'+VECTORS={base/"vectors"/case}','+CHECK_MMSE2_WIDTHS',*options,
                     '-do',negative.name if bad else positive.name]
            proc=subprocess.run(list(map(str,command)),cwd=work,capture_output=True,text=True,timeout=180)
            text=proc.stdout+proc.stderr;log=work/f'{case}_{label}_{scenario}.log';log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        def raw(text):
            match=re.search(r'PASS MMSE2 WIDTHS: '+' '.join([r'(-?\d+)']*len(NAMES)),text)
            if not match:raise RuntimeError('Missing MMSE2 raw evidence')
            return dict(zip(NAMES,map(int,match.groups())))
        for row in result['records']:
            for layout in LAYOUTS:
                for scenario,options in SCENARIOS.items():
                    text,_=run(row['case'],layout,scenario,options)
                    numeric=re.search(r'PASS MMSE: (\d+) outputs, (\d+) cycles',text)
                    if not numeric or not re.search(r'PASS BOUNDS mmse: [1-9]\d* checks',text) or 'PASS SATURATION mmse:' not in text:raise RuntimeError('Missing MMSE2 numeric evidence')
                    result['rtl_equivalence'].append(dict(case=row['case'],layout=layout[0],widths=list(layout[1:]),active=active,scenario=scenario,
                        outputs=int(numeric[1]),cycles=int(numeric[2]),observers_verified=True,**raw(text)))
            print('PASS MMSE2 widths',row['case'],'reset',active,flush=True)
        for layout in LAYOUTS:
            for scenario,(flag,banner) in EXTRA.items():
                text,_=run(CASES[0],layout,scenario,[flag])
                if banner not in text:raise RuntimeError('Missing MMSE2 rejection evidence')
                result['rtl_extra'].append(dict(scenario=scenario,layout=layout[0],active=active,**raw(text)))
        for layout in INVALID:
            text,rc=run(CASES[0],layout,'parameter',[],True)
            if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS MMSE:' in text:raise RuntimeError('Unsafe MMSE2 width accepted')
            result['rtl_parameters'].append(dict(layout=layout[0],active=active,tag='PARAMETER',returncode=rc))
        for tag in TAGS:
            text,rc=run(CASES[0],LAYOUTS[0],'inject_'+tag,['+INJECT_MMSE2='+tag],True)
            if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or 'PASS MMSE:' in text:raise RuntimeError('MMSE2 raw fault missed: '+tag)
            result['rtl_negative'].append(dict(active=active,tag=tag,returncode=rc))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/mmse2_width_sweep/results.json');args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS MMSE2 width sweep; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
