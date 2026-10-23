"""Собственная реализация модема на Python: тот же сценарий, что и modem_own_demo.m.

Строит созвездия до и после петель приёмника, сходимость ошибки,
кривую SER(SNR) и сравнение с отключённым ключевым узлом приёмника.
"""
from pathlib import Path
import argparse
import json

import numpy as np

from modem_core import (load_config, transmit, channel, receive, constellation,
                        maximal_ratio_combine)

BASE = dict(gain=0.65, phase=0.38, frequency=0.00015, delay=2.25)
GAINS = np.array([0.2 + 0.3j, 1 - 0.4j])


def choose_scenario(cfg):
    if cfg['equalizer'] != 'none':
        off = dict(cfg, equalizer='none')
        return ('многолучевой канал (эхо 0.45 через символ)', dict(echo=0.45),
                dict(cfg=off, args=dict(echo=0.45), title='Эквалайзер', snr_db=28, single=False))
    if cfg['diversity_branches'] > 1:
        return ('две ветви приёма с разным замиранием, MRC', {},
                dict(cfg=cfg, args={}, title='Объединение MRC', snr_db=4, single=True))
    if cfg['variable_delay']:
        off = dict(cfg, timing='feedforward')
        return ('уход тактовой частоты 6e-4', dict(drift=0.0006),
                dict(cfg=off, args=dict(drift=0.0006), title='Петля Gardner', snr_db=28, single=False))
    if cfg['phase_noise']:
        return 'фазовый шум 3e-3 рад/отсчёт', dict(phase_noise=0.003), None
    return 'AWGN, задержка и сдвиг частоты', {}, None


def receive_case(cfg, tx, data, training, args, single=False):
    args = dict(args)
    if cfg['diversity_branches'] > 1:
        # Две ветви с разными комплексными коэффициентами и независимым шумом.
        snr = args.pop('snr_db', np.inf)
        seed = args.pop('seed', 7)
        clean = channel(cfg, tx['waveform'], **args)
        sigma = 0.0 if np.isinf(snr) else np.sqrt(np.mean(abs(clean) ** 2) / 10 ** (snr / 10) / 2)
        rng = np.random.default_rng(seed)
        noise = sigma * (rng.normal(size=(2, len(clean))) + 1j * rng.normal(size=(2, len(clean))))
        branches = GAINS[:, None] * clean + noise
        wave = branches[0] / GAINS[0] if single else maximal_ratio_combine(branches, GAINS)
    else:
        wave = channel(cfg, tx['waveform'], **args)
    return receive(cfg, wave, data[:training], len(data))


def run(folder, symbols=1536, training=192, snr_db=28, sweep=range(-10, 25, 2), plot=True, save=None):
    folder = Path(folder)
    cfg = load_config(folder / 'config.json')
    cpm = cfg['family'] in ('msk', 'gmsk')
    data = np.random.default_rng(19).integers(0, cfg['order'], symbols)
    tx = transmit(cfg, data)
    payload = slice(training, symbols)
    count = symbols - training

    scenario, extra, ablation = choose_scenario(cfg)
    rx = receive_case(cfg, tx, data, training, dict(BASE, **extra, snr_db=snr_db))
    errors = int(np.count_nonzero(rx['data'][payload] != data[payload]))

    sweep = list(sweep)
    ser = []
    for k, s in enumerate(sweep):
        r = receive_case(cfg, tx, data, training, dict(BASE, **extra, snr_db=s, seed=101 + k))
        ser.append(float(np.mean(r['data'][payload] != data[payload])))

    compare = None
    if ablation:
        a = dict(BASE, **ablation['args'], snr_db=ablation['snr_db'])
        on = receive_case(cfg, tx, data, training, a)
        off = receive_case(ablation['cfg'], tx, data, training, a, single=ablation['single'])
        compare = dict(title=ablation['title'], snr_db=ablation['snr_db'], on=on, off=off,
                       errors_on=int(np.count_nonzero(on['data'][payload] != data[payload])),
                       errors_off=int(np.count_nonzero(off['data'][payload] != data[payload])))

    report = dict(modem=cfg['name'], scenario=scenario, snr_db=snr_db, payload_symbols=count,
                  symbol_errors=errors, ser=errors / count, estimated_delay=float(rx['delay']),
                  estimated_frequency=float(rx['frequency']), sweep_snr_db=sweep, sweep_ser=ser)
    print(f"{cfg['name']}: {scenario}, SNR {snr_db} дБ, ошибок {errors} из {count} "
          f"(SER {errors / count:.2g}), задержка {rx['delay']:.2f}, сдвиг частоты {rx['frequency']:.2e}")
    if compare:
        report.update(ablation=compare['title'], errors_enabled=compare['errors_on'],
                      errors_disabled=compare['errors_off'])
        print(f"  {compare['title']} (SNR {compare['snr_db']} дБ): ошибок {compare['errors_on']} "
              f"с узлом, {compare['errors_off']} без него")
    if plot or save:
        draw(cfg, cpm, rx, payload, training, count, sweep, ser, compare, scenario, plot, save)
    return report


def show_points(ax, cpm, values):
    if cpm:
        ax.hist(np.real(values), 60)
        ax.set_xlabel('Набег фазы за символ, рад')
    else:
        ax.plot(values.real, values.imag, '.', markersize=3)
        r = 1.1 * np.max(abs(values))
        ax.set_xlim(-r, r); ax.set_ylim(-r, r); ax.set_aspect('equal')
        ax.set_xlabel('I'); ax.set_ylabel('Q')
    ax.grid(True)


def residual(cfg, cpm, values):
    if cpm:
        ideal = np.sign(values.real) * np.pi / 2
    else:
        table = constellation(cfg)
        ideal = table[np.argmin(abs(values[:, None] - table[None, :]) ** 2, axis=1)]
    return abs(values - ideal) ** 2


def draw(cfg, cpm, rx, payload, training, count, sweep, ser, compare, scenario, plot, save):
    import matplotlib
    if not plot:
        matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(2, 2, figsize=(10, 8))
    fig.suptitle(f'Канал: {scenario}')
    show_points(ax[0, 0], cpm, rx['synchronized'][payload])
    ax[0, 0].set_title('Вход петель:\nпосле оценки задержки и частоты')
    show_points(ax[0, 1], cpm, rx['symbols'][payload])
    ax[0, 1].set_title('Выход приёмника:\nпосле петель и АРУ')
    err = residual(cfg, cpm, np.asarray(rx['symbols']))
    ax[1, 0].plot(err, color=(0.2, 0.4, 0.8), linewidth=0.7)
    ax[1, 0].plot(np.convolve(err, np.ones(32) / 32, mode='same'), 'k', linewidth=1.5)
    ax[1, 0].axvline(training, color='r', linestyle='--')
    ax[1, 0].set_xlabel('Номер символа'); ax[1, 0].set_ylabel('|ошибка|²')
    ax[1, 0].set_title('Квадрат ошибки решения\n(пунктир - конец преамбулы)'); ax[1, 0].grid(True)
    ax[1, 1].semilogy(sweep, np.maximum(ser, 0.5 / count), 'o-')
    ax[1, 1].set_xlabel('SNR на отсчёт, дБ'); ax[1, 1].set_ylabel('SER')
    ax[1, 1].set_title('Вероятность ошибки на символ\n(нижняя граница - ошибок нет)')
    ax[1, 1].grid(True, which='both')
    fig.tight_layout()
    figs = [fig]
    if compare:
        fig2, ax2 = plt.subplots(1, 2, figsize=(10, 4.6))
        show_points(ax2[0], cpm, compare['on']['symbols'][payload])
        ax2[0].set_title(f"{compare['title']} включён\n{compare['errors_on']} ошибок, SNR {compare['snr_db']} дБ")
        show_points(ax2[1], cpm, compare['off']['symbols'][payload])
        ax2[1].set_title(f"{compare['title']} выключен\n{compare['errors_off']} ошибок, SNR {compare['snr_db']} дБ")
        fig2.tight_layout()
        figs.append(fig2)
    if save:
        Path(save).mkdir(parents=True, exist_ok=True)
        for k, f in enumerate(figs, 1):
            f.savefig(Path(save) / f'own_py_{k}.png', dpi=90)
    if plot:
        plt.show()
    else:
        plt.close('all')


def main(folder):
    parser = argparse.ArgumentParser(description='Собственная реализация модема на Python')
    parser.add_argument('--snr', type=float, default=28, help='SNR на отсчёт, дБ')
    parser.add_argument('--no-plot', action='store_true', help='только числа, без графиков')
    parser.add_argument('--save', metavar='DIR', help='сохранить графики PNG в папку')
    parser.add_argument('--json', action='store_true', help='вывести отчёт в JSON')
    a = parser.parse_args()
    report = run(folder, snr_db=a.snr, plot=not a.no_plot, save=a.save)
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    return report
