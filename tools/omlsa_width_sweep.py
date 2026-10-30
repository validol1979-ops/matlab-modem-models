#!/usr/bin/env python3
"""Exact OM-LSA gain intermediates: operand-level 128-bit reference on trajectories, arbitrary-code
corners, unsafe one-bit-narrower controls and width guards; synthesis paused."""
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
import omlsa_gain_widths as widths
from omlsa_cases import vectors
from run_omlsa import CASES as NATIVE_CASES
from spectral_evidence import check_observers
from beam_energy_study import SCENARIOS
PARAMETERS=widths.PARAMETERS
SELECTED=tuple(widths.layout()['selected'])
LAYOUTS=[('selected',SELECTED)]+[('old_'+name.lower().removesuffix('_width'),tuple(128 if j==i else v for j,v in enumerate(SELECTED)))
                                 for i,name in enumerate(PARAMETERS)]+[('old_all',(128,)*len(SELECTED))]
INVALID=[(name.lower().removesuffix('_width')+suffix,tuple(value if j==i else v for j,v in enumerate(SELECTED)))
         for i,name in enumerate(PARAMETERS) for suffix,value in (('_low',SELECTED[i]-1),('_high',129))]
UNSAFE=[(name.lower().removesuffix('_width')+'_unsafe',tuple(v-1 if j==i else v for j,v in enumerate(SELECTED))) for i,name in enumerate(PARAMETERS)]
TAGS=('RECIP','GAMMA','XI','V','G1','T','A','OUT','GG','PREV','REGISTER')
COUNTS=('bins','reciprocals','registers','prev_registers')
PEAKS=('recip_peak','gamma_peak','xi_peak','v_peak','g1_peak','t_peak','a_peak','out_peak','gg_peak','prev_peak')
DIRECTED=(640,6400,240,40,30,24,50,320,40,40)
MEM_DIR=ROOT/'rtl/common/mem'
PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def case_name(n,hop,nnoise):return f'n{n}_hop{hop}_nn{nnoise}'


def fixture(index,folder):
    n,hop,nnoise,alpha,complex_input=NATIVE_CASES[index]
    report=vectors(folder,n,hop,nnoise,alpha,transactions=2,complex_input=complex_input,seed=31+index,stress=index==4)
    return dict(case=case_name(n,hop,nnoise),log2n=n.bit_length()-1,log2hop=hop.bit_length()-1,nnoise=nnoise,alpha_q=report['alpha_q'],
                complex_input=complex_input,inputs=report['inputs'],outputs=report['outputs'],transactions=report['transactions'],
                bins=report['saturation']['evaluation_formula']['omlsa.gamma'],
                vector_hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()})


def peak_limits(bounds):
    rows=bounds['rows'];return [max(abs(rows[name]['min']),rows[name]['max']) for name in PARAMETERS]


def report():
    with tempfile.TemporaryDirectory() as tmp:records=[fixture(i,Path(tmp)/str(i)) for i in range(len(NATIVE_CASES))]
    return dict(scope='OM-LSA gain exact intermediates; operand-level 128-bit trajectory reference and separate arbitrary-code corners; '
                      'contracts power<=2^47 and alpha<=65536; synthesis paused',
                bounds=widths.layout(),records=records,rtl_verified=False,rtl_equivalence=[],rtl_parameters=[],
                rtl_directed=[],rtl_unsafe=[],rtl_negative=[])


def check_acceptance(result):
    model=report()
    if any(result[k]!=model[k] for k in ('bounds','records')):raise RuntimeError('Changed/incomplete OM-LSA width fixtures/bounds')
    sections=('rtl_equivalence','rtl_parameters','rtl_directed','rtl_unsafe','rtl_negative')
    if not result['rtl_verified']:
        if any(result[k] for k in sections):raise RuntimeError('Unverified OM-LSA width observations')
        return
    expected={(r['case'],l[0],a,s) for r in result['records'] for l in LAYOUTS for a in (1,0) for s in SCENARIOS}
    rows=result['rtl_equivalence']
    if len(rows)!=len(expected) or {(r['case'],r['layout'],r['active'],r['scenario']) for r in rows}!=expected:raise RuntimeError('Incomplete/duplicated OM-LSA width coverage')
    limits=peak_limits(result['bounds'])
    for row in rows:
        source=next(r for r in result['records'] if r['case']==row['case']);layout=next(l for l in LAYOUTS if l[0]==row['layout']);b=source['bins']
        if (row['widths']!=list(layout[1]) or row['outputs']!=source['outputs'] or [row[k] for k in COUNTS]!=[b,2*b,8*b,b-source['transactions']]
                or row['observers_verified'] is not True or type(row['cycles']) is not int or row['cycles']<=0):raise RuntimeError('Missing OM-LSA width observations')
        if any(type(row[k]) is not int or not 0<=row[k]<=limit for k,limit in zip(PEAKS,limits)):raise RuntimeError('OM-LSA peak outside proven range')
    for source in result['records']:
        matches=[r for r in rows if r['case']==source['case']]
        if len({tuple(r[k] for k in PEAKS) for r in matches})!=1:raise RuntimeError('OM-LSA raw values changed with widths/reset/stalls')
        for a in (1,0):
            for s in SCENARIOS:
                if len({r['cycles'] for r in matches if r['active']==a and r['scenario']==s})!=1:raise RuntimeError('OM-LSA cycles changed with widths')
    expected={(n,l[0],a) for n in (4,5,6) for l in INVALID for a in (1,0)};rows=result['rtl_parameters']
    if len(rows)!=len(expected) or {(r['log2n'],r['layout'],r['active']) for r in rows}!=expected or any(type(r['returncode']) is not int or not r['returncode'] or r['tag']!='PARAMETER' for r in rows):raise RuntimeError('Incomplete OM-LSA width guards')
    expected={(n,l,a) for n in (4,6) for l in ('selected','old_all') for a in (1,0)};rows=result['rtl_directed']
    if len(rows)!=len(expected) or {(r['log2n'],r['layout'],r['active']) for r in rows}!=expected or any(r['checks']!=list(DIRECTED) for r in rows):raise RuntimeError('Incomplete OM-LSA corners')
    expected={(l[0],a) for l in UNSAFE for a in (1,0)};rows=result['rtl_unsafe']
    if len(rows)!=len(expected) or {(r['layout'],r['active']) for r in rows}!=expected or any(type(r['returncode']) is not int or not r['returncode'] or r['tag']!='ARITHMETIC' for r in rows):raise RuntimeError('Incomplete one-bit-narrower controls')
    expected={(a,t) for a in (1,0) for t in (*TAGS,'ARITHMETIC')};rows=result['rtl_negative']
    if len(rows)!=len(expected) or {(r['active'],r['tag']) for r in rows}!=expected or any(type(r['returncode']) is not int or not r['returncode'] for r in rows):raise RuntimeError('Incomplete OM-LSA fault controls')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();artifacts=[]
    for index,row in enumerate(result['records']):
        folder=base/'vectors'/row['case']
        if fixture(index,folder)!=row:raise RuntimeError('Changed OM-LSA vectors')
        artifacts.extend(p for p in folder.glob('*') if p.is_file())
    def verify_active(active):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log';execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,ROOT/'rtl/tb/axis_check.sv',
            ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/omlsa_tb.sv',ROOT/'rtl/tb/omlsa_gain_bounds_tb.sv'],work,log);artifacts.append(log)
        positive=work/'run.do';positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.extend([positive,negative])
        def run(top,log2n,log2hop,layout,label,options=(),bad=False,extra=()):
            args=[f'-gLOG2N={log2n}',*([f'-gLOG2HOP={log2hop}'] if top=='work.omlsa_tb' else []),f'-gRESET_ACTIVE={active}',f'-gMEM_DIR={MEM_DIR}/',
                  *(f'-g{k}={v}' for k,v in zip(PARAMETERS,layout[1])),*extra,*options]
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet',top,*args,'-do',negative.name if bad else positive.name])),cwd=work,capture_output=True,text=True,timeout=300)
            text=proc.stdout+proc.stderr;log=work/(label+'.log');log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        for row in result['records']:
            n,h=row['log2n'],row['log2hop'];folder=base/'vectors'/row['case']
            for layout in LAYOUTS:
                if active==1:
                    log=work/f'{row["case"]}_{layout[0]}_lint.log'
                    text=execute(['verilator','--lint-only','-Wall','--top-module','omlsa',f'-GLOG2N={n}',f'-GLOG2HOP={h}',f'-GMEM_DIR="{MEM_DIR}/"',
                                  *(f'-G{k}={v}' for k,v in zip(PARAMETERS,layout[1])),f'-I{PILOT}',*SOURCES],ROOT,log);artifacts.append(log)
                    if '%Warning' in text:raise RuntimeError('OM-LSA lint warnings: '+layout[0])
                for scenario,options in SCENARIOS.items():
                    text,_=run('work.omlsa_tb',n,h,layout,f'{row["case"]}_{layout[0]}_{scenario}',[f'+VECTORS={folder}','+CHECK_GAIN_WIDTHS',*options])
                    numeric=re.search(r'PASS OMLSA: (\d+) outputs, (\d+) cycles',text)
                    raw=re.search(r'PASS OMLSA GAIN WIDTHS: '+' '.join([r'(\d+)']*14),text)
                    if not numeric or not raw:raise RuntimeError('Missing OM-LSA numeric/raw evidence')
                    check_observers(text,folder,'omlsa')
                    result['rtl_equivalence'].append(dict(case=row['case'],layout=layout[0],widths=list(layout[1]),active=active,scenario=scenario,
                        outputs=int(numeric[1]),cycles=int(numeric[2]),observers_verified=True,**dict(zip((*COUNTS,*PEAKS),map(int,raw.groups())))))
            print('PASS OM-LSA widths',row['case'],'reset',active,flush=True)
        for n in (4,5,6):
            row=next(r for r in result['records'] if r['log2n']==n);folder=base/'vectors'/row['case']
            for layout in INVALID:
                text,rc=run('work.omlsa_tb',n,row['log2hop'],layout,f'parameter_n{1<<n}_{layout[0]}',[f'+VECTORS={folder}'],True)
                if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS OMLSA:' in text:raise RuntimeError('Unsafe OM-LSA width accepted')
                result['rtl_parameters'].append(dict(log2n=n,layout=layout[0],active=active,tag='PARAMETER',returncode=rc))
        for n in (4,6):
            for layout in (LAYOUTS[0],LAYOUTS[-1]):
                text,_=run('work.omlsa_gain_bounds_tb',n,0,layout,f'directed_n{1<<n}_{layout[0]}')
                match=re.search(r'PASS OMLSA GAIN BOUNDS: '+' '.join([r'(\d+)']*10),text)
                if not match:raise RuntimeError('Missing OM-LSA corner evidence')
                result['rtl_directed'].append(dict(log2n=n,layout=layout[0],active=active,checks=list(map(int,match.groups()))))
        for layout in UNSAFE:
            text,rc=run('work.omlsa_gain_bounds_tb',4,0,layout,'unsafe_'+layout[0],(),True,['-gUNSAFE_WIDTH_TEST=1'])
            if not rc or not re.search(r'\*\* Fatal:.*\[ARITHMETIC\]',text) or 'PASS OMLSA GAIN BOUNDS' in text:raise RuntimeError('One-bit-narrower OM-LSA width not caught: '+layout[0])
            result['rtl_unsafe'].append(dict(layout=layout[0],widths=list(layout[1]),active=active,tag='ARITHMETIC',returncode=rc))
        row=result['records'][0];folder=base/'vectors'/row['case']
        for tag in (*TAGS,'ARITHMETIC'):
            if tag=='ARITHMETIC':text,rc=run('work.omlsa_gain_bounds_tb',4,0,LAYOUTS[0],'negative_'+tag,['+INJECT_DIRECTED'],True)
            else:text,rc=run('work.omlsa_tb',row['log2n'],row['log2hop'],LAYOUTS[0],'negative_'+tag,[f'+VECTORS={folder}','+CHECK_GAIN_WIDTHS','+INJECT_GAIN_'+tag],True)
            if not rc or not re.search(r'\*\* Fatal:.*\['+tag+r'\]',text) or re.search(r'PASS OMLSA(?: GAIN BOUNDS)?:',text):raise RuntimeError('OM-LSA width fault missed: '+tag)
            result['rtl_negative'].append(dict(active=active,tag=tag,returncode=rc))
    with ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(verify_active,(1,0)))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/omlsa_width_sweep/results.json');args=parser.parse_args();args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS OM-LSA width sweep; RTL verified='+str(result['rtl_verified']))
if __name__=='__main__':main()
