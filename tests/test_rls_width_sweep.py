"""RLS full-state dot bounds, arbitrary-code versus trajectory scope and evidence gates."""
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
import rls_widths as widths
import rls_width_sweep as study


class TestRlsWidths(unittest.TestCase):
    def test_exact_corners_minimal_width_and_rounding_headroom(self):
        for w,n in product((34,44,48),range(6)):
            b=widths.component_bounds(w,n);count=1<<n;top=count*(1<<(w+17))
            self.assertEqual(b['real_max'],top);self.assertEqual(b['real_min'],-top+count*(1<<18))
            self.assertEqual((b['imag_min'],b['imag_max']),(-top+count*(1<<17),top-count*(1<<17)))
            self.assertEqual(b['width'],w+19+n)
            self.assertGreater(b['real_max'],(1<<(b['width']-2))-1)
            self.assertLess(b['real_max']+b['rounding_add'],1<<(b['width']-1))
            self.assertGreaterEqual(b['real_min']+b['rounding_add'],-(1<<(b['width']-1)))
        for bad in (-1,11,True,1.5):
            with self.assertRaises(ValueError):widths.layout(bad)

    def test_matrix_and_quadratic_extrema_need_more_than_64_bits(self):
        b=widths.layout(4)
        self.assertEqual((b['pred_width'],b['dot_width'],b['q_width']),(57,67,71))
        self.assertEqual(b['bounds']['matrix']['real_max'],1<<65)
        self.assertEqual(b['bounds']['quadratic']['real_max'],1<<69)
        self.assertEqual(b['denominator_width'],51)
        self.assertLess(b['denominator_max'],1<<50);self.assertGreater(b['denominator_max'],(1<<49)-1)
        self.assertEqual(b['denominator_min'],-(1<<49)+1)


class TestRlsWidthEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=study.report()

    def proof(self):
        r=deepcopy(self.model);r['rtl_verified']=True
        for source in r['records']:
            n=source['log2n'];count=source['inputs']
            for layout,a,s in product(study.layouts(n),(1,0),study.SCENARIOS):
                r['rtl_equivalence'].append(dict(case=source['case'],layout=layout[0],widths=list(layout[1:]),active=a,scenario=s,
                    outputs=source['outputs'],weights=source['weights'],inputs=count,predictions=2*count,registers=2*count,
                    matrices=2*source['taps']*count,quadratics=count,denominators=count,pred_peak=0,matrix_peak=1,q_peak=1,cycles=100,observers_verified=True))
            for layout,a in product(study.invalid(n),(1,0)):
                r['rtl_parameters'].append(dict(case=source['case'],layout=layout[0],active=a,tag='PARAMETER',returncode=13))
        r['rtl_directed']=[dict(log2n=n,layout=l,active=a,predictions=32,matrices=32*(1<<n),quadratics=16)
                           for n,l,a in product(range(5),('selected','old_all'),(1,0))]
        r['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),(*study.TAGS,'ARITHMETIC'))]
        return r

    def test_json_roundtrip_with_directed_and_adaptive_scopes(self):
        study.check_acceptance(json.loads(json.dumps(self.model)));study.check_acceptance(json.loads(json.dumps(self.proof())))
        self.assertEqual(len(self.model['records']),8)
        self.assertEqual({r['stress'] for r in self.model['records']},{None,'weight34','p44'})
        self.assertEqual({r['log2n'] for r in self.model['records']},set(range(5)))

    def test_missing_duplicate_or_changed_records_rejected(self):
        for field,value in (('inputs',0),('vector_hashes',{}),('layout',{})):
            r=deepcopy(self.model);r['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('records','rtl_equivalence','rtl_parameters','rtl_directed','rtl_negative'):
            for duplicate in (False,True):
                r=self.proof()
                if duplicate:r[section][-1]=r[section][0]
                else:r[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_raw_observations_ranges_cycles_and_strict_fault_status(self):
        for field,value in (('predictions',0),('registers',0),('matrices',0),('quadratics',0),('denominators',0),
                            ('cycles',True),('cycles',101),('pred_peak',-1),('q_peak',1<<100),('matrix_peak',2),('observers_verified',False)):
            r=self.proof();r['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_parameters','rtl_negative'):
            for code in (0,True,'13'):
                r=self.proof();r[section][0]['returncode']=code
                with self.subTest(section=section,code=code),self.assertRaises(RuntimeError):study.check_acceptance(r)
        r=self.proof();r['rtl_directed'][0]['matrices']=0
        with self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            proc=subprocess.run([sys.executable,'-O',str(ROOT/'tools/rls_width_sweep.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(proc.returncode,0);self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
