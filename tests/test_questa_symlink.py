"""questa_paths() должен находить корень Questa сквозь симлинк vsim в PATH.

Закрывает дефект: Path.absolute() (или поиск самого глубокого совпадения) не
разрешает симлинк и/или ошибается на макете Siemens, где bin/vsim сам указывает
на ../vco/bin/vsim (вложенный bin), поэтому корень находился неверно.
"""
from pathlib import Path
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools')]
from regression_evidence import questa_paths


def _make_vendor_layout(root):
    """Корректная раскладка Questa: реальный бинарник в vco/bin, а bin/vsim - симлинк на него."""
    home = root / 'questa'
    (home / 'vco' / 'bin').mkdir(parents=True)
    real = home / 'vco' / 'bin' / 'vsim'
    real.write_text('#!/bin/sh\n')
    (home / 'bin').mkdir()
    (home / 'bin' / 'vsim').symlink_to(os.path.relpath(real, home / 'bin'))  # -> ../vco/bin/vsim
    return home


class QuestaSymlink(unittest.TestCase):
    def _run(self, which_target):
        with patch('regression_evidence.shutil.which', return_value=str(which_target)), \
             patch.dict('os.environ', {}, clear=True):
            return questa_paths()[0]

    def test_vsim_symlink_in_path_with_nested_vendor_bin(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = _make_vendor_layout(root)
            pathdir = root / 'pathbin'
            pathdir.mkdir()
            (pathdir / 'vsim').symlink_to(home / 'bin' / 'vsim')  # симлинк vsim в PATH
            self.assertEqual(self._run(pathdir / 'vsim'), home / 'bin')

    def test_vsim_symlink_in_path_plain_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / 'questa'
            (home / 'bin').mkdir(parents=True)
            (home / 'bin' / 'vsim').write_text('#!/bin/sh\n')
            pathdir = root / 'pathbin'
            pathdir.mkdir()
            (pathdir / 'vsim').symlink_to(home / 'bin' / 'vsim')  # абсолютный симлинк в PATH
            self.assertEqual(self._run(pathdir / 'vsim'), home / 'bin')


if __name__ == '__main__':
    unittest.main()
