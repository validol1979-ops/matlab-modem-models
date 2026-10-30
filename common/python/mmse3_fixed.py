"""Integer 3x3 MMSE/ZF reference for rtl/common/mmse3.sv.

API: weights(H, lam) -> 3x3 complex integer-pair matrix W;
solve(x, H, lam, stats=None) -> flattened output triples of integer pairs.
H is 3x3 pairs (re, im), each component signed 18-bit scaled by 2**15.
lam is a finite nonnegative real scalar; L=round(lam*2**30) must fit unsigned
34 bits (nearest-even, as Python round). Observations use the same signed
18-bit / 2**15 format. Only output samples saturate to [-131072, 131071].

Configuration arithmetic is exact integer complex arithmetic:
G = H^H H + L I : Q30, signed 40-bit components.
C = cofactors(G), adj(G)=C^T : Q60, signed 84-bit components.
det = sum(G[0,j]*C[0,j]) : Q90, signed 128-bit, real and strictly positive.
M = adj(G) H^H : Q75, signed 106-bit components.
r,z = beam_fixed.reciprocal(det) : nearest-even round(2**z/det),
z = 22 + bit_length(det), 2**22 <= r <= 2**23.
W = round_half_up(M*r, z-39) : signed 64-bit / 2**24 components.
Positive shifts round half up, shift zero is exact identity, negative shifts
are exact left shifts. An out-of-range W is a configuration error, not a clamp.
Per observation triple each output is a full signed 85-bit complex dot sum,
rounded half up by 24 then saturated to signed 18 bits. Internal widths are
checked without wrapping or clipping. No floating matrix algebra is used.

Optional SatStats/SatTrace records rounded values BEFORE the output clamp under
output.y0.re/im, output.y1.re/im, output.y2.re/im, clamp='asym'. Equal rail values
are evaluations, not events. Instrumented and plain outputs are bit-identical.
"""
import math
from numbers import Integral, Real
from beam_fixed import reciprocal

LIMIT18 = (1 << 17)-1


def _signed(value, bits, name):
    if not -(1 << (bits-1)) <= value < (1 << (bits-1)):
        raise ValueError(f'{name} outside signed {bits}-bit range')
    return value


def _pair(value, name):
    try:
        if len(value) != 2:
            raise ValueError(name+' must be a complex integer pair')
        components = []
        for component in value:
            if not isinstance(component, Integral) or isinstance(component, bool):
                raise ValueError(name+' components must be integers')
            components.append(_signed(int(component), 18, name))
    except TypeError as exc:
        raise ValueError(name+' must be a complex integer pair') from exc
    return tuple(components)


def _channel(H):
    try:
        if len(H) != 3 or any(len(row) != 3 for row in H):
            raise ValueError('H must be a 3x3 matrix of integer pairs')
        return [[_pair(value, f'H[{i},{j}]') for j, value in enumerate(row)] for i, row in enumerate(H)]
    except TypeError as exc:
        raise ValueError('H must be a 3x3 matrix of integer pairs') from exc


def lambda_raw(lam):
    if not isinstance(lam, Real) or isinstance(lam, bool):
        raise ValueError('lambda must be a finite nonnegative real scalar')
    try:
        value = float(lam)
    except (ValueError, OverflowError) as exc:
        raise ValueError('lambda must be a finite nonnegative real scalar') from exc
    if not math.isfinite(value) or value < 0 or value > 16:
        raise ValueError('lambda must be finite, nonnegative and fit unsigned 34-bit Q30')
    raw = int(round(value*(1 << 30)))
    if not 0 <= raw < (1 << 34):
        raise ValueError('Rounded lambda outside unsigned 34-bit Q30 range')
    return raw


def _mul(a, b):
    return a[0]*b[0]-a[1]*b[1], a[0]*b[1]+a[1]*b[0]


def _sum(values):
    re = im = 0
    for a, b in values:
        re += a; im += b
    return re, im


def _conj(a):
    return a[0], -a[1]


def _round_shift(value, shift):
    if shift > 0:
        return (value+(1 << (shift-1))) >> shift
    return value << (-shift)


def _wide(pair, bits, name):
    return tuple(_signed(value, bits, name) for value in pair)


def weights(H, lam):
    H = _channel(H); L = lambda_raw(lam)
    gram = []
    for i in range(3):
        row = []
        for j in range(3):
            re, im = _sum(_mul(_conj(H[k][i]), H[k][j]) for k in range(3))
            row.append(_wide((re+(L if i == j else 0), im), 40, 'Gram component'))
        gram.append(row)
    cofactor = []
    for i in range(3):
        row = []
        a, b = [k for k in range(3) if k != i]
        for j in range(3):
            c, d = [k for k in range(3) if k != j]
            left = _mul(gram[a][c], gram[b][d]); right = _mul(gram[a][d], gram[b][c])
            sign = -1 if (i+j) % 2 else 1
            row.append(_wide((sign*(left[0]-right[0]), sign*(left[1]-right[1])), 84, 'Cofactor component'))
        cofactor.append(row)
    det = _wide(_sum(_mul(gram[0][j], cofactor[0][j]) for j in range(3)), 128, 'Determinant')
    if det[1] != 0 or det[0] <= 0:
        raise ValueError('Singular or nonpositive normal matrix determinant')
    r, z = reciprocal(det[0])
    W = []
    for i in range(3):
        row = []
        for j in range(3):
            # adj[i,k] = cofactor[k,i], H^H[k,j] = conj(H[j,k]).
            m = _wide(_sum(_mul(cofactor[k][i], _conj(H[j][k])) for k in range(3)), 106, 'M component')
            row.append(_wide(tuple(_round_shift(component*r, z-39) for component in m), 64, 'W coefficient'))
        W.append(row)
    return W


def solve(x, H, lam, stats=None):
    try:
        if len(x) % 3:
            raise ValueError('MMSE3 needs whole observation triples')
        observations = [_pair(value, f'observation[{i}]') for i, value in enumerate(x)]
    except TypeError as exc:
        raise ValueError('MMSE3 needs a sequence of observation triples') from exc
    W = weights(H, lam); out = []
    for start in range(0, len(observations), 3):
        for i in range(3):
            dot = _wide(_sum(_mul(W[i][j], observations[start+j]) for j in range(3)), 85, 'Output accumulator')
            rounded = [_round_shift(value, 24) for value in dot]
            if stats is None:
                out.append(tuple(max(-LIMIT18-1, min(LIMIT18, value)) for value in rounded))
            else:
                out.append((stats.record(f'output.y{i}.re', rounded[0], LIMIT18, clamp='asym'),
                            stats.record(f'output.y{i}.im', rounded[1], LIMIT18, clamp='asym')))
    return out
