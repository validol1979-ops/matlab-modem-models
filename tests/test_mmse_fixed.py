"""Integer 2x2 MMSE solver (mmse_fixed) against research_core.run('mimo')."""
from pathlib import Path
from fractions import Fraction
import sys
import unittest
import tempfile
import json
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import mmse_fixed as m
from research_core import run
import sat_diag
from mmse_cases import vectors


def q15(z):return [(max(-131072,min(131071,int(round(complex(v).real*32768)))),max(-131072,min(131071,int(round(complex(v).imag*32768))))) for v in z]
def complex_of(rows):return np.array([re+1j*im for re,im in rows])/32768
def matrix(H):return [q15(row) for row in H]


class TestMmseFixed(unittest.TestCase):
    def test_model_cases(self):
        rng=np.random.default_rng(2)
        H=np.array([[1+.3j,.4-.2j],[-.2+.1j,.8+.2j]])
        for lam in (0.,.015):
            symbols=(2*rng.integers(0,2,(128,2))-1).astype(complex);obs=symbols@H.T
            if lam:obs=obs+.02*(rng.normal(size=obs.shape)+1j*rng.normal(size=obs.shape))/np.sqrt(2)
            y=complex_of(m.solve(q15(obs.ravel()),matrix(H),lam));expected=run('mimo',[2,lam],obs.ravel(),H.ravel())
            with self.subTest(lam=lam):
                self.assertLess(np.max(abs(y-expected)),2e-4)
                self.assertTrue(np.all(np.sign(y.real)==symbols.real.ravel()))

    def test_random_channels(self):
        rng=np.random.default_rng(7)
        for trial in range(20):
            H=(rng.normal(size=(2,2))+1j*rng.normal(size=(2,2)))/2;lam=float(rng.choice([0,.001,.1,1]))
            obs=(rng.normal(size=40)+1j*rng.normal(size=40))/3
            Hq=complex_of([v for row in matrix(H) for v in row]).reshape(2,2)
            try:y=complex_of(m.solve(q15(obs),matrix(H),lam))
            except ValueError:continue
            expected=run('mimo',[2,lam],complex_of(q15(obs)),Hq.ravel())
            if np.max(abs(expected))>3.9:continue    # outside Q3.15
            with self.subTest(trial=trial):self.assertLess(np.max(abs(y-expected)),5e-4*max(1,np.linalg.cond(Hq)))

    def test_singular(self):
        with self.assertRaises(ValueError):m.weights(matrix([[1,1],[1,1]]),0)

    def test_tiny_identity_and_exact_weight_shifts(self):
        # Valid, perfectly conditioned H=I/32768: det=1, z=23, z-39=-16.
        tiny=[[(1,0),(0,0)],[(0,0),(1,0)]]
        expected=[[(1<<39,0),(0,0)],[(0,0),(1<<39,0)]]
        self.assertEqual(m.weights(tiny,0),expected)
        self.assertEqual(m.solve([(1,0),(0,1)],tiny,0),[(32768,0),(0,32768)])
        # det=2^16 has z=39: scaling at zero shift must preserve the exact product.
        unequal=[[(1,0),(0,0)],[(0,0),(256,0)]]
        self.assertEqual(m.weights(unequal,0),[[(1<<39,0),(0,0)],[(0,0),(1<<31,0)]])
        # Negative weights use the same exact left shift rather than sign-losing shifts.
        negative=[[(0,1),(0,0)],[(0,0),(0,-1)]]
        self.assertEqual(m.weights(negative,0),[[(0,-(1<<39)),(0,0)],[(0,0),(0,1<<39)]])
        self.assertEqual(m.solve([(0,1),(0,-1)],negative,0),[(32768,0),(32768,0)])

    def test_weight_round_shift_preserves_signed_half_up(self):
        for value in (-9,-8,-7,-1,0,1,7,8,9):
            with self.subTest(value=value):
                self.assertEqual(m.round_shift(value,3),(value+4)//8)
                self.assertEqual(m.round_shift(value,0),value)
                self.assertEqual(m.round_shift(value,-4),value*16)

    def test_rejects_unrepresentable_coefficients_with_positive_determinant(self):
        # det(Hraw)=1, so det(H^H H)=1: this is not the singular-matrix rejection.
        # H^-1 includes 131071*32768; its Q24 coefficient needs 56 bits.
        H=[[(131071,0),(131070,0)],[(1,0),(1,0)]]
        self.assertEqual(131071-131070,1)
        with self.assertRaisesRegex(ValueError,'coefficient.*48-bit'):
            m.weights(H,0)
        with self.assertRaisesRegex(ValueError,'coefficient.*48-bit'):
            m.solve([(1,0),(0,1)],H,0)

    def test_clamp_boundaries_and_evaluations(self):
        identity=matrix([[1,0],[0,1]])
        samples=[(131071,-131072),(-131072,131071)]
        stats=sat_diag.SatTrace()
        self.assertEqual(m.solve(samples,identity,0,stats=stats),samples)
        self.assertEqual(stats.total(),0)
        self.assertEqual(list(stats.evaluations.values()),[1]*4)
        half=matrix([[.5,0],[0,.5]])
        samples=[(65536,65536),(-65537,-65537)]
        stats=sat_diag.SatTrace();out=m.solve(samples,half,0,stats=stats)
        self.assertEqual(out,[(131071,131071),(-131072,-131072)])
        self.assertEqual(stats.counts,{'output.y0.re':{'pos':1,'neg':0},'output.y0.im':{'pos':1,'neg':0},
                                      'output.y1.re':{'pos':0,'neg':1},'output.y1.im':{'pos':0,'neg':1}})

    def test_channel_and_observation_port_formats(self):
        identity=matrix([[1,0],[0,1]])
        for H in (None,[],[identity[0]],[[identity[0][0]],identity[1]],
                  [[(1,0,0),(0,0)],[(0,0),(1,0)]],
                  [[1,(0,0)],[(0,0),(1,0)]],
                  [[(1.,0),(0,0)],[(0,0),(1,0)]],
                  [[(True,0),(0,0)],[(0,0),(1,0)]],
                  [[(131072,0),(0,0)],[(0,0),(1,0)]],
                  [[(1,-131073),(0,0)],[(0,0),(1,0)]]):
            with self.subTest(H=H):
                with self.assertRaises(ValueError):m.weights(H,0)
        for observations in (None,[(1,0)],[(1.,0),(0,0)],[(True,0),(0,0)],
                             [(131072,0),(0,0)],[(0,-131073),(0,0)],
                             [(1,0,0),(0,0)],[1,(0,0)]):
            with self.subTest(observations=observations):
                with self.assertRaises(ValueError):m.solve(observations,identity,0)
        # Negative 4 is representable; positive 4 is not. NumPy integer inputs
        # remain exact Python integers internally instead of overflowing int64 products.
        negative=np.array([[[-131072,0],[0,0]],[[0,0],[-131072,0]]],dtype=np.int64)
        self.assertEqual(m.weights(negative,np.float64(0)),
                         [[(-(1<<22),0),(0,0)],[(0,0),(-(1<<22),0)]])
        observations=np.array([[-131072,131071],[131071,-131072]],dtype=np.int64)
        self.assertEqual(m.solve(observations,np.array(identity),0),[tuple(row) for row in observations])

    def test_lambda_port_range_and_nearest_even_boundary(self):
        identity=matrix([[1,0],[0,1]])
        for lam in (-1,Fraction(-1,10**400),float('nan'),float('inf'),-float('inf'),1+0j,True,'0',16,17,10**400):
            with self.subTest(lam=str(lam)):
                with self.assertRaises(ValueError):m.weights(identity,lam)
        quantum=1/(1<<30)
        for lam,expected in ((.5*quantum,0),(1.5*quantum,2),(2.5*quantum,2)):
            self.assertEqual(m.lambda_raw(lam),expected)
        maximum=((1<<34)-1)*quantum
        self.assertEqual(m.lambda_raw(maximum),(1<<34)-1)
        self.assertEqual(len(m.weights(identity,maximum)),2)
        half_boundary=16-.5*quantum
        # At the half quantum below 16, ties-to-even rounds OUT of the 34-bit port.
        with self.assertRaisesRegex(ValueError,'Rounded lambda'):m.weights(identity,half_boundary)
        below=np.nextafter(half_boundary,-np.inf)
        self.assertEqual(m.lambda_raw(below),(1<<34)-1)
        self.assertEqual(len(m.weights(identity,below)),2)
        # Real inputs retain the existing exact round(lambda*2^30) arithmetic:
        # float conversion alone would collapse this value onto the rejected tie.
        exact_below=Fraction((1<<35)-1,1<<31)-Fraction(1,10**40)
        self.assertEqual(m.lambda_raw(exact_below),(1<<34)-1)
        self.assertEqual(len(m.weights(identity,exact_below)),2)

    def test_streamed_vectors_and_counter_replay(self):
        with tempfile.TemporaryDirectory() as tmp:
            for index,case in enumerate(('zf','mmse','random','strong','tinyidentity')):
                folder=Path(tmp)/case;report=vectors(folder,case,seed=37+index)
                cfg=[tuple(map(int,line.split())) for line in (folder/'cfg.txt').read_text().splitlines()]
                H=[cfg[:2],cfg[2:4]];lam=cfg[4][0]/2**30
                inputs=[tuple(map(int,line.split())) for line in (folder/'in.txt').read_text().splitlines()]
                outputs=[tuple(map(int,line.split())) for line in (folder/'out.txt').read_text().splitlines()]
                stats=sat_diag.SatTrace()
                values=m.solve([(re,im) for re,im,last in inputs],H,lam,stats=stats)
                self.assertEqual(values,[(re,im) for re,im,last in outputs])
                self.assertEqual(stats.to_dict(),report['saturation'])
                self.assertEqual(stats.to_dict()['evaluations'],json.loads((folder/'saturation.json').read_text())['evaluations'])
                self.assertEqual(sum(stats.evaluations.values()),2*report['outputs'])
                if case=='strong':self.assertEqual(stats.total(),0)
                else:self.assertGreater(stats.total(),0)
                if case=='tinyidentity':
                    self.assertEqual(H,[[(1,0),(0,0)],[(0,0),(1,0)]])
                    self.assertEqual(lam,0)
                    self.assertTrue(report['overload'])
                    self.assertTrue(all(abs(re)==1 and im==0 for re,im,last in inputs[:256]))
                    self.assertEqual([(re,im) for re,im,last in outputs[:256]],
                                     [(re*32768,0) for re,im,last in inputs[:256]])


if __name__=='__main__':unittest.main()
