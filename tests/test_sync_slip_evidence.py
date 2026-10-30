"""RTL trajectory evidence must reject truncation and a falsely corrected quadrant."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from sync_scenarios import costas_slip_scenario
from sync_slip_evidence import check_costas_slip


class SyncSlipEvidence(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        _, values, phases, _, reference, disabled = costas_slip_scenario()
        self.rows = [(re, im, phase, int(index == len(phases)-1))
                     for index, ((re, im), phase) in enumerate(zip(values, phases))]
        body = self._body(self.rows)
        (self.folder/'cl_out.txt').write_text(f'{len(phases)}\n'+body)
        self.observed = self.folder/'observed.txt'
        self.observed.write_text(body)
        (self.folder/'cl_slip_reference.txt').write_text(
            f'{len(reference)}\n'+'\n'.join(map(str, reference))+'\n')
        (self.folder/'cl_slip_disabled.txt').write_text(
            f'{len(disabled)}\n'+'\n'.join(map(str, disabled))+'\n')
        (self.folder/'cl_slip.json').write_text(json.dumps(dict(
            row_start=0, row_stop=len(phases), reference_file='cl_slip_reference.txt')))

    @staticmethod
    def _body(rows):
        return ''.join(' '.join(map(str, row))+'\n' for row in rows)

    def test_accepted_trajectory_measures_quadrant_relocking(self):
        result = check_costas_slip(self.folder, self.observed)
        self.assertTrue(result['rtl_verified'])
        self.assertEqual(result['samples'], 900)
        self.assertTrue(result['disabled_control_rejected'])

    def test_truncated_capture_rejected(self):
        self.observed.write_text(self._body(self.rows[:-1]))
        with self.assertRaisesRegex(RuntimeError, r'\[SLIP\].*incomplete'):
            check_costas_slip(self.folder, self.observed)

    def test_false_quadrant_correction_rejected(self):
        shifted = [(re, im, ((phase+(1<<30)+(1<<31)) % (1<<32))-(1<<31), last)
                   for re, im, phase, last in self.rows]
        self.observed.write_text(self._body(shifted))
        with self.assertRaisesRegex(RuntimeError, r'\[SLIP\]'):
            check_costas_slip(self.folder, self.observed)


if __name__ == '__main__':
    unittest.main()
