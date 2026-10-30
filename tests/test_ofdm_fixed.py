"""Integer OFDM (ofdm_fixed) against research_core.run('ofdm_tx'/'ofdm_rx')."""
from pathlib import Path
import json
import sys
import tempfile
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import ofdm_fixed as o
from sat_diag import SatTrace,RangeTrace
from research_core import run


def q15(z):return [(int(round(v.real*32768)),int(round(v.imag*32768))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


def constellation(order):
    if order==2:return np.array([-1,1],complex)
    side=int(np.sqrt(order));levels=np.arange(-(side-1),side,2);c=(levels[:,None]+1j*levels).ravel()
    return c/np.sqrt(np.mean(abs(c)**2))


class TestOfdmFixed(unittest.TestCase):
    def test_against_research_core(self):
        rng=np.random.default_rng(3)
        for n,cp in ((32,8),(64,16),(4,0),(1024,64)):
            for order in (2,4,16,64):
                const=constellation(order);labels=rng.integers(0,order,4*n);symbols=const[labels]
                wave=o.transmit(q15(symbols),n,cp);expected=run('ofdm_tx',[n,cp],symbols)
                # Rounding noise grows with n (about -48 dB of a unit symbol at n = 1024).
                tolerance=2e-3 if n<=64 else 6e-3
                with self.subTest(n=n,order=order):
                    self.assertEqual(len(wave),len(expected))
                    self.assertLess(np.max(abs(complex_of(wave)-expected)),tolerance)
                    received=expected+.003*(rng.normal(size=len(expected))+1j*rng.normal(size=len(expected)))/np.sqrt(2)
                    y=complex_of(o.receive(q15(received),n,cp));reference=run('ofdm_rx',[n,cp],received)
                    self.assertLess(np.max(abs(y-reference)),tolerance)
                    self.assertTrue(np.all(np.argmin(abs(y[:,None]-const)**2,axis=1)==labels))

    def test_round_trip_and_prefix(self):
        rng=np.random.default_rng(4);rows=[(int(a),int(b)) for a,b in rng.integers(-30000,30000,(64,2))]
        wave=o.transmit(rows,32,8)
        self.assertEqual(wave[0:8],wave[32:40]);self.assertEqual(wave[40:48],wave[72:80])
        back=o.receive(wave,32,8)
        self.assertLess(max(abs(a-b) for x,y in zip(back,rows) for a,b in zip(x,y)),40)

    def test_rejects(self):
        with self.assertRaises(ValueError):o.transmit([(0,0)]*30,32,8)
        with self.assertRaises(ValueError):o.receive([(0,0)]*32,32,8)
        with self.assertRaises(ValueError):o.transmit([(0,0)]*12,12,0)


class TestOfdmSaturation(unittest.TestCase):
    def test_prefix_does_not_duplicate_clamp_events(self):
        x=[(131071,-131072),(-131072,131071)]*2
        for cp in (0,2,4):
            stats=SatTrace();wave=o.transmit(x,4,cp,stats=stats)
            self.assertEqual(wave,o.transmit(x,4,cp))
            self.assertEqual(wave[-4:],[(0,0),(0,0),(131071,-131072),(0,0)])
            self.assertEqual(stats.evaluations,{'tx.re':4,'tx.im':4})
            self.assertEqual(stats.counts,{'tx.re':{'pos':1,'neg':0},'tx.im':{'pos':0,'neg':1}})
            stats=SatTrace();samples=x[-cp:]+x if cp else x
            self.assertEqual(o.receive(samples,4,cp,stats=stats),o.receive(samples,4,cp))
            self.assertEqual(stats.evaluations,{'rx.re':4,'rx.im':4})
            self.assertEqual(stats.counts,{'rx.re':{'pos':1,'neg':0},'rx.im':{'pos':0,'neg':1}})


def fft_stage_expectation(log2n,frames,direction):
    """Independent per-field evaluation counts: N/2 butterflies per stage and frame, so
    frames*N/2 per 'direction.s<g>.<sum|diff>.<re|im>'; the inverse also evaluates its
    final conjugation once per output sample (frames*N)."""
    n=1<<log2n;per=frames*n//2
    stages={f'{direction}.s{g}.{b}.{c}':per for g in range(log2n) for b in ('sum','diff') for c in ('re','im')}
    if direction=='inverse':stages['inverse.conj.im']=frames*n
    return stages


class TestOfdmEmbeddedFftStats(unittest.TestCase):
    # fft_stats is forwarded ONLY to the embedded fft_fixed.inverse (transmit) /
    # fft_fixed.forward (receive): numerical output stays byte-identical and the trace
    # records exactly the active stage evaluations, nothing else.
    def test_tx_stats_keep_output_and_inverse_stage_counts(self):
        rng=np.random.default_rng(11)
        for n,cp,frames in ((16,4,1),(32,0,2),(8,2,3)):
            syms=[(int(a),int(b)) for a,b in rng.integers(-30000,30000,(frames*n,2))]
            base=o.transmit(syms,n,cp)
            outer=SatTrace();fft_only=SatTrace();both=SatTrace()
            self.assertEqual(o.transmit(syms,n,cp,fft_stats=fft_only),base)
            self.assertEqual(o.transmit(syms,n,cp,stats=outer,fft_stats=both),base)
            expected=fft_stage_expectation(n.bit_length()-1,frames,'inverse')
            self.assertEqual(fft_only.evaluations,expected)
            self.assertEqual(both.evaluations,expected)
            self.assertEqual(set(outer.evaluations),{'tx.re','tx.im'})
            self.assertEqual(outer.evaluations,{'tx.re':frames*n,'tx.im':frames*n})
            self.assertFalse(any(k.startswith('forward') for k in both.counts|both.evaluations))

    def test_rx_stats_keep_output_and_forward_stage_counts(self):
        rng=np.random.default_rng(12)
        for n,cp,frames in ((16,4,1),(32,0,2),(8,2,3)):
            wave=o.transmit([(int(a),int(b)) for a,b in rng.integers(-30000,30000,(frames*n,2))],n,cp)
            base=o.receive(wave,n,cp)
            outer=SatTrace();fft_only=SatTrace();both=SatTrace()
            self.assertEqual(o.receive(wave,n,cp,fft_stats=fft_only),base)
            self.assertEqual(o.receive(wave,n,cp,stats=outer,fft_stats=both),base)
            expected=fft_stage_expectation(n.bit_length()-1,frames,'forward')
            self.assertEqual(fft_only.evaluations,expected)
            self.assertEqual(both.evaluations,expected)
            self.assertEqual(set(outer.evaluations),{'rx.re','rx.im'})
            self.assertEqual(outer.evaluations,{'rx.re':frames*n,'rx.im':frames*n})
            self.assertFalse(any(k.startswith('inverse') for k in both.counts|both.evaluations))

    def test_vectors_write_fft_expected_files(self):
        import fft_cases
        from ofdm_cases import vectors
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'n32_cp8'
            rep=vectors(folder,5,8,frames=2,seed=5)
            scored,n=3,32;per=scored*n//2
            self.assertTrue(rep['fft_saturation']['model_only_evidence'])
            for name,active in (('ofdm_tx_fft_expected.txt',1),('ofdm_rx_fft_expected.txt',0)):
                log2n,rows=fft_cases.read_saturation_expected(folder/name)
                self.assertEqual(log2n,5)
                self.assertEqual(len(rows),8*5)
                for index,(evaluations,pos,neg) in enumerate(rows):
                    direction=1 if index>=4*5 else 0
                    with self.subTest(file=name,row=index):
                        self.assertEqual(evaluations,per if direction==active else 0)
                        self.assertLessEqual(pos+neg,evaluations)
            js=json.loads((folder/'fft_saturation.json').read_text())
            self.assertTrue(js['model_only_evidence'])
            self.assertEqual(js['formula']['ofdm_tx_fft']['inverse.s0.sum.re'],per)
            self.assertEqual(js['formula']['ofdm_tx_fft']['inverse.conj.im'],scored*n)
            self.assertEqual(js['formula']['ofdm_rx_fft']['forward.s4.diff.im'],per)
            self.assertEqual(js['evaluations']['tx.inverse.s0.sum.re'],per)
            self.assertEqual(js['evaluations']['rx.forward.s0.sum.im'],per)
            self.assertGreater(js['total'],0)


if __name__=='__main__':unittest.main()
