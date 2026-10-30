"""Exact LMS/NLMS intermediate bounds, independent trace and complete evidence gates."""
from copy import deepcopy
from itertools import product
import json
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT/'common/python')]
import lms_widths as widths
import lms_width_sweep as study
import lms_fixed as fixed


class TestLmsWidths(unittest.TestCase):
    def test_selected_widths_are_minimal_and_old_layout_is_safe(self):
        for n in range(5):
            r=widths.layout(n);s=r['selected'];b=r['bounds']
            self.assertEqual(s,dict(pred_width=53+n,error_width=19,step_width=46,coeff_width=45,delta_width=63,weight_width=58,dump_width=35))
            self.assertTrue(all(r['old_safe'].values()))
            for name,key in (('pred_width','pred_raw'),('error_width','error'),('step_width','step_raw'),('coeff_width','coeff'),
                             ('delta_width','delta_raw'),('weight_width','weight'),('dump_width','dump_raw')):
                low,high=b[key];w=s[name]
                self.assertTrue(-(1<<(w-1))<=low and high<(1<<(w-1)),name)
                self.assertTrue(low<-(1<<(w-2)) or high>=(1<<(w-2)),name)
            self.assertEqual(b['product_width'],53);self.assertEqual(b['sum_width'],53+n)
        for n in (-1,28,True,2.5):
            with self.assertRaises(ValueError):widths.layout(n)

    def test_contract_extrema(self):
        self.assertEqual((min(fixed.RECIPROCAL),max(fixed.RECIPROCAL)),(513,1024))
        self.assertEqual(widths.RECIPROCAL,fixed.RECIPROCAL)
        b=widths.layout(4)['bounds']
        self.assertEqual(b['k_max'],1<<27);self.assertEqual((b['shift_min'],b['shift_max']),(1,31))
        self.assertEqual(b['step'],[-(1<<44),1<<44]);self.assertEqual(b['coeff'],[-(1<<43),1<<43])
        self.assertEqual(b['delta'],[-(1<<61),1<<61]);self.assertEqual(b['delta_round'],[-(1<<56),1<<56])
        self.assertEqual(b['weight'],[-(1<<56)-(1<<33),(1<<56)+(1<<33)-1])
        self.assertEqual(b['product'],[-(1<<51)+(1<<17),1<<51]);self.assertEqual(b['sum'],[16*(-(1<<51)+(1<<17)),1<<55])
        self.assertEqual(b['error'],[-(1<<18)+1,(1<<18)-1]);self.assertEqual(b['dump_round'],[-(1<<18),1<<18])
        # Brute force of every coefficient for k, e, shift extremes.
        values=[(s,(k*e+(1<<(s-1)))>>s) for k in (0,1,1<<27) for e in (-(1<<17),(1<<17)-1,1<<17) for s in range(1,32)]
        self.assertEqual(max(abs(v) for _,v in values),1<<43)
        # Step width depends on LOG2N only once the round add reaches 2^44.
        self.assertEqual([widths.layout(n)['selected']['step_width'] for n in (17,18,19,20)],[46,47,47,48])

    def test_rtl_guards_match_python_formulas(self):
        text=(ROOT/'rtl/common/lms_filter.sv').read_text()
        for fragment in ('PRED_WIDTH = 53 + LOG2N','ERROR_WIDTH = 19','STEP_WIDTH = 46','COEFF_WIDTH = 45','DELTA_WIDTH = 63',
                         'WEIGHT_WIDTH = 58','DUMP_WIDTH = 35','PRED_WIDTH<53+LOG2N','ERROR_WIDTH<19','STEP_WIDTH<STEP_MIN',
                         'COEFF_WIDTH<45','DELTA_WIDTH<63','WEIGHT_WIDTH<58','DUMP_WIDTH<35'):
            self.assertIn(fragment,text)
        # The RTL step_min constant function: 2^44 + 2^(26+LOG2N) bit length + sign.
        for n in range(28):
            self.assertEqual(((1<<44)+(1<<(26+n))).bit_length()+1,widths.layout(n)['selected']['step_width'])

    def test_trace_matches_fixed_model(self):
        rng=random.Random(7)
        for mode,taps,mu,eps in (('lms',1,131072,512),('nlms',16,131072,512),('nlms',3,40000,10**6),('lms',5,2621,512)):
            x=[(rng.randint(-131072,131071),rng.randint(-131072,131071)) for _ in range(60)]
            d=[(rng.randint(-131072,131071),rng.randint(-131072,131071)) for _ in range(60)]
            out,w,peaks=widths.trace(x,d,taps,mode,mu,eps)
            self.assertEqual((out,w),fixed.adapt(x,d,taps,mode,(mu,eps)))
            b=widths.layout(4)['bounds']
            self.assertLessEqual(peaks[5],1<<43);self.assertLessEqual(peaks[6],max(map(abs,b['delta_raw'])))
        with self.assertRaises(ValueError):widths.trace([],[],0,'lms',1,512)


class TestLmsWidthEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=study.report()

    def proof(self):
        r=deepcopy(self.model);r['rtl_verified']=True
        for source in r['records']:
            for layout,a,scenario in product(study.layouts(source['log2n']),(1,0),study.SCENARIOS):
                r['rtl_equivalence'].append(dict(case=source['case'],layout=layout[0],widths=list(layout[1]),active=a,scenario=scenario,
                    outputs=source['outputs'],weights=source['weights'],cycles=100,energy_checks=source['inputs'],observers_verified=True,
                    **dict(zip(study.COUNTS,study.expected_counts(source))),**dict(zip(study.PEAKS,source['peaks']))))
            for layout,a in product(study.invalid(source['log2n']),(1,0)):
                r['rtl_parameters'].append(dict(case=source['case'],layout=layout[0],active=a,tag='PARAMETER',returncode=13))
        r['rtl_directed']=[dict(log2n=n,layout=l,active=a,checks=study.DIRECTED(n)) for n,l,a in product((0,4),('selected','old_all'),(1,0))]
        r['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),(*study.TAGS,'ARITHMETIC'))]
        return r

    def test_cases_cover_modes_sizes_and_stress(self):
        study.check_acceptance(json.loads(json.dumps(self.model)));study.check_acceptance(json.loads(json.dumps(self.proof())))
        records={r['case']:r for r in self.model['records']}
        self.assertEqual({r['mode'] for r in records.values()},{'lms','nlms'})
        self.assertEqual({r['log2n'] for r in records.values()},{0,1,2,4})
        self.assertLess(records['nlms_n4_t3']['taps'],1<<records['nlms_n4_t3']['log2n'])
        self.assertTrue(records['nlms_coeff_n16']['coefficient_bound_reached'])
        self.assertEqual(records['nlms_coeff_n16']['peaks'][0],1<<51)
        self.assertEqual(len(study.layouts(4)),9);self.assertEqual(len(study.invalid(4)),14)
        self.assertEqual(study.layouts(0)[-1][1],(64,64,64,47,65,64,64))

    def test_changed_incomplete_or_duplicated_records_rejected(self):
        for field,value in (('weights',0),('vector_hashes',{}),('peaks',[0]*9)):
            r=deepcopy(self.model);r['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('records','rtl_equivalence','rtl_parameters','rtl_directed','rtl_negative'):
            for duplicate in (False,True):
                r=self.proof()
                if duplicate:r[section][-1]=r[section][0]
                else:r[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_counts_peaks_cycles_and_fault_status(self):
        changes=[(k,0) for k in study.COUNTS]+[('delta_peak',1),('coeff_peak',-1),('energy_checks',0),('cycles',True),('cycles',101),('observers_verified',False),('widths',[])]
        for field,value in changes:
            r=self.proof();r['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_parameters','rtl_negative'):
            for code in (0,True,'13'):
                r=self.proof();r[section][0]['returncode']=code
                with self.subTest(section=section,code=code),self.assertRaises(RuntimeError):study.check_acceptance(r)
        r=self.proof();r['rtl_directed'][0]['checks']=[0]*7
        with self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json';p=subprocess.run([sys.executable,'-O',str(ROOT/'tools/lms_width_sweep.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(p.returncode,0);self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
