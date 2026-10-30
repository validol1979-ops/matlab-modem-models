"""Integer notch and Kalman filters (oset_fixed) against research_core."""
from pathlib import Path
import sys
import unittest
import numpy as np
from scipy import signal as scipy_signal
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import oset_fixed as o
import sat_diag
from research_core import run


def q15(z):return [(int(round(complex(v).real*32768)),int(round(complex(v).imag*32768))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


class TestOsetFixed(unittest.TestCase):
    def test_notch_model_case(self):
        t=np.arange(512);clean=np.exp(2j*np.pi*.07*t);x=clean+2*np.exp(2j*np.pi*.23*t)
        y=complex_of(o.notch(q15(x),o.notch_coefficients(.23,.94)));expected=run('notch',[.23,.94],x)
        # Coefficient quantisation (2^-17) moves the pole a little: about 1e-4 of the output.
        self.assertLess(np.max(abs(y-expected)),2e-3)
        self.assertLess(abs(np.mean(y[200:]*np.exp(-2j*np.pi*.23*t[200:]))),.03)

    def test_notch_random(self):
        rng=np.random.default_rng(8)
        for f0,r in ((0,.5),(.5,.9),(.1,.99),(.37,0)):
            x=np.clip((rng.normal(size=300)+1j*rng.normal(size=300))/4,-1.9,1.9)
            y=complex_of(o.notch(q15(x),o.notch_coefficients(f0,r)))
            c=np.cos(2*np.pi*f0);expected=scipy_signal.lfilter([1,-2*c,1],[1,-2*r*c,r*r],x)
            with self.subTest(f0=f0,r=r):self.assertLess(np.max(abs(y-expected)),4e-3 if r<.95 else 2e-2)

    def test_kalman_model_case(self):
        rng=np.random.default_rng(3);x=np.ones(512)+.5*rng.normal(size=512)
        y=complex_of(o.kalman(q15(x),o.kalman_parameters(.0005,.25,1)));expected=run('kalman',[.0005,.25,1],x)
        self.assertLess(np.max(abs(y-expected)),2e-3)
        self.assertLess(np.mean(abs(y[100:]-1)**2),.2*np.mean(abs(x[100:]-1)**2))

    def test_kalman_gains_converge(self):
        gains=o.kalman_gains(o.kalman_parameters(.0005,.25,1),2000)
        self.assertEqual(len(set(gains[-200:])),1)
        self.assertEqual(o.kalman_gains(o.kalman_parameters(0,.25,0),3),[0,0,0])

    def test_rejects(self):
        with self.assertRaises(ValueError):o.notch_coefficients(.6,.5)
        with self.assertRaises(ValueError):o.kalman_parameters(.1,0,1)


class TestOsetSaturation(unittest.TestCase):
    """stats=None hooks, boundary/no-event/disabled-gain counters and replay of the
    generated-vector counters (sat_diag.SatTrace stages notch.state.*/notch.output.* /
    kalman.output.*)."""
    def setUp(self):
        sys.path.insert(0,str(ROOT/'tools'))
        import oset_cases
        self.cases=oset_cases

    def test_stats_hooks_keep_results_identical(self):
        rng=np.random.default_rng(5)
        x=q15(np.clip((rng.normal(size=64)+1j*rng.normal(size=64))/4,-1.9,1.9))
        c=o.notch_coefficients(.23,.94)
        self.assertEqual(o.notch(x,c),o.notch(x,c,stats=None))
        self.assertEqual(o.notch(x,c),o.notch(x,c,stats=sat_diag.SatTrace()))
        p=o.kalman_parameters(.0005,.25,1)
        self.assertEqual(o.kalman(x,p),o.kalman(x,p,stats=None))
        self.assertEqual(o.kalman(x,p),o.kalman(x,p,stats=sat_diag.SatTrace()))

    def _trace(self,x,coefficients):
        t=sat_diag.SatTrace();o.notch(x,coefficients,stats=t);return t

    def test_notch_boundary_counts_exact(self):
        # raw (0,65536,0): an exact +1 state accumulator (plus the fixed x[k-2] tap).
        # Positive: the first output rnd(Y,5) == +LIMIT18 EXACTLY (evaluated, no event);
        # state overshoots 4 times, 6 clamped outputs.
        pos=[(131071,0)]*5+[(0,0)]*2
        t=self._trace(pos,(0,65536,0))
        self.assertEqual(t.evaluations,{'notch.state.re':7,'notch.state.im':7,
                                        'notch.output.re':7,'notch.output.im':7})
        self.assertEqual(t.counts,{'notch.state.re':{'pos':4,'neg':0},
                                   'notch.output.re':{'pos':6,'neg':0}})
        # Negative: the 3rd pre-clamp sum is EXACTLY -2^24 (the LOW rail: evaluated, not an
        # event - counts 4, not 5); the output rail -131072 is representable, so the 1st
        # output (exact) is not an event and 6 outputs are clamped.
        neg=[(-131072,0)]*5+[(0,0)]*2
        t=self._trace(neg,(0,65536,0))
        self.assertEqual(t.evaluations['notch.state.re'],7)
        self.assertEqual(t.counts,{'notch.state.re':{'pos':0,'neg':4},
                                   'notch.output.re':{'pos':0,'neg':6}})

    def test_notch_no_events_stable_case(self):
        rng=np.random.default_rng(11)
        x=q15(np.clip((rng.normal(size=120)+1j*rng.normal(size=120))/64,-.2,.2))
        t=self._trace(x,o.notch_coefficients(.23,.94))
        self.assertEqual(sum(t.evaluations.values()),4*len(x))
        self.assertEqual(t.total(),0)

    def test_disabled_coefficients_and_zero_gain(self):
        # notch with a1=a2=0: the state recursion is disabled, output is exactly the
        # feed-forward x[k] + x[k-2] (no events at these levels).
        x=[(1000,0),(-2000,0),(3000,0),(0,0)]
        t=sat_diag.SatTrace()
        self.assertEqual([(1000,0),(-2000,0),(4000,0),(-2000,0)],
                         o.notch(x,(0,0,0),stats=t))
        self.assertEqual(t.total(),0);self.assertEqual(sum(t.evaluations.values()),4*len(x))
        # kalman (q=0,p0=0): every gain is 0, V never moves, output 0, no events.
        t=sat_diag.SatTrace()
        self.assertEqual(o.kalman([(131071,131071)]*8,o.kalman_parameters(0,.25,0),stats=t),
                         [(0,0)]*8)
        self.assertEqual(t.total(),0)
        self.assertEqual(t.evaluations['kalman.output.re'],8)

    def test_replay_counters_from_generated_vectors(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            report=self.cases.vectors(Path(tmp),notch=(.23,.94),kalman=(.0005,.25,1),
                                      transactions=2,seed=3)
            def rows(name):
                parts=(Path(tmp)/name).read_text().split('\n')
                n=int(parts[0]);return [tuple(map(int,l.split())) for l in parts[1:1+n]]
            cfg=lambda name:tuple(int(v) for v in (Path(tmp)/name).read_text().split())
            def stream(name):
                data=rows(name);tx=[];cur=[]
                for re,im,last in data:
                    cur.append((re,im))
                    if last:tx.append(cur);cur=[]
                self.assertEqual(cur,[]);return tx
            trace=sat_diag.SatTrace()
            nc=cfg('notch_cfg.txt');kp=cfg('kalman_cfg.txt')
            for tx in stream('notch_in.txt'):o.notch(tx,nc,stats=trace)
            for tx in stream('kalman_in.txt'):o.kalman(tx,kp,stats=trace)
            for name,stages in [('notch_state_expected.txt',self.cases.NOTCH_STATE_STAGES),
                                ('notch_output_expected.txt',self.cases.NOTCH_OUTPUT_STAGES),
                                ('kalman_expected.txt',self.cases.KALMAN_STAGES)]:
                self.assertEqual(rows(name),sat_diag.write_expected(Path(tmp)/('_'+name),trace,stages),name)
            m=report['saturation_markers']
            self.assertEqual(sum(trace.evaluations.get(s,0) for s in self.cases.NOTCH_STATE_STAGES),
                             m['notch_state'][0])
            self.assertEqual(trace.total(),sum(v[1] for v in m.values()))

    def test_stress_raw_config_state_events(self):
        # the labelled stress raw tuple drives BOTH state signs and is consumed identically
        # by the model; expected files and saturation.json exist with matching totals.
        import tempfile,json
        with tempfile.TemporaryDirectory() as tmp:
            report=self.cases.vectors(Path(tmp),transactions=2,seed=35,
                                      notch_raw=self.cases.STRESS_NOTCH_RAW,label='stress')
            c=json.loads((Path(tmp)/'saturation.json').read_text())
            for s in ('notch.state.re','notch.state.im'):
                self.assertGreater(c['stages'][s]['pos'],0,s)
                self.assertGreater(c['stages'][s]['neg'],0,s)
            self.assertTrue(all((Path(tmp)/f).is_file() for f in
                                ('notch_state_expected.txt','notch_output_expected.txt','kalman_expected.txt')))
            self.assertEqual(c['model_only_evidence'],True)
            self.assertNotIn('RTL_verified',c)
            self.assertEqual(tuple(int(v) for v in c['notch_raw']),self.cases.STRESS_NOTCH_RAW)
            self.assertEqual(report['notch'],self.cases.STRESS_NOTCH_RAW)


if __name__=='__main__':unittest.main()
