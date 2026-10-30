"""Exact NLMS power/epsilon widths, normalization, old overflow and evidence gates."""
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'common/python')]
import lms_energy as energy
import lms_energy_study as study
import lms_fixed as fixed


class TestLmsEnergy(unittest.TestCase):
    def test_exact_unsigned_limits_and_minimal_width(self):
        for n in range(9):
            r=energy.layout(n);width=r['selected_width']
            self.assertEqual(r['power_max'],(1<<n)*2*131072**2)
            self.assertEqual(r['total_max'],r['power_max']+(1<<34)-1)
            self.assertEqual(width,36+n)
            self.assertLessEqual(r['total_max'],(1<<width)-1)
            self.assertGreater(r['total_max'],(1<<(width-1))-1)
        self.assertEqual(energy.layout(4)['power_max'],1<<39)
        self.assertFalse(energy.layout(4)['old_width_safe'])
        self.assertTrue(energy.layout(3)['old_width_safe'])

    def test_normalization_overflow_is_visible_before_output_clipping(self):
        rows=energy.history_trace([(-131072,-131072)]*16,16,512)
        self.assertEqual(rows[-1],((1<<39),(1<<39)+512,40,0,1024))
        self.assertEqual((rows[-1][1]&((1<<39)-1)).bit_length(),10)
        rows=energy.history_trace([(131071,131071)]*16,16,(1<<34)-1)
        self.assertLess(rows[-1][0],1<<39);self.assertGreaterEqual(rows[-1][1],1<<39)

    def test_sliding_history_and_all_reciprocal_roundings(self):
        samples=[(-131072,-131072)]*16+[(0,0)]*16
        rows=energy.history_trace(samples,16,512)
        for k,row in enumerate(rows):
            window=samples[max(0,k-15):k+1]
            self.assertEqual(row[0],sum(re*re+im*im for re,im in window))
        self.assertEqual(rows[-1],(0,512,10,0,1024))
        self.assertEqual([((1<<19)+m//2)//m for m in range(512,1024)],list(fixed.RECIPROCAL))
        for n in (-1,28,True,2.5):
            with self.assertRaises(ValueError):energy.layout(n)
        for taps,eps in ((0,512),(1,511),(1,1<<34)):
            with self.assertRaises(ValueError):energy.history_trace([],taps,eps)


class TestLmsEnergyEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=study.report()

    def proof(self):
        r=deepcopy(self.model);r['rtl_verified']=True
        for source in r['records']:
            for width,a,s in product((source['layout']['selected_width'],source['layout']['control_width']),(1,0),study.SCENARIOS):
                r['rtl_equivalence'].append(dict(case=source['case'],width=width,active=a,scenario=s,
                    outputs=source['outputs'],weights=source['weights'],cycles=100,energy_checks=source['inputs'],rom_checks=source['inputs'],power_peak=source['observed_power_max'],observers_verified=True))
            for width,a in product((source['layout']['selected_width']-1,64),(1,0)):
                r['rtl_parameters'].append(dict(case=source['case'],width=width,active=a,returncode=13,tag='PARAMETER'))
        r['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),('ENERGY','NORMALIZATION','RECIPROCAL'))]
        return r

    def test_report_json_and_separate_power_total_overflow(self):
        study.check_acceptance(json.loads(json.dumps(self.model)));study.check_acceptance(json.loads(json.dumps(self.proof())))
        self.assertEqual(len(self.model['records']),12)
        positive=next(r for r in self.model['records'] if r['case']=='n16_positive_epsmax')
        self.assertFalse(positive['old_power_overflow']);self.assertTrue(positive['old_total_overflow'])

    def test_changed_or_incomplete_measurements_rejected(self):
        for field,value in (('outputs',1),('vector_hashes',{}),('observed_bits_max',39),('observed_total_max',0)):
            r=deepcopy(self.model);r['records'][-1][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('records','rtl_equivalence','rtl_parameters','rtl_negative'):
            for duplicate in (False,True):
                r=self.proof()
                if duplicate:r[section][-1]=r[section][0]
                else:r[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_unmeasured_states_cycles_or_faults_rejected(self):
        for field,value in (('energy_checks',0),('rom_checks',0),('power_peak',0),('cycles',0),('cycles',True),('cycles',101),('observers_verified',False)):
            r=self.proof();r['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_parameters','rtl_negative'):
            for code in (0,True,'13'):
                r=self.proof();r[section][0]['returncode']=code
                with self.subTest(section=section,code=code),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_reproduction_vectors_are_stable(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp);row=study.fixture(study.CASES[-1],path)
            self.assertEqual(row['inputs'],68);self.assertEqual(row['transactions'],1)
            outputs=[tuple(map(int,line.split())) for line in (path/'out.txt').read_text().splitlines()[1:]]
            self.assertEqual(outputs[16][:2],(4,-178))
            self.assertEqual((path/'cfg.txt').read_text(),'1 16 131072 512\n')

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            p=subprocess.run([sys.executable,'-O',str(ROOT/'tools/lms_energy_study.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
