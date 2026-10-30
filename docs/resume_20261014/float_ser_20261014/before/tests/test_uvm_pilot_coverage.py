"""Parent regression rejects partial successful UVM pilot reports."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from regression_evidence import begin,finish
from run_tests import verified_bpsk_uvm_artifacts


def coverage():
    records={}
    for profile,prefix,scenarios in (
            ('bpsk','',('stream','stalled','midreset','cfgreset')),
            ('bpsk_tx','tx_',('stream','gaps','stalled','midreset','outreset')),
            ('qpsk_diff','qpsk_diff_',('stream','stalled','midreset','cfgreset')),
            ('psk8_fb','psk8_fb_',('stream','stalled','midreset','cfgreset'))):
        for scenario in scenarios:
            for active in (1,0):
                records[f'{prefix}{scenario}_reset_{active}']=dict(profile=profile,scenario=scenario,reset_active=active)
    for prefix,controls in (
            ('',{'numeric':'NUMERIC','ser':'SER','valid_x':'PROTOCOL','ready_x':'PROTOCOL'}),
            ('tx_',{'numeric':'NUMERIC','s_valid_x':'PROTOCOL','s_ready_x':'PROTOCOL','m_valid_x':'PROTOCOL',
                    'm_ready_x':'PROTOCOL','data_x':'NUMERIC','held_data':'STALL'}),
            ('qpsk_diff_',{'numeric':'NUMERIC','ser':'SER','label_high_bit':'NUMERIC','valid_x':'PROTOCOL',
                           'ready_x':'PROTOCOL','gain_ready_x':'PROTOCOL','warm_ser':'SER'}),
            ('psk8_fb_',{'numeric':'NUMERIC','ser':'SER','label_high_bit':'NUMERIC','valid_x':'PROTOCOL',
                        'ready_x':'PROTOCOL','warm_ser':'SER'})):
        for name,tag in controls.items():
            for active in (1,0):records[f'{prefix}negative_{name}_reset_{active}']=dict(detected_tag=tag,returncode=13)
    return records


class TestUvmPilotCoverage(unittest.TestCase):
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
                          'negative_missing','wrong_tag','negative_rc0','negative_bool','no_artifacts','partial_profiles','qpsk_missing','psk_negative_missing'):
                data=copy.deepcopy(original)
                if fault=='rx_only':data['pilot']='rx'
                elif fault=='partial_profiles':data['rx_profile_selection']='bpsk'
                elif fault=='qpsk_missing':data['records'].pop('qpsk_diff_midreset_reset_0')
                elif fault=='psk_negative_missing':data['records'].pop('psk8_fb_negative_warm_ser_reset_1')
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


if __name__=='__main__':unittest.main()
