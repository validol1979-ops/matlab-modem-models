"""Only fresh normal scenario artifacts can contribute to coverage totals."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import coverage_report as c
from regression_evidence import begin,finish,write_json


class TestCoverageReport(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name)
        (self.root/'common').mkdir()
        (self.root/'common/source.py').write_text('value=1\n')
        self.output=self.root/'build/rtl/fft'
        (self.output/'case').mkdir(parents=True)
        self.mock=patch.object(c,'ROOT',self.root)
        self.mock.start();self.addCleanup(self.mock.stop)

    def log(self,name,modes='3,4'):
        path=self.output/'case'/name
        path.write_text(f'COVER fft m group=80.0 xfer=7 stall=2 last=1 pos=1 neg=1 zero=0 modes={modes}\n')
        return path

    def report(self,logs,suite='all',status='PASS'):
        data=dict(finish(begin(self.root),logs,self.root),status=status)
        write_json(self.output/f'{suite}_results.json',data)
        return data

    def test_stray_and_injection_logs_cannot_inflate_totals(self):
        normal=self.log('stream.log')
        injection=self.log('inject_sat_mismatch.log')
        rejection=self.log('bad_cfg.log')
        self.log('stalled.log')  # old file absent from the current manifest
        self.report([normal,injection,rejection])
        row=c.collect(['fft'])['fft m']
        self.assertEqual(row['runs'],1)
        self.assertEqual(row['xfer'],7)
        self.assertEqual(row['modes'],[3,4])

    def test_modified_artifact_and_source_are_rejected(self):
        normal=self.log('stream.log');self.report([normal])
        normal.write_text(normal.read_text()+'changed\n')
        with self.assertRaisesRegex(RuntimeError,'artifact'):
            c.collect(['fft'])
        self.report([normal])
        (self.root/'common/source.py').write_text('value=2\n')
        with self.assertRaisesRegex(RuntimeError,'source'):
            c.collect(['fft'])

    def test_newer_failed_or_running_run_cannot_use_older_success(self):
        normal=self.log('stream.log');self.report([normal])
        for status in ('RUNNING','FAIL'):
            with self.subTest(status=status):
                self.report([normal],suite='hdl',status=status)
                with self.assertRaisesRegex(RuntimeError,'passing'):
                    c.collect(['fft'])

    def test_missing_report_and_changed_mode_dimensions_are_rejected(self):
        with self.assertRaisesRegex(RuntimeError,'report'):
            c.collect(['fft'])
        self.report([self.log('stream.log'),self.log('stalled.log',modes='7')])
        with self.assertRaisesRegex(RuntimeError,'mode bin'):
            c.collect(['fft'])


if __name__=='__main__':unittest.main()
