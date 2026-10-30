"""Independent word-memory and arithmetic-stage model for framed LMS FIFO budgets."""
from collections import deque
from itertools import product
from pathlib import Path
import random
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common/python'))
import fifo_budget as budget


def lasts_for(lengths):
    result = []
    for n in lengths:
        result.extend([0] * (n - 1) + [1])
    return result


def reference(arrivals, lengths, taps, *, m_ready_pattern=(1,), w_ready_pattern=(1,),
              m_stall_windows=(), w_stall_windows=(), depth=None):
    """Word identities move through RAM, an output register and explicit stages.

    Stage7..1 represents PRODUCT,SUM,ERROR,STEP,COEFF,TAP,WEIGHT. DUMP is
    separate and emits actual (frame,tap) identities. This reference does not
    use the budget implementation's arithmetic/output deadline variables.
    """
    lasts = lasts_for(lengths)
    memory = deque()
    fifo_output = m_output = w_output = None
    stage = 0
    work_word = None
    dump = frame = sent = peak = blocked = 0
    accepted, service, outputs, weights, samples = [], [], [], [], []
    output_lasts, weight_lasts, service_ids, output_ids, weight_ids = [], [], [], [], []
    for cycle in range(200000):
        mr = int(bool(m_ready_pattern[cycle % len(m_ready_pattern)])
                 and not any(a <= cycle < b for a, b in m_stall_windows))
        wr = int(bool(w_ready_pattern[cycle % len(w_ready_pattern)])
                 and not any(a <= cycle < b for a, b in w_stall_windows))
        fv, mv, wv = fifo_output is not None, m_output is not None, w_output is not None
        fr = stage == 0 and not mv
        pop = fv and fr
        level = len(memory) + int(fv)
        sr = depth is None or level < depth or pop
        sv = sent < len(arrivals) and arrivals[sent] <= cycle
        samples.append(dict(cycle=cycle, s_valid=int(sv), s_ready=int(sr),
            s_last=lasts[sent] if sv else 0,
            f_valid=int(fv), f_ready=int(fr), f_last=lasts[fifo_output] if fv else 0,
            m_valid=int(mv), m_ready=mr, m_last=lasts[m_output] if mv else 0,
            w_valid=int(wv), w_ready=wr, w_last=int(w_output[1] == taps - 1) if wv else 0,
            level=level))
        incoming = fifo_output if pop else None
        # Read old RAM contents before appending a newly accepted input word.
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
            output_ids.append(m_output)
            if lasts[m_output]:
                output_lasts.append(cycle)
            m_output = None
        if wv and wr:
            weights.append(cycle)
            weight_ids.append(w_output)
            if w_output[1] == taps - 1:
                weight_lasts.append(cycle)
            w_output = None
        if stage == 0:
            if pop:
                work_word = incoming
                stage = 7
        elif stage == 'DUMP':
            if not wv or wr:
                if dump == taps:
                    w_output = None
                    stage = 0
                    frame += 1
                else:
                    w_output = (frame, dump)
                    dump += 1
        elif stage == 1:
            if lasts[work_word]:
                stage = 'DUMP'
                dump = 0
            else:
                stage = 0
        else:
            if stage == 5:
                assert m_output is None
                m_output = work_word
            stage -= 1
        if pop:
            service.append(cycle)
            service_ids.append(incoming)
        peak = max(peak, len(memory) + int(fifo_output is not None))
        if len(outputs) == len(arrivals) and len(weights) == len(lengths) * taps:
            assert stage == 0 and frame == len(lengths)
            assert service_ids == output_ids == list(range(len(arrivals)))
            assert weight_ids == [(f, tap) for f in range(len(lengths)) for tap in range(taps)]
            assert not memory and fifo_output is None and m_output is None and w_output is None
            return dict(peak=peak, blocked_cycles=blocked, accepted_cycles=accepted,
                service_cycles=service, output_cycles=outputs, weight_cycles=weights,
                output_last_cycles=output_lasts, weight_last_cycles=weight_lasts,
                trace=samples, drained_cycle=cycle)
    raise AssertionError('Independent LMS reference did not drain')


class LMSBudgets(unittest.TestCase):
    def compare(self, arrivals, lengths, taps, *, mode='lms', depth=None, **sinks):
        row = budget.lms_fifo_load(arrivals, frame_lengths=lengths, taps=taps,
            mode=mode, depth=depth, trace=True, **sinks)
        expected = reference(arrivals, lengths, taps, depth=depth, **sinks)
        for key, value in expected.items():
            self.assertEqual(row[key], value, (key, arrivals, lengths, taps, depth, sinks))
        unlimited = reference(arrivals, lengths, taps, **sinks)
        self.assertEqual(row['required_capacity'], unlimited['peak'])
        self.assertEqual(row['minimum_depth'], max(2, unlimited['peak']))
        self.assertTrue(row['supported_by_single_fifo'])
        return row

    def test_singleton_latency_weight_count_and_next_frame_boundary(self):
        for taps, mode in product((1, 3, 8, 16), ('lms', 'nlms')):
            row = self.compare([0, 1], [1, 1], taps, mode=mode)
            self.assertEqual(row['service_cycles'], [2, 11 + taps])
            self.assertEqual(row['output_cycles'][0], 6)
            self.assertEqual(row['weight_cycles'][:taps], list(range(11, 11 + taps)))
            self.assertEqual(row['weight_last_cycles'][0], 10 + taps)
            self.assertEqual((row['required_capacity'], row['minimum_depth']), (2, 2))
        row = self.compare([11], [1], 1)
        self.assertEqual(row['service_cycles'], [13])
        self.assertEqual(row['output_cycles'], [17])
        self.assertEqual(row['weight_cycles'], [22])
        self.assertEqual((row['required_capacity'], row['minimum_depth']), (1, 2))

    def test_frame_lengths_and_explicit_lasts_are_equivalent(self):
        arrivals = list(range(9))
        for taps in (1, 3, 8, 16):
            kwargs = dict(taps=taps, depth=3, m_stall_windows=((5, 28),), w_stall_windows=((11, 39),), trace=True)
            a = budget.lms_fifo_load(arrivals, frame_lengths=[1, 3, 5], **kwargs)
            b = budget.lms_fifo_load(arrivals, input_last=lasts_for([1, 3, 5]), **kwargs)
            self.assertEqual(a, b)

    def test_early_and_pending_data_stalls_and_no_same_edge_retake(self):
        ordinary = self.compare(range(4), [4], 3)
        early = self.compare(range(4), [4], 3, m_stall_windows=((0, 5),))
        self.assertEqual(ordinary['service_cycles'], early['service_cycles'])
        pending = self.compare(range(4), [4], 3, m_stall_windows=((6, 12),))
        self.assertEqual(pending['output_cycles'][0], 12)
        self.assertEqual(pending['service_cycles'][:2], [2, 13])
        self.assertEqual(pending['trace'][12]['f_ready'], 0)
        self.assertEqual(pending['trace'][13]['f_ready'], 1)

    def test_weight_stalls_do_not_freeze_data_or_first_dump_load(self):
        row = self.compare([0, 1], [1, 1], 3, w_stall_windows=((0, 20),))
        self.assertEqual(row['output_cycles'][0], 6)
        self.assertEqual(row['trace'][11]['w_valid'], 1)
        self.assertEqual(row['weight_cycles'][:3], [20, 21, 22])
        self.assertEqual(row['service_cycles'][1], 23)
        early = self.compare([0, 1], [1, 1], 3, w_stall_windows=((0, 11),))
        ordinary = self.compare([0, 1], [1, 1], 3)
        self.assertEqual(early['weight_cycles'], ordinary['weight_cycles'])
        self.assertEqual(early['service_cycles'], ordinary['service_cycles'])

    def test_weights_can_finish_before_pending_data_output(self):
        for taps in (1, 3, 8, 16):
            row = self.compare(range(16), [1, 7, 8], taps, m_stall_windows=((4, 42),))
            self.assertLess(row['weight_last_cycles'][0], 42)
            self.assertEqual(row['output_cycles'][0], 42)
            self.assertEqual(row['service_cycles'][1], 43)

    def test_selected_loads_exact_minimum_and_one_short(self):
        cases = [
            ('dense', list(range(16)), {}),
            ('paced', list(range(4)) + [12 + 9*j for j in range(12)], {}),
            ('mstall', list(range(16)), dict(m_ready_pattern=tuple(int(not 10 <= j < 26) for j in range(41)), m_stall_windows=((4, 42),))),
            ('wstall', list(range(16)), dict(w_ready_pattern=tuple(int(j == 20) for j in range(29)))),
        ]
        for taps in (1, 3, 8, 16):
            for name, arrivals, sinks in cases:
                with self.subTest(taps=taps, load=name):
                    row = self.compare(arrivals, [1, 7, 8], taps, **sinks)
                    need = row['minimum_depth']
                    minimum = self.compare(arrivals, [1, 7, 8], taps, depth=need, **sinks)
                    short = self.compare(arrivals, [1, 7, 8], taps, depth=need-1, **sinks)
                    self.assertEqual(minimum['accepted_cycles'], arrivals)
                    self.assertEqual(minimum['blocked_cycles'], 0)
                    self.assertGreater(short['blocked_cycles'], 0)
                    self.assertEqual(short['required_capacity'], row['required_capacity'])

    def test_sparse_weight_sink_holds_final_weight_for_every_tap_count(self):
        for taps in (1, 3, 8, 16):
            row = self.compare(range(16), [1, 7, 8], taps,
                w_ready_pattern=tuple(int(j == 20) for j in range(29)))
            held = [r for r in row['trace'] if r['w_valid'] and r['w_last'] and not r['w_ready']]
            self.assertTrue(held)
            self.assertEqual(len(row['weight_last_cycles']), 3)

    def test_oversized_mathematical_budget_is_not_a_legal_single_fifo(self):
        row = budget.lms_fifo_load(range(65538), frame_lengths=[65538], taps=1,
            m_stall_windows=((0, 65538),))
        # One sample leaves FIFO before the long pending-data pause.
        self.assertEqual(row['required_capacity'], 65537)
        self.assertEqual(row['minimum_depth'], 65537)
        self.assertEqual(row['ram_power_of_two'], 131072)
        self.assertFalse(row['supported_by_single_fifo'])

    def test_random_frames_both_modes_and_independent_sink_patterns(self):
        rng = random.Random(37124)
        for _ in range(120):
            lengths = [rng.randrange(1, 7) for _ in range(rng.randrange(1, 5))]
            arrivals = sorted(rng.sample(range(120), sum(lengths)))
            mp = [1] + [rng.randrange(2) for _ in range(rng.randrange(6))]
            wp = [1] + [rng.randrange(2) for _ in range(rng.randrange(8))]
            self.compare(arrivals, lengths, rng.choice((1, 3, 8, 16)),
                mode=rng.choice(('lms', 'nlms')), depth=rng.choice((None, 2, 3, 8, 20)),
                m_ready_pattern=mp, w_ready_pattern=wp,
                m_stall_windows=((3, 29), (67, 92)), w_stall_windows=((0, 21), (42, 80)))


class RateAndValidation(unittest.TestCase):
    def test_frame_service_period_matches_independent_reference(self):
        for lengths, taps in product(([1], [1, 1, 1], [1, 7, 8], [2, 3, 1, 6]), (1, 3, 8, 16)):
            row = reference(range(sum(lengths)), lengths, taps)
            period = row['weight_last_cycles'][-1] + 1 - row['service_cycles'][0]
            self.assertEqual(period, sum(8*n + taps + 1 for n in lengths))
            impossible = budget.lms_rate_bound(lengths, taps, period - 1)
            self.assertTrue(impossible['unavoidable_rate_deficit'])
            self.assertIs(impossible['finite_fifo_suffices'], False)
            boundary = budget.lms_rate_bound(lengths, taps, period)
            self.assertEqual(boundary['minimum_processing_period'], period)
            self.assertIsNone(boundary['finite_fifo_suffices'])
        self.assertEqual([budget.lms_rate_bound([1, 7, 8], t, 200)['minimum_processing_period'] for t in (1, 3, 8, 16)], [134, 140, 155, 179])
        self.assertIs(budget.lms_rate_bound([1], 1, 100, m_ready_pattern=(0,))['finite_fifo_suffices'], False)
        self.assertIs(budget.lms_rate_bound([1], 1, 100, w_ready_pattern=(0,))['finite_fifo_suffices'], False)
        self.assertIsNone(budget.lms_rate_bound([1], 1, 100, m_ready_pattern=(1, 0, 0), w_ready_pattern=(0, 1))['finite_fifo_suffices'])

    def test_invalid_frames_modes_taps_and_sinks(self):
        invalid = [dict(), dict(frame_lengths=[1], input_last=[1, 1]),
            dict(frame_lengths=[]), dict(frame_lengths=[1]), dict(frame_lengths=[0, 2]),
            dict(frame_lengths=[True, 1]), dict(frame_lengths=2), dict(input_last=[0, 0]),
            dict(input_last=[1]), dict(input_last=[True, 1]), dict(input_last=[0, 2]),
            dict(frame_lengths=[2], taps=0), dict(frame_lengths=[2], taps=True),
            dict(frame_lengths=[2], mode='rls'), dict(frame_lengths=[2], m_ready_pattern=(0,)),
            dict(frame_lengths=[2], w_ready_pattern=(0,)), dict(frame_lengths=[2], w_stall_windows=((2, 1),)),
            dict(frame_lengths=[2], depth=1)]
        for kwargs in invalid:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                budget.lms_fifo_load([0, 1], **kwargs)
        for args in (([], 1, 1), ([0], 1, 1), ([1], 0, 1), ([1], 1, 0), ([1], True, 10)):
            with self.assertRaises(ValueError):
                budget.lms_rate_bound(*args)


if __name__ == '__main__':
    unittest.main()
