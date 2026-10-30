"""Beam energy overflow at 32 channels, normalization and complete evidence gates."""
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
import beam_energy as energy
import beam_energy_study as study
import beam_fixed as fixed


class TestBeamEnergy(unittest.TestCase):
    def test_minimal_width_at_the_exact_unsigned_boundary(self):
        for n in range(10):
            row=energy.layout(n);width=row['selected_width']
            self.assertEqual(row['energy_max'],(1<<n)*2*131072**2)
            self.assertEqual(width,36+n)
            self.assertLess(row['energy_max'],1<<width)
            self.assertGreater(row['energy_max'],(1<<(width-1))-1)
        self.assertTrue(energy.layout(4)['old_width_safe'])
        self.assertFalse(energy.layout(5)['old_width_safe'])
        self.assertEqual(energy.layout(5)['energy_max']%(1<<40),0)
        for n in (-1,28,True,1.5):
            with self.assertRaises(ValueError):energy.layout(n)

    def test_independent_reciprocal_matches_exact_integer_rounding(self):
        values=list(range(1,2049))+[(1<<b)+d for b in range(12,43) for d in (-1,0,1)]
        for e in values:
            r,s=energy.exact_reciprocal(e)
            self.assertEqual((r,s+15),fixed.reciprocal(e))
            self.assertEqual(s,7+e.bit_length())
            self.assertLessEqual(2*abs(r*e-(1<<(s+15))),e)
        for e in (0,-1,True,1.5):
            with self.assertRaises(ValueError):energy.exact_reciprocal(e)


class TestBeamEnergyEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=study.report()

    def proof(self):
        r=deepcopy(self.model);r['rtl_verified']=True
        for source in r['records']:
            for width,a,s in product((source['layout']['selected_width'],source['layout']['control_width']),(1,0),study.SCENARIOS):
                r['rtl_equivalence'].append(dict(case=source['case'],width=width,active=a,scenario=s,
                    bf_outputs=source['bf_outputs'],al_outputs=source['al_outputs'],energy=source['energy'],cycles=100+width,
                    stream_cycles=100,configuration_cycles=width+30,energy_checks=source['channels'],reciprocal_checks=1,observers_verified=True))
            for width,a in product((source['layout']['selected_width']-1,64),(1,0)):
                r['rtl_parameters'].append(dict(case=source['case'],width=width,active=a,returncode=13,tag='PARAMETER'))
        r['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),('ENERGY','NORMALIZATION','RECIPROCAL'))]
        return r

    def test_json_roundtrip_and_both_zero_and_nonzero_wrapped_energy(self):
        study.check_acceptance(json.loads(json.dumps(self.model)));study.check_acceptance(json.loads(json.dumps(self.proof())))
        self.assertEqual(len(self.model['records']),11)
        full=next(r for r in self.model['records'] if r['case']=='m32_min')
        self.assertTrue(full['old_overflow']);self.assertEqual(full['old_energy'],0)
        partial=next(r for r in self.model['records'] if r['case']=='m63_capacity64')
        self.assertTrue(partial['old_overflow']);self.assertGreater(partial['old_energy'],0)
        self.assertEqual(full['reciprocal'],1<<23);self.assertEqual(full['shift'],48)

    def test_missing_duplicate_or_changed_records_rejected(self):
        for field,value in (('energy',0),('vector_hashes',{}),('reciprocal',0),('shift',0)):
            r=deepcopy(self.model);r['records'][-1][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('records','rtl_equivalence','rtl_parameters','rtl_negative'):
            for duplicate in (False,True):
                r=self.proof()
                if duplicate:r[section][-1]=r[section][0]
                else:r[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_observations_stream_cycles_and_strict_fault_status(self):
        for field,value in (('energy_checks',0),('reciprocal_checks',0),('energy',0),('cycles',True),('stream_cycles',0),('stream_cycles',101),('configuration_cycles',0),('observers_verified',False)):
            r=self.proof();r['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_parameters','rtl_negative'):
            for code in (0,True,'13'):
                r=self.proof();r[section][0]['returncode']=code
                with self.subTest(section=section,code=code),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_nonzero_wrap_changes_the_expected_first_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);row=study.fixture(study.CASES[-1],folder)
            first=tuple(map(int,(folder/'bf_out.txt').read_text().splitlines()[1].split()))
            self.assertEqual(first,(32768,0,0));self.assertEqual(row['old_energy'],31*(1<<35))
            old_r,old_shift=energy.exact_reciprocal(row['old_energy'])
            from fft_fixed import rnd
            self.assertNotEqual(rnd(row['energy']*old_r,old_shift),first[0])

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            p=subprocess.run([sys.executable,'-O',str(ROOT/'tools/beam_energy_study.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
