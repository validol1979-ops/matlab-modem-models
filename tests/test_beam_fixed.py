"""Integer beamformer and Alamouti decoder (beam_fixed) against research_core."""
from pathlib import Path
import sys
import tempfile
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import beam_fixed as b
import beam_cases
from sat_diag import SatTrace,write_expected
from research_core import run


def q15(z):return [(max(-131072,min(131071,int(round(complex(v).real*32768)))),max(-131072,min(131071,int(round(complex(v).imag*32768))))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


class TestBeamFixed(unittest.TestCase):
    def test_beamform_model_case(self):
        M=8;t=np.arange(128);desired=np.exp(.12j*t);interference=3*np.exp(.47j*t)
        steering=np.exp(2j*np.pi*np.arange(M)*.125)
        matrix=desired[:,None]*steering+interference[:,None]*np.ones(M)
        y=complex_of(b.beamform(q15(matrix.ravel()),q15(steering)));expected=run('beamform',[M],matrix.ravel(),steering)
        # The interference peaks at 4 = the Q3.15 limit; the clipped corners give the largest error.
        self.assertLess(np.max(abs(y-expected)),2e-4)
        self.assertLess(np.max(abs(y-desired)),2e-4)

    def test_beamform_random(self):
        rng=np.random.default_rng(1)
        for M,scale in ((1,1),(3,.2),(16,.5),(4,2)):
            a=scale*(rng.normal(size=M)+1j*rng.normal(size=M))/2;x=(rng.normal(size=40*M)+1j*rng.normal(size=40*M))/3
            qa=q15(a);aq=complex_of(qa)
            y=complex_of(b.beamform(q15(x),qa));expected=run('beamform',[M],complex_of(q15(x)),aq)
            with self.subTest(M=M,scale=scale):self.assertLess(np.max(abs(y-expected)),2e-4)

    def test_alamouti_model_case(self):
        rng=np.random.default_rng(4);symbols=(rng.normal(size=128)+1j*rng.normal(size=128))/np.sqrt(2)
        h=np.array([.4+.3j,1-.2j]);s=symbols.reshape(-1,2)
        r=np.c_[h[0]*s[:,0]+h[1]*s[:,1],-h[0]*s[:,1].conj()+h[1]*s[:,0].conj()].ravel()
        y=complex_of(b.alamouti(q15(r),q15(h)));expected=run('alamouti',[],r,h)
        self.assertLess(np.max(abs(y-expected)),2e-4)
        self.assertLess(np.max(abs(y-symbols)),2e-4)

    def test_reciprocal_range(self):
        for e in (1,2,3,1000,(1<<30)*8,(1<<36)-1):
            r,z=b.reciprocal(e);self.assertLess(abs(r*e/2**z-1),2**-22)
        with self.assertRaises(ValueError):b.reciprocal(0)


LIMIT=(1<<17)-1
IDENTITY=[(1<<15,0)]     # single weight 32768: sat18(round(acc*R, Z-15)) reproduces the sample


class TestSaturation(unittest.TestCase):
    """SatTrace semantics at the model's clamp edges (sat18 rails -131072/+131071)."""

    def test_beamform_rails_are_not_events(self):
        # The identity weight reaches the exact +full and -full rails without clamping: zero
        # events although the outputs sit on the rails, one evaluation per field per snapshot.
        x=[(LIMIT,0),(-LIMIT-1,0)]
        trace=SatTrace();y=b.beamform(x,IDENTITY,stats=trace)
        self.assertEqual(y,b.beamform(x,IDENTITY))
        self.assertEqual(y,[(LIMIT,0),(-LIMIT-1,0)])
        self.assertEqual(trace.total(),0)
        self.assertEqual(trace.evaluations,{'beam.output.re':2,'beam.output.im':2})

    def test_beamform_outside_rails_counts(self):
        # weight 1 scales by 32768: the rounded values leave the rails on both sides.
        x=[(LIMIT,0),(-LIMIT-1,0)]
        trace=SatTrace();y=b.beamform(x,[(1,0)],stats=trace)
        self.assertEqual(y,b.beamform(x,[(1,0)]))
        self.assertEqual(y,[(LIMIT,0),(-LIMIT-1,0)])
        self.assertEqual(trace.counts['beam.output.re'],{'pos':1,'neg':1})
        self.assertNotIn('beam.output.im',trace.counts)   # zero-event stages are absent
        self.assertEqual(trace.total(),2)

    def test_alamouti_rails_are_not_events(self):
        # h0=32768, h1=0: y0=r0 and y1=(-r1.re, r1.im) exactly; the rails are reached, not passed.
        h=[(1<<15,0),(0,0)]
        x=[(LIMIT,0),(LIMIT,-LIMIT-1)]
        trace=SatTrace();y=b.alamouti(x,h,stats=trace)
        self.assertEqual(y,b.alamouti(x,h))
        self.assertEqual(y,[(LIMIT,0),(-LIMIT,-LIMIT-1)])
        self.assertEqual(trace.total(),0)
        self.assertEqual(trace.evaluations,{'alamouti.y0.re':1,'alamouti.y0.im':1,
                                            'alamouti.y1.re':1,'alamouti.y1.im':1})

    def test_alamouti_outside_rails_counts(self):
        h=[(1,0),(0,1)]
        # y1re = ai - br = 2L+2 (positive event), y1im = bi - ar = -2L-2 (negative event),
        # while y0 = (ar+bi, ai+br) = (-1,-1) stays in range: not every field saturates.
        x=[(LIMIT,LIMIT),(-LIMIT-1,-LIMIT-1)]
        trace=SatTrace();y=b.alamouti(x,h,stats=trace)
        self.assertEqual(y,b.alamouti(x,h))
        self.assertEqual(trace.counts['alamouti.y1.re'],{'pos':1,'neg':0})
        self.assertEqual(trace.counts['alamouti.y1.im'],{'pos':0,'neg':1})
        self.assertEqual(set(trace.counts),{'alamouti.y1.re','alamouti.y1.im'})
        self.assertEqual(trace.total(),2)
        self.assertEqual(trace.evaluations,{'alamouti.y0.re':1,'alamouti.y0.im':1,
                                            'alamouti.y1.re':1,'alamouti.y1.im':1})

    def test_expected_file_rows(self):
        trace=SatTrace();b.beamform([(LIMIT,0),(-LIMIT-1,0)],[(1,0)],stats=trace)
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'beam_expected.txt'
            rows=write_expected(path,trace,['beam.output.re','beam.output.im'])
            self.assertEqual(rows,[(2,1,1),(2,0,0)])
            self.assertEqual(path.read_text().splitlines(),['2','2 1 1','2 0 0'])

    def test_vectors_streamed_counts_and_replay(self):
        # evaluations = one per output field of the streamed transactions only (the hypothetical
        # corner probes never reach a stats object); regeneration with the same seed is byte-identical.
        with tempfile.TemporaryDirectory() as tmp:
            first=Path(tmp)/'a';second=Path(tmp)/'b'
            report=beam_cases.vectors(first,3,'random',transactions=1,seed=77)
            beam_cases.vectors(second,3,'random',transactions=1,seed=77)
            self.assertEqual(report['bf_evaluations'],2*report['bf_outputs'])
            self.assertEqual(report['al_evaluations'],2*report['al_outputs'])
            for name in ('bf_cfg.txt','bf_in.txt','bf_out.txt','al_cfg.txt','al_in.txt','al_out.txt',
                         'beam_expected.txt','alamouti_expected.txt','saturation.json'):
                self.assertEqual((first/name).read_bytes(),(second/name).read_bytes(),name)
            self.assertIn('model_only_evidence',(first/'saturation.json').read_text())
            self.assertNotIn('rtl_verified',(first/'saturation.json').read_text())
            bf=[sum(row[1:]) for row in [report['bf_expected'][0],report['bf_expected'][1]]]
            self.assertEqual(sum(bf),report['bf_events'])


if __name__=='__main__':unittest.main()
