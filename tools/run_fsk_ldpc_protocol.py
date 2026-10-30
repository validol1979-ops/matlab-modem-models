#!/usr/bin/env python3
"""Bounded pin-only streaming-config boundary proofs for FSK and LDPC/GF2."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_unoptimized,require_pass
from run_rtl import SOURCES
sys.path.insert(0,str(ROOT/'common/python'))
from fsk_fixed import transmit,receive
from ldpc_fixed import encode,decode


def cases(before=False,block=None):
    rows=[]
    for kind,name in enumerate(('fsk_tx','fsk_rx','gf2','ldpc')):
        for mode,suffix in ((0,'initial'),(1,'first_word'),(4,'open_pause'),(5,'blocked_output'),(6,'invalid_recovery'),(7,'last_word')):
            rows.append(dict(name=f'{name}_{suffix}',kind=kind,mode=mode,
                             before_failure=mode in (1,6) or (mode==4 and kind<2)))
        if kind<3:
            for mode in (2,3):
                rows.append(dict(name=f'{name}_singleton{mode}',kind=kind,mode=mode,
                                 before_failure=(mode==2 and kind<2) or (mode==3 and kind==2)))
        if not before:rows.append(dict(name=f'{name}_new_frame_blocked_tail',kind=kind,mode=8,before_failure=False))
        if not before and kind==3:
            rows += [dict(name=f'ldpc_badrow_weight{weight}_recovery',kind=kind,mode=9 if weight==1 else 10,before_failure=True) for weight in (1,0)]
            rows.append(dict(name='ldpc_edgeoverflow_recovery',kind=kind,mode=11,before_failure=True))
    return [s for s in rows if block is None or (s['kind']<2)==(block=='fsk')]


def healthy_report_artifacts(report,block,root=ROOT):
    if block not in ('fsk','ldpc'):raise ValueError('Parent protocol group required')
    expected_count={'fsk':36,'ldpc':38}[block]
    expected={(case['name'],active):case for case in cases(False,block) for active in (1,0)}
    records=report.get('records') if isinstance(report,dict) else None
    if (not isinstance(report,dict) or report.get('before') is not False or not isinstance(records,list)
            or len(records)!=expected_count or len(expected)!=expected_count):raise RuntimeError('Incomplete healthy protocol suite')
    seen=set()
    for record in records:
        if (not isinstance(record,dict) or record.get('expected_failure') is not False
                or type(record.get('returncode')) is not int or record['returncode']!=0
                or type(record.get('reset_active')) is not int):raise RuntimeError('Unhealthy protocol record')
        key=(record.get('name'),record['reset_active'])
        if key not in expected or key in seen:raise RuntimeError('Duplicate or unexpected case/reset')
        if any(type(record.get(k)) is not type(v) or record[k]!=v for k,v in expected[key].items()):raise RuntimeError('Incorrect protocol case parameters')
        if type(record.get('held_tail_inputs')) is not int or record['held_tail_inputs']<0:raise RuntimeError('Missing blocked-tail measurement')
        if record['mode']==8 and record['kind']>0 and not record['held_tail_inputs']:raise RuntimeError('Missing accepted new input under old blocked output')
        if type(record.get('bad_config_inputs')) is not int or record['bad_config_inputs']!=0:raise RuntimeError('Input was accepted with illegal active configuration')
        seen.add(key)
    if seen!=set(expected) or not isinstance(report.get('artifact_hashes'),dict) or not report['artifact_hashes']:raise RuntimeError('Incomplete coverage/artifacts')
    require_pass(report,root)
    return [Path(root)/name for name in report['artifact_hashes']]


def matrix_words(matrix,kind):
    m,n=len(matrix),len(matrix[0]);flat=[int(b) for row in matrix for b in row]
    return [(int(i==len(flat)-1),b,m,n,1 if kind==3 else 0,2 if kind==3 else 0,256 if kind==3 else 0,0) for i,b in enumerate(flat)]


def stimulus(path,spec):
    kind,mode=spec['kind'],spec['mode'];use_a=mode in (4,5,8)
    if kind<2:
        a=[0,1<<30];b=[1<<29,1<<31];an=bn=3
        if mode in (2,3):
            b=[(1<<30) if mode==2 or kind==1 else 0]
            if kind==1 and mode==2:bn=1
        ca=[(int(i==len(a)-1),v,an,0,0,0,0,0) for i,v in enumerate(a)]
        cb=[(int(i==len(b)-1),v,bn,0,0,0,0,0) for i,v in enumerate(b)]
        table,n=(a,an) if use_a else (b,bn)
        labels=[1,0] if mode in (1,4) else [1 if use_a else 0]
        if kind==0:
            source=[(v,0) for v in labels];output=transmit(labels,n,table);pause=0
        else:
            source=transmit(labels,n,table);output=[(v,0) for v in receive(source,n,table)];pause=n-1
    elif kind==2:
        a,b=[[1,0]],[[1,1]]
        if mode==2:a,b=[[0]],[[1]]
        if mode==3:b=[[1]]
        ca,cb=matrix_words(a,kind),matrix_words(b,kind);matrix=a if use_a else b
        bits=[1]*len(matrix[0]);source=[(v,0) for v in bits];output=[(v,0) for v in encode(bits,matrix)];pause=0
    else:
        a,b=[[1,1,0]],[[1,0,1]];ca,cb=matrix_words(a,kind),matrix_words(b,kind);matrix=a if use_a else b
        llr=[600,100,-200];source=[(v,0) for v in llr];bits,posterior,_=decode(llr,matrix,2,1)
        output=list(zip(bits,posterior));pause=0
    source_last=[int(i==len(source)-1) for i in range(len(source))]
    output_last=[int(i==len(output)-1) for i in range(len(output))]
    if mode==8:
        pause=len(source)
        if kind==0:new_source=[(0,0)];new_output=transmit([0],bn,b)
        elif kind==1:
            new_source=transmit([0],bn,b);new_output=[(v,0) for v in receive(new_source,bn,b)]
        elif kind==2:
            bits=[1]*len(b[0]);new_source=[(v,0) for v in bits];new_output=[(v,0) for v in encode(bits,b)]
        else:
            new_source=[(v,0) for v in llr];bits,posterior,_=decode(llr,b,2,1);new_output=list(zip(bits,posterior))
        source += new_source;output += new_output
        source_last += [int(i==len(new_source)-1) for i in range(len(new_source))]
        output_last += [int(i==len(new_output)-1) for i in range(len(new_output))]
    lines=[f'{len(ca)} {len(cb)} {len(source)} {len(output)}']
    lines += [' '.join(map(str,row)) for row in ca+cb]
    lines += [' '.join(map(str,(*z,last))) for z,last in zip(source,source_last)]
    lines += [' '.join(map(str,(*z,last))) for z,last in zip(output,output_last)]
    path.write_text('\n'.join(lines)+'\n');return len(source),len(output),len(ca),len(cb),pause


def main(argv=None):
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before',action='store_true');parser.add_argument('--block',choices=['fsk','ldpc'])
    parser.add_argument('--case',choices=[case['name'] for case in cases(False)])
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/fsk_ldpc_protocol')
    args=parser.parse_args(argv);output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/'results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records=[]
    try:
        bindir,_=questa_paths();work=output/'workdir';work.mkdir(exist_ok=True)
        def run(command,log):
            result=subprocess.run(list(map(str,command)),cwd=work,capture_output=True,text=True,timeout=90)
            text=result.stdout+result.stderr;log.write_text(text);artifacts.append(log);return result.returncode,text
        if not(work/'work').is_dir():
            rc,text=run([bindir/'vlib','work'],work/'vlib.log')
            if rc:raise RuntimeError(f'vlib{rc}: {text[-2000:]}')
        rc,text=run([bindir/'vlog','-64','-sv',f'+incdir+{ROOT}/rtl/modems/bpsk_costas_2008_08_25',*SOURCES,ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/fsk_ldpc_protocol_tb.sv'],work/'compile.log')
        if rc or re.search(r'\*\* (?:Error|Fatal)',text):raise RuntimeError(text[-5000:])
        positive,negative=work/'probe.do',work/'negative.do'
        positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n');artifacts += [positive,negative]
        selected=cases(False if args.case else args.before,args.block)
        if args.case:selected=[case for case in selected if case['name']==args.case]
        if not selected:raise RuntimeError('Empty protocol coverage selection')
        for spec in selected:
            data=output/(spec['name']+'.txt');ni,no,na,nb,pause=stimulus(data,spec);artifacts.append(data)
            expected_failure=args.before and spec['before_failure']
            for active in (1,0):
                identifier=f'{spec["name"]}_reset{active}';print(f'RUN {identifier}',flush=True)
                rc,text=run([bindir/'vsim','-64','-c','-quiet','work.fsk_ldpc_protocol_tb',f'-gKIND={spec["kind"]}',f'-gMODE={spec["mode"]}',
                    f'-gPAUSE_AFTER={pause}',f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={ROOT}/rtl/modems/bpsk_costas_2008_08_25/tables',
                    f'-gPHI_FILE={ROOT}/rtl/common/mem/ldpc_phi.mem',f'-gINV_FILE={ROOT}/rtl/common/mem/ldpc_inv.mem',f'+DATA={data}',
                    '-do',(negative if expected_failure else positive).name],work/(identifier+'.log'))
                marker=re.search(r'PASS FSK LDPC PROTOCOL kind=(\d+) mode=(\d+) inputs=(\d+) outputs=(\d+) cfg=(\d+) held_tail_inputs=(\d+) bad_config_inputs=(\d+)',text)
                if expected_failure:
                    if not rc or not re.search(r'\*\* Fatal:.*\[(?:NUMERIC|PROTOCOL)\]',text) or marker:raise RuntimeError(f'Missing original failure {identifier}: {text[-5000:]}')
                elif rc or not marker or tuple(map(int,marker.groups()[:5]))!=(spec['kind'],spec['mode'],ni,no,nb if spec['mode']==0 else na+nb+(9 if spec['mode']==11 else nb) if spec['mode']>=9 else na+nb+(spec['mode']==6)) or re.search(r'\*\* (?:Error|Fatal)',text):
                    raise RuntimeError(f'Probe failed {identifier}: {text[-5000:]}')
                records.append(dict(spec,reset_active=active,returncode=rc,expected_failure=expected_failure,held_tail_inputs=int(marker.group(6)) if marker else 0,bad_config_inputs=int(marker.group(7)) if marker else 0));print(f'PASS {identifier} rc={rc}',flush=True)
        write_json(target,dict(finish(evidence,artifacts),status='PASS',before=args.before,records=records,
            scope='Pin-only held cfg/data offers. Initial configured0 vs reconfiguration configured1; first vs last config word; legal singleton, paused open frames and stored blocked output coherence; invalid dimensions/n recovery. Outputs against unchanged fsk_fixed/ldpc_fixed. No synthesis or clock feasibility claim.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}',records=records));raise
    return records


if __name__=='__main__':main()
