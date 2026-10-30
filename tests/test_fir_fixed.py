"""Integer FIR (fir_fixed) against research_core.run('fir'/'wsinc'), plus saturation
instrumentation checks (sat_diag; an output equal to a rail is NOT an event)."""
from pathlib import Path
import sys
import json
import tempfile
import unittest
import numpy as np
from scipy import signal as scipy_signal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import fir_fixed as r
import fir_cases
import sat_diag
from research_core import run


def q15(z):return [(int(round(complex(v).real*32768)),int(round(complex(v).imag*32768))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


class TestFirFixed(unittest.TestCase):
    def test_model_cases(self):
        rng=np.random.default_rng(6)
        h=scipy_signal.firwin(41,.24,window='hamming',scale=True)
        cases=[([1,0,0],[.25,.5,.25]),([1,0,0],h),((rng.normal(size=200)+1j*rng.normal(size=200))/3,h),
               (np.exp(.3j*np.arange(150))+.5*np.exp(2.4j*np.arange(150)),h),
               ((rng.normal(size=60)+1j*rng.normal(size=60))/3,(rng.normal(size=9)+1j*rng.normal(size=9))/6)]
        for k,(x,a) in enumerate(cases):
            y=complex_of(r.filter(q15(x),r.quantize_taps(a)));expected=run('fir',[],x,a)
            with self.subTest(case=k):
                self.assertEqual(len(y),len(expected))
                # Input (2^-16) and tap (2^-18 * sum |a|) quantisation plus the output rounding.
                self.assertLess(np.max(abs(y-expected)),1e-4)

    def test_wsinc(self):
        taps=r.wsinc_taps(41,.12);expected=run('wsinc',[41,.12],[0])
        self.assertLess(max(abs(a-b) for a,b in zip(taps,expected.real)),1e-12)
        q=r.quantize_taps(taps);self.assertEqual(len(q),41)
        self.assertLess(abs(sum(v for v,_ in q)-(1<<17)),41)

    def test_impulse_gives_taps(self):
        a=[.25,.5,.25];self.assertEqual(r.filter([(32768,0),(0,0),(0,0)],r.quantize_taps(a)),[(8192,0),(16384,0),(8192,0),(0,0),(0,0)])

    def test_rejects(self):
        with self.assertRaises(ValueError):r.quantize_taps([1.0])
        with self.assertRaises(ValueError):r.filter([],[(1,0)])
        with self.assertRaises(ValueError):r.wsinc_taps(1,.1)


class TestSaturation(unittest.TestCase):
    """Unit-gain tap 2^17 in Q17 makes the pre-clamp rounded value equal to the input."""
    UNIT=[(1<<17,0)]

    def test_sat_diag_clamp_matches_models(self):
        import fft_fixed as fx
        st=sat_diag.SatStats()
        for v in range(-(1<<17)-3,(1<<17)+4):
            self.assertEqual(st.record('t',v,(1<<17)-1),r.sat18(v))
            self.assertEqual(st.record('s',v,(1<<17)-1,clamp='sym'),fx.sat(v,18))
        self.assertEqual(st.counts['t'],{'pos':4,'neg':3})
        # The symmetric clamp changes -LIMIT-1 too, so it records one extra event.
        self.assertEqual(st.counts['s'],{'pos':4,'neg':4})

    def test_exact_rails_are_not_events(self):
        for v in ((1<<17)-1,-(1<<17)):
            for comp in (0,1):
                z=[(v,0)] if comp==0 else [(0,v)]
                st=sat_diag.SatStats()
                self.assertEqual(r.filter(z,self.UNIT,stats=st),r.filter(z,self.UNIT))
                self.assertEqual(st.total(),0)

    def test_out_of_range_counts_per_component(self):
        for v,sign in (((1<<17),'pos'),(-(1<<17)-1,'neg')):
            st=sat_diag.SatStats()
            out=r.filter([(v,0)],self.UNIT,stats=st)
            self.assertEqual(out,[((1<<17)-1 if v>0 else -(1<<17),0)])
            self.assertEqual(st.counts['output.re'],{'pos':int(sign=='pos'),'neg':int(sign=='neg')})
            self.assertNotIn('output.im',st.counts)
        st=sat_diag.SatStats()
        r.filter([(0,1<<17)],self.UNIT,stats=st)
        self.assertEqual(st.counts,{'output.im':{'pos':1,'neg':0}})

    def test_instrumented_equality(self):
        rng=np.random.default_rng(11)
        h=r.quantize_taps(r.wsinc_taps(41,.12))
        x=[tuple(map(int,t)) for t in rng.integers(-(1<<17),(1<<17)+1,(64,2))]
        for scale in (1,8):  # scale 8: deterministic overload
            taps=[(re*scale,im*scale) for re,im in h]
            st=sat_diag.SatStats()
            self.assertEqual(r.filter(x,taps,stats=st),r.filter(x,taps))
            self.assertGreater(st.total(),0 if scale==8 else -1)

    def test_vectors_saturation_json(self):
        with tempfile.TemporaryDirectory() as d:
            d=Path(d)
            reports={}
            for kind in ('harger','wsinc'):
                folder=d/kind
                reports[kind]=[fir_cases.vectors(folder,kind,transactions=4,seed=31)]
                if kind=='wsinc':  # deterministic regeneration must give identical counts
                    reports[kind].append(fir_cases.vectors(d/'wsinc_again',kind,transactions=4,seed=31))
                self.assertEqual(reports[kind][0]['saturation'],reports[kind][-1]['saturation'])
                js=json.loads((folder/'saturation.json').read_text())
                self.assertEqual(js['stages'],reports[kind][0]['saturation']['stages'])
                self.assertEqual(js['total'],reports[kind][0]['saturation']['total'])
                self.assertTrue(js['model_only_evidence'])
                # Replay the exact vectors the testbench consumes; outputs and counts must match.
                taps=[tuple(map(int,line.split())) for line in (folder/'cfg.txt').read_text().splitlines()[1:] if line.strip()]
                rows=[tuple(map(int,l.split())) for l in (folder/'in.txt').read_text().splitlines()[1:] if l.strip()]
                outs=[tuple(map(int,l.split())) for l in (folder/'out.txt').read_text().splitlines()[1:] if l.strip()]
                st=sat_diag.SatStats(); replay=[]; wave=[]
                for re,im,last in rows:
                    wave.append((re,im))
                    if last:
                        got=r.filter(wave,taps,stats=st)
                        self.assertEqual(len(got),len(wave)+len(taps)-1)
                        replay.extend((re_,im_,int(k==len(got)-1)) for k,(re_,im_) in enumerate(got))
                        wave=[]
                self.assertEqual(replay,outs)
                self.assertEqual(st.to_dict()['stages'],js['stages'])
            # harger reaches both actual rails exactly and must report ZERO events.
            flat=[int(t) for l in (d/'harger/out.txt').read_text().splitlines()[1:] if l.strip() for t in l.split()[:2]]
            self.assertEqual(max(flat),(1<<17)-1);self.assertEqual(min(flat),-(1<<17))
            self.assertEqual(reports['harger'][0]['saturation']['total'],0)
            # wsinc corners genuinely clip: exact expected counts, both signs, re only.
            self.assertEqual(reports['wsinc'][0]['saturation'],{'stages':{'output.re':{'pos':3,'neg':3}},'total':6})


if __name__=='__main__':unittest.main()
