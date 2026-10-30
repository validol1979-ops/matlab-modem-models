"""Exact FIR box bounds, rounding safety and complete width-qualification evidence."""
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
import fir_fixed as fixed
import fir_widths as widths
import fir_width_sweep as sweep


class TestFirWidths(unittest.TestCase):
    def test_minimal_product_and_tree_widths_over_all_operand_corners(self):
        corners=(-131072,131071)
        products=[x*h for x,h in product(corners,repeat=2)]
        values=[(hr*xr-hi*xi,hr*xi+hi*xr) for hr,hi,xr,xi in product(corners,repeat=4)]
        self.assertEqual((min(products),max(products)),(-(1<<34)+(1<<17),1<<34))
        for log2lanes in (0,1,2,3,6,7):
            layout=widths.tree_layout(log2lanes)
            for row in layout['levels']:
                count=1<<row['level']
                for axis,key in ((0,'real_width'),(1,'imag_width')):
                    low=count*min(z[axis] for z in values);high=count*max(z[axis] for z in values)
                    width=row[key]
                    self.assertGreaterEqual(low,-(1<<(width-1)))
                    self.assertLessEqual(high,(1<<(width-1))-1)
                    self.assertTrue(low<-(1<<(width-2)) or high>(1<<(width-2))-1)
            self.assertEqual(layout['saved_bits'],layout['uniform_bits']-layout['compact_bits'])
        self.assertEqual(widths.tree_layout(6)['compact_bits'],9511)
        self.assertEqual(widths.tree_layout(6)['uniform_bits'],10922)
        for bad in (-1,8,1.5,True):
            with self.assertRaises(ValueError):widths.tree_layout(bad)

    def test_bounds_equal_exhaustive_signed_box_vertices(self):
        pairs=list(product((-131072,131071),repeat=2))
        for taps in ([(65536,0)],[(-131072,-131072)],[(47,-19),(-9,38),(13,6)]):
            values=[]
            for samples in product(pairs,repeat=len(taps)):
                values.append(sweep.raw_convolution(samples,taps)[len(taps)-1])
            measured={axis:[min(row[i] for row in values),max(row[i] for row in values)] for i,axis in enumerate(('re','im'))}
            self.assertEqual(widths.bounds(taps),measured)

    def test_rounding_bias_is_in_the_bound(self):
        taps=[(65536,0)];limits=widths.bounds(taps)
        # Raw sums fit signed34, but the largest input plus the half-up bias does not.
        self.assertLessEqual(limits['re'][1],(1<<33)-1)
        self.assertGreater(limits['re'][1]+65536,(1<<33)-1)
        self.assertFalse(widths.fits(limits,34));self.assertEqual(widths.select(taps),35)

    def test_full_scale_minimum_imaginary_taps_need_the_extra_sign_bit(self):
        for log2tmax in (0,1,3,6,7):
            taps=[(-131072,-131072)]*(1<<log2tmax)
            self.assertEqual(widths.bounds(taps)['im'][1],1<<(35+log2tmax))
            self.assertEqual(widths.select(taps),37+log2tmax)

    def test_frame_edges_and_partial_sums_fit_the_selected_width(self):
        taps=[(131071,-131072),(-37,991),(49,-78),(-1961,211)]
        limits=widths.bounds(taps)
        for size in range(1,len(taps)+1):
            subset=widths.bounds(taps[:size])
            for axis in ('re','im'):
                self.assertGreaterEqual(subset[axis][0],limits[axis][0])
                self.assertLessEqual(subset[axis][1],limits[axis][1])
        self.assertEqual(widths.select([(0,0)]*3),18)

    def test_invalid_taps_and_widths(self):
        for taps in ([],[(131072,0)],[(0,-131073)],[(.5,0)],[(True,0)],[(0,)],[(0,0,0)]):
            with self.subTest(taps=taps),self.assertRaises(ValueError):widths.bounds(taps)
        for width in (17,64,True,35.5):
            with self.subTest(width=width),self.assertRaises(ValueError):widths.fits({'re':[0,0],'im':[0,0]},width)


class TestFirWidthEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=sweep.report()

    def proof(self):
        report=deepcopy(self.model);report['rtl_verified']=True
        for row in report['records']:
            for width,compact,active,scenario in product({row['default_width'],row['selected_width']},(0,1),(1,0),sweep.SCENARIOS):
                report['rtl_equivalence'].append(dict(case=row['case'],width=width,compact_tree=compact,active=active,scenario=scenario,
                                                     outputs=row['outputs'],raw_sums=row['outputs'],saturation=row['saturation'],bounds_verified=True,
                                                     tree_nodes=row['issues']*(2*(1<<row['log2lanes'])-1),product_words=4*(1<<row['log2lanes'])*row['issues'],cycles=100))
            for width,reject in [(row['selected_width'],False)]+([(row['selected_width']-1,True)] if row['selected_width']>18 else []):
                for active in (1,0):report['rtl_guards'].append(dict(case=row['case'],width=width,active=active,rejected=reject,sticky_reset_recovery_verified=True))
        report['rtl_negative']=[dict(active=a,returncode=13,tag=tag) for a in (1,0) for tag in ('ACCUMULATOR','TREE','PRODUCT')]
        return report

    def test_report_and_synthetic_evidence_schema(self):
        sweep.check_acceptance(self.model);sweep.check_acceptance(self.proof())
        sweep.check_acceptance(json.loads(json.dumps(self.model)))
        sweep.check_acceptance(json.loads(json.dumps(self.proof())))
        self.assertEqual(len(self.model['records']),12)
        self.assertTrue(any(row['clamp_events']>0 for row in self.model['records']))
        self.assertTrue(all(row['observed_bounds']==row['bounds'] for row in self.model['records']))

    def test_changed_measurements_are_rejected(self):
        for field,value in (('selected_width',34),('coefficient_hash','bad'),('outputs',1),('input_hash','bad'),('fractional_bits',16)):
            report=deepcopy(self.model);report['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):sweep.check_acceptance(report)
        report=deepcopy(self.model);report['records'][0]['bounds']['re'][1]+=1
        with self.assertRaises(RuntimeError):sweep.check_acceptance(report)

    def test_missing_duplicated_and_unmeasured_rtl_are_rejected(self):
        for section in ('records','rtl_equivalence','rtl_guards','rtl_negative'):
            for duplicate in (False,True):
                report=self.proof()
                if duplicate:report[section][-1]=report[section][0]
                else:report[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):sweep.check_acceptance(report)
        report=self.proof();report['rtl_verified']=False
        with self.assertRaises(RuntimeError):sweep.check_acceptance(report)

    def test_incomplete_arithmetic_and_lifecycle_checks_are_rejected(self):
        for field,value in (('raw_sums',0),('saturation',[0,0,0,999]),('bounds_verified',False),('tree_nodes',0),('product_words',0),('cycles',0),('cycles',101)):
            report=self.proof();report['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):sweep.check_acceptance(report)
        report=self.proof();report['rtl_guards'][0]['sticky_reset_recovery_verified']=False
        with self.assertRaises(RuntimeError):sweep.check_acceptance(report)
        report=self.proof();report['rtl_negative'][0]['returncode']=0
        with self.assertRaises(RuntimeError):sweep.check_acceptance(report)

    def test_saved_vectors_use_the_same_unclipped_sums_and_original_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);record=sweep.fixture(9,sweep.CASES[9],folder)
            raw=[tuple(map(int,line.split())) for line in (folder/'accumulator.txt').read_text().splitlines()[1:]]
            out=[tuple(map(int,line.split())) for line in (folder/'out.txt').read_text().splitlines()[1:]]
            self.assertEqual(sweep.row_hash(raw),record['raw_hash'])
            self.assertEqual(sweep.row_hash(out),record['output_hash'])
            self.assertEqual([(fixed.sat18((re+65536)>>17),fixed.sat18((im+65536)>>17)) for re,im in raw],
                             [row[:2] for row in out])
            self.assertGreater(max(im for re,im in raw),131071<<17)

    def test_optimized_verification_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'result.json'
            result=subprocess.run([sys.executable,'-O',str(ROOT/'tools/fir_width_sweep.py'),'--output',str(target)],capture_output=True,text=True)
            self.assertNotEqual(result.returncode,0);self.assertFalse(target.exists())


if __name__=='__main__':unittest.main()
