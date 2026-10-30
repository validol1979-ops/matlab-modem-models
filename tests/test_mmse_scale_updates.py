"""Endpoint arithmetic, minimality and independent configuration traces."""
import sys
from pathlib import Path
from itertools import product
import random
import copy
import unittest
ROOT=Path(__file__).resolve().parents[1];sys.path[:0]=[str(ROOT/'common/python'),str(ROOT/'tools')]
import mmse_scale_update_widths as w
import mmse3_fixed,mmse_n_fixed
from mmse3_cases import channel as channel3
from mmse_n_cases import channel as channeln


class TestArithmetic(unittest.TestCase):
    def test_scale_minimum_and_rounding_headroom(self):
        b=w.scale_bounds();self.assertEqual([b[k]['bits'] for k in ('product','round_add','scaled')],[129,130,145])
        self.assertEqual(w.scale(-(1<<105),1<<23,8)[1],-(1<<144))
        for v,r,s in product((-(1<<105),(1<<105)-1,-1,0,1),(1<<22,(1<<22)+1,(1<<23)-1,1<<23),range(8,135)):
            p,y,o=w.scale(v,r,s);self.assertTrue(-(1<<144)<=y<(1<<144));self.assertEqual(o,not -(1<<63)<=y<(1<<63))
        self.assertFalse(-(1<<143)<=-(1<<144)<(1<<143))

    def test_coefficient_asymmetric_rails_and_ties(self):
        for result in (-(1<<63)-1,-(1<<63),(1<<63)-1,1<<63):
            _,y,bad=w.scale(2*result,1<<23,48);self.assertEqual(y,result);self.assertEqual(bad,not -(1<<63)<=result<(1<<63))
        self.assertEqual([w.rnd(v,1) for v in (-3,-1,1,3)],[-1,0,1,2])

    def test_update_full_code_extrema(self):
        for bits,pw,uw in ((34,83,53),(72,121,91)):
            b=w.update_bounds(bits);self.assertEqual((b['product_bits'],b['update_bits']),(pw,uw))
            x=1<<(bits-1);peak=w.update((-(1<<47),)*2,(-x,)*2,(-x,)*2,bits)
            self.assertEqual(peak[1],2*(1<<47)*x);self.assertEqual(peak[3],-x-(peak[1]>>30))
            for v,width in ((peak[1],pw),(peak[3],uw)):
                self.assertTrue(-(1<<(width-1))<=v<(1<<(width-1)))
                self.assertFalse(-(1<<(width-2))<=v<(1<<(width-2)))
            for signs in product((0,1),repeat=6):
                codes=[(-(1<<47),(1<<47)-1)[s] for s in signs[:2]]+[(-x,x-1)[s] for s in signs[2:]]
                row=w.update(codes[:2],codes[2:4],codes[4:],bits)
                for i,v in enumerate(row):self.assertTrue(b['axes'][i]['min']<=v<=b['axes'][i]['max'])

    def test_independent_scale_trace(self):
        for i,case in enumerate(('identity','complex','regularized','tiny_identity','zero_shift','min_imag','random_complex','wide_reciprocal','gram_peak')):
            h,l=channel3(case,53+i);flat=[p for row in h for p in row];t=w.scale_trace(flat,mmse3_fixed.lambda_raw(l))
            self.assertEqual(t['weights'],[p for row in mmse3_fixed.weights(h,l) for p in row])

    def test_independent_elimination_trace(self):
        for n,case in product((2,3,4,5,8),('identity','complex','wide','random_complex','conditioned')):
            h,l=channeln(case,n,104+n);t=w.update_trace([p for row in h for p in row],mmse_n_fixed.lambda_raw(l),n)
            self.assertEqual(t['weights'],[p for row in mmse_n_fixed.weights(h,l) for p in row]);self.assertEqual(len(t['banks']),8)

class TestEvidence(unittest.TestCase):
    """Synthetic rows exercise the validator; these are not measured RTL runs."""
    @classmethod
    def setUpClass(cls):
        import mmse_scale_update_sweep as s
        cls.s=s;d=s.report();d['rtl_verified']=True
        for src in d['records']:
            k,n,c=src['kind'],src['n'],src['case'];spec=s.SPECS[k]
            for l,a,scenario in product(spec['layouts'],(1,0),s.SCENARIOS):
                factor=2 if scenario in ('midreset','outreset') else 1
                d['streams'].append(dict(kind=k,n=n,case=c,layout=l[0],active=a,scenario=scenario,widths=list(l[1:]),
                  outputs=src['outputs'],cycles=500,config_cycles=100 if k=='updates' else 0,
                  banks=[dict(b,count=b['count']*factor) for b in src['banks']]))
            for a,scenario in product((1,0),s.SCENARIOS):
                d['frozen'].append(dict(kind=k,n=n,case=c,active=a,scenario=scenario,old_cycles=500,new_cycles=500,
                  old_outputs=src['outputs'],new_outputs=src['outputs'],old_config_cycles=100 if k=='updates' else 0,new_config_cycles=100 if k=='updates' else 0))
        for k,sp in s.SPECS.items():
            for l,a in product(sp['layouts'],(1,0)):
                d['directed'].append(dict(kind=k,layout=l[0],active=a,checks=5090 if k=='scale' else 536,banks=s.direct_banks(k)))
            for l,a in product(s.invalid(k),(1,0)):d['parameters'].append(dict(kind=k,layout=l[0],active=a,returncode=13))
            for b,t,a in product(('stream','directed'),sp['tags'],(1,0)):d['negative'].append(dict(kind=k,bench=b,tag=t,active=a,returncode=13))
            for n,l in product(sp['sizes'],sp['layouts']):d['lint'].append(dict(kind=k,n=n,layout=l[0],warnings=0))
        cls.complete=d

    def test_complete_and_corrupted_evidence(self):
        s=self.s;s.check_acceptance(self.complete);s.check_acceptance(s.report())
        for section in s.SECTIONS:
            for duplicate in (False,True):
                d=copy.deepcopy(self.complete)
                if duplicate:d[section][-1]=d[section][0]
                else:d[section].pop()
                with self.subTest(section=section,duplicate=duplicate),self.assertRaises(RuntimeError):s.check_acceptance(d)
        for section,key,val in [('streams','cycles',501),('streams','config_cycles',True),('streams','outputs',1),
                ('directed','checks',0),('parameters','returncode',0),('negative','returncode',True),('lint','warnings',1)]:
            d=copy.deepcopy(self.complete);d[section][0][key]=val
            with self.subTest(section=section,key=key),self.assertRaises(RuntimeError):s.check_acceptance(d)
        d=copy.deepcopy(self.complete);d['frozen'][0]['old_outputs']=d['frozen'][0]['new_outputs']=1
        with self.assertRaises(RuntimeError):s.check_acceptance(d)
        d=copy.deepcopy(self.complete);d['streams'][0]['banks'][0]['max']+=1
        with self.assertRaises(RuntimeError):s.check_acceptance(d)
        d=copy.deepcopy(self.complete);d['directed'][0]['banks'][0]['min']=False
        with self.assertRaises(RuntimeError):s.check_acceptance(d)

if __name__=='__main__':unittest.main()
