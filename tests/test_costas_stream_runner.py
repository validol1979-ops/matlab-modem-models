"""Checks that the Costas acceptance gate requires observed protocol coverage and failures."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import run_costas_stream as runner


class HoldCoverage(unittest.TestCase):
    def test_stall_coverage_requires_one_positive_counter(self):
        self.assertEqual(runner.hold_coverage('COSTAS_STREAM backpressure hold checks: 42', True), 42)
        self.assertEqual(runner.hold_coverage('# COSTAS_STREAM backpressure hold checks: 5', True), 5)
        self.assertEqual(runner.hold_coverage('COSTAS_STREAM backpressure hold checks: 0', False), 0)
        for text in ('', 'COSTAS_STREAM backpressure hold checks: 0',
                     'COSTAS_STREAM backpressure hold checks: -1',
                     'COSTAS_STREAM backpressure hold checks: 1\n'
                     'COSTAS_STREAM backpressure hold checks: 2'):
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                runner.hold_coverage(text, True)

    def test_monitor_negative_needs_protocol_fatal_and_exact_exit(self):
        fatal = '** Fatal: [PROTOCOL] costas_stream output changed under backpressure'
        self.assertEqual(runner.check_negative(fatal, 13, 'PROTOCOL')['vsim_exit_code'], 13)
        for text, code in ((fatal, 1), (fatal, -11), (fatal, True), ('** Fatal: [NUMERIC] x', 13),
                           ('[PROTOCOL] ordinary diagnostic', 13),
                           (fatal + '\nPASS COSTAS_STREAM: 1 samples, 1 outputs, run_max 1, gap_max 0, '
                                    'out_gap_max 0, span 0, cycles 2', 13)):
            with self.subTest(text=text, code=code), self.assertRaises(RuntimeError):
                runner.check_negative(text, code, 'PROTOCOL')

    def test_numeric_control_cannot_use_protocol_failure(self):
        with self.assertRaises(RuntimeError):
            runner.check_negative('** Fatal: [PROTOCOL] x', 13, 'NUMERIC')
        runner.check_negative('** Fatal: [NUMERIC] x', 13, 'NUMERIC')
        with self.assertRaises(RuntimeError):
            runner.check_negative('** Fatal: [PROTOCOL] cfg accepted while busy', 13,
                                  'PROTOCOL', 'output changed under backpressure')


if __name__ == '__main__':
    unittest.main()
