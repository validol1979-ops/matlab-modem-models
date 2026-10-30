#!/usr/bin/env python3
"""Pin-only notch/Kalman/Gardner configuration boundaries and fixed numeric traces."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_unoptimized,require_pass
from run_rtl import SOURCES
sys.path.insert(0,str(ROOT/'common/python'))
from oset_fixed import notch,notch_coefficients,kalman,kalman_parameters
from sync_fixed import timing,timing_gains


def cases(before=False,block=None):
    selected=[dict(name='notch_coherent',kind=0,mode=0,offset=0,before_failure=False),
              dict(name='notch_open_pause',kind=0,mode=2,offset=0,before_failure=False),
              dict(name='kalman_concurrent',kind=1,mode=0,offset=400,before_failure=True),
              dict(name='kalman_invalid_recovery',kind=1,mode=1,offset=400,before_failure=True),
              dict(name='kalman_open_pause',kind=1,mode=2,offset=400,before_failure=False),
              dict(name='kalman_reconfig_fifo',kind=1,mode=3,offset=400,before_failure=True),
              dict(name='gardner_single_concurrent',kind=2,mode=0,offset=0,before_failure=True),
              dict(name='gardner_invalid_sps_recovery',kind=2,mode=1,offset=0,before_failure=True),
              dict(name='gardner_open_pause',kind=2,mode=2,offset=0,before_failure=False),
              dict(name='gardner_zero_count_recovery',kind=2,mode=4,offset=0,before_failure=True)]
    if not before:
        selected += [dict(name=f'kalman_reconfig_offset{offset}',kind=1,mode=3,offset=offset,before_failure=False)
                     for offset in (0,1,35,69,70,71)]
    allowed={'notch':{0},'kalman':{1},'gardner':{2},'oset':{0,1}}
    return [s for s in selected if block is None or s['kind'] in allowed[block]]


def healthy_report_artifacts(report,block,root=ROOT):
    """Accept only the complete healthy directed suite, then verify every artifact."""
    if block not in ('oset','gardner'):
        raise ValueError('Parent protocol gate must select oset or gardner')
    expected_count={'oset':24,'gardner':8}[block]
    selected=cases(False,block)
    expected={(case['name'],active):case for case in selected for active in (1,0)}
    records=report.get('records') if isinstance(report,dict) else None
    if (not isinstance(report,dict) or report.get('before') is not False
            or not isinstance(records,list) or len(records)!=expected_count
            or len(expected)!=expected_count):
        raise RuntimeError(f'Incomplete healthy {block} protocol gate')
    seen=set()
    for record in records:
        if (not isinstance(record,dict) or record.get('expected_failure') is not False
                or type(record.get('returncode')) is not int or record['returncode']!=0
                or type(record.get('reset_active')) is not int):
            raise RuntimeError(f'Unhealthy {block} protocol record')
        key=(record.get('name'),record['reset_active'])
        if key not in expected or key in seen:
            raise RuntimeError(f'Duplicate or unexpected {block} case/reset')
        case=expected[key]
        if any(type(record.get(field)) is not type(value) or record[field]!=value
               for field,value in case.items()):
            raise RuntimeError(f'Incorrect {block} protocol case parameters')
        seen.add(key)
    if seen!=set(expected) or not isinstance(report.get('artifact_hashes'),dict) or not report['artifact_hashes']:
        raise RuntimeError(f'Incomplete {block} protocol coverage/artifacts')
    require_pass(report,root)
    return [Path(root)/name for name in report['artifact_hashes']]


def stimulus(path,spec):
    x=[(21000,9000),(-18000,15000),(7000,-19000)]
    kind,mode=spec['kind'],spec['mode']
    if kind==0:
        a,b=notch_coefficients(.23,.94),notch_coefficients(.1,.5)
        chosen=a if mode==2 else b;y=notch(x,chosen);tags=[0]*len(y)
    elif kind==1:
        a,b=kalman_parameters(.0005,.25,1),kalman_parameters(.01,1,0)
        chosen=a if mode==2 else b;y=kalman(x,chosen);tags=[0]*len(y)
    else:
        a=(2,2,*timing_gains(0,0,0));b=(2,1 if mode==0 else 2,*timing_gains(.25,0,0))
        if mode==0:x=x[:1]
        chosen=a if mode==2 else b;y,tags=timing(x,chosen[0],chosen[1],chosen[2:])
    lines=[' '.join(map(str,(*a,*([0]*(5-len(a)))))), ' '.join(map(str,(*b,*([0]*(5-len(b)))))),f'{len(x)} {len(y)}']
    lines += [' '.join(map(str,(*z,int(i==len(x)-1)))) for i,z in enumerate(x)]
    lines += [' '.join(map(str,(*z,p,int(i==len(y)-1)))) for i,(z,p) in enumerate(zip(y,tags))]
    path.write_text('\n'.join(lines)+'\n')
    return len(x),len(y)


def main(argv=None):
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',action='store_true',help='Require confirmed original failures and coherent controls')
    parser.add_argument('--block',choices=['notch','kalman','gardner','oset'])
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/oset_gardner_protocol')
    args=parser.parse_args(argv);output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    target=output/'results.json';evidence=begin();write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records=[]
    try:
        bindir,_=questa_paths();work=output/'workdir';work.mkdir(exist_ok=True)
        def run(command,log):
            result=subprocess.run(list(map(str,command)),cwd=work,capture_output=True,text=True,timeout=90)
            text=result.stdout+result.stderr;log.write_text(text);artifacts.append(log);return result.returncode,text
        if not(work/'work').is_dir():
            rc,text=run([bindir/'vlib','work'],work/'vlib.log')
            if rc:raise RuntimeError(f'vlib{rc}: {text[-2000:]}')
        rc,text=run([bindir/'vlog','-64','-sv',f'+incdir+{ROOT}/rtl/modems/bpsk_costas_2008_08_25',*SOURCES,
                     ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/oset_gardner_protocol_tb.sv'],work/'compile.log')
        if rc or re.search(r'\*\* (?:Error|Fatal)',text):raise RuntimeError(text[-4000:])
        normal,negative=work/'probe.do',work/'negative_probe.do'
        normal.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
        artifacts += [normal,negative]
        selected=cases(args.before,args.block)
        for spec in selected:
            data=output/(spec['name']+'.txt');ni,no=stimulus(data,spec);artifacts.append(data)
            expected_failure=args.before and spec['before_failure']
            for active in (1,0):
                identifier=f'{spec["name"]}_reset{active}';print(f'RUN {identifier}',flush=True)
                rc,text=run([bindir/'vsim','-64','-c','-quiet','work.oset_gardner_protocol_tb',f'-gKIND={spec["kind"]}',f'-gMODE={spec["mode"]}',
                             f'-gOFFSET={spec["offset"]}',f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={ROOT}/rtl/modems/bpsk_costas_2008_08_25/tables',
                             f'+DATA={data}','-do',(negative if expected_failure else normal).name],work/(identifier+'.log'))
                marker=re.search(r'PASS CONFIG BOUNDARY kind=(\d+) mode=(\d+) inputs=(\d+) outputs=(\d+) cfg=(\d+)',text)
                if expected_failure:
                    if not rc or not re.search(r'\*\* Fatal:.*\[(?:NUMERIC|PROTOCOL)\]',text) or marker:raise RuntimeError(f'Missing original failure: {identifier}\n{text[-4000:]}')
                elif rc or not marker or tuple(map(int,marker.groups()))!=(spec['kind'],spec['mode'],ni,no,3 if spec['mode'] in (1,4) else 2) or re.search(r'\*\* (?:Error|Fatal)',text):
                    raise RuntimeError(f'Probe failure: {identifier}\n{text[-4000:]}')
                records.append(dict(spec,reset_active=active,returncode=rc,expected_failure=expected_failure))
                print(f'PASS {identifier} rc={rc}',flush=True)
        if len(records)!=2*len(selected):raise RuntimeError('Incomplete coverage')
        write_json(target,dict(finish(evidence,artifacts),status='PASS',records=records,before=args.before,
            scope='Pin-only independent-interface valid offers held until handshake; notch coherent concurrent acceptance control; open-frame pauses; Gardner single-LAST reconfiguration, invalid SPS/count recovery; Kalman idle FIFO and busy-divider reconfiguration. Independent unchanged fixed models generate expected tuples; no hierarchical timing assumptions. Sticky error remains set after invalid R/SPS until reset; zero-count configured0 is tested without inventing an error flag.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}',records=records));raise
    return records


if __name__=='__main__':main()
