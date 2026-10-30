"""Integer MMSE3 against independent floating solves and exact raw-bit examples."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
import mmse3_fixed as m
from research_core import run
from sat_diag import SatTrace


def quantize(values):
    a = np.asarray(values, complex).ravel()
    data = np.rint(np.c_[a.real, a.imag]*32768).astype(np.int64)
    if np.any((data < -131072) | (data > 131071)):
        raise ValueError('Test fixture outside sample format')
    return [tuple(map(int, row)) for row in data]


def complex_of(values):
    return np.asarray([complex(re, im)/32768 for re, im in values])


def matrix(H):
    values = quantize(H)
    return [values[k:k+3] for k in (0, 3, 6)]


def raw_diagonal(values):
    return [[(int(values[i]), 0) if i == j else (0, 0) for j in range(3)] for i in range(3)]


class TestMmse3Fixed(unittest.TestCase):
    def compare(self, H, lam, observations):
        raw_H = matrix(H); Hq = complex_of([v for row in raw_H for v in row]).reshape(3, 3)
        raw_x = quantize(observations); xq = complex_of(raw_x).reshape(-1, 3)
        rounded_lambda = m.lambda_raw(lam)/2**30
        expected = np.linalg.solve(Hq.conj().T@Hq+rounded_lambda*np.eye(3), Hq.conj().T@xq.T).T.ravel()
        independent = run('mimo', [3, rounded_lambda], xq.ravel(), Hq.ravel())
        np.testing.assert_allclose(independent, expected, rtol=0, atol=1e-13)
        self.assertLess(np.max(abs(expected.real)), 3.9)
        self.assertLess(np.max(abs(expected.imag)), 3.9)
        values = m.solve(raw_x, raw_H, lam)
        self.assertLess(np.max(abs(complex_of(values)-expected)), 3e-5)
        return float(np.max(abs(complex_of(values)-expected)))

    def test_identity_exact_and_regularization_reference(self):
        H = raw_diagonal([32768]*3)
        rows = [(131071, -131072), (32768, -7), (-17, 999)]*3
        self.assertEqual(m.solve(rows, H, 0), rows)
        expected = [[(1 << 24, 0) if i == j else (0, 0) for j in range(3)] for i in range(3)]
        self.assertEqual(m.weights(H, 0), expected)
        self.compare(np.eye(3), .1, np.array([[1+.2j, -.25+.1j, .75-.5j]]))

    def test_complex_well_conditioned_and_regularized_singular(self):
        rng = np.random.default_rng(11)
        H = np.array([[1+.2j, .3-.1j, -.1+.05j], [.1-.2j, .9+.1j, .2+.1j], [.2+.1j, -.1+.2j, 1.1-.15j]])
        observations = (rng.normal(size=(128, 3))+1j*rng.normal(size=(128, 3)))/4
        for lam in (0., .025, 1.):
            with self.subTest(lam=lam):
                self.compare(H, lam, observations)
        self.compare(np.ones((3, 3), complex), .1, observations)

    def test_random_complex_reference_without_skips(self):
        rng = np.random.default_rng(41)
        for index in range(30):
            H = np.eye(3)+(rng.normal(size=(3, 3))+1j*rng.normal(size=(3, 3)))*.12
            observations = (rng.normal(size=(20, 3))+1j*rng.normal(size=(20, 3)))*.15
            with self.subTest(index=index):
                self.compare(H, (0, .001, .1)[index % 3], observations)

    def test_tiny_identity_negative_and_zero_shifts(self):
        tiny = raw_diagonal([1, 1, 1])
        with patch.object(m, 'reciprocal', wraps=m.reciprocal) as inverse:
            W = m.weights(tiny, 0)
        self.assertEqual(inverse.call_args.args, (1,))
        self.assertEqual(W, [[(1 << 39, 0) if i == j else (0, 0) for j in range(3)] for i in range(3)])
        self.assertEqual(m.solve([(1, -1), (-2, 3), (0, 0)], tiny, 0),
                         [(32768, -32768), (-65536, 98304), (0, 0)])
        self.compare(np.eye(3)/32768, 0, np.array([[1-1j, -2+3j, 0]])/32768)
        zero_shift = raw_diagonal([4, 4, 16])
        with patch.object(m, 'reciprocal', wraps=m.reciprocal) as inverse:
            W = m.weights(zero_shift, 0)
        self.assertEqual(inverse.call_args.args, (65536,))
        self.assertEqual([W[i][i] for i in range(3)], [(1 << 37, 0), (1 << 37, 0), (1 << 35, 0)])
        self.assertEqual(m.solve([(4, 0), (0, -4), (16, 16)], zero_shift, 0), [(32768, 0), (0, -32768), (32768, 32768)])

    def test_exact_complex_inverse_and_output_order(self):
        H = matrix([[1, 1j, 0], [0, 1, 0], [0, 0, 1]])
        expected_W = [[(1 << 24, 0), (0, -(1 << 24)), (0, 0)],
                      [(0, 0), (1 << 24, 0), (0, 0)], [(0, 0), (0, 0), (1 << 24, 0)]]
        self.assertEqual(m.weights(H, 0), expected_W)
        observations = [(32768, 0), (0, 32768), (65536, -65536)]
        self.assertEqual(m.solve(observations, H, 0), [(65536, 0), (0, 32768), (65536, -65536)])
        self.assertEqual(m.solve([], H, 0), [])

    def test_minimum_channel_component_conjugation_is_not_clipped(self):
        # Conjugating raw -131072 needs +131072 internally: retain that exact
        # value even though the original H input component is signed 18-bit.
        H = [[(0, -131072) if i == j else (0, 0) for j in range(3)] for i in range(3)]
        W = m.weights(H, 0)
        self.assertEqual(W, [[(0, 1 << 22) if i == j else (0, 0) for j in range(3)] for i in range(3)])
        self.assertEqual(m.solve([(131071, -131072)]*3, H, 0), [(32768, 32768)]*3)
        self.compare(np.eye(3)*(-4j), 0, np.array([[.3+.2j, -.4-.1j, .5-.6j]]))

    def test_output_clamps_events_evaluations_and_bit_identity(self):
        rows = [(131071, -131072), (-131072, 131071), (0, 1)]
        stats = SatTrace()
        self.assertEqual(m.solve(rows, raw_diagonal([32768]*3), 0, stats), rows)
        self.assertEqual(stats.total(), 0)
        self.assertEqual(stats.evaluations, {f'output.y{i}.{axis}': 1 for i in range(3) for axis in ('re', 'im')})
        half = raw_diagonal([16384]*3)
        rows = [(65536, 65535), (-65536, -65537), (65535, -65537)]
        stats = SatTrace(); instrumented = m.solve(rows, half, 0, stats)
        self.assertEqual(instrumented, m.solve(rows, half, 0))
        self.assertEqual(instrumented, [(131071, 131070), (-131072, -131072), (131070, -131072)])
        self.assertEqual(stats.counts, {'output.y0.re': {'pos': 1, 'neg': 0},
                                       'output.y1.im': {'pos': 0, 'neg': 1},
                                       'output.y2.im': {'pos': 0, 'neg': 1}})
        self.assertEqual(sum(stats.evaluations.values()), 6)

    def test_invalid_configs_and_out_of_range_weight_are_rejected(self):
        identity = raw_diagonal([32768]*3)
        for H in [[], identity[:2], [[(1, 0)]*2]*3, [[(1., 0)]*3]*3, [[(True, 0)]*3]*3,
                  [[(131072, 0)]*3]*3, [[(-131073, 0)]*3]*3, [[(1,) for _ in range(3)] for _ in range(3)], np.eye(3, dtype=complex)]:
            with self.subTest(H=H), self.assertRaises(ValueError):
                m.weights(H, 0)
        for lam in (-1., float('nan'), float('inf'), 16., 10**1000, 1j, True, '0'):
            with self.subTest(lam=lam), self.assertRaises(ValueError):
                m.weights(identity, lam)
        self.assertEqual(m.lambda_raw(((1 << 34)-1)/2**30), (1 << 34)-1)
        self.assertEqual(m.lambda_raw(.5/2**30), 0)
        with self.assertRaisesRegex(ValueError, 'Singular'):
            m.weights(matrix(np.ones((3, 3))), 0)
        with self.assertRaisesRegex(ValueError, 'Singular'):
            m.weights(raw_diagonal([0]*3), .5/2**30)
        self.assertEqual(m.weights(raw_diagonal([0]*3), 1/2**30), [[(0, 0)]*3 for _ in range(3)])
        # det(H_raw)=1, inverse contains N**2; its Q24 coefficient exceeds 64 bits.
        N = 131071
        H = [[(N, 0), (1, 0), (0, 0)], [(0, 0), (N, 0), (1, 0)], [(1, 0), (0, 0), (0, 0)]]
        with self.assertRaisesRegex(ValueError, 'W coefficient outside signed 64'):
            m.weights(H, 0)

    def test_invalid_observations(self):
        H = raw_diagonal([32768]*3)
        for observations in [[(0, 0)], [(0, 0)]*4, [(1., 0)]*3, [(131072, 0)]*3,
                             [(0, -131073)]*3, [(float('nan'), 0)]*3, [1, 2, 3], None]:
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                m.solve(observations, H, 0)


if __name__ == '__main__':
    unittest.main()
