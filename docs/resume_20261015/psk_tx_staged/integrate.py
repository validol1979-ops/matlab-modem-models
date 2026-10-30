"""Apply only after the active root source snapshot has completed and been archived."""
from pathlib import Path
import json
root=Path('');stage=Path(__file__).resolve().parent
result=json.loads((root/'build/all_results.json').read_text())
assert result['status']=='PASS' and result['completed_at_utc']>'2026-10-15T11:29:00', 'Finish and archive acceptance e first'
assert (root/'docs/rtl_uvm_continuation_20261015e_results.json').is_file(), 'Archive acceptance e first'
for name,target in [('modem_tx_uvm.svh','rtl/tb'),('psk_tx_uvm_tb.sv','rtl/tb'),('run_psk_tx_uvm.py','tools'),('test_psk_tx_uvm.py','tests')]:
    s=(stage/name).read_text().replace("ROOT=Path('')","ROOT=Path(__file__).resolve().parents[1]")
    s=s.replace("\nsys.path.insert(0,str(Path(__file__).resolve().parent))",'')
    if name=='run_psk_tx_uvm.py':
        s=s.replace("f'+incdir+{Path(__file__).resolve().parent}'",'f\'+incdir+{ROOT/"rtl/tb"}\'')
        s=s.replace("Path(__file__).with_name('psk_tx_uvm_tb.sv')","ROOT/'rtl/tb/psk_tx_uvm_tb.sv'")
    (root/target/name).write_text(s)
p=root/'tools/run_tests.py';s=p.read_text()
assert 'def verified_psk_tx_uvm_artifacts(' not in s
point=s.index('\ndef python_tests(')
s=s[:point]+'\n'+(stage/'parent_psk_tx.py').read_text().rstrip()+'\n\n'+s[point:]
s=s.replace("'test_fft_uvm.py','test_dsp_uvm.py'", "'test_fft_uvm.py','test_dsp_uvm.py','test_psk_tx_uvm.py'")
point=s.index("            log=output/'logs/fft_uvm.log'")
extra='''            log=output/'logs/psk_tx_uvm.log'
            result=subprocess.run([sys.executable,str(ROOT/'tools/run_psk_tx_uvm.py'),'--suite','all'],
                                  capture_output=True,text=True)
            log.write_text(result.stdout+result.stderr)
            if result.returncode:raise RuntimeError(f'PSK/QAM TX UVM failed: {log}')
            report=ROOT/'build/rtl/psk_tx_uvm/all_results.json'
            pilot=json.loads(report.read_text())
            child_artifacts.extend([report,log,*verified_psk_tx_uvm_artifacts(pilot)])
            summary['rtl_psk_tx_uvm']=dict(result=str(report.relative_to(ROOT)),log=str(log.relative_to(ROOT)))
'''
s=s[:point]+extra+s[point:];p.write_text(s)
