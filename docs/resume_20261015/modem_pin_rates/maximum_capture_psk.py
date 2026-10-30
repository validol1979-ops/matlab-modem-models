"""Maximum legal shared PSK/QAM capture, including SIMO and the QAM64 FIR shift."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import json,os,re,subprocess,sys
import numpy as np
root=Path('');sys.path.insert(0,str(root/'tools'))
from regression_evidence import begin,finish,write_json,questa_paths
from run_rtl import SOURCES
from run_bpsk_uvm import PILOT,prepare_float,parse_report,parse_profile_report
from bpsk_cases import receiver_vectors,rtl_parameters,p,b,save
from modem_stream_rates import case_spec,pin_spec,measure
from uvm_floating_reference import rows
import mrc_fixed as m
stage=Path('/tmp/modems_max_capture_psk');stage.mkdir(exist_ok=True);evidence=begin();bindir,uvm=questa_paths()

def run(command,work,name):
 r=subprocess.run([str(v) for v in command],cwd=work,capture_output=True,text=True,timeout=240)
 text=r.stdout+r.stderr;log=work/name;log.write_text(text)
 if r.returncode:raise RuntimeError('rc'+str(r.returncode)+' '+str(log)+' '+text[-2000:])
 return text,log

def one(profile):
 name=profile.name;count=2048;frames=4;folder=stage/(name+'_vectors');folder.mkdir(exist_ok=True)
 model=receiver_vectors(folder,frames=frames,count=count,seed=19,profile=profile)
 simo=name=='qpsk_diff';wave=rows(folder/'rx_wave.txt',5 if simo else 3);ends=np.flatnonzero(wave[:,-1])+1
 original_trace=rows(folder/'rx_trace.txt',10);acquisition=rows(folder/'rx_acquire.txt',6);training=rows(folder/'preamble.txt',1)[:,0]
 gains=rows(folder/'gains.txt',6)[0].tolist() if simo else None
 weights=m.weights(tuple(gains[:2]),tuple(gains[2:4]),*gains[4:]) if simo else None
 padded=[];prefixes=[];start=0
 for f,end in enumerate(ends):
  original=wave[start:end,:-1].tolist();start=int(end);target=count*8+64
  if len(original)>target:raise RuntimeError('Original exceeds maximum legal capture')
  padded_frame=original+[[0]*(4 if simo else 2)]*(target-len(original));prefixes.append(dict(original_samples=len(original),appended_zeros=target-len(original)))
  processed=m.combine([tuple(r[:2]) for r in padded_frame],[tuple(r[2:]) for r in padded_frame],*weights) if simo else padded_frame
  result=p.receive(profile,processed,training,count);a=result['acquisition'];gold=[]
  for k,(real_value,imag_value,phase,freq,gain,correction,index,label) in enumerate(result['trace']):
   gold.append((real_value,imag_value,b.wrap(phase+a['frequency']*(k+1)),freq,gain,correction,index,label,int(k==count-1),int(original_trace[f*count+k,9])))
  if gold!=list(map(tuple,original_trace[f*count:(f+1)*count].tolist())) or [int(a[key]) for key in ('delay','frequency','phase','gain','score','confidence')]!=acquisition[f].tolist():raise RuntimeError('Zero extension changed original fixed result')
  padded.extend((*r,int(k==target-1)) for k,r in enumerate(padded_frame))
 save(folder/'rx_wave.txt',padded);model['samples']=len(padded)
 save(folder/'payload_expected.txt',[(v,) for v in model['payload_errors']])
 model.update(profile=name,parameters=rtl_parameters(profile),label_bits=(profile.alphabet-1).bit_length(),index_bits=(profile.order-1).bit_length(),simo=simo,
              cfg_label_max=int(training.max()),decoded_label_max=int(original_trace[:,7].max()),index_max=int(original_trace[:,6].max()),
              gain_control_scope='One actual SIMO gain tuple per reset epoch' if simo else 'NOT_APPLICABLE: single-branch receiver has no gain configuration ports')
 prepare_float(folder,name,model);write_json(folder/'model.json',model)
 timing_model=dict(name=name+'_rx',profile=name,direction='rx',input_lengths=[target]*frames,output_lengths=[count]*frames,simo=simo,memory_depth=16640,filter_tail=32)
 artifacts=[v for v in folder.iterdir() if v.is_file()];records={}
 for active in (1,0):
  work=stage/f'{name}_reset_{active}';work.mkdir(exist_ok=True)
  if not (work/'work').is_dir():run([bindir/'vlib','work'],work,'vlib.log')
  parameters=model['parameters'];defines=['+define+UVM_NO_DPI',*(['+define+RTL_RESET_LOW'] if not active else [])]
  defines.extend(f'+define+PILOT_{key}={parameters[key]}' for key in ('ORDER','AMPLITUDE','DIFFERENTIAL','FEEDFORWARD','TIMING_LOOP','PI4','EQUALIZER') if key in parameters);defines.append(f'+define+PILOT_SIMO={int(simo)}')
  text,log=run([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',uvm/'src/uvm_pkg.sv',*SOURCES,root/'rtl/tb/bpsk_rx_uvm_tb.sv'],work,'compile.log');artifacts.append(log)
  if re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):raise RuntimeError('Maximum capture compile warnings')
  pins=pin_spec(case_spec(name+'_rx'));script=work/'run.do';script.write_text('onfinish stop\nonerror {quit -code 13}\nvcd file pins.vcd\nvcd add '+' '.join('/'+path for path,width in pins.values())+'\nrun -all\nvcd flush\nquit -code 0\n')
  text,log=run([bindir/'vsim','-64','-c','-quiet','-voptargs=+acc','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.bpsk_rx_uvm_top',f'-gTABLE_DIR={PILOT/"tables"}',f'+VECTORS={folder}','+SYMBOLS=2048','+SCENARIO=stream','+FLOAT_SER','-do',script.name],work,'run.log')
  if re.search(r'UI-Msg \(Error\)|No objects found',text):raise RuntimeError('Missing VCD object')
  numeric=(parse_report if name=='bpsk' else parse_profile_report)(text,model,'stream',active,0);timing=measure(work/'pins.vcd',timing_model,active,pins)
  if any(r['capture_high_water_samples']!=16480 or r['capture_headroom_samples']!=160 for r in timing['per_frame']):raise RuntimeError('Maximum capture not reached')
  records[f'{name}_reset_{active}']=dict(numeric=numeric,timing=timing,zero_extension=prefixes)
  artifacts.extend([script,log,work/'pins.vcd'])
 print('PASS maximum capture '+name,flush=True)
 return records,artifacts

records={};files=[Path(__file__)];write_json(stage/'results.json',dict(evidence,status='RUNNING'))
try:
 with ThreadPoolExecutor(max_workers=4) as pool:
  for f in as_completed([pool.submit(one,profile) for profile in p.PROFILES]):
   r,a=f.result();records.update(r);files.extend(a)
 write_json(stage/'results.json',dict(finish(evidence,sorted(set(files))),status='PASS',records=records,scope='Shared PSK/QAM capture at2048 symbols and maximum16448 input samples, both reset polarities; all14 shared PSK/QAM profiles, including SIMO. Full UVM numeric/float and all physical memory writes; no physical synthesis.'))
except Exception as e:
 write_json(stage/'results.json',dict(evidence,status='FAIL',error=str(e)));raise
