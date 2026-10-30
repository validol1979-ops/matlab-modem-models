#!/usr/bin/env python3
"""Check signed 72-bit clamp observations, warm-up/stall gating and negative controls."""
import re
import subprocess
from regression_evidence import ROOT,begin,finish,questa_paths,write_json
from run_rtl import execute


def main():
    if not __debug__:raise RuntimeError('Verification requires Python assertions enabled')
    output=ROOT/'build/rtl/sat_event';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/'all_results.json';write_json(target,dict(status='RUNNING',**evidence))
    artifacts=[];records={};bindir,_=questa_paths()
    for width in (18,25):
        for active in (1,0):
            work=output/f'w{width}_reset{active}';work.mkdir(parents=True,exist_ok=True)
            if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
            expected=work/'expected.txt';expected.write_text('2\n5 2 0\n5 0 2\n');artifacts.append(expected)
            execute([bindir/'vlog','-64','-sv',ROOT/'rtl/tb/sat_event_check.sv',ROOT/'rtl/tb/sat_event_tb.sv'],work,work/'compile.log')
            artifacts.append(work/'compile.log')
            common=[bindir/'vsim','-64','-c','-quiet','work.sat_event_tb',f'-gRESET_ACTIVE={active}',
                    f'-gOUT_WIDTH={width}',f'+VECTORS={work}']
            text=execute([*common,'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,work/'positive.log')
            if ('PASS SATURATION unit: 10 evaluations, 4 events' not in text or 'PASS SAT EVENT UNIT' not in text
                    or re.search(r'\*\* (?:Error|Fatal)',text)):raise RuntimeError('Saturation checker positive control failed')
            artifacts.append(work/'positive.log')
            for name,flag in [('events','+INJECT_SAT_MISMATCH'),('evaluations','+INJECT_SAT_EVAL_MISMATCH'),('unknown','+INJECT_SAT_X')]:
                bad=subprocess.run([str(x) for x in [*common,flag,'-do','run -all; quit -code 0']],cwd=work,capture_output=True,text=True,timeout=60)
                text=bad.stdout+bad.stderr;log=work/f'negative_{name}.log';log.write_text(text);artifacts.append(log)
                if not re.search(r'\*\* Fatal:.*\[SATURATION\]',text) or 'PASS SAT EVENT UNIT' in text:
                    raise RuntimeError(f'Saturation checker negative {name} not detected')
            records[f'w{width}_reset{active}']=dict(status='PASS',evaluations=10,events=4,negative_controls=3)
    write_json(target,dict(status='PASS',records=records,**finish(evidence,artifacts)))
    print('PASS SAT EVENT CHECKER: 4 positive runs, 12 rejected violations')


if __name__=='__main__':main()
