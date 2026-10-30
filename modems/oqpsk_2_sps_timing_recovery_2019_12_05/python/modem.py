from pathlib import Path
import sys

# Общая реализация получает параметры именно этого исходного модема.
DIRECTORY = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(DIRECTORY.parents[1] / "common" / "python"))
from modem_core import load_config, transmit, receive, run_demo

CONFIG = load_config(DIRECTORY / "config.json")

if __name__ == "__main__":
    run_demo(CONFIG)
