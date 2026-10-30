"""Integer OQPSK modem against the floating OQPSK model."""
from pathlib import Path
import sys
import unittest
import tempfile
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import modem_core as real
import oqpsk_fixed as o
from oqpsk_tracking import scenario as tracking_scenario, metrics as tracking_metrics
from oqpsk_cases import vectors, delay_vectors

CASES=[{},dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
       dict(snr_db=30,gain=.2,phase=-1.1,frequency=-.0005,delay=7.25),
       dict(snr_db=35,gain=.8,phase=2.1,frequency=.0003,delay=.5),
       dict(snr_db=35,gain=1.3,phase=.7,frequency=.0004,delay=5.5)]


def config():return real.load_config(ROOT/'modems'/'oqpsk_2_sps_timing_recovery_2019_12_05'/'config.json')


class TestOqpskFixed(unittest.TestCase):
    def test_transmitter_against_real(self):
        cfg=config()
        for n in (1,192,768):
            labels=np.random.default_rng(n).integers(0,4,n)
            q=np.array(o.transmit(labels))/2**15
            expected=real.transmit(cfg,labels)['waveform']
            with self.subTest(n=n):
                self.assertEqual(len(q),len(expected))
                self.assertLess(np.max(abs(q[:,0]+1j*q[:,1]-expected)),2e-4)
        with self.assertRaises(ValueError):o.transmit([0,4])

    def test_receiver_channels(self):
        cfg=config();data=real.frame_data(cfg);tx=real.transmit(cfg,data)
        for params in CASES:
            with self.subTest(params=params):
                wave=real.channel(cfg,tx['waveform'],**params)
                result=o.receive(o.quantize(wave),data[:192],len(data));acq=result['acquisition']
                self.assertEqual(np.count_nonzero(result['data'][192:]!=data[192:]),0)
                self.assertLessEqual(abs(acq['delay']/65536-params.get('delay',0)),.5)
                if params:self.assertLess(abs(acq['frequency']/2**32-params.get('frequency',0)),1e-5)

    def test_low_snr_errors(self):
        cfg=config();data=real.frame_data(cfg);tx=real.transmit(cfg,data)
        wave=real.channel(cfg,tx['waveform'],snr_db=-8,seed=101)
        self.assertGreater(np.count_nonzero(o.receive(o.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:]),20)

    def test_ser_near_threshold(self):
        # The floating grid fit collapses below 6 dB while the integer matched-filter
        # front end keeps tracking; the integer model must not be worse than the reference.
        cfg=config();data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data);fixed=reference=0
        for snr in (0,4):
            for seed in range(4):
                wave=real.channel(cfg,tx['waveform'],snr_db=snr,seed=600+seed,delay=seed*.37)
                fixed+=np.count_nonzero(o.receive(o.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:])
                reference+=np.count_nonzero(real.receive(cfg,wave,data[:192],len(data))['data'][192:]!=data[192:])
        with self.subTest(fixed=fixed,reference=reference):
            self.assertGreater(reference,50)
            self.assertLess(fixed,1.3*reference+20)

    def test_phase_noise(self):
        cfg=config();data=real.frame_data(cfg);tx=real.transmit(cfg,data)
        for pn in (.0003,.005,.01):
            wave=real.channel(cfg,tx['waveform'],snr_db=35,phase_noise=pn)
            fixed=np.count_nonzero(o.receive(o.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:])
            reference=np.count_nonzero(real.receive(cfg,wave,data[:192],len(data))['data'][192:]!=data[192:])
            print(f'phase_noise={pn}: fixed={fixed} floating={reference}')
            if pn==.0003:self.assertEqual(fixed,0)
            if pn==.005:self.assertLessEqual(fixed,reference+20)

    def test_validation(self):
        with self.assertRaises(ValueError):o.receive([(0,0)]*6144,[0]*191,768)
        with self.assertRaises(ValueError):o.receive([(0,0)]*6144,[0]*192,100)
        with self.assertRaises(ValueError):o.receive([(0,0)]*6144,[0]*192,2049)
        with self.assertRaises(ValueError):o.receive([(0,0)]*1024,[0]*192,768)
        with self.assertRaises(ValueError):o.receive([(0,0)]*6144,[0]*191+[4],768)
        for delay in (0,-1,1.5,True):
            with self.subTest(delay=delay),self.assertRaises(ValueError):
                o.receive([(0,0)]*6144,[0]*192,768,loop_delay=delay)

    def test_feedback_uses_exact_symbol_age(self):
        cfg=config();data=real.frame_data(cfg)
        wave=o.quantize(real.channel(cfg,real.transmit(cfg,data)['waveform'],snr_db=40,phase_noise=.018,seed=1000))
        default=o.receive(wave,data[:192],len(data))
        disabled=o.receive(wave,data[:192],len(data),feedback=False)
        for delay in (1,8,10,16):
            result=o.receive(wave,data[:192],len(data),loop_delay=delay)
            if delay==o.LOOP_DELAY:self.assertEqual(default['values'],result['values'])
            # Identical samples and acquisition: feedback cannot change any output
            # before its declared age, and the first nonzero error changes symbol D.
            self.assertEqual(result['acquisition'],disabled['acquisition'])
            self.assertEqual(result['values'][:delay],disabled['values'][:delay])
            self.assertNotEqual(result['values'][delay],disabled['values'][delay])

    def test_shorter_delay_on_identical_phase_noise_and_threshold_frames(self):
        with tempfile.TemporaryDirectory() as work:
            folders=[Path(work)/str(delay) for delay in (8,10)]
            reports=[delay_vectors(folder,delay) for folder,delay in zip(folders,(8,10))]
            for name in ('preamble','tx_symbols','tx_out','rx_wave','rx_acquire'):
                self.assertEqual((folders[0]/(name+'.txt')).read_bytes(),(folders[1]/(name+'.txt')).read_bytes())
            self.assertNotEqual((folders[0]/'rx_out.txt').read_bytes(),(folders[1]/'rx_out.txt').read_bytes())
            new,old=[{name:sum(values) for name,values in report['payload_errors'].items()} for report in reports]
            self.assertLess(new['phase_noise'],old['phase_noise'])
            self.assertLessEqual(new['threshold'],old['threshold']+6)

    def test_phase_excursion_tracking_and_disabled_control(self):
        for seed,count in ((19,768),(23,2048)):
            with self.subTest(seed=seed,count=count):
                preamble=np.random.default_rng(seed).integers(0,4,192)
                labels,_,_,result,disabled,report=tracking_scenario(preamble,count)
                self.assertTrue(all(report[k] for k in ('acquired','lost','recovered')),report)
                self.assertEqual(result['acquisition'],disabled['acquisition'])
                self.assertFalse(tracking_metrics(disabled,disabled,labels)['recovered'])
                # Recovery tolerance uses the same checker for a deliberately untracked receiver.
                self.assertGreater(report['recovery_disabled_evm'],.15)

    def test_tailcut_frame_matches_full_receiver_with_outside_taps(self):
        # A valid 8*N input frame omits the channel tail. The final Q interpolation
        # then lies beyond the captured FIR frame and must receive zero samples.
        with tempfile.TemporaryDirectory() as work:
            folder=Path(work);count=256
            report=vectors(folder,frames=1,count=count,seed=23,tailcut=True)
            read=lambda name:[tuple(map(int,line.split())) for line in (folder/name).read_text().splitlines()[1:]]
            wave=read('rx_wave.txt');labels=np.array([label for label,last in read('tx_symbols.txt')])
            preamble=[row[0] for row in read('preamble.txt')]
            self.assertEqual(len(wave),8*count)
            self.assertEqual([last for re,im,last in wave], [0]*(8*count-1)+[1])
            result=o.receive([(re,im) for re,im,last in wave],preamble,count)
            expected=[(re,im,int(label),int(k==count-1)) for k,((re,im),label) in
                      enumerate(zip(result['values'],result['data']))]
            self.assertEqual(read('rx_out.txt'),expected)
            acquired=result['acquisition']
            self.assertEqual(read('rx_acquire.txt'),[(acquired['delay'],acquired['frequency'],acquired['phase'])])
            self.assertLess(abs(acquired['delay']/65536-7.25),.5)
            capture_length=len(wave)+32
            q_base=((32+8*(count-1)+4)*65536+acquired['delay'])//65536-1
            self.assertGreaterEqual(q_base,capture_length)
            self.assertEqual(result['values'][-1][1],0)
            errors=int(np.count_nonzero(result['data'][192:]!=labels[192:]))
            self.assertEqual(report['payload_errors'],[errors])
            self.assertEqual(report['payload_ser'],[errors/(count-192)])
            self.assertEqual(report['frames'],1)
            self.assertIsNone(report['tracking'])


if __name__=='__main__':unittest.main()
