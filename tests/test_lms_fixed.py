"""Integer LMS/NLMS (lms_fixed) against research_core.run('lms'/'nlms')."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import lms_fixed as l
from research_core import run
from sat_diag import SatTrace


def q15(z):return [(max(-131072,min(131071,int(round(complex(v).real*32768)))),max(-131072,min(131071,int(round(complex(v).imag*32768))))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


class TestLmsFixed(unittest.TestCase):
    def check(self,mode,step,seed=1,taps=np.array([.6+.1j,-.2+.1j,.15]),n=512,eps=.01):
        rng=np.random.default_rng(seed);x=(rng.normal(size=n)+1j*rng.normal(size=n))/np.sqrt(2)
        desired=np.convolve(x,taps)[:n]
        out,weights=l.adapt(q15(x),q15(desired),len(taps),mode,l.parameters(step,eps))
        pred=complex_of([p for p,_ in out]);err=complex_of([e for _,e in out])
        expected=run(mode,[len(taps),step,eps],x,desired)
        self.assertLess(np.mean(abs(err[-128:])**2),.02*np.mean(abs(err[:32])**2))
        self.assertLess(np.max(abs(complex_of(weights).conj()-taps)),.002)
        # Same trajectory as the floating filter up to quantisation.
        self.assertLess(np.max(abs(pred-expected[:n])),.02)
        return err

    def test_lms_model_case(self):self.check('lms',.05)
    def test_nlms_model_case(self):self.check('nlms',.6)
    def test_other_lengths(self):
        rng=np.random.default_rng(3)
        for mode,step in (('lms',.02),('nlms',.3)):
            for taps in (np.array([.9]),(rng.normal(size=8)+1j*rng.normal(size=8))/8):
                with self.subTest(mode=mode,n=len(taps)):self.check(mode,step,seed=5,taps=taps,n=1500)

    def test_rejects(self):
        with self.assertRaises(ValueError):l.parameters(0,.01)
        with self.assertRaises(ValueError):l.parameters(.1,1e-9)

    def test_weight_clamps_with_hand_counts(self):
        for target,sign,rail in [(131071,'pos',131071),(-131072,'neg',-131072)]:
            stats=SatTrace();x=[(131071,0),(0,0)];d=[(target,0),(0,0)]
            out,weights=l.adapt(x,d,2,'lms',l.parameters(1,.01),stats=stats)
            self.assertEqual(out,[((0,0),(target,0)),((0,0),(0,0))])
            self.assertEqual(weights,[(rail,0),(0,0)])
            self.assertEqual(stats.counts,{'update.re':{'pos':int(sign=='pos'),'neg':int(sign=='neg')},
                                         'dump.re':{'pos':int(sign=='pos'),'neg':int(sign=='neg')}})
            self.assertEqual(stats.evaluations,{'pred.re':2,'pred.im':2,'error.re':2,'error.im':2,
                                                'update.re':4,'update.im':4,'dump.re':2,'dump.im':2})

    def test_instrumented_trajectories_and_evaluations(self):
        rng=np.random.default_rng(96)
        for mode in ('lms','nlms'):
            for taps in (1,3,8):
                x=[tuple(map(int,row)) for row in rng.integers(-131072,131072,size=(37,2))]
                d=[tuple(map(int,row)) for row in rng.integers(-131072,131072,size=(37,2))]
                params=l.parameters(.6,.01);stats=SatTrace()
                self.assertEqual(l.adapt(x,d,taps,mode,params),l.adapt(x,d,taps,mode,params,stats=stats))
                for stage in ('pred.re','pred.im','error.re','error.im'):self.assertEqual(stats.evaluations[stage],37)
                for stage in ('update.re','update.im'):self.assertEqual(stats.evaluations[stage],37*taps)
                for stage in ('dump.re','dump.im'):self.assertEqual(stats.evaluations[stage],taps)


if __name__=='__main__':unittest.main()
