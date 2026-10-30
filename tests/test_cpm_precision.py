"""CPM full-chain accuracy, independent receiver boundaries and failure gates."""
import contextlib
import copy
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import cpm_precision as p


class TestCpmPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=p.report()

    def test_full_chain_all_profiles_and_channels(self):
        self.assertEqual(len(self.result['records']),9)
        self.assertTrue(all(self.result['checks'].values()),self.result['checks'])
        for record in self.result['records']:
            for mode in ('fixed','floating'):
                expected=record[mode]['errors']>20 if record['case']=='low_snr' else record[mode]['errors']==0
                self.assertTrue(expected,(record['profile'],record['case'],mode))

    def test_payload_truth_only_scores_original_indices(self):
        truth=np.zeros(p.COUNT,dtype=int);decoded=truth.copy();decoded[:p.PREAMBLE]=1
        self.assertEqual(p.payload_score(decoded,truth)['errors'],0)
        decoded[-1]=1;self.assertEqual(p.payload_score(decoded,truth)['errors'],1)
        with self.assertRaises(ValueError):p.payload_score(decoded[:-1],truth)

    def test_missing_duplicate_and_nominal_errors_fail(self):
        records=self.result['records']
        self.assertFalse(all(p.check_records(records[:-1]).values()))
        self.assertFalse(all(p.check_records(records+[records[0]]).values()))
        broken=copy.deepcopy(records);broken[1]['floating']['errors']=1
        self.assertFalse(all(p.check_records(broken).values()))
        broken=copy.deepcopy(records);broken[1]['fixed']['status']='failed'
        self.assertFalse(all(p.check_records(broken).values()))

    def test_missing_nodes_and_fake_clean_noise_fail(self):
        broken=copy.deepcopy(self.result['records']);broken[0]['nodes'].clear()
        self.assertFalse(all(p.check_records(broken).values()))
        broken=copy.deepcopy(self.result['records']);broken[-1]['fixed']['errors']=0
        self.assertFalse(all(p.check_records(broken).values()))

    def test_sqnr_circular_distance_handles_wrap_without_fit(self):
        metric=p.metric(np.array([-np.pi+1e-7]),np.array([np.pi-1e-7]),angular=True)
        self.assertLess(metric['max_abs_error'],3e-7)
        shifted=p.metric(np.array([0.1,1.1]),np.array([0.,1.]))
        self.assertAlmostEqual(shifted['max_abs_error'],.1)
        with self.assertRaises(ValueError):p.metric([1],[0])

    def test_coherent_float_does_not_use_integer_receiver_or_acquisition(self):
        cfg=p.real.load_config(ROOT/'modems/gmsk_coherent_demodulation_2010_10_03/config.json')
        bits=np.random.default_rng(p.LABEL_SEED).integers(0,2,p.COUNT)
        wave=p.samples(p.fixed.transmit(bits,True))
        with patch.object(p.fixed,'acquire',side_effect=AssertionError('integer acquisition forbidden')), \
             patch.object(p.fixed,'receive_coherent',side_effect=AssertionError('integer receiver forbidden')), \
             patch.object(p.psk_fixed,'quantize',side_effect=AssertionError('requantization forbidden')), \
             patch.object(p.coherent,'acquire',side_effect=AssertionError('shared fixed acquisition forbidden')):
            result=p.floating_coherent(cfg,wave,bits[:p.PREAMBLE],p.COUNT)
        self.assertEqual(p.payload_score(result['data'],bits)['errors'],0)

    def test_shared_channel_uses_fixed_tx_and_quantizes_once_per_record(self):
        bits=np.random.default_rng(p.LABEL_SEED).integers(0,2,p.COUNT)
        expected=[p.samples(p.fixed.transmit(bits,profile!='msk_frequency')) for profile in p.PROFILES]
        original=p.real.channel
        upstream=[]
        def capture(cfg,wave,**parameters):
            upstream.append(np.asarray(wave).copy());return original(cfg,wave,**parameters)
        with patch.object(p.real,'channel',side_effect=capture),patch.object(p.psk_fixed,'quantize',wraps=p.psk_fixed.quantize) as quantize:
            result=p.report()
        self.assertEqual(quantize.call_count,9)
        self.assertTrue(all(result['checks'].values()))
        for i,wave in enumerate(upstream):np.testing.assert_array_equal(wave,expected[i//3])

    def test_failure_writes_fail_and_raises(self):
        broken=copy.deepcopy(self.result);broken['checks']['forced_failure']=False
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'result.json'
            with patch.object(p,'report',return_value=broken),self.assertRaises(RuntimeError):p.main(['--output',str(target)])
            self.assertEqual(json.loads(target.read_text())['status'],'FAIL')

    def test_cli_evidence_and_optimization_guard(self):
        with tempfile.TemporaryDirectory() as directory:
            target=Path(directory)/'result.json'
            run=subprocess.run([sys.executable,str(ROOT/'tools/cpm_precision.py'),'--output',str(target)],capture_output=True,text=True,timeout=60)
            self.assertEqual(run.returncode,0,run.stderr)
            evidence=json.loads(target.read_text())
            self.assertEqual(evidence['status'],'PASS');self.assertFalse(evidence['rtl_verified'])
            self.assertIn('completed_at_utc',evidence)
            run=subprocess.run([sys.executable,'-O',str(ROOT/'tools/cpm_precision.py'),'--output',str(target)],capture_output=True,text=True,timeout=60)
            self.assertNotEqual(run.returncode,0)
            self.assertEqual(json.loads(target.read_text())['status'],'FAIL')


if __name__=='__main__':unittest.main()
