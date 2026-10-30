"""MSK/GMSK TX geometry, independent waveforms, and complete parent acceptance."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from run_cpm_uvm import PROFILES, CONTROLS, TX_SCENARIOS, prepare_vectors
from run_bpsk_uvm import parse_tx_report
from run_tests import verified_cpm_uvm_artifacts
from regression_evidence import begin, finish
from cpm_cases import CONFIGS, real


def report_text(profile,scenario='stream'):
    tail=32 if profile=='gmsk' else 0
    normal=8128 if profile=='gmsk' else 7968
    mid,out=scenario=='midreset',scenario=='outreset';reset=mid or out
    warm_bits=768 if mid else 33 if out else 0
    warm_samples=8*warm_bits+tail if reset else 0
    prefix=111 if mid else 8*33+tail-1 if out else 0
    inputs=996+(16 if mid else 33 if out else 0)
    lines=[f'UVM TX FRAME frame={f} inputs={n} samples={8*n+tail}' for f,n in enumerate([1,2,33,192,768])]
    lines += [f'UVM {profile.upper()} TX checked={normal+prefix} frames=5 input={inputs} '
              f'discarded={warm_samples-prefix} discarded_inputs={warm_bits-(inputs-996)} '
              f'expected={normal+warm_samples} expected_inputs={996+warm_bits} resets={1+int(reset)} '
              f'before_reset={prefix} pending_resets={int(reset)} held_last_resets={int(out)}',
              f'UVM TX HANDSHAKES input={inputs} output={normal+prefix} input_stalls=7000 '
              f'output_stalls={100 if scenario in ("stalled","midreset","outreset") else 0} '
              f'ready_gaps={232 if scenario=="gaps" else 0} pending_resets={int(reset)}',
              'UVM TX LABELS bits=1 mask=3','UVM_ERROR : 0','UVM_FATAL : 0']
    return '\n'.join(lines)


class TestCpmTxUvm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.folder=Path(cls.temporary.name)
        cls.models={p:prepare_vectors(cls.folder/p,p) for p in PROFILES}
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_independent_floating_transmitter_and_exact_boundaries(self):
        for profile,model in self.models.items():
            cfg=real.load_config(ROOT/CONFIGS[profile=='gmsk'])
            bits=np.loadtxt(self.folder/profile/'tx_symbols.txt',skiprows=1,dtype=int)
            samples=np.loadtxt(self.folder/profile/'tx_out.txt',skiprows=1,dtype=int)
            self.assertEqual(model['input_symbols'],996)
            self.assertEqual(model['output_samples'],8128 if profile=='gmsk' else 7968)
            self.assertEqual(set(bits[:,0]),{0,1})
            self.assertEqual(int(samples[:,2].sum()),5)
            i=j=0
            for n in model['frame_symbols']:
                size=8*n+model['tail']
                expected=real.transmit(cfg,bits[i:i+n,0])['waveform']
                actual=(samples[j:j+size,0]+1j*samples[j:j+size,1])/32768
                self.assertEqual(len(actual),len(expected))
                self.assertLess(np.max(abs(actual-expected)),2e-3 if profile=='gmsk' else 1e-4)
                self.assertEqual(int(samples[j:j+size,2].sum()),1)
                self.assertEqual(samples[j+size-1,2],1)
                i+=n;j+=size

    def test_all_scenarios_and_both_polarities(self):
        for profile,model in self.models.items():
            for active in (1,0):
                for scenario in TX_SCENARIOS:
                    row=parse_tx_report(report_text(profile,scenario),model,scenario,active,modulation=profile.upper())
                    self.assertEqual(row['profile'],profile+'_tx')
                    self.assertEqual(row['checked']+row['discarded_expected_samples'],row['expected_samples'])
                    if scenario=='outreset':self.assertEqual(row['discarded_expected_samples'],1)

    def test_wrong_tail_full_width_reset_and_duplicate_success_rejected(self):
        for profile,model in self.models.items():
            text=report_text(profile,'outreset')
            for bad in (text+text,text.replace('UVM_FATAL : 0','UVM_FATAL : 1'),
                        text.replace('mask=3','mask=1'),text.replace('held_last_resets=1','held_last_resets=0'),
                        text.replace('discarded=1','discarded=2'),text.replace('samples=','wrong_samples=',1)):
                with self.subTest(profile=profile),self.assertRaises(RuntimeError):
                    parse_tx_report(bad,model,'outreset',0,modulation=profile.upper())
            other='MSK' if profile=='gmsk' else 'GMSK'
            with self.assertRaises(RuntimeError):parse_tx_report(text,model,'outreset',0,modulation=other)

    def test_parent_requires_all_profiles_scenarios_and_controls(self):
        records={}
        for profile,model in self.models.items():
            for active in (1,0):
                for scenario in TX_SCENARIOS:
                    records[f'{profile}_{scenario}_reset_{active}']=parse_tx_report(report_text(profile,scenario),model,scenario,active,modulation=profile.upper())
                for key,(tag,_,_) in CONTROLS.items():records[f'{profile}_negative_{key}_reset_{active}']=dict(returncode=13,detected_tag=tag)
        log=self.folder/'coverage.log';log.write_text('CPM fixture')
        original=dict(finish(begin(),[log]),status='PASS',profiles='all',records=records)
        self.assertEqual(verified_cpm_uvm_artifacts(original),[log])
        for fault in ('profile','missing_scenario','width','missing_control','tag','rc0','bool_rc','artifact'):
            data=copy.deepcopy(original)
            if fault=='profile':data['profiles']='msk'
            elif fault=='missing_scenario':data['records'].pop('gmsk_outreset_reset_0')
            elif fault=='width':data['records']['msk_stream_reset_1']['label_bits']=2
            elif fault=='missing_control':data['records'].pop('msk_negative_imaginary_reset_1')
            elif fault=='tag':data['records']['gmsk_negative_held_data_reset_0']['detected_tag']='NUMERIC'
            elif fault=='rc0':data['records']['msk_negative_numeric_reset_0']['returncode']=0
            elif fault=='bool_rc':data['records']['msk_negative_numeric_reset_0']['returncode']=True
            else:data['artifact_hashes']={}
            with self.assertRaises(RuntimeError):verified_cpm_uvm_artifacts(data)
        log.write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'artifact'):verified_cpm_uvm_artifacts(original)


if __name__=='__main__':unittest.main()
