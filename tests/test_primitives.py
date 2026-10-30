"""Независимые опорные проверки базовых операций и происхождения данных."""
from pathlib import Path
import hashlib
import json
import sys
import unittest
import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common'/'python'))
from modem_core import (rrc_taps, gaussian_taps, cubic, encode, load_config,
                        maximal_ratio_combine, transmit)


# Публичная копия не содержит сторонних исходников (THIRD_PARTY.md).
THIRD_PARTY_SKIP='third-party sources/ are not in this copy; see THIRD_PARTY.md'

class TestPrimitives(unittest.TestCase):
    def test_rrc_symmetry_energy_and_nyquist(self):
        for beta in (0,.25,1):
            h=rrc_taps(8,128,beta)
            np.testing.assert_allclose(h,h[::-1],atol=1e-15)
            self.assertAlmostEqual(float(h@h),1,places=14)
            if beta:
                rc=np.convolve(h,h)
                self.assertLess(np.max(abs(rc[128+8:128+48:8])),.003)

    def test_cubic_reproduces_cubic_polynomial(self):
        x=np.arange(30,dtype=float)
        positions=np.array([3.1,6.5,18.8])
        np.testing.assert_allclose(cubic(x**3,positions),positions**3,rtol=1e-14)
        np.testing.assert_allclose(cubic(x,[0,29,-4,40]),[0,29,0,0])

    def test_gaussian(self):
        h=gaussian_taps(8,.3)
        self.assertAlmostEqual(h.sum(),1,places=14)
        np.testing.assert_array_equal(h,h[::-1])
        self.assertTrue(np.all(h>0))

    def test_independent_bpsk_and_pi4_vectors(self):
        cfg=load_config(ROOT/'modems/bpsk_costas_2008_08_25/config.json')
        ids,symbols=encode(cfg,[0,1,1,0,1])
        np.testing.assert_array_equal(ids,[0,1,0,0,1])
        np.testing.assert_array_equal(symbols,[.5+.5j,-.5-.5j,.5+.5j,.5+.5j,-.5-.5j])
        cfg=load_config(ROOT/'modems/pi4_qpsk_8_sps_ff_sync_2021_05_27/config.json')
        ids,_=encode(cfg,[0,1,2,3])
        np.testing.assert_array_equal(ids,[1,4,3,0])

    def test_msk_phase_increments(self):
        cfg=load_config(ROOT/'modems/msk_modulator_2008_06_22/config.json')
        wave=transmit(cfg,[1,0])['waveform']
        phase=np.angle(wave*np.conj(np.r_[1,wave[:-1]]))
        np.testing.assert_allclose(phase,np.r_[np.full(8,np.pi/16),np.full(8,-np.pi/16)],atol=1e-14)

    def test_source_integrity(self):
        if not (ROOT/'sources').is_dir():self.skipTest(THIRD_PARTY_SKIP)
        catalog=json.loads((ROOT/'modems/catalog.json').read_text())
        self.assertEqual({entry['config'] for entry in catalog},
                         {str(p.relative_to(ROOT)) for p in (ROOT/'modems').glob('*/config.json')})
        self.assertEqual(len(catalog),len({entry['name'] for entry in catalog}))
        for entry in catalog:
            cfg=load_config(ROOT/entry['config'])
            source=ROOT/cfg['source']
            original=ROOT/'modems'/cfg['name']/'original'/source.name
            self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(),cfg['source_sha256'])
            self.assertEqual(source.read_bytes(),original.read_bytes())
        cfg=load_config(ROOT/'modems/dqpsk_19_09_2006/config.json')
        self.assertEqual(cfg['order'],8)

    def test_extracted_mapping_and_source_locations(self):
        if not (ROOT/'sources').is_dir():self.skipTest(THIRD_PARTY_SKIP)
        for config_path in sorted((ROOT/'modems').glob('*/config.json')):
            cfg=load_config(config_path)
            blocks=json.loads((config_path.parent/'source_parameters.json').read_text())
            source_lines=(ROOT/cfg['source']).read_text(errors='replace').splitlines()
            for block in blocks:
                self.assertEqual(source_lines[block['source_line']-1].strip(),'Block {')
                if block.get('Name')=='data_mapper' and 'OutputValues' in block:
                    raw=[complex(s.replace('i','j')) for s in block['OutputValues'].strip('[]').split()]
                    expected=np.array(cfg['constellation'])
                    np.testing.assert_array_equal(raw,expected[:,0]+1j*expected[:,1])

    def test_oqpsk_half_symbol_stagger(self):
        cfg=load_config(ROOT/'modems/oqpsk_2_sps_timing_recovery_2019_12_05/config.json')
        data=np.array([0,1,2,3,3,0,2,1])
        actual=transmit(cfg,data)['waveform']
        ordinary=transmit(dict(cfg,family='psk'),data)['waveform']
        half=cfg['sps']//2
        np.testing.assert_allclose(actual.real,np.pad(ordinary.real,(0,half)),atol=1e-15)
        np.testing.assert_allclose(actual.imag,np.pad(ordinary.imag,(half,0)),atol=1e-15)

    def test_mrc_analytic_and_invalid(self):
        signal=np.array([1+2j,-.5j])
        gains=np.array([1+1j,.5-1j])
        np.testing.assert_allclose(maximal_ratio_combine(gains[:,None]*signal,gains,[1,2]),signal)
        for gains_,variances in (([0,0],[1,1]),(gains,[0,1])):
            with self.assertRaises(ValueError): maximal_ratio_combine(np.zeros((2,2)),gains_,variances)


if __name__=='__main__': unittest.main(verbosity=2)
