"""Optional saturation counters for the fixed-point models (fir_fixed, fft_fixed).

A value equal to a rail is NOT a clipping event: record() counts a saturation event
only when the pre-clamp rounded value lies strictly outside the clamp's bounds.
FIR uses [-limit-1, limit]; FFT uses [-limit, limit]. A representable FFT value
-limit-1 is therefore a negative event, because the clamp changes that value.

record() also performs the model's own clamping so instrumented and plain runs stay
bit-identical: clamp='asym' reproduces fir sat18 (rails -limit-1, +limit);
clamp='sym' reproduces fft sat (both rails +-limit). Note that the fft model maps the
representable value -limit-1 to -limit; that is counted as a negative event.

Models take an optional stats=None keyword; the default calls and return values do not
touch this module at all, so default numerical results are unchanged by construction.
"""


class SatStats:
    def __init__(self):
        self.counts = {}

    def record(self, stage, value, limit, clamp='asym'):
        """Count one pre-clamp event for `stage`, return the model-clamped value."""
        low = -limit if clamp == 'sym' else -limit - 1
        if value > limit:
            self._bump(stage, 'pos')
        elif value < low:
            self._bump(stage, 'neg')
        return max(low, min(limit, value))

    def _bump(self, stage, sign):
        self.counts.setdefault(stage, {'pos': 0, 'neg': 0})[sign] += 1

    def total(self):
        return sum(c['pos'] + c['neg'] for c in self.counts.values())

    def merge(self, other):
        for stage, c in other.counts.items():
            t = self.counts.setdefault(stage, {'pos': 0, 'neg': 0})
            t['pos'] += c['pos']; t['neg'] += c['neg']
        return self

    def to_dict(self):
        return {'stages': {k: dict(v) for k, v in sorted(self.counts.items())}, 'total': self.total()}


def save_json(path, stats, **extra):
    """Write saturation metadata for one vector folder; returns the payload dict."""
    import json
    payload = dict(extra, model_only_evidence=True, **stats.to_dict())
    path.write_text(json.dumps(payload, indent=1, sort_keys=True) + '\n')
    return payload


class SatTrace(SatStats):
    """Also count evaluated clamp inputs, including every in-range value."""
    def __init__(self):
        super().__init__()
        self.evaluations = {}

    def record(self, stage, value, limit, clamp='asym'):
        self.evaluations[stage] = self.evaluations.get(stage, 0) + 1
        return super().record(stage, value, limit, clamp)

    def merge(self, other):
        super().merge(other)
        for stage, count in other.evaluations.items():
            self.evaluations[stage] = self.evaluations.get(stage, 0) + count
        return self

    def to_dict(self):
        return dict(super().to_dict(), evaluations=dict(sorted(self.evaluations.items())))


def write_expected(path, stats, stages):
    """Header = field count, followed by evaluations/positive/negative per field."""
    rows = [(stats.evaluations.get(stage, 0), stats.counts.get(stage, {}).get('pos', 0),
             stats.counts.get(stage, {}).get('neg', 0)) for stage in stages]
    path.write_text(str(len(rows)) + '\n' + '\n'.join(' '.join(map(str, row)) for row in rows) + '\n')
    return rows


class RangeTrace(SatTrace):
    """Trace min/max limiters with arbitrary rails as well as signed bit clamps."""
    def record_range(self, stage, value, low, high):
        if high is not None and low > high:
            raise ValueError('Invalid clamp interval')
        self.evaluations[stage] = self.evaluations.get(stage, 0) + 1
        if high is not None and value > high:
            self._bump(stage, 'pos')
        elif value < low:
            self._bump(stage, 'neg')
        return max(low, value if high is None else min(high, value))
