"""Full PSK/QAM label alphabets, independent float TX and mandatory UVM profile coverage."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from run_psk_tx_uvm import PROFILES,TX_SCENARIOS,CONTROLS,prepare_vectors,parse_report,parameters,TX_PARAMETERS,CONFIGS
from run_bpsk_uvm import verify_tx_negative
import modem_core as real


def report_text(name,scenario='stream'):
    profile=PROFILES[name];mid,out=scenario=='midreset',scenario=='outreset';reset=mid or out
    warm=768 if mid else 33 if out else 0;extra=8*warm+32 if reset else 0
    prefix=111 if mid else 295 if out else 0;inputs=996+(16 if mid else 33 if out else 0)
    lines=[f'UVM TX FRAME frame={f} inputs={n} samples={8*n+32}' for f,n in enumerate((1,2,33,192,768))]
    lines.extend([f'UVM PSK TX checked={8128+prefix} frames=5 input={inputs} discarded={extra-prefix} '
                  f'discarded_inputs={warm-(inputs-996)} expected={8128+extra} expected_inputs={996+warm} '
                  f'resets={1+int(reset)} before_reset={prefix} pending_resets={int(reset)} held_last_resets={int(out)}',
                  f'UVM TX HANDSHAKES input={inputs} output={8128+prefix} input_stalls=7000 output_stalls={100 if reset or scenario=="stalled" else 0} '
                  f'ready_gaps={232 if scenario=="gaps" else 0} pending_resets={int(reset)}',
                  f'UVM TX LABELS bits={(profile.alphabet-1).bit_length()} mask={(1<<profile.alphabet)-1}',
                  'UVM PSK TX PARAMETERS '+' '.join(f'{label}={parameters(name)[key]}' for label,key in
                      zip(('order','amplitude','differential','axis','pi4'),TX_PARAMETERS)),
                  'UVM_ERROR : 0','UVM_FATAL : 0'])
    return '\n'.join(lines)


class TestPskTxUvm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.folder=Path(cls.temporary.name)
        cls.models={name:prepare_vectors(cls.folder/name,name) for name in PROFILES}
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_every_label_and_independent_floating_waveform(self):
        for name,profile in PROFILES.items():
            folder=self.folder/name;model=self.models[name]
            source=np.loadtxt(folder/'tx_symbols.txt',skiprows=1,dtype=int)
            expected=np.loadtxt(folder/'tx_out.txt',skiprows=1,dtype=int)
            self.assertEqual(model['input_symbols'],996);self.assertEqual(model['output_samples'],8128)
            self.assertEqual(set(source[:,0]),set(range(profile.alphabet)))
            self.assertEqual(sum(1<<int(v) for v in set(source[:,0])),model['labels_seen_mask'])
            self.assertEqual(int(expected[:,2].sum()),5)
            a=b=0
            for n in model['frame_symbols']:
                size=8*n+32
                # The independent transmitter continues to work with the fixed TX disabled.
                with patch('psk_fixed.transmit',side_effect=AssertionError('Fixed dependency')):
                    reference=real.transmit(real.load_config(ROOT/CONFIGS[name]),source[a:a+n,0])['waveform']
                got=(expected[b:b+size,0]+1j*expected[b:b+size,1])/32768
                self.assertEqual(len(reference),size);self.assertLess(float(np.max(abs(got-reference))),1e-4)
                self.assertEqual(int(expected[b:b+size,2].sum()),1);self.assertEqual(expected[b+size-1,2],1)
                a+=n;b+=size
        self.assertEqual(self.models['qam64']['labels_seen_mask'],18446744073709551615)

    def test_every_scenario_and_polarity(self):
        for name,model in self.models.items():
            for active in (1,0):
                for scenario in TX_SCENARIOS:
                    row=parse_report(report_text(name,scenario),model,scenario,active)
                    self.assertEqual(row['profile'],name+'_tx')
                    self.assertEqual(row['checked']+row['discarded_expected_samples'],row['expected_samples'])
                    self.assertEqual(row['tx_parameters'],parameters(name))

    def test_truncated_masks_mapper_parameters_and_reset_summary_rejected(self):
        for name,model in self.models.items():
            text=report_text(name,'outreset')
            for bad in (text+text,text.replace('UVM_FATAL : 0','UVM_FATAL : 1'),
                        text.replace('mask=','mask=0'),text.replace('bits=','wrong_bits='),
                        text.replace('amplitude=','wrong_amplitude='),text.replace('axis=','wrong_axis='),
                        text.replace('held_last_resets=1','held_last_resets=0'),text.replace('discarded=1 ','discarded=0 ')):
                with self.subTest(profile=name),self.assertRaises(RuntimeError):parse_report(bad,model,'outreset',0)
            with self.assertRaises(RuntimeError):parse_report(text,model,'outreset',False)
        qam=self.models['qam64'];text=report_text('qam64')
        with self.assertRaises(RuntimeError):parse_report(text.replace('18446744073709551615','4294967295'),qam,'stream',1)

    def test_negative_requires_intended_fatal_and_incomplete_transaction(self):
        for tag in ('NUMERIC','PROTOCOL','STALL'):
            text=f'UVM_FATAL @ 1: reporter [{tag}] fault\nUVM_FATAL : 1'
            verify_tx_negative(text,13,tag,modulation='PSK')
            for bad,rc in ((text,0),(text.replace('['+tag+']','[OTHER]'),13),(text+'\n'+report_text('qam64'),13)):
                with self.assertRaises(RuntimeError):verify_tx_negative(bad,rc,tag,modulation='PSK')

    def test_parent_requires_all_profiles_mapper_bits_frames_and_controls(self):
        from run_tests import verified_psk_tx_uvm_artifacts
        from regression_evidence import begin,finish
        records={}
        for name,model in self.models.items():
            for active in (1,0):
                for scenario in TX_SCENARIOS:records[f'{name}_{scenario}_reset_{active}']=parse_report(report_text(name,scenario),model,scenario,active)
                for key,(tag,_,_) in CONTROLS.items():records[f'{name}_negative_{key}_reset_{active}']=dict(returncode=13,detected_tag=tag)
        log=self.folder/'scope.log';log.write_text('PSK TX fixture')
        original=dict(finish(begin(),[log]),status='PASS',profiles='all',records=records)
        self.assertEqual(verified_psk_tx_uvm_artifacts(original),[log])
        for fault in ('profile','missing','mask','width','parameters','frames','terminal','control','tag','rc0','bool_rc','bool_reset','artifact'):
            data=copy.deepcopy(original);r=data['records'];key='qam64_outreset_reset_0'
            if fault=='profile':data['profiles']='qam64'
            elif fault=='missing':r.pop('qpsk_half_diff_midreset_reset_1')
            elif fault=='mask':r[key]['labels_seen_mask']=4294967295
            elif fault=='width':r[key]['label_bits']=5
            elif fault=='parameters':r[key]['tx_parameters']['ORDER']=16
            elif fault=='frames':r[key]['per_frame']=[]
            elif fault=='terminal':r[key]['held_last_resets']=0
            elif fault=='control':r.pop('psk8_rotated_fb_negative_input_high_bit_reset_0')
            elif fault=='tag':r['pi4_negative_held_data_reset_1']['detected_tag']='NUMERIC'
            elif fault=='rc0':r['qam64_negative_imaginary_reset_1']['returncode']=0
            elif fault=='bool_rc':r['qam64_negative_imaginary_reset_1']['returncode']=True
            elif fault=='bool_reset':r[key]['reset_active']=False
            else:data['artifact_hashes']={}
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):verified_psk_tx_uvm_artifacts(data)
        log.write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'artifact'):verified_psk_tx_uvm_artifacts(original)


if __name__=='__main__':unittest.main()
