"""Rational P/Q resampling models (float and fixed point).

Polyphase implementation of the rational resampler of Harris, *Multirate
Signal Processing for Communication Systems*, ch. 7.4-7.5: a P-stage polyphase
filter fed with one input sample per commutator wrap, the commutator read with
stride Q modulo P (Figure 7.21 / Table 7.2, and 12/5 in Figure 7.22).

Sample convention (contract)
---------------------------
    y[k] = sum_j h[(k*Q) % P + j*P] * x[floor(k*Q/P) - j]

with ``x[n] = 0`` for ``n < 0`` (zero initial state) and ``x[n] = 0`` for
``n >= N`` after the frame ended (the tail of inserted zeros).  Output ``k = 0``
sits at high-rate time 0.  For P=5, Q=3 the phase sequence is 0, 3, 1, 4, 2.

No explicit upsample and no convolution call: each output reads one pre-sliced
polyphase branch ``h[r::P]`` plus a *bounded* history of at most
``ceil(len(taps)/P)`` original samples and two integer counters (next output
index, accepted input count).  ``phase`` / ``input_index`` are derived from the
next output index and describe the schedule of the NEXT output.

Frame / stream semantics
------------------------
* ``push(sample)`` -> outputs that became causally available; after N accepted
  inputs exactly ``ceil(N*P/Q)`` outputs exist in total, i.e. filtering a
  zero-stuffed array of length ``N*P`` and taking ``[0::Q]``.
* ``flush(tail=True)`` emits through the full convolution length
  ``N*P + len(h) - 1`` (total ``ceil((N*P + len(h) - 1)/Q)``, deliberately
  including the final ``P-1`` inserted zeros) and CLOSES the frame.
  ``flush(tail=False)`` finalizes at ``ceil(N*P/Q)`` outputs.  Empty frame ->
  ``[]``; repeated flush -> ``[]``; an invalid ``tail`` rejects with no state
  mutation, even after close.
* ``push`` after close raises until ``reset()`` / ``configure()``.
* ``reset()`` keeps the configuration; ``configure()`` is legal only before the
  first sample or after a flush, validates everything before touching state and
  always resets.  Bad sample/config/flush arguments never change state.

No implicit TLAST, no cycle accuracy, no back-pressure modelling.  Taps are
used exactly as given: never normalised, never scaled by P.

Stdlib only (numpy not required, though numpy scalars/arrays are accepted).
"""

from __future__ import annotations

import math
import numbers
import operator
from collections import deque

__all__ = [
    "RationalModel",
    "RationalFloat",
    "RationalFixed",
    "resample_float",
    "resample_fixed",
    "accumulator_width",
    "RationalModelError",
    "RationalClosedError",
]

MAX_TAPS = 2047                                    # taps length 1..2047
MAX_RATIO = 32                                     # up/down each 1..32
COEFF_BITS = 18                                    # fixed taps: signed 18 bit
COEFF_MIN = -(1 << (COEFF_BITS - 1))               # -131072
COEFF_MAX = (1 << (COEFF_BITS - 1)) - 1            #  131071
FRAC_MIN, FRAC_MAX = 0, 30
WIDTH_MIN, WIDTH_MAX = 2, 32


# --------------------------------------------------------------------------- #
# Exceptions.  Argument errors raise RationalModelError, a plain ValueError
# subclass; frame/state errors are RuntimeError.
# --------------------------------------------------------------------------- #
class RationalModelError(ValueError):
    """Invalid argument (ratio, taps, sample, flag); state left unchanged."""


class RationalClosedError(RuntimeError):
    """Frame closed, or configure() attempted in the middle of a frame."""


# --------------------------------------------------------------------------- #
# Strict validators (bool and non-integers are always rejected)
# --------------------------------------------------------------------------- #
def _is_bool(value: object) -> bool:
    if isinstance(value, bool):
        return True
    dtype = getattr(value, "dtype", None)
    if dtype is not None and getattr(dtype, "kind", None) == "b":
        return True
    return type(value).__name__ in ("bool_", "bool8")


def _unwrap(value):
    """0-d numpy scalar/array -> scalar; everything else unchanged."""
    if getattr(value, "ndim", None) == 0 and hasattr(value, "item"):
        return value.item()
    return value


def _strict_int(value, name: str) -> int:
    """Python/numpy integer only; bool and every float are rejected."""
    value = _unwrap(value)
    if _is_bool(value):
        raise RationalModelError(f"{name}: bool is not an integer")
    try:
        return operator.index(value)
    except TypeError:
        raise RationalModelError(
            f"{name}: expected an integer, got {type(value).__name__}") from None


def _as_taps_sequence(value, name: str):
    """1-D sequence/array of taps -> list (scalars, strings rejected)."""
    if value is None or isinstance(value, (str, bytes, bytearray)):
        raise RationalModelError(f"{name}: expected a non-empty sequence")
    if getattr(value, "shape", None) is not None and hasattr(value, "reshape"):
        shape = value.shape
        if len(shape) > 1 and 1 not in shape:
            raise RationalModelError(f"{name}: must be 1-D, got shape {shape}")
        return list(value.reshape(-1))
    if isinstance(value, numbers.Number):
        raise RationalModelError(f"{name}: expected a sequence, got a scalar")
    try:
        return list(value)
    except TypeError:
        raise RationalModelError(f"{name}: not iterable") from None


def _iter_samples(samples, name: str = "samples"):
    """Iterable of samples -> list; a 2-D (N, 2) array becomes N I/Q rows."""
    if samples is None or isinstance(samples, (str, bytes, bytearray)):
        raise RationalModelError(f"{name}: expected an iterable of samples")
    if getattr(samples, "shape", None) is not None:            # numpy array
        if getattr(samples, "ndim", 0) == 0:
            raise RationalModelError(f"{name}: expected an iterable, got a scalar")
        return list(samples)
    if isinstance(samples, numbers.Number):
        raise RationalModelError(f"{name}: expected an iterable, got a scalar")
    try:
        return list(samples)
    except TypeError:
        raise RationalModelError(f"{name}: not iterable") from None


def _real_scalar(value, name: str) -> float:
    """Finite real scalar (int or float); complex and bool rejected."""
    value = _unwrap(value)
    if _is_bool(value):
        raise RationalModelError(f"{name}: bool is not allowed")
    if isinstance(value, numbers.Integral):
        return float(value)
    if isinstance(value, numbers.Real):
        out = float(value)
    elif isinstance(value, numbers.Complex):
        raise RationalModelError(f"{name}: complex values are not allowed")
    else:
        raise RationalModelError(f"{name}: expected a real number, got "
                                 f"{type(value).__name__}")
    if not math.isfinite(out):
        raise RationalModelError(f"{name}: must be finite")
    return out


def _fixed_coeff(value, name: str) -> int:
    """Signed 18-bit integer tap."""
    coeff = _strict_int(value, name)
    if not COEFF_MIN <= coeff <= COEFF_MAX:
        raise RationalModelError(f"{name}: {coeff} outside signed {COEFF_BITS}-bit "
                                 f"range [{COEFF_MIN}, {COEFF_MAX}]")
    return coeff


def _tail_flag(value) -> bool:
    if _is_bool(value):
        return bool(value)
    raise RationalModelError("tail: expected a bool")


def _coprime_ratio(up, down) -> tuple:
    p = _strict_int(up, "up")
    q = _strict_int(down, "down")
    if not 1 <= p <= MAX_RATIO:
        raise RationalModelError(f"up: must be 1..{MAX_RATIO}, got {p}")
    if not 1 <= q <= MAX_RATIO:
        raise RationalModelError(f"down: must be 1..{MAX_RATIO}, got {q}")
    if math.gcd(p, q) != 1:
        raise RationalModelError(f"up/down = {p}/{q} is not coprime")
    return p, q


def _rails(width: int) -> tuple:
    return -(1 << (width - 1)), (1 << (width - 1)) - 1


def _saturate(value: int, width: int) -> int:
    lo, hi = _rails(width)
    if value < lo:
        return lo
    if value > hi:
        return hi
    return value


def _as_iq_pair(value, width: int):
    """Exactly two signed integers inside the ``width``-bit signed rails."""
    if value is None or isinstance(value, (str, bytes, bytearray)):
        raise RationalModelError("sample: expected an (I, Q) pair of integers")
    if isinstance(value, numbers.Number):
        raise RationalModelError("sample: expected an (I, Q) pair of integers, "
                                 f"got scalar {type(value).__name__}")
    items = _as_taps_sequence(value, "sample")
    if len(items) != 2:
        raise RationalModelError(
            f"sample: expected exactly 2 integers, got {len(items)}")
    lo, hi = _rails(width)
    out = []
    for pos, item in enumerate(items):
        comp = _strict_int(item, f"sample[{pos}]")
        if not lo <= comp <= hi:
            raise RationalModelError(
                f"sample[{pos}]: {comp} outside signed {width}-bit rails "
                f"[{lo}, {hi}]")
        out.append(comp)
    return (out[0], out[1])


def _as_complex_sample(value, name: str) -> complex:
    """Finite real/complex scalar (or 2-element I/Q sequence) -> complex."""
    value = _unwrap(value)
    if _is_bool(value):
        raise RationalModelError(f"{name}: bool is not a valid sample")
    if isinstance(value, numbers.Number):
        if isinstance(value, numbers.Integral):
            return complex(float(value), 0.0)
        if isinstance(value, numbers.Real):
            real = float(value)
            if not math.isfinite(real):
                raise RationalModelError(f"{name}: sample must be finite")
            return complex(real, 0.0)
        if isinstance(value, numbers.Complex):
            real, imag = float(value.real), float(value.imag)
            if not (math.isfinite(real) and math.isfinite(imag)):
                raise RationalModelError(f"{name}: sample must be finite")
            return complex(real, imag)
        raise RationalModelError(f"{name}: unsupported type "
                                 f"{type(value).__name__}")
    items = _as_taps_sequence(value, name)
    if len(items) == 2:                       # (I, Q) convenience form
        return complex(_real_scalar(items[0], f"{name}[0]"),
                       _real_scalar(items[1], f"{name}[1]"))
    raise RationalModelError(f"{name}: expected a number or an (I, Q) pair")


# --------------------------------------------------------------------------- #
# Common engine
# --------------------------------------------------------------------------- #
class RationalModel:
    """Polyphase P/Q core; subclasses provide the numeric layer."""

    def __init__(self, up, down, taps):
        self._apply(self._validate_config(up, down, taps))

    # ---------------- configuration ---------------- #
    @staticmethod
    def _validate_tap(value, name: str):
        return _real_scalar(value, name)

    def _validate_config(self, up, down, taps):
        """Validated ``(P, Q, taps_tuple)``; raises without mutating anything."""
        p, q = _coprime_ratio(up, down)
        seq = _as_taps_sequence(taps, "taps")
        if not 1 <= len(seq) <= MAX_TAPS:
            raise RationalModelError(f"taps: length must be 1..{MAX_TAPS}, "
                                     f"got {len(seq)}")
        return p, q, tuple(self._validate_tap(t, f"taps[{j}]")
                           for j, t in enumerate(seq))

    def _apply(self, config) -> None:
        p, q, taps = config
        self._up, self._down, self._taps = p, q, taps
        # type-1 polyphase branches: branch r holds h[r], h[r+P], h[r+2P], ...
        self._branches = [list(taps[r::p]) for r in range(p)]
        self._hist_limit = -(-len(taps) // p)              # ceil(L/P)
        self._clear_state()

    def _clear_state(self) -> None:
        self._hist = deque(maxlen=self._hist_limit)        # bounded history
        self._n = 0            # accepted input samples
        self._k = 0            # index of the NEXT output
        self._closed = False

    def configure(self, up, down, taps) -> None:
        """Reconfigure + start a new frame (before first sample or after flush)."""
        if self._n and not self._closed:
            raise RationalClosedError(
                "configure() is allowed before the first sample or after "
                "flush(); call flush() or reset() first")
        config = self._validate_config(up, down, taps)     # atomic validation
        self._apply(config)

    def reset(self) -> None:
        """Clear history/counters/closed flag, keep the configuration."""
        self._clear_state()

    # ---------------- read-only state ---------------- #
    @property
    def up(self) -> int:
        return self._up

    @property
    def down(self) -> int:
        return self._down

    @property
    def taps(self):
        return self._taps

    @property
    def phase(self) -> int:
        """Commulator port of the NEXT output: (next_output_index*Q) % P."""
        return (self._k * self._down) % self._up

    @property
    def input_index(self) -> int:
        """Newest input index the NEXT output uses: (next_output_index*Q) // P."""
        return (self._k * self._down) // self._up

    @property
    def output_index(self) -> int:
        """Index of the NEXT output == number of outputs emitted so far."""
        return self._k

    @property
    def input_count(self) -> int:
        return self._n

    @property
    def is_closed(self) -> bool:
        return self._closed

    @property
    def history_limit(self) -> int:
        """Bound on kept original samples: ceil(len(taps)/P)."""
        return self._hist_limit

    @property
    def history_len(self) -> int:
        return len(self._hist)

    # ---------------- emission ---------------- #
    def _push_limit(self) -> int:
        """Last output index available after N inputs: (N*P - 1) // Q."""
        return (self._n * self._up - 1) // self._down

    def _tail_limit(self) -> int:
        """Last output index of the full convolution: (N*P + L - 2) // Q."""
        return (self._n * self._up + len(self._taps) - 2) // self._down

    def _advance(self, limit: int):
        """Emit outputs k..limit inclusive, advancing the schedule counters."""
        out = []
        p, q, k = self._up, self._down, self._k
        while k <= limit:
            stride = k * q
            out.append(self._dot(self._branches[stride % p], stride // p))
            k += 1
        self._k = k
        return out

    # numeric layer (subclass) ------------------------------------ #
    def _check_sample(self, sample):                        # pragma: no cover
        raise NotImplementedError

    def _dot(self, branch, input_index: int):               # pragma: no cover
        raise NotImplementedError

    # ---------------- stream API ---------------- #
    def push(self, sample):
        """Accept one input sample; return newly available outputs (a list)."""
        if self._closed:
            raise RationalClosedError(
                "frame is closed; call reset() or configure() before pushing")
        value = self._check_sample(sample)                  # validate first
        self._hist.append(value)
        self._n += 1
        return self._advance(self._push_limit())

    def flush(self, tail: bool = True):
        """Emit the remaining outputs and CLOSE the frame."""
        tail = _tail_flag(tail)                             # even when closed
        if self._closed:
            return []                                       # idempotent
        if self._n == 0:
            self._closed = True                             # no tail for empty
            return []
        out = self._advance(self._tail_limit()) if tail else []
        self._closed = True
        return out

    def push_many(self, samples):
        """Convenience: push every sample of an iterable, concatenating output."""
        out = []
        for sample in _iter_samples(samples):
            out.extend(self.push(sample))
        return out

    def _run(self, samples, tail: bool):
        out = []
        for sample in samples:
            out.extend(self.push(sample))
        out.extend(self.flush(tail))
        return out

    def __repr__(self):
        return (f"{type(self).__name__}(up={self._up}, down={self._down}, "
                f"taps=len {len(self._taps)}, n={self._n}, k={self._k}, "
                f"closed={self._closed})")


# --------------------------------------------------------------------------- #
# Floating point model
# --------------------------------------------------------------------------- #
class RationalFloat(RationalModel):
    """Float/complex model: finite numeric samples in, ``complex`` outputs out.

    Taps are finite real numbers (complex and bool rejected); they are used
    verbatim - no normalisation, no hidden factor P.  A unity-gain P-oversampled
    prototype with sum(h) = P is the caller's choice.
    """

    @staticmethod
    def _validate_tap(value, name: str) -> float:
        return _real_scalar(value, name)

    def _check_sample(self, sample) -> complex:
        return _as_complex_sample(sample, "sample")

    def _input(self, index: int):
        """x[n] from the bounded history; 0 for n < 0 and n >= N (zero tail)."""
        if index < 0 or index >= self._n:
            return 0j
        return self._hist[index - self._n]

    def _dot(self, branch, input_index: int) -> complex:
        acc = 0j
        index = input_index
        for coeff in branch:
            if coeff:
                acc += coeff * self._input(index)
            index -= 1
        return acc


# --------------------------------------------------------------------------- #
# Fixed point model
# --------------------------------------------------------------------------- #
class RationalFixed(RationalModel):
    """Fixed-point IQ model.

    Taps: signed 18-bit integers in Q``coeff_frac``.  Samples: exactly two
    signed integers within ``input_width``.  The polyphase dot product is exact
    (arbitrary-precision integers, no intermediate wrap or clipping), then ONE
    rounding shift ``(raw + 2**(frac-1)) >> frac`` (no shift when
    ``coeff_frac == 0``), then full signed ``output_width`` saturation.
    ``input_width`` / ``coeff_frac`` / ``output_width`` stay fixed on
    ``configure()``; use a new object to change them.
    """

    def __init__(self, up, down, taps, input_width: int = 18,
                 coeff_frac: int = 17, output_width: int = 18):
        self._input_width, self._coeff_frac, self._output_width = \
            self._validate_widths(input_width, coeff_frac, output_width)
        self._apply(self._validate_config(up, down, taps))

    @staticmethod
    def _validate_widths(input_width, coeff_frac, output_width):
        iw = _strict_int(input_width, "input_width")
        fr = _strict_int(coeff_frac, "coeff_frac")
        ow = _strict_int(output_width, "output_width")
        for name, val, (lo, hi) in (("input_width", iw, (WIDTH_MIN, WIDTH_MAX)),
                                    ("coeff_frac", fr, (FRAC_MIN, FRAC_MAX)),
                                    ("output_width", ow, (WIDTH_MIN, WIDTH_MAX))):
            if not lo <= val <= hi:
                raise RationalModelError(f"{name}: must be {lo}..{hi}, got {val}")
        return iw, fr, ow

    @staticmethod
    def _validate_tap(value, name: str) -> int:
        return _fixed_coeff(value, name)

    def _check_sample(self, sample):
        return _as_iq_pair(sample, self._input_width)

    def _input(self, index: int):
        """x[n] from the bounded history; None means 0+0j outside the frame."""
        if index < 0 or index >= self._n:
            return None
        return self._hist[index - self._n]

    def _dot(self, branch, input_index: int):
        acc_i = 0
        acc_q = 0
        index = input_index
        frac = self._coeff_frac
        for coeff in branch:
            sample = self._input(index)
            if sample is not None and coeff:
                acc_i += coeff * sample[0]
                acc_q += coeff * sample[1]
            index -= 1
        if frac:
            bias = 1 << (frac - 1)
            acc_i = (acc_i + bias) >> frac          # arithmetic shift (floor)
            acc_q = (acc_q + bias) >> frac
        ow = self._output_width
        return (_saturate(acc_i, ow), _saturate(acc_q, ow))

    @property
    def input_width(self) -> int:
        return self._input_width

    @property
    def coeff_frac(self) -> int:
        return self._coeff_frac

    @property
    def output_width(self) -> int:
        return self._output_width


# --------------------------------------------------------------------------- #
# Batch helpers
# --------------------------------------------------------------------------- #
def resample_float(samples, up, down, taps, tail: bool = True):
    """Fresh RationalFloat frame: push all samples, flush, return all outputs."""
    tail = _tail_flag(tail)
    model = RationalFloat(up, down, taps)                # validates ratio/taps
    return model._run(_iter_samples(samples), tail)


def resample_fixed(samples, up, down, taps, tail: bool = True, **width_kwargs):
    """Fresh RationalFixed frame; ``input_width``/``coeff_frac``/
    ``output_width`` come from ``width_kwargs``."""
    tail = _tail_flag(tail)
    model = RationalFixed(up, down, taps, **width_kwargs)
    return model._run(_iter_samples(samples), tail)


# --------------------------------------------------------------------------- #
# Proven accumulator width bound
# --------------------------------------------------------------------------- #
def accumulator_width(taps, up, input_width: int = 18) -> int:
    """Smallest signed accumulator width covering EVERY polyphase dot product
    over the full signed input rails.

    For each polyphase branch the extreme sums are built exactly from the
    coefficient signs: ``c >= 0`` contributes ``[c*rail_lo, c*rail_hi]`` and
    ``c < 0`` the mirrored interval ``[c*rail_hi, c*rail_lo]``.  Then the
    smallest ``W`` with ``-2**(W-1) <= lo`` and ``hi <= 2**(W-1) - 1`` is found
    by exact integer arithmetic (no floats, no logarithms, no numpy overflow).
    This is a proven format bound, not wrapped arithmetic emulation.
    """
    p = _strict_int(up, "up")
    if not 1 <= p <= MAX_RATIO:
        raise RationalModelError(f"up: must be 1..{MAX_RATIO}, got {p}")
    iw = _strict_int(input_width, "input_width")
    if not WIDTH_MIN <= iw <= WIDTH_MAX:
        raise RationalModelError(f"input_width: must be "
                                 f"{WIDTH_MIN}..{WIDTH_MAX}, got {iw}")
    seq = _as_taps_sequence(taps, "taps")
    if not 1 <= len(seq) <= MAX_TAPS:
        raise RationalModelError(f"taps: length must be 1..{MAX_TAPS}, "
                                 f"got {len(seq)}")
    coeffs = tuple(_fixed_coeff(t, f"taps[{j}]") for j, t in enumerate(seq))

    rail_lo, rail_hi = _rails(iw)

    lo_all, hi_all = 0, 0                     # an unused/empty branch sums to 0
    for r in range(p):
        lo = hi = 0
        for coeff in coeffs[r::p]:
            if coeff >= 0:
                lo += coeff * rail_lo
                hi += coeff * rail_hi
            else:
                lo += coeff * rail_hi
                hi += coeff * rail_lo
        if lo < lo_all:
            lo_all = lo
        if hi > hi_all:
            hi_all = hi

    width = 1
    while True:
        slo, shi = _rails(width)
        if slo <= lo_all and hi_all <= shi:
            return width
        width += 1
