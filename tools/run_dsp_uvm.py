#!/usr/bin/env python3
"""UVM for production DSP pin streams, configuration and sideband outputs."""
import argparse
from concurrent.futures import ThreadPoolExecutor,as_completed
import os
from pathlib import Path
import re
import subprocess
import sys

from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_unoptimized
from run_rtl import SOURCES
from dsp_uvm_plans import CASES,prepare

SCENARIOS=('stream','gaps','stalled','midreset','outreset')
CONTROLS={
    'numeric':('NUMERIC','INJECT_MISMATCH','stream'),
    's_valid_x':('PROTOCOL','INJECT_S_VALID_X','stream'),
    's_ready_x':('PROTOCOL','INJECT_S_READY_X','stream'),
    'm_valid_x':('PROTOCOL','INJECT_M_VALID_X','stream'),
    'm_ready_x':('PROTOCOL','INJECT_M_READY_X','stream'),
    'input_x':('NUMERIC','INJECT_INPUT_X','stream'),
    'output_x':('NUMERIC','INJECT_OUTPUT_X','stream'),
    'error_x':('PROTOCOL','INJECT_ERROR_X','stream'),
    'last':('NUMERIC','INJECT_LAST','stream'),
    'held_data':('STALL','INJECT_HELD_DATA','stalled'),
}
CFG_CONTROLS={
    'cfg_valid_x':('PROTOCOL','INJECT_CFG_VALID_X','stream'),
    'cfg_ready_x':('PROTOCOL','INJECT_CFG_READY_X','stream'),
    'cfg_data':('NUMERIC','INJECT_CFG_DATA','stream'),
}
SUMMARY=(r'UVM DSP checked=(\d+) inputs=(\d+) configs=(\d+) frames=(\d+) discarded=(\d+) discarded_inputs=(\d+) '
         r'discarded_configs=(\d+) expected=(\d+) expected_inputs=(\d+) expected_configs=(\d+) resets=(\d+) before_reset=(\d+) terminal_resets=(\d+)')
HANDSHAKES=(r'UVM DSP HANDSHAKES config=(\d+) input=(\d+) output=(\d+) cfg_stalls=(\d+) input_stalls=(\d+) output_stalls=(\d+) gaps=(\d+) pending_resets=(\d+)')


def scenarios(model):return (*SCENARIOS,*(('woutreset',) if model.get('weight_port',False) else ()),*(('cfgreset',) if model.get('cfgreset_supported',bool(model['config_rows'])) else ()))
def controls(model):
    base={k:v for k,v in CONTROLS.items() if k!='error_x' or model.get('error_port',True)}
    if model.get('sideband_port',False):base['sideband']=('NUMERIC','INJECT_SIDEBAND','stream')
    if model.get('weight_port',False):base.update({
        'desired_data':('NUMERIC','INJECT_DESIRED','stream'),
        'error_data':('NUMERIC','INJECT_ERROR_DATA','stream'),
        'weight_numeric':('NUMERIC','INJECT_WEIGHT_MISMATCH','stream'),
        'weight_valid_x':('PROTOCOL','INJECT_W_VALID_X','stream'),
        'weight_ready_x':('PROTOCOL','INJECT_W_READY_X','stream'),
        'weight_data_x':('NUMERIC','INJECT_W_DATA_X','stream'),
        'weight_last':('NUMERIC','INJECT_W_LAST','stream'),
        'weight_held':('STALL','INJECT_W_HELD','stalled'),
    })
    return {**base,**(CFG_CONTROLS if model['config_rows'] else {})}


def parse_weight_report(text,model,scenario):
    found=re.findall(r'UVM DSP WEIGHTS checked=(\d+) expected=(\d+) discarded=(\d+) before_reset=(\d+) frames=(\d+) terminal_resets=(\d+)',text)
    hands=re.findall(r'UVM DSP WEIGHT_HANDSHAKES outputs=(\d+) stalls=(\d+) pending_resets=(\d+)',text)
    if len(found)!=1 or len(hands)!=1:raise RuntimeError('Complete DSP weight accounting required')
    checked,expected,discarded,before,frames,terminal=map(int,found[0]);handshakes,stalls,pending=map(int,hands[0])
    actual_frames=[tuple(map(int,v)) for v in re.findall(r'UVM DSP WEIGHT_FRAME id=(\d+) outputs=(\d+)',text)]
    frame_lengths=model['weight_lengths'];has_weights=model['weight_port']
    expected_frames=[(k,count) for k,count in enumerate(frame_lengths) if count]
    if actual_frames!=expected_frames or frames!=len(expected_frames):raise RuntimeError('DSP final tap-dump frame geometry mismatch')
    if len(frame_lengths)!=model['frames'] or model['weight_rows']!=sum(frame_lengths):raise RuntimeError('DSP immutable weight geometry mismatch')
    reset=scenario in ('midreset','outreset','woutreset','cfgreset');warm=model['warm_weights'];prefix=checked-model['weight_rows']
    if (not 0<=prefix<=warm or
            (scenario=='woutreset' and prefix!=warm-1) or
            (scenario!='outreset' and scenario!='woutreset' and prefix!=0)):
        raise RuntimeError('DSP actual warm-weight interval mismatch')
    if (expected!=model['weight_rows']+warm*int(reset) or discarded!=(warm-prefix if reset else 0)
            or checked!=handshakes or before!=prefix or terminal!=int(scenario=='woutreset')
            or checked+discarded!=expected):raise RuntimeError('DSP weight handshake/reset conservation mismatch')
    if scenario=='woutreset':
        if pending!=1:raise RuntimeError('Pending terminal weight reset missing')
    elif scenario=='outreset':
        if pending not in (0,1):raise RuntimeError('DSP pending-weight reset scope')
    elif pending:raise RuntimeError('Unexpected pending-weight reset')
    if has_weights and scenario in ('stalled','woutreset') and stalls<1:raise RuntimeError('DSP weight backpressure missing')
    if not has_weights and any((checked,expected,discarded,before,frames,terminal,handshakes,stalls,pending)):
        raise RuntimeError('No physical weight stream on this DUT')
    return dict(weight_port=has_weights,packed_weight_bits=model['packed_weight_bits'],weight_checked=checked,
                weight_expected=expected,weight_discarded=discarded,weight_before_reset=before,weight_terminal_resets=terminal,
                weight_stalls=stalls,weight_pending_resets=pending,per_weight_frame=[dict(frame=k,outputs=count) for k,count in actual_frames])


def parse_report(text,model,scenario,active,returncode=0):
    if scenario not in scenarios(model):raise RuntimeError('Unsupported DSP UVM scenario')
    summary=re.findall(SUMMARY,text);handshakes=re.findall(HANDSHAKES,text)
    if (returncode or len(summary)!=1 or len(handshakes)!=1 or
            re.search(r'UVM_(?:ERROR|FATAL)\s*:\s*[1-9]|UVM_(?:ERROR|FATAL)[^\n]*\[|\*\* (?:Error|Fatal)',text)):
        raise RuntimeError('Complete successful DSP UVM report required')
    fields=('checked','input_checked','cfg_checked','frames','discarded_outputs','discarded_inputs','discarded_configs',
            'expected_outputs','expected_inputs','expected_configs','resets','before_reset','terminal_resets')
    row=dict(zip(fields,map(int,summary[0])))
    row.update(dict(zip(('cfg_handshakes','input_handshakes','output_handshakes','cfg_stalls','input_stalls','output_stalls','input_gaps','pending_resets'),map(int,handshakes[0]))))
    if re.findall(r'UVM DSP KIND id=(\d+)',text)!=[str(model['case']['kind'])]:raise RuntimeError('DSP physical DUT kind mismatch')
    parameters=re.findall(r'UVM DSP PARAMETERS log2n=(\d+) cp=(\d+) log2hop=(\d+) lanes=(\d+) tmax=(\d+)',text)
    expected_parameters=tuple(model['case'].get(key,default) for key,default in
                              [('log2n',5),('cp',8),('log2hop',3),('log2lanes',2),('log2tmax',7)])
    if len(parameters)!=1 or tuple(map(int,parameters[0]))!=expected_parameters:
        raise RuntimeError('DSP physical DUT parameter coverage mismatch')
    frames=[tuple(map(int,values)) for values in re.findall(r'UVM DSP FRAME id=(\d+) inputs=(\d+) outputs=(\d+)',text)]
    if frames!=[(k,a,b) for k,(a,b) in enumerate(model['lengths'])] or row['frames']!=model['frames']:
        raise RuntimeError('DSP independent input/output frame geometry mismatch')
    if model['frames']!=len(model['lengths']) or model['inputs']!=sum(a for a,b in model['lengths']) or model['outputs']!=sum(b for a,b in model['lengths']):
        raise RuntimeError('DSP immutable model geometry mismatch')
    mid,out,cfg=scenario=='midreset',scenario=='outreset',scenario=='cfgreset';wout=scenario=='woutreset';reset=mid or out or cfg or wout
    c,ni,no=model['config_rows'],model['warm_inputs'],model['warm_outputs']
    warm_cfg=max(1,c//2) if cfg else c if mid or out or wout else 0
    warm_in=max(1,ni//2) if mid else ni if out or wout else 0
    prefix=row['checked']-model['outputs']
    if not 0<=prefix<=no or (not mid and prefix!=(no-1 if out else no if wout else 0)):
        raise RuntimeError('DSP actual warm-output interval mismatch')
    expected=(model['config_rows']+warm_cfg,model['inputs']+warm_in,model['outputs']+prefix,
              c-warm_cfg if reset else 0,ni-warm_in if reset else 0,no-prefix if reset else 0,
              model['config_rows']+c*int(reset),model['inputs']+ni*int(reset),model['outputs']+no*int(reset),
              1+int(reset),prefix,int(out))
    actual=(row['cfg_checked'],row['input_checked'],row['checked'],row['discarded_configs'],row['discarded_inputs'],row['discarded_outputs'],
            row['expected_configs'],row['expected_inputs'],row['expected_outputs'],row['resets'],row['before_reset'],row['terminal_resets'])
    if actual!=expected or (row['cfg_handshakes'],row['input_handshakes'],row['output_handshakes'])!=(row['cfg_checked'],row['input_checked'],row['checked']):
        raise RuntimeError('DSP actual cfg/input/output/reset conservation mismatch')
    if row['pending_resets']!=(1 if out else 0) and not (mid and row['pending_resets'] in (0,1)):
        raise RuntimeError('DSP pending-output reset coverage mismatch')
    if scenario=='gaps' and row['input_gaps']<1:raise RuntimeError('DSP actual ready source gap missing')
    if scenario in ('stalled','outreset') and row['output_stalls']<1:raise RuntimeError('DSP output backpressure missing')
    extra=re.findall(r'UVM DSP EXTRA log2m=(\d+) log2nmax=(\d+)',text)
    if extra!=[(str(model['case'].get('log2m',2)),str(model['case'].get('log2nmax',5)))]:raise RuntimeError('DSP extra physical parameters mismatch')
    memory=re.findall(r'UVM DSP MEMORY mmax=(\d+) kmax=(\d+) emax=(\d+)',text)
    if memory!=[tuple(str(model['case'].get(key,default)) for key,default in [('log2mmax',6),('log2kmax',6),('log2emax',9)])]:raise RuntimeError('DSP physical memory parameters mismatch')
    row.update(case=model['name'],kind=model['case']['kind'],scenario=scenario,reset_active=active,
               configured=bool(c),cfgreset_supported=model.get('cfgreset_supported',bool(c)),error_port=model.get('error_port',True),sideband_port=model.get('sideband_port',False),packed_input_bits=model['packed_input_bits'],packed_output_bits=model['packed_output_bits'],
               per_frame=[dict(frame=f,inputs=a,outputs=b) for f,a,b in frames])
    row.update(parse_weight_report(text,model,scenario))
    return row


def verify_negative(text,returncode,tag):
    if (not returncode or re.search(SUMMARY,text) or not re.search(r'UVM_FATAL[^\n]*\['+tag+r'\]',text)
            or not re.search(r'UVM_FATAL\s*:\s*[1-9]',text)):
        raise RuntimeError('DSP UVM negative control not rejected: '+tag)


def run_case(output,name):
    bindir,uvm=questa_paths();case=CASES[name]
    records,artifacts={},[];folder=output/(name+'_vectors');model=prepare(folder,name)
    artifacts.extend(p for p in folder.rglob('*') if p.is_file())
    def run(command,work,filename):
        result=subprocess.run([str(x) for x in command],cwd=work,capture_output=True,text=True,timeout=180)
        text=result.stdout+result.stderr;log=work/filename;log.write_text(text);artifacts.append(log)
        return result.returncode,text
    for active in (1,0):
        work=output/f'{name}_reset_{active}';work.mkdir(parents=True,exist_ok=True)
        if not (work/'work').is_dir():
            rc,text=run([bindir/'vlib','work'],work,'vlib.log')
            if rc:raise RuntimeError('DSP vlib failed: '+text[-2000:])
        definitions=['+define+UVM_NO_DPI',f'+define+DSP_KIND={case["kind"]}']
        definitions += [f'+define+DSP_{key.upper()}={case[key]}' for key in ('log2n','log2hop','cp','log2lanes','log2tmax','log2m','log2nmax','log2mmax','log2kmax','log2emax') if key in case]
        if not active:definitions.append('+define+RTL_RESET_LOW')
        rc,text=run([bindir/'vlog','-64','-sv',*definitions,f'+incdir+{uvm/"src"}',f'+incdir+{ROOT/"rtl/modems/bpsk_costas_2008_08_25"}',
                     f'+incdir+{ROOT/"rtl/tb"}',uvm/'src/uvm_pkg.sv',*SOURCES,ROOT/'rtl/tb/dsp_stream_uvm_tb.sv'],work,'compile.log')
        if rc or re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):raise RuntimeError('DSP UVM compile failed/warned: '+text[-6000:])
        positive,negative=work/'run.do',work/'negative.do'
        positive.write_text('onfinish stop\nonerror {quit -code 13}\nrun -all\nquit -code 0\n')
        negative.write_text('onfinish stop\nonerror {quit -code 13}\nonbreak {quit -code 13}\nrun -all\nquit -code 0\n')
        artifacts.extend([positive,negative])
        n=1<<case.get('log2n',5);hop=1<<case.get('log2hop',3)
        base=[bindir/'vsim','-64','-c','-quiet','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.dsp_uvm_top',
              f'-gLMS_RECIP_FILE={ROOT}/rtl/common/mem/lms_reciprocal.mem',f'-gPHI_FILE={ROOT}/rtl/common/mem/ldpc_phi.mem',f'-gINV_FILE={ROOT}/rtl/common/mem/ldpc_inv.mem',f'-gMEM_DIR={ROOT}/rtl/common/mem',f'-gTABLE_DIR={ROOT}/rtl/modems/bpsk_costas_2008_08_25/tables',f'-gTWIDDLE_FILE={ROOT}/rtl/common/mem/fft_twiddle_{n}.mem',f'-gWINDOW_FILE={ROOT}/rtl/common/mem/stft_window_{n}.mem',
              f'-gRECIP_FILE={ROOT}/rtl/common/mem/stft_recip_{n}_{hop}.mem',f'+VECTORS={folder}']
        for scenario in scenarios(model):
            rc,text=run([*base,f'+SCENARIO={scenario}','-do',positive.name],work,scenario+'.log')
            records[f'{name}_{scenario}_reset_{active}']=parse_report(text,model,scenario,active,rc)
        for key,(tag,flag,scenario) in controls(model).items():
            rc,text=run([*base,f'+SCENARIO={scenario}','+'+flag,'-do',negative.name],work,'negative_'+key+'.log')
            verify_negative(text,rc,tag);records[f'{name}_negative_{key}_reset_{active}']=dict(returncode=rc,detected_tag=tag)
        records[f'{name}_model_reset_{active}']=model
    print('PASS DSP UVM '+name,flush=True)
    return records,artifacts


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=('python','hdl','all'),default='all')
    parser.add_argument('--case',choices=('all',*CASES),default='all');parser.add_argument('--jobs',type=int,default=4)
    args=parser.parse_args();require_unoptimized()
    if not 1<=args.jobs<=8:parser.error('--jobs must be1..8')
    output=ROOT/'build/rtl/dsp_uvm';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/(('' if args.case=='all' else args.case+'_')+args.suite+'_results.json')
    artifacts,records=[],{};write_json(target,dict(evidence,status='RUNNING'))
    try:
        if args.suite in ('python','all'):
            result=subprocess.run([sys.executable,str(ROOT/'tests/test_dsp_uvm.py')],cwd=ROOT,capture_output=True,text=True)
            log=output/'python.log';log.write_text(result.stdout+result.stderr);artifacts.append(log)
            if result.returncode:raise RuntimeError('DSP UVM Python tests failed: '+log.read_text()[-6000:])
            records['python']='PASS'
        if args.suite in ('hdl','all'):
            selected=[name for name in CASES if args.case in ('all',name)]
            pool=ThreadPoolExecutor(max_workers=min(args.jobs,len(selected)))
            futures={pool.submit(run_case,output,name):name for name in selected}
            try:
                for future in as_completed(futures):
                    child,files=future.result();records.update(child);artifacts.extend(files)
            except Exception:
                for future in futures:future.cancel()
                raise
            finally:
                pool.shutdown(wait=True,cancel_futures=True)
        write_json(target,dict(finish(evidence,sorted(set(artifacts))),status='PASS',case_selection=args.case,records=records,
                               scope='Full UVM DSP on all registered original production vectors, lossless packed physical pin fields, independent transaction geometry, exact accepted cfg/input/output/final-weight queues, gaps/backpressure and partial/terminal/config resets.'))
    except Exception as exc:
        write_json(target,dict(evidence,status='FAIL',error=f'{type(exc).__name__}: {exc}'));raise
    print('PASS DSP UVM '+args.suite)


if __name__=='__main__':main()
