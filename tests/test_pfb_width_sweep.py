"""PFB phase widths, tight box extrema, actual unclipped sums and evidence guards."""
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
import pfb_widths as widths
import pfb_width_sweep as sweep


class TestPfbWidths(unittest.TestCase):
    def test_tight_width_includes_rounding_for_every_supported_geometry(self):
        extrema=[x*h for x,h in product((-131072,131071),repeat=2)]
        for m,t in product(range(2,9),range(17)):
            row=widths.layout(m,t);low,high=row['raw_bounds'];w=row['selected_width']
            self.assertEqual([low,high],[row['terms_per_phase']*min(extrema),row['terms_per_phase']*max(extrema)])
            self.assertGreaterEqual(low,-(1<<(w-1)))
            self.assertLessEqual(high+row['round_bias'],(1<<(w-1))-1)
            self.assertGreater(high,(1<<(w-2))-1)
            for phase in range(1<<m):
                self.assertLessEqual(len(range(phase,1<<t,1<<m)),row['terms_per_phase'])
            self.assertEqual(row['saved_bits'],row['legacy_accumulator_bits']-row['accumulator_bits'])
        self.assertEqual(widths.layout(6,8)['selected_width'],38)
        self.assertEqual(widths.layout(6,8)['saved_bits'],768)

    def test_invalid_geometries(self):
        for pair in ((1,4),(9,4),(2,-1),(2,17),(True,4),(2,False),(2,3.5)):
            with self.subTest(pair=pair),self.assertRaises(ValueError):widths.layout(*pair)


class TestPfbWidthEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=sweep.report()

    def proof(self):
        result=deepcopy(self.model);result['rtl_verified']=True
        for row in result['records']:
            for w,a,s in product({row['layout']['selected_width'],row['layout']['legacy_width']},(1,0),sweep.SCENARIOS):
                result['rtl_equivalence'].append(dict(case=row['case'],width=w,active=a,scenario=s,bins=row['bins'],
                    raw_phases=row['raw_phases'],raw_peak=row['observed_bounds'][1],observers_verified=True,cycles=100))
            for w,a in product((row['layout']['selected_width']-1,64),(1,0)):
                result['rtl_parameters'].append(dict(case=row['case'],width=w,active=a,tag='PARAMETER',returncode=13))
        result['rtl_negative']=[dict(active=a,tag='ACCUMULATOR',returncode=13) for a in (1,0)]
        return result

    def test_report_roundtrip_and_full_scale_extrema(self):
        for report in (self.model,self.proof()):sweep.check_acceptance(json.loads(json.dumps(report)))
        self.assertEqual(len(self.model['records']),11)
        for row in self.model['records']:
            self.assertEqual(row['bins'],row['raw_phases'])
            if row['full_scale']:self.assertEqual(row['observed_bounds'],row['layout']['raw_bounds'])

    def test_changed_arithmetic_or_vectors_rejected(self):
        for field,value in (('bins',1),('raw_hash','bad'),('observed_bounds',[0,1]),('vector_hashes',{})):
            report=deepcopy(self.model);report['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):sweep.check_acceptance(report)

    def test_missing_duplicate_evidence_rejected(self):
        for section in ('records','rtl_equivalence','rtl_negative','rtl_parameters'):
            for duplicate in (False,True):
                report=self.proof()
                if duplicate:report[section][-1]=report[section][0]
                else:report[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):sweep.check_acceptance(report)

    def test_raw_observers_and_cycles_required(self):
        for field,value in (('raw_phases',0),('raw_peak',0),('observers_verified',False),('cycles',0),('cycles',True),('cycles',101)):
            report=self.proof();report['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):sweep.check_acceptance(report)
        for section in ('rtl_parameters','rtl_negative'):
            report=self.proof();report[section][0]['returncode']=0
            with self.subTest(section=section),self.assertRaises(RuntimeError):sweep.check_acceptance(report)
        report=self.proof();report['rtl_verified']=False
        with self.assertRaises(RuntimeError):sweep.check_acceptance(report)

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            result=subprocess.run([sys.executable,'-O',str(ROOT/'tools/pfb_width_sweep.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertFalse(path.exists())

if __name__=='__main__':unittest.main()
