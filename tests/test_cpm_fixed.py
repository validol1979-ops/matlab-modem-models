"""Integer MSK/GMSK modem against the floating CPM model."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import cpm_fixed as c
import gmsk_coherent as gc
import psk_fixed as p
import modem_core as real

MODELS={'msk':'msk_modulator_2008_06_22','gmsk':'gmsk_coherent_demodulation_2010_10_03'}
CASES=[{},dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
       dict(snr_db=30,gain=.2,phase=-1.1,frequency=-.0005,delay=7.25),
       dict(snr_db=35,gain=.8,phase=2.1,frequency=.0003,delay=.5),
       dict(snr_db=35,gain=1.3,phase=.7,frequency=.0004,delay=5.5)]


def config(family):return real.load_config(ROOT/'modems'/MODELS[family]/'config.json')


class TestCpmFixed(unittest.TestCase):
    def test_gaussian_taps(self):
        self.assertEqual(sum(c.GAUSS),1<<16)
        self.assertEqual(len(c.GAUSS),4*c.SPS+1)
        self.assertLess(max(abs(np.array(c.GAUSS)/65536-real.gaussian_taps(8,.3))),2e-5)

    def test_transmitter_against_real(self):
        for family,tolerance in (('msk',1e-4),('gmsk',2e-3)):
            cfg=config(family)
            for n in (1,192,768):
                bits=np.random.default_rng(n).integers(0,2,n)
                q=np.array(c.transmit(bits,family=='gmsk'))/2**15
                expected=real.transmit(cfg,bits)['waveform']
                with self.subTest(family=family,n=n):
                    self.assertEqual(len(q),len(expected))
                    self.assertLess(np.max(abs(q[:,0]+1j*q[:,1]-expected)),tolerance)
        with self.assertRaises(ValueError):c.transmit([0,2],False)

    def test_receiver_channels(self):
        for family in MODELS:
            cfg=config(family);data=real.frame_data(cfg);tx=real.transmit(cfg,data)
            for params in CASES:
                with self.subTest(family=family,params=params):
                    wave=real.channel(cfg,tx['waveform'],**params)
                    result=c.receive(p.quantize(wave),data[:192],len(data),family=='gmsk');acq=result['acquisition']
                    self.assertEqual(np.count_nonzero(result['data'][192:]!=data[192:]),0)
                    self.assertLessEqual(abs(acq['delay']/65536-params.get('delay',0)),.5)
                    if params:self.assertLess(abs(acq['frequency']/2**32-params.get('frequency',0)),1e-5)
            wave=real.channel(cfg,tx['waveform'],snr_db=-8,seed=101)
            self.assertGreater(np.count_nonzero(c.receive(p.quantize(wave),data[:192],len(data),family=='gmsk')['data'][192:]!=data[192:]),20)

    def test_ser_near_threshold(self):
        # The floating grid fit picks a different sampling offset per frame at low SNR; the
        # integer receiver must not be noticeably worse.
        for family in MODELS:
            cfg=config(family);data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data);fixed=reference=0
            for snr in (3,6):
                for seed in range(4):
                    wave=real.channel(cfg,tx['waveform'],snr_db=snr,seed=600+seed,delay=seed*.37)
                    fixed+=np.count_nonzero(c.receive(p.quantize(wave),data[:192],len(data),family=='gmsk')['data'][192:]!=data[192:])
                    reference+=np.count_nonzero(real.receive(cfg,wave,data[:192],len(data))['data'][192:]!=data[192:])
            with self.subTest(family=family,fixed=fixed,reference=reference):
                self.assertGreater(reference,50)
                self.assertLess(fixed,1.3*reference+20)

    def test_coherent_gmsk(self):
        cfg=config('gmsk');data=real.frame_data(cfg);tx=real.transmit(cfg,data)
        for params in CASES:
            with self.subTest(params=params):
                wave=real.channel(cfg,tx['waveform'],**params)
                self.assertEqual(np.count_nonzero(c.receive_coherent(p.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:]),0)
        wave=real.channel(cfg,tx['waveform'],snr_db=-8,seed=101)
        self.assertGreater(np.count_nonzero(c.receive_coherent(p.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:]),20)

    def test_coherent_gmsk_ser(self):
        # Integer coherent receiver close to the floating Laurent reference and far better
        # than the discriminator.
        cfg=config('gmsk');data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data);fixed=reference=discriminator=0
        for seed in range(4):
            wave=real.channel(cfg,tx['waveform'],snr_db=-4,seed=600+seed,delay=seed*.37)
            fixed+=np.count_nonzero(c.receive_coherent(p.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:])
            reference+=np.count_nonzero(gc.receive(cfg,wave,data[:192],len(data))['data'][192:]!=data[192:])
            discriminator+=np.count_nonzero(c.receive(p.quantize(wave),data[:192],len(data),True)['data'][192:]!=data[192:])
        with self.subTest(fixed=fixed,reference=reference,discriminator=discriminator):
            self.assertGreater(reference,50)
            self.assertLess(abs(fixed-reference),.2*reference+20)
            self.assertLess(3*fixed,discriminator)

    def test_validation(self):
        with self.assertRaises(ValueError):c.receive([(0,0)]*6144,[0]*191,768,False)


if __name__=='__main__':unittest.main()
