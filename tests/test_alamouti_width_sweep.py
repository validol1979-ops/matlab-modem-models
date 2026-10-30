"""Proven Alamouti widths, attained extrema and complete raw-observation evidence."""
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
import alamouti_widths as widths
import alamouti_width_sweep as study


class TestAlamoutiWidths(unittest.TestCase):
    def test_all_256_corners_and_exact_minimal_widths(self):
        rows=[widths.sums(v[:4],v[4:]) for v in product((-131072,131071),repeat=8)]
        bound=widths.layout()
        self.assertEqual(bound['bounds'],[dict(min=min(v[k] for v in rows),max=max(v[k] for v in rows)) for k in range(4)])
        self.assertEqual(bound['bounds'][0],dict(min=-(1<<36)+(1<<19),max=1<<36))
        for k in (1,2,3):self.assertEqual(bound['bounds'][k],dict(min=-(1<<36)+(1<<18),max=(1<<36)-(1<<18)))
        self.assertEqual(bound['sum_width'],38);self.assertEqual(bound['energy_width'],37)
        self.assertEqual(4*131072**2,1<<36)
        for a,b in product((-131072,131071),repeat=2):
            for value in (a*b,-a*b):self.assertTrue(-(1<<35)<=value<(1<<35))

    def test_scale_and_rounding_proof_with_a_reachable_lower_width_failure(self):
        b=widths.layout();maximum=widths.sums((-131072,)*4,(-131072,)*4)[0]
        from beam_energy import exact_reciprocal
        r,s=exact_reciprocal(1<<36)
        self.assertEqual((maximum,r,s),(1<<36,1<<23,44))
        scaled=maximum*r;rounded=scaled+(1<<(s-1))
        self.assertEqual(scaled,1<<59);self.assertGreater(rounded,(1<<59)-1)
        self.assertEqual(rounded,b['rounded_upper_bound']);self.assertLess(rounded,1<<60)
        self.assertGreaterEqual(-(1<<59),-(1<<60))


class TestAlamoutiWidthEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=study.report()

    def proof(self):
        r=deepcopy(self.model);r['rtl_verified']=True
        for source in r['records']:
            for layout,a,s in product(study.LAYOUTS,(1,0),study.SCENARIOS):
                row={k:source[k] for k in ('bf_outputs','al_outputs','energy','sum_max','sum_min','scale_peak')}
                r['rtl_equivalence'].append(dict(row,case=source['case'],layout=layout[0],widths=list(layout[1:]),active=a,scenario=s,
                    cycles=100,stream_cycles=70,configuration_cycles=layout[2]+31,energy_checks=2,reciprocal_checks=1,
                    product_checks=16*source['pairs'],sum_checks=4*source['pairs'],scale_checks=4*source['pairs'],observers_verified=True))
            for layout,a in product(study.INVALID,(1,0)):
                r['rtl_parameters'].append(dict(case=source['case'],layout=layout[0],active=a,tag='PARAMETER',returncode=13))
        r['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),study.TAGS)]
        return r

    def test_report_roundtrip_and_fixtures_reach_every_proven_sum_bound(self):
        study.check_acceptance(json.loads(json.dumps(self.model)));study.check_acceptance(json.loads(json.dumps(self.proof())))
        for k,bound in enumerate(self.model['bounds']['bounds']):
            self.assertEqual(min(r['field_bounds'][k]['min'] for r in self.model['records']),bound['min'])
            self.assertEqual(max(r['field_bounds'][k]['max'] for r in self.model['records']),bound['max'])
        self.assertEqual(max(r['scale_peak'] for r in self.model['records']),1<<59)
        self.assertEqual(min(r['energy'] for r in self.model['records']),1)

    def test_changed_or_incomplete_fixtures_and_coverage_rejected(self):
        for field,value in (('energy',0),('vector_hashes',{}),('scale_peak',0),('sum_min',0)):
            r=deepcopy(self.model);r['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('records','rtl_equivalence','rtl_parameters','rtl_negative'):
            for duplicate in (False,True):
                r=self.proof()
                if duplicate:r[section][-1]=r[section][0]
                else:r[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_missing_raw_observations_or_changed_pipeline_rejected(self):
        for field,value in (('product_checks',0),('sum_checks',0),('scale_checks',0),('energy_checks',0),('reciprocal_checks',0),
                            ('scale_peak',0),('cycles',True),('stream_cycles',71),('configuration_cycles',1),('widths',[39,40,64]),('observers_verified',False)):
            r=self.proof();r['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_parameters','rtl_negative'):
            for code in (0,True,'13'):
                r=self.proof();r[section][0]['returncode']=code
                with self.subTest(section=section,code=code),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            proc=subprocess.run([sys.executable,'-O',str(ROOT/'tools/alamouti_width_sweep.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(proc.returncode,0);self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
