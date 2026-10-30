"""Integer OM-LSA (omlsa_fixed) against research_core.run('omlsa')."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import omlsa_fixed as o
from research_core import run


def q15(z):return [(max(-131072,min(131071,int(round(complex(v).real*32768)))),max(-131072,min(131071,int(round(complex(v).imag*32768))))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


class TestOmlsaFixed(unittest.TestCase):
    def test_model_case(self):
        rng=np.random.default_rng(1)
        n=32;hop=8;t=np.arange(640);clean=np.zeros(640);clean[160:]=np.sin(2*np.pi*.125*t[160:]);x=clean+.32*rng.normal(size=640)
        y=complex_of(o.enhance(q15(x),n,hop,12,.92));expected=run('omlsa',[n,hop,12,.92],x)
        before=np.mean(abs(x[224:]-clean[224:])**2);after=np.mean(abs(y[224:]-clean[224:])**2)
        self.assertEqual(len(y),640)
        self.assertLess(after,before)
        self.assertLess(np.max(abs(y)),1.6)
        # Close to the floating enhancer: same improvement within a fraction of a dB.
        ref=np.mean(abs(expected[224:]-clean[224:])**2)
        print('improvement fixed %.2f dB, float %.2f dB, max |y - ref| %.4f'%(10*np.log10(before/after),10*np.log10(before/ref),np.max(abs(y-expected))))
        self.assertLess(abs(10*np.log10(after/ref)),.5)
        self.assertLess(np.sqrt(np.mean(abs(y-expected)**2)),.02)


    def test_other_parameters(self):
        rng=np.random.default_rng(5)
        for n,hop,nn,alpha,complex_input in ((64,16,6,.9,False),(32,8,4,.98,True),(16,4,10,.8,False)):
            t=np.arange(900);clean=np.zeros(900,complex);clean[300:]=np.exp(2j*np.pi*.07*t[300:]) if complex_input else np.cos(2*np.pi*.07*t[300:])
            x=clean+.3*(rng.normal(size=900)+(1j*rng.normal(size=900) if complex_input else 0))
            y=complex_of(o.enhance(q15(x),n,hop,nn,alpha));expected=run('omlsa',[n,hop,nn,alpha],x)
            with self.subTest(n=n,hop=hop):
                self.assertEqual(len(y),900)
                self.assertLess(np.sqrt(np.mean(abs(y-expected)**2)),.01)

    def test_rejects(self):
        with self.assertRaises(ValueError):o.enhance([(0,0)]*20,32,8,12,.9)


class TestOmlsaSaturation(unittest.TestCase):
    def test_silence_floors_and_complete_istft_length(self):
        from sat_diag import RangeTrace
        x=[(0,0)]*17;stats=RangeTrace()
        self.assertEqual(o.enhance(x,16,4,1,.9,stats=stats),x)
        self.assertEqual(stats.evaluations['omlsa.noise'],16)
        self.assertEqual(stats.counts['omlsa.noise'],{'pos':0,'neg':16})
        self.assertEqual(stats.evaluations['omlsa.gamma'],144)
        self.assertNotIn('omlsa.gamma',stats.counts)
        self.assertEqual(stats.counts['omlsa.excess'],{'pos':0,'neg':144})
        self.assertEqual(stats.evaluations['omlsa_istft.output.re'],48)
        self.assertEqual(stats.evaluations['omlsa_istft.spectrum.re'],144)

    def test_quiet_prefix_followed_by_burst(self):
        from sat_diag import RangeTrace
        x=[(0,0)]*48+[(131071,-131072)]*64+[(-131072,131071)]*64
        stats=RangeTrace()
        self.assertEqual(o.enhance(x,16,4,1,.9,stats=stats),o.enhance(x,16,4,1,.9))
        self.assertGreater(stats.counts['omlsa.gamma']['pos'],0)
        self.assertEqual(stats.evaluations['omlsa.gamma'],49*16)
        self.assertEqual(stats.evaluations['omlsa_istft.output.re'],208)


if __name__=='__main__':unittest.main()
