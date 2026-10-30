"""Continuous-rate Costas vectors: bit-exact outputs of sync_fixed.costas_pipelined for
rtl/common/costas_stream.sv (the same per-sample arithmetic as costas_loop.sv, but with the loop
delay counted in samples instead of a per-transaction restart).

Each case directory holds cl_cfg.txt (`k1 k2`, the integer gains of sync_fixed.costas_gains),
cl_in.txt (first line: number of samples; then `re im last`) and cl_out.txt (first line: number of
outputs; then `re im phase last`) - the layout rtl/tb/costas_stream_tb.sv reads. Values are Q15 ints
inside the signed 18-bit range, phases are 32-bit signed (2^-32 turns).

The stream is CONTINUOUS: `last` only marks the end of a group of samples and is copied to the
output; the loop state is never restarted by it. A case may therefore hold several groups back to
back (`frames`), which costas_loop.sv cannot do without a reconfiguration gap.
"""
import math
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'common/python'))
import sync_fixed  # noqa: E402

LOOP_DELAY = 10   # samples; see rtl/common/costas_stream.sv and docs/RTL_COSTAS_STREAM.md
FULL = 131072     # |Q15| full scale (the signed 18-bit range is -131072..131071)
CORNER = 23170    # 1/sqrt(2) in Q15: a unit-amplitude QPSK point lands on +-FULL/2 in both axes
QUADRANTS = ((1, 1), (-1, 1), (-1, -1), (1, -1))


def clamp(value):
    return max(-FULL, min(FULL - 1, int(round(value))))


def qpsk(length, seed, magnitude, phase, last_lengths=None):
    """QPSK labels (random per seed) times exp(j phase(n)) scaled by magnitude(rng, n), clipped to Q15."""
    rng = random.Random(seed)
    data = []
    for n in range(length):
        q_re, q_im = QUADRANTS[rng.randrange(4)]
        value, theta = magnitude(rng, n), phase(n)
        data.append((clamp(value * (q_re * math.cos(theta) - q_im * math.sin(theta))),
                     clamp(value * (q_re * math.sin(theta) + q_im * math.cos(theta)))))
    last = []
    edge = 0
    for size in (last_lengths or [length]):
        edge += size
        last += [False] * (edge - len(last))
        last[-1] = True
    return data, last


def signal_model():
    """The project's model case shape: random QPSK labels on a phase ramp, 768 samples."""
    return qpsk(768, 0, lambda rng, n: CORNER, lambda n: .3 + .006 * n)


def signal_limit():
    """The aggressive gain set (.3,.01) on a large offset: exercises the 32-bit phase wrap and the
    frequency accumulator. It is deliberately kept as the documented LIMIT of the continuous-rate
    loop: at the 10-advance delay this gain set does not lock any more (see LOCKED and
    docs/RTL_COSTAS_STREAM.md), although the outputs are still bit exact against the model - the
    bench scores arithmetic and protocol, not acquisition quality."""
    return qpsk(512, 1, lambda rng, n: 20000 + rng.randrange(8000), lambda n: 1.1 + .02 * n)


def signal_slow():
    """Small gains and a long, slowly rotating stream."""
    return qpsk(1200, 2, lambda rng, n: 18000 + rng.randrange(4000), lambda n: -.4 + .0015 * n)


def signal_corners():
    """Discriminator corner cases: axes (error 0), constellation corners, both full-scale rails."""
    rows = [(FULL - 1, 0), (0, FULL - 1), (-FULL, 0), (0, -FULL),
            (FULL - 1, FULL - 1), (-FULL, FULL - 1), (-FULL, -FULL), (FULL - 1, -FULL),
            (65536, 65536), (-65536, 65536), (-65536, -65536), (65536, -65536),
            (1, 1), (-1, 1), (-1, -1), (1, -1),
            (0, 0), (CORNER, CORNER), (-CORNER - 1, -CORNER - 1)]
    data = [rows[n % len(rows)] for n in range(400)]
    return data, [n == 399 for n in range(400)]


def signal_frames():
    """Back-to-back groups of 37, 1, 128 and 37 samples: `last` must not restart the loop."""
    return qpsk(203, 3, lambda rng, n: 18000 + rng.randrange(5000),
                lambda n: .2 + .004 * n, last_lengths=[37, 1, 128, 37])


def signal_off():
    """Zero gains: the phase never moves, rotate(x, 0) is a pure 17-bit scaling."""
    rows = [(FULL - 1, 0), (0, FULL - 1), (-FULL, 0), (0, -FULL)]
    data = [rows[n % 4] for n in range(64)]
    return data, [n == 63 for n in range(64)]


# Carrier phase of the generated stream (radians); the runner compares the tracked phase against it
# modulo 90 degrees (a QPSK Costas loop locks with a four-fold phase ambiguity).
CARRIERS = {
    'model': lambda n: .3 + .006 * n,
    'limit': lambda n: 1.1 + .02 * n,
    'slow': lambda n: -.4 + .0015 * n,
    'frames': lambda n: .2 + .004 * n,
}
# Whether the integer model locks at LOOP_DELAY (mean |residual mod 90 deg| below 0.05 rad over the
# second half of the case); None where the case has no carrier to lock to.
LOCKED = {'model': True, 'limit': False, 'slow': True, 'frames': True, 'corners': None, 'off': None}

CASES = {
    'model': (signal_model, (.08, .001)),
    'limit': (signal_limit, (.3, .01)),
    'slow': (signal_slow, (.02, .0001)),
    'corners': (signal_corners, (.08, .001)),
    'frames': (signal_frames, (.08, .001)),
    'off': (signal_off, (0, 0)),
}


def expected(data, gains):
    return sync_fixed.costas_pipelined(data, sync_fixed.costas_gains(*gains), LOOP_DELAY)


def write_case(directory, data, last, gains):
    """Write one case (cl_cfg.txt, cl_in.txt, cl_out.txt) and return its expected outputs."""
    directory.mkdir(parents=True, exist_ok=True)
    values, phases = expected(data, gains)
    k1, k2 = sync_fixed.costas_gains(*gains)
    (directory / 'cl_cfg.txt').write_text(f'{k1} {k2}\n')
    (directory / 'cl_in.txt').write_text(f'{len(data)}\n' +
                                         ''.join(f'{re} {im} {1 if last[n] else 0}\n'
                                                 for n, (re, im) in enumerate(data)))
    (directory / 'cl_out.txt').write_text(f'{len(values)}\n' +
                                          ''.join(f'{re} {im} {phases[n]} {1 if last[n] else 0}\n'
                                                  for n, (re, im) in enumerate(values)))
    return values, phases


def vectors(directory):
    """Write every case under `directory`; return {name: (samples, gains, last_flags)}."""
    directory.mkdir(parents=True, exist_ok=True)
    table = {}
    for name, (builder, gains) in CASES.items():
        data, last = builder()
        write_case(directory / name, data, last, gains)
        table[name] = (len(data), gains, last)
    return table


if __name__ == '__main__':
    target = Path(sys.argv[1] if len(sys.argv) > 1 else 'build/rtl/costas_stream/vectors')
    for name, (count, gains, _) in vectors(target).items():
        print(f'{name}: {count} samples, gains {gains}')
