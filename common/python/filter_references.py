"""Independent oracles used by tests/test_filter_models.py.

This module deliberately contains no imports of the production models.  The
integer/rational paths use Python integers and Fraction; NumPy is used only for
the explicit floating-point convolution and DTFT references.
"""
from __future__ import annotations

from fractions import Fraction
import math
from typing import Iterable, Sequence

import numpy as np


# ---------------------------------------------------------------------------
# CIC and droop-compensating FIR references
# ---------------------------------------------------------------------------
def cic_response(frequency, rate: int, stages: int = 3, delay: int = 1):
    """Normalized CIC decimation magnitude, including scalar/array shape."""
    def one(f):
        if delay * f == 0.0:
            return 1.0
        return float(abs(np.sinc(delay * f) / np.sinc(f / rate)) ** stages)

    if np.isscalar(frequency):
        return one(float(frequency))
    x = np.asarray(frequency, dtype=float)
    return np.vectorize(one, otypes=[float])(x)


def quantize_q17_reference(taps: Sequence[float]):
    """Q17 signed-18 export: ties to +infinity and exact unity centre sum."""
    h = np.asarray(taps, dtype=float)
    if h.ndim != 1 or h.size == 0 or h.size % 2 == 0:
        raise ValueError("taps must be nonempty and odd")
    if not np.all(np.isfinite(h)):
        raise ValueError("nonfinite tap")
    m = h.size // 2
    if not np.allclose(h, h[::-1], rtol=0.0, atol=1e-10):
        raise ValueError("taps must be symmetric")
    q = [int(math.floor(float(v) * 131072.0 + 0.5)) for v in h]
    q[m] += 131072 - sum(q)
    if any(v < -131072 or v > 131071 for v in q):
        raise OverflowError("Q17 coefficient outside signed 18 bits")
    return [(v, 0) for v in q]


def _dtft(taps, freqs):
    h = np.asarray(taps, dtype=float)
    n = np.arange(h.size, dtype=float)
    return np.exp(-2j * np.pi * np.outer(freqs, n)) @ h


def metrics_reference(taps, rate, stages=3, delay=1, passband=.16,
                      stopband=.32, points=8193):
    """Direct-grid metrics; magnitudes are clamped before taking dB."""
    h = np.asarray(taps, dtype=float)
    f = np.linspace(0.0, 0.5, int(points))
    hm = np.abs(_dtft(h, f))
    db = 20.0 * np.log10(np.maximum(hm, 1e-300))
    p = f <= passband
    s = f >= stopband
    c = cic_response(f, rate, stages, delay)
    cdb = 20.0 * np.log10(np.maximum(c, 1e-300))
    casc = np.maximum(hm * c, 1e-300)
    casc_db = 20.0 * np.log10(casc)
    return {
        "dc_gain": float(np.sum(h)),
        "passband_ripple_db": float(np.ptp(casc_db[p])),
        "passband_max_error_db": float(np.max(np.abs(casc_db[p]))),
        "uncompensated_droop_db": float(np.ptp(cdb[p])),
        "fir_stopband_db": float(np.max(db[s])),
        "cascade_stopband_db": float(np.max(20.0 * np.log10(casc[s]))),
    }


def cic_decimate_convolution_reference(samples, rate, stages=3, delay=1,
                                          input_width=18):
    """Exact normalized CIC decimator via integer convolution and group-end
    sampling.

    The impulse response is the N-fold convolution of a length rate*delay
    boxcar.  Output m samples the convolution at high-rate index
    (m+1)*rate-1, i.e. at the end of each accepted input group.  Normalization
    is the contract's exact nearest, ties-to-+infinity division followed by
    saturation to the input width.
    """
    n = len(samples)
    if n % rate:
        raise ValueError("sample count must be a multiple of rate")
    box = np.ones(rate * delay, dtype=np.int64)
    h = np.ones(1, dtype=np.int64)
    for _ in range(stages):
        h = np.convolve(h, box)
    gain = (rate * delay) ** stages
    lo, hi = -(1 << (input_width - 1)), (1 << (input_width - 1)) - 1
    out = []
    for m in range(n // rate):
        base = (m + 1) * rate - 1
        ai = aq = 0
        for j, c in enumerate(h):
            idx = base - int(j)
            if 0 <= idx < n:
                ai += int(c) * int(samples[idx][0])
                aq += int(c) * int(samples[idx][1])
        ai = (2 * ai + gain) // (2 * gain)
        aq = (2 * aq + gain) // (2 * gain)
        out.append((max(lo, min(hi, ai)), max(lo, min(hi, aq))))
    return out


def fir_q17_reference(samples, taps_q17, output_width=18):
    """Exact full-tail Q17 FIR with nearest, ties-to-+infinity rounding."""
    coeff = [int(c) for c, _ in taps_q17]
    lo = -(1 << (output_width - 1))
    hi = (1 << (output_width - 1)) - 1
    out = []
    for n in range(len(samples) + len(coeff) - 1):
        ai = aq = 0
        for j, c in enumerate(coeff):
            idx = n - j
            if 0 <= idx < len(samples):
                ai += c * int(samples[idx][0])
                aq += c * int(samples[idx][1])
        ai = (Fraction(ai) + 65536) // 131072
        aq = (Fraction(aq) + 65536) // 131072
        out.append((max(lo, min(hi, int(ai))), max(lo, min(hi, int(aq)))))
    return out


def cascade_reference(samples, rate, stages, taps_q17, delay=1):
    """Independent normalized CIC followed by the exact Q17 FIR."""
    cic = cic_decimate_convolution_reference(samples, rate, stages, delay)
    return fir_q17_reference(cic, taps_q17)


# ---------------------------------------------------------------------------
# Rational polyphase references
# ---------------------------------------------------------------------------
def _zero_stuffed(samples, up):
    n = len(samples)
    if np.iscomplexobj(np.asarray(samples)):
        z = np.zeros(n * up, dtype=complex)
    else:
        z = np.zeros(n * up, dtype=float)
    if n:
        z[::up] = samples
    return z


def rational_float_reference(samples, up, down, taps, tail=True):
    """Explicit length-N*P zero insertion, np.convolve, stride down."""
    z = _zero_stuffed(np.asarray(list(samples), dtype=complex), up)
    if z.size == 0:
        return []
    full = np.convolve(z, np.asarray(taps, dtype=float))
    if tail:
        return list(full[::down])
    return list(full[0:z.size:down])


def _sat(value: int, width: int) -> int:
    lo, hi = -(1 << (width - 1)), (1 << (width - 1)) - 1
    return lo if value < lo else hi if value > hi else value


def rational_fixed_reference(samples, up, down, taps, coeff_frac=17,
                             output_width=18, tail=True):
    """Exact full-width integer convolution with one Fraction rounding step."""
    coeff = [int(v) for v in taps]
    n = len(samples)
    zlen = n * up
    if n == 0:
        return []
    if tail:
        last = zlen + len(coeff) - 1
    else:
        last = zlen
    count = (last + down - 1) // down
    out = []
    scale = 1 << coeff_frac
    half = 0 if coeff_frac == 0 else 1 << (coeff_frac - 1)
    for k in range(count):
        t = k * down
        ai = aq = 0
        for j, c in enumerate(coeff):
            idx = t - j
            if idx >= 0 and idx % up == 0 and idx // up < n:
                s = samples[idx // up]
                ai += c * int(s[0])
                aq += c * int(s[1])
        if coeff_frac:
            ai = int((Fraction(ai) + Fraction(half, 1)) // scale)
            aq = int((Fraction(aq) + Fraction(half, 1)) // scale)
        out.append((_sat(ai, output_width), _sat(aq, output_width)))
    return out


def accumulator_width_reference(taps, up, input_width=18):
    """Minimum signed accumulator width over every polyphase branch."""
    h = [int(v) for v in taps]
    xlo, xhi = -(1 << (input_width - 1)), (1 << (input_width - 1)) - 1
    lo = hi = 0
    for branch in range(up):
        blo = bhi = 0
        for c in h[branch::up]:
            a, b = c * xlo, c * xhi
            blo += min(a, b)
            bhi += max(a, b)
        lo, hi = min(lo, blo), max(hi, bhi)
    for w in range(1, 4097):
        if -(1 << (w - 1)) <= lo and hi <= (1 << (w - 1)) - 1:
            return w
    raise OverflowError("no practical width")
