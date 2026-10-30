"""A sampled RTL acquisition grid must contain every point and use its known reference."""
from pathlib import Path
import json
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from sync_cases import vectors
from sync_slip_evidence import check_costas_acquisition


class SyncGridEvidence(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory();self.addCleanup(temporary.cleanup)
        self.folder=Path(temporary.name)
        vectors(self.folder,transactions=1,seed=41)
        self.observed=self.folder/'observed.txt'
        body=(self.folder/'cl_out.txt').read_text().splitlines()[1:]
        self.observed.write_text('\n'.join(body)+'\n')

    def test_complete_grid_measured_from_accepted_output(self):
        result=check_costas_acquisition(self.folder,self.observed)
        self.assertTrue(result['rtl_verified']);self.assertEqual(result['points'],12)
        self.assertEqual({v['classification'] for v in result['cases']},
                         {'true_quadrant_lock','other_quadrant_lock','unlocked'})
        path=self.folder/'cl_acquisition.json';metadata=json.loads(path.read_text())
        path.write_text(json.dumps(metadata[:-1]))
        with self.assertRaisesRegex(RuntimeError,r'\[ACQUISITION\].*incomplete'):
            check_costas_acquisition(self.folder,self.observed)

    def test_false_carrier_reference_rejected(self):
        metadata=json.loads((self.folder/'cl_acquisition.json').read_text())
        path=self.folder/metadata[0]['reference_file']
        lines=path.read_text().splitlines();lines[1]=str(float(lines[1])+.1)
        path.write_text('\n'.join(lines)+'\n')
        with self.assertRaisesRegex(RuntimeError,r'\[ACQUISITION\].*reference'):
            check_costas_acquisition(self.folder,self.observed)


if __name__=='__main__':unittest.main()
