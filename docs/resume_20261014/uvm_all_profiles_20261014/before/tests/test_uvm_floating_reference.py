"""Independent float SER reference for the RX UVM: independence, provenance, negatives."""
from pathlib import Path
import copy
import shutil
import sys
import tempfile
import unittest
from unittest import mock
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tests'))
import uvm_floating_reference as ref
from run_bpsk_uvm import prepare_vectors,prepare_profile_vectors,parse_float,poison_truth,FLOAT_NEGATIVES,RX_PROFILES
from test_bpsk_uvm_evidence import float_report_text


def _banned(*args,**kwargs):raise AssertionError('Fixed-point receiver/combiner used by float reference')


class TestUvmFloatingReference(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary=tempfile.TemporaryDirectory();cls.folder=Path(cls.temporary.name)
        cls.models={'bpsk':prepare_vectors(cls.folder/'bpsk')}
        for name,profile in RX_PROFILES.items():cls.models[name]=prepare_profile_vectors(cls.folder/name,profile)
        cls.alphabet=dict(bpsk=2,qpsk_diff=4,psk8_fb=8)
    @classmethod
    def tearDownClass(cls):cls.temporary.cleanup()

    def test_original_reference_values_and_shapes(self):
        expected=dict(bpsk=[0,0,0,54],qpsk_diff=[0,0,16,308],psk8_fb=[0,0,0,408])
        for name,model in self.models.items():
            self.assertEqual(model['float_payload_errors'],expected[name]);self.assertEqual(model['float_payload_symbols'],[576]*4)
            decisions=ref.floating_decisions(self.folder/name,name)
            self.assertEqual(decisions.shape,(4,768));self.assertTrue(np.all((decisions>=0)&(decisions<self.alphabet[name])))
            ref.validate_float_reference(self.folder/name,name)

    def test_no_fixed_point_module_participates(self):
        for name in self.models:
            original=ref.floating_decisions(self.folder/name,name)
            patches=[mock.patch.object(module,attr,_banned) for mname,module in list(sys.modules.items())
                     if mname.endswith('_fixed') and module is not None
                     for attr,value in vars(module).items() if callable(value) and not isinstance(value,type) and getattr(value,'__module__',None)==mname]
            self.assertTrue(patches)
            for p in patches:p.start()
            try:again=ref.floating_decisions(self.folder/name,name)
            finally:
                for p in patches:p.stop()
            np.testing.assert_array_equal(original,again)

    def test_truth_change_leaves_decisions_and_moves_only_score(self):
        for name in self.models:
            target=self.folder/(name+'_truth');poison_truth(self.folder/name,target,alphabet=self.alphabet[name])
            np.testing.assert_array_equal(ref.floating_decisions(self.folder/name,name),ref.floating_decisions(target,name))
            with self.assertRaisesRegex(ValueError,'truth'):ref.validate_float_reference(target,name)

    def test_simo_uses_q15_pins_gains_and_relative_variances(self):
        folder=self.folder/'qpsk_diff';gains=list(map(int,(folder/'gains.txt').read_text().split()[1:]))
        raw=ref.rows(folder/'rx_wave.txt',5);calls=[];real=ref.real.maximal_ratio_combine
        def record(branches,g,v):calls.append((branches,g,v));return real(branches,g,v)
        with mock.patch.object(ref.real,'maximal_ratio_combine',record):ref.floating_decisions(folder,'qpsk_diff')
        self.assertEqual(len(calls),4)
        branches,g,v=calls[0];stop=int(np.flatnonzero(raw[:,4])[0])+1
        self.assertEqual(g,[complex(gains[0],gains[1])/32768,complex(gains[2],gains[3])/32768]);self.assertEqual(list(v),gains[4:])
        np.testing.assert_array_equal(branches[0],(raw[:stop,0]+1j*raw[:stop,1])/32768)
        np.testing.assert_array_equal(branches[1],(raw[:stop,2]+1j*raw[:stop,3])/32768)

    def test_metadata_negatives_change_one_file_and_are_rejected(self):
        for name in self.models:
            for kind in FLOAT_NEGATIVES:
                target=self.folder/f'{name}_{kind}'
                changed=ref.mutate_float_metadata(self.folder/name,target,kind,alphabet=self.alphabet[name])
                self.assertEqual(changed,'float_decisions.txt' if kind=='decision' else 'float_expected.txt')
                with self.assertRaises(ValueError):ref.validate_float_reference(target,name)
                # Even with a recomputed digest the independent rerun must still reject.
                import json
                meta=json.loads((target/'float_reference.json').read_text());meta['float_decisions_sha256']=ref._sha(target/'float_decisions.txt')
                meta['float_expected_sha256']=ref._sha(target/'float_expected.txt');(target/'float_reference.json').write_text(json.dumps(meta))
                with self.assertRaises(ValueError):ref.validate_float_reference(target,name)

    def test_waveform_or_gain_provenance_change_rejected(self):
        for name,file in (('bpsk','rx_wave.txt'),('qpsk_diff','gains.txt'),('psk8_fb','preamble.txt')):
            target=self.folder/f'{name}_provenance';shutil.copytree(self.folder/name,target)
            lines=(target/file).read_text().splitlines();parts=lines[1].split();parts[0]=str(int(parts[0])^1);lines[1]=' '.join(parts)
            (target/file).write_text('\n'.join(lines)+'\n')
            with self.assertRaisesRegex(ValueError,'provenance'):ref.validate_float_reference(target,name)

    def test_uvm_float_markers_parsed_and_tampering_rejected(self):
        model=self.models['qpsk_diff'];rows=[(f,e,576) for f,e in enumerate(model['payload_errors'])]
        text=float_report_text(model);r=parse_float(text,model,rows,576)
        self.assertEqual(r['float_payload_errors'],sum(model['float_payload_errors']))
        self.assertEqual([x['delta'] for x in r['float_per_frame']],[a-b for a,b in zip(model['payload_errors'],model['float_payload_errors'])])
        last=f'float_errors={model["float_payload_errors"][3]} delta'
        for bad in (text.replace(last,f'float_errors={model["float_payload_errors"][3]+1} delta'),text.replace('symbols=576','symbols=575',1),
                    text.replace('frame=1 ','frame=2 ',1),text.rsplit('\n',1)[0],text+'\n'+text,
                    text.replace(f'delta={model["payload_errors"][3]-model["float_payload_errors"][3]}','delta=0')):
            with self.subTest(text=bad),self.assertRaises(RuntimeError):parse_float(bad,model,rows,576)
        broken=copy.deepcopy(model);broken['float_payload_symbols'][0]=575
        with self.assertRaises(RuntimeError):parse_float(text,broken,rows,576)


if __name__=='__main__':unittest.main()
