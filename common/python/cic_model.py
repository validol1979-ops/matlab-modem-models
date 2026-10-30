"""Python DSP models for CIC decimator / interpolator (DSP-CIC-DEC, DSP-CIC-INT).

Newly written from the mathematical Cascaded-Integrator-Comb architecture.
Conceptual reference (read only, NOT a cycle-exact copy of its pipeline):
    verilog-dsp-master/rtl/cic_decimator.v , cic_interpolator.v

Implementation choices fixed by the project contract:
  * causal, zero initial state;
  * integrator stage k uses the *updated* preceding stage on the same accepted
    sample (combinational-cascade semantics, not registered cross-cycle);
  * decimation emits at input indices R-1, 2R-1, ... (end of each R group);
  * interpolation = zero stuffing then N-fold boxcar; emits phases 0..R-1 per
    accepted input; realised as comb@low-rate -> upsample(R) -> integrators@high-rate
    which is exactly ``zeroinsert`` convolved with ``(boxcar_{R*M})^{*N}``;
  * all integrator / comb arithmetic is modular (two's complement) at a single
    width ``acc_width`` (the working register width).  No per-stage truncation
    or saturation: ``+``/``-`` are congruent modulo ``2**acc_width`` so wrapping
    each step equals wrapping the exact result;
  * samples are integer signed pairs ``(re, im)``;
  * no floats / bools accepted for integer parameters or sample components.

Only Python standard library is used.  This module is the production model; it
must not import the independent ``cic_reference`` model.
"""

from __future__ import annotations

import numbers
from collections import deque

__all__ = [
    "cic_gain",
    "register_width",
    "quantize",
    "CICDecimator",
    "CICInterpolator",
    "decimate",
    "interpolate",
    "MAX_RATE_LIMIT",
]

# Hard upper bound of the supported decimation / interpolation ratio.
MAX_RATE_LIMIT = 32


# --------------------------------------------------------------------------- #
# integer / parameter validation helpers
# --------------------------------------------------------------------------- #
def _as_int(name, value):
    """Return ``value`` as a Python ``int``.

    Accepts ``int`` and any ``numbers.Integral`` (e.g. numpy integer scalars).
    Rejects ``bool`` (a subclass of ``int``) and every non integral type
    (``float``, ``str``, ...).
    """
    if isinstance(value, bool):
        raise TypeError("%s must be an integer, not bool" % name)
    if isinstance(value, numbers.Integral):
        return int(value)
    raise TypeError(
        "%s must be an integer, got %s" % (name, type(value).__name__)
    )


def _check_range(name, value, low, high):
    if not low <= value <= high:
        raise ValueError(
            "%s out of range [%d, %d]: %r" % (name, low, high, value)
        )
    return value


def _validate_kind(kind):
    if kind not in ("decimate", "interpolate"):
        raise ValueError(
            "kind must be 'decimate' or 'interpolate', got %r" % (kind,)
        )
    return kind


# --------------------------------------------------------------------------- #
# gain / width / quantisation primitives
# --------------------------------------------------------------------------- #
def cic_gain(rate, stages=3, delay=1, kind="decimate"):
    """Exact integer DC gain of an ideal CIC.

    ``decimate``   : ``(R*M)**N``
    ``interpolate``: ``(R*M)**N // R``  (zero stuffing divides the DC by R)
    """
    rate = _as_int("rate", rate)
    stages = _as_int("stages", stages)
    delay = _as_int("delay", delay)
    _check_range("rate", rate, 1, MAX_RATE_LIMIT)
    _check_range("stages", stages, 1, 5)
    _check_range("delay", delay, 1, 2)
    _validate_kind(kind)
    gain = (rate * delay) ** stages
    if kind == "interpolate":
        # (R*M)**N is always divisible by R for R>=1, M>=1, N>=1.
        gain //= rate
    return gain


def register_width(input_width=18, rate=32, stages=3, delay=1, kind="decimate"):
    """Accumulator width required to hold the full ``kind`` gain.

    ``input_width + ceil(log2(gain))`` computed exactly as
    ``input_width + (gain - 1).bit_length()`` -- no floating point logarithms.
    """
    input_width = _as_int("input_width", input_width)
    rate = _as_int("rate", rate)
    stages = _as_int("stages", stages)
    delay = _as_int("delay", delay)
    _check_range("input_width", input_width, 2, 32)
    _check_range("rate", rate, 1, MAX_RATE_LIMIT)
    _check_range("stages", stages, 1, 5)
    _check_range("delay", delay, 1, 2)
    _validate_kind(kind)
    gain = cic_gain(rate, stages, delay, kind)
    return input_width + (gain - 1).bit_length()


def _wrap(value, width):
    """Wrap ``value`` into the signed range of a ``width``-bit two's complement word."""
    mask = (1 << width) - 1
    v = value & mask
    sign = 1 << (width - 1)
    if v & sign:
        v -= 1 << width
    return v


def quantize(value, divisor, output_width):
    """Nearest-integer division with ties toward ``+infinity`` then signed saturation.

    Implemented as the exact integer expression ``floor((2*value + divisor) /
    (2*divisor))`` using Python floor division, then clamped to the signed range
    of ``output_width`` bits.
    """
    value = _as_int("value", value)
    divisor = _as_int("divisor", divisor)
    output_width = _as_int("output_width", output_width)
    if divisor <= 0:
        raise ValueError("divisor must be positive, got %d" % divisor)
    _check_range("output_width", output_width, 2, 32)
    q = (2 * value + divisor) // (2 * divisor)
    lo = -(1 << (output_width - 1))
    hi = (1 << (output_width - 1)) - 1
    if q < lo:
        return lo
    if q > hi:
        return hi
    return q


# --------------------------------------------------------------------------- #
# stateful building blocks
# --------------------------------------------------------------------------- #
class _IntegratorBank:
    """N integrator stages; stage k adds the *updated* stage k-1 on each sample."""

    __slots__ = ("n", "width", "state")

    def __init__(self, n, width):
        self.n = n
        self.width = width
        self.state = [0] * n

    def reset(self):
        self.state = [0] * self.n

    def advance(self, sample):
        v = _wrap(sample, self.width)
        st = self.state
        for i in range(self.n):
            v = _wrap(st[i] + v, self.width)
            st[i] = v
        return v


class _CombBank:
    """N comb stages ``(1 - z**-M)`` operating at the bank sample rate.

    A comb delays its stage *input*, not its output: each stage keeps its own
    last ``M`` inputs and the subtracted term is that stage's input exactly
    ``M`` steps ago (zero while the delay line is still filling).  The transfer
    of one stage is therefore the FIR ``1 - z**-M``; the per-stage input is
    captured before the subtraction and pushed into the delay line afterwards.
    """

    __slots__ = ("n", "m", "width", "hist")

    def __init__(self, n, m, width):
        self.n = n
        self.m = m
        self.width = width
        self.hist = [deque(maxlen=m) for _ in range(n)]

    def reset(self):
        for h in self.hist:
            h.clear()

    def advance(self, sample):
        v = _wrap(sample, self.width)
        m = self.m
        for i in range(self.n):
            h = self.hist[i]
            incoming = v
            delayed = h[0] if len(h) == m else 0
            v = _wrap(incoming - delayed, self.width)
            h.append(incoming)
        return v


# --------------------------------------------------------------------------- #
# base class
# --------------------------------------------------------------------------- #
class _CICBase:
    _KIND = "decimate"

    def __init__(self, rate, stages=3, delay=1, input_width=18,
                 acc_width=None, normalize=False, max_rate=MAX_RATE_LIMIT):
        # --- parameter validation (every scalar rejects bool / non integer) ---
        rate = _as_int("rate", rate)
        stages = _as_int("stages", stages)
        delay = _as_int("delay", delay)
        input_width = _as_int("input_width", input_width)
        max_rate = _as_int("max_rate", max_rate)

        _check_range("max_rate", max_rate, 1, MAX_RATE_LIMIT)
        _check_range("rate", rate, 1, max_rate)
        _check_range("stages", stages, 1, 5)
        _check_range("delay", delay, 1, 2)
        _check_range("input_width", input_width, 2, 32)

        # normalize must be a genuine bool flag
        if not isinstance(normalize, bool):
            raise TypeError("normalize must be a bool, got %s"
                            % type(normalize).__name__)

        # default accumulator width sized for the maximum supported rate so the
        # ratio can be reconfigured between frames without changing widths.
        default_w = register_width(input_width, max_rate, stages, delay, self._KIND)
        if acc_width is None:
            acc_width = default_w
        else:
            acc_width = _as_int("acc_width", acc_width)
        _check_range("acc_width", acc_width, input_width, 128)

        # --- public configuration (change rate through configure()) ---
        self.max_rate = max_rate
        self.stages = stages
        self.delay = delay
        self.input_width = input_width
        self.acc_width = acc_width
        self.normalize = normalize
        self._rate = rate
        self._gain = cic_gain(rate, stages, delay, self._KIND)
        self._in_lo = -(1 << (input_width - 1))
        self._in_hi = (1 << (input_width - 1)) - 1

        self._build_state()
        self._reset_state()

    # ------------------------------------------------------------------ #
    @property
    def rate(self):
        return self._rate

    @property
    def gain(self):
        return self._gain

    # ------------------------------------------------------------------ #
    def _build_state(self):
        raise NotImplementedError

    def _reset_state(self):
        raise NotImplementedError

    # ------------------------------------------------------------------ #
    def _validate_sample(self, sample):
        """Return ``(re, im)`` wrapped to nothing (range checked) or raise.

        No state is mutated here: an invalid sample leaves the filter untouched.
        """
        if isinstance(sample, (str, bytes)) or not hasattr(sample, "__len__"):
            try:
                seq = list(sample)
            except TypeError:
                raise TypeError(
                    "sample must be a length-2 sequence (re, im), got %s"
                    % type(sample).__name__)
        else:
            seq = list(sample)
        if len(seq) != 2:
            raise ValueError("sample must contain exactly 2 components, got %d"
                             % len(seq))
        re = _as_int("sample[0]", seq[0])
        im = _as_int("sample[1]", seq[1])
        _check_range("sample[0]", re, self._in_lo, self._in_hi)
        _check_range("sample[1]", im, self._in_lo, self._in_hi)
        return re, im

    @staticmethod
    def _validate_last(last):
        if not isinstance(last, bool):
            raise TypeError("last must be a bool, got %s" % type(last).__name__)

    # ------------------------------------------------------------------ #
    def _format_output(self, raw_re, raw_im):
        """Turn a wrapped accumulator pair into the emitted signed pair."""
        wr = _wrap(raw_re, self.acc_width)
        wi = _wrap(raw_im, self.acc_width)
        if self.normalize:
            wr = quantize(wr, self._gain, self.input_width)
            wi = quantize(wi, self._gain, self.input_width)
        return wr, wi

    # ------------------------------------------------------------------ #
    def push(self, sample, last=False):
        raise NotImplementedError

    def reset(self):
        """Reset numeric state, phase and frame tracking; keep the current rate."""
        self._reset_state()

    def configure(self, rate):
        """Change the rate.  Allowed only between frames; validates then resets."""
        rate = _as_int("rate", rate)
        _check_range("rate", rate, 1, self.max_rate)
        if self._in_frame:
            raise RuntimeError(
                "configure() not allowed mid-frame; call reset() first")
        self._rate = rate
        self._gain = cic_gain(rate, self.stages, self.delay, self._KIND)
        self._reset_state()


# --------------------------------------------------------------------------- #
# decimator
# --------------------------------------------------------------------------- #
class CICDecimator(_CICBase):
    """CIC decimator (``1/R`` rate change) -- accepted-sample model.

    ``push`` returns ``[]`` or a single ``((re, im), last)`` result.  A result is
    emitted on the last input of every R group (input indices ``R-1, 2R-1, ...``).
    ``last=True`` is legal only on a sample that completes an R group.
    """

    _KIND = "decimate"

    def _build_state(self):
        n = self.stages
        w = self.acc_width
        # one integrator bank and one comb bank per component (re, im)
        self._integ = [_IntegratorBank(n, w) for _ in range(2)]
        self._comb = [_CombBank(n, self.delay, w) for _ in range(2)]
        self._phase = 0
        self._in_frame = False

    def _reset_state(self):
        for bank in self._integ:
            bank.reset()
        for bank in self._comb:
            bank.reset()
        self._phase = 0
        self._in_frame = False

    # ------------------------------------------------------------------ #
    def push(self, sample, last=False):
        self._validate_last(last)
        re, im = self._validate_sample(sample)
        # A premature TLAST (not landing on an R-group boundary) is an error and
        # must leave every piece of state unchanged -> validated before mutation.
        completes = self._phase == self._rate - 1
        if last and not completes:
            raise ValueError(
                "last=True requires the input to complete an R-group "
                "(phase %d of R=%d)" % (self._phase, self._rate))

        # ---- mutation begins here ----
        self._in_frame = True
        s0 = self._integ[0].advance(re)
        s1 = self._integ[1].advance(im)

        if not completes:
            self._phase += 1
            return []

        out_re = self._comb[0].advance(s0)
        out_im = self._comb[1].advance(s1)
        self._phase = 0
        if last:
            self._in_frame = False
        return [(self._format_output(out_re, out_im), last)]


# --------------------------------------------------------------------------- #
# interpolator
# --------------------------------------------------------------------------- #
class CICInterpolator(_CICBase):
    """CIC interpolator (``R``x rate change) -- accepted-sample model.

    Each accepted input returns exactly ``R`` results (phases ``0..R-1``).  The
    ``last`` flag is raised only on the final phase when ``last=True`` was given.
    Structurally ``comb(delay M)@low -> upsample(R) -> integrators@high`` which
    is identical to ``zeroinsert`` convolved with ``(boxcar_{R*M})^{*N}``.
    """

    _KIND = "interpolate"

    def _build_state(self):
        n = self.stages
        w = self.acc_width
        self._comb = [_CombBank(n, self.delay, w) for _ in range(2)]
        self._integ = [_IntegratorBank(n, w) for _ in range(2)]
        self._in_frame = False

    def _reset_state(self):
        for bank in self._comb:
            bank.reset()
        for bank in self._integ:
            bank.reset()
        self._in_frame = False

    # ------------------------------------------------------------------ #
    def push(self, sample, last=False):
        self._validate_last(last)
        re, im = self._validate_sample(sample)

        # ---- mutation begins here ----
        self._in_frame = True
        v0 = self._comb[0].advance(re)
        v1 = self._comb[1].advance(im)

        rate = self._rate
        results = []
        for phase in range(rate):
            feed0 = v0 if phase == 0 else 0
            feed1 = v1 if phase == 0 else 0
            o0 = self._integ[0].advance(feed0)
            o1 = self._integ[1].advance(feed1)
            flag = bool(last and phase == rate - 1)
            results.append((self._format_output(o0, o1), flag))

        if last:
            self._in_frame = False
        return results


# --------------------------------------------------------------------------- #
# functional convenience API
# --------------------------------------------------------------------------- #
def decimate(samples, rate, **kwargs):
    """Convenience wrapper: fresh instance, list in, list of pairs out."""
    return _run_batch(CICDecimator, samples, rate, **kwargs)


def interpolate(samples, rate, **kwargs):
    """Convenience wrapper: fresh instance, list in, list of pairs out."""
    return _run_batch(CICInterpolator, samples, rate, **kwargs)


def _run_batch(cls, samples, rate, **kwargs):
    if isinstance(samples, (str, bytes)):
        raise TypeError("samples must be an iterable of (re, im) pairs")
    try:
        items = list(samples)
    except TypeError:
        raise TypeError("samples must be an iterable of (re, im) pairs")

    # Constructor validates parameters before any sample is consumed.
    obj = cls(rate, **kwargs)

    if len(items) == 0:
        return []

    if cls is CICDecimator and len(items) % obj.rate != 0:
        raise ValueError(
            "decimate frame length %d is not a multiple of R=%d"
            % (len(items), obj.rate))

    results = []
    for idx, s in enumerate(items):
        is_last = idx == len(items) - 1
        for pair, _flag in obj.push(s, last=is_last):
            results.append(pair)
    return results
