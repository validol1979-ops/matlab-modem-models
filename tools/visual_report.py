#!/usr/bin/env python3
"""Строим графики по настоящим тестовым векторам и сохранённым сигналам MATLAB."""
from pathlib import Path
from datetime import datetime, timezone
import argparse
from regression_evidence import require_pass
import csv
import hashlib
import json
import os
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault('MPLCONFIGDIR', str(ROOT / 'build' / 'matplotlib'))
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import ListedColormap
from matplotlib.ticker import MaxNLocator
import numpy as np
from scipy.io import loadmat
from scipy.signal import welch

sys.path.insert(0, str(ROOT / 'common' / 'python'))
from modem_core import transmit, receive, encode, channel, maximal_ratio_combine

BLUE, TEAL, ORANGE, RED, INK, MUTED = '#2563b9', '#087e74', '#c87517', '#c3423f', '#183247', '#5d7181'
ALIASES = {
    'QAM64_2008_11_21': '64-QAM · 2008',
    'bpsk_costas_2008_08_25': 'BPSK · Costas',
    'dqpsk_19_09_2006': '8-PSK · legacy DQPSK archive',
    'dqpsk_ff_symbol_farrow_sync_fast_agc_2008_05_12': 'DQPSK · Farrow / fast AGC',
    'gmsk_coherent_demodulation_2010_10_03': 'GMSK · coherent original',
    'msk_modulator_2008_06_22': 'MSK · modulator',
    'pi4_qpsk_8_sps_ff_sync_2021_05_27': 'Pi/4 QPSK · 8 SPS / 2021',
    'pi4_qpsk_feedforward_4_power_phase_sync_2010_07_15': 'Pi/4 QPSK · fourth-power sync',
    'psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15': '8-PSK · fast feedforward',
    'psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19': '8-PSK · feedback / AGC',
    'qam_fb_gardner_symbol_farrow_sync_fb_phase_sync_agc_2007_06_18': '16-QAM · Gardner / Farrow',
    'qam_fb_symbol_sync_fb_phase_sync_agc_dfe_2007_07_26': '16-QAM · decision feedback EQ',
    'qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_2007_07_10': '16-QAM · variable delay',
    'qam_fb_symbol_sync_fb_phase_sync_agc_var_ch_delay_eq_2007_07_21': '16-QAM · linear EQ',
    'qpsk_demod_with_phase_noise': 'QPSK · phase noise / Costas',
    'qpsk_fast_symbol_sync_fast_phase_sync_fast_agc_2007_03_06': 'QPSK · fast acquisition',
    'qpsk_fb_symbol_sync_fb_phase_sync_agc_2008_05_15': 'QPSK · feedback / AGC',
    'qpsk_ff_symbol_farrow_sync_ff_phase_sync_fast_agc_2007_05_20': 'QPSK · feedforward / Farrow',
    'qpsk_phase_noise_phase_sync_2009_04_12': 'QPSK · phase tracking',
    'simo_maximal_ratio_combining_2010_08_27': 'SIMO · maximal ratio combining',
}
CASE_NAMES = ['Clean channel', 'AWGN + carrier + delay', 'Variant stress channel']
plt.rcParams.update({'font.family': 'DejaVu Sans', 'font.size': 9, 'axes.titlesize': 11,
    'axes.labelcolor': MUTED, 'text.color': INK, 'axes.edgecolor': '#cfdae0',
    'xtick.color': MUTED, 'ytick.color': MUTED, 'axes.spines.top': False,
    'axes.spines.right': False, 'axes.grid': True, 'grid.color': '#e6edf1',
    'grid.linewidth': .65, 'axes.axisbelow': True, 'legend.frameon': False,
    'svg.fonttype': 'none', 'savefig.facecolor': 'white'})


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Report:
    def __init__(self, output):
        self.output = output
        self.output.mkdir(parents=True, exist_ok=True)
        self.evidence, self.assets, self.pages = {}, [], 0
        self.pdf = PdfPages(output / 'modem_test_report.pdf')
        self.pdf.infodict().update(Title='Modem verification atlas', Author='Modem project')

    def source(self, path):
        path = Path(path)
        self.evidence[str(path.relative_to(ROOT))] = sha(path)
        return path

    def json(self, path):
        return json.loads(self.source(path).read_text())

    def save(self, fig, stem, pdf=False):
        path = self.output / stem
        path.parent.mkdir(parents=True, exist_ok=True)
        for suffix in ['png', 'svg']:
            target = path.with_suffix('.' + suffix)
            fig.savefig(target, dpi=135)
            self.assets.append(str(target.relative_to(self.output)))
        if pdf:
            self.pdf.savefig(fig)
            self.pages += 1
        plt.close(fig)
        return dict(png=stem + '.png', svg=stem + '.svg')


def figure(title, subtitle, footer, shape=(2, 2)):
    fig, axes = plt.subplots(*shape, figsize=(15.2, 9.1), squeeze=False)
    fig.subplots_adjust(left=.072, right=.963, top=.835, bottom=.145, hspace=.50, wspace=.32)
    fig.text(.055, .96, title, fontsize=22, weight='bold', va='top')
    fig.text(.055, .908, subtitle, fontsize=10, color=MUTED, va='top')
    fig.text(.055, .045, textwrap.fill(footer, 172), fontsize=8, color=MUTED, va='bottom')
    return fig, axes.ravel()


def thin(x, limit=1200):
    x = np.asarray(x).ravel()
    return x[::max(1, int(np.ceil(len(x) / limit)))]


def iq(ax, samples, label, color=BLUE, limit=1400):
    z = thin(samples, limit)
    ax.scatter(z.real, z.imag, s=7, alpha=.4, c=color, linewidths=0, label=label, rasterized=True)
    ax.set(xlabel='In-phase', ylabel='Quadrature', aspect='equal')


def vector(path):
    values = np.fromstring(path.read_text(), sep=' ')
    assert np.all(np.isfinite(values)), path
    n, nr, nt, training, branches = values[:5].astype(int)
    pos = 5
    def take(count, complex_values=False):
        nonlocal pos
        size = count * (2 if complex_values else 1)
        data = values[pos:pos + size]
        assert len(data) == size, path
        pos += size
        return data[::2] + 1j * data[1::2] if complex_values else data
    data = take(n).astype(int)
    wave = take(nr, True)
    if branches == 2:
        second, gains = take(nr, True), take(2, True)
        wave = maximal_ratio_combine([wave, second], gains)
    tx, decoded, symbols = take(nt, True), take(n).astype(int), take(n, True)
    delay, frequency = take(2)
    assert pos == len(values), path
    return dict(data=data, wave=wave, tx=tx, decoded=decoded, symbols=symbols,
                training=training, branches=branches, delay=delay, frequency=frequency)


def metrics(cfg, v):
    start = v['training']
    truth, actual = v['data'][start:], v['decoded'][start:]
    errors = int(np.count_nonzero(truth != actual))
    bits = int(np.log2(cfg['order']))
    bit_errors = sum(int(a ^ b).bit_count() for a, b in zip(truth, actual))
    return dict(symbol_errors=errors, payload_symbols=len(truth), ser=errors/len(truth),
                bit_errors=bit_errors, payload_bits=len(truth)*bits, ber=bit_errors/(len(truth)*bits),
                delay_samples=float(v['delay']), frequency_cycles_per_sample=float(v['frequency']))


def portable_chart(cfg, v, case_name, parameters, negative=False):
    m = metrics(cfg, v)
    cpm = cfg['family'] in ('msk', 'gmsk')
    subtitle = f"PORTABLE MODEL  /  {case_name}  /  {m['symbol_errors']} errors in {m['payload_symbols']} payload symbols"
    source = ('Source: fresh Python negative control using a saved TX payload; numerical signals are in negative_control_data.npz. '
              if negative else 'Source: saved portable regression vectors, replayed with the current Python core. ')
    footer = (source +
              'The first 192 symbols are training and are excluded from BER/SER. Channel points are oversampled, '
              'not symbol decisions. Spectra share the TX peak reference. These figures do not establish original MATLAB receiver equivalence.')
    fig, ax = figure(ALIASES.get(cfg['name'], cfg['name'].replace('_', ' ')), subtitle, footer, (2, 3))
    n = min(24*cfg['sps'], len(v['tx']), len(v['wave']))
    time = np.arange(n)/cfg['sps']
    ax[0].plot(time, v['tx'][:n].real, color=BLUE, lw=1.1, label='TX I')
    ax[0].plot(time, v['tx'][:n].imag, color=TEAL, lw=1.0, alpha=.8, label='TX Q')
    ax[0].plot(time, v['wave'][:n].real, color=ORANGE, lw=.9, alpha=.8, label='Channel I')
    ax[0].set(title='Waveforms · first 24 symbols', xlabel='Time / symbol period', ylabel='Amplitude')
    ax[0].legend(loc='upper right', fontsize=8, ncol=3)
    iq(ax[1], v['wave'][v['training']*cfg['sps']:], 'Channel samples', ORANGE)
    ax[1].set_title('Combined SIMO input' if v['branches'] == 2 else 'Channel I/Q cloud')
    start = v['training']
    if cpm:
        values = v['symbols'][start:].real
        for bit, color in [(0, BLUE), (1, TEAL)]:
            ax[2].hist(values[v['data'][start:] == bit], bins=22, alpha=.65, color=color, label=f'TX bit {bit}')
        ax[2].axvline(0, color=RED, ls='--', lw=1, label='Decision threshold')
        ax[2].set(title='Receiver discriminator', xlabel='Integrated phase change / rad', ylabel='Symbol count')
        target = (2*v['data']-1)*np.pi/2
        error = abs(v['symbols'].real-target)
        error_label = 'Phase increment error / rad'
    else:
        iq(ax[2], v['symbols'][start:], 'Recovered symbols', BLUE)
        table = np.asarray(cfg['constellation']); table = table[:, 0]+1j*table[:, 1]
        ax[2].scatter(table.real, table.imag, s=60, facecolors='none', edgecolors=INK, lw=.9, label='Ideal alphabet')
        ax[2].set_title('Recovered constellation · payload')
        target = encode(cfg, v['data'])[1]
        error = abs(v['symbols']-target)/np.sqrt(np.mean(abs(target)**2))
        error_label = 'Error / RMS ideal symbol'
    ax[2].legend(fontsize=7, loc='best')
    spectra = []
    for wave in [v['tx'], v['wave']]:
        f, psd = welch(wave, fs=cfg['sps'], nperseg=min(512, len(wave)),
                       return_onesided=False, detrend=False, scaling='density')
        spectra.append((np.fft.fftshift(f), np.fft.fftshift(psd)))
    reference = max(spectra[0][1])
    for (f, psd), color, label in zip(spectra, [BLUE, ORANGE], ['TX', 'Channel']):
        ax[3].plot(f, 10*np.log10(np.maximum(psd/reference, 1e-14)), color=color, lw=1, label=label)
    ax[3].set(title='Power spectral density', xlabel='Frequency / symbol rate', ylabel='dB relative to TX peak', ylim=(-100, 6))
    ax[3].legend(fontsize=8)
    ax[4].plot(error, color=TEAL, lw=.75)
    ax[4].axvspan(0, start, color='#e5edf3', zorder=0)
    ax[4].axvline(start, color=MUTED, ls=':', lw=.8)
    ax[4].set(title='Symbol estimate error', xlabel='Symbol index · shaded = training', ylabel=error_label)
    interval = np.arange(start, min(start+64, len(v['data'])))
    ax[5].step(interval, v['data'][interval], where='mid', color=INK, lw=2.2, alpha=.35, label='Transmitted')
    ax[5].step(interval, v['decoded'][interval], where='mid', color=BLUE, lw=1.0, ls='--', label='Decoded')
    bad = interval[v['data'][interval] != v['decoded'][interval]]
    if len(bad):
        ax[5].scatter(bad, v['decoded'][bad], c=RED, marker='x', s=28, label='Error')
    ax[5].set(title='Decoded labels · first 64 payload symbols', xlabel='Symbol index', ylabel='Integer label', ylim=(-.5, cfg['order']-.5))
    ax[5].yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    ax[5].legend(fontsize=7)
    m.update(parameters=parameters, case=case_name)
    return fig, m


def trace_series(trace):
    t, data = np.asarray(trace['time']).ravel(), np.asarray(trace['data'])
    if data.ndim == 1:
        data = data[:, None]
    elif data.shape[0] != len(t) and data.shape[-1] == len(t):
        data = np.moveaxis(data, -1, 0)
    assert data.shape[0] == len(t), trace['block']
    return t, data.reshape(len(t), -1)[:, 0]


def original_chart(cfg, traces, result):
    top = {s['block'].split('/', 1)[1]: s for s in traces if s['port'] == 1 and s['block'].count('/') == 1}
    if cfg['name'] == 'msk_modulator_2008_06_22':
        tx_name, rx_name = 'Math Function1', None
    elif cfg['name'] == 'qpsk_demod_with_phase_noise':
        tx_name, rx_name = 'source', 'Product'
    else:
        tx_name = next(name for name in top if name.lower().startswith('modulator'))
        rx_name = next((name for name in top if 'clock_domain' in name), None)
        if rx_name is None:
            rx_name = 'Enabled Subsystem' if 'Enabled Subsystem' in top else 'Product'
    tt, tx = trace_series(top[tx_name])
    subtitle = f"ORIGINAL MATLAB CAPTURE  /  runtime PASS  /  exact repeat PASS  /  solver: {result['solver']}"
    footer = ('Actual R2020b signals with documented runtime settings. Native receiver monitors can contain '
              'held or oversampled values; their point clouds are not a BER measurement. Time is in the model\'s units. '
              'Simulation and repeatability do not establish receiver equivalence. Model: '+cfg['name'])
    fig, ax = figure(ALIASES.get(cfg['name'], cfg['name'].replace('_', ' ')), subtitle, footer)
    n = min(384, len(tt))
    ax[0].plot(tt[:n], tx[:n].real, color=BLUE, label='I', lw=1)
    ax[0].plot(tt[:n], tx[:n].imag, color=TEAL, label='Q', lw=1)
    ax[0].set(title=f'Transmitter · {tx_name}', xlabel='Model time', ylabel='Amplitude')
    ax[0].legend(ncol=2)
    stride = max(1, len(tt)//2500)
    ax[1].plot(tt[::stride], abs(tx[::stride]), color=BLUE, lw=.6)
    ax[1].set(title='Transmitter envelope · entire capture', xlabel='Model time', ylabel='Magnitude')
    if rx_name:
        rt, rx = trace_series(top[rx_name])
        if np.iscomplexobj(rx) and np.any(rx.imag != 0):
            iq(ax[2], rx[len(rx)//2:], 'Second half of capture')
            ax[2].set_title(f'Receiver monitor · {rx_name}', fontsize=10)
        else:
            # Скалярный выход контура не является комплексным созвездием.
            stride = max(1, len(rt)//2000)
            ax[2].plot(rt[::stride], rx.real[::stride], color=TEAL, lw=.7)
            ax[2].set(title=f'Real control monitor · {rx_name}', xlabel='Model time', ylabel='Control value')
    else:
        iq(ax[2], tx, 'MSK waveform', TEAL)
        ax[2].set_title('TX phase portrait · modulator-only source')
    by_name = {s['name']: s for s in traces}
    mappers = result.get('mapper_ports', [])
    if mappers:
        points = np.asarray(by_name[mappers[0]['output']]['data']).ravel()
        if cfg['name'] == 'QAM64_2008_11_21':
            real = next(m for m in mappers if m['block'].endswith(' RE'))
            imag = next(m for m in mappers if m['block'].endswith(' IM'))
            points = np.asarray(by_name[real['output']]['data']).ravel()+1j*np.asarray(by_name[imag['output']]['data']).ravel()
        table = np.asarray(cfg['constellation']); table = table[:, 0]+1j*table[:, 1]
        iq(ax[3], points, 'MATLAB mapper', TEAL)
        ax[3].scatter(table.real, table.imag, s=100, facecolors='none', edgecolors=INK, label='Portable table')
        ax[3].set_title('Original mapper vs portable alphabet')
        ax[3].legend(fontsize=8)
    else:
        n = min(512, len(tx))
        ax[3].plot(tx[:n].real, tx[:n].imag, color=TEAL, lw=.7, alpha=.85)
        ax[3].set(title='TX I/Q trajectory · first 512 samples', xlabel='In-phase', ylabel='Quadrature', aspect='equal')
    return fig, dict(tx_monitor=tx_name, rx_monitor=rx_name, captured_samples=len(tt))


def overview_chart(models, portable, native):
    fig, ax = plt.subplots(figsize=(15.2, 10.8))
    fig.subplots_adjust(left=.275, right=.96, bottom=.16, top=.83)
    columns = ['Original\ncompile', 'Adapted\nMATLAB run', 'Exact\nrepeat', 'Portable\n3 cases', 'Portable\nUVM', 'Mapper\nreference', 'MSK TX\nreference', 'Full RX\nequivalence']
    rows, labels = [], []
    for m in models:
        n = native[m['name']]
        rows.append([2 if n['original_compile'] == 'PASS' else 1, 2, 2, 2, 2,
                     2 if n['mapper_checks'] else 0, 3 if m['name'].startswith('msk_') else 0, 0])
        labels.append(m['label'])
    ax.imshow(rows, aspect='auto', cmap=ListedColormap(['#eaf0f3', '#f8dfaf', '#c7e9de', '#c8dff5']), vmin=0, vmax=3)
    ax.set_xticks(range(len(columns)), columns, fontsize=9)
    ax.xaxis.tick_top()
    ax.set_yticks(range(len(labels)), labels, fontsize=9)
    ax.grid(False)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            text = ['—', 'UPDATE', 'PASS', 'TX ONLY'][value]
            ax.text(c, r, text, ha='center', va='center', fontsize=8, weight='bold', color=INK)
    for y in np.arange(-.5, len(rows), 1): ax.axhline(y, color='white', lw=2)
    for x in np.arange(-.5, len(columns), 1): ax.axvline(x, color='white', lw=2)
    fig.text(.055, .956, 'Modem verification · coverage map', fontsize=25, weight='bold')
    fig.text(.055, .914, '20 original models  /  60 portable channel cases  /  17 mapper blocks  /  1 transmitter reference', color=MUTED, fontsize=12)
    fig.text(.055, .055, 'PASS applies only to the named check. UPDATE means the original requires compatibility changes in R2020b.\n'
             'Gray cells are not established or not tested; the MSK reference covers TX after its scrambler at 32 samples/symbol.\n'
             'Portable UVM checks agreement with Python. Original receiver correctness and complete historical equivalence remain unverified.', fontsize=10, color=MUTED)
    return fig


def qpsk_chart(traces, diagnostic):
    signals = {s['block'].split('/', 1)[1]: s for s in traces}
    tx, rx = np.asarray(signals['From4']['data']).ravel().astype(int), np.asarray(signals['From5']['data']).ravel().astype(int)
    delay, offset = diagnostic['delay_symbols'], diagnostic['inferred_label_offset_modulo_4']
    tx, rx = tx[:-delay], rx[delay:]
    mid = len(tx)//2
    a, b = tx[mid:], rx[mid:]
    corrected = (b-offset) % 4
    assert np.count_nonzero(a != corrected) == diagnostic['held_out_errors_after_offset']
    footer = (f'Source: original MATLAB QPSK phase-noise capture. Delay {delay} comes from the archived error counter. '
              f'Offset {offset} modulo four was inferred before the held-out interval. The correction below is diagnostic only; '
              'it was not inserted into the receiver. The original counter reports 10910/10910 symbol errors.')
    fig, axes = figure('QPSK · expose the phase ambiguity',
        f'HELD-OUT CAPTURE  /  {len(a)} symbols  /  raw SER {np.mean(a != b):.0%}  /  corrected diagnostic SER {np.mean(a != corrected):.0%}', footer)
    for ax, actual, title in [(axes[0], b, 'Raw labels · off-diagonal = wrong'),
                              (axes[1], corrected, 'Diagnostic phase correction · diagonal = match')]:
        counts = np.zeros((4, 4), int)
        np.add.at(counts, (a, actual), 1)
        ax.imshow(counts, cmap='Blues', vmin=0, vmax=max(1, counts.max()))
        for i in range(4):
            for j in range(4): ax.text(j, i, str(counts[i, j]), ha='center', va='center', color='white' if counts[i,j] > counts.max()/2 else INK)
        ax.set(title=title, xlabel='Received label', ylabel='Transmitted label', xticks=range(4), yticks=range(4))
        ax.grid(False)
    x = np.arange(mid, mid+32)
    for ax, actual, color, title in [(axes[2], b, ORANGE, 'Raw label sequence'),
                                    (axes[3], corrected, TEAL, 'After diagnostic label rotation')]:
        ax.step(x, a[:32], where='mid', color=INK, alpha=.35, lw=3, label='TX')
        ax.step(x, actual[:32], where='mid', color=color, ls='--', lw=1.2, label='RX')
        ax.set(title=title, xlabel='Aligned symbol index', ylabel='Label', yticks=range(4))
        ax.legend(ncol=2)
    return fig


def msk_chart(report, root):
    reference = np.loadtxt(root / 'matlab_tx.txt'); reference = reference[:, 0]+1j*reference[:, 1]
    cfg = json.loads((root / 'config.json').read_text())
    bits = np.loadtxt(root / 'data.txt', dtype=int)
    actual = transmit(cfg, bits)['waveform']
    errors = abs(reference-actual)
    assert len(errors) == report['msk_reference']['samples']
    assert max(errors) < 1e-9, 'MSK reference mismatch'
    assert np.isclose(max(errors), report['msk_reference']['python_maximum_error'], rtol=1e-6, atol=1e-18)
    footer = ('Source: actual MATLAB MSK samples after the original scrambler; 511 captured bits, 32 samples/symbol, '
              'fixed 33-sample startup alignment. No fitted gain or phase. Zero errors are plotted at 1e-18 on the log axis. '
              'The SystemVerilog maximum is from the recorded UVM run and includes Python-based RX comparisons.')
    fig, ax = figure('MSK · original waveform agreement',
        f"MATLAB REFERENCE  /  {len(errors):,} samples  /  maximum TX error {max(errors):.3g}", footer)
    x = np.arange(256)/32
    ax[0].plot(x, reference[:256].real, color=INK, lw=3, alpha=.35, label='MATLAB I')
    ax[0].plot(x, actual[:256].real, color=BLUE, ls='--', lw=1.2, label='Python I')
    ax[0].set(title='Aligned real waveform', xlabel='Time / symbol period', ylabel='Amplitude')
    ax[0].legend()
    ax[1].plot(x, reference[:256].imag, color=INK, lw=3, alpha=.35, label='MATLAB Q')
    ax[1].plot(x, actual[:256].imag, color=TEAL, ls='--', lw=1.2, label='Python Q')
    ax[1].set(title='Aligned imaginary waveform', xlabel='Time / symbol period', ylabel='Amplitude')
    ax[1].legend()
    ax[2].semilogy(np.maximum(errors, 1e-18), color=BLUE, lw=.7)
    ax[2].axhline(1e-9, color=ORANGE, ls='--', label='Python / Octave tolerance')
    ax[2].set(title='Absolute error · all captured samples', xlabel='Aligned sample index', ylabel='Complex sample error', ylim=(5e-19, 1e-8))
    ax[2].legend(fontsize=8)
    values = [report['msk_reference']['python_maximum_error'], report['msk_reference']['octave_maximum_error'], report['msk_uvm']['maximum_error']]
    ax[3].bar(['Python TX', 'Octave TX', 'SystemVerilog UVM'], values, color=[BLUE, TEAL, '#748ac7'])
    ax[3].set(title='Recorded maximum differences', ylabel='Maximum absolute difference', ylim=(0, max(values)*1.4))
    ax[3].ticklabel_format(axis='y', style='sci', scilimits=(0, 0))
    for i, value in enumerate(values): ax[3].text(i, value*1.04, f'{value:.3g}', ha='center', fontsize=9)
    return fig


def main():
    from regression_evidence import require_unoptimized
    require_unoptimized()
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, default=ROOT / 'docs' / 'visual')
    args = parser.parse_args()
    report = Report(args.output.resolve())
    portable = report.json(ROOT / 'docs' / 'verification_results.json')
    for evidence in [portable['python'],portable['cross'],*portable['hdl']]: require_pass(evidence, ROOT)
    native = report.json(ROOT / 'docs' / 'matlab_reference_results.json')
    for evidence in native['run_evidence'].values(): require_pass(evidence, ROOT)
    require_pass(native['msk_reference'], ROOT)
    require_pass(native['msk_uvm'], ROOT)
    native_by_name = {r['name']: r for r in native['models']}
    hdl = {r['modem']: r for r in portable['hdl']}
    models, captures = [], {}
    for path in sorted((ROOT / 'modems').glob('*/config.json')):
        # Атлас исторической подборки сохраняет область исходных двадцати схем.
        if path.parent.name not in native_by_name:
            continue
        cfg = report.json(path)
        name = cfg['name']
        # Старые результаты можно подписывать только при совпадении проверенных реализаций.
        for p in [path, ROOT/'common/python/modem_core.py', ROOT/'common/octave/modem_core.m', ROOT/'common/sv/modem_dsp_pkg.sv']:
            key = str(p.relative_to(ROOT))
            assert sha(p) == portable['source_hashes'][key], f'Stale portable evidence: {key}'
            report.source(p)
        assert hdl[name]['status'] == 'PASS'
        manifest = report.json(ROOT/'build/vectors'/name/'manifest.json')
        cases = []
        for number in range(3):
            v = vector(report.source(ROOT/'build/vectors'/name/f'case_{number}.txt'))
            computed_tx = transmit(cfg, v['data'])['waveform']
            replay = receive(cfg, v['wave'], v['data'][:v['training']], len(v['data']))
            assert np.allclose(computed_tx, v['tx'], rtol=0, atol=1e-12), name
            assert np.array_equal(replay['data'], v['decoded']), name
            assert np.allclose(replay['symbols'], v['symbols'], rtol=0, atol=1e-10), name
            fig, m = portable_chart(cfg, v, CASE_NAMES[number], manifest[number]['channel'])
            assert m['symbol_errors'] == manifest[number]['payload_errors'] == 0, 'Stale passing case evidence'
            m.update(report.save(fig, f'portable/{name}/case_{number}', pdf=False))
            cases.append(m)
        record = report.json(ROOT/'build/matlab_originals/compatible'/name/'result.json')
        capture = report.source(ROOT/'build/matlab_originals/compatible'/name/'signals.mat')
        assert sha(capture) == native_by_name[name]['capture_sha256'], f'Stale MATLAB evidence: {name}'
        assert record['simulation_status'] == record['repeat_status'] == 'PASS'
        traces = loadmat(capture, simplify_cells=True)['traces']
        captures[name] = (cfg, traces, record)
        n = native_by_name[name]
        models.append(dict(name=name, label=ALIASES[name], family=cfg['family'].upper(), order=cfg['order'],
            equalizer=cfg['equalizer'], cases=cases, native_original_compile=n['original_compile'],
            native_runtime=n['runtime_status'], native_repeat=n['repeat_status'],
            mapper_blocks=len(n['mapper_checks']), uvm=hdl[name],
            runtime_changes=n['runtime_changes'], library_changes=n['migration']['changes']))
        print(f'PASS visual replay {name}: 3 portable cases and MATLAB capture verified', flush=True)
    overview = report.save(overview_chart(models, portable, native_by_name), 'overview', pdf=True)
    qpsk_name = 'qpsk_demod_with_phase_noise'
    diagnostic = native_by_name[qpsk_name]['receiver_diagnostic']
    qpsk = report.save(qpsk_chart(captures[qpsk_name][1], diagnostic), 'qpsk_phase_ambiguity', pdf=True)
    msk_root = ROOT/'build/matlab_msk_reference'
    for f in ['matlab_tx.txt', 'config.json', 'data.txt', 'reference.json', 'octave.log']:
        report.source(msk_root/f)
    msk = report.save(msk_chart(native, msk_root), 'msk_reference', pdf=True)
    # Намеренно плохой канал служит наглядным контролем чувствительности теста.
    cfg = captures['bpsk_costas_2008_08_25'][0]
    v = vector(ROOT/'build/vectors'/cfg['name']/'case_0.txt')
    parameters = dict(snr_db=-8, gain=.65, phase=.38, frequency=.00015, delay=2.25)
    wave = channel(cfg, v['tx'], seed=29, **parameters)
    rx = receive(cfg, wave, v['data'][:192], len(v['data']))
    v.update(wave=wave, decoded=rx['data'], symbols=rx['symbols'], delay=rx['delay'], frequency=rx['frequency'])
    fig, stress = portable_chart(cfg, v, 'Negative control · -8 dB sample SNR', parameters, negative=True)
    assert stress['symbol_errors'] > 0, 'Negative control did not produce errors'
    stress.update(report.save(fig, 'negative_control', pdf=True))
    np.savez_compressed(report.output/'negative_control_data.npz', **{k: v[k] for k in ['data', 'tx', 'wave', 'decoded', 'symbols']})
    for model in models:
        name = model['name']
        cfg, traces, record = captures[name]
        fig, info = original_chart(cfg, traces, record)
        info.update(report.save(fig, f'matlab/{name}', pdf=True))
        model['matlab'] = info
        v = vector(ROOT/'build/vectors'/name/'case_2.txt')
        fig, _ = portable_chart(cfg, v, CASE_NAMES[2], model['cases'][2]['parameters'])
        report.pdf.savefig(fig); report.pages += 1; plt.close(fig)
        print(f'PLOTTED original MATLAB {name}', flush=True)
    report.pdf.close()
    data = dict(generated_utc=datetime.now(timezone.utc).isoformat(), models=models, overview=overview,
        qpsk=qpsk, qpsk_diagnostic=diagnostic, msk=msk, msk_reference=native['msk_reference'],
        msk_uvm=native['msk_uvm'], stress=stress, pdf_pages=report.pages,
        portable_recorded_utc=portable['recorded_utc'], matlab_recorded_utc=native['captured_at_utc'],
        python_tests=portable['python']['python_tests'], portable_uvm_frames=sum(x['frames'] for x in portable['hdl']),
        full_equivalence='NOT_ESTABLISHED')
    template = ROOT/'tools/visual_report_assets'
    for f in ['report.css', 'report.js']:
        (report.output/f).write_bytes(report.source(template/f).read_bytes())
    html = report.source(template/'index.html').read_text()
    html = html.replace('__REPORT_DATA__', json.dumps(data, ensure_ascii=False).replace('</', '<\\/'))
    (report.output/'index.html').write_text(html)
    report.source(Path(__file__))
    (report.output/'report_data.json').write_text(json.dumps(data, indent=2, ensure_ascii=False)+'\n')
    (report.output/'provenance.json').write_text(json.dumps(dict(generated_utc=data['generated_utc'],
        source_sha256=report.evidence, output_sha256={f: sha(report.output/f) for f in report.assets},
        scope='60 saved portable cases replayed; native MATLAB captures verified by hash; no MATLAB or UVM rerun by this renderer.'), indent=2)+'\n')
    with (report.output/'summary.csv').open('w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['modem', 'case', 'payload_symbols', 'symbol_errors', 'SER', 'BER', 'matlab_runtime', 'matlab_repeat', 'mapper_blocks'])
        for m in models:
            for c in m['cases']:
                writer.writerow([m['name'], c['case'], c['payload_symbols'], c['symbol_errors'], c['ser'], c['ber'], m['native_runtime'], m['native_repeat'], m['mapper_blocks']])
    print(f'PASS visual report: {len(models)} models, {len(report.assets)//2} figures, {report.pages} PDF pages')
    print(report.output/'index.html')


if __name__ == '__main__':
    main()
