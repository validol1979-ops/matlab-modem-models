"""Rate-1/2, K=7 convolutional encoder and Viterbi decoder (stdlib only).

Source: vit_trellis.svh (first entry of direct_sources.json), pCODE_GEN = 171/133 octal.
  reg = (bit << 6) | state ; outputs = parity(reg & g) for g in (0o171, 0o133)
  next state = reg >> 1  (input bit becomes the MSB of the next state)
Sign convention: positive LLR favours bit 0; branch cost of coded bit c is c * LLR.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from fractions import Fraction

GENS = (0o171, 0o133)
MEM = 6                 # constraint length 7 -> 6 memory bits (tail length)
NSTATE = 1 << MEM       # 64 states


@dataclass(frozen=True)
class StageTrace:
    """Per-stage metrics: min/max over reachable states BEFORE normalization,
    and the normalization offset (= min) subtracted from every metric."""
    stage: int
    min_metric: object
    max_metric: object
    normalization: object


@dataclass
class DecodeResult:
    bits: list                       # decoded info bits (tail removed if terminated)
    metric_trace: list = field(default_factory=list)   # list of StageTrace
    final_state: int = 0
    final_metric: object = 0         # normalized metric of final state
    normalization_sum: object = 0    # sum of all per-stage offsets
    quant_bits: object = None        # None in float mode


def _outputs(reg):
    return tuple(bin(reg & g).count("1") & 1 for g in GENS)


# Trellis: for next state ns, input = ns >> 5; predecessors s = 2*(ns & 31) + x (ascending).
_PRED = []
for _ns in range(NSTATE):
    _b = _ns >> (MEM - 1)
    _PRED.append([(((_ns & 31) << 1) | _x, _outputs((_b << MEM) | ((_ns & 31) << 1) | _x))
                  for _x in (0, 1)])


def _check_bits(bits):
    out = []
    for b in bits:
        if isinstance(b, bool) or not isinstance(b, int) or b not in (0, 1):
            raise ValueError(f"bit must be int 0 or 1, got {b!r}")
        out.append(b)
    return out


def conv_encode(bits, terminate=True):
    """Encode info bits to a flat list of coded bits (g0, g1 per input bit).
    If terminate, 6 zero tail bits are appended so the trellis ends in state 0."""
    data = _check_bits(bits)
    if terminate:
        data = data + [0] * MEM
    state, out = 0, []
    for b in data:
        reg = (b << MEM) | state
        out.extend(_outputs(reg))
        state = reg >> 1
    return out


def _check_llrs(llrs):
    vals = list(llrs)
    if not vals or len(vals) % 2:
        raise ValueError("LLR sequence must be non-empty with even length")
    for v in vals:
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError(f"LLR must be a real number, got {v!r}")
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError(f"LLR must be finite, got {v!r}")
    return vals


def _check_quant(quant_bits, scale):
    if isinstance(quant_bits, bool) or not isinstance(quant_bits, int) or not 2 <= quant_bits <= 32:
        raise ValueError(f"quant_bits must be int in [2, 32], got {quant_bits!r}")
    if isinstance(scale, bool) or not isinstance(scale, (int, float)) \
            or not math.isfinite(scale) or scale <= 0:
        raise ValueError(f"scale must be finite and > 0, got {scale!r}")


def _quantize(v, quant_bits, scale):
    """Signed quantizer: round(v * scale) with ties-to-even, clipped to the signed range."""
    lo, hi = -(1 << (quant_bits - 1)), (1 << (quant_bits - 1)) - 1
    q = round(Fraction(v) * Fraction(scale))   # Fraction is exact; round() is half-even
    return min(max(q, lo), hi)


def viterbi_decode(llrs, terminated=True, quant_bits=None, scale=8):
    """Soft-decision Viterbi decoding of rate-1/2 K=7 code.
    quant_bits=None: float metrics. quant_bits=int: quantize LLR*scale to signed
    quant_bits (nearest, ties-to-even, clipped) and use integer metrics."""
    vals = _check_llrs(llrs)
    stages = len(vals) // 2
    if terminated and stages < MEM:
        raise ValueError(f"terminated decode needs >= {MEM} stages, got {stages}")
    fixed = quant_bits is not None
    if fixed:
        _check_quant(quant_bits, scale)
        vals = [_quantize(v, quant_bits, scale) for v in vals]
    else:
        vals = [float(v) for v in vals]
    zero = 0 if fixed else 0.0
    metric = [None] * NSTATE
    metric[0] = zero                 # encoder starts in state 0
    survivors, trace, norm_sum = [], [], zero
    for t in range(stages):
        l0, l1 = vals[2 * t], vals[2 * t + 1]
        new, surv = [None] * NSTATE, [0] * NSTATE
        for ns in range(NSTATE):
            best, best_s = None, 0
            for s, (o0, o1) in _PRED[ns]:      # ascending prev state: smaller wins ties
                if metric[s] is None:
                    continue
                c = metric[s] + o0 * l0 + o1 * l1
                if best is None or c < best:
                    best, best_s = c, s
            new[ns], surv[ns] = best, best_s
        reached = [m for m in new if m is not None]
        mn, mx = min(reached), max(reached)
        metric = [None if m is None else m - mn for m in new]   # normalize stage
        norm_sum += mn
        trace.append(StageTrace(t, mn, mx, mn))
        survivors.append(surv)
    if terminated:
        fs = 0
    else:
        fs = min((m, s) for s, m in enumerate(metric) if m is not None)[1]
    path, s = [0] * stages, fs
    for t in reversed(range(stages)):
        path[t] = s >> (MEM - 1)       # input bit is MSB of the state after that stage
        s = survivors[t][s]
    bits = path[:stages - MEM] if terminated else path
    return DecodeResult(bits=bits, metric_trace=trace, final_state=fs,
                        final_metric=metric[fs], normalization_sum=norm_sum,
                        quant_bits=quant_bits)
