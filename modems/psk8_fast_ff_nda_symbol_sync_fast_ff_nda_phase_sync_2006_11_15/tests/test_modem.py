from pathlib import Path
import sys
import unittest

# Один контракт применяется ко всем вариантам с их собственными параметрами.
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "common" / "python"))
from modem_checks import ModemContract


class TestModem(ModemContract, unittest.TestCase):
    config_path = Path(__file__).resolve().parents[1] / "config.json"


if __name__ == "__main__":
    unittest.main(verbosity=2)
