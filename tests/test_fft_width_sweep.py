"""Width selection evidence, clipping semantics and exploratory acceptance controls."""
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
import fft_width_sweep as sweep


class TestFftWidthSweep(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.result=sweep.report()

    def test_same_inputs_current_control_and_independent_float_metrics(self):
        sweep.check_acceptance(self.result)
        for n in sweep.SIZES:
            for case in sweep.cases(n):
                rows=case['rows'];z=np.array([re+1j*im for re,im in rows])
                expected=np.fft.ifft(z)*n if case['inverse'] else np.fft.fft(z)/n
                records=[r for r in self.result['records'] if r['n']==n and r['case']==case['case']]
                self.assertEqual(len({r['input_hash'] for r in records}),1)
                for record in records:
                    actual=sweep.f.transform(rows,case['inverse'],18,record['width'])
                    measured=sweep.compare([re+1j*im for re,im in actual],expected)
                    self.assertEqual(measured['evm_rms'],record['evm_rms'])
                    if record['width']==20:self.assertTrue(record['control_bit_exact'])
        self.assertEqual(self.result['selected_simulation_width'],19)
        self.assertIsNone(self.result['accepted_new_default_width'])
        self.assertFalse(self.result['rtl_candidate_equivalence_verified'])

    def test_guard_bits_do_not_change_unclipped_rounding(self):
        for n in sweep.SIZES:
            for case in sweep.cases(n):
                if case['nominal']:
                    self.assertEqual(sweep.f.transform(case['rows'],case['inverse'],18,19),
                                     sweep.f.transform(case['rows'],case['inverse'],18,24))

    def test_real_preclamp_event_and_rail_equality(self):
        trace=sweep.StageTrace()
        self.assertEqual(trace.record('node',7,7),7)
        self.assertEqual(trace.record('node',-7,7),-7)
        self.assertEqual(trace.total(),0)
        self.assertEqual(trace.record('node',8,7),7)
        self.assertEqual(trace.record('node',-8,7),-7)
        self.assertEqual(trace.total(),2)
        self.assertEqual(trace.stages()['node']['minimum'],-8)
        # At n64/w24 the inverse MIN imaginary DC loses one LSB to symmetric
        # clamping: its excellent SQNR still fails a strict zero-clamp budget.
        record=next(r for r in self.result['records'] if r['n']==64 and r['width']==24 and not r['nominal'])
        self.assertGreater(record['sqnr_db'],100)
        self.assertEqual(record['clamp_events'],1)
        self.assertFalse(record['budget_met'])
        self.assertIsNone(self.result['full_envelope_simulation_width'])

    def test_corrupted_control_metrics_and_missing_inputs_are_rejected(self):
        for kind in ('control','input','missing','metric','accept'):
            bad=deepcopy(self.result)
            if kind=='control':next(r for r in bad['records'] if r['width']==20)['control_bit_exact']=False
            if kind=='input':bad['records'][0]['input_hash']='different-input'
            if kind=='missing':bad['records'].pop()
            if kind=='metric':bad['records'][0]['evm_rms']=.3
            if kind=='accept':bad['accepted_new_default_width']=19
            with self.subTest(kind=kind):
                with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)

    def test_rtl_proof_requires_complete_unique_grid_and_actual_checks(self):
        candidate=deepcopy(self.result)
        candidate['rtl_candidate_equivalence_verified']=True
        candidate['rtl_equivalence']=[dict(width=width,n=n,reset_active=active,scenario=scenario,
                                           numeric_verified=True,saturation_verified=True,bounds_verified=True,
                                           outputs=5*n,frames=5)
                                      for width in (19,20) for n in sweep.SIZES for active in (1,0)
                                      for scenario in ('stream','stalled','midreset','outreset')]
        sweep.check_acceptance(candidate)
        for fault in ('missing','duplicate','numeric','saturation','bounds','count'):
            bad=deepcopy(candidate)
            if fault=='missing':bad['rtl_equivalence'].pop()
            elif fault=='duplicate':bad['rtl_equivalence'][-1]=deepcopy(bad['rtl_equivalence'][0])
            elif fault=='count':bad['rtl_equivalence'][0]['outputs']-=1
            else:bad['rtl_equivalence'][0][fault+'_verified']=False
            with self.subTest(fault=fault):
                with self.assertRaises(RuntimeError):sweep.check_acceptance(bad)
        sweep.check_acceptance(self.result)  # Empty proof is permitted for the model-only study.

    def test_source_hash_json_and_nonzero_failure_and_optimization(self):
        with tempfile.TemporaryDirectory() as work:
            output=Path(work)/'pass.json'
            with patch.object(sweep,'report',return_value=deepcopy(self.result)):
                self.assertEqual(sweep.main(['--output',str(output)]),0)
            result=json.loads(output.read_text());self.assertEqual(result['status'],'PASS')
            self.assertTrue(result['source_hashes']);self.assertIn('completed_at_utc',result)
            failure=Path(work)/'fail.json'
            script="import sys;sys.path.insert(0,'tools');import fft_width_sweep as s;s.report=lambda:{};s.main(['--output',sys.argv[1]])"
            failed=subprocess.run([sys.executable,'-c',script,str(failure)],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(failed.returncode,0);self.assertEqual(json.loads(failure.read_text())['status'],'FAIL')
            optimized=subprocess.run([sys.executable,'-O',str(ROOT/'tools/fft_width_sweep.py'),
                                      '--output',str(Path(work)/'optimized.json')],cwd=ROOT,capture_output=True,text=True)
            self.assertNotEqual(optimized.returncode,0)
            self.assertFalse((Path(work)/'optimized.json').exists())


if __name__=='__main__':unittest.main()
