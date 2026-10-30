"""Integer two-branch MRC against the floating reference and the SIMO receiver."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import psk_fixed as p
import mrc_fixed as m
import modem_core as real

CFG=real.load_config(ROOT/'modems/simo_maximal_ratio_combining_2010_08_27/config.json')
GAINS=(.2+.3j,1-.4j)
CASES=[{},dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
       dict(snr_db=35,gain=.8,phase=2.1,frequency=.0003,delay=.5)]


def branches(wave,gains,sigma,seed,variances=(1,1)):
    rng=np.random.default_rng(seed);out=[]
    for gain,variance in zip(gains,variances):
        noise=sigma*np.sqrt(variance)*(rng.normal(size=len(wave))+1j*rng.normal(size=len(wave)))
        out.append(gain*wave+noise)
    return out


class TestMrcFixed(unittest.TestCase):
    def test_profile(self):
        self.assertIs(m.branch_profile(CFG),p.QPSK_DIFF)
        with self.assertRaises(ValueError):p.profile_for(CFG)
        with self.assertRaises(ValueError):m.branch_profile(real.load_config(ROOT/'modems/qpsk_script_costas/config.json'))

    def test_weights_against_real(self):
        rng=np.random.default_rng(3)
        for _ in range(300):
            gains=rng.normal(size=2)+1j*rng.normal(size=2);variances=rng.integers(1,65536,2)
            if np.min(abs(gains))<.05 or np.max(abs(gains))>3.9:continue
            q=[m.quantize_gain(g) for g in gains]
            try:weights=m.weights(*q,*map(int,variances))
            except ValueError:continue
            gq=np.array([complex(*x)/2**15 for x in q])
            expected=gq.conj()/variances/np.sum(abs(gq)**2/variances)
            got=np.array([complex(*w)/2**14 for w in weights])
            self.assertLess(np.max(abs(got-expected)),2**-14)

    def test_weight_rounding_and_limits(self):
        self.assertEqual(m.weights((32768,0),(0,0)),((16384,0),(0,0)))
        self.assertEqual(m.weights((0,0),(0,-16384)),((0,0),(0,32768)))
        with self.assertRaises(ValueError):m.weights((0,0),(0,0))
        with self.assertRaises(ValueError):m.weights((32768,0),(0,0),0,1)
        with self.assertRaises(ValueError):m.weights((32768,0),(0,0),1,65536)
        with self.assertRaises(ValueError):m.weights((131072,0),(0,0))
        # |w| = 1/|g| reaches 8 for |g| = 1/8.
        self.assertEqual(m.weights((4097,0),(0,0))[0][0],131040)
        with self.assertRaises(ValueError):m.weights((4096,0),(0,0))

    def test_combine_matches_real(self):
        data=real.frame_data(CFG);wave=real.transmit(CFG,data)['waveform']
        a,b=branches(wave,GAINS,.01,5)
        weights=m.weights(*(m.quantize_gain(g) for g in GAINS))
        got=np.array(m.combine(p.quantize(a),p.quantize(b),*weights))/2**15
        expected=real.maximal_ratio_combine([a,b],GAINS)
        self.assertLess(np.max(abs(got[:,0]+1j*got[:,1]-expected)),5e-4)
        with self.assertRaises(ValueError):m.combine([(0,0)],[],*weights)

    def test_combine_saturates(self):
        self.assertEqual(m.combine([(131071,-131072)],[(131071,-131072)],(16384,0),(16384,0)),[(131071,-131072)])

    def test_receiver_channels(self):
        data=real.frame_data(CFG);tx=real.transmit(CFG,data)
        for index,case in enumerate(CASES):
            for variances,sigma in (((1,1),.15),((1,4),.07),((9,1),.05)):
                with self.subTest(case=case,variances=variances):
                    wave=real.channel(CFG,tx['waveform'],seed=29+index,**case)
                    a,b=branches(wave,GAINS,sigma,99+index,variances)
                    result=m.receive(p.QPSK_DIFF,p.quantize(a),p.quantize(b),*(m.quantize_gain(g) for g in GAINS),data[:192],len(data),*variances)
                    self.assertEqual(np.count_nonzero(result['data'][192:]!=data[192:]),0)
                    self.assertTrue(result['acquisition']['confidence'])
                    reference=real.receive(CFG,real.maximal_ratio_combine([a,b],GAINS,variances),data[:192],len(data))
                    np.testing.assert_array_equal(reference['data'][192:],data[192:])

    def test_diversity_gain_and_real_ser(self):
        data=real.frame_data(CFG,1536);tx=real.transmit(CFG,data)
        totals=dict(fixed=0,real=0,single=0)
        # sigma 0.3: SER is well above zero, acquisition does not fail (see docs/BPSK_RTL.md, SIMO).
        for seed in range(10):
            wave=real.channel(CFG,tx['waveform'],seed=40+seed)
            a,b=branches(wave,GAINS,.3,60+seed)
            fixed=m.receive(p.QPSK_DIFF,p.quantize(a),p.quantize(b),*(m.quantize_gain(g) for g in GAINS),data[:192],len(data))
            reference=real.receive(CFG,real.maximal_ratio_combine([a,b],GAINS),data[:192],len(data))
            single=p.receive(p.QPSK_DIFF,p.quantize(b/GAINS[1]),data[:192],len(data))
            for key,result in (('fixed',fixed),('real',reference),('single',single)):
                totals[key]+=int(np.count_nonzero(result['data'][192:]!=data[192:]))
        self.assertGreater(totals['fixed'],0)
        self.assertLess(abs(totals['fixed']-totals['real']),.1*totals['real']+10)
        self.assertLess(totals['fixed'],totals['single'])

    def test_qpsk_diff_tx_against_real(self):
        data=real.frame_data(CFG);q=np.array(p.transmit(p.QPSK_DIFF,data))/2**15
        self.assertLess(np.max(abs(q[:,0]+1j*q[:,1]-real.transmit(CFG,data)['waveform'])),.0001)


if __name__=='__main__':unittest.main()
