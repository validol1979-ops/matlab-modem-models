"""DDS/NCO: 32-bit phase accumulator, signed18 IQ ROM addressed by top lut_bits."""
import math
import numbers

PHASE_MOD = 1 << 32
AMP = (1 << 17) - 1  # symmetric signed18 amplitude 131071


def _check_u32(name, v):
    if type(v) is not int:
        raise TypeError(f"{name} must be int, got {type(v).__name__}")
    if not 0 <= v < PHASE_MOD:
        raise ValueError(f"{name} out of range 0..2^32-1: {v}")
    return v


class DDS:
    """Continuous-phase NCO. Negative frequency: pass step = (-k) % 2**32."""

    def __init__(self, step, phase=0, lut_bits=12):
        if type(lut_bits) is not int:
            raise TypeError("lut_bits must be int")
        if not 2 <= lut_bits <= 16:
            raise ValueError(f"lut_bits out of range 2..16: {lut_bits}")
        n = 1 << lut_bits
        self._shift = 32 - lut_bits
        self._lut = [(round(AMP * math.cos(2 * math.pi * i / n)),
                      round(AMP * math.sin(2 * math.pi * i / n))) for i in range(n)]
        self._step = _check_u32("step", step)
        self._phase = _check_u32("phase", phase)

    @property
    def step(self):
        return self._step

    @property
    def phase(self):
        return self._phase

    def next(self, accept=True):
        """Return CURRENT (I, Q); advance phase by step only if accept is True."""
        if type(accept) is not bool:
            raise TypeError("accept must be bool")
        i, q = self._lut[self._phase >> self._shift]
        if accept:
            self._phase = (self._phase + self._step) % PHASE_MOD
        return (i, q)

    def value_float(self):
        """Ideal complex phasor of the current phase (no ROM quantization)."""
        a = 2 * math.pi * self._phase / PHASE_MOD
        return complex(math.cos(a), math.sin(a))

    def configure(self, step=None, phase=None):
        """Atomically validate and set step/phase; None keeps the current value."""
        new_step = self._step if step is None else _check_u32("step", step)
        new_phase = self._phase if phase is None else _check_u32("phase", phase)
        self._step, self._phase = new_step, new_phase

    def reset(self, phase=0):
        self._phase = _check_u32("phase", phase)


# ---------------- DSP-HILBERT: streaming real -> analytic (I = delayed x, Q = Hilbert) ----

ALLOWED_NUMTAPS = (31, 63)
SAT18 = (1 << 17) - 1                       # symmetric signed18 output rail 131071
IN18_MIN, IN18_MAX = -(1 << 17), (1 << 17) - 1   # signed18 input rails
ACC64 = 1 << 63                             # signed64 accumulator rails


def _check_accept(accept):
    if type(accept) is not bool:
        raise TypeError(f"accept must be bool, got {type(accept).__name__}")


def _check_real(name, v):
    if type(v) is bool or not isinstance(v, numbers.Real):
        raise TypeError(f"{name} must be real int/float, got {type(v).__name__}")
    if not math.isfinite(v):
        raise ValueError(f"{name} must be finite: {v}")
    return float(v)


def _check_int18(name, v):
    if type(v) is bool or not isinstance(v, numbers.Integral):
        raise TypeError(f"{name} must be int, got {type(v).__name__}")
    if not IN18_MIN <= v <= IN18_MAX:
        raise ValueError(f"{name} out of signed18 range {IN18_MIN}..{IN18_MAX}: {v}")
    return int(v)


def _round_halfup(v, bits):
    """Nearest division, exact ties toward positive infinity."""
    return (v + (1 << (bits - 1))) >> bits


def hilbert_taps(numtaps=31):
    """Hamming-windowed discrete Hilbert taps, antisymmetric about the centre.

    With k = n - (numtaps-1)/2: h[n] = (0.54 - 0.46*cos(2*pi*n/(M-1))) * 2/(pi*k)
    for odd k, else 0 (h at the centre is 0). Response -j*sgn(f) with group delay
    (numtaps-1)/2, so a causal cos gives a POSITIVE sin; gain ~1 (never 2).
    Returns a tuple of numtaps floats.
    """
    if type(numtaps) is bool or not isinstance(numtaps, int):
        raise TypeError(f"numtaps must be int, got {type(numtaps).__name__}")
    if numtaps not in ALLOWED_NUMTAPS:
        raise ValueError(f"numtaps must be one of {ALLOWED_NUMTAPS}: {numtaps}")
    d = (numtaps - 1) // 2
    h = []
    for n in range(numtaps):
        k = n - d
        w = 0.54 - 0.46 * math.cos(2 * math.pi * n / (numtaps - 1))
        h.append(0.0 if k % 2 == 0 else w * 2.0 / (math.pi * k))
    return tuple(h)


class _AnalyticBase:
    """Shared delay line (length == numtaps), validation-before-mutation, process()."""

    @staticmethod
    def _check(v):
        _check_real("sample", v)

    def __init__(self, numtaps):
        self._t = hilbert_taps(numtaps)
        self._m = len(self._t)
        self._d = (self._m - 1) // 2
        self.reset()

    @property
    def numtaps(self):
        return self._m

    @property
    def delay(self):
        return self._d

    @property
    def taps(self):
        return self._t

    def reset(self):
        """Clear the delay line, hold output at zero, clear clipping counters."""
        self._z = [0] * self._m          # _z[j] = x[n-j], newest first; bounded by numtaps
        self._held = self._zero
        self.clip_count = 0
        self.acc_clip_count = 0

    def process(self, seq):
        """Validate the whole sequence first (atomic), then push it; returns outputs."""
        vals = tuple(seq)
        for v in vals:
            self._check(v)
        return [self.push(v) for v in vals]


class AnalyticSignal(_AnalyticBase):
    """Real -> analytic FIR. push(x, accept=True) -> CURRENT complex(I + jQ) with
    I[n] = x[n-delay] (exact) and Q[n] = sum_k h[k]*x[n-k]. accept=False holds the last
    output and leaves the state untouched; invalid accept/sample raise before any change."""

    _zero = 0j

    def __init__(self, numtaps=63):
        super().__init__(numtaps)

    def push(self, sample, accept=True):
        _check_accept(accept)
        v = _check_real("sample", sample)
        if not accept:
            return self._held
        self._z.insert(0, v)
        del self._z[self._m:]
        self._held = complex(self._z[self._d],
                             sum(t * z for t, z in zip(self._t, self._z)))
        return self._held


class AnalyticSignalFixed(_AnalyticBase):
    """signed18 integer twin: offline float taps -> Q coef_bits integers, EXACT integer
    dot clamped to signed64, half-up divide by 2**coef_bits, symmetric signed18 saturation
    on Q. delayedI stays exact (may be -131072). push -> tuple (I, Q) of ints;
    clip_count counts saturated Q samples, acc_clip_count clamped 64-bit dots."""

    _zero = (0, 0)
    @staticmethod
    def _check(v):
        _check_int18("sample", v)

    def __init__(self, numtaps=63, coef_bits=17):
        if type(coef_bits) is bool or not isinstance(coef_bits, int) or not 1 <= coef_bits <= 24:
            raise ValueError(f"coef_bits must be int in 1..24: {coef_bits!r}")
        self._bits = coef_bits
        super().__init__(numtaps)
        scale = 1 << coef_bits
        self._ti = tuple(int(round(c * scale)) for c in self._t)   # runtime integer taps

    @property
    def coef_bits(self):
        return self._bits

    @property
    def taps_fixed(self):
        return self._ti

    def push(self, sample, accept=True):
        _check_accept(accept)
        v = _check_int18("sample", sample)
        if not accept:
            return self._held
        self._z.insert(0, v)
        del self._z[self._m:]
        acc = 0
        for t, z in zip(self._ti, self._z):
            acc += t * z
        if not -ACC64 <= acc < ACC64:                  # signed64 accumulator clamp
            acc = max(-ACC64, min(ACC64 - 1, acc))
            self.acc_clip_count += 1
        q = _round_halfup(acc, self._bits)
        if not -SAT18 <= q <= SAT18:                   # symmetric signed18 saturation
            q = SAT18 if q > SAT18 else -SAT18
            self.clip_count += 1
        self._held = (self._z[self._d], q)             # I exact, never saturated
        return self._held
