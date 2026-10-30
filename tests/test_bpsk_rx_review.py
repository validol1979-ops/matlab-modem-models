"""Review coverage and exact exit-code acceptance, without invoking Questa."""
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from bpsk_rx_review import EPOCH_COUNTS,checked_review
from run_bpsk import numeric_negative


class ReviewEvidence(unittest.TestCase):
    def test_recovery_requires_every_epoch_and_both_reset_locations(self):
        good=''.join(f'BPSK RX review epoch N={n} symbols={3*n} acquisitions=3 short_frames={int(n<=244)}\n'+(f'BPSK RX short reset mode={i+1}\n' if i<2 else '') for i,n in enumerate(EPOCH_COUNTS))
        good+='PASS BPSK RX short recovery: 7 epochs, 21 frames, 5130 symbols, 21 acquisitions\n'
        self.assertEqual(checked_review(good)['symbols'],5130)
        for old,new in [('N=245','N=244'),('symbols=732','symbols=731'),('acquisitions=3','acquisitions=2'),
                        ('short_frames=1','short_frames=0'),('mode=2','mode=1'),('PASS BPSK','FAIL BPSK')]:
            with self.subTest(old=old),self.assertRaises(RuntimeError):checked_review(good.replace(old,new))
        for bad in (good+good,good+'** Fatal: [NUMERIC] mismatch',good+'UVM_FATAL [NUMERIC] mismatch'):
            with self.assertRaises(RuntimeError):checked_review(bad)

    def test_collision_counts_include_first_word_and_final_configuration_beat(self):
        report=dict(symbols=732,frames=3)
        for index in (0,191):
            good=(f'BPSK RX cfg collision index={index} accepted_cfg=192 blocked_data={192-index}\n'
                  f'PASS BPSK RX cfg arbitration index={index} symbols=732 acquisitions=3\n')
            self.assertEqual(checked_review(good,collision=index,report=report)['collision'],index)
            for bad in (good+good,good.replace('accepted_cfg=192','accepted_cfg=191'),
                        good.replace('blocked_data=', 'missing='),good.replace('symbols=732','symbols=731'),
                        good.replace('PASS BPSK','FAIL BPSK'),good+'** Fatal: [CONFIG_ARB]'):
                with self.assertRaises(RuntimeError):checked_review(bad,collision=index,report=report)

    def test_runners_refuse_existing_evidence_directory(self):
        root=Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as folder:
            sentinel=Path(folder)/'old.log';sentinel.write_text('keep')
            for runner in ('run_bpsk','run_cpm','run_oqpsk'):
                result=subprocess.run([sys.executable,str(root/f'tools/{runner}.py'),'--suite','hdl','--output',folder],capture_output=True,text=True)
                self.assertNotEqual(result.returncode,0)
                self.assertIn('FileExistsError',result.stderr)
                self.assertEqual(sentinel.read_text(),'keep')
                self.assertEqual(list(Path(folder).iterdir()),[sentinel])

    def test_negative_requires_exactly_13(self):
        fatal='UVM_FATAL @ 1: reporter [NUMERIC] mismatch\nUVM_FATAL : 1\n'
        with tempfile.TemporaryDirectory() as folder:
            work=Path(folder)
            for code in (0,1,2,12,14,-31):
                with self.subTest(code=code),patch('run_bpsk.subprocess.run',return_value=subprocess.CompletedProcess([],code,fatal,'')),self.assertRaises(RuntimeError):
                    numeric_negative(['vsim'],work,work/'negative.log','PASS BPSK RX')
            with patch('run_bpsk.subprocess.run',return_value=subprocess.CompletedProcess([],13,fatal,'')):
                self.assertEqual(numeric_negative(['vsim'],work,work/'negative.log','PASS BPSK RX')['returncode'],13)


if __name__=='__main__':unittest.main()
