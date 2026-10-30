"""Signed Q formats: integer arithmetic, nearest-even rounding and saturation.

width includes the sign bit; frac is the number of fractional bits.
Raw integers, not binary floats, are the interface to bit-accurate RTL models.
"""
from dataclasses import dataclass
from fractions import Fraction
import math
from numbers import Integral


def integer(value):
    if not isinstance(value, Integral) or isinstance(value, bool):
        raise ValueError('Expected an integer')
    return int(value)


def round_shift(value, drop):
    """Scale an unbounded signed integer; midpoint ties go to an even integer."""
    value, drop = integer(value), integer(drop)
    if drop <= 0:
        return value << -drop
    quotient, remainder = divmod(value, 1 << drop)
    half = 1 << (drop - 1)
    return quotient + int(remainder > half or (remainder == half and quotient & 1))


@dataclass
class QuantizationStats:
    values: int = 0
    rounded: int = 0
    positive_overflows: int = 0
    negative_overflows: int = 0

    @property
    def overflows(self):
        return self.positive_overflows + self.negative_overflows


@dataclass(frozen=True)
class QFormat:
    width: int
    frac: int

    def __post_init__(self):
        integer(self.width); integer(self.frac)
        if self.width < 2 or not 0 <= self.frac < self.width:
            raise ValueError('Q format requires width >= 2 and 0 <= frac < width')

    @property
    def minimum(self):
        return -(1 << (self.width - 1))

    @property
    def maximum(self):
        return (1 << (self.width - 1)) - 1

    def check(self, raw):
        raw = integer(raw)
        if not self.minimum <= raw <= self.maximum:
            raise ValueError('Raw value outside Q format')
        return raw

    def saturate(self, raw, stats=None):
        raw = integer(raw)
        overflow = raw < self.minimum or raw > self.maximum
        if stats is not None:
            stats.values += 1
            stats.positive_overflows += int(raw > self.maximum)
            stats.negative_overflows += int(raw < self.minimum)
        return max(self.minimum, min(self.maximum, raw)), overflow

    def requantize(self, raw, source_frac, stats=None):
        raw, source_frac = integer(raw), integer(source_frac)
        if source_frac < 0:
            raise ValueError('Negative source fraction width')
        drop = source_frac - self.frac
        if stats is not None and drop > 0:
            stats.rounded += int(raw % (1 << drop) != 0)
        return self.saturate(round_shift(raw, drop), stats)

    def quantize(self, value, stats=None):
        # Fraction retains the actual value of a binary float, with exact ties.
        if isinstance(value, complex) or not math.isfinite(value):
            raise ValueError('Expected a finite real value')
        scaled = Fraction(value) * (1 << self.frac)
        if stats is not None:
            stats.rounded += int(scaled.denominator != 1)
        return self.saturate(round(scaled), stats)[0]

    def decode(self, raw):
        return self.check(raw) / (1 << self.frac)

    def encode_bits(self, raw):
        return self.check(raw) & ((1 << self.width) - 1)

    def decode_bits(self, bits):
        bits = integer(bits)
        if not 0 <= bits < 1 << self.width:
            raise ValueError('Bit pattern outside format width')
        return bits - (1 << self.width) if bits >> (self.width - 1) else bits


SAMPLE = QFormat(18, 15)  # Q(3.15), including the sign bit in the three bits.


def complex_multiply(a, b, source=SAMPLE, target=SAMPLE, stats=None):
    ar, ai = (source.check(v) for v in a)
    br, bi = (source.check(v) for v in b)
    re, re_over = target.requantize(ar * br - ai * bi, 2 * source.frac, stats)
    im, im_over = target.requantize(ar * bi + ai * br, 2 * source.frac, stats)
    return (re, im), int(re_over) | (int(im_over) << 1)


def complex_add(a, b, source=SAMPLE, target=SAMPLE, stats=None):
    ar, ai = (source.check(v) for v in a)
    br, bi = (source.check(v) for v in b)
    re, re_over = target.requantize(ar + br, source.frac, stats)
    im, im_over = target.requantize(ai + bi, source.frac, stats)
    return (re, im), int(re_over) | (int(im_over) << 1)


class ElasticPipeline:
    """Cycle model of a globally stalled pipeline, matching the initial RTL.

    tick returns the signals *before* the edge and updates registers at the edge.
    Reset discards all pending samples. Arithmetic data registers are not reset.
    """
    def __init__(self, latency, function):
        self.latency = integer(latency)
        if self.latency < 1:
            raise ValueError('Positive latency required')
        self.function = function
        self.stages = [None] * latency

    def tick(self, valid=False, data=None, last=False, ready=True, reset=False):
        output = self.stages[-1]
        advance = output is None or ready
        signals = dict(s_ready=bool(advance and not reset),
                       m_valid=bool(output is not None and not reset),
                       output=output, accepted=bool(valid and advance and not reset),
                       emitted=bool(output is not None and ready and not reset))
        if reset:
            self.stages = [None] * self.latency
        elif advance:
            self.stages = [(self.function(data), bool(last)) if valid else None] + self.stages[:-1]
        return signals
