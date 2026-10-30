"""Packet RX acceptance: original truth, full-width soft values and reset conservation."""
import copy
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from run_packet_rx_uvm import (PROFILES, SCENARIOS, CONTROLS, VECTOR_CONTROLS, CPM_CONTROLS,
                               prepare_vectors, parse_packet_report, verify_negative)
from run_tests import verified_packet_rx_uvm_artifacts
from regression_evidence import begin, finish
import uvm_floating_reference as floating


def report_text(model,scenario='stream'):
    partial,terminal=scenario=='midreset',scenario=='outreset'
    warm=partial or terminal
    prefix=600 if partial else 767 if terminal else 0
    extra=model['warm_samples'] if partial else model['warm_wave_samples'] if terminal else 0
    cfg=384 if warm else 288 if scenario=='cfgreset' else 192
    errors=model['payload_errors'];floats=model['float_payload_errors']
    lines=[f'UVM PILOT SER frame={f} errors={e} symbols=576' for f,e in enumerate(errors)]
    lines += [f'UVM PILOT FLOAT SER frame={f} rtl_errors={e} float_errors={flt} delta={e-flt} symbols=576'
              for f,(e,flt) in enumerate(zip(errors,floats))]
    lines += [f'UVM PILOT FLOAT SUMMARY frames=4 rtl_errors={sum(errors)} float_errors={sum(floats)} symbols=2304',
              f'UVM PACKET PILOT checked={3072+prefix} frames=4 acquisitions={4+int(warm)} errors={sum(errors)} payload=2304 '
              f'discarded={768-prefix if warm else 0} resets={1+int(warm or scenario=="cfgreset")} '
              f'partial_payload_discarded={prefix-192 if warm else 0} partial_errors_discarded={model["immutable_warm_error_prefix"][prefix] if warm else 0}',
              f'UVM PILOT HANDSHAKES cfg={cfg} input={model["samples"]+extra} stalls={0 if scenario=="stream" else 100} pending_resets={int(warm)}',
              f'UVM PILOT PROFILE label_bits={model["label_bits"]} index_bits={model["label_bits"]} gaincfg=0 cfg_max={model["cfg_label_max"]} label_max={model["decoded_label_max"]} index_max={model["index_max"]}',
              f'UVM RX KIND packet={model["kind"]} gaps={30 if scenario=="gaps" else 0}',
              f'UVM RX EPOCHS frames={0 if model["kind"]==1 else 4} checks={0 if model["kind"]==1 else 4168}',
              f'UVM RX INPUTS checked={model["samples"]+extra} expected={model["samples"]+(model["warm_wave_samples"] if warm else 0)} discarded={model["warm_wave_samples"]-extra if partial else 0}',
              'UVM_ERROR : 0','UVM_FATAL : 0']
    return '\n'.join(lines)


class TestPacketRxUvm(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.folder=Path(cls.temporary.name)
        cls.models={name:prepare_vectors(cls.folder/name,name) for name in PROFILES}
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_original_native_waves_truth_and_soft_values_preserved(self):
        from oqpsk_cases import vectors as oqpsk_vectors
        from cpm_cases import vectors as cpm_vectors
        for name,model in self.models.items():
            source=self.folder/name;legacy=self.folder/(name+'_native')
            if name=='oqpsk':oqpsk_vectors(legacy,frames=4,count=768,tracking=False)
            else:cpm_vectors(legacy,name=='gmsk',frames=4,count=768)
            original=floating.rows(legacy/'rx_wave.txt',3)
            end=np.flatnonzero(original[:,2])[3]+1
            np.testing.assert_array_equal(floating.rows(source/'rx_wave.txt',3),original[:end])
            trace=floating.rows(source/'rx_trace.txt',10)
            native=floating.rows(legacy/'rx_out.txt',4 if name=='oqpsk' else 3)[:3072]
            np.testing.assert_array_equal(trace[:,0],native[:,0])
            np.testing.assert_array_equal(trace[:,1],native[:,1] if name=='oqpsk' else np.zeros(3072,dtype=int))
            truth_file='tx_symbols.txt' if name=='oqpsk' else 'tx_bits.txt'
            np.testing.assert_array_equal(trace[:,9],floating.rows(legacy/truth_file,2)[:3072,0])
            if name=='msk':self.assertGreater(np.max(abs(trace[:,0])),2**31)
            self.assertEqual(model['immutable_warm_error_prefix'][-1],model['payload_errors'][3])

    def test_float_independence_provenance_and_mutation_rejection(self):
        for name in self.models:
            folder=self.folder/name
            expected=floating.floating_decisions(folder,name)
            patches=[mock.patch.object(module,attr,side_effect=AssertionError('Fixed model called'))
                     for modname,module in list(sys.modules.items()) if modname.endswith('_fixed') and module is not None
                     for attr,value in vars(module).items() if callable(value) and not isinstance(value,type)
                     and getattr(value,'__module__',None)==modname]
            for patch in patches:patch.start()
            try:actual=floating.floating_decisions(folder,name)
            finally:
                for patch in patches:patch.stop()
            np.testing.assert_array_equal(actual,expected)
            for key in ('decision','errorcount','denominator'):
                target=self.folder/(name+'_float_'+key)
                floating.mutate_float_metadata(folder,target,key,alphabet=PROFILES[name][1])
                with self.assertRaises(ValueError):floating.validate_float_reference(target,name)

    def test_all_scenarios_widths_and_original_partial_errors(self):
        for model in self.models.values():
            for active in (1,0):
                for scenario in SCENARIOS:
                    row=parse_packet_report(report_text(model,scenario),model,scenario,active)
                    self.assertEqual(row['profile'],model['profile'])
                    self.assertEqual(row['soft_bits'],18 if model['profile']=='oqpsk' else 36)
                    self.assertEqual(row['terminal_last_discarded'],int(scenario=='outreset'))
                    self.assertEqual(row['checked']+row['discarded_expected_symbols'],3072+(768 if scenario in ('midreset','outreset') else 0))

    def test_false_success_wrong_physical_kind_and_reset_counts_rejected(self):
        for model in self.models.values():
            text=report_text(model,'outreset')
            for bad in (text+text,text.replace('UVM_FATAL : 0','UVM_FATAL : 1'),
                        text.replace(f'packet={model["kind"]}','packet=0'),
                        text.replace('discarded=1 resets=2','discarded=2 resets=2'),
                        text.replace('partial_payload_discarded=575','partial_payload_discarded=576'),
                        text.replace('pending_resets=1','pending_resets=0'),
                        text.replace('resets=2','resets=3'),text.replace('index_bits=','wrong_bits='),
                        text.replace('UVM RX INPUTS checked=','UVM RX INPUTS wrong=')):
                with self.subTest(profile=model['profile'],bad=bad),self.assertRaises(RuntimeError):
                    parse_packet_report(bad,model,'outreset',0)
            with self.assertRaises(RuntimeError):parse_packet_report(text,model,'outreset',0,13)
            with self.assertRaises(RuntimeError):parse_packet_report(report_text(model,'gaps').replace('gaps=30','gaps=0'),model,'gaps',1)

    def test_negative_fatal_category_and_completion_guard(self):
        for tag in ('NUMERIC','SER','PROTOCOL','STALL','FLOAT_SER'):
            text=f'UVM_FATAL @ 1: reporter [{tag}] fault\nUVM_FATAL : 1'
            verify_negative(text,13,tag)
            for bad,rc in ((text,0),(text.replace(f'[{tag}]','[OTHER]'),13),
                           (text.replace('UVM_FATAL : 1','UVM_FATAL : 0'),13),
                           (text+'\n'+report_text(self.models['oqpsk']),13)):
                with self.assertRaises(RuntimeError):verify_negative(bad,rc,tag)

    def test_parent_rejects_partial_profiles_missing_controls_and_bad_artifacts(self):
        records={}
        for name,model in self.models.items():
            for active in (1,0):
                for scenario in SCENARIOS:records[f'{name}_{scenario}_reset_{active}']=parse_packet_report(report_text(model,scenario),model,scenario,active)
                controls={**{k:v[0] for k,v in CONTROLS.items()},**VECTOR_CONTROLS}
                if name!='oqpsk':controls.update({k:v[0] for k,v in CPM_CONTROLS.items()})
                for key,tag in controls.items():
                    records[f'{name}_negative_{key}_reset_{active}']=dict(returncode=13,detected_tag=tag)
            for key in ('decision','errorcount','denominator'):records[f'{name}_validator_rejects_float_{key}']=dict(rejected='digest')
        self.assertEqual(len(CONTROLS)+len(VECTOR_CONTROLS),18)
        log=self.folder/'coverage.log';log.write_text('packet fixture')
        original=dict(finish(begin(),[log]),status='PASS',profiles='all',records=records)
        self.assertEqual(verified_packet_rx_uvm_artifacts(original),[log])
        for fault in ('profile','missing_scenario','width','float','missing_control','tag','rc0','bool_rc','validator','artifact'):
            data=copy.deepcopy(original)
            if fault=='profile':data['profiles']='oqpsk'
            elif fault=='missing_scenario':data['records'].pop('gmsk_outreset_reset_0')
            elif fault=='width':data['records']['msk_stream_reset_1']['soft_bits']=18
            elif fault=='float':data['records']['oqpsk_gaps_reset_0'].pop('float_per_frame')
            elif fault=='missing_control':data['records'].pop('gmsk_negative_acquisition_x_reset_1')
            elif fault=='tag':data['records']['oqpsk_negative_warm_ser_reset_0']['detected_tag']='NUMERIC'
            elif fault=='rc0':data['records']['msk_negative_input_data_reset_0']['returncode']=0
            elif fault=='bool_rc':data['records']['msk_negative_input_data_reset_0']['returncode']=True
            elif fault=='validator':data['records'].pop('msk_validator_rejects_float_errorcount')
            else:data['artifact_hashes']={}
            with self.subTest(fault=fault),self.assertRaises(RuntimeError):verified_packet_rx_uvm_artifacts(data)
        log.write_text('changed')
        with self.assertRaisesRegex(RuntimeError,'artifact'):verified_packet_rx_uvm_artifacts(original)


if __name__=='__main__':unittest.main()
