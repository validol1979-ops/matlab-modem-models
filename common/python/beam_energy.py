"""Exact coefficient energy bounds for a full signed18 complex beamformer."""
from numbers import Integral


def layout(log2m):
    if isinstance(log2m,bool) or not isinstance(log2m,Integral) or not 0<=log2m<=27:
        raise ValueError('Expected integer LOG2M in 0..27')
    maximum=(1<<log2m)*(1<<35)
    return dict(capacity=1<<log2m,energy_max=maximum,selected_width=maximum.bit_length(),
                control_width=max(40,maximum.bit_length()+1),old_width=40,old_width_safe=maximum<(1<<40))


def exact_reciprocal(energy):
    if isinstance(energy,bool) or not isinstance(energy,Integral) or energy<=0:
        raise ValueError('Expected positive integer energy')
    shift=7+int(energy).bit_length();numerator=1<<(shift+15)
    quotient,remainder=divmod(numerator,int(energy))
    if 2*remainder>energy or (2*remainder==energy and quotient%2):quotient+=1
    return quotient,shift
