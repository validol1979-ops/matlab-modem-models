"""Independent causal recurrences, honest stress classification, evidence policy."""
import copy
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
import state_precision as s
from regression_evidence import require_pass


class TestStatePrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans=s.plans()
        cls.report=dict(model_only=True,scope=s.SCOPE,formats=dict(s.FORMATS),budget=dict(s.BUDGET),records=[s.evaluate(p) for p in cls.plans])

    def test_complete_precision_and_real_stress(self):
        self.assertTrue(s.check_acceptance(self.report))
        records={r['case']:r for r in self.report['records']}
        for name in ('notch_output_clamp','notch_state_clamp'):
            self.assertFalse(records[name]['quality_claim'])
            self.assertGreater(records[name]['trace']['total'],0)
        self.assertEqual(records['kalman_legal_rails']['trace']['total'],0)
        self.assertTrue(records['kalman_disabled']['steady_error']['exact'])
        self.assertEqual(records['fsk_quiet4']['fixed_errors'],0)
        self.assertGreater(records['fsk_noisy_low']['fixed_errors'],0)

    def test_manual_float_recurrences(self):
        p=dict(case='manual',family='notch',category='nominal',inputs=[(32768,0),(65536,0),(98304,0)],
               samples=3,score_start=0,config=[-32768,16384,-8192],input_clamps=0)
        np.testing.assert_allclose(s.floating(p),[1,1.75,3.3125],rtol=0,atol=0)
        p.update(family='kalman',config=[0,2**24,2**24])
        np.testing.assert_allclose(s.floating(p),[.5,1,1.5],rtol=0,atol=1e-15)

    def test_reference_independent_and_causal(self):
        with patch.object(s.o,'notch',side_effect=AssertionError('fixed state leak')),patch.object(s.o,'kalman',side_effect=AssertionError('fixed state leak')),patch.object(s.o,'kalman_gains',side_effect=AssertionError('fixed gain leak')),patch.object(s.fsk,'_basis',side_effect=AssertionError('fixed LUT leak')):
            for p in self.plans:
                reference=s.floating(p);self.assertTrue(np.all(np.isfinite(reference)))
                if p['family']!='fsk':
                    later=copy.deepcopy(p);later['inputs'][100:]=[(0,0)]*(p['samples']-100)
                    if p['samples']>100:np.testing.assert_array_equal(reference[:100],s.floating(later)[:100])
                if p['family']=='kalman' and 'truth' in p:
                    unrelated=copy.deepcopy(p);unrelated['truth']=[[99.,-99.]]*p['samples']
                    np.testing.assert_array_equal(reference,s.floating(unrelated))
                if p['family']=='fsk':
                    unrelated=copy.deepcopy(p);unrelated['labels']=[0]*len(p['labels'])
                    np.testing.assert_array_equal(reference,s.floating(unrelated))

    def test_invalid_shape_and_words(self):
        p=self.plans[0]
        for mutate in (lambda q:q.update(samples=q['samples']+1),lambda q:q.update(score_start=q['samples']),
                       lambda q:q['inputs'].__setitem__(0,(131072,0)),lambda q:q['inputs'].__setitem__(0,(.5,0)),
                       lambda q:q['inputs'].__setitem__(0,(True,0)),lambda q:q.update(config=[0,0])):
            q=copy.deepcopy(p);mutate(q)
            with self.assertRaises(ValueError):s.floating(q)
        with self.assertRaises(ValueError):s.metrics([1],[1,2])
        with self.assertRaises(ValueError):s.metrics([np.nan],[0])
        f=copy.deepcopy(self.plans[-1]);f['inputs'].pop();f['samples']-=1
        with self.assertRaises(ValueError):s.floating(f)

    def test_coverage_metadata_and_metric_faults_rejected(self):
        for fault in ('drop','duplicate','expected','actual','extra','quality','nan','span','count','sqnr','stress','budget','decision','plan','shape','format'):
            r=copy.deepcopy(self.report);first=r['records'][0]
            if fault=='drop':r['records'].pop()
            elif fault=='duplicate':r['records'][-1]=copy.deepcopy(first)
            elif fault=='expected':first['expected_evaluations']={}
            elif fault=='actual':first['trace']['evaluations']={}
            elif fault=='extra':first['trace']['evaluations']['unexpected']=1
            elif fault=='quality':first['quality_claim']=False
            elif fault=='nan':first['steady_error']['rms_signal_units']=float('nan')
            elif fault=='span':first['score_start']+=1
            elif fault=='count':first['steady_error']['count']-=1
            elif fault=='sqnr':first['steady_error']['sqnr_db']=1000
            elif fault=='stress':r['records'][8]['trace']['stages']={};r['records'][8]['trace']['total']=0
            elif fault=='budget':r['budget']['nominal_rms_max_signal_units']=1000
            elif fault=='decision':r['records'][-1]['fixed_ser']=0
            elif fault=='plan':first['plan_hash']='bad'
            elif fault=='shape':r['records'][-1]['correlator_shape']=[1,1]
            elif fault=='format':r['formats']['signal']='Q0'
            with self.subTest(fault=fault),self.assertRaises(ValueError):s.check_acceptance(r)

    def test_composite_fsk_counts_and_observation_forgery(self):
        r=copy.deepcopy(self.report);record=r['records'][-1]
        for k in ('fixed_errors','float_errors','decision_mismatches','fixed_ser','float_ser','decision_mismatch_fraction'):record[k]=0
        with self.assertRaisesRegex(ValueError,'actual decisions'):s.check_acceptance(r)
        r=copy.deepcopy(self.report);record=r['records'][-1];labels=self.plans[-1]['labels']
        record['fixed_decisions']=list(labels);record['float_decisions']=list(labels)
        for k in ('fixed_errors','float_errors','decision_mismatches','fixed_ser','float_ser','decision_mismatch_fraction'):record[k]=0
        with self.assertRaisesRegex(ValueError,'correlation argmax'):s.check_acceptance(r)
        r=copy.deepcopy(self.report);record=r['records'][-1]
        for key in ('fixed_correlations','float_correlations'):
            record[key]=[[[1. if j==label else 0.,0.] for j in range(record['order'])] for label in labels]
        record['fixed_decisions']=list(labels);record['float_decisions']=list(labels)
        for k in ('fixed_errors','float_errors','decision_mismatches','fixed_ser','float_ser','decision_mismatch_fraction'):record[k]=0
        with self.assertRaisesRegex(ValueError,'seeded common waveform'):s.check_acceptance(r)

    def test_evidence_failure_and_fresh_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'report.json'
            with patch.object(s,'evaluate',side_effect=RuntimeError('forced numeric failure')):
                with self.assertRaisesRegex(RuntimeError,'forced numeric failure'):s.run_report(p)
            failed=json.loads(p.read_text());self.assertEqual(failed['status'],'FAIL')
            with self.assertRaises(RuntimeError):require_pass(failed)
            report=s.run_report(p);require_pass(report);self.assertTrue(s.check_acceptance(report))

    def test_optimized_cli_rejected(self):
        result=subprocess.run([sys.executable,'-O',str(ROOT/'tools/state_precision.py')],capture_output=True,text=True,timeout=20)
        self.assertNotEqual(result.returncode,0);self.assertIn('without Python optimization',result.stderr)
        self.assertNotIn('PASS state precision',result.stdout)


if __name__=='__main__':unittest.main()
