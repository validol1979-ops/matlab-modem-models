"""Full-recursion adaptive comparisons and negative evidence controls."""
from copy import deepcopy
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
import adaptive_precision as precision


class TestAdaptivePrecision(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=precision.report()

    def test_full_recursions_converge_and_share_once_quantized_inputs(self):
        precision.check_acceptance(self.result)
        for name,_,_,_ in precision.SCENARIOS:
            records=[r for r in self.result['records'] if r['case']==name]
            self.assertEqual(len({(r['input_hash'],r['desired_hash']) for r in records}),1)
            for record in records:
                self.assertTrue(record['quality_accepted'])
                self.assertEqual(record['saturation']['total'],0)
                self.assertLess(record['prediction_settled']['rms_signal_units'],.0001)
                self.assertLess(record['exported_weight_rms_coefficient_units'],.0001)
                # With no error clamp, d-pred makes the two stream discrepancies equal.
                self.assertAlmostEqual(record['prediction_settled']['rms_signal_units'],
                                       record['error_settled']['rms_signal_units'],places=12)

    def test_independent_float_arguments_and_recomputed_metrics(self):
        dataset=precision.nominal_data()[1]
        original=precision.floating_run
        with patch.object(precision,'floating_run',wraps=original) as floating:
            record=precision.measure('rls',dataset)
        operation,parameters,x,d=floating.call_args.args
        self.assertEqual(operation,'rls')
        np.testing.assert_array_equal(x,precision.complex_words(dataset['x']))
        np.testing.assert_array_equal(d,precision.complex_words(dataset['d']))
        self.assertEqual(parameters,record['floating_parameters'])
        reference=original(operation,parameters,x,d)
        fixed,weights=precision.rls.adapt(dataset['x'],dataset['d'],dataset['taps'],precision.configured('rls')[0])
        prediction=precision.complex_words([p for p,e in fixed])
        expected=precision.deviation(prediction[400:],reference[:1200][400:])
        self.assertEqual(expected,record['prediction_settled'])
        direct=precision.complex_words(weights)-reference[2400:]
        self.assertEqual(record['exported_weight_rms_coefficient_units'],float(np.sqrt(np.mean(abs(direct)**2))))

    def test_dataset_noise_and_quantization_are_reproducible(self):
        first=precision.nominal_data();again=precision.nominal_data()
        for one,two in zip(first,again):
            self.assertEqual(one['x'],two['x']);self.assertEqual(one['d'],two['d'])
            self.assertEqual(one['input_clamps']+one['desired_clamps'],0)
        self.assertEqual(first[0]['measured_noise_power_signal_units_squared'],0)
        self.assertGreater(first[1]['measured_noise_power_signal_units_squared'],0)
        self.assertGreater(first[2]['measured_noise_power_signal_units_squared'],first[1]['measured_noise_power_signal_units_squared'])

    def test_real_clipping_stresses_are_not_quality_acceptance(self):
        for record in self.result['records']:
            if not record['nominal']:
                self.assertFalse(record['quality_accepted'])
                self.assertEqual(record['status'],'measured')
                self.assertGreater(record['saturation']['total'],0)
                self.assertGreater(record['saturation']['stages']['dump.re']['pos'],0)
        record=next(r for r in self.result['records'] if r['case']=='stress_rls')
        self.assertEqual(record['saturation']['stages']['update.re']['pos'],4)
        self.assertEqual(record['saturation']['stages']['update.im']['neg'],4)

    def test_rls_loss_of_positivity_is_diagnostic_not_successful_quality(self):
        dataset=dict(case='stress_rls',taps=1,x=[(1,0)]*8,d=[(131071,131071)]*8,
                     nominal=False,input_clamps=0,desired_clamps=0)
        with patch.object(precision.rls,'adapt',side_effect=ValueError('RLS denominator lost positivity')):
            record=precision.measure('rls',dataset)
        self.assertEqual(record['status'],'diagnostic_rejection')
        self.assertFalse(record['quality_accepted'])
        self.assertNotIn('prediction_settled',record)

    def test_bad_quality_observers_inputs_and_empty_coverage_rejected(self):
        for fault in ('empty','weight','input','clamps','observer','expected','unexpected_stage',
                      'range','metric_span','samples','classification','stress'):
            bad=deepcopy(self.result)
            if fault=='empty':bad['records']=[]
            elif fault=='weight':bad['records'][0]['exported_weight_rms_coefficient_units']=.1
            elif fault=='input':bad['records'][0]['input_hash']='different'
            elif fault=='clamps':bad['records'][0]['saturation']['total']=1
            elif fault=='observer':bad['records'][0]['saturation']['evaluations']['pred.re']=0
            elif fault=='expected':bad['records'][0]['expected_evaluations']={}
            elif fault=='unexpected_stage':bad['records'][0]['saturation']['evaluations']['unknown.stage']=1
            elif fault=='range':bad['records'][0]['scored_sample_start']=401
            elif fault=='metric_span':bad['records'][0]['prediction_settled']['samples']=799
            elif fault=='samples':bad['records'][0]['samples']=1199
            elif fault=='classification':bad['records'][0]['nominal']=False
            else:bad['records'][-1]['quality_accepted']=True
            with self.subTest(fault=fault):
                with self.assertRaises(RuntimeError):precision.check_acceptance(bad)

    def test_json_source_snapshot_failure_exit_and_optimization(self):
        with tempfile.TemporaryDirectory() as work:
            output=Path(work)/'pass.json'
            with patch.object(precision,'report',return_value=deepcopy(self.result)):
                self.assertEqual(precision.main(['--output',str(output)]),0)
            value=json.loads(output.read_text());self.assertEqual(value['status'],'PASS')
            self.assertIn('completed_at_utc',value);self.assertTrue(value['source_hashes'])
            failing=Path(work)/'fail.json'
            script="import sys;sys.path.insert(0,'tools');import adaptive_precision as p;p.report=lambda:{};p.main(['--output',sys.argv[1]])"
            process=subprocess.run([sys.executable,'-c',script,str(failing)],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(process.returncode,0);self.assertEqual(json.loads(failing.read_text())['status'],'FAIL')
            optimized=subprocess.run([sys.executable,'-O',str(ROOT/'tools/adaptive_precision.py'),
                                      '--output',str(Path(work)/'optimized.json')],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(optimized.returncode,0);self.assertFalse((Path(work)/'optimized.json').exists())


if __name__=='__main__':unittest.main()
