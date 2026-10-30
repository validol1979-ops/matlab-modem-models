from pathlib import Path
import subprocess
import sys
import unittest
# Тест запускает все сценарии только этой модели.
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'tools/run_research.py').is_file())
class ModelTests(unittest.TestCase):
    def test_numeric_contract(self):
        subprocess.run([sys.executable,str(ROOT/'tools/run_research.py'),'--suite','python','--workspace','mimo/dsplog'],check=True)

if __name__=='__main__': unittest.main()
