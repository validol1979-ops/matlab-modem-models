#!/usr/bin/env python3
"""Independent directed Costas configuration/frame boundaries, plus fixed outputs."""
import argparse
from pathlib import Path
import re
import subprocess
import sys

from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_unoptimized
from run_rtl import SOURCES
sys.path.insert(0,str(ROOT/'common/python'))
from sync_fixed import costas,costas_gains


def main(argv=None):
    require_unoptimized();parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expect-rejection',action='store_true')
    parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/costas_protocol')
    args=parser.parse_args(argv);output=args.output.resolve();output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/'results.json';write_json(target,dict(evidence,status='RUNNING'));artifacts=[];records=[]
    try:
        gains=[costas_gains(.08,.001),costas_gains(.02,.0001)]
        samples=[(20000,11000),(-24000,17000),(9000,-20000),(-15000,-8000),(26000,3000)]
        data_files={}
        for mode in range(6):
            data=output/f'probe{mode}.txt';lines=[' '.join(map(str,(*gains[0],*gains[1])))]
            if mode==5:
                for x in samples*2:
                    values,phases=costas([x],gains[0]);lines.append(' '.join(map(str,(*x,*values[0],phases[0],1))))
            else:
                for g in (gains if mode<4 else [gains[0]]*2):
                    values,phases=costas(samples,g)
                    lines.extend(' '.join(map(str,(*x,*y,p,int(i==4)))) for i,(x,y,p) in enumerate(zip(samples,values,phases)))
            data.write_text('\n'.join(lines)+'\n');artifacts.append(data);data_files[mode]=data
        bindir,_=questa_paths();work=output/'workdir';work.mkdir(exist_ok=True)
        def run(command,log):
            result=subprocess.run(list(map(str,command)),cwd=work,capture_output=True,text=True,timeout=90)
            text=result.stdout+result.stderr;log.write_text(text);artifacts.append(log);return result.returncode,text
        if not(work/'work').is_dir():
            rc,text=run([bindir/'vlib','work'],work/'vlib.log')
            if rc:raise RuntimeError(f'vlib failed{rc}: {text[-3000:]}')
        rc,text=run([bindir/'vlog','-64','-sv',f'+incdir+{ROOT}/rtl/modems/bpsk_costas_2008_08_25',*SOURCES,
                     ROOT/'rtl/tb/axis_check.sv',ROOT/'rtl/tb/costas_protocol_tb.sv'],work/'compile.log')
        if rc or re.search(r'\*\* (?:Error|Fatal)',text):raise RuntimeError(text[-4000:])
        script=work/'probe.do';script.write_text('onfinish stop\nonerror {quit -code 13}\n'+
            ('onbreak {quit -code 13}\n' if args.expect_rejection else '')+'run -all\nquit -code 0\n');artifacts.append(script)
        for mode in range(4 if args.expect_rejection else 6):
            for active in (1,0):
                rc,text=run([bindir/'vsim','-64','-c','-quiet','work.costas_protocol_tb',f'-gMODE={mode}',f'-gRESET_ACTIVE={active}',
                    f'-gTABLE_DIR={ROOT}/rtl/modems/bpsk_costas_2008_08_25/tables',f'+DATA={data_files[mode]}','-do',script.name],work/f'mode{mode}_reset{active}.log')
                marker=re.search(r'PASS COSTAS PROTOCOL mode=(\d+) inputs=(\d+) outputs=(\d+) cfg=(\d+)',text)
                if args.expect_rejection:
                    if not rc or not re.search(r'\*\* Fatal:.*\[PROTOCOL\]',text) or marker:raise RuntimeError(f'Missing original protocol failure mode{mode}reset{active}: {text[-4000:]}')
                elif rc or not marker or tuple(map(int,marker.groups()))!=(mode,10,10,3 if mode==1 else 2 if mode<4 else 1) or re.search(r'\*\* (?:Fatal|Error)',text):
                    raise RuntimeError(f'Probe failed mode{mode}reset{active}: {text[-4000:]}')
                records.append(dict(mode=mode,reset_active=active,returncode=rc,expected_rejection=args.expect_rejection))
                print(f'PASS COSTAS PROTOCOL mode{mode} reset{active} rc={rc}',flush=True)
        write_json(target,dict(finish(evidence,artifacts),status='PASS',records=records,expected_rejection=args.expect_rejection,
            scope='Pin-only cfg/data exclusion and transaction fences; paused frame, concurrent idle config/data, pending boundary config, blocked final output, continuously offered fast frame boundary, ten single-sample frames. Numeric outputs and used phases from unchanged sync_fixed; every frame starts phase0.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}',records=records));raise
    return records


if __name__=='__main__':main()
