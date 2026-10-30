# Modem catalog

Each row is a separate workspace with preserved original source, a portable configuration and Octave, Python and SystemVerilog entry points. Related historical variants can share a portable algorithm; see the porting contract for differences.

| Workspace | Modulation | Alphabet | Equalizer |
| --- | --- | --- | --- |
| [QAM64_2008_11_21](../modems/QAM64_2008_11_21/README.md) | QAM | 64 | none |
| [bpsk_costas_2008_08_25](../modems/bpsk_costas_2008_08_25/README.md) | PSK | 2 | none |
| [dqpsk_19_09_2006](../modems/dqpsk_19_09_2006/README.md) | PSK | 8 | none |
| [dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12](../modems/dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12/README.md) | PSK | 4 | none |
| [gmsk_coherent_demodulation_2010_10_03](../modems/gmsk_coherent_demodulation_2010_10_03/README.md) | GMSK | 2 | none |
| [msk_modulator_2008_06_22](../modems/msk_modulator_2008_06_22/README.md) | MSK | 2 | none |
| [oqpsk_2_sps_timing_recovery_2019_12_05](../modems/oqpsk_2_sps_timing_recovery_2019_12_05/README.md) | OQPSK | 4 | none |
| [pi4_qpsk_8_sps_ff_sync_2021_05_27](../modems/pi4_qpsk_8_sps_ff_sync_2021_05_27/README.md) | PI4 | 4 | none |
| [pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15](../modems/pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15/README.md) | PI4 | 4 | none |
| [psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15](../modems/psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15/README.md) | PSK | 8 | none |
| [psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19](../modems/psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19/README.md) | PSK | 8 | none |
| [qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18](../modems/qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18/README.md) | QAM | 16 | none |
| [qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26](../modems/qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26/README.md) | QAM | 16 | dfe |
| [qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10](../modems/qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10/README.md) | QAM | 16 | none |
| [qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21](../modems/qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21/README.md) | QAM | 16 | linear |
| [qpsk_8_sps_fb_sync_2020_11_25](../modems/qpsk_8_sps_fb_sync_2020_11_25/README.md) | PSK | 4 | none |
| [qpsk_demod_with_phase_noise](../modems/qpsk_demod_with_phase_noise/README.md) | PSK | 4 | none |
| [qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06](../modems/qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06/README.md) | PSK | 4 | none |
| [qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15](../modems/qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15/README.md) | PSK | 4 | none |
| [qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20](../modems/qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20/README.md) | PSK | 4 | none |
| [qpsk_phase_noise_phase_sync_2009_04_12](../modems/qpsk_phase_noise_phase_sync_2009_04_12/README.md) | PSK | 4 | none |
| [qpsk_script_basic](../modems/qpsk_script_basic/README.md) | PSK | 4 | none |
| [qpsk_script_costas](../modems/qpsk_script_costas/README.md) | PSK | 4 | none |
| [simo_maximal_ratio_combining_2010_08_27](../modems/simo_maximal_ratio_combining_2010_08_27/README.md) | PSK | 4 | none |

The separate [typed model catalog](TYPED_MODELS.md) includes OFDM and FSK modem workspaces plus synchronization, filtering, coding, MIMO, audio and array-processing algorithms. Their regression uses `tools/run_research.py`.

## Auxiliary archives

`DPD_Example`, `adaptdemos`, `ams_r2006a_2007a`, `polar_code`, `graphic_equalizer_16_band_2011_05_17` and `milewski_sequence_2011_05_19` are extracted under `sources`. They are supporting DSP, coding, analog or demonstration material, not additional modem workspaces. Their full conversion and testing is outside this modem implementation scope. `Modems` and `petrov_modems_electronix` are archive collections with duplicate modem archives.

Standalone CIC, decimator and stereo scripts remain in `arxiv`. Reference books remain in `matlab`. [The inventory](archive_inventory.json) records every unique archive, nested origin, duplicate alias and extracted file hash.
