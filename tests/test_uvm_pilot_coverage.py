"""Parent regression rejects partial successful UVM pilot reports."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from regression_evidence import begin,finish
from run_tests import verified_bpsk_uvm_artifacts


sys.path.insert(0,str(ROOT/'common/python'))
import psk_fixed
RX=[p.name for p in psk_fixed.PROFILES if p.name!='bpsk']


def coverage():
    records={};floats={f'float_{k}':'FLOAT_SER' for k in ('decision','errorcount','denominator')}
    for profile,prefix,scenarios in [('bpsk_tx','tx_',('stream','gaps','stalled','midreset','outreset'))]+[
            (name,'' if name=='bpsk' else name+'_',('stream','stalled','midreset','cfgreset')) for name in ['bpsk',*RX]]:
        for scenario in scenarios:
            for active in (1,0):
                records[f'{prefix}{scenario}_reset_{active}']=dict(profile=profile,scenario=scenario,reset_active=active)
                if profile!='bpsk_tx':records[f'{prefix}{scenario}_reset_{active}']['float_per_frame']=[dict(rtl_errors=3,float_errors=1,delta=2)]*4
        if profile!='bpsk_tx':
            for kind in ('decision','errorcount','denominator'):records[f'{prefix}validator_rejects_float_{kind}']=dict(rejected='digest')
    controls=[('',{'numeric':'NUMERIC','ser':'SER','valid_x':'PROTOCOL','ready_x':'PROTOCOL',**floats}),
              ('tx_',{'numeric':'NUMERIC','s_valid_x':'PROTOCOL','s_ready_x':'PROTOCOL','m_valid_x':'PROTOCOL',
                      'm_ready_x':'PROTOCOL','data_x':'NUMERIC','held_data':'STALL'})]
    for name in RX:
        controls.append((name+'_',{'numeric':'NUMERIC','ser':'SER','label_high_bit':'NUMERIC','valid_x':'PROTOCOL','ready_x':'PROTOCOL',
                                   'warm_ser':'SER',**floats,**({'gain_ready_x':'PROTOCOL'} if name=='qpsk_diff' else {})}))
    for prefix,names in controls:
        for name,tag in names.items():
            for active in (1,0):records[f'{prefix}negative_{name}_reset_{active}']=dict(detected_tag=tag,returncode=13)
    return records


class TestUvmPilotCoverage(unittest.TestCase):
    def test_parallel_profile_libraries_preserve_every_result_and_artifact(self):
        import run_bpsk_uvm as runner
        profiles=[SimpleNamespace(name=name) for name in ('a','b','c')]
        def run_one(output,bindir,uvm,files,selected):
            self.assertEqual(len(selected),1)
            name=selected[0].name;files.append(Path('/tmp')/(name+'.log'))
            return {name:dict(checked=10)}
        files=[]
        with mock.patch.object(runner,'_run_profiles_serial_hdl',side_effect=run_one) as run:
            records=runner.run_profile_hdl(None,None,None,files,profiles,jobs=2)
        self.assertEqual(set(records),{'a','b','c'});self.assertEqual(run.call_count,3)
        self.assertCountEqual(files,[Path('/tmp')/(p.name+'.log') for p in profiles])

    def test_full_scope_preserves_verified_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'pilot.log';log.write_text('coverage fixture')
            data=dict(finish(begin(),[log]),status='PASS',pilot='both',rx_profile_selection='all',records=coverage())
            self.assertEqual(verified_bpsk_uvm_artifacts(data),[log])
            log.write_text('changed')
            with self.assertRaisesRegex(RuntimeError,'artifact'):verified_bpsk_uvm_artifacts(data)

    def test_partial_scope_or_false_healthy_controls_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            log=Path(directory)/'pilot.log';log.write_text('coverage fixture')
            original=dict(finish(begin(),[log]),status='PASS',pilot='both',rx_profile_selection='all',records=coverage())
            for fault in ('rx_only','tx_missing','rx_missing','wrong_scenario','reset_bool','wrong_profile',
                          'negative_missing','wrong_tag','negative_rc0','negative_bool','no_artifacts','partial_profiles','qpsk_missing','psk_negative_missing',
                          'float_missing','float_delta','float_negative_missing','validator_missing',
                          'qam64_missing','pi4_negative_missing'):
                data=copy.deepcopy(original)
                if fault=='rx_only':data['pilot']='rx'
                elif fault=='partial_profiles':data['rx_profile_selection']='bpsk'
                elif fault=='qpsk_missing':data['records'].pop('qpsk_diff_midreset_reset_0')
                elif fault=='psk_negative_missing':data['records'].pop('psk8_fb_negative_warm_ser_reset_1')
                elif fault=='float_missing':data['records']['qpsk_diff_stream_reset_1'].pop('float_per_frame')
                elif fault=='float_delta':data['records']['midreset_reset_0']['float_per_frame'][3]=dict(rtl_errors=3,float_errors=1,delta=0)
                elif fault=='float_negative_missing':data['records'].pop('psk8_fb_negative_float_denominator_reset_0')
                elif fault=='validator_missing':data['records'].pop('validator_rejects_float_decision')
                elif fault=='qam64_missing':data['records'].pop('qam64_stalled_reset_1')
                elif fault=='pi4_negative_missing':data['records'].pop('pi4_negative_float_errorcount_reset_0')
                elif fault=='tx_missing':data['records'].pop('tx_outreset_reset_0')
                elif fault=='rx_missing':data['records'].pop('cfgreset_reset_1')
                elif fault=='wrong_scenario':data['records']['tx_stream_reset_0']['scenario']='stalled'
                elif fault=='reset_bool':data['records']['stream_reset_1']['reset_active']=True
                elif fault=='wrong_profile':data['records']['stream_reset_1']['profile']='qpsk'
                elif fault=='negative_missing':data['records'].pop('tx_negative_data_x_reset_0')
                elif fault=='wrong_tag':data['records']['negative_ser_reset_0']['detected_tag']='NUMERIC'
                elif fault=='negative_rc0':data['records']['tx_negative_held_data_reset_1']['returncode']=0
                elif fault=='negative_bool':data['records']['negative_numeric_reset_1']['returncode']=True
                else:data['artifact_hashes']={}
                with self.subTest(fault=fault),self.assertRaises(RuntimeError):verified_bpsk_uvm_artifacts(data)


    def test_parent_and_runner_require_every_shared_core_profile(self):
        from run_tests import UVM_RX_PROFILES
        from run_bpsk_uvm import RX_PROFILES
        self.assertEqual(list(UVM_RX_PROFILES),RX);self.assertEqual(list(RX_PROFILES),RX);self.assertEqual(len(RX),13)


if __name__=='__main__':unittest.main()
