"""Thin wire adapter and independent polynomial-division vectors for crc_stream.

The production model ext_code_basics is unchanged. Wire words carry bit0 first.
"""
from dataclasses import dataclass
import random
from ext_code_basics import crc_update, crc_bits, crc, crc_parallel, append_fcs, check_fcs


@dataclass(frozen=True)
class Config:
    width: int
    mode: int
    poly: int
    init: int
    xorout: int
    reflected: bool = False
    refout: bool = False


def reverse(value, width):
    return int(f'{value:0{width}b}'[::-1], 2)


def divide_crc(bits, cfg):
    """Long division of the complete polynomial, independent of LFSR recurrence."""
    poly = reverse(cfg.poly, cfg.width) if cfg.reflected else cfg.poly
    initial = reverse(cfg.init, cfg.width) if cfg.reflected else cfg.init
    message = 0
    for bit in bits:
        message = (message << 1) | bit
    dividend = (initial << len(bits)) ^ (message << cfg.width)
    divisor = (1 << cfg.width) | poly
    while dividend.bit_length() > cfg.width:
        dividend ^= divisor << (dividend.bit_length() - divisor.bit_length())
    raw = reverse(dividend, cfg.width) if cfg.reflected else dividend
    return (reverse(raw, cfg.width) if cfg.refout else raw) ^ cfg.xorout


def model_crc(bits, cfg):
    raw = crc_update(cfg.init, bits, cfg.width, cfg.poly, cfg.reflected)
    result = (reverse(raw, cfg.width) if cfg.refout else raw) ^ cfg.xorout
    assert result == divide_crc(bits, cfg)
    if not cfg.reflected:
        assert result == crc_bits(bits, cfg.width, cfg.poly, cfg.init,
                                  refout=cfg.refout, xorout=cfg.xorout)
    return result


def wire_bits(data, reflected):
    return [(b >> j) & 1 for b in data
            for j in (range(8) if reflected else range(7, -1, -1))]


def fcs_bits(value, cfg):
    order = range(cfg.width) if cfg.reflected else range(cfg.width-1, -1, -1)
    return [(value >> j) & 1 for j in order]


def words(bits, word_bits):
    if not bits:
        return [(0, 0, 1)]
    return [(sum(bit << j for j, bit in enumerate(bits[i:i+word_bits])),
             len(bits[i:i+word_bits]), int(i+word_bits >= len(bits)))
            for i in range(0, len(bits), word_bits)]


def frame(bits, cfg, word_bits):
    inputs = words(bits, word_bits)
    if cfg.mode == 2:
        payload = bits[:-cfg.width] if len(bits) >= cfg.width else []
        value = model_crc(payload, cfg)
        ok = len(bits) >= cfg.width and bits[-cfg.width:] == fcs_bits(value, cfg)
    else:
        value = model_crc(bits, cfg)
        ok = True
    if cfg.mode == 0:
        outputs = [(0, 0, 1, value, 1)]
    elif cfg.mode == 1:
        outputs = [(d, n, 0, 0, 0) for d, n, _ in inputs if n]
        outputs += [(d, n, last, value if last else 0, last)
                    for d, n, last in words(fcs_bits(value, cfg), word_bits)]
    else:
        outputs = [(d, n, last, value if last else 0, int(ok) if last else 0)
                   for d, n, last in inputs]
    return dict(cfg=cfg, inputs=inputs, outputs=outputs, error=int(not ok))


def cases(width, word_bits, seed=9041):
    rng = random.Random(seed + width + word_bits)
    reflected = width == 32
    poly = 0xedb88320 if reflected else 0x1021 if width == 16 else 1
    mask = (1 << width)-1
    xorout = mask if reflected else 0
    result = []
    for mode in range(3):
        cfg = Config(width, mode, poly, mask, xorout, reflected)
        for length in sorted({0, 1, 7, 8, 9, 31, 32, 33, width-1, width, width+1, 511}):
            for pattern in (0, 1, 2):
                bits = ([pattern] * length if pattern < 2 else
                        [rng.randrange(2) for _ in range(length)])
                if mode == 2:
                    bits += fcs_bits(model_crc(bits, cfg), cfg)
                result.append(frame(bits, cfg, word_bits))
    # Standard check, exhaustive single-bit errors, bursts and wrong wire ordering.
    cfg = Config(width, 2, poly, mask, xorout, reflected)
    data = b'123456789'
    payload = wire_bits(data, reflected)
    value = model_crc(payload, cfg)
    if width in (16, 32):
        assert value == (0xcbf43926 if reflected else 0x29b1)
        assert value == crc(data, width, 0x04c11db7 if reflected else poly,
                            mask, reflected, reflected, xorout)
        packet = append_fcs(data, 'ethernet' if reflected else 'ccitt_false')
        assert wire_bits(packet, reflected) == payload + fcs_bits(value, cfg)
        assert check_fcs(packet, 'ethernet' if reflected else 'ccitt_false')
        residue = crc_update(mask, wire_bits(packet, reflected), width, poly, reflected)
        assert residue == (0xdebb20e3 if reflected else 0)
        # Reverse FCS bytes without changing the bit order inside any byte.
        wrong_endian = data + packet[len(data):][::-1]
        assert not check_fcs(wrong_endian, 'ethernet' if reflected else 'ccitt_false')
        wrong_frame = frame(wire_bits(wrong_endian, reflected), cfg, word_bits)
        assert wrong_frame['error'] == 1
        result.append(wrong_frame)
    good = payload + fcs_bits(value, cfg)
    result.append(frame(good, cfg, word_bits))
    for i in range(len(good)):
        bad = good.copy(); bad[i] ^= 1
        result.append(frame(bad, cfg, word_bits))
    for length in (2, 3, 7, 8, min(width, 17)):
        bad = good.copy()
        for i in range(3, 3+length):
            bad[i] ^= 1
        result.append(frame(bad, cfg, word_bits))
    for bad in ([], [1], good[:width-1], payload + fcs_bits(value, cfg)[::-1],
                wire_bits(data, not reflected) + fcs_bits(value, cfg)):
        result.append(frame(bad, cfg, word_bits))
    # Full byte input domain and random full-range polynomials/registers, both directions.
    for value in range(256):
        cfg = Config(width, value % 3, poly, mask, xorout, reflected)
        bits = wire_bits(bytes([value]), reflected)
        if cfg.mode == 2:
            bits += fcs_bits(model_crc(bits, cfg), cfg)
        result.append(frame(bits, cfg, word_bits))
    for i in range(32):
        cfg = Config(width, i % 3, rng.getrandbits(width), rng.getrandbits(width),
                     rng.getrandbits(width), bool(i & 1), bool(i & 2))
        bits = [rng.randrange(2) for _ in range(i * 3)]
        if cfg.mode == 2:
            bits += fcs_bits(model_crc(bits, cfg), cfg)
        result.append(frame(bits, cfg, word_bits))
    # Explicit zero/all-one register and polynomial boundaries.
    for value in (0, mask):
        for direction in (False, True):
            cfg = Config(width, 0, value, value, value, direction, True)
            result.append(frame([0, 1]*17, cfg, word_bits))
    return result


def write_vectors(path, width, word_bits):
    entries = cases(width, word_bits)
    rows = [str(len(entries))]
    for entry in entries:
        c = entry['cfg']
        rows.append(f'{c.mode} {c.poly:x} {c.init:x} {c.xorout:x} '
                    f'{int(c.reflected)} {int(c.refout)} '
                    f'{len(entry["inputs"])} {len(entry["outputs"])} {entry["error"]}')
        rows.extend(f'{d:x} {n} {last}' for d, n, last in entry['inputs'])
        rows.extend(f'{d:x} {n} {last} {crc_value:x} {ok}'
                    for d, n, last, crc_value, ok in entry['outputs'])
    path.write_text('\n'.join(rows)+'\n')
    return dict(frames=len(entries), inputs=sum(len(e['inputs']) for e in entries),
                outputs=sum(len(e['outputs']) for e in entries),
                rejected_fcs=sum(e['error'] for e in entries))
