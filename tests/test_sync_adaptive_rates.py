"""Cycle evidence validation independent of simulator latency assumptions."""
import csv
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'tools'))
from run_sync_adaptive_rates import COLUMNS, analyze, profiles


def synthetic(gardner=False):
    count = 8 if gardner else 4
    events = dict(s={}, m={}, w={})
    for frame in range(count):
        source = [3+frame*16+i*(1 if gardner else 2) for i in range(8)]
        output = [12+frame*16+i for i in range(4)] if gardner else [c+2 for c in source]
        for prefix, cycles in (('s', source), ('m', output)):
            events[prefix].update({c: int(i == len(cycles)-1) for i, c in enumerate(cycles)})
        if not gardner:
            events['w'][source[-1]+1] = 1
    last_source = max(events['s'])
    last = max(max(e, default=0) for e in events.values())+3
    rows = []
    for cycle in range(1, last+1):
        row = dict.fromkeys(COLUMNS, 0)
        row.update(cycle=cycle, cfg_valid=int(cycle == 1), cfg_ready=1,
                   configured=int(cycle > 1), s_valid=int(3 <= cycle <= last_source),
                   s_ready=int(cycle in events['s']), m_ready=1, w_ready=1)
        for prefix in ('m', 'w'):
            row[prefix+'_valid'] = int(cycle in events[prefix])
        for prefix in events:
            row[prefix+'_last'] = events[prefix].get(cycle, 0)
        rows.append(row)
    return rows, count


class RatesTest(unittest.TestCase):
    def evaluate(self, rows, gardner=False, frames=4):
        spec = dict(kind=1 if gardner else 2, input_length=8,
                    output_count=4 if gardner else 8, weights_per_frame=0 if gardner else 1, sps=8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'trace.csv'
            with path.open('w') as fd:
                writer = csv.DictWriter(fd, fieldnames=COLUMNS)
                writer.writeheader(); writer.writerows(rows)
            return analyze(path, spec, 0, False, frame_count=frames)

    def test_accepted_cycles_frames_and_weight_tail(self):
        rows, count = synthetic(); measured = self.evaluate(rows, frames=count)
        self.assertEqual(measured['input']['accepted'], 32)
        self.assertEqual(measured['weights']['accepted'], 4)
        self.assertEqual(measured['input']['central_periods']['rate'], .5)
        self.assertEqual(measured['output']['central_periods']['rate'], .5)
        self.assertEqual(measured['input']['longest_consecutive_burst'], 1)
        self.assertEqual(measured['frame_first_input_to_first_output_lag'], [2]*4)
        self.assertEqual(measured['weight_tail'][0]['transfers'], 1)
        self.assertEqual(measured['budgets']['required_clock_mhz_for_100msps_raw_input'], 200)

    def test_gardner_counts_and_different_rate_units(self):
        rows, count = synthetic(True); measured = self.evaluate(rows, True, count)
        self.assertEqual(measured['input']['accepted'], 64)
        self.assertEqual(measured['output']['accepted'], 32)
        self.assertEqual(measured['input']['longest_consecutive_burst'], 8)
        self.assertEqual(measured['input']['central_periods']['rate'], .5)
        self.assertEqual(measured['output']['central_periods']['rate'], .25)
        budget = measured['budgets']
        self.assertEqual(budget['finite_input_to_output_ratio'], 2)
        self.assertEqual(budget['configured_samples_per_symbol'], 8)
        self.assertEqual(budget['required_clock_mhz_for_symbol_target'], 50)
        self.assertEqual(budget['required_clock_mhz_for_both_targets'], 200)

    def test_reject_malformed_counts_controls_and_source_holes(self):
        changes = [('cycle', 8, 999), ('m_valid', 8, 'x'), ('error', 8, 1),
                   ('s_valid', 5, 0), ('m_last', 18, 0), ('w_ready', 8, 0),
                   ('configured', 2, 0)]
        for field, index, value in changes:
            with self.subTest(field=field):
                rows, count = synthetic(); rows[index][field] = value
                with self.assertRaises(RuntimeError):
                    self.evaluate(rows, frames=count)

    def test_explicit_fourteen_profiles(self):
        selected = profiles()
        self.assertEqual(len(selected), 14)
        self.assertEqual({p['kind'] for p in selected}, {0, 1, 2, 3, 4})
        self.assertEqual({p['taps'] for p in selected if p['kind'] == 4}, {1, 3, 8})


if __name__ == '__main__':
    unittest.main()
