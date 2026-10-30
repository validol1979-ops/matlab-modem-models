"""ISTFT tight widths, worst-case overlap, unclipped evidence and rejection guards."""
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
import istft_widths as widths
import istft_width_sweep as sweep


class TestIstftWidths(unittest.TestCase):
    def test_exact_signed_corners_and_minimal_widths(self):
        fft_limit=(1<<23)-1
        for n in range(2,9):
            for h in range(max(0,n-2),n+1):
                row=widths.layout(n,h);r=row['overlap'];w=row['accumulator_width']
                corners=[u*window for u,window in product((-fft_limit,fft_limit),(-131072,131071))]
                self.assertEqual(row['product_bounds'],[min(corners),max(corners)])
                self.assertEqual(row['accumulator_bounds'],[r*min(corners),r*max(corners)])
                low,high=row['accumulator_bounds']
                self.assertGreaterEqual(low,-(1<<(w-1)));self.assertLessEqual(high,(1<<(w-1))-1)
                self.assertGreater(high,(1<<(w-2))-1)
                self.assertLessEqual(row['product_bounds'][1],(1<<40)-1)
                self.assertGreater(row['product_bounds'][1],(1<<39)-1)
                self.assertEqual(row['saved_ram_bits'],row['legacy_ram_bits']-row['ram_bits'])
        self.assertEqual(widths.layout(8,8)['saved_ram_bits'],1536)
        self.assertEqual(widths.layout(8,7)['saved_ram_bits'],1024)
        self.assertEqual(widths.layout(8,6)['saved_ram_bits'],512)

    def test_invalid_geometry(self):
        for pair in ((1,1),(9,7),(6,3),(6,7),(2,-1),(True,0),(4,2.5)):
            with self.subTest(pair=pair),self.assertRaises(ValueError):widths.layout(*pair)


class TestIstftEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=sweep.report()

    def proof(self):
        result=deepcopy(self.model);result['rtl_verified']=True
        for row in result['records']:
            for aw,pw,a,s in product({row['layout']['accumulator_width'],44},(41,42),(1,0),sweep.SCENARIOS):
                result['rtl_equivalence'].append(dict(case=row['case'],acc_width=aw,product_width=pw,active=a,scenario=s,
                    **{k:row[k] for k in ('spectra','samples','raw_writes','raw_reads','max_overlap')},cycles=100,observers_verified=True))
            pairs=((row['layout']['accumulator_width']-1,41),(45,41),(row['layout']['accumulator_width'],40),(row['layout']['accumulator_width'],43))
            for (aw,pw),a in product(pairs,(1,0)):
                result['rtl_parameters'].append(dict(case=row['case'],acc_width=aw,product_width=pw,active=a,tag='PARAMETER',returncode=13))
        result['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),('PRODUCT','ACCUMULATOR','RAM_READ'))]
        return result

    def test_roundtrip_exact_extrema_and_full_overlap(self):
        for report in (self.model,self.proof()):sweep.check_acceptance(json.loads(json.dumps(report)))
        self.assertEqual(len(self.model['records']),10)
        for row in self.model['records']:
            self.assertEqual(row['max_overlap'],row['layout']['overlap'])
            if row['custom_window']:
                self.assertEqual(row['observed_products'],row['layout']['product_bounds'])
                self.assertEqual(row['observed_sums'],row['layout']['accumulator_bounds'])
                self.assertGreater(row['raw_writes'],3*(1<<row['log2n']))

    def test_tampered_vectors_or_raw_measurements_rejected(self):
        for field,value in (('samples',1),('raw_writes',0),('observed_products',[0,1]),('vector_hashes',{})):
            report=deepcopy(self.model);report['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):sweep.check_acceptance(report)

    def test_missing_duplicate_rtl_evidence_rejected(self):
        for section in ('records','rtl_equivalence','rtl_parameters','rtl_negative'):
            for duplicate in (False,True):
                report=self.proof()
                if duplicate:report[section][-1]=report[section][0]
                else:report[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):sweep.check_acceptance(report)

    def test_incomplete_arithmetic_and_cycle_controls_rejected(self):
        for field,value in (('raw_writes',0),('raw_reads',0),('max_overlap',0),('observers_verified',False),('cycles',0),('cycles',True),('cycles',101)):
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
            result=subprocess.run([sys.executable,'-O',str(ROOT/'tools/istft_width_sweep.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertFalse(path.exists())

    def test_fixture_roms_are_complete_binary_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);spec=sweep.CASES[-3]
            sweep.fixture(spec,folder)
            n=1<<spec[1];hop=1<<spec[2]
            for name,bits,expected in (
                ('window.mem',18,[-131072 & ((1<<18)-1)]*n),
                ('recip.mem',24,[v for row in sweep.fixed.reciprocals(n,hop) for v in row])):
                lines=(folder/name).read_text().splitlines()
                self.assertTrue(all(len(line)==bits and set(line)<={'0','1'} for line in lines))
                self.assertEqual([int(line,2) for line in lines],expected)
if __name__=='__main__':unittest.main()
