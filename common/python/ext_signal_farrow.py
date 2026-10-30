"""DSP-FARROW: causal Lagrange Farrow fractional-delay interpolator.

Output times t = t0 + k*step live on an integer Q<frac_bits> grid (t0 = 0).
Output t is emitted once n = ceil(t) has been accepted, and is evaluated as
    y(t) = sum_j h_j(mu) x[n-j],  mu = n - t in [0,1),  h_j Lagrange on nodes 0..degree.
Branch polynomials c_k(n) = sum_j a[j][k] x[n-j] are evaluated with Horner in mu.
Coefficients are generated exactly (Fractions) at construction; no rounded tables.
"""
from collections import deque
from fractions import Fraction
import math
import numbers

Q_COEF = 27
S_MIN, S_MAX = -(1 << 17), (1 << 17) - 1          # signed18 samples/outputs
I64_MIN, I64_MAX = -(1 << 63), (1 << 63) - 1
I32_MIN, I32_MAX = -(1 << 31), (1 << 31) - 1


def _sat(v, lo, hi):
    return lo if v < lo else (hi if v > hi else v)


def _round_halfup(fr, bits):
    """Exact Fraction -> int, scaled by 2**bits, ties toward +infinity."""
    return math.floor(fr * (1 << bits) + Fraction(1, 2))


def lagrange_coeffs(degree):
    """Exact a[j][k]: h_j(mu) = sum_k a[j][k] mu^k, h_j(l)=delta_jl for nodes l=0..degree."""
    table = []
    for j in range(degree + 1):
        poly, denom = [Fraction(1)], Fraction(1)
        for l in range(degree + 1):
            if l == j:
                continue
            new = [Fraction(0)] * (len(poly) + 1)
            for k, c in enumerate(poly):
                new[k + 1] += c
                new[k] -= l * c
            poly, denom = new, denom * (j - l)
        table.append([c / denom for c in poly])
    return table


class Farrow:
    def __init__(self, degree=3, step=1.0, frac_bits=16, fixed=False):
        if isinstance(degree, bool) or not isinstance(degree,numbers.Integral) or degree not in (3, 4):
            raise ValueError("degree must be 3 or 4")
        if isinstance(frac_bits, bool) or not isinstance(frac_bits, int) or not 16 <= frac_bits <= 32:
            raise ValueError("frac_bits must be an int in [16, 32]")
        if type(fixed) is not bool:raise ValueError("fixed must be bool")
        self.degree, self.frac_bits, self.fixed = int(degree), frac_bits, fixed
        exact = lagrange_coeffs(degree)
        if self.fixed:
            self._q = [[_round_halfup(a, Q_COEF) for a in row] for row in exact]
            if any(not I32_MIN <= v <= I32_MAX for row in self._q for v in row):
                raise ValueError("Q27 coefficient overflow")
        else:
            self._f = [[float(a) for a in row] for row in exact]
        self._step = self._quantize_step(step)
        self.reset()

    # ---- validation (no state mutation) ----
    def _quantize_step(self, step):
        if isinstance(step, bool) or not isinstance(step, (int, float, Fraction)):
            raise ValueError("step must be real")
        if isinstance(step, float) and not math.isfinite(step):
            raise ValueError("step must be finite")
        fr = Fraction(step)
        if not Fraction(1, 16) <= fr <= 16:
            raise ValueError("step outside [1/16, 16]")
        return _round_halfup(fr, self.frac_bits)

    def _validate(self, s):
        if self.fixed:
            if not isinstance(s,numbers.Number) and hasattr(s,"__len__") and len(s) == 2:
                i, q = s
            else:
                i, q = s, 0
            for v in (i, q):
                if isinstance(v, bool) or not isinstance(v, numbers.Integral) or not S_MIN <= v <= S_MAX:
                    raise ValueError("fixed sample must be signed18 int or IQ pair")
            return (int(i), int(q))
        if isinstance(s, bool) or not isinstance(s, numbers.Number):
            raise ValueError("float sample must be real or complex")
        c = complex(s)
        if not (math.isfinite(c.real) and math.isfinite(c.imag)):
            raise ValueError("non-finite sample")
        return c

    # ---- public API ----
    @property
    def next_time(self):
        """Next scheduled output time, integer Q<frac_bits>."""
        return self._t

    @property
    def count(self):
        return self._count

    def configure_rate(self, step):
        self._step = self._quantize_step(step)   # raises before mutation; next_time preserved

    def reset(self):
        self._hist = deque(maxlen=self.degree + 2)
        self._count = 0
        self._t = 0

    def push(self, sample, accept=True):
        if type(accept) is not bool:raise ValueError("accept must be bool")
        x = self._validate(sample)
        if not accept:
            return []
        self._hist.append(x)
        n = self._count
        self._count += 1
        out = []
        F = self.frac_bits
        while True:
            nn = -((-self._t) >> F)              # ceil(t / 2**F)
            if nn > n:
                break
            out.append(self._eval((nn << F) - self._t))
            self._t += self._step
        return out

    def _taps(self, pad):
        """x[n-j], j=0..degree, newest first; negative time is zero."""
        h = list(self._hist)
        return [h[-1 - j] if j < len(h) else pad for j in range(self.degree + 1)]

    def _eval(self, mu_q):
        if not self.fixed:
            mu = mu_q / (1 << self.frac_bits)
            xs = self._taps(0j)
            c = [sum(self._f[j][k] * xs[j] for j in range(self.degree + 1))
                 for k in range(self.degree + 1)]
            acc = c[-1]
            for k in range(self.degree - 1, -1, -1):
                acc = acc * mu + c[k]
            return acc
        return (self._fixed_branch([s[0] for s in self._taps((0, 0))], mu_q),
                self._fixed_branch([s[1] for s in self._taps((0, 0))], mu_q))

    def _fixed_branch(self, xs, mu_q):
        F, D = self.frac_bits, self.degree
        c = []
        for k in range(D + 1):
            acc = sum(self._q[j][k] * xs[j] for j in range(D + 1))
            c.append(_sat(acc, I64_MIN, I64_MAX))
        acc = c[D]
        for k in range(D - 1, -1, -1):
            acc = _sat(((acc * mu_q + (1 << (F - 1))) >> F) + c[k], I64_MIN, I64_MAX)
        return _sat((acc + (1 << (Q_COEF - 1))) >> Q_COEF, S_MIN, S_MAX)
