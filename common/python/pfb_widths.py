"""Exact worst-case phase accumulator widths for real signed18 PFB taps."""
from numbers import Integral


def layout(log2m,log2tmax):
    for value in (log2m,log2tmax):
        if isinstance(value,bool) or not isinstance(value,Integral):
            raise ValueError('Integer geometry required')
    if not 2<=log2m<=8 or not 0<=log2tmax<=16:
        raise ValueError('Expected log2m in 2..8 and log2tmax in 0..16')
    terms=1<<max(log2tmax-log2m,0)
    low=terms*(-(1<<34)+(1<<17));high=terms*(1<<34)
    width=36+max(log2tmax-log2m,0);legacy=36+log2tmax
    return dict(terms_per_phase=terms,raw_bounds=[low,high],round_bias=4096,
                selected_width=width,legacy_width=legacy,
                accumulator_bits=2*(1<<log2m)*width,
                legacy_accumulator_bits=2*(1<<log2m)*legacy,
                saved_bits=2*(1<<log2m)*(legacy-width))
