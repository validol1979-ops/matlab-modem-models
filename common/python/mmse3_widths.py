"""Integer bounds and independent arithmetic for the MMSE3 width sweep.

Channels and weights are flat row-major lists of nine (real, imaginary)
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


def layout():
    """Return exact extrema, including each real/imaginary component domain."""
    a, b = 1 << 17, 1 << 63
    gram_real = [-6*a*(a-1), 6*a*a]
    gram_imag = [-6*a*a+3*a, 6*a*a-3*a]
    diagonal = [0, 7*a*a-1]
    sum_real = [-6*a*b+3*a, 6*a*b-3*a]
    sum_imag = [-6*a*b+6*a, 6*a*b]
    low, high = sum_real[0], sum_imag[1]
    half = 1 << 23
    return {
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


def gram(channel, lambda_raw):
    """Exact H^H H + lambda I; return 18 interleaved row-major components."""
    h = _pairs(channel, 9, 18, "H")
    lam = _integer(lambda_raw, 0, (1 << 34)-1, "lambda")
    result = []
    for row in range(3):
        for col in range(3):
            real = lam if row == col else 0
            imag = 0
            for k in range(3):
                ar, ai = h[3*k+row]
                br, bi = h[3*k+col]
                real += ar*br + ai*bi
                imag += ar*bi - ai*br
            result.extend((real, imag))
    return result


def sums(weights, observations):
    """Exact W*x; return six interleaved real/imaginary components."""
    w = _pairs(weights, 9, 64, "W")
    x = _pairs(observations, 3, 18, "observations")
    result = []
    for row in range(3):
        real = imag = 0
        for col in range(3):
            wr, wi = w[3*row+col]
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
