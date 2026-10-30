"""Exact update bounds and complete raw/register evidence, separate from reachability."""
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
import rls_update_widths as widths
import rls_update_sweep as study


class TestRlsUpdateWidths(unittest.TestCase):
    def test_exact_complex_corners_and_rounding_headroom(self):
        for a,b,shift in ((40,18,15),(40,48,30)):
            raw=widths.complex_bounds(a,b,shift)
            self.assertEqual(raw[0]['max'],1<<(a+b-1))
            self.assertEqual(raw[0]['width'],a+b+1)
            self.assertEqual(raw[1]['width'],a+b)
            self.assertEqual(raw[0]['min'],-(1<<(a+b-1))+(1<<min(a,b)))
            for row in raw:
                self.assertLess(row['max']+(1<<(shift-1)),1<<(row['width']-1))
                self.assertGreaterEqual(row['min']+(1<<(shift-1)),-(1<<(row['width']-1)))

    def test_scalar_covariance_weight_and_gain_extrema(self):
        b=widths.layout();p=(-(1<<43),(1<<43)-1);t=(-(1<<45),(1<<45)-1)
        values=[(x-y)*z for x,y,z in product(p,t,(0,(1<<32)-1))]
        self.assertEqual((min(values),max(values)),(b['cov_min'],b['cov_max']))
        self.assertEqual(widths.signed_width(min(values),max(values)),79)
        self.assertEqual(widths.signed_width(b['cov_delta_min'],b['cov_delta_max']),47)
        self.assertLess(max(values)+(1<<29),1<<78)
        self.assertEqual(widths.signed_width(b['gain_min'],b['gain_max']),71)
        self.assertEqual(b['gain_min'],-(1<<47)*(1<<23))
        self.assertEqual(b['variable_gain_rounding_width'],128)
        self.assertEqual(widths.signed_width(min(r['min'] for r in b['weights']),max(r['max'] for r in b['weights'])),44)
        self.assertGreater(max(r['max'] for r in b['weights']),(1<<42)-1)


class TestRlsUpdateEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=study.report()

    def proof(self):
        r=deepcopy(self.model);r['rtl_verified']=True
        for source in r['records']:
            s=source['inputs'];t=source['taps'];counts=[2*s*t]*5+[s*t*(t+1)]*2+[s*t*t,2*s*t*t]
            for layout,a,scenario in product(study.LAYOUTS,(1,0),study.SCENARIOS):
                r['rtl_equivalence'].append(dict(case=source['case'],layout=layout[0],widths=list(layout[1]),active=a,scenario=scenario,
                    outputs=source['outputs'],weights_total=source['weights_total'],cycles=100,observers_verified=True,
                    **dict(zip(study.COUNTS,counts)),**dict.fromkeys(study.PEAKS,1)))
            for layout,a in product(study.INVALID,(1,0)):
                r['rtl_parameters'].append(dict(case=source['case'],layout=layout[0],active=a,tag='PARAMETER',returncode=13))
        r['rtl_directed']=[dict(log2n=n,layout=l,active=a,gain=16*(1<<n),updates=192*(1<<n),pt=64*(1<<n)**2,cov=48*(1<<n)**2)
                           for n,l,a in product((0,4),('selected','old_all'),(1,0))]
        r['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),(*study.TAGS,'ARITHMETIC'))]
        return r

    def test_json_roundtrip_full_layout_and_stage_coverage(self):
        study.check_acceptance(json.loads(json.dumps(self.model)));study.check_acceptance(json.loads(json.dumps(self.proof())))
        self.assertEqual(len(study.LAYOUTS),7);self.assertEqual(len(study.INVALID),10)
        self.assertEqual(len(self.model['records']),5)
        self.assertEqual({r['stress'] for r in self.model['records']},{None,'weight34','p44'})

    def test_changed_incomplete_or_duplicated_records_rejected(self):
        for field,value in (('weights_total',0),('vector_hashes',{}),('inputs',0)):
            r=deepcopy(self.model);r['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('records','rtl_equivalence','rtl_parameters','rtl_directed','rtl_negative'):
            for duplicate in (False,True):
                r=self.proof()
                if duplicate:r[section][-1]=r[section][0]
                else:r[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_raw_register_counts_peaks_cycles_and_fault_status(self):
        changes=[(k,0) for k in study.COUNTS]+[('gain_peak',-1),('cov_peak',1<<100),('product_peak',2),('cycles',True),('cycles',101),('observers_verified',False)]
        for field,value in changes:
            r=self.proof();r['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_parameters','rtl_negative'):
            for code in (0,True,'13'):
                r=self.proof();r[section][0]['returncode']=code
                with self.subTest(section=section,code=code),self.assertRaises(RuntimeError):study.check_acceptance(r)
        r=self.proof();r['rtl_directed'][0]['cov']=0
        with self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json';p=subprocess.run([sys.executable,'-O',str(ROOT/'tools/rls_update_sweep.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
