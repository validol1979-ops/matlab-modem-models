"""Only the new actual-DUT SER marker/parser and numeric control acceptance."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from run_bpsk import parse_rtl_payload_ser,numeric_negative


class TestBpskSerEvidence(unittest.TestCase):
    def test_actual_per_frame_errors_and_zero_denominator(self):
        report=dict(frames=2,symbols=400,payload_errors=[1,2])
        text='RTL PAYLOAD SER frame=0 errors=1 symbols=8\nRTL PAYLOAD SER frame=1 errors=2 symbols=8\nPASS BPSK receiver: 400 symbols, 2 acquisitions, 3 payload errors\n'
        result=parse_rtl_payload_ser(text,report,profile='qpsk',scenario='stream',reset_active=0)
        self.assertEqual(result['payload_symbols'],16);self.assertEqual(result['payload_errors'],3)
        self.assertEqual(result['ser'],3/16);self.assertEqual(result['frames'][0]['ser'],1/8)
        zero=parse_rtl_payload_ser('RTL PAYLOAD SER frame=0 errors=0 symbols=0\nPASS BPSK receiver: 192 symbols, 1 acquisitions, 0 payload errors\n',
                                   dict(frames=1,symbols=192,payload_errors=[0]),profile='bpsk',scenario='minimum',reset_active=1)
        self.assertIsNone(zero['ser']);self.assertFalse(zero['defined'])
        self.assertIsNone(zero['frames'][0]['ser']);self.assertFalse(zero['frames'][0]['defined'])

    def test_missing_bad_counts_duplicate_and_failed_run_are_rejected(self):
        report=dict(frames=1,symbols=200,payload_errors=[1])
        good='RTL PAYLOAD SER frame=0 errors=1 symbols=8\nPASS BPSK receiver: 200 symbols, 1 acquisitions, 1 payload errors\n'
        for text in [good.split('\n',1)[1],good.replace('symbols=8','symbols=9'),good.replace('frame=0','frame=1'),
                     good.replace('errors=1','errors=0'),good.replace('1 payload errors','0 payload errors'),
                     good+'UVM_FATAL [NUMERIC] failure',good.split('\n')[0]+'\n'+good]:
            with self.subTest(text=text),self.assertRaises(RuntimeError):
                parse_rtl_payload_ser(text,report,profile='bpsk',scenario='stream',reset_active=1)

    def test_numeric_control_requires_nonzero_tag_count_and_no_pass(self):
        fatal='UVM_FATAL @ 1: reporter [NUMERIC] mismatch\nUVM_FATAL : 1\n'
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder);log=work/'negative.log'
            for rc,text in [(0,fatal),(13,'UVM_FATAL [NUMERIC] absent summary'),(13,'UVM_FATAL : 1'),(13,fatal+'PASS BPSK receiver:')]:
                with self.subTest(rc=rc,text=text),patch('run_bpsk.subprocess.run',return_value=subprocess.CompletedProcess([],rc,text,'')),self.assertRaises(RuntimeError):
                    numeric_negative(['vsim'],work,log,'PASS BPSK receiver:')
            with patch('run_bpsk.subprocess.run',return_value=subprocess.CompletedProcess([],13,fatal,'')) as run:
                result=numeric_negative(['vsim'],work,log,'PASS BPSK receiver:')
            self.assertEqual(result['returncode'],13)
            self.assertEqual(run.call_args.args[0][-2:],['-do','numeric_negative.do'])
            self.assertEqual(run.call_args.kwargs['timeout'],90)


if __name__=='__main__':unittest.main()
