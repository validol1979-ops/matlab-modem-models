"""Integer receiver checks against independent floating channel/reference."""
from pathlib import Path
import sys
import unittest
import math
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import bpsk_fixed as b
import modem_core as real
from bpsk_tables import files

CFG=real.load_config(ROOT/'modems/bpsk_costas_2008_08_25/config.json')

class TestBpskFixed(unittest.TestCase):
    def test_tables(self):
        for path,text in files().items():self.assertEqual(path.read_text(),text,path.name)
        self.assertEqual(b.RRC,b.RRC[::-1])
        for coefs in b.CUBIC:self.assertLessEqual(abs(sum(coefs)-65536),1)

    def test_cordic(self):
        rng=np.random.default_rng(81)
        for x,y in [(0,0),(-100000,0),(0,100000),(0,-100000)]+[tuple(map(int,p)) for p in rng.integers(-2**40,2**40,(1000,2))]:
            phase=b.atan2(y,x);expected=round(math.atan2(y,x)/(2*math.pi)*2**32)
            self.assertLess(abs(b.wrap(phase-expected)),50000)

    def test_tx_against_real(self):
        for n in (1,192,768):
            bits=np.random.default_rng(n).integers(0,2,n)
            q=np.array(b.transmit(bits))/2**15
            expected=real.transmit(CFG,bits)['waveform']
            self.assertEqual(len(q),8*n+32)
            self.assertLess(np.max(abs(q[:,0]+1j*q[:,1]-expected)),.00008)

    def test_receiver_channels(self):
        cases=[{},dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
               dict(snr_db=30,gain=.2,phase=-1.1,frequency=-.0005,delay=7.25),
               dict(snr_db=35,gain=.8,phase=2.1,frequency=.0003,delay=.5)]
        for seed in (19,82):
            bits=np.random.default_rng(seed).integers(0,2,768)
            for params in cases:
                with self.subTest(seed=seed,params=params):
                    wave=real.channel(CFG,real.transmit(CFG,bits)['waveform'],**params)
                    result=b.receive(b.quantize(wave),bits[:192],len(bits))
                    self.assertEqual(np.count_nonzero(result['data'][192:]!=bits[192:]),0)
                    self.assertLess(abs(result['acquisition']['delay']/65536-params.get('delay',0)),.5)
                    self.assertLess(abs(result['acquisition']['frequency']/2**32/8-params.get('frequency',0)),1e-5)
                    np.testing.assert_array_equal(real.receive(CFG,wave,bits[:192],len(bits))['data'][192:],bits[192:])

    def test_noise_is_not_payload_truth(self):
        bits=np.random.default_rng(19).integers(0,2,768)
        wave=real.channel(CFG,real.transmit(CFG,bits)['waveform'],snr_db=-8)
        result=b.receive(b.quantize(wave),bits[:192],len(bits))
        self.assertGreater(np.count_nonzero(result['data'][192:]!=bits[192:]),20)

    def test_validation(self):
        for preamble,count,wave in [([0]*191,768,[(0,0)]*6144),([0]*192,191,[(0,0)]*6144),([0]*192,2049,[(0,0)]*17000),([0]*192,768,[(0,0)]*10)]:
            with self.assertRaises(ValueError):b.receive(wave,preamble,count)

if __name__=='__main__':unittest.main()
