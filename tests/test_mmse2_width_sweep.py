"""Proven mmse2 expression widths, reachable lower-width failures and complete raw evidence."""
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
import mmse2_widths as widths
import mmse2_width_sweep as study
import mmse_fixed

LO,HI=widths.LO,widths.HI


def fits(value,width):return -(1<<(width-1))<=value<(1<<(width-1))


def random_h(rng):
    pick=lambda:rng.choice((LO,HI,0,rng.randint(LO,HI)))
    return tuple((pick(),pick()) for _ in range(4))


class TestMmse2Bounds(unittest.TestCase):
    def test_gram_and_det_intervals_are_exact_formulas(self):
        b=widths.layout();A=(1<<36)+(1<<34)-1
        self.assertEqual(b['gram'],dict(a=[0,A],d=[0,A],b_re=[-(1<<36)+(1<<19),1<<36],b_im=[-(1<<36)+(1<<18),(1<<36)-(1<<18)]))
        self.assertEqual(b['det'],[-((1<<72)+((1<<36)-(1<<18))**2),A*A])
        self.assertEqual(b['widths'],dict(gram=38,det=74,m=55,m_interval=56,scale=78,sum=68))
        self.assertTrue(A*A<(1<<73) and (1<<72)+((1<<36)-(1<<18))**2<=(1<<73))
        self.assertEqual(widths.trace(((LO,LO),)*4,0)['gram'][0],1<<36)            # signed37 fails
        self.assertFalse(fits(1<<36,37))

    def test_identity_bounds_hold_against_the_rtl_expressions(self):
        rng=random.Random(20261020)
        for _ in range(4000):
            h=random_h(rng);lam=rng.choice((0,1,widths.LAMBDA_MAX,rng.randrange(1<<34)))
            t=widths.trace(h,lam)
            hr=[v[0] for v in h];hi=[v[1] for v in h]
            d=(hr[0]*hr[3]-hi[0]*hi[3]-hr[1]*hr[2]+hi[1]*hi[2],hr[0]*hi[3]+hi[0]*hr[3]-hr[1]*hi[2]-hi[1]*hr[2])
            # det G = |det H|^2 + LAMBDA tr(H^H H) + LAMBDA^2, exactly in integers.
            self.assertEqual(t['det'],d[0]**2+d[1]**2+lam*sum(x*x for x in hr+hi)+lam*lam)
            self.assertLessEqual(d[0]**2+d[1]**2,1<<72)
            self.assertTrue(widths.det_interval()[0]<=t['det']<=widths.det_interval()[1])
            if t['m'] is None:continue
            # adj(G) H^H = conj(det H) adj(H) + LAMBDA H^H, checked exactly in integers.
            adj=[(hr[3],hi[3]),(-hr[1],-hi[1]),(-hr[2],-hi[2]),(hr[0],hi[0])]
            hh=[(hr[0],-hi[0]),(hr[2],-hi[2]),(hr[1],-hi[1]),(hr[3],-hi[3])]
            for k in range(4):
                expected=(d[0]*adj[k][0]+d[1]*adj[k][1]+lam*hh[k][0],d[0]*adj[k][1]-d[1]*adj[k][0]+lam*hh[k][1])
                self.assertEqual((t['m'][2*k],t['m'][2*k+1]),expected)
            self.assertLessEqual(max(map(abs,t['m'])),widths.m_bound())
            interval=widths.m_interval();self.assertTrue(all(interval[0]<=v<=interval[1] for v in t['m']))
            scale=widths.scale_bounds()
            for m,s in zip(t['m'],t['scaled']):
                self.assertTrue(scale['positive'][0]<=m*t['reciprocal']<=scale['positive'][1])
                if t['z']<39:self.assertLessEqual(abs(s),scale['left_shift_abs'])
            if not t['overflow']:
                W=mmse_fixed.weights([[h[0],h[1]],[h[2],h[3]]],lam/(1<<30))
                self.assertEqual([x for row in W for c in row for x in c],t['scaled'])

    def test_reachable_witnesses_fail_one_bit_narrower(self):
        b=widths.layout();w=b['witnesses']
        det=widths.trace(*widths.DET_WITNESS);scale=widths.trace(*widths.SCALE_WITNESS)
        self.assertEqual(w['det'],det['det']);self.assertFalse(fits(det['det'],73));self.assertTrue(fits(det['det'],74))
        self.assertFalse(fits(w['m'],54));self.assertTrue(fits(w['m'],55));self.assertEqual(w['m'],max(map(abs,det['m'])))
        self.assertFalse(fits(w['scale'],77));self.assertTrue(fits(w['scale'],78))
        for t in (det,scale):self.assertFalse(t['overflow'])                    # both configure normally
        self.assertLess(b['m_abs_bound'],1<<54);self.assertGreaterEqual(b['m_interval'][1],1<<54)
        self.assertLess(b['scale']['positive'][1],1<<77);self.assertLess(b['scale']['left_shift_abs'],1<<57)
        self.assertEqual(b['scale']['amount_max'],56)

    def test_small_determinant_left_shift_bound(self):
        # det = 1 with large entries: the left-shift branch of the coefficient overflow fixture.
        t=widths.trace(study.OVERFLOW_H,0)
        self.assertEqual((t['det'],t['z'],t['overflow']),(1,23,True))
        self.assertLessEqual(max(map(abs,t['m'])),widths.small_det_bound(1))
        self.assertLessEqual(max(map(abs,t['scaled'])),widths.scale_bounds()['left_shift_abs'])
        rng=random.Random(5)
        for _ in range(3000):
            h=tuple((rng.randint(-3,3),rng.randint(-3,3)) for _ in range(4));lam=rng.randint(0,2)
            t=widths.trace(h,lam)
            if t['m'] is None or t['det']>=1<<16:continue
            self.assertLessEqual(max(map(abs,t['m'])),widths.small_det_bound(t['det'].bit_length()))

    def test_sum_width_is_exact_for_full_weight_codes(self):
        s=widths.sum_intervals();w=-(1<<47);o=(LO,LO)
        y=widths.sums([w]*8,o,o)
        self.assertEqual((y[1],y[3]),(1<<66,1<<66))
        self.assertEqual(s['im'],(-(1<<66)+(1<<19),1<<66));self.assertEqual(s['re'],(-(1<<66)+(1<<18),(1<<66)-(1<<18)))
        self.assertFalse(fits((1<<66)+(1<<23),67));self.assertTrue(fits((1<<66)+(1<<23),68))
        # Every sum is multilinear in its 8 distinct signed48/signed18 operands: corners are the extremes.
        W=(-(1<<47),(1<<47)-1);O=(LO,HI)
        values=[widths.sums(list(v[:4])+[0]*4,v[4:6],v[6:]) for v in product(W,W,W,W,O,O,O,O)]
        for k,key in ((0,'re'),(1,'im')):
            self.assertEqual((min(r[k] for r in values),max(r[k] for r in values)),tuple(s[key]))


class TestMmse2WidthEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.model=study.report()

    def proof(self):
        r=deepcopy(self.model);r['rtl_verified']=True
        for source in r['records']:
            for layout,a,s in product(study.LAYOUTS,(1,0),study.SCENARIOS):
                c=study.CONFIGS[s]
                r['rtl_equivalence'].append(dict({k:source[k] for k in study.PEAKS},case=source['case'],layout=layout[0],widths=list(layout[1:]),
                    active=a,scenario=s,outputs=source['outputs'],cycles=500,reciprocal_cycles=109,configuration_cycles=112,
                    gram_checks=4*c,det_checks=c,reciprocal_checks=c,m_checks=8*c,product_checks=8*c,scale_checks=8*c,weight_checks=8*c,
                    sum_checks=4*source['pairs']+(4 if c>1 else 0),observers_verified=True))
        for layout,a in product(study.LAYOUTS,(1,0)):
            r['rtl_extra'].append(dict(scenario='singular',layout=layout[0],active=a,gram_checks=4,det_checks=1,reciprocal_checks=0,m_checks=0,
                                       det_peak=self.model['extra']['singular']['det']))
            r['rtl_extra'].append(dict(self.model['extra']['overflow'],scenario='overflow',layout=layout[0],active=a,gram_checks=4,det_checks=1,
                                       reciprocal_checks=1,m_checks=8,product_checks=8,scale_checks=8,weight_checks=0))
        r['rtl_parameters']=[dict(layout=l[0],active=a,tag='PARAMETER',returncode=13) for l,a in product(study.INVALID,(1,0))]
        r['rtl_negative']=[dict(active=a,tag=t,returncode=13) for a,t in product((1,0),study.TAGS)]
        r['rtl_lint']=[dict(layout=l[0],warnings=0) for l in study.LAYOUTS]
        return r

    def test_report_roundtrip_and_fixtures_reach_the_witnesses(self):
        study.check_acceptance(json.loads(json.dumps(self.model)));study.check_acceptance(json.loads(json.dumps(self.proof())))
        w=self.model['bounds']['witnesses'];records=self.model['records']
        self.assertEqual(max(r['det_peak'] for r in records),w['det'])
        self.assertEqual(max(r['m_peak'] for r in records),w['m'])
        self.assertEqual(max(r['product_peak'] for r in records),w['scale'])
        self.assertEqual(min(r['z'] for r in records),23)                       # tiny identity: left shift by 16

    def test_changed_or_incomplete_evidence_rejected(self):
        for field,value in (('det_peak',0),('vector_hashes',{}),('m_peak',1)):
            r=deepcopy(self.model);r['records'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_equivalence','rtl_extra','rtl_parameters','rtl_negative','rtl_lint'):
            for duplicate in (False,True):
                r=self.proof()
                if duplicate:r[section][-1]=r[section][0]
                else:r[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):study.check_acceptance(r)
        for field,value in (('m_checks',0),('sum_checks',0),('scale_checks',1),('reciprocal_checks',2),('m_peak',0),('cycles',True),
                            ('widths',[39,76,58,84,68]),('observers_verified',False),('configuration_cycles',0)):
            r=self.proof();r['rtl_equivalence'][0][field]=value
            with self.subTest(field=field),self.assertRaises(RuntimeError):study.check_acceptance(r)
        r=self.proof();r['rtl_equivalence'][1]['cycles']=501
        with self.assertRaises(RuntimeError):study.check_acceptance(r)
        r=self.proof();r['rtl_lint'][0]['warnings']=1
        with self.assertRaises(RuntimeError):study.check_acceptance(r)
        for section in ('rtl_parameters','rtl_negative'):
            for code in (0,True,'13'):
                r=self.proof();r[section][0]['returncode']=code
                with self.subTest(section=section,code=code),self.assertRaises(RuntimeError):study.check_acceptance(r)

    def test_optimized_verification_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'result.json'
            proc=subprocess.run([sys.executable,'-O',str(ROOT/'tools/mmse2_width_sweep.py'),'--output',str(path)],capture_output=True,text=True)
            self.assertNotEqual(proc.returncode,0);self.assertFalse(path.exists())
if __name__=='__main__':unittest.main()
