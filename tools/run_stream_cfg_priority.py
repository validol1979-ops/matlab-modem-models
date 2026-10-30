#!/usr/bin/env python3
"""Направленные проверки приоритета cfg: Questa или Verilator, обе полярности reset."""
import argparse
from pathlib import Path
import re
import subprocess
import sys
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_unoptimized
from run_rtl import SOURCES,execute

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'
MEM=ROOT/'rtl/common/mem'
BLOCKS=('beam','pfb','omlsa')


def stimulus(path):
    sys.path.insert(0,str(ROOT/'common/python'))
    from omlsa_fixed import enhance
    inputs=[];outputs=[]
    for length,nn in ((33,1),(129,16)):
        wave=[((i*977)%16001-8000,(i*619)%12001-6000) for i in range(length)]
        result=enhance(wave,32,8,nn,58982/65536)
        if len(result)!=length:raise RuntimeError('Incomplete OM-LSA reference')
        inputs.extend((*v,int(i==length-1)) for i,v in enumerate(wave))
        outputs.extend((*v,int(i==length-1)) for i,v in enumerate(result))
    rows=[f'{len(inputs)} {len(outputs)}']+[' '.join(map(str,row)) for row in inputs+outputs]
    path.write_text('\n'.join(rows)+'\n')


def check_run(rc,text,marker,negative=False,simulator='questa'):
    if negative:
        valid=(rc==13 if simulator=='questa' else rc!=0)
        detail=re.search(r'\*\* Fatal:.*\[NUMERIC\]',text) if simulator=='questa' else '[NUMERIC]' in text
        valid=valid and detail and marker not in text
    else:
        valid=rc==0 and marker in text and not re.search(r'\*\* (?:Error|Fatal)|%Error|\[(?:NUMERIC|CONFIG_ARB|TIMEOUT|VECTOR)\]',text)
    if not valid:raise RuntimeError(f'Unexpected cfg regression rc={rc}:\n{text[-6000:]}')


def run_group(block,output,artifacts,simulator='questa'):
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    specs=([(0,'alamouti'),(1,'beamform')] if block=='beam' else [(2,'pfb')] if block=='pfb' else [(0,'collision'),(1,'mid_signal')])
    top='omlsa_cfg_priority_tb' if block=='omlsa' else 'stream_cfg_priority_tb'
    tb=ROOT/f'rtl/tb/{top}.sv';records=[]
    data=output/'omlsa.txt'
    if block=='omlsa':stimulus(data);artifacts.append(data)
    bindir=questa_paths()[0] if simulator=='questa' else None
    for kind,name in specs:
        for active in (1,0):
            work=output/f'{name}_reset{active}';work.mkdir(parents=True,exist_ok=True)
            params=dict(RESET_ACTIVE=active,**({'MID_SIGNAL':kind} if block=='omlsa' else {'FAMILY':kind}))
            marker=f'PASS OMLSA CFG priority mid={kind} inputs=162 outputs=162 cfg={2 if kind else 3}' if block=='omlsa' else f'PASS STREAM CFG priority family={kind}'
            if simulator=='questa':
                if not(work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
                execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',*SOURCES,tb],work,work/'compile.log')
                positive,negative_script=work/'probe.do',work/'negative.do'
                positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
                negative_script.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                artifacts.extend([positive,negative_script])
                command=[bindir/'vsim','-64','-c','-quiet',f'work.{top}',*[f'-g{k}={v}' for k,v in params.items()],f'-gMEM_DIR={MEM}']
            else:
                execute(['verilator','--binary','--timing','-j','4','-Wno-TIMESCALEMOD','--top-module',top,
                         '--Mdir',work/'obj',f'-I{PILOT}',*[f'-G{k}={v}' for k,v in params.items()],
                         f'-GMEM_DIR="{MEM}"',*SOURCES,tb],ROOT,work/'compile.log')
                command=[work/'obj'/f'V{top}']
            artifacts.append(work/'compile.log')
            if block=='omlsa':command.append(f'+DATA={data}')
            for negative in (False,True):
                log=work/('negative.log' if negative else 'simulation.log')
                options=['+INJECT_MISMATCH'] if negative else []
                if simulator=='questa':options.extend(['-do',(negative_script if negative else positive).name])
                result=subprocess.run(list(map(str,[*command,*options])),
                                      cwd=work,capture_output=True,text=True,timeout=120)
                text=result.stdout+result.stderr;log.write_text(text);artifacts.append(log)
                check_run(result.returncode,text,marker,negative,simulator)
                records.append(dict(block=block,case=name,reset_active=active,negative=negative,returncode=result.returncode))
            print(f'PASS CFG priority {name} reset={active} ({simulator}, negative control detected)',flush=True)
    return records


def main():
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--blocks',nargs='+',choices=BLOCKS,default=BLOCKS)
    parser.add_argument('--simulator',choices=('questa','verilator'),default='questa')
    parser.add_argument('--output-dir',type=Path,help='new isolated output directory')
    args=parser.parse_args();output=(args.output_dir or ROOT/'build/rtl/stream_cfg_priority').resolve()
    output.mkdir(parents=True,exist_ok=args.output_dir is None)
    evidence=begin();target=output/'results.json';artifacts=[];records=[]
    write_json(target,dict(evidence,status='RUNNING'))
    try:
        for block in dict.fromkeys(args.blocks):records.extend(run_group(block,output/block,artifacts,args.simulator))
        write_json(target,dict(status='PASS',simulator=args.simulator,records=records,**finish(evidence,artifacts)))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=str(exc),records=records));raise
    print(f'PASS STREAM CFG priority ({args.simulator})')


if __name__=='__main__':main()
