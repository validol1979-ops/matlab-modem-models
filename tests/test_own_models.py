"""Автономные демонстрации модемов и перекрёстная проверка Python/Octave."""
from pathlib import Path
import contextlib
import io
import json
import math
import runpy
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
OWN = ROOT / 'common' / 'own'
sys.path.insert(0, str(OWN / 'python'))
from own_core import load_config, transmit


class TestOwnModels(unittest.TestCase):
    def test_entry_points_and_readme(self):
        matlab = {p.parent for p in (ROOT / 'modems').glob('*/run_own.m')}
        python = {p.parent for p in (ROOT / 'modems').glob('*/run_own.py')}
        self.assertTrue(matlab, 'No autonomous modem entry points found')
        self.assertEqual(matlab, python)
        for folder in sorted(matlab):
            with self.subTest(modem=folder.name):
                for name in ('config.json', 'run_own.py', 'run_demo.m', 'README.md'):
                    self.assertTrue((folder / name).is_file(), str(folder / name))
                self.assertTrue((folder / 'images').is_dir())
                self.assertIn('run_own', (folder / 'README.md').read_text())

    def test_python_main_without_plots(self):
        entries = sorted((ROOT / 'modems').glob('*/run_own.py'))
        self.assertTrue(entries, 'No autonomous Python modems found')
        for entry in entries:
            with self.subTest(modem=entry.parent.name):
                # Выполняем обёртку и её main, сохраняя список путей других тестов.
                with patch.object(sys, 'path', sys.path.copy()):
                    module = runpy.run_path(str(entry))
                    output = io.StringIO()
                    with contextlib.redirect_stdout(output):
                        report = module['main'](module['HERE'], [
                            '--no-plot', '--json', '--sweep', '-10', '10', '24'])
                printed = json.loads(output.getvalue()[output.getvalue().index('{'):])
                self.assertEqual(printed, report)
                self.assertEqual(report['modem'], entry.parent.name)
                self.assertEqual(report['payload_symbols'], 1536 - 192)
                self.assertEqual(report['snr_db'], 28)
                count, errors = report['payload_symbols'], report['symbol_errors']
                self.assertGreaterEqual(errors, 0)
                self.assertLessEqual(errors, count)
                self.assertAlmostEqual(report['ser'], errors / count)
                self.assertLessEqual(report['ser'], 0.01)
                self.assertEqual(report['sweep_snr_db'], [-10, 10, 24])
                self.assertEqual(len(report['sweep_ser']), 3)
                for ser in report['sweep_ser']:
                    self.assertTrue(math.isfinite(ser))
                    self.assertGreaterEqual(ser, 0)
                    self.assertLessEqual(ser, 1)
                # Шумовой контроль обнаруживает деградацию, высокий SNR восстанавливает кадр.
                self.assertGreater(report['sweep_ser'][0], report['sweep_ser'][-1] + 0.1)
                self.assertLessEqual(report['sweep_ser'][-1], 0.01)
                self.assertTrue(math.isfinite(report['estimated_delay']))
                self.assertGreaterEqual(report['estimated_delay'], 0)
                self.assertLess(report['estimated_delay'], 100)
                self.assertTrue(math.isfinite(report['estimated_frequency']))
                self.assertLess(abs(report['estimated_frequency']), 0.005)
                if 'ablation' in report:
                    self.assertGreaterEqual(report['errors_enabled'], 0)
                    self.assertLess(report['errors_enabled'], report['errors_disabled'])
                    self.assertLessEqual(report['errors_disabled'], count)

    def test_source_metadata_does_not_change_transmit(self):
        for entry in sorted((ROOT / 'modems').glob('*/run_own.py')):
            with self.subTest(modem=entry.parent.name):
                cfg = load_config(entry.parent / 'config.json')
                # Поля происхождения не участвуют в численном алгоритме.
                stripped = {k: v for k, v in cfg.items() if k not in ('source', 'source_sha256')}
                data = np.arange(16) % cfg['order']
                np.testing.assert_array_equal(transmit(cfg, data)['waveform'],
                                              transmit(stripped, data)['waveform'])

    def test_python_octave_cross_check(self):
        octave = shutil.which('octave-cli')
        if octave is None:
            self.skipTest('octave-cli is not installed; Python/Octave own-model cross-check requires GNU Octave')
        entries = sorted((ROOT / 'modems').glob('*/run_own.py'))
        self.assertTrue(entries, 'No autonomous modems for cross-check')
        with tempfile.TemporaryDirectory(prefix='own_cross_') as temporary:
            target = Path(temporary) / 'vectors'
            generated = subprocess.run([
                sys.executable, str(OWN / 'python' / 'own_cross_vectors.py'), str(target)],
                cwd=temporary, capture_output=True, text=True, timeout=180)
            self.assertEqual(generated.returncode, 0, generated.stdout + generated.stderr)
            self.assertEqual({p.stem for p in target.glob('*.json')},
                             {p.parent.name for p in entries})
            for vector in target.glob('*.json'):
                self.assertEqual(len(json.loads(vector.read_text())['cases']), 3)
            quote = lambda path: str(path).replace("'", "''")
            checked = subprocess.run([
                octave, '--quiet', '--eval',
                f"addpath('{quote(OWN)}'); assert(own_cross_check('{quote(target)}'));"],
                cwd=temporary, capture_output=True, text=True, timeout=180)
            self.assertEqual(checked.returncode, 0, checked.stdout + checked.stderr)
            passed = [line for line in checked.stdout.splitlines() if line.startswith('PASS ')]
            self.assertEqual(len(passed), len(entries), checked.stdout)


if __name__ == '__main__':
    unittest.main(verbosity=2)
