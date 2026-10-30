"""UVM report completion and immutable truth-fault isolation, no simulator mocks."""
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from run_bpsk_uvm import parse_report,verify_negative,poison_truth,prepare_vectors,parse_tx_report,verify_tx_negative,prepare_tx_vectors,TX_SCENARIOS,prepare_profile_vectors,parse_profile_report,poison_profile_warm_truth,RX_PROFILES
from regression_evidence import digest


MODEL=dict(frames=4,symbols=3072,samples=24731,payload_errors=[0,0,0,58])


def report_text(scenario='stream'):
    rows='\n'.join(f'UVM PILOT SER frame={i} errors={error} symbols=576' for i,error in enumerate(MODEL['payload_errors']))
    mid=scenario=='midreset';cfg=scenario=='cfgreset'
    checked,discarded,acquired,resets=(3372,468,5,2) if mid else (3072,0,4,2 if cfg else 1)
    count=384 if mid else 288 if cfg else 192
    inputs=MODEL['samples']+(4200 if mid else 0)
    stalls=0 if scenario=='stream' else 100
    return (rows+'\n'+f'UVM BPSK PILOT checked={checked} frames=4 acquisitions={acquired} errors=58 payload=2304 discarded={discarded} resets={resets} partial_payload_discarded={108 if mid else 0} partial_errors_discarded={13 if mid else 0}\n'
            +f'UVM PILOT HANDSHAKES cfg={count} input={inputs} stalls={stalls} pending_resets={int(mid)}\nUVM_ERROR : 0\nUVM_FATAL : 0\n')


class TestBpskUvmEvidence(unittest.TestCase):
    def test_complete_reports_reset_discard_accounting_and_handshakes(self):
        for scenario in ('stream','stalled','midreset','cfgreset'):
            result=parse_report(report_text(scenario),MODEL,scenario,1)
            self.assertEqual(result['frames'],4);self.assertEqual(result['payload_errors'],58)
            self.assertEqual(result['ser'],58/2304)
        mid=parse_report(report_text('midreset'),MODEL,'midreset',0)
        self.assertEqual(mid['checked']+mid['discarded_expected_symbols'],3072+768)
        self.assertEqual(mid['pending_resets'],1)

    def test_missing_markers_failed_uvm_unexercised_reset_and_extra_counts_rejected(self):
        text=report_text('midreset')
        for candidate in [text.replace('UVM PILOT SER frame=1 errors=0 symbols=576\n',''),
                          text.replace('discarded=468','discarded=0'),text.replace('acquisitions=5','acquisitions=4'),
                          text.replace('cfg=384','cfg=192'),text.replace('input=28931','input=24731'),
                          text.replace('stalls=100','stalls=0'),text.replace('pending_resets=1','pending_resets=0'),
                          text.replace('UVM_ERROR : 0','UVM_ERROR : 1'),text.replace('symbols=576','symbols=577'),
                          text.replace('partial_payload_discarded=108','partial_payload_discarded=0'),
                          text.replace('partial_errors_discarded=13','partial_errors_discarded=0')]:
            with self.subTest(text=candidate),self.assertRaises(RuntimeError):parse_report(candidate,MODEL,'midreset',1)
        with self.assertRaises(RuntimeError):parse_report(report_text(),MODEL,'stream',1,13)

    def test_zero_payload_is_undefined(self):
        text='UVM PILOT SER frame=0 errors=0 symbols=0\nUVM BPSK PILOT checked=192 frames=1 acquisitions=1 errors=0 payload=0 discarded=0 resets=1 partial_payload_discarded=0 partial_errors_discarded=0\nUVM PILOT HANDSHAKES cfg=192 input=1600 stalls=0 pending_resets=0\nUVM_ERROR : 0\nUVM_FATAL : 0\n'
        result=parse_report(text,dict(frames=1,symbols=192,samples=1600,payload_errors=[0]),'stream',1)
        self.assertIsNone(result['ser']);self.assertFalse(result['defined'])

    def test_negative_needs_nonzero_right_category_fatal_count_and_no_completion(self):
        for category in ('NUMERIC','SER','PROTOCOL'):
            text=f'UVM_FATAL @ 1: reporter [{category}] mismatch\nUVM_FATAL : 1\n'
            verify_negative(text,13,category)
            for output,rc in [(text,0),(text.replace('UVM_FATAL : 1','UVM_FATAL : 0'),13),
                              (text.replace(f'[{category}]','[OTHER]'),13),(text+report_text(),13)]:
                with self.subTest(category=category,rc=rc),self.assertRaises(RuntimeError):verify_negative(output,rc,category)

    def test_truth_negative_preserves_wave_acquisition_numeric_and_original_error_metadata(self):
        with tempfile.TemporaryDirectory() as folder:
            folder=Path(folder);source=folder/'source';target=folder/'poison'
            model=prepare_vectors(source);self.assertEqual({k:model[k] for k in MODEL},MODEL)
            self.assertEqual(model['float_payload_errors'],[0,0,0,54]);self.assertEqual(model['float_payload_symbols'],[576]*4)
            poison_truth(source,target)
            for name in ('rx_wave.txt','rx_acquire.txt','preamble.txt','payload_expected.txt','float_decisions.txt','float_expected.txt','float_reference.json'):
                self.assertEqual(digest(source/name),digest(target/name))
            original=[line.split() for line in (source/'rx_trace.txt').read_text().splitlines()]
            poison=[line.split() for line in (target/'rx_trace.txt').read_text().splitlines()]
            changed=[index for index,(a,b) in enumerate(zip(original,poison)) if a!=b]
            self.assertEqual(changed,[193]);self.assertEqual(original[193][:9],poison[193][:9])
            self.assertNotEqual(original[193][9],poison[193][9])


TX_MODEL=dict(frames=5,frame_symbols=[1,2,33,192,768],input_symbols=996,output_samples=8128)


def tx_report_text(scenario='stream'):
    mid=scenario=='midreset';out=scenario=='outreset';reset=mid or out
    before=111 if mid else 295 if out else 0
    discarded=6065 if mid else 1 if out else 0
    expected=14304 if mid else 8424 if out else 8128
    inputs=1012 if mid else 1029 if out else 996
    expected_inputs=1764 if mid else inputs
    rows='\n'.join(f'UVM TX FRAME frame={f} inputs={n} samples={8*n+32}' for f,n in enumerate(TX_MODEL['frame_symbols']))
    return (rows+'\n'+f'UVM BPSK TX checked={8128+before} frames=5 input={inputs} discarded={discarded} discarded_inputs={752 if mid else 0} expected={expected} expected_inputs={expected_inputs} resets={1+int(reset)} before_reset={before} pending_resets={int(reset)} held_last_resets={int(out)}\n'
            +f'UVM TX HANDSHAKES input={inputs} output={8128+before} input_stalls=10 output_stalls={10 if scenario in ("stalled","midreset","outreset") else 0} ready_gaps={232 if scenario=="gaps" else 0} pending_resets={int(reset)}\nUVM_ERROR : 0\nUVM_FATAL : 0\n')


class TestBpskTxUvmEvidence(unittest.TestCase):
    def test_actual_handshakes_frames_and_reset_conservation(self):
        for polarity in (0,1):
            for scenario in TX_SCENARIOS:
                r=parse_tx_report(tx_report_text(scenario),TX_MODEL,scenario,polarity)
                self.assertEqual(r['frames'],5);self.assertEqual(r['input_checked'],r['input_handshakes'])
                self.assertEqual(r['checked']+r['discarded_expected_samples'],r['expected_samples'])
                self.assertEqual(r['input_checked']+r['discarded_expected_inputs'],r['expected_inputs'])
        r=parse_tx_report(tx_report_text('outreset'),TX_MODEL,'outreset',0)
        self.assertEqual(r['samples_before_reset'],295);self.assertEqual(r['discarded_expected_samples'],1)
        with self.assertRaises(RuntimeError):parse_tx_report(tx_report_text(),TX_MODEL,'cfgreset',1)

    def test_failed_duplicate_incomplete_counts_and_unexercised_controls(self):
        text=tx_report_text('midreset')
        for bad in (text.replace('UVM TX FRAME frame=2 inputs=33 samples=296\n',''),text+text,
                    text.replace('input=1012','input=996'),text.replace('discarded_inputs=752','discarded_inputs=0'),
                    text.replace('expected=14304','expected=8128'),text.replace('before_reset=111','before_reset=0'),
                    text.replace('pending_resets=1','pending_resets=0'),text.replace('resets=2','resets=1'),
                    text.replace('input_stalls=10','input_stalls=0'),text.replace('output_stalls=10','output_stalls=0'),
                    text.replace('UVM_ERROR : 0','UVM_ERROR : 1'),text.replace('samples=296','samples=295')):
            with self.subTest(text=bad),self.assertRaises(RuntimeError):parse_tx_report(bad,TX_MODEL,'midreset',1)
        with self.assertRaises(RuntimeError):parse_tx_report(tx_report_text(),TX_MODEL,'stream',1,13)
        with self.assertRaises(RuntimeError):parse_tx_report(tx_report_text('gaps').replace('ready_gaps=232','ready_gaps=0'),TX_MODEL,'gaps',1)
        inconsistent=dict(TX_MODEL,output_samples=8000)
        with self.assertRaises(RuntimeError):parse_tx_report(tx_report_text(),inconsistent,'stream',1)

    def test_composed_reset_counts_need_real_terminal_fence(self):
        # Preserve total conservation while forging a reset one sample earlier.
        bad=tx_report_text('outreset').replace('checked=8423','checked=8422').replace('output=8423','output=8422').replace('before_reset=295','before_reset=294').replace('discarded=1','discarded=2')
        with self.assertRaises(RuntimeError):parse_tx_report(bad,TX_MODEL,'outreset',0)
        bad=tx_report_text('midreset').replace('checked=8239','checked=8128').replace('output=8239','output=8128').replace('before_reset=111','before_reset=0').replace('discarded=6065','discarded=6176')
        with self.assertRaises(RuntimeError):parse_tx_report(bad,TX_MODEL,'midreset',1)

    def test_negative_requires_right_fatal_nonzero_no_completion(self):
        for category in ('NUMERIC','PROTOCOL','STALL'):
            text=f'UVM_FATAL @ 1: reporter [{category}] injected fault\nUVM_FATAL : 1\n'
            verify_tx_negative(text,13,category)
            for output,rc in ((text,0),(text.replace('UVM_FATAL : 1','UVM_FATAL : 0'),13),
                              (text.replace(f'[{category}]','[OTHER]'),13),(text+tx_report_text(),13)):
                with self.subTest(category=category,rc=rc),self.assertRaises(RuntimeError):verify_tx_negative(output,rc,category)

    def test_tx_reference_byte_exact_and_independent_geometry(self):
        from bpsk_cases import generate
        with tempfile.TemporaryDirectory() as temporary:
            folder=Path(temporary);old=folder/'old';new=folder/'uvm'
            generate(old);model=prepare_tx_vectors(new)
            self.assertEqual({k:model[k] for k in TX_MODEL},TX_MODEL)
            self.assertIn('no configuration ports',model['configuration'])
            for name in ('bits.txt','tx.txt'):self.assertEqual((old/name).read_bytes(),(new/name).read_bytes())
            rows=[list(map(int,row.split())) for row in (new/'tx.txt').read_text().splitlines()[1:]]
            stops=[i for i,row in enumerate(rows) if row[2]]
            self.assertEqual(stops,[39,87,383,1951,8127])


def float_report_text(model):
    pairs=list(zip(model['payload_errors'],model['float_payload_errors']))
    return '\n'.join(f'UVM PILOT FLOAT SER frame={f} rtl_errors={r} float_errors={e} delta={r-e} symbols=576' for f,(r,e) in enumerate(pairs))+\
        f'\nUVM PILOT FLOAT SUMMARY frames={len(pairs)} rtl_errors={sum(model["payload_errors"])} float_errors={sum(model["float_payload_errors"])} symbols={576*len(pairs)}'


def profile_report_text(model,scenario):
    mid=scenario=='midreset';cfg=scenario=='cfgreset';prefix=247 if model['simo'] else 246
    total=sum(model['payload_errors']);rows='\n'.join(f'UVM PILOT SER frame={f} errors={e} symbols=576' for f,e in enumerate(model['payload_errors']))
    checked=3072+(prefix if mid else 0);discarded=768-prefix if mid else 0
    gaincfg=(1+int(mid or cfg)) if model['simo'] else 0
    rows+='\n'+float_report_text(model)
    return (rows+'\n'+f'UVM BPSK PILOT checked={checked} frames=4 acquisitions={4+int(mid)} errors={total} payload=2304 discarded={discarded} resets={2 if mid or cfg else 1} partial_payload_discarded={prefix-192 if mid else 0} partial_errors_discarded={model["immutable_warm_error_prefix"][prefix] if mid else 0}\n'
            +f'UVM PILOT HANDSHAKES cfg={384 if mid else 288 if cfg else 192} input={model["samples"]+(4200 if mid else 0)} stalls={0 if scenario=="stream" else 100} pending_resets={int(mid)}\n'
            +f'UVM PILOT PROFILE label_bits={model["label_bits"]} index_bits={model["index_bits"]} gaincfg={gaincfg} cfg_max={model["cfg_label_max"]} label_max={model["decoded_label_max"]} index_max={model["index_max"]}\nUVM_ERROR : 0\nUVM_FATAL : 0\n')


class TestPskRxUvmEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.folder=Path(cls.temporary.name);cls.models={}
        for name,profile in RX_PROFILES.items():cls.models[name]=prepare_profile_vectors(cls.folder/name,profile)
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_original_profile_vectors_full_width_and_immutable_prefix(self):
        from bpsk_cases import receiver_vectors,rtl_parameters
        for name,profile in RX_PROFILES.items():
            model=self.models[name];source=self.folder/name;legacy=self.folder/(name+'_legacy')
            receiver_vectors(legacy,frames=4,count=768,seed=19,profile=profile)
            for file in legacy.glob('*.txt'):self.assertEqual(file.read_bytes(),(source/file.name).read_bytes())
            self.assertEqual(model['parameters'],rtl_parameters(profile))
            self.assertEqual(model['label_bits'],(profile.alphabet-1).bit_length());self.assertEqual(model['index_bits'],(profile.order-1).bit_length())
            self.assertEqual(model['cfg_label_max'],profile.alphabet-1);self.assertEqual(model['decoded_label_max'],profile.alphabet-1)
            rows=[list(map(int,row.split())) for row in (source/'warm_reset_expected.txt').read_text().splitlines()[1:]]
            self.assertEqual(len(rows),769);self.assertEqual(rows[-1],[768,576,model['payload_errors'][3]])
            for prefix,payload,errors in rows:
                self.assertEqual(payload,max(0,prefix-192));self.assertEqual(errors,model['immutable_warm_error_prefix'][prefix])

    def test_actual_profile_counts_and_reset_prefix_errors(self):
        for name,model in self.models.items():
            for polarity in (0,1):
                for scenario in ('stream','stalled','midreset','cfgreset'):
                    r=parse_profile_report(profile_report_text(model,scenario),model,scenario,polarity)
                    self.assertEqual(r['profile'],name);self.assertEqual(r['payload_errors'],sum(model['payload_errors']))
                    if scenario=='midreset':
                        prefix=r['checked']-model['symbols'];self.assertEqual(r['discarded_partial_errors'],model['immutable_warm_error_prefix'][prefix])
                        self.assertEqual(r['gain_handshakes'],2 if model['simo'] else 0)
        # A zero-error partial counter is legal for a genuinely zero-error reference prefix.
        import copy
        model=copy.deepcopy(self.models['psk8_fb']);model['immutable_warm_error_prefix']=[0]*769
        r=parse_profile_report(profile_report_text(model,'midreset'),model,'midreset',1)
        self.assertFalse(r['partial_nonzero_error_counter_exercised'])

    def test_width_gain_prefix_and_duplicated_reports_rejected(self):
        for model in self.models.values():
            text=profile_report_text(model,'midreset');prefix=247 if model['simo'] else 246
            partial=model['immutable_warm_error_prefix'][prefix]
            for bad in (text.replace(f'label_bits={model["label_bits"]}','label_bits=1'),
                        text.replace(f'index_bits={model["index_bits"]}','index_bits=1'),
                        text.replace(f'cfg_max={model["cfg_label_max"]}','cfg_max=1'),
                        text.replace(f'label_max={model["decoded_label_max"]}','label_max=1'),
                        text.replace(f'gaincfg={2 if model["simo"] else 0}','gaincfg=9'),
                        text.replace(f'partial_errors_discarded={partial}',f'partial_errors_discarded={partial+1}'),text+text,
                        text.replace(f'partial_payload_discarded={prefix-192}','partial_payload_discarded=0')):
                with self.subTest(profile=model['profile'],text=bad),self.assertRaises(RuntimeError):parse_profile_report(bad,model,'midreset',1)

    def test_warm_ser_fault_only_truth_leaves_numeric_and_prefix_metadata(self):
        for name,profile in RX_PROFILES.items():
            source=self.folder/name;target=self.folder/(name+'_warm_fault')
            poison_profile_warm_truth(source,target,alphabet=profile.alphabet)
            src=[line.split() for line in (source/'rx_trace.txt').read_text().splitlines()]
            dst=[line.split() for line in (target/'rx_trace.txt').read_text().splitlines()]
            changed=[i for i,(a,b) in enumerate(zip(src,dst)) if a!=b]
            self.assertEqual(changed,[2497]);self.assertEqual(src[2497][:9],dst[2497][:9])
            self.assertNotEqual(src[2497][9],dst[2497][9])
            for file in source.glob('*.txt'):
                if file.name!='rx_trace.txt':self.assertEqual(file.read_bytes(),(target/file.name).read_bytes())


if __name__=='__main__':unittest.main()
