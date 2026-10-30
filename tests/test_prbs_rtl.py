"""Vector/model equivalence and runner gates; no simulator or synthesis invocation."""
import random
import subprocess
import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
sys.path.insert(0, str(ROOT/'tools'))
import prbs_rtl_cases as cases
import run_prbs as runner
from ext_code_basics import prbs_bits, lfsr_jump, additive_scramble, selfsync_scramble, selfsync_descramble


class PrbsVectors(unittest.TestCase):
    def test_independent_recurrence_periods_and_jump(self):
        rng = random.Random(318)
        for n, k in ((7, 6), (9, 5), (15, 14), (31, 28)):
            seed = rng.randrange(1, 1 << n)
            length = (1 << n)-1 if n < 31 else 2048
            bits, state = prbs_bits(n, length, seed)
            history = [(seed >> j) & 1 for j in range(n)]
            for j in range(length):
                history.append(history[j] ^ history[j+n-k])
            self.assertEqual(bits, history[:length])
            self.assertEqual(state, cases.pack(history[length:length+n]))
            self.assertEqual(state, lfsr_jump(n, length, seed))
            if n < 31:
                self.assertEqual(state, seed)
                # Independently walk the scalar recurrence, counting every state.
                states = set()
                for j in range(length):
                    states.add(cases.pack(history[j:j+n]))
                self.assertEqual(len(states), length)
                self.assertNotIn(0, states)
            else:
                for j in range(n):
                    basis = 1 << j
                    for step in (1, 31, 127, 1024):
                        self.assertEqual(lfsr_jump(n, step, basis), prbs_bits(n, step, basis)[1])
                self.assertEqual(lfsr_jump(n, 10**12+37, seed),
                                 lfsr_jump(n, 10**12, lfsr_jump(n, 37, seed)))

    def test_word_partition_state_and_bit_order(self):
        for n in cases.ORDERS:
            seed = (1 << n)-3
            for width in (1, 3, 8, 31, 32, 64):
                words = [(i * 997) & ((1 << width)-1) for i in range(19)]
                for mode in range(4):
                    initial = seed if mode < 2 else 0
                    baseline = cases.reference(n, width, mode, initial, 0, [words])
                    for split in range(1, len(words)):
                        rows = cases.reference(n, width, mode, initial, 0, [words[:split], words[split:]])
                        self.assertEqual([(x, y, s) for x, _, y, s in rows],
                                         [(x, y, s) for x, _, y, s in baseline])
                    raw = cases.bits_of(words, width)
                    expected = (prbs_bits(n, len(raw), seed)[0] if mode == 0 else
                                additive_scramble(raw, n, seed) if mode == 1 else
                                selfsync_scramble(raw, n) if mode == 2 else selfsync_descramble(raw, n))
                    self.assertEqual(cases.bits_of([row[2] for row in baseline], width), expected)
        expected = prbs_bits(7, 16, 0x53)[0]
        self.assertNotEqual(expected[:8], expected[:8][::-1])
        self.assertEqual(cases.reference(7, 8, 0, 0x53, 0, [[0, 0]])[0][2], cases.pack(expected[:8]))

    def test_restart_roundtrip_and_error_spread(self):
        for n, k in ((7, 6), (9, 5), (15, 14), (31, 28)):
            for width in (1, 8, 64):
                words = [(i * 977) & ((1 << width)-1) for i in range(100)]
                for mode in range(4):
                    seed = 1 if mode < 2 else 0
                    rows = cases.reference(n, width, mode, seed, 1, [words, words])
                    self.assertEqual(rows[:100], rows[100:])
                for mode, inverse in ((1, 1), (2, 3)):
                    seed = 1 if mode == 1 else 0
                    enc = cases.reference(n, width, mode, seed, 0, [words])
                    ciphertext = [r[2] for r in enc]
                    dec = cases.reference(n, width, inverse, seed, 0, [ciphertext])
                    self.assertEqual([r[2] for r in dec], words)
                    pos = width+1
                    ciphertext[pos//width] ^= 1 << (pos % width)
                    bad = cases.reference(n, width, inverse, seed, 0, [ciphertext])
                    difference = [a ^ b for a, b in zip(cases.bits_of([r[2] for r in bad], width), cases.bits_of(words, width))]
                    self.assertEqual([i for i, b in enumerate(difference) if b],
                                     [pos] if mode == 1 else [pos, pos+k, pos+n])

    def test_vector_file_complete_and_deterministic(self):
        with TemporaryDirectory() as temp:
            a, b = Path(temp)/'a.txt', Path(temp)/'b.txt'
            report = cases.vectors(a, 7, 8)
            self.assertEqual(cases.vectors(b, 7, 8), report)
            self.assertEqual(a.read_bytes(), b.read_bytes())
            entries = cases.cases(7, 8)
            lines = a.read_text().splitlines()
            self.assertEqual(int(lines[0]), report['configurations'])
            self.assertEqual(len(lines), 1+report['configurations']+report['outputs'])
            for mode in range(4):
                rows = [r for m, _, _, block in entries if m == mode for r in block]
                self.assertEqual({r[0] for r in rows}, set(range(256)))
            self.assertEqual({seed for mode, seed, _, _ in entries if mode == 0}, set(range(1, 128)))

    def test_validation(self):
        for args in ((8, 1, 0, 1, 0, [[0]]), (7, 0, 0, 1, 0, [[0]]),
                     (7, 65, 0, 1, 0, [[0]]), (7, 1, 4, 1, 0, [[0]]),
                     (7, 1, 0, 0, 0, [[0]]), (7, 1, 2, 1, 0, [[0]]),
                     (7, 1, 0, 128, 0, [[0]]), (7, 1, 1, 1, 0, [[]]),
                     (7, 1, 1, 1, 0, [[2]])):
            with self.subTest(args=args), self.assertRaises(ValueError):
                cases.reference(*args)


class RunnerGates(unittest.TestCase):
    def test_negatives_require_exact_code_fatal_tag_and_no_pass(self):
        for prefix in ('** Fatal:', '%Error:', '%Fatal:'):
            for tag in ('NUMERIC', 'PROTOCOL'):
                message = f'{prefix} tb:1 [{tag}] injected failure'
                self.assertEqual(runner.check_negative(13, message, tag)['returncode'], 13)
                for code in (0, 1, -6, -11, True):
                    with self.assertRaises(RuntimeError):
                        runner.check_negative(code, message, tag)
                for text in ('', f'[{tag}] ordinary diagnostic', message.replace(tag, 'OTHER'),
                             message+'\nPASS PRBS: configs=1 outputs=1 max_run=1 holds=0 gaps=0'):
                    with self.assertRaises(RuntimeError):
                        runner.check_negative(13, text, tag)

    def test_positive_counts_coverage_and_errors(self):
        report = dict(configurations=3, outputs=100)
        good = runner.DIRECTED+'\nPASS PRBS: configs=3 outputs=100 max_run=99 holds=5 gaps=6'
        runner.check_positive(0, good, report, True)
        runner.check_positive(0, good, report, False)
        for text in ('', good+good, good.replace('outputs=100', 'outputs=99'),
                     good.replace('holds=5', 'holds=0'), good+'\n%Error: bad',
                     good.replace(runner.DIRECTED, '')):
            with self.assertRaises(RuntimeError):
                runner.check_positive(0, text, report, True)
        with self.assertRaises(RuntimeError):
            runner.check_positive(13, good, report, False)
        with self.assertRaises(RuntimeError):
            runner.check_positive(0, good.replace('max_run=99', 'max_run=1'), report, False)

    def test_existing_output_rejected_before_tools(self):
        with TemporaryDirectory() as temp:
            result = subprocess.run([sys.executable, ROOT/'tools/run_prbs.py', '--suite', 'lint',
                                     '--output-dir', temp], capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('FileExistsError', result.stderr)
            self.assertFalse(list(Path(temp).iterdir()))

    def test_optimized_python_rejected(self):
        result = subprocess.run([sys.executable, '-O', ROOT/'tools/run_prbs.py', '--help'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('without Python optimization', result.stderr)


if __name__ == '__main__':
    unittest.main()
