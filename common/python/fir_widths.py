"""Exact accumulator intervals and minimum FIR tree widths for signed18 operands.

Every tap sees independent real/imaginary samples, so summing per-tap corner extrema
is tight at a complete overlap. Zero lies inside every interval: all frame edges,
lane groups and intermediate accumulation steps are bounded as well.
"""
from itertools import product
from numbers import Integral

INPUT_LOW = -(1 << 17)
INPUT_HIGH = (1 << 17)-1
ROUND_BIAS = 1 << 16


def bounds(taps):
    if not taps:
        raise ValueError('At least one tap is required')
    low = [0, 0]; high = [0, 0]
    for tap in taps:
        if len(tap) != 2 or any(isinstance(v, bool) or not isinstance(v, Integral)
                               or not INPUT_LOW <= v <= INPUT_HIGH for v in tap):
            raise ValueError('Signed18 integer tap pairs are required')
        hr, hi = map(int, tap)
        corners = [(hr*xr-hi*xi, hr*xi+hi*xr)
                   for xr, xi in product((INPUT_LOW, INPUT_HIGH), repeat=2)]
        for axis in range(2):
            low[axis] += min(row[axis] for row in corners)
            high[axis] += max(row[axis] for row in corners)
    return dict(re=[low[0], high[0]], im=[low[1], high[1]])


def fits(intervals, width):
    if isinstance(width, bool) or not isinstance(width, Integral) or not 18 <= width <= 63:
        raise ValueError('Accumulator width must be an integer in 18..63')
    low, high = -(1 << (width-1)), (1 << (width-1))-1
    return all(low <= bottom and top+ROUND_BIAS <= high for bottom, top in intervals.values())


def select(taps):
    intervals = bounds(taps)
    return next(width for width in range(18, 64) if fits(intervals, width))


def tree_layout(log2lanes):
    """Tight full-input/full-coefficient widths; counts only nodes actually used.
    Products are signed36. Re = rr-ii is signed(36+level), Im = ri+ir needs one
    extra bit at every level because MIN*MIN is positive and exactly a power of two.
    These bounds do not depend on a particular configured tap set.
    """
    if isinstance(log2lanes,bool) or not isinstance(log2lanes,Integral) or not 0<=log2lanes<=7:
        raise ValueError('Tree study supports log2lanes in 0..7')
    levels=[dict(level=v,nodes=1<<(log2lanes-v),real_width=36+v,imag_width=37+v)
            for v in range(log2lanes+1)]
    uniform_bits=2*(37+log2lanes)*sum(row['nodes'] for row in levels)
    compact_bits=sum((row['real_width']+row['imag_width'])*row['nodes'] for row in levels)
    return dict(product_width=36,levels=levels,uniform_bits=uniform_bits,compact_bits=compact_bits,
                saved_bits=uniform_bits-compact_bits)
