"""Finite load budgets against an independent word queue and explicit consumer FSM."""
from collections import deque
from itertools import combinations
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common/python'))
import fifo_budget as budget


def reference(arrivals, ready_pattern=(1,), stall_windows=(), depth=None):
    """Independent storage model: unread RAM words + registered output word.

    The consumer uses three explicit RTL-like states and a seven-register
    rotation-valid pipeline instead of the production model's deadlines.
    Word indices follow every transfer, exposing losses and reordering.
    """
    memory = deque()
    fifo_output = None
    core_output = None
    rotate = [None] * 7
    state = 'IDLE'
    sent = 0
    accepted, service, outputs, samples = [], [], [], []
    service_words, output_words = [], []
    peak = blocked = 0
    for cycle in range(20000):
        mr = int(bool(ready_pattern[cycle % len(ready_pattern)])
                 and not any(a <= cycle < b for a, b in stall_windows))
        fv, mv = fifo_output is not None, core_output is not None
        fr = (not mv or bool(mr)) and state in ('IDLE', 'UPDATE')
        pop = fv and fr
        level = len(memory) + int(fv)
        sr = depth is None or level < depth or pop
        sv = sent < len(arrivals) and arrivals[sent] <= cycle
        samples.append(dict(cycle=cycle, s_valid=int(sv), s_ready=int(sr),
            f_valid=int(fv), f_ready=int(fr), m_valid=int(mv), m_ready=mr, level=level))
        word = fifo_output if pop else None
        # A RAM read sees only words written on earlier edges. A popped
        # registered word is replaced if such an unread word already exists.
        if memory and (not fv or fr):
            fifo_output = memory.popleft()
        elif pop:
            fifo_output = None
        if sv and sr:
            memory.append(sent)
            accepted.append(cycle)
            sent += 1
        elif sv:
            blocked += 1
        if mv and mr:
            outputs.append(cycle)
            output_words.append(core_output)
            core_output = None
        if state == 'IDLE':
            if pop:
                state = 'ROTATE'
        elif state == 'ROTATE':
            if rotate[-1] is not None:
                assert core_output is None
                core_output = rotate[-1]
                state = 'UPDATE'
        else:
            state = 'ROTATE' if pop else 'IDLE'
        if pop:
            service.append(cycle)
            service_words.append(word)
        rotate = [word] + rotate[:-1]
        peak = max(peak, len(memory) + int(fifo_output is not None))
        if len(outputs) == len(arrivals):
            assert service_words == output_words == list(range(len(arrivals)))
            assert not memory and fifo_output is None and core_output is None
            return dict(peak=peak, blocked_cycles=blocked, accepted_cycles=accepted,
                service_cycles=service, output_cycles=outputs, trace=samples, drained_cycle=cycle)
    raise AssertionError('Independent reference did not drain')


class ExactLoads(unittest.TestCase):
    def compare(self, arrivals, ready_pattern=(1,), stall_windows=(), depth=None):
        actual = budget.costas_fifo_load(arrivals, ready_pattern=ready_pattern,
            stall_windows=stall_windows, depth=depth, trace=True)
        expected = reference(arrivals, ready_pattern, stall_windows, depth)
        for key, value in expected.items():
            self.assertEqual(actual[key], value, (key, arrivals, ready_pattern, stall_windows, depth))
        unlimited = reference(arrivals, ready_pattern, stall_windows)
        self.assertEqual(actual['required_capacity'], unlimited['peak'])
        self.assertEqual(actual['minimum_depth'], max(2, unlimited['peak']))
        return actual

    def test_singleton_empty_latency_and_registered_capacity(self):
        row = self.compare([7])
        self.assertEqual(row['accepted_cycles'], [7])
        self.assertEqual(row['service_cycles'], [9])
        self.assertEqual(row['output_cycles'], [17])
        self.assertEqual((row['required_capacity'], row['minimum_depth']), (1, 2))
        # Coincident pop/new write at level1 leaves output invalid next cycle.
        row = self.compare([0, 2, 10, 18], depth=2)
        self.assertEqual(row['trace'][2]['level'], 1)
        self.assertEqual(row['trace'][3]['f_valid'], 0)
        self.assertEqual(row['service_cycles'], [2, 10, 18, 26])

    def test_original_burst_budgets_remain_unchanged(self):
        for length in range(1, 80):
            row = budget.costas_fifo_load(range(length))
            self.assertEqual(row['required_capacity'], budget.finite_burst(length, 8)['required_capacity'])
            self.assertEqual(row['accepted_cycles'], list(range(length)))
            self.assertEqual(row['service_cycles'], [2 + 8*j for j in range(length)])
        self.assertEqual(budget.report()['rows'][0]['required_capacity'], 14)

    def test_early_sink_stall_does_not_freeze_rotation(self):
        ordinary = self.compare(range(16))
        early = self.compare(range(16), stall_windows=((3, 9),))
        self.assertEqual(early['service_cycles'], ordinary['service_cycles'])
        self.assertEqual(early['output_cycles'], ordinary['output_cycles'])
        blocked = self.compare(range(16), stall_windows=((10, 13),))
        self.assertEqual(blocked['service_cycles'][:3], [2, 13, 21])
        self.assertEqual(blocked['output_cycles'][:2], [13, 21])

    def test_selected_workloads_exact_capacity_and_one_word_short(self):
        cases = [
            ([b*32+j for b in range(4) for j in range(16)], (1,), (), 50, 3),
            ([b*160+j for b in range(3) for j in range(16)], (1,), (), 14, 9),
            (list(range(8)) + [15+8*j for j in range(56)],
             tuple(int(not 16 <= j <= 22) for j in range(37)), (), 14, 48),
            ([b*128+j for b in range(4) for j in range(16)], (1,),
             ((40, 64), (170, 194), (310, 334)), 21, 7),
        ]
        for arrivals, pattern, windows, need, short_wait in cases:
            with self.subTest(need=need, count=len(arrivals)):
                unlimited = self.compare(arrivals, pattern, windows)
                self.assertEqual(unlimited['required_capacity'], need)
                minimum = self.compare(arrivals, pattern, windows, need)
                self.assertEqual(minimum['blocked_cycles'], 0)
                self.assertEqual(minimum['accepted_cycles'], arrivals)
                short = self.compare(arrivals, pattern, windows, need-1)
                self.assertEqual(short['blocked_cycles'], short_wait)
                self.assertNotEqual(short['accepted_cycles'], arrivals)
                self.assertEqual(len(short['output_cycles']), len(arrivals))
                self.assertEqual(short['required_capacity'], need)

    def test_short_exhaustive_release_patterns_and_periodic_ready(self):
        for count in (1, 2, 3):
            for arrivals in combinations(range(7), count):
                for pattern in ((1,), (0, 1), (1, 0, 0)):
                    for depth in (None, 2, 3):
                        self.compare(arrivals, pattern, depth=depth)

    def test_random_mixed_stalls_and_accumulated_source_backlog(self):
        rng = random.Random(1817)
        for _ in range(80):
            arrivals = sorted(rng.sample(range(90), rng.randrange(3, 35)))
            pattern = [rng.randrange(2) for _ in range(rng.randrange(1, 10))]
            pattern[0] = 1
            windows = ((rng.randrange(0, 20), rng.randrange(21, 55)), (57, 80))
            self.compare(arrivals, pattern, windows, rng.randrange(2, 15))

    def test_mathematical_budget_larger_than_supported_physical_fifo(self):
        # Only the first word leaves FIFO before the long output pause ends.
        row = budget.costas_fifo_load(range(65538), stall_windows=((0, 65538),))
        self.assertEqual(row['required_capacity'], 65537)
        self.assertEqual(row['minimum_depth'], 65537)
        self.assertEqual(row['ram_power_of_two'], 131072)
        self.assertFalse(row['supported_by_single_fifo'])


class RateAndInputs(unittest.TestCase):
    def test_sustained_deficit_is_only_a_necessary_bound(self):
        for words, period in ((1, 1), (16, 32), (17, 128)):
            row = budget.costas_rate_bound(words, period)
            self.assertTrue(row['unavoidable_rate_deficit'])
            self.assertIs(row['finite_fifo_suffices'], False)
        for words, period in ((1, 8), (16, 128), (1, 100)):
            row = budget.costas_rate_bound(words, period, ready_pattern=(1, 0, 0, 0))
            self.assertFalse(row['unavoidable_rate_deficit'])
            self.assertIsNone(row['finite_fifo_suffices'])
        self.assertIs(budget.costas_rate_bound(1, 100, ready_pattern=(0,))['finite_fifo_suffices'], False)
        # Equal ready duty cycles have different finite workloads service phase.
        a = budget.costas_fifo_load(range(32), ready_pattern=(1, 1, 0))
        b = budget.costas_fifo_load(range(32), ready_pattern=(0, 1, 1))
        self.assertNotEqual(a['service_cycles'], b['service_cycles'])

    def test_invalid_releases_depth_masks_and_windows(self):
        invalid = [dict(arrivals=[]), dict(arrivals=[0, 0]), dict(arrivals=[1, 0]),
            dict(arrivals=None), dict(arrivals=[0], ready_pattern=1),
            dict(arrivals=[0], stall_windows=(1,)),
            dict(arrivals=[-1]), dict(arrivals=[True]), dict(arrivals=[0.0]),
            dict(arrivals=[0], ready_pattern=()), dict(arrivals=[0], ready_pattern=(0,)),
            dict(arrivals=[0], ready_pattern=(True,)), dict(arrivals=[0], ready_pattern=(2,)),
            dict(arrivals=[0], depth=1), dict(arrivals=[0], depth=True),
            dict(arrivals=[0], depth=65537), dict(arrivals=[0], trace=1),
            *[dict(arrivals=[0], stall_windows=(w,)) for w in ((-1, 3), (3, 3), (4, 2), (1,), (0.0, 2))]]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                budget.costas_fifo_load(**kwargs)
        for words, period in ((0, 1), (1, 0), (True, 1), (1, 8.0)):
            with self.assertRaises(ValueError):
                budget.costas_rate_bound(words, period)


if __name__ == '__main__':
    unittest.main()
