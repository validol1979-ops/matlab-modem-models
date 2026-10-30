"""Independent timing facts: burst transfers separated by frame pauses."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
import run_stream_rates as r


class TestStreamRates(unittest.TestCase):
    def trace(self,path):
        rows=[]
        for cycle in range(1,280):
            source_index=cycle-1;output_index=cycle-4
            s_valid=0<=source_index<256 and source_index%8<4
            m_valid=0<=output_index<256 and output_index%8<4
            rows.append(dict(cycle=cycle,s_valid=int(s_valid),s_ready=1,s_last=int(s_valid and source_index%8==3),
                             m_valid=int(m_valid),m_ready=1,m_last=int(m_valid and output_index%8==3),
                             fifo=0,extra=0,full_banks=0,draining=0,fifo_capacity=8))
        self.write(path,rows);return rows

    def write(self,path,rows):
        with path.open('w') as fd:
            writer=csv.DictWriter(fd,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)

    def test_burst_one_does_not_claim_sustained_one(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.csv';self.trace(path);result=r.analyze(path,'fir',4,4,4)
        self.assertEqual(result['input']['longest_consecutive_burst'],4)
        self.assertEqual(result['input']['central_periods']['rate'],.5)
        self.assertAlmostEqual(result['input']['accepted_span_rate'],128/252)
        self.assertEqual(result['frame_first_input_to_first_output'],[3]*32)
        self.assertEqual(result['input']['boundary_idle_cycles'],[4]*31)
        self.assertLess(result['full_first_input_to_last_output']['input_rate'],result['input']['accepted_span_rate'])

    def test_false_continuous_offer_claim_and_fifo_overflow_fail(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.csv';rows=self.trace(path)
            with self.assertRaises(RuntimeError):r.analyze(path,'fir',4,4,0)
            rows[7]['fifo']=9;self.write(path,rows)
            with self.assertRaises(RuntimeError):r.analyze(path,'fir',4,4,4)

    def test_lost_clock_or_missing_frame_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'trace.csv';rows=self.trace(path)
            self.write(path,rows[:50]+rows[51:])
            with self.assertRaises(RuntimeError):r.analyze(path,'fir',4,4,4)
            rows=self.trace(path);rows[3]['s_last']=0;self.write(path,rows)
            with self.assertRaises(RuntimeError):r.analyze(path,'fir',4,4,4)


if __name__=='__main__':unittest.main()
