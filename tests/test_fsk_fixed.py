"""Integer M-FSK (fsk_fixed) against research_core.run('fsk_tx'/'fsk_rx')."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import fsk_fixed as k
from research_core import run


def q15(z):return [(int(round(complex(v).real*32768)),int(round(complex(v).imag*32768))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768


class TestFskFixed(unittest.TestCase):
    def test_model_case(self):
        rng=np.random.default_rng(2);data=np.array([0,1,2,3]*12);table=k.steps(32,2,3,4)
        wave=complex_of(k.transmit(data,32,table));expected=run('fsk_tx',[32,2,3,4],data)
        # 12-bit phase table: about 2 pi / 4096 of phase error.
        self.assertLess(np.max(abs(wave-expected)),2e-3)
        noisy=expected+.1*(rng.normal(size=len(expected))+1j*rng.normal(size=len(expected)))/np.sqrt(2)
        self.assertEqual(k.receive(q15(noisy),32,table),list(data))
        self.assertEqual(list(run('fsk_rx',[32,2,3,4],noisy).real.astype(int)),list(data))

    def test_other_alphabets(self):
        rng=np.random.default_rng(5)
        for n,f0,df,order in ((16,1,2,2),(40,.5,1.5,8),(7,0,1,3),(64,3,4,16)):
            labels=rng.integers(0,order,30);table=k.steps(n,f0,df,order)
            wave=complex_of(k.transmit(labels,n,table))
            with self.subTest(n=n,order=order):
                self.assertLess(np.max(abs(wave-run('fsk_tx',[n,f0,df,order],labels))),2e-3)
                self.assertEqual(k.receive(q15(wave),n,table),list(labels))

    def test_rejects(self):
        with self.assertRaises(ValueError):k.transmit([4],8,k.steps(8,0,1,4))
        with self.assertRaises(ValueError):k.receive([(0,0)]*7,8,k.steps(8,0,1,4))


if __name__=='__main__':unittest.main()
