#!/usr/bin/env python3
"""Full FFT UVM on every existing geometry, width, direction and boundary plan."""
import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

from regression_evidence import ROOT, begin, finish, write_json, questa_paths, require_unoptimized
from run_rtl import SOURCES
from run_fft import CASES as NATIVE_CASES, BOUNDARY, case_name, twiddle
from fft_cases import vectors, boundary_vectors

CASES={case_name(*row):row for row in NATIVE_CASES}
SCENARIOS=('stream','gaps','stalled','midreset','outreset','badlast')
CONTROLS={
    'numeric':('NUMERIC','INJECT_MISMATCH','stream'),
    's_valid_x':('PROTOCOL','INJECT_S_VALID_X','stream'),
    's_ready_x':('PROTOCOL','INJECT_S_READY_X','stream'),
    'm_valid_x':('PROTOCOL','INJECT_M_VALID_X','stream'),
    'm_ready_x':('PROTOCOL','INJECT_M_READY_X','stream'),
    'input_x':('NUMERIC','INJECT_INPUT_X','stream'),
    'output_x':('NUMERIC','INJECT_OUTPUT_X','stream'),
    'direction':('NUMERIC','INJECT_DIRECTION','stream'),
    'last':('NUMERIC','INJECT_LAST','stream'),
    'held_data':('STALL','INJECT_HELD_DATA','stalled'),
    'error_clear':('ERROR','INJECT_ERROR_CLEAR','badlast'),
}
SUMMARY=(r'UVM FFT checked=(\d+) inputs=(\d+) frames=(\d+) discarded=(\d+) discarded_inputs=(\d+) '
         r'expected=(\d+) expected_inputs=(\d+) resets=(\d+) before_reset=(\d+) terminal_resets=(\d+) bad_completed=(\d+) modes=(\d+)')
HANDSHAKES=(r'UVM FFT HANDSHAKES input=(\d+) output=(\d+) input_stalls=(\d+) output_stalls=(\d+) gaps=(\d+) pending_resets=(\d+) error_cycles=(\d+)')


def prepare_vectors(folder,case,gaps=False):
    folder=Path(folder)
    log2n,frames,in_width,width=CASES[case]
    model=(boundary_vectors(folder,gaps=gaps) if CASES[case]==BOUNDARY else
           vectors(folder,log2n,frames=frames,gaps=gaps,in_width=in_width,width=width))
    n=1<<log2n
    inputs=[list(map(int,line.split())) for line in (folder/'in.txt').read_text().splitlines()[1:]]
    modes=[inputs[f*n][2] for f in range(frames)]
    if len(inputs)!=n*frames or model['outputs']!=n*frames:
        raise RuntimeError('FFT production vectors differ from independent N*frames geometry')
    model.update(case=case,frame_modes=modes,mode_mask=sum(1<<mode for mode in set(modes)))
    return model


def parse_report(text,model,scenario,active,returncode=0):
    if scenario not in SCENARIOS:
        raise RuntimeError('Unsupported FFT UVM scenario')
    summaries=re.findall(SUMMARY,text);handshakes=re.findall(HANDSHAKES,text)
    if (returncode or len(summaries)!=1 or len(handshakes)!=1 or
            re.search(r'UVM_(?:FATAL|ERROR)\s*:\s*[1-9]|UVM_(?:FATAL|ERROR)[^\n]*\[|\*\* (?:Error|Fatal)',text)):
        raise RuntimeError('Complete successful FFT UVM report required')
    fields=('checked','input_checked','frames','discarded_outputs','discarded_inputs','expected_outputs','expected_inputs',
            'resets','before_reset','terminal_resets','bad_completed','mode_mask')
    result=dict(zip(fields,map(int,summaries[0])))
    result.update(dict(zip(('input_handshakes','output_handshakes','input_stalls','output_stalls','input_gaps','pending_resets','error_cycles'),map(int,handshakes[0]))))
    n=1<<model['log2n'];normal=n*model['frames']
    if (model['samples']!=normal or model['outputs']!=normal or len(model['frame_modes'])!=model['frames']
            or model['mode_mask']!=sum(1<<mode for mode in set(model['frame_modes']))):
        raise RuntimeError('FFT immutable geometry/direction metadata mismatch')
    rows=[tuple(map(int,row)) for row in re.findall(r'UVM FFT FRAME id=(\d+) samples=(\d+) inverse=(\d+)',text)]
    if rows!=[(f,n,mode) for f,mode in enumerate(model['frame_modes'])] or result['frames']!=model['frames'] or result['mode_mask']!=model['mode_mask']:
        raise RuntimeError('FFT completed frame/direction coverage mismatch')
    widths=re.findall(r'UVM FFT WIDTH log2n=(\d+) input=(\d+) output=(\d+)',text)
    if len(widths)!=1 or tuple(map(int,widths[0]))!=(model['log2n'],model['in_width'],model['width']):
        raise RuntimeError('FFT physical width/size coverage mismatch')
    mid,out,bad=scenario=='midreset',scenario=='outreset',scenario=='badlast'
    reset=mid or out or bad
    extra_inputs=n//2 if mid else n if out or bad else 0
    extra_outputs=n-1 if out else n if bad else 0
    discarded_in=n//2 if mid else 0
    discarded_out=n if mid else 1 if out else 0
    actual=(result['input_checked'],result['checked'],result['discarded_inputs'],result['discarded_outputs'],
            result['expected_inputs'],result['expected_outputs'],result['resets'],result['before_reset'],
            result['terminal_resets'],result['bad_completed'],result['pending_resets'])
    expected=(normal+extra_inputs,normal+extra_outputs,discarded_in,discarded_out,normal+n*int(reset),normal+n*int(reset),
              1+int(reset),n-1 if out else 0,int(out),int(bad),int(out))
    if actual!=expected or result['input_handshakes']!=result['input_checked'] or result['output_handshakes']!=result['checked']:
        raise RuntimeError('FFT actual handshake/reset/queue conservation mismatch')
    if result['input_checked']+discarded_in!=result['expected_inputs'] or result['checked']+discarded_out!=result['expected_outputs']:
        raise RuntimeError('FFT expected queues did not drain')
    if scenario=='stream' and result['input_stalls']:
        raise RuntimeError('FFT continuous stream failed one accepted sample per cycle')
    if scenario=='gaps' and result['input_gaps']<1:
        raise RuntimeError('FFT source gaps missing')
    if scenario in ('stalled','outreset','badlast') and result['output_stalls']<1:
        raise RuntimeError('FFT output backpressure missing')
    if (bad and result['error_cycles']<5) or (not bad and result['error_cycles']):
        raise RuntimeError('FFT malformed TLAST sticky error/reset recovery missing')
    result.update(case=model['case'],scenario=scenario,reset_active=active,log2n=model['log2n'],
                  in_width=model['in_width'],width=model['width'],per_frame=[dict(frame=f,samples=k,inverse=mode) for f,k,mode in rows])
    return result


def verify_negative(text,returncode,tag):
    if (not returncode or re.search(SUMMARY,text) or not re.search(r'UVM_FATAL[^\n]*\['+tag+r'\]',text)
            or not re.search(r'UVM_FATAL\s*:\s*[1-9]',text)):
        raise RuntimeError('FFT UVM negative control not rejected: '+tag)


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=('python','hdl','all'),default='all')
    parser.add_argument('--case',choices=('all',*CASES),default='all');args=parser.parse_args();require_unoptimized()
    output=ROOT/'build/rtl/fft_uvm';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/(('' if args.case=='all' else args.case+'_')+args.suite+'_results.json')
    artifacts,records=[],{};write_json(target,dict(evidence,status='RUNNING'))
    try:
        def run(command,work,name):
            completed=subprocess.run([str(x) for x in command],cwd=work,capture_output=True,text=True,timeout=120)
            text=completed.stdout+completed.stderr;log=work/name;log.write_text(text);artifacts.append(log)
            return completed.returncode,text
        if args.suite in ('python','all'):
            rc,text=run([sys.executable,ROOT/'tests/test_fft_uvm.py'],output,'python.log')
            if rc:raise RuntimeError('FFT UVM evidence tests failed: '+text[-6000:])
            records['python']='PASS'
        if args.suite in ('hdl','all'):
            bindir,uvm=questa_paths()
            for name,(log2n,_,in_width,width) in CASES.items():
                if args.case not in ('all',name):continue
                folder=output/(name+'_vectors');model=prepare_vectors(folder,name)
                gaps=output/(name+'_gaps');gap_model=prepare_vectors(gaps,name,gaps=True)
                artifacts.extend(p for source in (folder,gaps) for p in source.iterdir() if p.is_file())
                for active in (1,0):
                    work=output/f'{name}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
                    if not (work/'work').is_dir():
                        rc,text=run([bindir/'vlib','work'],work,'vlib.log')
                        if rc:raise RuntimeError('FFT UVM vlib failed: '+text[-2000:])
                    defines=['+define+UVM_NO_DPI',f'+define+FFT_LOG2N={log2n}',f'+define+FFT_IN_WIDTH={in_width}',f'+define+FFT_WIDTH={width}']
                    if not active:defines.append('+define+RTL_RESET_LOW')
                    rc,text=run([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',
                                 f'+incdir+{ROOT/"rtl/modems/bpsk_costas_2008_08_25"}',uvm/'src/uvm_pkg.sv',*SOURCES,ROOT/'rtl/tb/fft_uvm_tb.sv'],work,'compile.log')
                    if rc or re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):
                        raise RuntimeError('FFT UVM compile failed/warned: '+text[-6000:])
                    positive,negative=work/'run.do',work/'negative.do'
                    positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
                    negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
                    artifacts.extend([positive,negative])
                    base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),
                          'work.fft_uvm_top',f'-gTWIDDLE_FILE={twiddle(log2n)}']
                    for scenario in SCENARIOS:
                        source=gaps if scenario=='gaps' else folder
                        rc,text=run([*base,f'+VECTORS={source}',f'+SCENARIO={scenario}','-do',positive.name],work,scenario+'.log')
                        records[f'{name}_{scenario}_reset_{active}']=parse_report(text,gap_model if scenario=='gaps' else model,scenario,active,rc)
                        print(f'PASS UVM FFT {name} {scenario} reset={active}',flush=True)
                    for key,(tag,flag,scenario) in CONTROLS.items():
                        rc,text=run([*base,f'+VECTORS={folder}',f'+SCENARIO={scenario}','+'+flag,'-do',negative.name],work,'negative_'+key+'.log')
                        verify_negative(text,rc,tag);records[f'{name}_negative_{key}_reset_{active}']=dict(returncode=rc,detected_tag=tag)
                    records[f'{name}_model_reset_{active}']=model
        write_json(target,dict(finish(evidence,artifacts),status='PASS',case_selection=args.case,records=records,
                               scope='Full FFT sequencer/driver/monitor/scoreboard UVM on existing production vectors; actual accepted I/Q, inverse and TLAST, input/output queue reset accounting and malformed-TLAST sticky-error recovery. Native internal bounds/saturation remain in run_fft.py.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise
    print('PASS FFT UVM '+args.suite)


if __name__=='__main__':main()
