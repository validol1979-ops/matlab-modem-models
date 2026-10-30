# Уже есть в проекте «Модемы» (не предлагать повторно)

## RTL rtl/common
alamouti_rx.sv axis_fifo.sv beamform.sv costas_loop.sv costas_stream.sv fft_delay.sv fft_r2sdf.sv fir_runtime.sv fsk_rx.sv fsk_tx.sv fxp_complex_add.sv fxp_complex_mul.sv fxp_divide_seq.sv fxp_mrc2.sv fxp_round_sat.sv fxp_stream_resize.sv gardner_timing.sv gf2_encoder.sv kalman_scalar.sv ldpc_decoder.sv lms_filter.sv mmse2.sv mmse3.sv mmse_n.sv norm_reciprocal.sv notch_iir.sv omlsa_gain.sv omlsa.sv pfb_analysis.sv reflect_pad.sv rls_filter.sv stft_analysis.sv stft_synthesis.sv 

## Модемы modems/
bpsk_costas_2008_08_25 catalog.json dqpsk_19_09_2006 dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12 fsk_text gmsk_coherent_demodulation_2010_10_03 msk_modulator_2008_06_22 ofdm_awgn oqpsk_2_sps_timing_recovery_2019_12_05 pi4_qpsk_8_sps_ff_sync_2021_05_27 pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15 psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15 psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19 QAM64_2008_11_21 qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18 qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26 qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10 qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21 qpsk_8_sps_fb_sync_2020_11_25 qpsk_demod_with_phase_noise qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06 qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15 qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20 qpsk_phase_noise_phase_sync_2009_04_12 qpsk_script_basic qpsk_script_costas simo_maximal_ratio_combining_2010_08_27 

## Алгоритмы algorithms/
algorithms/adaptive/lms_nlms_rls algorithms/arrays/beamforming algorithms/audio/omlsa algorithms/audio/stft algorithms/channelizers/pfb_wola algorithms/coding/ldpc algorithms/filters/oset algorithms/filters/windowed_sinc algorithms/mimo/dsplog algorithms/synchronization/symbol_timing algorithms/teaching/harger 

## Python-модели common/python
alamouti_widths.py beam_energy.py beam_fixed.py bpsk_fixed.py cic_compensation.py cic_model.py cic_reference.py cpm_fixed.py ext_advanced_arrays.py ext_advanced_cfo.py ext_advanced_channels.py ext_advanced_dpd.py ext_advanced_dynamics.py ext_advanced_eq.py ext_advanced_imcra_fixed.py ext_advanced_imcra.py ext_advanced_kalman.py ext_advanced_radar.py ext_advanced_sar.py ext_code_basics.py ext_code_bch.py ext_code_btc.py ext_code_gf.py ext_code_golay.py ext_code_llr.py ext_code_pls.py ext_code_polar.py ext_code_rs.py ext_code_tcm.py ext_code_trellis.py ext_code_turbo.py ext_signal_am.py ext_signal_core.py ext_signal_dct.py ext_signal_ddc.py ext_signal_farrow.py ext_signal_fm.py ext_signal_psd.py ext_signal_sos.py ext_signal_spectral.py ext_signal_ssb.py fft_fixed.py fifo_budget.py filter_references.py fir_fixed.py fir_widths.py fixed_point.py fsk_fixed.py gmsk_coherent.py istft_widths.py ldpc_fixed.py lms_energy.py lms_fixed.py lms_widths.py mmse2_widths.py mmse3_config_widths.py mmse3_fixed.py mmse3_widths.py mmse_fixed.py mmse_n_fixed.py mmse_norm_back_widths.py mmse_n_widths.py mmse_scale_update_widths.py modem_checks.py modem_core.py mrc_fixed.py ofdm_fixed.py omlsa_fixed.py omlsa_gain_widths.py oqpsk_fixed.py oset_fixed.py pfb_fixed.py pfb_widths.py psk_fixed.py rational_model.py research_core.py research_validate.py rls_fixed.py rls_update_widths.py rls_widths.py sat_diag.py stft_fixed.py sync_fixed.py 

## Задачи TODO (разделы 8–9, ID и заголовки)
DSP-CIC-DEC — Параметризованный CIC-дециматор (P1).
DSP-CIC-INT — Параметризованный CIC-интерполятор (P2).
DSP-DDS — Общий NCO/DDS с непрерывной фазой и runtime phase-step (P2).
DSP-CIC-COMP — Синтез коэффициентов CIC-droop compensation и проверяемый каскад CIC+FIR (P1).
DSP-RATIONAL — Общий полифазный преобразователь частоты P/Q (P1).
DSP-FARROW — Farrow-конвертер с произвольной дробной задержкой и меняющимся rate (P2).
DSP-HILBERT — Потоковый Hilbert/analytic-signal real→I/Q (P2).
DSP-SOS — Общий IIR biquad и каскад SOS с конфигурируемыми коэффициентами (P1).
DSP-PSD — Нормированный periodogram/PSD поверх существующего FFT (P2).
DSP-DDC — Составной цифровой down-converter DDS→CIC→2 half-band (P3).
MOD-AM — AM-модулятор и демодулятор огибающей (P2).
MOD-FM — FM-модулятор, discriminator и pre/de-emphasis (P2).
MOD-SSB — SSB USB/LSB модем с выбором боковой полосы (P2).
FEC-VIT — Свёрточный кодер и soft-input Viterbi K=7 (P2).
FEC-RS — Reed–Solomon encoder/decoder с error/erasure contract (P2).
FEC-BCH — BCH encoder/decoder с IBM/RIBM и Chien search (P2).
FEC-POLAR — Polar encoder/SC decoder с frozen map и optional CRC (P2).
FEC-TURBO — CCSDS Turbo encoder и Max-Log-MAP decoder (P2).
MOD-LLR — Soft LLR demapper и Gray mapper с явным адаптером к LDPC (P2).
MOD-TCM — 4D-TCM-8PSK coded mapper и Viterbi demodulator (P2).
DSP-DCT — DCT/IDCT и усечение коэффициентов аудиоблока (P2).
RF-DPD — DPD memory-polynomial: статический runtime и offline идентификация (P1).
ARRAY-MVDR — Ковариационный накопитель и MVDR/Capon веса (P1).
ARRAY-DOA — DOA estimation: MUSIC, затем ESPRIT (P2).
AUDIO-IMCRA — Адаптивный IMCRA noise-PSD tracker перед существующим OM-LSA gain (P1).
AUDIO-EQ16 — 16-band graphic EQ как synthesis extension PFB/WOLA (P2).
CHANNEL-AWGN — Генератор комплексного Gaussian/AWGN с управляемым seed и уровнем (P1).
CHANNEL-RAYLEIGH — Коррелированный Rayleigh/Doppler канал для проверки модемов (P2).
OFDM-CFO-ICI — Пилотная оценка CFO/ICI для OFDM: исследовательский модуль (P2).
FEC-CRC — Параметризованный CRC и проверка/формирование FCS (P1).
DSP-PRBS-SCRAMBLER — PRBS/LFSR, скремблер и дескремблер (P1).
FEC-DVB-PLS — DVB-S2 PLS: кодирование, scrambling, π/2-BPSK и Hadamard decoding (P2).
FEC-HAMMING — Расширенный Hamming SECDED encoder/decoder (P2).
FEC-GOLAY24 — Расширенный Golay(24,12,8): hard и soft Chase-II decoder (P2).
FEC-BTC — Блоковый произведённый код SPC/eHamming иитеративное soft decoding (P2).
DSP-FFT-CONV — Потоковая FFT overlap-save / overlap-add свёртка с произвольным размером блока (P1).
AUDIO-COMPLIMIT — Цифровой compressor/soft limiter с knee и attack/release (P2).
AUDIO-NOISEGATE — Noise gate с hysteresis, hold и плавным gain (P2).
RADAR-CHIRP — Параметрическая LFM/PLFM chirp-модель и генератор тестового эха (P2).
RADAR-PULSE-COMP — Согласованная фильтрация LFM и сжатие импульсов (P2).
RADAR-DOPPLER-MTI — Range–Doppler обработка и подавление неподвижного clutter (MTI) (P2).
RADAR-CFAR — Исследовательская модель CA-CFAR с контролем ложной тревоги (P3; сначала математическое ТЗ).
DSP-KALMAN-MATRIX — Матричный Kalman state-space estimator (P2).
SAR-OMEGA-K — Исследовательский Omega-K/Stolt SAR focusing (P3; сначала математическое ТЗ).

## Кандидаты прошлых обходов (task_catalog, task_additions)
- DSP-CIC-DEC | Параметризованный CIC-дециматор
- DSP-CIC-INT | Параметризованный CIC-интерполятор
- DSP-DDS | Общий NCO/DDS с непрерывной фазой и runtime phase-step
- DSP-CIC-COMP | Синтез коэффициентов CIC-droop compensation и проверяемый каскад CIC+FIR
- DSP-RATIONAL | Общий полифазный преобразователь частоты P/Q
- DSP-FARROW | Farrow-конвертер с произвольной дробной задержкой и меняющимся rate
- DSP-HILBERT | Потоковый Hilbert/analytic-signal real→I/Q
- DSP-SOS | Общий IIR biquad и каскад SOS с конфигурируемыми коэффициентами
- DSP-PSD | Нормированный periodogram/PSD поверх существующего FFT
- DSP-DDC | Составной цифровой down-converter DDS→CIC→2 half-band
- MOD-AM | AM-модулятор и демодулятор огибающей
- MOD-FM | FM-модулятор, discriminator и pre/de-emphasis
- MOD-SSB | SSB USB/LSB модем с выбором боковой полосы
- FEC-VIT | Свёрточный кодер и soft-input Viterbi K=7
- FEC-RS | Reed–Solomon encoder/decoder с error/erasure contract
- FEC-BCH | BCH encoder/decoder с IBM/RIBM и Chien search
- FEC-POLAR | Polar encoder/SC decoder с frozen map и optional CRC
- FEC-TURBO | CCSDS Turbo encoder и Max-Log-MAP decoder
- MOD-LLR | Soft LLR demapper и Gray mapper с явным адаптером к LDPC
- MOD-TCM | 4D-TCM-8PSK coded mapper и Viterbi demodulator
- DSP-DCT | DCT/IDCT и усечение коэффициентов аудиоблока
- RF-DPD | DPD memory-polynomial: статический runtime и offline идентификация
- ARRAY-MVDR | Ковариационный накопитель и MVDR/Capon веса
- ARRAY-DOA | DOA estimation: MUSIC, затем ESPRIT
- AUDIO-IMCRA | Адаптивный IMCRA noise-PSD tracker перед существующим OM-LSA gain
- AUDIO-EQ16 | 16-band graphic EQ как synthesis extension PFB/WOLA
- CHANNEL-AWGN | Генератор комплексного Gaussian/AWGN с управляемым seed и уровнем
- CHANNEL-RAYLEIGH | Коррелированный Rayleigh/Doppler канал для проверки модемов
- OFDM-CFO-ICI | Пилотная оценка CFO/ICI для OFDM: исследовательский модуль
- FEC-CRC | Параметризованный CRC и проверка/формирование FCS
- DSP-PRBS-SCRAMBLER | PRBS/LFSR, скремблер и дескремблер
- FEC-DVB-PLS | DVB-S2 PLS: кодирование, scrambling, π/2-BPSK и Hadamard decoding
- FEC-HAMMING | Расширенный Hamming SECDED encoder/decoder
- FEC-GOLAY24 | Расширенный Golay(24,12,8): hard и soft Chase-II decoder
- FEC-BTC | Блоковый произведённый код SPC/eHamming иитеративное soft decoding
- DSP-FFT-CONV | Потоковая FFT overlap-save / overlap-add свёртка с произвольным размером блока
- AUDIO-COMPLIMIT | Цифровой compressor/soft limiter с knee и attack/release
- AUDIO-NOISEGATE | Noise gate с hysteresis, hold и плавным gain
- RADAR-CHIRP | Параметрическая LFM/PLFM chirp-модель и генератор тестового эха
- RADAR-PULSE-COMP | Согласованная фильтрация LFM и сжатие импульсов
- RADAR-DOPPLER-MTI | Range–Doppler обработка и подавление неподвижного clutter (MTI)
- RADAR-CFAR | Исследовательская модель CA-CFAR с контролем ложной тревоги
- DSP-KALMAN-MATRIX | Матричный Kalman state-space estimator
- SAR-OMEGA-K | Исследовательский Omega-K/Stolt SAR focusing
