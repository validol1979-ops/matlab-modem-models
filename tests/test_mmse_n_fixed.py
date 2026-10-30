"""Integer N x N MMSE against independent floating solves, the exact mmse3 model and raw-bit examples."""
from pathlib import Path
import sys
import unittest
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'common/python'))
import mmse_n_fixed as m
import mmse3_fixed as m3
from research_core import run
from sat_diag import SatTrace

SIZES = range(m.NMIN, m.NMAX+1)


def quantize(values):
    a = np.asarray(values, complex).ravel()
    data = np.rint(np.c_[a.real, a.imag]*32768).astype(np.int64)
    if np.any((data < -131072) | (data > 131071)):
        raise ValueError('Test fixture outside sample format')
    return [tuple(map(int, row)) for row in data]


def complex_of(values):
    return np.asarray([complex(re, im)/32768 for re, im in values])


def matrix(H):
    H = np.asarray(H, complex); n = len(H); values = quantize(H)
    return [values[k*n:(k+1)*n] for k in range(n)]


def raw_diagonal(values):
    n = len(values)
    return [[(int(values[i]), 0) if i == j else (0, 0) for j in range(n)] for i in range(n)]


def weights_float(W):
    return np.array([[complex(re, im)/2**24 for re, im in row] for row in W])


class TestMmseNFixed(unittest.TestCase):
    def compare(self, H, lam, observations, budget=3e-5):
        raw_H = matrix(H); n = len(raw_H)
        Hq = complex_of([v for row in raw_H for v in row]).reshape(n, n)
        raw_x = quantize(observations); xq = complex_of(raw_x).reshape(-1, n)
        rounded_lambda = m.lambda_raw(lam)/2**30
        expected = np.linalg.solve(Hq.conj().T@Hq+rounded_lambda*np.eye(n), Hq.conj().T@xq.T).T.ravel()
        independent = run('mimo', [n, rounded_lambda], xq.ravel(), Hq.ravel())
        np.testing.assert_allclose(independent, expected, rtol=0, atol=1e-12)
        self.assertLess(np.max(abs(expected.real)), 3.9)
        self.assertLess(np.max(abs(expected.imag)), 3.9)
        values = m.solve(raw_x, raw_H, lam)
        error = float(np.max(abs(complex_of(values)-expected)))
        self.assertLess(error, budget)
        return error

    def test_identity_exact_for_every_size(self):
        for n in SIZES:
            with self.subTest(n=n):
                H = raw_diagonal([32768]*n)
                expected = [[(1 << 24, 0) if i == j else (0, 0) for j in range(n)] for i in range(n)]
                self.assertEqual(m.weights(H, 0), expected)
                rows = ([(131071, -131072), (32768, -7), (-17, 999)]*n)[:2*n]
                self.assertEqual(m.solve(rows, H, 0), rows)
                self.compare(np.eye(n), .1, np.array([np.linspace(-.75, .75, n)+.2j]))

    def test_tiny_and_extreme_diagonals_use_exact_shifts(self):
        for n in SIZES:
            with self.subTest(n=n):
                self.assertEqual(m.weights(raw_diagonal([1]*n), 0),
                                 [[(1 << 39, 0) if i == j else (0, 0) for j in range(n)] for i in range(n)])
                tiny = raw_diagonal([1]*n)
                rows = [(1, -1), (-2, 3)]*n
                self.assertEqual(m.solve(rows[:n], tiny, 0), [(32768*re, 32768*im) for re, im in rows[:n]])
                H = [[(0, -131072) if i == j else (0, 0) for j in range(n)] for i in range(n)]
                self.assertEqual(m.weights(H, 0),
                                 [[(0, 1 << 22) if i == j else (0, 0) for j in range(n)] for i in range(n)])
                self.assertEqual(m.solve([(131071, -131072)]*n, H, 0), [(32768, 32768)]*n)
                self.assertEqual(m.weights(raw_diagonal([0]*n), 1/2**30), [[(0, 0)]*n for _ in range(n)])

    def test_full_scale_channel_fits_fixed_widths(self):
        # Every component -131072 gives the largest Gram magnitude; the lambda keeps it regular.
        for n in SIZES:
            with self.subTest(n=n):
                H = [[(-131072, -131072)]*n for _ in range(n)]
                W = m.weights(H, 15.)
                self.assertTrue(all(-(1 << 63) <= v < (1 << 63) for row in W for pair in row for v in pair))

    def test_matches_exact_mmse3_within_one_weight_lsb_scale(self):
        rng = np.random.default_rng(29)
        for index in range(40):
            H = matrix(np.eye(3)+(rng.normal(size=(3, 3))+1j*rng.normal(size=(3, 3)))*.15)
            lam = (0, .001, .1, 1.)[index % 4]
            with self.subTest(index=index):
                difference = np.max(abs(weights_float(m.weights(H, lam))-weights_float(m3.weights(H, lam))))
                self.assertLess(difference, 64/2**24)
                x = [tuple(map(int, row)) for row in rng.integers(-40000, 40000, (30, 2))]
                ours = np.array(m.solve(x, H, lam)); exact = np.array(m3.solve(x, H, lam))
                self.assertLessEqual(int(np.max(abs(ours-exact))), 1)

    def test_random_complex_reference_without_skips(self):
        rng = np.random.default_rng(41)
        for n in SIZES:
            for index in range(12):
                H = np.eye(n)+(rng.normal(size=(n, n))+1j*rng.normal(size=(n, n)))*.08
                observations = (rng.normal(size=(10, n))+1j*rng.normal(size=(10, n)))*.15
                with self.subTest(n=n, index=index):
                    self.compare(H, (0, .001, .1)[index % 3], observations)

    def test_conditioned_and_regularised_singular(self):
        rng = np.random.default_rng(7)
        for n in SIZES:
            H = np.eye(n)+(rng.normal(size=(n, n))+1j*rng.normal(size=(n, n)))*.05
            H[:, 1] = H[:, 0]+.05*H[:, 1]
            observations = (rng.normal(size=(16, n))+1j*rng.normal(size=(16, n)))*.02
            with self.subTest(n=n, case='conditioned'):
                self.assertGreater(np.linalg.cond(H), 20)
                self.compare(H, 0, observations)
            with self.subTest(n=n, case='regularised'):
                self.compare(np.ones((n, n), complex), .1, observations*10)

    def test_output_clamps_events_evaluations_and_bit_identity(self):
        for n in (2, 5, 8):
            with self.subTest(n=n):
                half = raw_diagonal([16384]*n)
                rows = ([(65536, 65535), (-65536, -65537), (65535, -65537)]*n)[:n]
                stats = SatTrace(); instrumented = m.solve(rows, half, 0, stats)
                self.assertEqual(instrumented, m.solve(rows, half, 0))
                self.assertEqual(instrumented[:3], [(131071, 131070), (-131072, -131072), (131070, -131072)][:n])
                self.assertEqual(sum(stats.evaluations.values()), 2*n)
                self.assertEqual(stats.counts['output.y0.re'], {'pos': 1, 'neg': 0})
                self.assertEqual(stats.counts['output.y1.im'], {'pos': 0, 'neg': 1})

    def test_invalid_configs_and_dynamic_range_are_rejected(self):
        for H in [[], [[(1, 0)]], raw_diagonal([32768]*9), [[(1, 0)]*2]*3, [[(1., 0)]*3]*3,
                  [[(True, 0)]*3]*3, [[(131072, 0)]*3]*3, [[(-131073, 0)]*3]*3,
                  [[(1,) for _ in range(3)] for _ in range(3)], np.eye(3, dtype=complex)]:
            with self.subTest(H=H), self.assertRaises(ValueError):
                m.weights(H, 0)
        identity = raw_diagonal([32768]*4)
        for lam in (-1., float('nan'), float('inf'), 16., 10**1000, 1j, True, '0'):
            with self.subTest(lam=lam), self.assertRaises(ValueError):
                m.weights(identity, lam)
        for n in SIZES:
            with self.subTest(n=n):
                with self.assertRaisesRegex(ValueError, 'Singular'):
                    m.weights(matrix(np.ones((n, n))), 0)
                with self.assertRaisesRegex(ValueError, 'Singular'):
                    m.weights(raw_diagonal([0]*n), .5/2**30)
                # A 1-LSB channel next to a full-scale one is below the normalised resolution.
                weak = raw_diagonal([131071]+[1]*(n-1))
                with self.assertRaisesRegex(ValueError, 'Singular'):
                    m.weights(weak, 0)
        # det(H_raw)=1 and the inverse contains 131071**2: its Q24 weight exceeds 64 bits.
        N = 131071
        H = [[(N, 0), (1, 0), (0, 0)], [(0, 0), (N, 0), (1, 0)], [(1, 0), (0, 0), (0, 0)]]
        with self.assertRaises(ValueError):
            m.weights(H, 0)

    def test_invalid_observations(self):
        H = raw_diagonal([32768]*4)
        for observations in [[(0, 0)], [(0, 0)]*5, [(1., 0)]*4, [(131072, 0)]*4,
                             [(0, -131073)]*4, [(float('nan'), 0)]*4, [1, 2, 3, 4], None]:
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                m.solve(observations, H, 0)
        self.assertEqual(m.solve([], H, 0), [])


if __name__ == '__main__':
    unittest.main()
