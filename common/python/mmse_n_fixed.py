"""Integer N x N MMSE/ZF reference for rtl/common/mmse_n.sv (2 <= N <= 8).

API: weights(H, lam) -> NxN complex integer-pair matrix W;
solve(x, H, lam, stats=None) -> flattened output N-tuples of integer pairs.
H is NxN pairs (re, im), each component signed 18-bit scaled by 2**15; N is
taken from H. lam follows mmse3_fixed.lambda_raw (unsigned 34-bit Q30).

Unlike mmse3 (exact adjugate), widths here do not grow with N. The solver is
block-normalised fixed-point Gaussian elimination of the Hermitian normal
matrix, with real pivots and one rounding per update:

G = H^H H + L I exact, Q30, signed 40-bit components (any N <= 8).
e = bit_length(max_i G[i,i]) - 31; A = round_half_up(G, e) puts the largest
diagonal in [2**30, 2**31): A is signed 34-bit Q30, only the upper triangle
(i <= j) is stored and A[i,i] is real.
B = H^H << 24 : signed 72-bit, the right-hand side in FB = 24.
For pivot k: d = A[k,k] must be positive (signed 34-bit, real).
For i > k: m = divide(conj(A[k,i]) << 30, d) per component : signed 48-bit Q30;
A[i,j] -= round(m*A[k,j], 30) for j >= i (on the diagonal only the real part
changes and the imaginary part stays exactly zero);
B[i,j] -= round(m*B[k,j], 30) for all j.
Back substitution, k = N-1 .. 0, every column j:
acc = (B[k,j] << 30) - sum_{c>k} A[k,c]*X[c,j] (exact, signed 112-bit),
X[k,j] = divide(acc, d_k) per component : signed 72-bit.
divide is bpsk_fixed.divide: the exact quotient rounded to nearest, ties to
even (sign-symmetric), as rtl/common/fxp_divide_seq.sv computes it.
W = round_half_up(X, e+15) (left shift when negative) : signed 64-bit Q24.
Every other rounding is half up per component of the exact complex value; a zero
shift is the identity. Any value outside its width, or a nonpositive pivot,
is a configuration error (ValueError), never a wrap or a clamp.

Per observation N-tuple each output is a full signed (83+clog2(N))-bit
complex dot sum, rounded half up by 24 then saturated to signed 18 bits,
exactly as mmse3. Optional SatStats/SatTrace records the rounded values BEFORE
the clamp under output.y<i>.re/im, clamp='asym'.
"""
from bpsk_fixed import divide
from mmse3_fixed import lambda_raw, _pair, _signed

LIMIT18 = (1 << 17)-1
F = 30          # fractional bits of A and of the multipliers m
FB = 24         # fractional bits of the right-hand side / solution
GW, AW, MW, XW, ACCW, WW = 40, 34, 48, 72, 112, 64
NMIN, NMAX = 2, 8

__all__ = ['weights', 'solve', 'lambda_raw', 'output_width', 'NMIN', 'NMAX']


def output_width(n):
    return 83+(n-1).bit_length()


def _channel(H):
    try:
        n = len(H)
        if not NMIN <= n <= NMAX or any(len(row) != n for row in H):
            raise ValueError(f'H must be a square NxN matrix of integer pairs, {NMIN} <= N <= {NMAX}')
        return [[_pair(value, f'H[{i},{j}]') for j, value in enumerate(row)] for i, row in enumerate(H)]
    except TypeError as exc:
        raise ValueError('H must be a square matrix of integer pairs') from exc


def _round_shift(value, shift):
    if shift > 0:
        return (value+(1 << (shift-1))) >> shift
    return value << (-shift)


def _cmul(a, b):
    return a[0]*b[0]-a[1]*b[1], a[0]*b[1]+a[1]*b[0]


def _conj(a):
    return a[0], -a[1]


def _wide(pair, bits, name):
    return tuple(_signed(value, bits, name) for value in pair)


def _cround(pair, shift):
    return tuple(_round_shift(value, shift) for value in pair)


def weights(H, lam, trace=None):
    """trace (optional list) receives (stage, value) records of the configuration."""
    H = _channel(H); L = lambda_raw(lam); n = len(H)
    G = {}
    for i in range(n):
        for j in range(i, n):
            re = im = 0
            for k in range(n):
                p = _cmul(_conj(H[k][i]), H[k][j]); re += p[0]; im += p[1]
            G[i, j] = _wide((re+(L if i == j else 0), im), GW, 'Gram component')
    dmax = max(G[i, i][0] for i in range(n))
    if dmax <= 0:
        raise ValueError('Singular normal matrix (zero diagonal)')
    e = dmax.bit_length()-31
    A = {key: _wide(_cround(value, e), AW, 'Normalised Gram component') for key, value in G.items()}
    B = [[_wide((H[j][i][0] << FB, -H[j][i][1] << FB), XW, 'Right-hand side') for j in range(n)]
         for i in range(n)]
    pivots = []
    for k in range(n):
        d = A[k, k][0]
        if d <= 0 or A[k, k][1] != 0:
            raise ValueError('Singular or nonpositive pivot')
        pivots.append(d)
        if trace is not None:
            trace.append(('pivot', k, d))
        for i in range(k+1, n):
            a = _conj(A[k, i])
            m = _wide((divide(a[0] << F, d), divide(a[1] << F, d)), MW, 'Multiplier')
            for j in range(i, n):
                p = _cround(_cmul(m, A[k, j]), F)
                if i == j:
                    A[i, i] = _wide((A[i, i][0]-p[0], 0), AW, 'Updated pivot')
                else:
                    A[i, j] = _wide((A[i, j][0]-p[0], A[i, j][1]-p[1]), AW, 'Updated Gram component')
            for j in range(n):
                p = _cround(_cmul(m, B[k][j]), F)
                B[i][j] = _wide((B[i][j][0]-p[0], B[i][j][1]-p[1]), XW, 'Updated right-hand side')
    X = B
    for k in reversed(range(n)):
        d = pivots[k]
        for j in range(n):
            re, im = X[k][j][0] << F, X[k][j][1] << F
            for c in range(k+1, n):
                p = _cmul(A[k, c], X[c][j]); re -= p[0]; im -= p[1]
            _wide((re, im), ACCW, 'Back-substitution accumulator')
            X[k][j] = _wide((divide(re, d), divide(im, d)), XW, 'Solution')
    return [[_wide(_cround(X[i][j], e+15), WW, 'W coefficient') for j in range(n)] for i in range(n)]


def solve(x, H, lam, stats=None):
    n = len(H) if hasattr(H, '__len__') else 0
    W = weights(H, lam); YW = output_width(n)
    try:
        if len(x) % n:
            raise ValueError(f'MMSE{n} needs whole observation {n}-tuples')
        observations = [_pair(value, f'observation[{i}]') for i, value in enumerate(x)]
    except TypeError as exc:
        raise ValueError('MMSE needs a sequence of observation tuples') from exc
    out = []
    for start in range(0, len(observations), n):
        for i in range(n):
            re = im = 0
            for j in range(n):
                p = _cmul(W[i][j], observations[start+j]); re += p[0]; im += p[1]
            rounded = [_round_shift(value, 24) for value in _wide((re, im), YW, 'Output accumulator')]
            if stats is None:
                out.append(tuple(max(-LIMIT18-1, min(LIMIT18, value)) for value in rounded))
            else:
                out.append((stats.record(f'output.y{i}.re', rounded[0], LIMIT18, clamp='asym'),
                            stats.record(f'output.y{i}.im', rounded[1], LIMIT18, clamp='asym')))
    return out
