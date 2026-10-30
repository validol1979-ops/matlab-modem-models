"""Integer STFT/ISTFT (stft_fixed) against research_core.run('stft'/'istft')."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import stft_fixed as s
from research_core import run


def q15(z):return [(int(round(v.real*32768)),int(round(v.imag*32768))) for v in z]
def complex_of(rows,frac=15):return np.array([re+1j*im for re,im in rows])/(1<<frac)
CASES=((64,16,320),(64,32,200),(32,32,96),(32,8,200),(4,1,23),(256,64,1200))


class TestStftFixed(unittest.TestCase):
    def signal(self,length,seed=1):
        rng=np.random.default_rng(seed)
        return np.clip((rng.normal(size=length)+1j*rng.normal(size=length))/np.sqrt(2),-3.9,3.9)

    def test_analysis_against_research_core(self):
        for n,hop,length in CASES:
            x=self.signal(length);spectra=complex_of(s.analyze(q15(x),n,hop),19)
            expected=run('stft',[n,hop],x)/n
            with self.subTest(n=n,hop=hop):
                self.assertEqual(len(spectra),len(expected))
                # X/n in Q19: the input quantisation (Q15) dominates, a few Q19 LSB of rounding.
                self.assertLess(np.max(abs(spectra-expected)),2/32768)

    def test_reconstruction(self):
        for n,hop,length in CASES:
            x=self.signal(length,seed=2);rows=q15(x)
            frames=1+(length-n)//hop;used=(frames-1)*hop+n
            back=complex_of(s.synthesize(s.analyze(rows,n,hop),n,hop))
            reference=run('istft',[n,hop],run('stft',[n,hop],x))
            with self.subTest(n=n,hop=hop):
                self.assertEqual(len(back),used)
                self.assertLess(np.max(abs(reference-x[:used])),1e-9)
                # Edge samples are divided by tiny window powers (w[0]^2 = 6e-4 at n = 64,
                # 3.8e-5 at n = 256), so their error is larger than inside the signal.
                error=abs(back-x[:used]);edge=n-hop
                self.assertLess(np.max(error),0.005 if n<=64 else 0.06)
                if hop<n:self.assertLess(np.max(error[edge:used-edge]),1.5e-4)
                self.assertLess(np.sqrt(np.mean(error**2)),3e-4 if n<=64 else 3e-3)

    def test_tables(self):
        w=s.window(64);self.assertLess(max(w),1<<17);self.assertGreater(min(w),0)
        r=s.reciprocals(64,16);self.assertEqual(len(r),16);self.assertEqual(len(r[0]),16)
        self.assertEqual(s.recip_frac(64,16),12)
        self.assertEqual(r[5][15],round(4096/2))   # interior: sum of four shifted Hann windows = 2
        for n,hop in ((4,1),(32,8),(64,32),(256,64)):self.assertTrue(all(v<(1<<24) for row in s.reciprocals(n,hop) for v in row))

    def test_rejects(self):
        with self.assertRaises(ValueError):s.analyze([(0,0)]*10,64,16)
        with self.assertRaises(ValueError):s.analyze([(0,0)]*100,64,8)
        with self.assertRaises(ValueError):s.synthesize([(0,0)]*70,64,16)
        with self.assertRaises(ValueError):s.analyze([(0,0)]*2000,1024,256)


class TestStftSaturation(unittest.TestCase):
    def test_symmetric_rails_and_just_outside(self):
        from sat_diag import SatTrace
        c=s.SPECTRUM_LIMIT;values=[(c,-c),(c+1,-c-1),(-c,c),(-c-1,c+1)]
        stats=SatTrace()
        self.assertEqual(s.synthesize(values,4,1,stats=stats),s.synthesize(values,4,1))
        self.assertEqual(stats.counts['stft.spectrum.re'],{'pos':1,'neg':1})
        self.assertEqual(stats.counts['stft.spectrum.im'],{'pos':1,'neg':1})
        self.assertEqual(stats.evaluations,{'stft.spectrum.re':4,'stft.spectrum.im':4,
                                           'stft.output.re':4,'stft.output.im':4})

    def test_arbitrary_and_one_sided_ranges(self):
        from sat_diag import RangeTrace
        stats=RangeTrace()
        self.assertEqual([stats.record_range('gain',v,3277,65536) for v in (3277,65536,3276,65537)],
                         [3277,65536,3277,65536])
        self.assertEqual(stats.counts['gain'],{'pos':1,'neg':1})
        self.assertEqual(stats.evaluations['gain'],4)
        self.assertEqual(stats.record_range('floor',0,1,None),1)
        self.assertEqual(stats.record_range('floor',1<<200,1,None),1<<200)
        self.assertEqual(stats.counts['floor'],{'pos':0,'neg':1})
        with self.assertRaises(ValueError):stats.record_range('bad',0,2,1)


if __name__=='__main__':unittest.main()
