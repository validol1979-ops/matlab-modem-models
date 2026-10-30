from pathlib import Path
import ast,json,re,sys
root=Path('');sys.path.insert(0,str(root/'tools'))
from run_bpsk_uvm import TX_SUMMARY,TX_HANDSHAKES,TX_FRAME
from run_psk_tx_uvm import PROFILES,parameters
from regression_evidence import begin,finish,write_json,require_pass
stage=Path('/tmp/modems_max_tx');data=json.loads((stage/'results.json').read_text());require_pass(data);evidence=begin()
parsed=ast.parse(Path('/tmp/modems_max_tx.py').read_text());node=next(n for n in parsed.body if isinstance(n,ast.FunctionDef) and n.name=='validate_maximum_tx')
namespace=dict(re=re,PROFILES=PROFILES,parameters=parameters,TX_SUMMARY=TX_SUMMARY,TX_HANDSHAKES=TX_HANDSHAKES,TX_FRAME=TX_FRAME)
exec(compile(ast.Module(body=[node],type_ignores=[]),'/tmp/modems_max_tx.py','exec'),namespace)
validate=namespace['validate_maximum_tx'];records={}
for name in ('bpsk','qam64'):
 model=json.loads((stage/(name+'_vectors/model.json')).read_text());text=(stage/(name+'_reset_1/run.log')).read_text();validate(text,model,name,1)
 bad=[('missing_summary',text.replace('checked=','wrong=')),('wrong_counts',text.replace('input=2276','input=2275')),
      ('frame_geometry',text.replace('frame=4 inputs=2048','frame=4 inputs=2047')),
      ('fatal',text+'\nUVM_FATAL [NUMERIC] injected\n')]
 if name=='qam64':bad.extend([('label_mask',re.sub(r'(UVM TX LABELS bits=6 mask=)\d+',r'\g<1>0',text)),
                             ('physical_mapper',text.replace('PARAMETERS order=64','PARAMETERS order=16'))])
 for kind,poison in bad:
  if poison==text:raise RuntimeError('Fault was not actually injected')
  try:validate(poison,model,name,1)
  except RuntimeError:records[name+'_'+kind]=dict(rejected=True)
  else:raise RuntimeError('Maximum TX parser accepted '+name+' '+kind)
write_json(stage/'validator_controls.json',dict(finish(evidence,[Path(__file__),stage/'results.json',Path('/tmp/modems_max_tx.py')]),status='PASS',records=records))
print('PASS maximum TX parser:',len(records),'negative controls')
