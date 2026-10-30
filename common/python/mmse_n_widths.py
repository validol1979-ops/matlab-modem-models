"""Integer bounds and independent arithmetic for the MMSE_N width sweep.

Channels and weights are flat row-major lists of N*N (real, imaginary)
pairs.  Lambda is the raw unsigned Q30 integer, not a real scalar.  The
weight domain is all signed 64-bit values; no claim of configuration
reachability is needed for these output-accumulator bounds.
"""
from numbers import Integral


def _bits(low, high):
    width = 1
    while low < -(1 << (width - 1)) or high >= 1 << (width - 1):
        width += 1
    return width


def _interval(low, high):
    return {"minimum": low, "maximum": high,
            "required_bits": _bits(low, high)}


def size(n):
    return _integer(n, 2, 8, "N")


def layout(n):
    n = size(n)
    """Return exact extrema, including each real/imaginary component domain."""
    a, b = 1 << 17, 1 << 63
    gram_real = [-2*n*a*(a-1), 2*n*a*a]
    gram_imag = [-2*n*a*a+n*a, 2*n*a*a-n*a]
    diagonal = [0, (2*n+1)*a*a-1]
    sum_real = [-2*n*a*b+n*a, 2*n*a*b-n*a]
    sum_imag = [-2*n*a*b+2*n*a, 2*n*a*b]
    low, high = sum_real[0], sum_imag[1]
    half = 1 << 23
    return {
        "n": n,
        "ports": {"h_bits": 18, "lambda_bits": 34, "weight_bits": 64,
                  "output_bits": 18, "shift": 24},
        "gram": {**_interval(gram_imag[0], diagonal[1]),
                 "real_offdiag": gram_real, "imag_offdiag": gram_imag,
                 "diagonal": diagonal},
        "sum": {**_interval(low, high), "real": sum_real, "imag": sum_imag},
        "round_add": _interval(low+half, high+half),
        "rounded": _interval((low+half) >> 24, (high+half) >> 24),
    }


def _integer(value, low, high, name):
    if not isinstance(value, Integral) or isinstance(value, bool):
        raise ValueError(name+" must be an integer")
    value = int(value)
    if not low <= value <= high:
        raise ValueError(name+" outside its input range")
    return value


def _pairs(values, count, bits, name):
    try:
        if len(values) != count:
            raise ValueError(f"{name} needs {count} complex pairs")
        result = []
        for pair in values:
            if len(pair) != 2:
                raise ValueError(name+" needs complex pairs")
            result.append(tuple(_integer(v, -(1 << (bits-1)),
                                         (1 << (bits-1))-1, name) for v in pair))
        return result
    except TypeError as exc:
        raise ValueError(name+" needs complex pairs") from exc


def gram(channel, lambda_raw, n):
    n = size(n)
    """Exact H^H H + lambda I; return 2*N*N interleaved row-major components."""
    h = _pairs(channel, n*n, 18, "H")
    lam = _integer(lambda_raw, 0, (1 << 34)-1, "lambda")
    result = []
    for row in range(n):
        for col in range(n):
            real = lam if row == col else 0
            imag = 0
            for k in range(n):
                ar, ai = h[n*k+row]
                br, bi = h[n*k+col]
                real += ar*br + ai*bi
                imag += ar*bi - ai*br
            result.extend((real, imag))
    return result


def sums(weights, observations, n):
    n = size(n)
    """Exact W*x; return 2*N interleaved real/imaginary components."""
    w = _pairs(weights, n*n, 64, "W")
    x = _pairs(observations, n, 18, "observations")
    result = []
    for row in range(n):
        real = imag = 0
        for col in range(n):
            wr, wi = w[n*row+col]
            xr, xi = x[col]
            real += wr*xr - wi*xi
            imag += wr*xi + wi*xr
        result.extend((real, imag))
    return result


def rounded(raw, clip=False):
    """Round Q24 half toward positive infinity, optionally clamp to signed18."""
    if not isinstance(raw, Integral) or isinstance(raw, bool):
        raise ValueError("raw must be an integer")
    value = (int(raw)+(1 << 23)) >> 24
    return max(-(1 << 17), min((1 << 17)-1, value)) if clip else value


def gram_partials(channel, lambda_raw, n):
    """Actual upper-triangle C_GRAM additions, including final lambda."""
    n = size(n)
    h = _pairs(channel, n*n, 18, "H")
    lam = _integer(lambda_raw, 0, (1 << 34)-1, "lambda")
    result = []
    for row in range(n):
        for col in range(row, n):
            re = im = 0
            for k in range(n):
                ar, ai = h[n*k+row]; br, bi = h[n*k+col]
                re += ar*br+ai*bi
                im += ar*bi-ai*br
                result.append((re+(lam if row == col and k == n-1 else 0), im))
    return result


def sum_partials(weights, observations, n):
    """Post-edge yr/yi for each accepted sample in one N-tuple."""
    n = size(n)
    w = _pairs(weights, n*n, 64, "W")
    x = _pairs(observations, n, 18, "observations")
    result = []
    accum = [0]*(2*n)
    for k, (xr, xi) in enumerate(x):
        for row in range(n):
            wr, wi = w[n*row+k]
            accum[2*row] += wr*xr-wi*xi
            accum[2*row+1] += wr*xi+wi*xr
        result.append(tuple(accum))
    return result
