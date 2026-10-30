"""CIC main-lobe droop compensation model (DSP-CIC-COMP), Python only.

Motivation: Harris, Multirate DSP, sec. 12.8 (PDF file pages 490-491): the CIC main lobe
droops quadratically; a compensating FIR with opposite-sign quadratic term
flattens the cascade.  All parameters and gates below are project-derived.

Normalised CIC decimation magnitude at output-rate frequency f (cycles per
output sample):  |sinc(M f) / sinc(f / R)|**N   (DC = 1, no R*M gain factor).
Compensator: symmetric linear-phase FIR, DC gain exactly 1, designed offline by
weighted least squares; integer export is Q17 signed18 with symmetric,
sum-exact rounding.  Uses NumPy and the standard library only.
"""

from __future__ import annotations

import math
import os
import sys

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

import cic_model  # noqa: E402  (existing read-only model, used as-is)
import fir_fixed  # noqa: E402  (existing read-only model, used as-is)

__all__ = ["cic_response", "design", "quantize", "metrics", "cascade_fixed"]

Q17_ONE = 1 << 17            # 131072
Q17_LO = -(1 << 17)
Q17_HI = (1 << 17) - 1


# --------------------------------------------------------------------------- #
# validation helpers
# --------------------------------------------------------------------------- #
def _int(name, value, low, high):
    if isinstance(value, (bool, np.bool_)):
        raise TypeError("%s must be an integer, not bool" % name)
    if not isinstance(value, (int, np.integer)):
        raise TypeError("%s must be an integer, got %s" % (name, type(value).__name__))
    value = int(value)
    if not low <= value <= high:
        raise ValueError("%s out of range [%d, %d]: %d" % (name, low, high, value))
    return value


def _float(name, value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, (int, float, np.floating, np.integer)):
        raise TypeError("%s must be a real number, got %s" % (name, type(value).__name__))
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("%s must be finite" % name)
    return value


def _cic_params(rate, stages, delay):
    return (_int("rate", rate, 1, 32), _int("stages", stages, 1, 5),
            _int("delay", delay, 1, 2))


def _real_odd_taps(taps, name="taps"):
    if isinstance(taps, (str, bytes)):
        raise TypeError("%s must be a numeric sequence" % name)
    try:
        arr = np.asarray(taps)
    except Exception as exc:  # pragma: no cover
        raise TypeError("%s must be numeric" % name) from exc
    if arr.ndim != 1 or arr.size == 0:
        raise ValueError("%s must be a nonempty 1-D sequence" % name)
    if np.iscomplexobj(arr) or arr.dtype == object or arr.dtype == bool:
        raise TypeError("%s must be real numeric" % name)
    arr = arr.astype(np.float64)
    if not np.all(np.isfinite(arr)):
        raise ValueError("%s must be finite" % name)
    if arr.size % 2 == 0:
        raise ValueError("%s must have odd length, got %d" % (name, arr.size))
    if np.max(np.abs(arr - arr[::-1])) > 1e-10:
        raise ValueError("%s must be symmetric (tol 1e-10)" % name)
    return arr


# --------------------------------------------------------------------------- #
# 1. CIC response
# --------------------------------------------------------------------------- #
def cic_response(frequency, rate, stages=3, delay=1):
    """Normalised CIC decimation magnitude |sinc(M f)/sinc(f/R)|**N.

    ``frequency`` is in cycles per OUTPUT sample, finite, in [-0.5, 0.5].
    Scalar input returns float; array input returns an ndarray of the same shape.
    """
    rate, stages, delay = _cic_params(rate, stages, delay)
    scalar = np.ndim(frequency) == 0
    f = np.asarray(frequency)
    if f.dtype == bool or np.iscomplexobj(f) or f.dtype == object:
        raise TypeError("frequency must be real numeric")
    f = f.astype(np.float64)
    if not np.all(np.isfinite(f)) or np.any(np.abs(f) > 0.5):
        raise ValueError("frequency must be finite and within [-0.5, 0.5]")
    mag = np.abs(np.sinc(delay * f) / np.sinc(f / rate)) ** stages
    if scalar:
        return float(mag)
    return mag


# --------------------------------------------------------------------------- #
# 2. design
# --------------------------------------------------------------------------- #
def design(rate, stages=3, delay=1, numtaps=31, passband=0.16, stopband=0.32,
           grid=512, pass_weight=10.0):
    """Offline weighted-LS symmetric FIR compensator with exact unit DC gain."""
    rate, stages, delay = _cic_params(rate, stages, delay)
    numtaps = _int("numtaps", numtaps, 3, 127)
    if numtaps % 2 == 0:
        raise ValueError("numtaps must be odd")
    passband = _float("passband", passband)
    stopband = _float("stopband", stopband)
    if not (0.0 < passband < stopband < 0.5):
        raise ValueError("require 0 < passband < stopband < 0.5")
    grid = _int("grid", grid, 1, 8192)
    if grid < numtaps:
        raise ValueError("grid must be >= numtaps")
    pass_weight = _float("pass_weight", pass_weight)
    if pass_weight <= 0:
        raise ValueError("pass_weight must be positive")

    # fixed grid per band: passband 0..pb, stopband sb..0.5
    f_pb = np.linspace(0.0, passband, grid)
    f_sb = np.linspace(stopband, 0.5, grid)
    f = np.concatenate([f_pb, f_sb])
    wt = np.concatenate([np.full(grid, pass_weight), np.ones(grid)])

    # inverse normalised CIC in passband, zero in stopband
    h_cic = cic_response(f_pb, rate, stages, delay)
    if not np.all(np.isfinite(h_cic)) or np.any(h_cic <= 0):
        raise ValueError("CIC response singular/nonfinite in passband; cannot invert")
    desired = np.concatenate([1.0 / h_cic, np.zeros(grid)])

    m = (numtaps - 1) // 2
    k = np.arange(1, m + 1)
    # H(f) - 1 = sum_k c_k * 2 (cos(2 pi f k) - 1), with DC forced exactly
    A = 2.0 * (np.cos(2.0 * np.pi * np.outer(f, k)) - 1.0)
    y = desired - 1.0
    c, *_ = np.linalg.lstsq(A * wt[:, None], y * wt, rcond=None)
    if not np.all(np.isfinite(c)):
        raise ValueError("design produced nonfinite coefficients")

    h = np.empty(numtaps, dtype=np.float64)
    h[m] = 1.0 - 2.0 * np.sum(c)
    h[m + k] = c
    h[m - k] = c
    return h


# --------------------------------------------------------------------------- #
# 3. quantize
# --------------------------------------------------------------------------- #
def quantize(taps):
    """Q17 signed18 export as list of (int_real, 0); symmetric, sum == 2**17."""
    arr = _real_odd_taps(taps)
    m = (arr.size - 1) // 2
    # nearest, ties toward +infinity
    q = [int(math.floor(float(v) * Q17_ONE + 0.5)) for v in arr]
    # enforce symmetry from the right half, then re-centre so the sum is exact
    for i in range(m):
        q[i] = q[arr.size - 1 - i]
    side = sum(q[i] for i in range(arr.size) if i != m)
    q[m] = Q17_ONE - side
    for v in q:
        if not Q17_LO <= v <= Q17_HI:
            raise OverflowError("quantized coefficient %d outside signed18 range" % v)
    if sum(q) != Q17_ONE:  # pragma: no cover - guaranteed by construction
        raise AssertionError("integer DC sum mismatch")
    return [(v, 0) for v in q]


# --------------------------------------------------------------------------- #
# 4. metrics
# --------------------------------------------------------------------------- #
def metrics(taps, rate, stages=3, delay=1, passband=0.16, stopband=0.32, points=8193):
    """Passband / stopband metrics of the FIR alone and of CIC*FIR (dB)."""
    rate, stages, delay = _cic_params(rate, stages, delay)
    h = _real_odd_taps(taps)
    passband = _float("passband", passband)
    stopband = _float("stopband", stopband)
    if not (0.0 < passband < stopband < 0.5):
        raise ValueError("require 0 < passband < stopband < 0.5")
    points = _int("points", points, 2, 1 << 20)

    f = np.linspace(0.0, 0.5, points)
    n = np.arange(h.size)
    # direct DTFT of the FIR on the grid
    H = np.exp(-2j * np.pi * np.outer(f, n)) @ h
    fir_mag = np.abs(H)
    cic_mag = cic_response(f, rate, stages, delay)

    def db(x):
        return 20.0 * np.log10(np.maximum(x, 1e-300))

    pb = f <= passband
    sb = f >= stopband
    casc_db = db(cic_mag * fir_mag)
    return {
        "dc_gain": float(np.sum(h)),
        "passband_ripple_db": float(np.max(casc_db[pb]) - np.min(casc_db[pb])),
        "passband_max_error_db": float(np.max(np.abs(casc_db[pb]))),
        "uncompensated_droop_db": float(np.max(np.abs(db(cic_mag[pb])))),
        "fir_stopband_db": float(np.max(db(fir_mag[sb]))),
        "cascade_stopband_db": float(np.max(db(cic_mag[sb] * fir_mag[sb]))),
    }


# --------------------------------------------------------------------------- #
# 5. fixed-point cascade
# --------------------------------------------------------------------------- #
def _validate_fixed_taps(taps):
    if isinstance(taps, (str, bytes)):
        raise TypeError("taps must be a sequence of (int, 0) pairs")
    try:
        items = list(taps)
    except TypeError:
        raise TypeError("taps must be a sequence of (int, 0) pairs")
    if not items:
        raise ValueError("taps must be nonempty")
    if len(items) % 2 == 0:
        raise ValueError("taps must have odd length")
    out = []
    for t in items:
        if not isinstance(t, (tuple, list)) or len(t) != 2:
            raise TypeError("each tap must be a (re, im) pair")
        re = _int("tap.re", t[0], Q17_LO, Q17_HI)
        im = _int("tap.im", t[1], Q17_LO, Q17_HI)
        if im != 0:
            raise ValueError("compensator taps must be real (im == 0)")
        out.append((re, im))
    return out


def cascade_fixed(samples, rate, stages, taps, delay=1):
    """CIC decimator (normalize=True) followed by full-tail Q17 FIR filter.

    Samples are signed18 integer (re, im) pairs; the frame length must be a
    multiple of ``rate``.  Pure accepted-sample model (no ready/valid/cycle claims).
    """
    rate, stages, delay = _cic_params(rate, stages, delay)
    qtaps = _validate_fixed_taps(taps)
    dec = cic_model.decimate(samples, rate, stages=stages, delay=delay, normalize=True)
    if not dec:
        return []
    return fir_fixed.filter(dec, qtaps)
