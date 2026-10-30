"""Integer PSK profiles: BPSK equivalence and QPSK against the floating reference."""
from pathlib import Path
import sys
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import bpsk_fixed as b
import psk_fixed as p
import modem_core as real

BPSK_CFG=real.load_config(ROOT/'modems/bpsk_costas_2008_08_25/config.json')
QPSK_MODELS=('qpsk_8_sps_fb_sync_2020_11_25','qpsk_script_basic','qpsk_script_costas')
QPSK_CFG=real.load_config(ROOT/'modems/qpsk_script_costas/config.json')
VARIANTS={'qpsk_half_diff':('qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15',),
          'qpsk_axis_diff_ff':('dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12','qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06',
                               'qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20','qpsk_phase_noise_phase_sync_2009_04_12'),
          'qpsk_axis':('qpsk_demod_with_phase_noise',),
          'psk8_ff':('psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15',),
          'psk8_fb':('psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19',),
          'psk8_rotated_fb':('dqpsk_19_09_2006',),
          'pi4':('pi4_qpsk_8_sps_ff_sync_2021_05_27','pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15'),
          'qam16':('qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18','qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10'),
          'qam16_eq':('qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21',),
          'qam16_dfe':('qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26',),
          'qam64':('QAM64_2008_11_21',)}
ECHO=dict(echo=.45,delay=3.25,snr_db=35)
CASES=[{},dict(snr_db=30,gain=.65,phase=.38,frequency=.00015,delay=2.25),
       dict(snr_db=30,gain=.2,phase=-1.1,frequency=-.0005,delay=7.25),
       dict(snr_db=35,gain=.8,phase=2.1,frequency=.0003,delay=.5),
       dict(snr_db=35,gain=1.3,phase=.7,frequency=.0004,delay=5.5)]


class TestPskFixed(unittest.TestCase):
    def test_profiles(self):
        self.assertIs(p.profile_for(BPSK_CFG),p.BPSK)
        for name in QPSK_MODELS:
            self.assertIs(p.profile_for(real.load_config(ROOT/'modems'/name/'config.json')),p.QPSK)
        for profile,names in VARIANTS.items():
            for name in names:self.assertEqual(p.profile_for(real.load_config(ROOT/'modems'/name/'config.json')).name,profile)
        for name in ('simo_maximal_ratio_combining_2010_08_27','oqpsk_2_sps_timing_recovery_2019_12_05'):
            with self.assertRaises(ValueError):p.profile_for(real.load_config(ROOT/'modems'/name/'config.json'))

    def test_block_fit_matches_rtl_default(self):
        # bpsk_rx: BLOCK_FIT=EQUALIZER!=0||ORDER==4; simo_rx and the synthesis top rely on the default.
        for profile in p.PROFILES:
            self.assertEqual(profile.block_fit,profile.equalizer!='none' or profile.order==4,profile.name)

    def test_low_snr_acquisition_keeps_unshifted_candidate(self):
        # -8 dB, channel delay 0: the energy delay lands below -0.5 sample. The candidate is
        # clamped, not dropped, so the fit stays on the symbol grid and the gain is not railed.
        labels=np.random.default_rng(19).integers(0,4,512)
        tx=np.array([complex(*z) for z in p.transmit(p.QPSK,labels)])/32768
        rows=p.quantize(real.channel(real.load_config(ROOT/'modems/qpsk_script_costas/config.json'),tx,seed=7,snr_db=-8))
        acq=p.acquire(p.QPSK,p.fir(rows,p.QPSK.rx_shift),labels[:192])
        self.assertLess(abs(acq['delay']),1<<16);self.assertLess(acq['gain'],16<<20)
        decoded=np.asarray(p.receive(p.QPSK,rows,labels[:192],512)['data'])
        self.assertLess(np.count_nonzero(decoded[192:]!=labels[192:]),100)

    def test_qpsk_labels(self):
        table=real.constellation(QPSK_CFG)
        for index in range(4):
            a,b2=p.QPSK.point(index)
            self.assertEqual((a>0,b2>0),(table[index].real>0,table[index].imag>0))
            self.assertEqual(p.QPSK.slice((a*p.QPSK.amplitude,b2*p.QPSK.amplitude)),index)

    def test_bpsk_profile_is_bit_exact(self):
        for seed in (19,82):
            bits=np.random.default_rng(seed).integers(0,2,768)
            self.assertEqual(b.transmit(bits),p.transmit(p.BPSK,bits))
            for params in CASES[:4]+[dict(snr_db=-8)]:
                with self.subTest(seed=seed,params=params):
                    wave=b.quantize(real.channel(BPSK_CFG,real.transmit(BPSK_CFG,bits)['waveform'],**params))
                    first=b.receive(wave,bits[:192],768);second=p.receive(p.BPSK,wave,bits[:192],768)
                    self.assertEqual(first['trace'],second['trace'])
                    self.assertEqual(first['acquisition'],second['acquisition'])

    def test_qpsk_tx_against_real(self):
        for n in (1,192,768):
            symbols=np.random.default_rng(n).integers(0,4,n)
            q=np.array(p.transmit(p.QPSK,symbols))/2**15
            expected=real.transmit(QPSK_CFG,symbols)['waveform']
            self.assertEqual(len(q),8*n+32)
            self.assertLess(np.max(abs(q[:,0]+1j*q[:,1]-expected)),.0001)

    def test_qpsk_receiver_channels(self):
        for seed in (19,82):
            symbols=np.random.default_rng(seed).integers(0,4,768)
            for params in CASES:
                with self.subTest(seed=seed,params=params):
                    wave=real.channel(QPSK_CFG,real.transmit(QPSK_CFG,symbols)['waveform'],**params)
                    result=p.receive(p.QPSK,p.quantize(wave),symbols[:192],768);acq=result['acquisition']
                    self.assertEqual(np.count_nonzero(result['data'][192:]!=symbols[192:]),0)
                    self.assertTrue(acq['confidence'])
                    self.assertLess(abs(acq['delay']/65536-params.get('delay',0)),.5)
                    self.assertLess(abs(acq['frequency']/2**32/8-params.get('frequency',0)),1e-5)
                    np.testing.assert_array_equal(real.receive(QPSK_CFG,wave,symbols[:192],768)['data'][192:],symbols[192:])

    def test_qpsk_noise_is_not_payload_truth(self):
        symbols=np.random.default_rng(19).integers(0,4,768)
        wave=real.channel(QPSK_CFG,real.transmit(QPSK_CFG,symbols)['waveform'],snr_db=-8)
        result=p.receive(p.QPSK,p.quantize(wave),symbols[:192],768)
        self.assertGreater(np.count_nonzero(result['data'][192:]!=symbols[192:]),20)

    def test_variants_against_real(self):
        cases=CASES[:3]+[dict(snr_db=35)]
        for profile_name,names in VARIANTS.items():
            for name in names[:1]+names[3:]:
                cfg=real.load_config(ROOT/'modems'/name/'config.json');profile=p.profile_for(cfg)
                data=real.frame_data(cfg);tx=real.transmit(cfg,data)
                q=np.array(p.transmit(profile,data))/2**15
                self.assertLess(np.max(abs(q[:,0]+1j*q[:,1]-tx['waveform'])),.0001)
                for params in cases+([dict(snr_db=35,phase_noise=.0003)] if cfg['phase_noise'] else []):
                    with self.subTest(model=name,params=params):
                        wave=real.channel(cfg,tx['waveform'],**params)
                        result=p.receive(profile,p.quantize(wave),data[:192],len(data))
                        self.assertEqual(np.count_nonzero(result['data'][192:]!=data[192:]),0)
                wave=real.channel(cfg,tx['waveform'],snr_db=-8,seed=101)
                self.assertGreater(np.count_nonzero(p.receive(profile,p.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:]),20)

    def test_phase_noise_needs_tracking(self):
        import dataclasses
        for name in ('qpsk_phase_noise_phase_sync_2009_04_12','qpsk_demod_with_phase_noise'):
            cfg=real.load_config(ROOT/'modems'/name/'config.json');profile=p.profile_for(cfg)
            data=real.frame_data(cfg,1536);wave=real.channel(cfg,real.transmit(cfg,data)['waveform'],snr_db=35,phase_noise=.005)
            good=p.receive(profile,p.quantize(wave),data[:192],len(data))
            bad=p.receive(dataclasses.replace(profile,freq_gain=0,phase_gain=0),p.quantize(wave),data[:192],len(data))
            self.assertEqual(np.count_nonzero(good['data'][192:]!=data[192:]),0,name)
            self.assertGreater(np.count_nonzero(bad['data'][192:]!=data[192:]),0,name)

    def test_psk8_slicer(self):
        import math
        for index,point in enumerate(p.TARGET8):self.assertEqual(p.PSK8_FB.slice(point),index)
        rng=np.random.default_rng(5)
        for x,y in rng.integers(-60000,60000,(5000,2)):
            angle=math.degrees(math.atan2(y,x))%360
            if abs(angle-45*round(angle/45))>1e-6:self.assertEqual(p.PSK8_FB.slice((int(x),int(y))),int(angle//45))

    def test_gray_differential(self):
        profile=p.QPSK_HALF_DIFF
        labels=[a for x in range(4) for y in range(4) for a in (x,y)]
        ids=p.encode(profile,labels);previous=0;decoded=[]
        for index in ids:decoded.append(p.decode(profile,index,previous));previous=index
        self.assertEqual(decoded,labels)
        np.testing.assert_array_equal(ids,real.encode(real.load_config(ROOT/'modems'/VARIANTS['qpsk_half_diff'][0]/'config.json'),labels)[0])

    def test_pi4_differential(self):
        cfg=real.load_config(ROOT/'modems'/VARIANTS['pi4'][0]/'config.json')
        labels=[a for x in range(4) for y in range(4) for a in (x,y)]
        ids=p.encode(p.PI4,labels)
        np.testing.assert_array_equal(ids,real.encode(cfg,labels)[0])
        self.assertTrue(all((b-a)%2 for a,b in zip([0]+ids,ids)))
        previous=0;decoded=[]
        for index in ids:decoded.append(p.decode(p.PI4,index,previous));previous=index
        self.assertEqual(decoded,labels)
        with self.assertRaises(ValueError):p.encode(p.PI4,[4])

    def test_qam16_tables(self):
        cfg=real.load_config(ROOT/'modems'/VARIANTS['qam16'][0]/'config.json');table=real.constellation(cfg)
        for index,(a,b) in enumerate(p.QAM16_LEVELS):
            self.assertEqual(complex(a,b)/2,table[index])
            self.assertEqual(p.QAM16.slice((a*16384,b*16384)),index)
        rng=np.random.default_rng(8)
        for x,y in rng.integers(-131072,131072,(4000,2)):
            if x%32768 and y%32768:
                self.assertEqual(p.QAM16.slice((int(x),int(y))),int(np.argmin(abs(table-complex(x,y)/2**15))))
        labels=list(range(16))*3;ids=p.encode(p.QAM16,labels)
        np.testing.assert_array_equal(ids,real.encode(cfg,labels)[0])
        previous=0;decoded=[]
        for index in ids:decoded.append(p.decode(p.QAM16,index,previous));previous=index
        self.assertEqual(decoded,labels)
        self.assertEqual([p.reciprocal(n) for n in (2,10,18)],[32768,6554,3641])

    def test_qam16_drift_needs_timing_loop(self):
        import dataclasses
        cfg=real.load_config(ROOT/'modems'/VARIANTS['qam16'][1]/'config.json')
        data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data)
        for drift in (.0006,-.0006):
            wave=p.quantize(real.channel(cfg,tx['waveform'],snr_db=35,drift=drift,delay=1.25))
            good=p.receive(p.QAM16,wave,data[:192],len(data))
            bad=p.receive(dataclasses.replace(p.QAM16,timing_gain=0),wave,data[:192],len(data))
            self.assertEqual(np.count_nonzero(good['data'][192:]!=data[192:]),0)
            self.assertGreater(np.count_nonzero(bad['data'][192:]!=data[192:]),100)

    def test_qam16_ser_near_threshold(self):
        cfg=real.load_config(ROOT/'modems'/VARIANTS['qam16'][0]/'config.json')
        data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data);fixed=reference=0
        for seed in range(4):
            wave=real.channel(cfg,tx['waveform'],snr_db=6,seed=300+seed)
            fixed+=np.count_nonzero(p.receive(p.QAM16,p.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:])
            reference+=np.count_nonzero(real.receive(cfg,wave,data[:192],len(data))['data'][192:]!=data[192:])
        self.assertGreater(reference,50)
        self.assertLess(abs(fixed-reference),.15*reference+10)

    def test_equalizer_reciprocal(self):
        rng=np.random.default_rng(12)
        for power in [1,2,511,512,1023,1024]+[int(x) for x in rng.integers(1,1<<40,2000)]:
            s=power.bit_length();m=power>>(s-10) if s>10 else power<<(10-s)
            # r*2^(-9-s) approximates 1/power within the 10-bit mantissa truncation.
            self.assertLess(abs(p.EQ_RECIPROCAL[m-512]*2.0**(-9-s)*power-1),2**-9+2**-10)
        for e in ((1000,-2000),(-131072,131071),(0,0)):
            for power in (1<<33,3<<30,7):
                c=p.eq_coefficient(e,power,p.EQ_STEP_DATA);x=12345
                expected=[v*p.EQ_STEP_DATA/2**15/power*x*2**22 for v in e]
                for got,want in zip(c,expected):
                    if abs(got)<131071:self.assertLess(abs(round(got*x/2**18)-want),.004*abs(want)+2)

    def test_equalizers_remove_echo(self):
        import dataclasses
        for profile_name in ('qam16_eq','qam16_dfe'):
            cfg=real.load_config(ROOT/'modems'/VARIANTS[profile_name][0]/'config.json');profile=p.profile_for(cfg)
            data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data)
            for params in (ECHO,dict(ECHO,gain=.65,phase=.38,frequency=.00015,snr_db=30),dict(ECHO,delay=7.25,gain=.2,phase=-1.1,frequency=-.0005,snr_db=30)):
                with self.subTest(profile=profile_name,params=params):
                    wave=p.quantize(real.channel(cfg,tx['waveform'],**params))
                    good=p.receive(profile,wave,data[:192],len(data));acq=good['acquisition']
                    self.assertEqual(np.count_nonzero(good['data'][192:]!=data[192:]),0)
                    self.assertLess(abs(acq['frequency']/2**32/8-params.get('frequency',0)),1e-5)
                    # Ablation: the same block acquisition without the equalizer fails.
                    bad=p.receive(dataclasses.replace(profile,equalizer='none'),wave,data[:192],len(data))
                    self.assertGreater(np.count_nonzero(bad['data'][192:]!=data[192:]),300)

    def test_equalizer_ser_near_threshold(self):
        for profile_name in ('qam16_eq','qam16_dfe'):
            cfg=real.load_config(ROOT/'modems'/VARIANTS[profile_name][0]/'config.json');profile=p.profile_for(cfg)
            data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data);fixed=reference=0
            for seed in range(4):
                wave=real.channel(cfg,tx['waveform'],echo=.45,delay=3.25,snr_db=8,seed=400+seed)
                fixed+=np.count_nonzero(p.receive(profile,p.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:])
                reference+=np.count_nonzero(real.receive(cfg,wave,data[:192],len(data))['data'][192:]!=data[192:])
            with self.subTest(profile=profile_name,fixed=fixed,reference=reference):
                self.assertGreater(reference,30)
                self.assertLess(abs(fixed-reference),.2*reference+10)

    def test_equalizer_drift_needs_timing_loop(self):
        import dataclasses
        cfg=real.load_config(ROOT/'modems'/VARIANTS['qam16_eq'][0]/'config.json')
        data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data)
        for drift in (.0006,-.0006):
            wave=p.quantize(real.channel(cfg,tx['waveform'],snr_db=35,drift=drift,delay=1.25))
            good=p.receive(p.QAM16_EQ,wave,data[:192],len(data))
            bad=p.receive(dataclasses.replace(p.QAM16_EQ,timing_gain=0),wave,data[:192],len(data))
            self.assertEqual(np.count_nonzero(good['data'][192:]!=data[192:]),0)
            self.assertGreater(np.count_nonzero(bad['data'][192:]!=data[192:]),100)

    def test_qam64_tables(self):
        cfg=real.load_config(ROOT/'modems'/VARIANTS['qam64'][0]/'config.json');table=real.constellation(cfg)
        for index,(a,b) in enumerate(p.QAM64_LEVELS):
            self.assertEqual(complex(a,b),table[index])
            self.assertEqual(p.QAM64.slice((a*8192,b*8192)),index)
        rng=np.random.default_rng(9)
        for x,y in rng.integers(-131072,131072,(4000,2)):
            if x%16384 and y%16384:
                self.assertEqual(p.QAM64.slice((int(x),int(y))),int(np.argmin(abs(table-complex(x,y)/8192))))
        labels=list(range(64))*3;ids=p.encode(p.QAM64,labels)
        np.testing.assert_array_equal(ids,real.encode(cfg,labels)[0])
        previous=0;decoded=[]
        for index in ids:decoded.append(p.decode(p.QAM64,index,previous));previous=index
        self.assertEqual(decoded,labels)
        # Transmit points level*2^14 stay inside 18 bits; the waveform is the exact Q15 one.
        self.assertEqual(max(abs(v) for i in range(64) for v in p.QAM64.tx_point(i)),7*16384)

    def test_qam64_ser_near_threshold(self):
        cfg=real.load_config(ROOT/'modems'/VARIANTS['qam64'][0]/'config.json')
        data=real.frame_data(cfg,1536);tx=real.transmit(cfg,data);fixed=reference=0
        for seed in range(4):
            wave=real.channel(cfg,tx['waveform'],snr_db=12,seed=500+seed)
            fixed+=np.count_nonzero(p.receive(p.QAM64,p.quantize(wave),data[:192],len(data))['data'][192:]!=data[192:])
            reference+=np.count_nonzero(real.receive(cfg,wave,data[:192],len(data))['data'][192:]!=data[192:])
        self.assertGreater(reference,50)
        self.assertLess(abs(fixed-reference),.15*reference+10)

    def test_qam64_input_level_limit(self):
        # Contract limit of the Q3.15 input: channel gain up to 1.2 (peak 3.64 per axis at 1).
        cfg=real.load_config(ROOT/'modems'/VARIANTS['qam64'][0]/'config.json')
        data=real.frame_data(cfg);tx=real.transmit(cfg,data)
        wave=p.quantize(real.channel(cfg,tx['waveform'],snr_db=30,gain=1.2))
        self.assertEqual(np.count_nonzero(p.receive(p.QAM64,wave,data[:192],len(data))['data'][192:]!=data[192:]),0)

    def test_validation(self):
        with self.assertRaises(ValueError):p.receive(p.QPSK,[(0,0)]*6144,[0]*191,768)
        with self.assertRaises(ValueError):p.receive(p.QPSK,[(0,0)]*6144,[4]*192,768)
        with self.assertRaises(ValueError):p.transmit(p.QPSK,[0,1,4])
        with self.assertRaises(ValueError):p.transmit(p.BPSK,[0,2])


if __name__=='__main__':unittest.main()
