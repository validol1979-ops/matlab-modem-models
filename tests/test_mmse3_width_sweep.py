"""Endpoint and independent integer checks for the MMSE3 width proof."""
from itertools import product
import copy
from pathlib import Path
import random
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
import mmse3_fixed as fixed
import mmse3_widths as widths
sys.path.insert(0, str(ROOT/'tools'))
import mmse3_width_sweep as sweep


class TestMmse3Widths(unittest.TestCase):
    def fits(self, value, bits):
        self.assertGreaterEqual(value, -(1 << (bits-1)))
        self.assertLess(value, 1 << (bits-1))

    def test_exact_layout_and_minimality(self):
        bounds = widths.layout()
        self.assertEqual(bounds['gram']['required_bits'], 38)
        self.assertEqual(bounds['sum']['required_bits'], 84)
        self.assertEqual(bounds['round_add']['required_bits'], 84)
        self.assertEqual(bounds['rounded']['required_bits'], 60)
        for name in ('gram', 'sum', 'round_add', 'rounded'):
            interval = bounds[name]
            bits = interval['required_bits']
            self.fits(interval['minimum'], bits)
            self.fits(interval['maximum'], bits)
            self.assertTrue(interval['minimum'] < -(1 << (bits-2)) or
                            interval['maximum'] >= 1 << (bits-2))
        a = 1 << 17
        g = widths.gram([(-a, -a)]*9, (1 << 34)-1)
        self.assertEqual(g[0], bounds['gram']['maximum'])
        self.assertGreater(g[0], (1 << 36)-1)

    def test_all_output_endpoint_corners_and_expression_prefixes(self):
        a, b = 1 << 17, 1 << 63
        limits = widths.layout()
        extrema = [[None, None], [None, None]]
        for corner in product((0, 1), repeat=12):
            w = [(-b, b-1)[v] for v in corner[:6]]
            x = [(-a, a-1)[v] for v in corner[6:]]
            wp = list(zip(w[::2], w[1::2]))
            xp = list(zip(x[::2], x[1::2]))
            actual = widths.sums(wp*3, xp)
            terms = ([], [])
            for k in range(3):
                terms[0].extend((w[2*k]*x[2*k], -w[2*k+1]*x[2*k+1]))
                terms[1].extend((w[2*k]*x[2*k+1], w[2*k+1]*x[2*k]))
            for axis in range(2):
                total = 0
                for term in terms[axis]:
                    self.fits(term, 84)
                    total += term
                    self.fits(total, 84)
                self.assertEqual(actual[axis::2], [total]*3)
                low, high = extrema[axis]
                extrema[axis] = [total if low is None else min(low, total),
                                 total if high is None else max(high, total)]
                self.fits(total+(1 << 23), 84)
                self.fits(widths.rounded(total), 60)
        self.assertEqual(extrema[0], limits['sum']['real'])
        self.assertEqual(extrema[1], limits['sum']['imag'])
        self.assertEqual(widths.sums([(-b, -b)]*9, [(-a, -a)]*3)[1],
                         limits['sum']['maximum'])

    def test_all_gram_offdiagonal_endpoint_corners_and_partials(self):
        a = 1 << 17
        extrema = [[None, None], [None, None]]
        for corner in product((-a, a-1), repeat=12):
            h = []
            total = [0, 0]
            for k in range(3):
                ar, ai, br, bi = corner[4*k:4*k+4]
                h.extend(((ar, ai), (br, bi), (0, 0)))
                terms = ((ar*br, ai*bi), (ar*bi, -ai*br))
                for axis in range(2):
                    self.fits(terms[axis][0], 38)
                    self.fits(sum(terms[axis]), 38)
                    total[axis] += sum(terms[axis])
                    self.fits(total[axis], 38)
            g = widths.gram(h, (1 << 34)-1)
            self.assertEqual(g[2:4], total)
            self.assertEqual(g[6:8], [total[0], -total[1]])
            for k in range(3):
                self.assertEqual(g[2*(3*k+k)+1], 0)
            for value in g:
                self.fits(value, 38)
            for axis in range(2):
                low, high = extrema[axis]
                extrema[axis] = [total[axis] if low is None else min(low, total[axis]),
                                 total[axis] if high is None else max(high, total[axis])]
        self.assertEqual(extrema[0], widths.layout()['gram']['real_offdiag'])
        self.assertEqual(extrema[1], widths.layout()['gram']['imag_offdiag'])
        self.assertEqual(min(extrema[0][0], extrema[1][0]),
                         widths.layout()['gram']['minimum'])

    def test_diagonal_endpoint_corners_and_zero(self):
        a = 1 << 17
        maximum = 0
        for corner in product((-a, a-1), repeat=6):
            h = []
            total = 0
            for k in range(3):
                re, im = corner[2*k:2*k+2]
                h.extend(((re, im), (0, 0), (0, 0)))
                total += re*re+im*im
                self.fits(total, 38)
            total += (1 << 34)-1
            self.fits(total, 38)
            self.assertEqual(widths.gram(h, (1 << 34)-1)[0], total)
            maximum = max(maximum, total)
        self.assertEqual(maximum, widths.layout()['gram']['diagonal'][1])
        self.assertEqual(widths.gram([(0, 0)]*9, 0), [0]*18)

    def test_integer_reference_random_channels_and_frames(self):
        rng = random.Random(804038)
        for _ in range(40):
            h = [(rng.randrange(-131072, 131072), rng.randrange(-131072, 131072))
                 for _ in range(9)]
            matrix = [h[k:k+3] for k in (0, 3, 6)]
            lam = rng.randrange(1, 1 << 34)
            g = widths.gram(h, lam)
            reference = []
            for row in range(3):
                for col in range(3):
                    re, im = fixed._sum(fixed._mul(fixed._conj(matrix[k][row]),
                                                   matrix[k][col]) for k in range(3))
                    reference.extend((re+(lam if row == col else 0), im))
            self.assertEqual(g, reference)
            # Binary scaling is exact, so the reference receives the same raw lambda.
            w = [v for row in fixed.weights(matrix, lam/(1 << 30)) for v in row]
            x = [(rng.randrange(-131072, 131072), rng.randrange(-131072, 131072))
                 for _ in range(3)]
            raw = widths.sums(w, x)
            actual = list(zip([widths.rounded(v, clip=True) for v in raw[::2]],
                              [widths.rounded(v, clip=True) for v in raw[1::2]]))
            self.assertEqual(actual, fixed.solve(x, matrix, lam/(1 << 30)))

    def test_rounding_ties_and_clamp_boundaries(self):
        half, scale = 1 << 23, 1 << 24
        self.assertEqual([widths.rounded(v) for v in (-half-1, -half, half-1, half)],
                         [-1, 0, 0, 1])
        for rail in (-131072, 131071):
            for offset in (-1, 0, 1):
                raw = rail*scale-half+offset
                expected = (raw+half)//scale
                self.assertEqual(widths.rounded(raw), expected)
                self.assertEqual(widths.rounded(raw, clip=True),
                                 max(-131072, min(131071, expected)))
        for name in ('minimum', 'maximum'):
            raw = widths.layout()['sum'][name]
            self.assertEqual(widths.rounded(raw, clip=True),
                             -131072 if raw < 0 else 131071)


class TestMmse3Evidence(unittest.TestCase):
    """Synthetic observation matrices exercise acceptance, not RTL execution."""

    @classmethod
    def setUpClass(cls):
        cls.model = sweep.report()
        cls.complete = copy.deepcopy(cls.model)
        cls.complete['rtl_verified'] = True
        for source, layout, active, scenario in product(
                cls.model['records'], sweep.LAYOUTS, (1, 0), sweep.SCENARIOS):
            counts = [b['count'] for b in source['banks']]
            cls.complete['rtl_equivalence'].append(dict(
                case=source['case'], layout=layout[0], active=active,
                scenario=scenario, outputs=source['outputs'], cycles=500,
                observers_verified=True, widths=list(layout[1:]),
                gram_checks=sum(counts[:2]), sum_checks=sum(counts[2:8]),
                round_checks=sum(counts[8:]), banks=copy.deepcopy(source['banks'])))
        for source, active, scenario in product(cls.model['records'], (1, 0), sweep.SCENARIOS):
            cls.complete['rtl_frozen'].append(dict(
                case=source['case'], active=active, scenario=scenario,
                old_outputs=source['outputs'], new_outputs=source['outputs'],
                old_cycles=500, new_cycles=500))
        cls.complete['rtl_directed'] = [dict(layout=l[0], active=a, passed=True,
                                           widths=list(l[1:]), **sweep.DIRECTED_COUNTS)
                                         for l, a in product(sweep.LAYOUTS, (1, 0))]
        cls.complete['rtl_parameters'] = [dict(layout=l[0], active=a, returncode=13)
                                           for l, a in product(sweep.INVALID, (1, 0))]
        cls.complete['rtl_negative'] = [dict(bench=b, tag=t, active=a, returncode=13)
                                         for b, t, a in product(('stream', 'directed'),
                                                                 sweep.TAGS, (1, 0))]
        cls.complete['rtl_lint'] = [dict(layout=l[0], warnings=0) for l in sweep.LAYOUTS]

    def reject(self, evidence):
        with self.assertRaises((RuntimeError, KeyError, TypeError, ValueError)):
            sweep.check_acceptance(evidence)

    def test_model_report_peak_and_acceptance(self):
        self.assertEqual([r['case'] for r in self.model['records']], list(sweep.CASES))
        self.assertEqual(len(self.model['records']), 9)
        peak = self.model['records'][-1]
        self.assertEqual(peak['case'], 'gram_peak')
        self.assertEqual(peak['banks'][0]['max'], widths.layout()['gram']['maximum'])
        for record in self.model['records']:
            self.assertEqual(len(record['banks']), 14)
            self.assertEqual(record['outputs'], 3*record['triples'])
            self.assertEqual([b['count'] for b in record['banks']],
                             [9, 9]+[record['triples']]*12)
            self.assertTrue(record['vector_hashes'])
        sweep.check_acceptance(self.model)
        sweep.check_acceptance(self.complete)

    def test_changed_model_records_and_unverified_claims_rejected(self):
        for key in ('bounds', 'records', 'baseline_revision'):
            changed = copy.deepcopy(self.model)
            changed[key] = None
            with self.subTest(key=key):
                self.reject(changed)
        for key in ('rtl_equivalence', 'rtl_frozen', 'rtl_parameters',
                    'rtl_directed', 'rtl_negative', 'rtl_lint'):
            changed = copy.deepcopy(self.model)
            changed[key] = [copy.deepcopy(self.complete[key][0])]
            with self.subTest(section=key):
                self.reject(changed)
        changed = copy.deepcopy(self.model)
        changed['rtl_verified'] = 1
        self.reject(changed)

    def test_all_coverage_deletions_and_duplicates_rejected(self):
        for key in ('rtl_equivalence', 'rtl_frozen', 'rtl_parameters',
                    'rtl_directed', 'rtl_negative', 'rtl_lint'):
            for mutation in ('delete', 'duplicate'):
                changed = copy.deepcopy(self.complete)
                if mutation == 'delete':
                    changed[key].pop()
                else:
                    changed[key].append(copy.deepcopy(changed[key][0]))
                with self.subTest(section=key, mutation=mutation):
                    self.reject(changed)

    def test_output_observation_width_bank_and_timing_mutations_rejected(self):
        for key, value in (('outputs', 1), ('outputs', 303.0),
                           ('cycles', 0), ('cycles', 501),
                           ('cycles', 500.0), ('observers_verified', False),
                           ('widths', [37, 84]), ('widths', [38, 83]),
                           ('widths', [38.0, 84]),
                           ('gram_checks', 0), ('sum_checks', 0), ('round_checks', 0)):
            changed = copy.deepcopy(self.complete)
            changed['rtl_equivalence'][0][key] = value
            with self.subTest(key=key, value=value):
                self.reject(changed)
        for index in range(14):
            for key in ('count', 'min', 'max'):
                changed = copy.deepcopy(self.complete)
                changed['rtl_equivalence'][0]['banks'][index][key] += 1
                with self.subTest(bank=index, key=key):
                    self.reject(changed)
        changed = copy.deepcopy(self.complete)
        changed['rtl_equivalence'][0]['banks'].pop()
        self.reject(changed)
        for key in ('min', 'max'):
            changed = copy.deepcopy(self.complete)
            # Identity Gram imaginary values are exactly zero, so equality alone
            # cannot reject this non-integer observation.
            self.assertEqual(changed['rtl_equivalence'][0]['banks'][1][key], 0)
            changed['rtl_equivalence'][0]['banks'][1][key] = 0.0
            with self.subTest(bank_type=key):
                self.reject(changed)

    def test_frozen_directed_rejections_and_lint_mutations_rejected(self):
        for key, value in (('old_cycles', 0), ('new_cycles', 501),
                           ('old_cycles', 500.0), ('new_cycles', 500.0),
                           ('old_outputs', 1), ('new_outputs', 1),
                           ('new_outputs', 303.0)):
            changed = copy.deepcopy(self.complete)
            changed['rtl_frozen'][0][key] = value
            with self.subTest(frozen=key):
                self.reject(changed)
        changed = copy.deepcopy(self.complete)
        changed['rtl_directed'][0]['passed'] = False
        self.reject(changed)
        for section in ('rtl_parameters', 'rtl_negative'):
            for value in (0, 1, -11, True, 13.0, None):
                changed = copy.deepcopy(self.complete)
                changed[section][0]['returncode'] = value
                with self.subTest(section=section, returncode=value):
                    self.reject(changed)
        for value in (1, False, 0.0):
            changed = copy.deepcopy(self.complete)
            changed['rtl_lint'][0]['warnings'] = value
            with self.subTest(warnings=value):
                self.reject(changed)

    def test_directed_counters_and_widths_are_mandatory(self):
        for key in (*sweep.DIRECTED_COUNTS, 'widths'):
            changed = copy.deepcopy(self.complete)
            del changed['rtl_directed'][0][key]
            with self.subTest(missing=key):
                self.reject(changed)
        for key, expected in sweep.DIRECTED_COUNTS.items():
            for value in (0, expected+1, float(expected), True):
                changed = copy.deepcopy(self.complete)
                changed['rtl_directed'][0][key] = value
                with self.subTest(counter=key, value=value):
                    self.reject(changed)
        for value in ([37, 84], [38, 83], [38.0, 84]):
            changed = copy.deepcopy(self.complete)
            changed['rtl_directed'][0]['widths'] = value
            with self.subTest(directed_widths=value):
                self.reject(changed)

    def test_optimized_python_cannot_emit_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)/'optimized.json'
            run = subprocess.run([sys.executable, '-O', str(ROOT/'tools/mmse3_width_sweep.py'),
                                  '--output', str(output)], capture_output=True, text=True)
            self.assertNotEqual(run.returncode, 0)
            self.assertIn('without Python optimization', run.stderr)
            self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
