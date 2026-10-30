"""Integer polyphase bank (pfb_fixed) against research_core.run('pfb'/'wola')."""
from pathlib import Path
import sys
import unittest
import numpy as np
from scipy import signal as scipy_signal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import pfb_fixed as p
from research_core import run


def q15(z):return [(int(round(v.real*32768)),int(round(v.imag*32768))) for v in z]
def complex_of(rows,frac=19):return np.array([re+1j*im for re,im in rows])/(1<<frac)


class TestPfbFixed(unittest.TestCase):
    def test_research_cases(self):
        # The model.json case: M = 4, 33 firwin taps, a two-tone signal, D = 4 and 3.
        M=4;h=scipy_signal.firwin(33,.20);t=np.arange(256);x=np.exp(2j*np.pi*t/M)+.4*np.exp(-2j*np.pi*t/M)
        taps=p.quantize_taps(h)
        for op in ('pfb','wola'):
            for D in (4,3):
                y=complex_of(p.analyze(q15(x),taps,M,D))*M;expected=run(op,[M,D],x,h)
                with self.subTest(op=op,D=D):
                    self.assertEqual(len(y),len(expected))
                    # Tap quantisation (2^-18 per tap) dominates: a few 1e-4 of the unit tones.
                    self.assertLess(np.max(abs(y-expected)),2e-3)
                    power=np.mean(abs(y.reshape(-1,M)[12:])**2,axis=0);self.assertGreater(power[3],20*power[0])

    def test_random(self):
        rng=np.random.default_rng(4)
        for M,D,T,L in ((8,8,40,200),(8,5,7,120),(16,16,64,300),(4,1,3,30),(64,32,129,500)):
            h=rng.uniform(-.6,.6,T)/np.sqrt(T);x=np.clip((rng.normal(size=L)+1j*rng.normal(size=L))/np.sqrt(2),-3.9,3.9)
            taps=p.quantize_taps(h);y=complex_of(p.analyze(q15(x),taps,M,D))*M
            expected=run('pfb',[M,D],x,np.array(taps)/2**17)
            with self.subTest(M=M,D=D,T=T):
                self.assertEqual(len(y),M*((L+D-1)//D))
                self.assertLess(np.max(abs(y-expected))/M,4/32768)

    def test_rejects(self):
        with self.assertRaises(ValueError):p.analyze([(0,0)]*8,[1],6,2)
        with self.assertRaises(ValueError):p.analyze([(0,0)]*8,[1],4,5)
        with self.assertRaises(ValueError):p.quantize_taps([1.0])


class TestPfbSaturation(unittest.TestCase):
    def test_second_tap_in_phase_causes_clamp(self):
        from sat_diag import SatTrace
        stats=SatTrace();x=[(131071,-131072)]*5;taps=[131071]*8
        self.assertEqual(p.analyze(x,taps,4,4,stats=stats),p.analyze(x,taps,4,4))
        self.assertEqual(stats.evaluations,{'phase.re':8,'phase.im':8})
        self.assertEqual(stats.counts,{'phase.re':{'pos':1,'neg':0},'phase.im':{'pos':0,'neg':1}})

    def test_all_taps_stress_counts(self):
        from sat_diag import SatTrace
        stats=SatTrace()
        for value in ((131071,-131072),(-131072,131071)):
            p.analyze([value]*64,[131071]*16,4,4,stats=stats)
        self.assertEqual(stats.evaluations,{'phase.re':128,'phase.im':128})
        self.assertEqual(stats.counts,{'phase.re':{'pos':57,'neg':57},'phase.im':{'pos':57,'neg':57}})


class TestPfbFftSaturation(unittest.TestCase):
    # optional fft_stats: the embedded FFT clamps are counted without changing any output, and
    # each active forward field is evaluated exactly frames*M/2 times (inverse rows stay zero).
    def test_fft_stats_same_output_and_exact_formula(self):
        from sat_diag import SatStats,SatTrace
        taps=[131071]*16;x=[(131071,-131072)]*64+[(-131072,131071)]*64   # phase clamps, M=4
        plain=p.analyze(x,taps,4,4)
        self.assertEqual(plain,p.analyze(x,taps,4,4,fft_stats=SatStats()))
        self.assertEqual(plain,p.analyze(x,taps,4,4,stats=SatTrace(),fft_stats=SatTrace()))
        # small case: M=4 (LOG2M=2), D=4, L=12 -> frames = ceil(12/4) = 3 evaluations/field = 3*4/2 = 6
        small=[(1000,-2000)]*12
        st=SatTrace()
        self.assertEqual(p.analyze(small,taps,4,4,fft_stats=st),p.analyze(small,taps,4,4))
        self.assertEqual(st.evaluations,{f'forward.s{g}.{b}.{c}':6
                                         for g in range(2) for b in ('sum','diff') for c in ('re','im')})
        self.assertEqual(st.total(),0)   # small values never reach the 24-bit FFT rails
        # stats alone still sees only the phase clamps; fft_stats alone only forward FFT stages.
        ph=SatTrace();p.analyze(x,taps,4,4,stats=ph)
        self.assertEqual(set(ph.evaluations),{'phase.re','phase.im'})
        self.assertEqual({k for k in st.evaluations if not k.startswith('forward.')},set())

    def test_cases_expected_file_json_and_determinism(self):
        import json,tempfile
        sys.path.insert(0,str(ROOT/'tools'))
        import pfb_cases,fft_cases
        from sat_diag import SatStats
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'c'
            rep=pfb_cases.vectors(folder,2,4,16,transactions=2,seed=5)
            again=pfb_cases.vectors(Path(d)/'again',2,4,16,transactions=2,seed=5)
            # vectors preserved: identical in/out files and identical phase statistics and JSON
            for name in ('cfg.txt','in.txt','out.txt','pfb_phase_expected.txt','saturation.json'):
                self.assertEqual((folder/name).read_text(),(Path(d)/'again'/name).read_text())
            self.assertEqual(rep['saturation'],again['saturation'])
            self.assertEqual(rep['fft_saturation'],again['fft_saturation'])
            # row layout of tools/fft_cases.py: header LOG2M, 8*LOG2M rows 'evaluations pos neg'
            log2m,rows=fft_cases.read_saturation_expected(folder/pfb_cases.FFT_EXPECTED)
            self.assertEqual(log2m,2);self.assertEqual(len(rows),16)
            frames=rep['bins']//rep['m']   # frames = sum ceil(L/D)
            self.assertEqual([r[0] for r in rows[:8]],[frames*2]*8)      # forward: frames*M/2 = frames*2
            self.assertEqual(rows[8:],[(0,0,0)]*8)                       # inactive inverse rows zero
            self.assertEqual(rep['fft_saturation_expected']['rows'],[list(r) for r in rows])
            # replay exactly the scored transactions (in.txt + cfg.txt) and match the JSON
            words=[int(t) for t in (folder/'cfg.txt').read_text().split()]
            taps,d=words[1:-1],words[-1]   # cfg.txt: count header, taps, d
            stats=SatStats();frame=[];replay=[]
            for line in (folder/'in.txt').read_text().splitlines()[1:]:
                re_,im,tf=(int(v) for v in line.split());frame.append((re_,im))
                if tf:
                    got=p.analyze(frame,taps,4,int(d),fft_stats=stats)
                    replay.extend((re_o,im_o,int(k==len(got)-1)) for k,(re_o,im_o) in enumerate(got))
                    frame=[]
            self.assertEqual(replay,[tuple(map(int,l.split()))
                                     for l in (folder/'out.txt').read_text().splitlines()[1:]])
            self.assertEqual(stats.to_dict()['stages'],rep['fft_saturation']['stages'])
            js=json.loads((folder/pfb_cases.FFT_JSON).read_text())
            self.assertTrue(js['model_only_evidence'])
            self.assertEqual(js['stages'],rep['fft_saturation']['stages'])
            self.assertEqual(js['formula'],{f'forward.s{g}.{b}.{c}':frames*2
                                            for g in range(2) for b in ('sum','diff') for c in ('re','im')})
            self.assertEqual(js['frames'],frames);self.assertEqual(js['formula'],rep['fft_saturation_formula'])


if __name__=='__main__':unittest.main()
