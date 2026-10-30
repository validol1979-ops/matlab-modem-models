"""2048-symbol frame completion on every existing modem TX profile and reset polarity."""
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
import json,os,re,subprocess,sys
import numpy as np
root=Path('');sys.path.insert(0,str(root/'tools'))
from regression_evidence import begin,finish,write_json,questa_paths
from run_rtl import SOURCES
from run_bpsk_uvm import PILOT,TX_SUMMARY,TX_HANDSHAKES,TX_FRAME
from run_psk_tx_uvm import PROFILES,parameters,parse_report as parse_psk
from bpsk_cases import b,p,save
from oqpsk_cases import o
from cpm_cases import c
from modem_stream_rates import case_spec,pin_spec,measure
stage=Path('/tmp/modems_max_tx');stage.mkdir(exist_ok=True);bindir,uvm=questa_paths();evidence=begin()

def run(command,work,name):
 result=subprocess.run([str(v) for v in command],cwd=work,capture_output=True,text=True,timeout=180)
 text=result.stdout+result.stderr;log=work/name;log.write_text(text)
 if result.returncode:raise RuntimeError('rc'+str(result.returncode)+' '+str(log)+' '+text[-2000:])
 return text,log

def validate_maximum_tx(text,model,name,active):
    # The production parser deliberately requires its unchanged768-symbol matrix.
    # This separate directed experiment has an explicit2048-symbol contract.
    modulation='PSK' if name in PROFILES else name.upper()
    summary=re.findall(TX_SUMMARY.replace('BPSK',modulation),text);hs=re.findall(TX_HANDSHAKES,text)
    lengths=[1,2,33,192,2048];tail=36 if name=='oqpsk' else 0 if name=='msk' else 32
    count=sum(lengths);samples=sum(8*n+tail for n in lengths)
    if (len(summary)!=1 or len(hs)!=1 or re.search(r'UVM_(?:FATAL|ERROR)\s*:\s*[1-9]|UVM_(?:FATAL|ERROR)[^\n]*\[|\*\* (?:Fatal|Error)',text)):
        raise RuntimeError('Maximum TX must have one clean complete UVM summary')
    if tuple(map(int,summary[0]))!=(samples,5,count,0,0,samples,count,1,0,0,0):raise RuntimeError('Maximum TX actual counts/queues/reset conservation')
    handshakes=tuple(map(int,hs[0]))
    if handshakes[:2]!=(count,samples) or handshakes[2]<5 or handshakes[3:]!=(0,0,0):raise RuntimeError('Maximum TX physical handshakes')
    frame_rows=[tuple(map(int,r)) for r in re.findall(TX_FRAME,text)]
    if frame_rows!=[(f,n,8*n+tail) for f,n in enumerate(lengths)]:raise RuntimeError('Maximum TX explicit frame geometry')
    if model['frame_symbols']!=lengths or model['input_symbols']!=count or model['output_samples']!=samples:raise RuntimeError('Maximum TX independent model metadata')
    if name!='bpsk':
        alphabet=PROFILES[name].alphabet if name in PROFILES else 4 if name=='oqpsk' else 2
        if re.findall(r'UVM TX LABELS bits=(\d+) mask=(\d+)',text)!=[(str((alphabet-1).bit_length()),str((1<<alphabet)-1))]:raise RuntimeError('Maximum TX label alphabet')
    if name in PROFILES:
        values=parameters(name)
        if re.findall(r'UVM PSK TX PARAMETERS order=(\d+) amplitude=(\d+) differential=(\d+) axis=(\d+) pi4=(\d+)',text)!=[tuple(str(values[k]) for k in ('ORDER','AMPLITUDE','DIFFERENTIAL','TX_AXIS','PI4'))]:raise RuntimeError('Maximum TX physical mapper parameters')
    return dict(profile=name,reset_active=active,checked=samples,frames=5,input_handshakes=count,output_handshakes=samples,input_stalls=handshakes[2],frame_symbols=lengths)


def one(name):
 lengths=[1,2,33,192,2048];profile=PROFILES.get(name)
 alphabet=profile.alphabet if profile else 4 if name=='oqpsk' else 2;bits=(alphabet-1).bit_length()
 rng=np.random.default_rng(71 if name=='bpsk' else 19);source=[];output=[];tail=36 if name=='oqpsk' else 0 if name=='msk' else 32
 for f,n in enumerate(lengths):
  labels=rng.integers(0,alphabet,n).tolist() if name=='bpsk' else [0] if f==0 else [alphabet-1,0] if f==1 else list(range(min(n,alphabet)))+rng.integers(0,alphabet,max(0,n-alphabet)).tolist()
  wave=p.transmit(profile,labels) if profile else o.transmit(labels) if name=='oqpsk' else c.transmit(labels,name=='gmsk') if name in ('msk','gmsk') else b.transmit(labels)
  if len(wave)!=8*n+tail:raise RuntimeError('Independent maximum TX geometry')
  source.extend((int(v),int(k==n-1)) for k,v in enumerate(labels));output.extend((r,i,int(k==len(wave)-1)) for k,(r,i) in enumerate(wave))
 folder=stage/(name+'_vectors');folder.mkdir(exist_ok=True);source_file,output_file=('bits.txt','tx.txt') if name=='bpsk' else ('tx_symbols.txt','tx_out.txt')
 save(folder/source_file,source);save(folder/output_file,output)
 model=dict(frames=5,frame_symbols=lengths,input_symbols=sum(lengths),output_samples=len(output))
 if profile:model.update(profile=name,tx_parameters=parameters(name),alphabet=alphabet,label_bits=bits,labels_seen_mask=(1<<alphabet)-1)
 write_json(folder/'model.json',model);artifacts=list(folder.iterdir());records={}
 timing_model=dict(name=name+'_tx',profile=name,direction='tx',input_lengths=lengths,output_lengths=[8*n+tail for n in lengths],simo=False,memory_depth=None,filter_tail=0)
 family='psk' if profile else 'cpm' if name in ('msk','gmsk') else name
 for active in (1,0):
  work=stage/f'{name}_reset_{active}';work.mkdir(exist_ok=True)
  if not (work/'work').is_dir():run([bindir/'vlib','work'],work,'vlib.log')
  defines=['+define+UVM_NO_DPI',*(['+define+RTL_RESET_LOW'] if not active else [])]
  if profile:defines.extend([f'+define+PSK_LABEL_BITS={bits}',*(f'+define+PSK_{key}={value}' for key,value in parameters(name).items())])
  if name in ('msk','gmsk'):defines.append(f'+define+TX_GMSK={int(name=="gmsk")}')
  text,log=run([bindir/'vlog','-64','-sv',*defines,f'+incdir+{uvm/"src"}',f'+incdir+{PILOT}',f'+incdir+{root/"rtl/tb"}',uvm/'src/uvm_pkg.sv',*SOURCES,root/f'rtl/tb/{family}_tx_uvm_tb.sv'],work,'compile.log');artifacts.append(log)
  if re.search(r'Warnings:\s*[1-9]|(?:Error|Warning):',text):raise RuntimeError('Maximum TX compile warning')
  pins=pin_spec(case_spec(name+'_tx'));script=work/'run.do';script.write_text('onfinish stop\nonerror {quit -code 13}\nvcd file pins.vcd\nvcd add '+' '.join('/'+p for p,width in pins.values())+'\nrun -all\nvcd flush\nquit -code 0\n')
  args=[bindir/'vsim','-64','-c','-quiet','-voptargs=+acc','-dpicpppath',os.environ.get('DPI_CC','/usr/bin/gcc'),'work.'+family+'_tx_uvm_top',f'+VECTORS={folder}','+SCENARIO=stream','-do',script.name]
  if family=='cpm':args.append(f'-gTABLE_DIR={PILOT/"tables"}')
  text,log=run(args,work,'run.log')
  if re.search(r'UI-Msg \(Error\)|No objects found',text):raise RuntimeError('Missing VCD object')
  numeric=validate_maximum_tx(text,model,name,active)
  timing=measure(work/'pins.vcd',timing_model,active,pins)
  if any(not f['output']['every_cycle'] or f['input']['beats']>1 and (f['input']['minimum_interval'],f['input']['maximum_interval'])!=(8,8) for f in timing['per_frame']):raise RuntimeError('Maximum TX stream cadence')
  records[f'{name}_reset_{active}']=dict(numeric=numeric,timing=timing);artifacts.extend([script,log,work/'pins.vcd'])
 print('PASS maximum TX '+name,flush=True)
 return records,artifacts

records={};files=[Path(__file__)];write_json(stage/'results.json',dict(evidence,status='RUNNING'))
try:
 with ThreadPoolExecutor(max_workers=4) as pool:
  for f in as_completed([pool.submit(one,name) for name in ('bpsk',*PROFILES,'oqpsk','msk','gmsk')]):
   r,a=f.result();records.update(r);files.extend(a)
 write_json(stage/'results.json',dict(finish(evidence,sorted(set(files))),status='PASS',records=records,scope='All17 frame TX profiles,34 UVM/VCD runs, frames1,2,33,192,2048 labels; unchanged production fixed models and actual pin cadence; no physical synthesis.'))
except Exception as e:
 write_json(stage/'results.json',dict(evidence,status='FAIL',error=str(e)));raise
