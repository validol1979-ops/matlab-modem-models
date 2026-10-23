"""Собственная реализация модема psk8_fast_ff_nda_symbol_sync_fast_ff_nda_phase_sync_2006_11_15 на Python (NumPy, Matplotlib).

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
