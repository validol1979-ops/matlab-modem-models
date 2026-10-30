from pathlib import Path
import sys
# Находим корень по общей библиотеке, независимо от глубины категории.
ROOT=next(p for p in Path(__file__).resolve().parents if (p/'common/python/research_core.py').is_file())
sys.path.insert(0,str(ROOT/'common/python'))
from research_core import run
