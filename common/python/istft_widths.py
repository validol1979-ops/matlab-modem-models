"""Exact ISTFT interval using the symmetric FFT rail and signed18 window box."""
from numbers import Integral


def layout(log2n,log2hop):
    if any(isinstance(v,bool) or not isinstance(v,Integral) for v in (log2n,log2hop)):
        raise ValueError('Integer geometry required')
    if not 2<=log2n<=8 or not 0<=log2hop<=log2n or not 0<=log2n-log2hop<=2:
        raise ValueError('Expected N in 4..256, overlap in 1,2,4')
    ratio=1<<(log2n-log2hop);peak=((1<<23)-1)*(1<<17);width=41+log2n-log2hop
    return dict(overlap=ratio,fft_limit=(1<<23)-1,product_width=41,
                product_bounds=[-peak,peak],accumulator_width=width,
                accumulator_bounds=[-ratio*peak,ratio*peak],
                ram_bits=2*(1<<log2n)*width,legacy_ram_bits=88*(1<<log2n),
                saved_ram_bits=2*(1<<log2n)*(44-width))
