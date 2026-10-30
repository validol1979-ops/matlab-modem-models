"""Independent CIC reference model: exact integer FIR convolution and NumPy float.

Does not import cic_model and does not use integrator/comb recurrences.
Causal zero-state; no output quantization, wrapping or tail flushing.
"""
import numbers

import numpy as np


def _int(name, value, lo=None, hi=None):
    if isinstance(value, bool) or not isinstance(value, numbers.Integral):
        raise TypeError(f"{name} must be an integer")
    value = int(value)
    if (lo is not None and value < lo) or (hi is not None and value > hi):
        raise ValueError(f"{name} out of range: {value}")
    return value


def _params(rate, stages, delay):
    return (_int("rate", rate, 1, 32),
            _int("stages", stages, 1, 5),
            _int("delay", delay, 1, 2))


def _split(samples):
    re, im = [], []
    for pair in samples:
        a, b = pair
        re.append(_int("sample re", a))
        im.append(_int("sample im", b))
    return re, im


def _conv_full(a, b):
    out = [0] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def _fir_causal(seq, h):
    """Exact integer causal convolution, truncated to len(seq)."""
    out = [0] * len(seq)
    for n in range(len(seq)):
        acc = 0
        for k in range(min(n, len(h) - 1) + 1):
            acc += h[k] * seq[n - k]
        out[n] = acc
    return out


def boxcar_kernel(rate, stages=3, delay=1):
    """N-fold convolution of a length rate*delay boxcar of ones."""
    rate, stages, delay = _params(rate, stages, delay)
    box = [1] * (rate * delay)
    h = [1]
    for _ in range(stages):
        h = _conv_full(h, box)
    return h


def decimate_reference(samples, rate, stages=3, delay=1):
    """Filter, then keep outputs at input indices R-1, 2R-1, ..."""
    rate, stages, delay = _params(rate, stages, delay)
    re, im = _split(samples)
    h = boxcar_kernel(rate, stages, delay)
    fr = _fir_causal(re, h)
    fi = _fir_causal(im, h)
    return [(fr[i], fi[i]) for i in range(rate - 1, len(re), rate)]


def interpolate_reference(samples, rate, stages=3, delay=1):
    """Zero-insert by R, filter, clip to len(input)*R outputs."""
    rate, stages, delay = _params(rate, stages, delay)
    re, im = _split(samples)
    h = boxcar_kernel(rate, stages, delay)
    n_out = len(re) * rate
    ure = [0] * n_out
    uim = [0] * n_out
    ure[::rate] = re
    uim[::rate] = im
    fr = _fir_causal(ure, h)
    fi = _fir_causal(uim, h)
    return list(zip(fr, fi))


def float_reference(samples, rate, stages=3, delay=1, kind="decimate"):
    """Independent NumPy floating-point version; returns complex array."""
    rate, stages, delay = _params(rate, stages, delay)
    if kind not in ("decimate", "interpolate"):
        raise ValueError("kind must be 'decimate' or 'interpolate'")
    re, im = _split(samples)
    x = np.array(re, dtype=float) + 1j * np.array(im, dtype=float)
    h = np.array(boxcar_kernel(rate, stages, delay), dtype=float)
    if x.size == 0:
        return np.zeros(0, dtype=complex)
    if kind == "decimate":
        y = np.convolve(x, h)[:len(x)]
        return y[rate - 1::rate]
    u = np.zeros(len(x) * rate, dtype=complex)
    u[::rate] = x
    return np.convolve(u, h)[:len(u)]
