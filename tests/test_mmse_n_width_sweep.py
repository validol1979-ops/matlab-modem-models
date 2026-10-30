"""Exact local endpoint proof, independent arithmetic and evidence rejection."""
import copy
from itertools import product
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'common/python'),str(ROOT/'tools')]
import mmse_n_widths as widths
import mmse_n_fixed as fixed
import mmse_n_width_sweep as sweep


class TestWidths(unittest.TestCase):
    def fits(self,v,bits):
        self.assertGreaterEqual(v,-(1<<(bits-1)));self.assertLess(v,1<<(bits-1))

    def test_all_n_exact_minimal_widths_and_peak_witnesses(self):
        a,b=1<<17,1<<63
        self.assertEqual([(widths.layout(n)['gram']['required_bits'],widths.layout(n)['sum']['required_bits']) for n in range(2,9)],[(38,84),(38,84),(39,85),(39,85),(39,85),(39,85),(40,86)])
        for n in range(2,9):
            bounds=widths.layout(n)
            for field in ('gram','sum','round_add','rounded'):
                d=bounds[field];bits=d['required_bits']
                self.fits(d['minimum'],bits);self.fits(d['maximum'],bits)
                self.assertTrue(d['minimum']<-(1<<(bits-2)) or d['maximum']>=1<<(bits-2))
            self.assertEqual(widths.gram([(-a,-a)]*(n*n),(1<<34)-1,n)[0],bounds['gram']['maximum'])
            self.assertEqual(widths.sums([(-b,-b)]*(n*n),[(-a,-a)]*n,n)[1],bounds['sum']['maximum'])

    def test_local_multiaffine_endpoint_extrema_extend_to_all_n(self):
        # Each row/sample contributes independently. Enumerating the 16 local
        # corners proves extrema; repeating a corner attains N times each one.
        a,b=1<<17,1<<63
        gc=[(ar*br+ai*bi,ar*bi-ai*br) for ar,ai,br,bi in product((-a,a-1),repeat=4)]
        sc=[(wr*xr-wi*xi,wr*xi+wi*xr) for wr,wi in product((-b,b-1),repeat=2) for xr,xi in product((-a,a-1),repeat=2)]
        for n in range(2,9):
            bounds=widths.layout(n)
            for axis,name in enumerate(('real_offdiag','imag_offdiag')):
                self.assertEqual([n*min(v[axis] for v in gc),n*max(v[axis] for v in gc)],bounds['gram'][name])
            for axis,name in enumerate(('real','imag')):
                self.assertEqual([n*min(v[axis] for v in sc),n*max(v[axis] for v in sc)],bounds['sum'][name])
            for ar,ai,br,bi in product((-a,a-1),repeat=4):
                h=[(0,0)]*(n*n)
                for k in range(n):h[n*k]=(ar,ai);h[n*k+1]=(br,bi)
                g=widths.gram_partials(h,(1<<34)-1,n)
                for pair in g:
                    for v in pair:self.fits(v,bounds['gram']['required_bits'])
                self.assertEqual(widths.gram(h,(1<<34)-1,n)[2:4],[n*(ar*br+ai*bi),n*(ar*bi-ai*br)])
            for wr,wi in product((-b,b-1),repeat=2):
                for xr,xi in product((-a,a-1),repeat=2):
                    partial=widths.sum_partials([(wr,wi)]*(n*n),[(xr,xi)]*n,n)
                    for p in partial:
                        for v in p:self.fits(v,bounds['sum']['required_bits'])
                    self.assertEqual(list(partial[-1]),widths.sums([(wr,wi)]*(n*n),[(xr,xi)]*n,n))

    def test_diagonal_zero_and_full_unsigned_lambda(self):
        for n in range(2,9):
            self.assertEqual(widths.gram([(0,0)]*(n*n),0,n),[0]*(2*n*n))
            g=widths.gram([(0,0)]*(n*n),(1<<34)-1,n)
            for row in range(n):
                for col in range(n):self.assertEqual(g[2*(n*row+col):2*(n*row+col)+2],[(1<<34)-1 if row==col else 0,0])

    def test_random_channels_match_unchanged_fixed_model(self):
        rng=random.Random(803984)
        for n in range(2,9):
            for _ in range(4):
                h=[(rng.randrange(-131072,131072),rng.randrange(-131072,131072)) for _ in range(n*n)]
                H=[h[k:k+n] for k in range(0,n*n,n)];lam=rng.randrange(1,1<<34)
                w=[v for row in fixed.weights(H,lam/(1<<30)) for v in row]
                x=[(rng.randrange(-131072,131072),rng.randrange(-131072,131072)) for _ in range(n)]
                raw=widths.sums(w,x,n)
                actual=[(widths.rounded(raw[2*k],True),widths.rounded(raw[2*k+1],True)) for k in range(n)]
                self.assertEqual(actual,fixed.solve(x,H,lam/(1<<30)))
                gram=widths.gram(h,lam,n)
                for row in range(n):
                    for col in range(n):
                        re=sum(H[k][row][0]*H[k][col][0]+H[k][row][1]*H[k][col][1] for k in range(n))+(lam if row==col else 0)
                        im=sum(H[k][row][0]*H[k][col][1]-H[k][row][1]*H[k][col][0] for k in range(n))
                        self.assertEqual(gram[2*(n*row+col):2*(n*row+col)+2],[re,im])

    def test_rounding_and_validation(self):
        self.assertEqual([widths.rounded(v) for v in (-(1<<23)-1,-(1<<23),(1<<23)-1,1<<23)],[-1,0,0,1])
        for rail,delta in product((-131072,131071),(-1,0,1)):
            v=rail*(1<<24)-(1<<23)+delta
            self.assertEqual(widths.rounded(v,True),max(-131072,min(131071,(v+(1<<23))>>24)))
        for n in (1,9,True,3.0):
            with self.assertRaises(ValueError):widths.layout(n)
        for call in (lambda:widths.gram([(0,0)]*4,1<<34,2),lambda:widths.sums([(1<<63,0)]*4,[(0,0)]*2,2)):
            with self.assertRaises(ValueError):call()


class TestEvidence(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model=sweep.report();cls.full=copy.deepcopy(cls.model);cls.full['rtl_verified']=True
        for source,label,active,(scenario,_) in product(cls.model['records'],sweep.LAYOUTS,(1,0),sweep.SCENARIOS):
            cls.full['rtl_equivalence'].append(dict(n=source['n'],case=source['case'],layout=label,active=active,scenario=scenario,outputs=source['outputs'],cycles=500,config_cycles=100,observers_verified=True,widths=sweep.layout(source['n'],label),banks=copy.deepcopy(source['banks'])))
        cls.full['rtl_directed']=[dict(n=n,layout=l,active=a,passed=True,widths=sweep.layout(n,l),**sweep.directed_counts(n)) for n,l,a in product(sweep.SIZES,sweep.LAYOUTS,(1,0))]
        cls.full['rtl_parameters']=[dict(n=n,layout=l,active=a,returncode=13) for n in sweep.SIZES for l,_,_ in sweep.invalid(n) for a in (1,0)]
        cls.full['rtl_negative']=[dict(n=n,bench=b,tag=t,active=a,returncode=13) for n,b,t,a in product(sweep.SIZES,('stream','directed'),sweep.TAGS,(1,0))]
        cls.full['rtl_lint']=[dict(n=n,layout=l,warnings=0) for n,l in product(range(2,9),sweep.LAYOUTS)]

    def reject(self,r):
        with self.assertRaises((RuntimeError,KeyError,TypeError,ValueError)):sweep.check_acceptance(r)

    def test_complete_model_and_observations(self):
        sweep.check_acceptance(self.model);sweep.check_acceptance(self.full)
        self.assertEqual(len(self.full['rtl_equivalence']),400)
        for r in self.model['records']:
            n=r['n'];self.assertEqual([b['count'] for b in r['banks']],[n*n*(n+1)//2]*2+[r['outputs']]*(2*n)+[r['tuples']]*(2*n))

    def test_coverage_and_unverified_claims(self):
        for section in sweep.SECTIONS:
            for duplicate in (False,True):
                r=copy.deepcopy(self.full)
                if duplicate:r[section].append(copy.deepcopy(r[section][0]))
                else:r[section].pop()
                self.reject(r)
            r=copy.deepcopy(self.model);r[section]=[self.full[section][0]];self.reject(r)
        for key in ('bounds','records','scope','rtl_verified'):
            r=copy.deepcopy(self.model);r[key]=None;self.reject(r)

    def test_numeric_raw_types_width_and_cycle_mutations(self):
        for key,value in (('outputs',1),('outputs',float(self.full['rtl_equivalence'][0]['outputs'])),('cycles',501),('cycles',500.0),('config_cycles',101),('observers_verified',False),('widths',[44,83]),('active',True)):
            r=copy.deepcopy(self.full);r['rtl_equivalence'][0][key]=value;self.reject(r)
        for bank in range(len(self.full['rtl_equivalence'][0]['banks'])):
            for key in ('count','min','max'):
                r=copy.deepcopy(self.full);r['rtl_equivalence'][0]['banks'][bank][key]+=1;self.reject(r)
        r=copy.deepcopy(self.full);r['rtl_equivalence'][0]['banks'][1]['min']=0.0;self.reject(r)
        for section,key,value in (('rtl_directed','passed',False),('rtl_directed','sum_checks',0),('rtl_parameters','returncode',0),('rtl_parameters','returncode',1),('rtl_negative','returncode',-11),('rtl_negative','returncode',13.0),('rtl_lint','warnings',False)):
            r=copy.deepcopy(self.full);r[section][0][key]=value;self.reject(r)

    def test_optimized_interpreter_rejected_before_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'result.json';run=subprocess.run([sys.executable,'-O',str(ROOT/'tools/mmse_n_width_sweep.py'),'--output',str(p)],capture_output=True,text=True)
            self.assertNotEqual(run.returncode,0);self.assertIn('without Python optimization',run.stderr);self.assertFalse(p.exists())


if __name__=='__main__':unittest.main()
