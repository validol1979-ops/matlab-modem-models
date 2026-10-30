"""Thin accepted-sample/vector adapter for the unchanged SOSFilterFixed model."""
from pathlib import Path
import json
import numpy as np
from scipy import signal
from ext_signal_sos import SOSFilterFixed


class TracedSOS(SOSFilterFixed):
    """Observe the model's existing clip calls, without duplicating its arithmetic."""
    def _clip(self, value, bits):
        result = super()._clip(value, bits)
        self.trace.append((int(value), result))
        return result

    def sample(self, pair):
        self.trace = []
        result = self.push(pair)
        return result, list(self.trace)


def cases(seed=8202):
    rng = np.random.default_rng(seed)
    rails = [(-131072, 131071), (131071, -131072), (0, 0), (-1, 1), (-3, 3), (-5, 5)]
    random = [tuple(map(int, row)) for row in rng.integers(-131072, 131072, (512, 2))]
    small = [tuple(map(int, row)) for row in rng.integers(-3000, 3001, (384, 2))]
    yield 'identity', [[1, 0, 0, 1, 0, 0]], rails + random
    yield 'ties', [[.5, 0, 0, 1, 0, 0]], rails + random
    # Signed32 coefficient endpoints (exact at every supported fractional precision).
    yield 'coefficient_rails', [[(2**31-1)/2**28, -8, 7, 1, -.5, .125]], rails + random
    yield 'state_clipping', [[7, 7, 7, 1, -.99, 0]], rails * 5 + [(131071, -131072)] * 96
    for n in (1, 2, 4):
        for kind in ('lowpass', 'highpass'):
            wave = [(20000, -20000)] + [(0, 0)] * 127
            wave += [(30000, -30000)] * 256 + small + rails + random
            yield f'butter_{n}_{kind}', signal.butter(2*n, .3, btype=kind, output='sos'), wave
    r = .995
    yield 'resonator', [[.001, 0, 0, 1, -2*r*np.cos(.19*np.pi), r*r]], [(20000, -20000)] + [(0, 0)]*7999
    yield 'limit_cycle', [[1, 0, 0, 1, -.99, 0]], [(131071, -131072)] + [(0, 0)]*5000
    yield 'dc_step', [[.125, 0, 0, 1, -.875, 0]], [(30000, -30000)]*1024


def exhaustive_cases():
    """Every signed18 input code on both channels, including every half-way tie."""
    for start in range(-131072, 131072, 8192):
        yield f'full_range_{start+131072}', [[.5, 0, 0, 1, 0, 0]], [
            (value, -1-value) for value in range(start, start+8192)]


def write_vectors(path, coef_frac=28, state_bits=64, seed=8202):
    """Configuration uses model.sos after balancing/quantization, never float RTL math.

    Each sample has input IQ, TLAST, output IQ, sticky clipping; then, for each
    channel/section, y/s1/s2 followed by their three pre-clipping integer values.
    Frame boundaries deliberately do not reset the model.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    specs = list(cases(seed))
    # The baseline covers every input code. Other formats use the same directed
    # and random cases without repeating this comparatively large exhaustive set.
    if (coef_frac, state_bits) == (28, 64):
        specs.extend(exhaustive_cases())
    report = dict(coef_frac=coef_frac, state_bits=state_bits, samples=0, cases=[], clippings=0)
    with path.open('w') as stream:
        stream.write(f'{len(specs)}\n')
        for name, sos, wave in specs:
            # At F16, include both exact signed32 endpoints as feedforward coefficients.
            if name == 'coefficient_rails':
                sos = [[(2**31-1)/2**coef_frac, -(2**31)/2**coef_frac, 7, 1, -.5, .125]]
            model = TracedSOS(sos, coef_bits=coef_frac, state_bits=state_bits)
            n = len(model.sos)
            stream.write(f'{n} {len(wave)}\n')
            for b0, b1, b2, _, a1, a2 in model.sos:
                stream.write(f'{b0} {b1} {b2} {a1} {a2}\n')
            for i, pair in enumerate(wave):
                out, trace = model.sample(pair)
                last = int(i in (0, 6, 31, 127) or i == len(wave)-1)
                stream.write(' '.join(map(str, (*pair, last, *out, int(model.clippings > 0))))+'\n')
                for offset in range(0, len(trace), 3):
                    triple = trace[offset:offset+3]
                    stream.write(' '.join(map(str, [v[1] for v in triple]+[v[0] for v in triple]))+'\n')
            entry = dict(name=name, sections=n, samples=len(wave), clippings=model.clippings,
                         tail_peak=max(abs(v) for v in model.last))
            report['cases'].append(entry)
            report['samples'] += len(wave)
            report['clippings'] += model.clippings
    path.with_suffix('.json').write_text(json.dumps(report, indent=2)+'\n')
    return report
