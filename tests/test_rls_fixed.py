"""Integer RLS (rls_fixed) against research_core.run('rls')."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import rls_fixed as r
from research_core import run
from sat_diag import SatTrace


def q15(z):return [(max(-131072,min(131071,int(round(complex(v).real*32768)))),max(-131072,min(131071,int(round(complex(v).imag*32768))))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


class TestRlsFixed(unittest.TestCase):
    def check(self,lam,taps,n=512,seed=1,eps=.01):
        rng=np.random.default_rng(seed);x=(rng.normal(size=n)+1j*rng.normal(size=n))/np.sqrt(2)
        desired=np.convolve(x,taps)[:n]
        out,weights=r.adapt(q15(x),q15(desired),len(taps),r.parameters(lam,eps))
        err=complex_of([e for _,e in out]);pred=complex_of([p for p,_ in out])
        expected=run('rls',[len(taps),lam,eps],x,desired)
        self.assertLess(np.mean(abs(err[-128:])**2),.02*np.mean(abs(err[:32])**2))
        self.assertLess(np.max(abs(complex_of(weights).conj()-taps)),.002)
        self.assertLess(np.max(abs(pred[20:]-expected[20:n])),.01)

    def test_model_case(self):self.check(.995,np.array([.6+.1j,-.2+.1j,.15]))
    def test_other(self):
        rng=np.random.default_rng(4)
        for lam,taps in ((.99,np.array([.9])),(1.,(rng.normal(size=6)+1j*rng.normal(size=6))/6),(.98,np.array([.3,-.2j,.1,.05]))):
            with self.subTest(lam=lam,n=len(taps)):self.check(lam,taps,n=1500,seed=5)

    def test_rejects(self):
        with self.assertRaises(ValueError):r.parameters(1.2,.01)

    def test_weight_clamps_both_components(self):
        for desired,signs,weight in [(131071,('pos','neg'),(131071,-131072)),
                                    (-131072,('neg','pos'),(-131072,131071))]:
            stats=SatTrace();x=[(1,0)]*8;d=[(desired,desired)]*8;params=r.parameters(1,1/16384)
            actual=r.adapt(x,d,1,params,stats=stats)
            self.assertEqual(actual,r.adapt(x,d,1,params))
            self.assertEqual(actual[1],[weight])
            self.assertEqual(actual[0][0],((0,0),(desired,desired)))
            for component,sign in zip(('re','im'),signs):
                self.assertEqual(stats.counts['update.'+component],{'pos':4*int(sign=='pos'),'neg':4*int(sign=='neg')})
                self.assertEqual(stats.counts['dump.'+component],{'pos':int(sign=='pos'),'neg':int(sign=='neg')})
            for stage in ('pred.re','pred.im','error.re','error.im','u.re','u.im','q',
                          'gain.re','gain.im','update.re','update.im','pt.re','pt.im','P.re'):
                self.assertEqual(stats.evaluations[stage],8)
            self.assertEqual(stats.evaluations.get('P.im',0),0)

    def test_covariance_clamp_with_zero_data(self):
        # P0=2^42 and lambda=1/2: both diagonals clamp at every update, starting at step one.
        stats=SatTrace();actual=r.adapt([(0,0)]*4,[(0,0)]*4,2,r.parameters(.5,1/16384),stats=stats)
        self.assertEqual(actual,([((0,0),(0,0))]*4,[(0,0)]*2))
        self.assertEqual(stats.counts,{'P.re':{'pos':8,'neg':0}})
        self.assertEqual(stats.evaluations['P.re'],12)
        self.assertEqual(stats.evaluations['P.im'],4)
        self.assertEqual(stats.evaluations['pt.re'],12)
        self.assertEqual(stats.evaluations['pt.im'],12)

    def test_triangle_evaluations_and_same_trajectory(self):
        params=r.parameters(.995,.01)
        for taps in (1,3,8):
            x=[(1000+k*10,500-k*9) for k in range(17)];d=[(700-k*3,100+k*2) for k in range(17)]
            stats=SatTrace()
            self.assertEqual(r.adapt(x,d,taps,params,stats=stats),r.adapt(x,d,taps,params))
            upper=17*taps*(taps+1)//2;strict=17*taps*(taps-1)//2
            expected={'pred.re':17,'pred.im':17,'error.re':17,'error.im':17,'q':17,
                      'u.re':17*taps,'u.im':17*taps,'gain.re':17*taps,'gain.im':17*taps,
                      'update.re':17*taps,'update.im':17*taps,'pt.re':upper,'pt.im':upper,
                      'P.re':upper,'P.im':strict,'dump.re':taps,'dump.im':taps}
            self.assertEqual({k:stats.evaluations.get(k,0) for k in expected},expected)


if __name__=='__main__':unittest.main()
