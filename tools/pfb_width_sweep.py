#!/usr/bin/env python3
"""Prove phase-local PFB accumulator widths and compare old/new RTL arithmetic."""
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
import pfb_widths
from pfb_cases import vectors
from run_pfb import CASES as NATIVE_CASES,files
from spectral_evidence import check_observers,check_embedded_fft

CASES=tuple((f'native_{i}',*spec,False,i==7,31+i) for i,spec in enumerate(NATIVE_CASES))+(
    ('full_m4_t256',2,2,8,4,256,True,False,91),
    ('full_m64_t256',6,3,8,32,256,True,False,92),
    ('short_m16_t4',4,1,2,3,4,True,False,93))
SCENARIOS={'stream':[],'stalled':['+STALL_INPUT','+STALL_OUTPUT'],
           'midreset':['+MID_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'outreset':['+OUT_RESET','+STALL_INPUT','+STALL_OUTPUT'],
           'cfgreset':['+CFG_RESET','+STALL_INPUT','+STALL_OUTPUT']}


def fixture(spec,folder):
    name,m,l,t,d,count,full,stress,seed=spec
    reference=vectors(folder,m,d,count,seed=seed,stress=stress,full_scale=full)
    inputs=[tuple(map(int,line.split())) for line in (folder/'in.txt').read_text().splitlines()[1:]]
    taps=list(map(int,(folder/'cfg.txt').read_text().splitlines()[1:-1]))
    phase_sums=[];frame=[]
    for re_,im,last in inputs:
        frame.append((re_,im))
        if last:
            for end in range(0,len(frame),d):
                phases=[[0,0] for _ in range(1<<m)]
                for j in range(min(end+1,len(taps))):
                    xr,xi=frame[end-j];phases[j%(1<<m)][0]+=taps[j]*xr;phases[j%(1<<m)][1]+=taps[j]*xi
                phase_sums.extend(phases)
            frame=[]
    if frame:raise RuntimeError('Incomplete frame')
    layout=pfb_widths.layout(m,t)
    flat=[value for row in phase_sums for value in row]
    if min(flat)<layout['raw_bounds'][0] or max(flat)>layout['raw_bounds'][1]:raise RuntimeError('Unsafe phase bounds')
    if full and (max(flat)!=layout['raw_bounds'][1] or min(flat)!=layout['raw_bounds'][0]):
        raise RuntimeError('Full-scale phase fixture did not attain both exact bounds')
    hashes={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(folder.glob('*')) if p.is_file()}
    return dict(case=name,log2m=m,log2lanes=l,log2tmax=t,decimation=d,taps=count,
                full_scale=full,bins=reference['bins'],layout=layout,
                raw_phases=len(phase_sums),observed_bounds=[min(flat),max(flat)],
                raw_hash=hashlib.sha256(json.dumps(phase_sums,separators=(',',':')).encode()).hexdigest(),vector_hashes=hashes)


def report():
    with tempfile.TemporaryDirectory() as tmp:
        rows=[fixture(spec,Path(tmp)/spec[0]) for spec in CASES]
    return dict(scope='Exact phase-local signed18 PFB accumulator range, including +4096 rounding; physical synthesis paused',
                records=rows,rtl_verified=False,rtl_equivalence=[],rtl_negative=[],rtl_parameters=[])


def check_acceptance(result):
    if result['records']!=report()['records']:raise RuntimeError('Changed or incomplete PFB phase width measurements')
    if not result['rtl_verified']:
        if any(result[k] for k in ('rtl_equivalence','rtl_negative','rtl_parameters')):raise RuntimeError('Unverified RTL data')
        return
    expected={(r['case'],w,a,s) for r in result['records'] for w in {r['layout']['selected_width'],r['layout']['legacy_width']}
              for a in (1,0) for s in SCENARIOS}
    rows=result['rtl_equivalence']
    if len(rows)!=len(expected) or {(r['case'],r['width'],r['active'],r['scenario']) for r in rows}!=expected:
        raise RuntimeError('Incomplete/duplicated PFB RTL width matrix')
    for r in rows:
        source=next(row for row in result['records'] if row['case']==r['case'])
        if (r['bins']!=source['bins'] or r['raw_phases']!=source['raw_phases'] or r['raw_peak']!=source['observed_bounds'][1]
                or r['observers_verified'] is not True or type(r['cycles']) is not int or r['cycles']<=0):
            raise RuntimeError('Incomplete PFB arithmetic evidence')
    for case in result['records']:
        for active in (1,0):
            for scenario in SCENARIOS:
                if len({r['cycles'] for r in rows if r['case']==case['case'] and r['active']==active and r['scenario']==scenario})!=1:
                    raise RuntimeError('PFB cycles differ with accumulator width')
    controls=result['rtl_negative']
    if len(controls)!=2 or {r['active'] for r in controls}!={0,1} or any(r['tag']!='ACCUMULATOR' or r['returncode']==0 for r in controls):
        raise RuntimeError('Missing raw accumulator fault controls')
    expected={(r['case'],w,a) for r in result['records'] for w in (r['layout']['selected_width']-1,64) for a in (1,0)}
    params=result['rtl_parameters']
    if len(params)!=len(expected) or {(r['case'],r['width'],r['active']) for r in params}!=expected or any(r['returncode']==0 or r['tag']!='PARAMETER' for r in params):
        raise RuntimeError('Incomplete parameter rejection matrix')


def verify_rtl(result,base):
    from run_rtl import SOURCES,execute
    bindir,_=questa_paths();pilot=ROOT/'rtl/modems/bpsk_costas_2008_08_25';artifacts=[]
    for spec,row in zip(CASES,result['records']):
        folder=base/'vectors'/spec[0]
        if fixture(spec,folder)!=row:raise RuntimeError('Changed vectors')
        artifacts.extend(folder.glob('*'))
    for active in (1,0):
        work=base/f'reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
        log=work/'compile.log'
        execute([bindir/'vlog','-64','-sv',f'+incdir+{pilot}',f'+incdir+{ROOT/"rtl/tb"}',*SOURCES,
                 ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/stream_cover.sv',ROOT/'rtl/tb/sat_group_check.sv',ROOT/'rtl/tb/pfb_tb.sv'],work,log)
        artifacts.append(log)
        script=work/'run.do';script.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.append(script)
        negative=work/'negative.do';negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts.append(negative)
        def run(row,width,scenario,bad=False):
            table=ROOT/files(1<<row['log2m'])['TWIDDLE_FILE'];folder=base/'vectors'/row['case']
            options=[f'-gLOG2M={row["log2m"]}',f'-gLOG2LANES={row["log2lanes"]}',f'-gLOG2TMAX={row["log2tmax"]}',
                     f'-gACC_WIDTH={width}',f'-gRESET_ACTIVE={active}',f'-gTWIDDLE_FILE={table}']
            flags=SCENARIOS.get(scenario,[])+(['+INJECT_ACCUMULATOR'] if scenario=='negative' else [])
            proc=subprocess.run(list(map(str,[bindir/'vsim','-64','-c','-quiet','work.pfb_tb',*options,
                                f'+VECTORS={folder}','+CHECK_ACCUMULATOR',*flags,'-do',negative.name if bad else script.name])),cwd=work,capture_output=True,text=True,timeout=120)
            text=proc.stdout+proc.stderr;log=work/f'{row["case"]}_w{width}_{scenario}.log';log.write_text(text);artifacts.append(log)
            if not bad and (proc.returncode or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError(text[-4000:])
            return text,proc.returncode
        for row in result['records']:
            for width in sorted({row['layout']['selected_width'],row['layout']['legacy_width']}):
                if active==1:
                    log=work/f'{row["case"]}_w{width}_lint.log'
                    execute(['verilator','--lint-only','-Wall','--top-module','pfb_analysis',f'-GACC_WIDTH={width}',
                             f'-GLOG2M={row["log2m"]}',f'-GLOG2LANES={row["log2lanes"]}',f'-GLOG2TMAX={row["log2tmax"]}',f'-I{pilot}',*SOURCES],ROOT,log)
                    artifacts.append(log)
                for scenario in SCENARIOS:
                    text,_=run(row,width,scenario)
                    numeric=re.search(r'PASS PFB: (\d+) bins, (\d+) cycles',text)
                    raw=re.search(r'PASS PFB ACCUMULATOR: (\d+) (\d+)',text)
                    if not numeric or not raw:raise RuntimeError('Missing PFB raw/numeric evidence')
                    check_observers(text,base/'vectors'/row['case'],'pfb');check_embedded_fft(text,base/'vectors'/row['case'],('pfb',))
                    result['rtl_equivalence'].append(dict(case=row['case'],width=width,active=active,scenario=scenario,
                        bins=int(numeric[1]),cycles=int(numeric[2]),raw_phases=int(raw[1]),raw_peak=int(raw[2]),observers_verified=True))
            for width in (row['layout']['selected_width']-1,64):
                text,rc=run(row,width,'parameter',True)
                if not rc or not re.search(r'\*\* Fatal:.*\[PARAMETER\]',text) or 'PASS PFB:' in text:raise RuntimeError('Unsafe PFB width accepted')
                result['rtl_parameters'].append(dict(case=row['case'],width=width,active=active,tag='PARAMETER',returncode=rc))
            print('PASS PFB width',row['case'],'reset',active,flush=True)
        row=result['records'][0];text,rc=run(row,row['layout']['selected_width'],'negative',True)
        if not rc or not re.search(r'\*\* Fatal:.*\[ACCUMULATOR\]',text) or 'PASS PFB:' in text:raise RuntimeError('Raw phase corruption missed')
        result['rtl_negative'].append(dict(active=active,tag='ACCUMULATOR',returncode=rc))
    result['rtl_verified']=True
    return artifacts


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify-rtl',action='store_true');parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/pfb_width_sweep/results.json');args=parser.parse_args()
    args.output=args.output.resolve()
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'));result={}
    try:
        result=report();check_acceptance(result);artifacts=verify_rtl(result,args.output.parent/'equivalence') if args.verify_rtl else []
        check_acceptance(result);write_json(args.output,dict(finish(evidence,artifacts),status='PASS',**result))
    except Exception as exc:
        write_json(args.output,dict(evidence,status='FAIL',error=str(exc),result=result));raise
    print('PASS PFB phase widths; RTL verified='+str(result['rtl_verified']))

if __name__=='__main__':main()
