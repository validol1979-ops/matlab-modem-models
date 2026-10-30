"""LDPC truth-free recurrence, actual decisions, clipping and report controls."""
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
import ldpc_precision as s
from regression_evidence import require_pass
from research_core import run


class TestLdpcPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plans=s.plans()
        cls.report=dict(model_only=True,scope=s.SCOPE,formats=dict(s.FORMATS),budget=dict(s.BUDGET),records=[s.evaluate(p) for p in cls.plans])

    def test_complete_quality_and_diagnostic_separation(self):
        self.assertTrue(s.check_acceptance(self.report))
        for r in self.report['records']:
            if r['family']=='gf2':self.assertEqual(r['mismatched_bits'],0);continue
            if r['case'].endswith('clean'):
                self.assertEqual(r['fixed']['bit_errors'],0);self.assertEqual(r['floating']['bit_errors'],0)
            if r['category'] in ('diagnostic','clamp_stress'):self.assertFalse(r['quality_claim'])
            if r['category']=='clamp_stress':self.assertGreater(r['trace']['total'],0)
        near=self.report['records'][2]
        self.assertGreater(near['fixed']['bit_errors'],0)
        self.assertGreater(near['iteration_mismatch_frames'],0)

    def test_manual_recursion_and_research_convention(self):
        for mode,posterior in [(0,[.5,.5]),(1,[.5,.5]),(2,[.75,0]),(3,[.75,.25])]:
            bits,post,used=s.floating([256,-128],[[1,1]],4,mode,.5,.25)
            np.testing.assert_allclose(post,posterior,atol=1e-15);np.testing.assert_array_equal(bits,[0,0]);self.assertEqual(used,1)
        for mode in range(4):
            p=next(p for p in self.plans if p['case']==f'mode{mode}_noisy');llr=p['llrs'][0]
            bits,post,_=s.floating(llr,p['H'],p['iterations'],mode,p['alpha_raw']/256,p['beta_raw']/256)
            r=run('ldpc',[p['checks'],p['columns'],p['iterations'],mode,p['alpha_raw']/256,p['beta_raw']/256],np.asarray(llr)/256,np.asarray(p['H']).ravel()).real
            np.testing.assert_array_equal(bits,r[:12]);np.testing.assert_allclose(post,r[12:],rtol=0,atol=2e-8)

    def test_stable_sum_product_zero_and_large_llr(self):
        self.assertEqual(s.phi(0),float('inf'));self.assertEqual(s.phi(float('inf')),0.)
        self.assertEqual(s.sum_product_message([0.,1e6]),0.)
        self.assertAlmostEqual(s.sum_product_message([1024.,1024.]),1024.-np.log(2),places=10)
        self.assertAlmostEqual(s.sum_product_message([-1024.,1024.]),-1024.+np.log(2),places=10)
        bits,post,used=s.floating([32767]*3,[[1,1,1]],20,0,.8,.15)
        self.assertTrue(np.all(np.isfinite(post)));self.assertGreater(np.min(post),200.)
        np.testing.assert_array_equal(bits,[0,0,0]);self.assertEqual(used,1)
        self.assertAlmostEqual(s.phi(s.phi(.01)),.01,places=13)
        for x in (1.,18.,30.,35.,36.,37.,1024.):
            with self.subTest(boundary=x):
                expected=x-np.log(2)+np.log1p(np.exp(-2*x))
                self.assertAlmostEqual(s.sum_product_message([x,x]),expected,places=12)
                self.assertAlmostEqual(s.sum_product_message([-x,x]),-expected,places=12)
                self.assertEqual(s.sum_product_message([0.,x]),0.)

    def test_reference_does_not_use_fixed_states_or_truth(self):
        with patch.object(s.fixed,'decode',side_effect=AssertionError('fixed state leak')),patch.object(s.fixed,'encode',side_effect=AssertionError('fixed encoder leak')):
            for p in self.plans:
                if p['family']=='gf2':self.assertEqual(s.gf2_reference(p['messages'],p['A']).shape,(p['frames'],p['parity']+p['message_bits']))
                else:
                    bits,post,_=s.floating(p['llrs'][0],p['H'],p['iterations'],p['mode'],p['alpha_raw']/256,p['beta_raw']/256)
                    self.assertEqual(len(bits),p['columns']);self.assertTrue(np.all(np.isfinite(post)))
        np.testing.assert_array_equal(s.gf2_reference([[1,0,1],[0,1,1]],[[1,1,0],[0,1,1]]),[[1,1,1,0,1],[1,0,0,1,1]])

    def test_shape_format_and_codeword_rejection(self):
        p=self.plans[0]
        for mutate in (lambda q:q['llrs'].__setitem__(0,[0]),lambda q:q['llrs'][0].__setitem__(0,32768),
                       lambda q:q['llrs'][0].__setitem__(0,.5),lambda q:q['H'][0].__setitem__(0,2),
                       lambda q:q['words'][0].__setitem__(0,1-q['words'][0][0]),
                       lambda q:q.update(alpha_raw=257),lambda q:q.update(iterations=0)):
            q=copy.deepcopy(p);mutate(q)
            with self.assertRaises(ValueError):s.evaluate(q)
        with self.assertRaises(ValueError):s.quantize([np.inf])
        with self.assertRaises(ValueError):s.metric([1],[1,2])
        with self.assertRaises(ValueError):s.metric([np.nan],[0])
        with self.assertRaises(ValueError):s.gf2_reference([[1,0]],[[1]])

    def test_tampering_rejected(self):
        for fault in ('drop','duplicate','expected','actual','extra','iterations','quality','span','posterior_nan','posterior_metric','bits','syndrome','ber','stress','gf2','budget','format'):
            r=copy.deepcopy(self.report);first=r['records'][0]
            if fault=='drop':r['records'].pop()
            elif fault=='duplicate':r['records'][-1]=copy.deepcopy(first)
            elif fault=='expected':first['expected_evaluations']={}
            elif fault=='actual':first['trace']['evaluations']={}
            elif fault=='extra':first['trace']['evaluations']['unexpected']=1
            elif fault=='iterations':first['fixed_iterations'][0]=0
            elif fault=='quality':r['records'][2]['quality_claim']=True
            elif fault=='span':first['frames']+=1
            elif fault=='posterior_nan':first['fixed_posteriors'][0][0]=float('nan')
            elif fault=='posterior_metric':first['terminal_posterior_error']['rms_llr_units']=0
            elif fault=='bits':first['fixed']['bits'][0][0]^=1
            elif fault=='syndrome':first['fixed']['syndromes'][0][0]^=1
            elif fault=='ber':first['fixed']['ber']=1
            elif fault=='stress':r['records'][3]['trace']['stages']={};r['records'][3]['trace']['total']=0
            elif fault=='gf2':r['records'][-1]['actual_words'][0][0]^=1
            elif fault=='budget':r['budget']['noisy_ber_excess_max']=1
            elif fault=='format':r['formats']['llr']='Q15'
            with self.subTest(fault=fault),self.assertRaises(ValueError):s.check_acceptance(r)

    def test_composite_decision_and_early_stop_forgery(self):
        for family in ('fixed','floating'):
            r=copy.deepcopy(self.report);record=r['records'][2];p=self.plans[2]
            record['fixed']=s.decision(p['words'],p['words'],p['H'])
            record['floating']=s.decision(p['words'],p['words'],p['H'])
            record['decision_mismatches']=0
            with self.subTest(family=family,fault='forged perfect decisions'),self.assertRaisesRegex(ValueError,'posterior signs'):
                s.check_acceptance(r)
            r=copy.deepcopy(self.report);record=r['records'][0]
            key='fixed_iterations' if family=='fixed' else 'float_iterations';record[key][0]=2
            record['iteration_mismatch_frames']=1
            if family=='fixed':
                record['expected_evaluations']['v']+=record['edges'];record['expected_evaluations']['post']+=record['columns']
                record['trace']['evaluations']=dict(record['expected_evaluations'])
            with self.subTest(family=family,fault='forged stop2'),self.assertRaisesRegex(ValueError,'stop at1'):
                s.check_acceptance(r)
            r=copy.deepcopy(self.report);record=r['records'][0]
            key='fixed_first_posteriors' if family=='fixed' else 'float_first_posteriors'
            record[key][0][0]*=1.001
            record['first_iteration_posterior_error']=s.metric(record['fixed_first_posteriors'],record['float_first_posteriors'])
            with self.subTest(family=family,fault='inconsistent first posterior'),self.assertRaisesRegex(ValueError,'contradicts first posterior'):
                s.check_acceptance(r)

    def test_running_failure_and_fresh_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'results.json'
            def fail(plan):
                self.assertEqual(json.loads(p.read_text())['status'],'RUNNING');raise RuntimeError('forced decoding failure')
            with patch.object(s,'evaluate',side_effect=fail):
                with self.assertRaisesRegex(RuntimeError,'forced decoding failure'):s.run_report(p)
            r=json.loads(p.read_text());self.assertEqual(r['status'],'FAIL')
            with self.assertRaises(RuntimeError):require_pass(r)
            r=s.run_report(p);require_pass(r);self.assertTrue(s.check_acceptance(r))

    def test_optimized_cli_rejected(self):
        r=subprocess.run([sys.executable,'-O',str(ROOT/'tools/ldpc_precision.py')],capture_output=True,text=True,timeout=20)
        self.assertNotEqual(r.returncode,0);self.assertIn('without Python optimization',r.stderr);self.assertNotIn('PASS LDPC',r.stdout)


if __name__=='__main__':unittest.main()
