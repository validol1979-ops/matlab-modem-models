"""Thin accepted-sample/vector adapter for CIC RTL; production model is unchanged.

Expected words come from independent exact FIR convolution, checked against the
fixed model before writing. File blocks contain header, inputs, then outputs.
"""
from dataclasses import dataclass
from fractions import Fraction
from functools import lru_cache
import math
from pathlib import Path
import random

from cic_model import CICDecimator, register_width
from cic_reference import decimate_reference

LO, HI = -131072, 131071
KINDS = ('impulse', 'dc', 'alternating', 'rails', 'random')


@dataclass(frozen=True)
class Profile:
    stages: int
    delay: int
    normalize: bool = False
    acc_width: int | None = None

    @property
    def width(self):
        return self.acc_width or register_width(18, 32, self.stages, self.delay)

    @property
    def name(self):
        return f'n{self.stages}_m{self.delay}_norm{int(self.normalize)}_aw{self.width}'


PROFILES = tuple(Profile(n, m, norm) for n in (1, 2, 3, 5)
                 for m in (1, 2) for norm in (False, True)) + (
                     Profile(5, 2, False, 18), Profile(5, 2, True, 18))


def wave(kind, count, seed):
    rng = random.Random(seed)
    if kind == 'impulse':
        return [(HI, LO)] + [(0, 0)] * (count - 1)
    if kind == 'dc':
        return [(LO, HI)] * count
    if kind == 'alternating':
        return [(LO, HI) if i % 2 else (HI, LO) for i in range(count)]
    if kind == 'rails':
        values = [(LO, LO), (HI, HI), (LO, HI), (HI, LO), (0, -1), (1, 0)]
        return [values[i % len(values)] for i in range(count)]
    if kind == 'random':
        return [(rng.randint(LO, HI), rng.randint(LO, HI)) for _ in range(count)]
    raise ValueError(f'Unknown wave: {kind}')


def wrap(value, width):
    return (value + (1 << (width - 1))) % (1 << width) - (1 << (width - 1))


def independent_format(value, profile, rate):
    value = wrap(value, profile.width)
    if profile.normalize:
        gain = (rate * profile.delay) ** profile.stages
        value = math.floor(Fraction(value, gain) + Fraction(1, 2))
        value = min(HI, max(LO, value))
    return value


@lru_cache(maxsize=8)
def raw_cases(stages, delay):
    records = []
    for rate in range(1, 33):
        for kind in KINDS:
            samples = wave(kind, 16 * rate, 20261030 + rate * 100 + stages * 10 + delay)
            raw = decimate_reference(samples, rate, stages, delay)
            records.append((rate, kind, tuple(samples), tuple(raw)))
    # Explicit positive/negative half ties at gain 2 (and near ties elsewhere).
    samples = [(0, 0), (1, -1), (0, 0), (3, -3), (0, 0), (5, -5), (0, 0), (7, -7)]
    records.append((2, 'ties', tuple(samples), tuple(decimate_reference(samples, 2, stages, delay))))
    return tuple(records)


def cases(profile):
    for rate, kind, samples, raw in raw_cases(profile.stages, profile.delay):
        inputs = [(a, b, int(i in (len(samples)//2-1, len(samples)-1)))
                  for i, (a, b) in enumerate(samples)]
        expected = [(*(independent_format(v, profile, rate) for v in pair),
                     int(i in (len(raw)//2-1, len(raw)-1))) for i, pair in enumerate(raw)]
        model = CICDecimator(rate, profile.stages, profile.delay, acc_width=profile.width,
                             normalize=profile.normalize)
        actual = []
        for a, b, last in inputs:
            actual.extend((*pair, int(flag)) for pair, flag in model.push((a, b), bool(last)))
        if actual != expected:
            raise AssertionError(f'Fixed/FIR mismatch: {profile.name}, R={rate}, {kind}')
        yield rate, kind, inputs, expected


def vectors(path, profile):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    counts = dict(cases=0, inputs=0, outputs=0, frames=0)
    with path.open('w') as stream:
        for rate, _kind, inputs, expected in cases(profile):
            stream.write(f'{rate} {len(inputs)} {len(expected)}\n')
            for row in inputs + expected:
                stream.write(' '.join(map(str, row)) + '\n')
            counts['cases'] += 1
            counts['inputs'] += len(inputs)
            counts['outputs'] += len(expected)
            counts['frames'] += 2
    return dict(profile=profile.name, **counts)
