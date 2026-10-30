"""Общие проверки контракта каждого модема."""
import copy
from unittest.mock import patch
import modem_core
import numpy as np
from modem_core import (load_config, frame_data, transmit, receive, channel, encode,
                        decode, constellation, slice_symbols, maximal_ratio_combine)


class ModemContract:
    def setUp(self):
        self.cfg = load_config(self.config_path)

    def test_all_labels_and_state_transitions(self):
        cfg = self.cfg
        # Проверяются все пары соседних меток, а не только монотонный счётчик.
        data = np.array([x for a in range(cfg['order']) for b in range(cfg['order']) for x in (a,b)])
        ids, symbols = encode(cfg, data)
        np.testing.assert_array_equal(decode(cfg, ids), data)
        np.testing.assert_array_equal(slice_symbols(cfg, symbols), ids)

    def test_noiseless_waveform(self):
        cfg = self.cfg
        data = frame_data(cfg)
        tx = transmit(cfg, data)
        rx = receive(cfg, tx['waveform'], data[:192], len(data))
        np.testing.assert_array_equal(rx['data'][192:], data[192:])
        if cfg['family'] in ('msk','gmsk'):
            np.testing.assert_allclose(abs(tx['waveform']),1,atol=1e-12)

    def test_noise_fractional_delay_and_carrier(self):
        cfg = self.cfg
        data = frame_data(cfg)
        tx = transmit(cfg, data)
        for gain,phase,frequency,delay in ((.65,.38,.00015,2.25),(.2,-1.1,-.0005,7.25)):
            with self.subTest(gain=gain,frequency=frequency):
                wave = channel(cfg,tx['waveform'],snr_db=30,gain=gain,phase=phase,frequency=frequency,delay=delay)
                rx = receive(cfg,wave,data[:192],len(data))
                np.testing.assert_array_equal(rx['data'][192:],data[192:])
                self.assertLess(abs(rx['frequency']-frequency),1e-5)
                self.assertLessEqual(abs(rx['delay']-delay),.5)

    def test_repeatability_and_reset(self):
        cfg = self.cfg
        data = frame_data(cfg,256)
        first = transmit(cfg,data)
        transmit(cfg,frame_data(cfg,512,77))
        second = transmit(cfg,data)
        np.testing.assert_array_equal(first['waveform'],second['waveform'])

    def test_invalid_input(self):
        cfg = self.cfg
        for data in ([],[-1],[cfg['order']],[.25],[np.nan],[[0,1]]):
            with self.subTest(data=data), self.assertRaises(ValueError): transmit(cfg,data)
        with self.assertRaises(ValueError): receive(cfg,np.zeros(10),np.zeros(32,int),64)

    def test_noise_changes_decisions(self):
        cfg = self.cfg
        # Контроль чувствительности: ошибки нельзя скрывать возвратом переданных данных.
        data = frame_data(cfg)
        tx = transmit(cfg,data)
        wave = channel(cfg,tx['waveform'],snr_db=-8,seed=101)
        rx = receive(cfg,wave,data[:192],len(data))
        self.assertGreater(np.count_nonzero(rx['data'][192:]!=data[192:]),20)

    def test_variant_specific_processing(self):
        cfg = self.cfg
        data = frame_data(cfg)
        tx = transmit(cfg,data)
        if cfg['equalizer'] != 'none':
            wave = channel(cfg,tx['waveform'],echo=.45,delay=3.25,snr_db=35)
            rx = receive(cfg,wave,data[:192],len(data))
            np.testing.assert_array_equal(rx['data'][192:],data[192:])
            disabled = copy.deepcopy(cfg); disabled['equalizer']='none'
            bad = receive(disabled,wave,data[:192],len(data))
            self.assertGreater(np.count_nonzero(bad['data'][192:]!=data[192:]),0)
        elif cfg['diversity_branches']>1:
            gains = np.array([.2+.3j,1-.4j])
            rng = np.random.default_rng(99)
            noise = .15*(rng.normal(size=(2,len(tx['waveform'])))+1j*rng.normal(size=(2,len(tx['waveform']))))
            branches = gains[:,None]*tx['waveform']+noise
            combined = maximal_ratio_combine(branches,gains)
            self.assertLess(np.mean(abs(combined-tx['waveform'])**2),np.mean(abs(branches[0]/gains[0]-tx['waveform'])**2))
            rx = receive(cfg,combined,data[:192],len(data))
            np.testing.assert_array_equal(rx['data'][192:],data[192:])
        else:
            kwargs = dict(snr_db=35)
            if cfg['variable_delay']: kwargs.update(drift=.0001,delay=1.25)
            if cfg['phase_noise']: kwargs.update(phase_noise=.0003)
            wave = channel(cfg,tx['waveform'],**kwargs)
            rx = receive(cfg,wave,data[:192],len(data))
            np.testing.assert_array_equal(rx['data'][192:],data[192:])

        self.check_tracking_ablation()

    def check_tracking_ablation(self):
        cfg=self.cfg
        if not (cfg['variable_delay'] or cfg['phase_noise']):
            return
        data=frame_data(cfg,1536);tx=transmit(cfg,data)
        if cfg['variable_delay']:
            for drift in (-.0006,.0006):
                with self.subTest(drift=drift):
                    wave=channel(cfg,tx['waveform'],snr_db=35,drift=drift,delay=1.25)
                    good=receive(cfg,wave,data[:192],len(data))
                    disabled=dict(cfg,timing='feedforward')
                    bad=receive(disabled,wave,data[:192],len(data))
                    np.testing.assert_array_equal(good['data'][192:],data[192:])
                    self.assertGreater(np.count_nonzero(bad['data'][192:]!=data[192:]),20)
        if cfg['phase_noise']:
            wave=channel(cfg,tx['waveform'],snr_db=35,phase_noise=.005)
            good=receive(cfg,wave,data[:192],len(data))
            original=modem_core.symbol_receiver
            with patch.object(modem_core,'symbol_receiver',side_effect=lambda c,x,t:original(c,x,t,track_carrier=False)):
                bad=receive(cfg,wave,data[:192],len(data))
            np.testing.assert_array_equal(good['data'][192:],data[192:])
            self.assertGreater(np.count_nonzero(bad['data'][192:]!=data[192:]),0)
