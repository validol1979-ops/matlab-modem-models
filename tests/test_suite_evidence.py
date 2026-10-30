"""Parent results retain verified child artifacts instead of only a status copy."""
from pathlib import Path
import sys
import tempfile
import unittest
import json

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from run_tests import verified_suite_artifacts,mark_failed_reports
from regression_evidence import begin,finish


class TestSuiteEvidence(unittest.TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory();self.addCleanup(self.folder.cleanup)
        self.root=Path(self.folder.name);(self.root/'common').mkdir()
        (self.root/'common/source.py').write_text('value=1\n')
        self.log=self.root/'result.log';self.log.write_text('PASS\n')
        self.passed=dict(finish(begin(self.root),[self.log],self.root),status='PASS')

    def test_dict_and_list_keep_child_artifacts_without_duplicates(self):
        self.assertEqual(verified_suite_artifacts(self.passed,self.root),[self.log])
        self.assertEqual(verified_suite_artifacts([self.passed,self.passed],self.root),[self.log])

    def test_empty_failed_and_unfinished_child_evidence_rejected(self):
        for data in ([],{},dict(self.passed,status='FAIL'),dict(self.passed,completed_at_utc=None)):
            with self.subTest(data_type=type(data).__name__),self.assertRaises(RuntimeError):
                verified_suite_artifacts(data,self.root)

    def test_changed_child_log_is_rejected(self):
        self.log.write_text('changed\n')
        with self.assertRaisesRegex(RuntimeError,'artifact'):
            verified_suite_artifacts([self.passed],self.root)

    def test_failed_invocation_closes_running_results_preserving_original_snapshot(self):
        path=self.root/'running.json'
        original=dict(begin(self.root),status='RUNNING')
        path.write_text(json.dumps(original))
        mark_failed_reports([(path,original['started_at_utc'])],RuntimeError('child failed'))
        failed=json.loads(path.read_text())
        self.assertEqual(failed['status'],'FAIL');self.assertEqual(failed['error'],'RuntimeError: child failed')
        self.assertEqual(failed['source_hashes'],original['source_hashes'])
        self.assertEqual(failed['started_at_utc'],original['started_at_utc'])
        self.assertTrue(failed['failed_at_utc']);self.assertNotIn('completed_at_utc',failed)

    def test_failure_cleanup_keeps_completed_and_newer_invocations(self):
        for original,started in ((self.passed,self.passed['started_at_utc']),
                                 (dict(begin(self.root),status='RUNNING'),'older invocation')):
            path=self.root/'other.json';path.write_text(json.dumps(original));before=path.read_bytes()
            mark_failed_reports([(path,started)],RuntimeError('old child failed'))
            self.assertEqual(path.read_bytes(),before)


if __name__=='__main__':unittest.main()
