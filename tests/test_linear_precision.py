"""Independent linear algebra, clamp/rejection diagnostics and evidence gates."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'tools'))
import linear_precision as precision


class TestLinearPrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=precision.report()

    def test_full_nominal_coverage_and_exact_tiny_controls(self):
        precision.check_acceptance(self.result)
        nominal=[r for r in self.result['records'] if r['category']=='nominal']
        self.assertEqual(len(nominal),14)
        for record in nominal:
            self.assertEqual(record['saturation']['total'],0)
            if 'tiny' in record['case']:
                self.assertTrue(record['unclipped_output']['comparison_exact'])
                self.assertTrue(record['coefficients']['comparison_exact'])

    def test_reference_never_uses_fixed_weights_or_normalizer(self):
        for plan in precision.plans():
            if plan['category']!='nominal':continue
            with (patch.object(precision.mmse2,'weights',side_effect=AssertionError('fixed weights leaked')),
                  patch.object(precision.mmse3,'weights',side_effect=AssertionError('fixed weights leaked')),
                  patch.object(precision.beam,'reciprocal',side_effect=AssertionError('fixed reciprocal leaked'))):
                output,weights=precision.floating_reference(plan)
            self.assertEqual(output.shape,(precision.output_count(plan),))
            self.assertTrue(np.all(np.isfinite(weights)))

    def test_manual_tiny_gain_and_anti_linear_alamouti(self):
        for plan in precision.plans():
            if 'tiny' not in plan['case']:continue
            raw=np.array([complex(re,im) for re,im in plan['observations']])
            expected=raw
            if plan['family']=='alamouti':
                X=raw.reshape(-1,2);a,b=X[:,0],X[:,1]
                expected=np.column_stack(((a.real+b.imag+1j*(a.imag+b.real))/2,
                                          (a.imag-b.real+1j*(b.imag-a.real))/2)).ravel()
            actual=precision.complex_words(precision.fixed_outputs(plan))
            np.testing.assert_array_equal(actual,expected)

    def test_actual_clamps_and_exact_coefficient_rejection_certificates(self):
        clamp=[r for r in self.result['records'] if r['category']=='clamp_stress']
        self.assertEqual([r['saturation']['total'] for r in clamp],[4,6,4,2])
        for record in clamp:
            self.assertFalse(record['quality_accepted']);self.assertTrue(record['clipped_output']['comparison_exact'])
            self.assertGreater(record['unclipped_output']['rms_deviation'],1)
        overflow=[r for r in self.result['records'] if r['category']=='coefficient_rejection']
        for record in overflow:
            proof=record['independent_rejection_proof'];self.assertEqual(proof['determinant_raw'],1)
            self.assertEqual(proof['gram_determinant_raw'],1);self.assertTrue(proof['mathematically_exceeds_range'])
            self.assertGreater(int(proof['required_max_abs_coefficient_q24']),int(proof['positive_limit_q24']))
            self.assertEqual(record['outputs'],0)

    def test_shape_coverage_metrics_and_rejection_tampering_rejected(self):
        for fault in ('empty','metric','shape','count','stages','clamp','class','hash','nan_stress','reject_trace','reject'):
            bad=deepcopy(self.result)
            if fault=='empty':bad['records']=[]
            elif fault=='metric':bad['records'][0]['unclipped_output']['rms_deviation']=.1
            elif fault=='shape':bad['records'][0]['unclipped_output']['shape']=[1]
            elif fault=='count':bad['records'][0]['outputs']-=1
            elif fault=='stages':bad['records'][0]['saturation']['evaluations']['unknown']=1
            elif fault=='clamp':bad['records'][0]['saturation']['total']=1
            elif fault=='class':bad['records'][0]['category']='clamp_stress'
            elif fault=='hash':bad['records'][0]['input_hash']='different'
            elif fault=='nan_stress':bad['records'][14]['clipped_output']['max_complex_deviation']=float('nan')
            elif fault=='reject_trace':bad['records'][-1]['saturation']['stages']['ghost']={'pos':1,'neg':0}
            else:bad['records'][-1]['rejection_verified']=False
            with self.subTest(fault=fault):
                with self.assertRaises(RuntimeError):precision.check_acceptance(bad)
        plan=precision.plans()[0];plan['observations']=plan['observations'][:-1]
        with self.assertRaises(ValueError):precision.floating_reference(plan)
        plan=precision.plans()[0];plan['observations'][0]=1
        with self.assertRaises(ValueError):precision.floating_reference(plan)

    def test_rail_equality_is_not_clipping(self):
        trace=precision.SatTrace()
        rows=[(131071,0),(-131072,0)]
        self.assertEqual(precision.beam.beamform(rows,[(32768,0)],trace),rows)
        self.assertEqual(trace.total(),0)

    def test_json_source_snapshot_failure_exit_and_optimization(self):
        with tempfile.TemporaryDirectory() as work:
            output=Path(work)/'pass.json'
            with patch.object(precision,'report',return_value=deepcopy(self.result)):
                self.assertEqual(precision.main(['--output',str(output)]),0)
            value=json.loads(output.read_text());self.assertEqual(value['status'],'PASS')
            self.assertTrue(value['source_hashes']);self.assertIn('completed_at_utc',value)
            failure=Path(work)/'fail.json'
            script="import sys;sys.path.insert(0,'tools');import linear_precision as p;p.report=lambda:{};p.main(['--output',sys.argv[1]])"
            process=subprocess.run([sys.executable,'-c',script,str(failure)],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(process.returncode,0);self.assertEqual(json.loads(failure.read_text())['status'],'FAIL')
            optimized=subprocess.run([sys.executable,'-O',str(ROOT/'tools/linear_precision.py'),
                                      '--output',str(Path(work)/'optimized.json')],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(optimized.returncode,0);self.assertFalse((Path(work)/'optimized.json').exists())


if __name__=='__main__':unittest.main()
