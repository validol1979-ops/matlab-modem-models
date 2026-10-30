"""Independent maximum legal packet RX capture; no changes to production sources."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import json,os,re,subprocess,sys
import numpy as np
root=Path('');sys.path.insert(0,str(root/'tools'))
from regression_evidence import begin,finish,write_json,questa_paths,require_pass
from run_rtl import SOURCES
from run_bpsk_uvm import PILOT,prepare_float
from run_packet_rx_uvm import PROFILES,parse_packet_report
from oqpsk_cases import vectors as oqvectors,save,o
from cpm_cases import vectors as cvectors,c
from uvm_floating_reference import rows
from modem_stream_rates import case_spec,pin_spec,measure
stage=Path('/tmp/modems_max_capture');stage.mkdir(exist_ok=True)
evidence=begin();bindir,uvm=questa_paths()

def run(command,work,name):
 r=subprocess.run([str(v) for v in command],cwd=work,capture_output=True,text=True,timeout=240)
 text=r.stdout+r.stderr;path=work/name;path.write_text(text)
 if r.returncode:raise RuntimeError('rc'+str(r.returncode)+' '+str(path)+' '+text[-2000:])
 return text,path

def one(profile):
 count=2048;frames=4;kind,alphabet=PROFILES[profile];folder=stage/(profile+'_vectors');folder.mkdir(exist_ok=True)
 native=oqvectors(folder,frames=frames,count=count,tracking=False) if profile=='oqpsk' else cvectors(folder,profile=='gmsk',frames=frames,count=count)
 wave=rows(folder/'rx_wave.txt',3);ends=np.flatnonzero(wave[:,-1])+1;start=0;padded=[];prefixes=[]
 output=rows(folder/'rx_out.txt',4 if profile=='oqpsk' else 3)[:count*frames]
 acquisition=rows(folder/'rx_acquire.txt',3)[:frames];training=rows(folder/'preamble.txt',1)[:,0]
 for f,end in enumerate(ends[:frames]):
  original=wave[start:end,:2].tolist();start=int(end);target=count*8+96
  if len(original)>target:raise RuntimeError('Original channel exceeds maximum legal capture')
  padded_frame=original+[[0,0]]*(target-len(original));prefixes.append(dict(original_samples=len(original),appended_zeros=target-len(original)))
  # Recompute on the physically padded frame using the unchanged production model.
  result=o.receive(padded_frame,training,count) if profile=='oqpsk' else c.receive_coherent(padded_frame,training,count) if profile=='gmsk' else c.receive(padded_frame,training,count,False)
  decoded=result['data'];values=result['values'];a=result['acquisition']
  expected=[(*v,int(decoded[k]),int(k==count-1)) if profile=='oqpsk' else (v,int(decoded[k]),int(k==count-1)) for k,v in enumerate(values)]
  if expected!=list(map(tuple,output[f*count:(f+1)*count].tolist())) or [a['delay'],a['frequency'],a['phase']]!=acquisition[f].tolist():
   raise RuntimeError('Zero extension changed original fixed RX result')
  padded.extend((re,im,int(k==target-1)) for k,(re,im) in enumerate(padded_frame))
 save(folder/'rx_wave.txt',padded);save(folder/'rx_out.txt',output);save(folder/'rx_acquire.txt',[(*a,0,0,0) for a in acquisition])
 truth_file='tx_symbols.txt' if profile=='oqpsk' else 'tx_bits.txt';truth=rows(folder/truth_file,2)[:count*frames,0]
 save(folder/truth_file,[(int(v),int(k%count==count-1)) for k,v in enumerate(truth)])
 trace=[]
 for k,row in enumerate(output):
  re_value,im_value,label,last=map(int,row) if profile=='oqpsk' else (int(row[0]),0,int(row[1]),int(row[2]))
  trace.append((re_value,im_value,0,0,0,0,label,label,last,int(truth[k])))
 save(folder/'rx_trace.txt',trace);errors=[sum(r[7]!=r[9] for r in trace[f*count+192:(f+1)*count]) for f in range(frames)]
 if errors!=native['payload_errors'][:frames]:raise RuntimeError('Immutable original payload changed')
 save(folder/'payload_expected.txt',[(v,) for v in errors])
 model=dict(profile=profile,kind=kind,frames=frames,symbols=count*frames,samples=len(padded),payload_errors=errors,warm_frame=3,warm_samples=5600,warm_wave_samples=count*8+96,
            label_bits=(alphabet-1).bit_length(),cfg_label_max=int(training.max()),decoded_label_max=max(r[7] for r in trace),index_max=max(r[6] for r in trace),soft_bits=18 if profile=='oqpsk' else 36)
 prepare_float(folder,profile,model);write_json(folder/'model.json',model)
 timing_model=dict(name=profile+'_rx',profile=profile,direction='rx',input_lengths=[count*8+96]*frames,output_lengths=[count]*frames,simo=False,memory_depth=16512,filter_tail=32 if profile=='oqpsk' else 0)
 artifacts=[p for p in folder.iterdir() if p.is_file()];records={}
 for active in (1,0):
  work=stage/f'{profile}_reset_{active}';work.mkdir(exist_ok=True)
  if not (work/'work').is_dir():run([bindir/'vlib','work'],work,'vlib.log')
  defines=['+define+UVM_NO_DPI',f'+define+PILOT_PACKET={kind}',f'+define+PILOT_ORDER={alphabet}',*(['+define+RTL_RESET_LOW'] if not active else [])]
  text,log=run([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',uvm/'src/uvm_pkg.sv',*SOURCES,root/'rtl/tb/cpm_acquisition_check.sv',root/'rtl/tb/bpsk_rx_uvm_tb.sv'],work,'compile.log');artifacts.append(log)
  if re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):raise RuntimeError('Maximum capture compile warnings')
  pins=pin_spec(case_spec(profile+'_rx'));script=work/'run.do';script.write_text('onfinish stop\nonerror {quit -code 13}\nvcd file pins.vcd\nvcd add '+' '.join('/'+p for p,width in pins.values())+'\nrun -all\nvcd flush\nquit -code 0\n')
  text,log=run([bindir/'vsim','-64','-c','-quiet','-voptargs=+acc','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.bpsk_rx_uvm_top',f'-gTABLE_DIR={PILOT/"tables"}',f'+VECTORS={folder}','+SYMBOLS=2048','+SCENARIO=stream','+FLOAT_SER','-do',script.name],work,'run.log')
  if re.search(r'UI-Msg \(Error\)|No objects found',text):raise RuntimeError('Missing VCD object')
  numeric=parse_packet_report(text,model,'stream',active,0);timing=measure(work/'pins.vcd',timing_model,active,pins)
  expected_writes=16512 if profile=='oqpsk' else 16480
  if any(r['capture_high_water_samples']!=expected_writes for r in timing['per_frame']):raise RuntimeError('Maximum legal capture not reached')
  records[f'{profile}_reset_{active}']=dict(numeric=numeric,timing=timing,zero_extension=prefixes)
  artifacts.extend([script,log,work/'pins.vcd'])
 print('PASS maximum capture '+profile,flush=True)
 return records,artifacts

records={};files=[Path(__file__)];write_json(stage/'results.json',dict(evidence,status='RUNNING'))
try:
 with ThreadPoolExecutor(max_workers=2) as pool:
  for f in as_completed([pool.submit(one,p) for p in PROFILES]):
   r,a=f.result();records.update(r);files.extend(a)
 write_json(stage/'results.json',dict(finish(evidence,sorted(set(files))),status='PASS',records=records,scope='2048-symbol packet RX, maximum legal16480 input samples, both reset polarities, full UVM numeric/float and physical capture writes. No physical synthesis.'))
except Exception as e:
 write_json(stage/'results.json',dict(evidence,status='FAIL',error=str(e)));raise
