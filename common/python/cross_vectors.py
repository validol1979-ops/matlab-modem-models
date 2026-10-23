"""Векторы перекрёстной проверки Python и MATLAB/Octave.

Для каждого модема Python формирует данные и принятый сигнал в нескольких
каналах, сам их принимает и записывает результат в JSON. Затем
common/cross_check.m принимает тот же сигнал MATLAB-кодом и сравнивает.

    python common/python/cross_vectors.py [папка_вывода]
"""
from pathlib import Path
import json
import sys

import numpy as np

from modem_core import load_config, transmit, channel, receive, maximal_ratio_combine

ROOT = Path(__file__).resolve().parents[2]
CASES = [
    dict(snr_db=40),
    dict(snr_db=28, gain=0.65, phase=0.38, frequency=0.00015, delay=2.25),
    dict(snr_db=20, gain=1.3, phase=-1.1, frequency=-0.0002, delay=5.5),
]


def pack(values):
    values = np.asarray(values, complex)
    return dict(re=values.real.tolist(), im=values.imag.tolist())


def vectors(cfg):
    out = []
    for k, case in enumerate(CASES):
        data = np.random.default_rng(40 + k).integers(0, cfg['order'], 768)
        tx = transmit(cfg, data)
        wave = channel(cfg, tx['waveform'], seed=50 + k, **case)
        item = dict(data=data.tolist(), training=192, wave=pack(wave))
        if cfg['diversity_branches'] > 1:
            # Две ветви с разными коэффициентами; объединение MRC выполняет каждая сторона сама.
            gains = np.array([0.2 + 0.3j, 1 - 0.4j])
            second = channel(cfg, tx['waveform'], seed=60 + k, **case)
            branches = np.vstack([wave * gains[0], second * gains[1]])
            item.update(wave=pack(branches[0]), branch_b=pack(branches[1]), gains=pack(gains))
            wave = maximal_ratio_combine(branches, gains)
        rx = receive(cfg, wave, data[:192], len(data))
        item.update(tx=pack(tx['waveform']), rx_symbols=pack(rx['symbols']),
                    rx_data=np.asarray(rx['data']).astype(int).tolist(),
                    delay=float(rx['delay']), frequency=float(rx['frequency']))
        out.append(item)
    return out


def main():
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / 'cross_vectors'
    target.mkdir(parents=True, exist_ok=True)
    for folder in sorted((ROOT / 'modems').iterdir()):
        if not (folder / 'config.json').exists():
            continue
        cfg = load_config(folder / 'config.json')
        (target / f'{folder.name}.json').write_text(json.dumps(dict(name=folder.name, cases=vectors(cfg))))
        print(f'{folder.name}: {len(CASES)} сигнала')
    print(f'Векторы записаны в {target}')


if __name__ == '__main__':
    main()
