"""AM TX amp=.5*(1+depth*m), IQ=amp*exp(j phase); RX envelope, DC block, audio LPF.

Float TX uses the ideal DDS phasor, fixed TX the supplied 32-bit DDS ROM.
Fixed RX: Q30 one-pole coefficients, signed64 states with Q17 fraction, integer
isqrt envelope, half-up Q17 output and signed18 saturation. A one-pole low-pass
has DC gain 1 and gain alpha/|1-(1-alpha)e^-jw| (approximately -3 dB near cutoff when cutoff << fs). Validate
everything before mutating; a stalled/rejected sample holds output and state.
"""
import math
import numbers
from ext_signal_core import DDS

AMP = 131071                        # symmetric signed18 magnitude
IN18 = (-(1 << 17), (1 << 17) - 1)  # full signed18 IQ rails
A18 = (-AMP, AMP)                   # -131072 excluded by the audio bound
Q17, Q30, C64 = 1 << 17, 1 << 30, 1 << 63


def _flag(n, v):
    if type(v) is not bool:
        raise TypeError(f"{n} must be bool, got {type(v).__name__}")


def _num(n, v, lo, hi, integer=False):
    if type(v) is bool or not isinstance(v, numbers.Integral if integer else numbers.Real):
        raise TypeError(f"{n} must be {'int' if integer else 'real'}: {type(v).__name__}")
    x = int(v) if integer else float(v)
    if not integer and not math.isfinite(x):
        raise ValueError(f"{n} must be finite: {v}")
    if not lo <= x <= hi:
        raise ValueError(f"{n} out of range {lo}..{hi}: {v}")
    return x


def _rh(v, b):                      # nearest /2**b, ties toward +infinity
    return (v + (1 << (b - 1))) >> b


def _rd(v, d):                      # nearest integer division, ties upward
    return (v + d // 2) // d


def _sat18(v):
    return AMP if v > AMP else (-AMP if v < -AMP else v)


class _Stream:
    def process(self, seq):
        vals = tuple(seq)
        for v in vals:
            self._check_sample(v)
        return [self.push(v) for v in vals]


class AMModulator(_Stream):
    """Full-carrier AM; .5 headroom keeps carrier+sidebands below full scale."""

    def __init__(self, depth=0.5, step=0, fixed=False):
        _flag("fixed", fixed)
        self._depth, self._fixed = _num("depth", depth, 0.0, 1.0), fixed
        self._dds = DDS(step)
        self._dq = int(math.floor(self._depth * Q17 + 0.5))
        self.reset()

    def reset(self):
        self._dds.reset(0)
        self._held = (0, 0) if self._fixed else 0j
        self.clip_count = 0

    def _check_sample(self, v):
        return _num("audio", v, *A18, integer=True) if self._fixed else _num("audio", v, -1.0, 1.0)

    def push(self, audio, accept=True):
        _flag("accept", accept)
        v = self._check_sample(audio)
        if not accept:
            return self._held
        if self._fixed:
            amp = (AMP + _rh(self._dq * v, 17)) // 2
            i, q = self._dds.next(True)
            ri, rq = _rd(amp * i, AMP), _rd(amp * q, AMP)
            oi, oq = _sat18(ri), _sat18(rq)
            self.clip_count += (oi != ri) + (oq != rq)
            self._held = (oi, oq)
        else:
            amp, ph = 0.5 * (1.0 + self._depth * v), self._dds.value_float()
            self._dds.next(True)
            self._held = amp * ph
        return self._held


class AMDemodulator(_Stream):
    """Envelope abs(IQ), one-pole DC estimate, then one-pole audio low-pass."""

    def __init__(self, fs=400000, cutoff=5000, dc_cutoff=20, fixed=False):
        _flag("fixed", fixed)
        self._fs, self._fixed = _num("fs", fs, 0.0, math.inf), fixed
        self._cutoff = _num("cutoff", cutoff, 0.0, math.inf)
        self._dc_cutoff = _num("dc_cutoff", dc_cutoff, 0.0, math.inf)
        if not 0.0 < self._dc_cutoff < self._cutoff < self._fs / 2.0:
            raise ValueError("require 0 < dc_cutoff < cutoff < fs/2")
        self._alpha = -math.expm1(-2.0 * math.pi * self._cutoff / self._fs)
        self._beta = -math.expm1(-2.0 * math.pi * self._dc_cutoff / self._fs)
        self._aq = int(math.floor(self._alpha * Q30 + 0.5))
        self._bq = int(math.floor(self._beta * Q30 + 0.5))
        if fixed and (not 0 < self._aq < Q30 or not 0 < self._bq < Q30):raise ValueError("Q30 cutoff not representable")
        self.reset()

    def reset(self):
        self._dcr = self._lpr = 0
        self._dc = self._lp = 0.0
        self._held = 0
        self.clip_count = self.state_clip_count = 0

    def _check_sample(self, v):
        if not self._fixed:
            if type(v) is bool or not isinstance(v, numbers.Complex):
                raise TypeError(f"IQ must be complex, got {type(v).__name__}")
            z = complex(v)
            if not (math.isfinite(z.real) and math.isfinite(z.imag)):
                raise ValueError("IQ must be finite")
            return z
        if type(v) is not tuple or len(v) != 2:
            raise TypeError("fixed IQ must be an ordinary tuple (I, Q)")
        return _num("I", v[0], *IN18, integer=True), _num("Q", v[1], *IN18, integer=True)

    def _upd(self, raw, coef, inraw):  # signed64 state keeps Q17 fraction
        v = raw + ((coef * ((inraw << 17) - raw) + (1 << 29)) >> 30)
        if not -C64 <= v < C64:
            v = max(-C64, min(C64 - 1, v))
            self.state_clip_count += 1
        return v

    def push(self, iq, accept=True):
        _flag("accept", accept)
        v = self._check_sample(iq)
        if not accept:
            return self._held
        if not self._fixed:
            env = abs(v)
            self._dc += self._beta * (env - self._dc)
            self._lp += self._alpha * ((env - self._dc) - self._lp)
            self._held = float(self._lp)
            return self._held
        env = math.isqrt(v[0] * v[0] + v[1] * v[1])
        self._dcr = self._upd(self._dcr, self._bq, env)
        self._lpr = self._upd(self._lpr, self._aq, env - (self._dcr >> 17))
        out = _rh(self._lpr, 17)                 # half-up Q17 -> integer audio
        sat = _sat18(out)
        self.clip_count += sat != out
        self._held = sat
        return sat
