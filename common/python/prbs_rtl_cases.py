"""Thin word-stream adapter to ext_code_basics; no alternative scrambling model.

Words are LSB first. Each case has several frames under one configuration.
Self-sync history is reconstructed from the reference's transmitted bits.
"""
from pathlib import Path
import random
from ext_code_basics import (prbs_bits, lfsr_jump, additive_scramble,
                             selfsync_scramble, selfsync_descramble)

ORDERS = (7, 9, 15, 31)
HDL_CASES = tuple((n, 1) for n in ORDERS) + ((7, 8), (9, 3), (15, 32), (31, 64))


def bits_of(words, width):
    return [(word >> i) & 1 for word in words for i in range(width)]


def pack(bits):
    return sum(bit << i for i, bit in enumerate(bits))


def reference(order, width, mode, seed, restart, frames):
    """Return (input, last, output, post-word state) rows using only original APIs."""
    if order not in ORDERS or not 1 <= width <= 64 or mode not in range(4):
        raise ValueError('Unsupported profile, word width or mode')
    if not 0 <= seed < 1 << order or (seed == 0) == (mode < 2):
        raise ValueError('PRBS requires nonzero seed; self-sync requires zero history')
    if not frames or any(not frame for frame in frames):
        raise ValueError('Frames must contain at least one word')
    if any(type(w) is not int or not 0 <= w < 1 << width for f in frames for w in f):
        raise ValueError('Word outside unsigned range')
    rows = []
    groups = [[f] for f in frames] if restart else [frames]
    for group in groups:
        words = [w for frame in group for w in frame]
        bits = bits_of(words, width)
        if mode == 0:
            expected, _ = prbs_bits(order, len(bits), seed)
        elif mode == 1:
            expected = additive_scramble(bits, order, seed)
        elif mode == 2:
            expected = selfsync_scramble(bits, order)
        else:
            expected = selfsync_descramble(bits, order)
        state = seed
        offset = 0
        for frame in group:
            for index, word in enumerate(frame):
                end = offset + width
                if mode < 2:
                    _, state = prbs_bits(order, width, state)
                else:
                    history = (expected if mode == 2 else bits)[max(0, end-order):end]
                    # Most recent bit occupies bit 0 of the history register.
                    state = pack(history[::-1])
                rows.append((word, int(index == len(frame)-1), pack(expected[offset:end]), state))
                offset = end
        if mode < 2 and state != lfsr_jump(order, len(bits), seed):
            raise RuntimeError('Iterative PRBS state differs from independent GF2 jump')
    return rows


def cases(order, width):
    rng = random.Random(0x50524253 + order * 64 + width)
    mask = (1 << width)-1
    values = [0, mask, mask & 0xaaaaaaaaaaaaaaaa, mask & 0x5555555555555555]
    values += [1 << i for i in range(width)] + [mask ^ (1 << i) for i in range(width)]
    values += list(range(1 << width)) if width <= 8 else [rng.getrandbits(width) for _ in range(256)]
    result = []
    for mode in range(4):
        seeds = (1, (1 << order)-1, 1 << (order-1), rng.randrange(1, 1 << order)) if mode < 2 else (0,)
        for restart in (0, 1):
            for seed in seeds:
                frames = [[values[0]], values, [rng.getrandbits(width) for _ in range(17)]]
                result.append((mode, seed, restart, reference(order, width, mode, seed, restart, frames)))
    # A full small-order period is also exercised by the actual HDL scoreboard.
    length = (1 << order)-1 if order <= 15 else 4096
    frames = [[0] * ((length + width-1)//width)]
    result.append((0, (1 << order)-1, 0, reference(order, width, 0, (1 << order)-1, 0, frames)))
    # Explicit round trips and self-sync single-error propagation in HDL vectors.
    source = [rng.getrandbits(width) for _ in range(96)]
    raw = bits_of(source, width)
    encrypted = additive_scramble(raw, order, 1)
    encrypted_words = [pack(encrypted[i:i+width]) for i in range(0, len(raw), width)]
    result.append((1, 1, 0, reference(order, width, 1, 1, 0, [encrypted_words])))
    encrypted = selfsync_scramble(raw, order)
    for corrupt in (False, True):
        received = encrypted.copy()
        if corrupt:
            received[width+1] ^= 1
        words = [pack(received[i:i+width]) for i in range(0, len(raw), width)]
        result.append((3, 0, 0, reference(order, width, 3, 0, 0, [words])))
    if order == 7:
        for seed in range(1, 128):
            result.append((0, seed, 0, reference(order, width, 0, seed, 0, [[0]*3])))
    return result


def vectors(path, order, width):
    entries = cases(order, width)
    lines = [str(len(entries))]
    for mode, seed, restart, rows in entries:
        lines.append(f'{mode} {seed:x} {restart} {len(rows)}')
        lines.extend(f'{x:x} {last} {y:x} {state:x}' for x, last, y, state in rows)
    Path(path).write_text('\n'.join(lines) + '\n')
    return dict(configurations=len(entries), outputs=sum(len(v[3]) for v in entries))
