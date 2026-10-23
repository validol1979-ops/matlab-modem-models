"""Собственная реализация модема psk8_fb_symbol_sync_fb_phase_sync_agc_2009_08_19 на Python (NumPy, Matplotlib).

    python run_own.py              демонстрация с графиками
    python run_own.py --snr 12     свой SNR на отсчёт, дБ
    python run_own.py --no-plot    только числа
"""
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'common' / 'python'))
from modem_own_demo import main

if __name__ == '__main__':
    main(HERE)
