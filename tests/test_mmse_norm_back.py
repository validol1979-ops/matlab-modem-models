"""Stored-code extrema, prefix bounds, independent traces and evidence rejection."""
import copy
from itertools import product
from pathlib import Path
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'common/python'),str(ROOT/'tools')]
import mmse_norm_back_widths as w
import mmse_n_fixed as fixed
from mmse_n_cases import channel
import mmse_norm_back_sweep as s


class Arithmetic(unittest.TestCase):
    def test_shift_extrema_rounding_and_minimality(self):
        for bits,extra,name in ((40,30,'norm'),(72,15,'weight')):
            bound=w.bounds(2)[name];observed=[]
            for x,amount in product((-(1<<(bits-1)),-1,0,1,(1<<(bits-1))-1),range(-extra,9 if bits==40 else 24)):
                y=w.rnd(x,amount);observed.append(y)
                self.assertTrue(bound['min']<=y<=bound['max'])
                if amount>0:
                    before=x+(1<<(amount-1))
                    self.assertTrue(-(1<<(bound['bits']-1))<=before<(1<<(bound['bits']-1)))
            self.assertEqual((min(observed),max(observed)),(bound['min'],bound['max']))
            self.assertEqual(bound['bits'],70 if bits==40 else 87)
            self.assertLess(bound['min'],-(1<<(bound['bits']-2)))
        self.assertEqual([w.rnd(x,1) for x in (-3,-1,0,1,3)],[-1,0,0,1,2])

    def test_multiplier_conjugate_negative_rail(self):
        self.assertEqual(w.bounds(2)['mult_im']['max'],1<<63)
        self.assertEqual(-(-(1<<33)<<30),1<<63)
        self.assertEqual(w.bounds(2)['mult_im']['bits'],65)
        self.assertEqual(w.bounds(2)['mult_re']['bits'],64)

    def test_all_complex_corners_and_prefixes(self):
        a,b=1<<33,1<<71
        rows=[w.cmul(v[:2],v[2:]) for v in product((-a,a-1),(-a,a-1),(-b,b-1),(-b,b-1))]
        for n in range(2,9):
            bounds=w.bounds(n);expected=106+(n-1).bit_length()
            for axis,name in enumerate(('re','im')):
                lo,hi=min(r[axis] for r in rows),max(r[axis] for r in rows)
                self.assertEqual((lo,hi),(bounds['product_'+name]['min'],bounds['product_'+name]['max']))
                accum=[(seed<<30)-t*r[axis] for seed,t,r in product((-b,b-1),range(n),rows)]
                self.assertEqual((min(accum),max(accum)),(bounds['acc_'+name]['min'],bounds['acc_'+name]['max']))
                self.assertLessEqual(bounds['acc_'+name]['bits'],expected)
            self.assertEqual(bounds['product_im']['bits'],107)
            self.assertEqual(bounds['acc_im']['bits'],expected)
            self.assertLess(bounds['acc_im']['min'],-(1<<(expected-2)))
        for n in (True,1,9,2.0):
            with self.assertRaises(ValueError):w.bounds(n)

    def test_trace_matches_unchanged_fixed_model(self):
        for n,case in product(range(2,9),('identity','complex','wide','random_complex','conditioned','tiny_identity')):
            h,l=channel(case,n,104+n);t=w.trace([p for row in h for p in row],fixed.lambda_raw(l),n)
            self.assertEqual(t['weights'],[p for row in fixed.weights(h,l) for p in row])
            self.assertEqual([r['count'] for r in t['banks']],
                             [n*(n+1)//2]*2+[n*(n-1)//2]*2+[n*n*(n-1)//2]*2+[n*n*(n+1)//2]*2+[n*n]*2)


class Evidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        d=s.report();d['rtl_verified']=True
        for src in d['records']:
            k,n,c=src['kind'],src['n'],src['case'];sp=s.SPECS[k]
            for l,a,scenario in product(sp['layouts'],(1,0),s.SCENARIOS):
                factor=2 if scenario in ('midreset','outreset') else 1
                d['streams'].append(dict(kind=k,n=n,case=c,layout=l[0],active=a,scenario=scenario,widths=list(s.values(l,n)),
                    outputs=src['outputs'],cycles=500,config_cycles=100,banks=[dict(b,count=b['count']*factor) for b in src['banks']]))
            for a,scenario in product((1,0),s.SCENARIOS):
                d['frozen'].append(dict(kind=k,n=n,case=c,active=a,scenario=scenario,old_cycles=500,new_cycles=500,
                    old_outputs=src['outputs'],new_outputs=src['outputs'],old_config_cycles=100,new_config_cycles=100))
        for k,sp in s.SPECS.items():
            for n,l,a in product(sp['sizes'],sp['layouts'],(1,0)):
                d['directed'].append(dict(kind=k,n=n,layout=l[0],active=a,checks=3808+96*(n-1)))
            for n in sp['sizes']:
                for l,a in product(s.invalid(k,n),(1,0)):d['parameters'].append(dict(kind=k,n=n,layout=l[0],active=a,returncode=13))
            for b,t,a in product(('stream','directed'),sp['tags'],(1,0)):d['negative'].append(dict(kind=k,bench=b,tag=t,active=a,returncode=13))
            for n,l in product(sp['sizes'],sp['layouts']):d['lint'].append(dict(kind=k,n=n,layout=l[0],warnings=0))
        cls.complete=d

    def test_matrix_missing_and_duplicate(self):
        s.check_acceptance(self.complete);s.check_acceptance(s.report())
        for section in s.SECTIONS:
            for duplicate in (False,True):
                d=copy.deepcopy(self.complete)
                if duplicate:d[section][-1]=d[section][0]
                else:d[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):s.check_acceptance(d)

    def test_forged_observations(self):
        for section,key,value in [('streams','cycles',501),('streams','config_cycles',0),('streams','outputs',1),
                ('directed','checks',0),('parameters','returncode',0),('negative','returncode',True),('lint','warnings',1),
                ('frozen','old_cycles',501),('streams','n',True),('streams','widths',[70,87,65,107,112])]:
            d=copy.deepcopy(self.complete);d[section][0][key]=value
            with self.subTest(section=section,key=key),self.assertRaises(RuntimeError):s.check_acceptance(d)
        d=copy.deepcopy(self.complete);d['streams'][0]['banks'][0]['max']+=1
        with self.assertRaises(RuntimeError):s.check_acceptance(d)
        d=copy.deepcopy(self.complete);d['streams'][0]['banks'][0]['min']=False
        with self.assertRaises(RuntimeError):s.check_acceptance(d)

if __name__=='__main__':unittest.main()
