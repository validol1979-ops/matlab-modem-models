"""Exact unsigned history-energy range for full signed18 complex samples."""
from numbers import Integral


def layout(log2n):
    if isinstance(log2n,bool) or not isinstance(log2n,Integral) or not 0<=log2n<=27:
        raise ValueError('Expected integer LOG2N in 0..27')
    power_max=(1<<log2n)*(1<<35);total_max=power_max+(1<<34)-1
    return dict(capacity=1<<log2n,power_max=power_max,total_max=total_max,
                selected_width=total_max.bit_length(),control_width=max(39,total_max.bit_length()+1),
                old_width=39,old_width_safe=total_max<(1<<39))


def history_trace(samples,taps,eps):
    """Re-sum the live history on every sample; independent of the RTL recurrence."""
    if taps<1 or not 512<=eps<(1<<34):
        raise ValueError('NLMS trace needs positive taps and unsigned34 EPS >= 512')
    history=[(0,0)]*taps;rows=[]
    for sample in samples:
        history=[sample]+history[:-1]
        power=sum(int(re)*int(re)+int(im)*int(im) for re,im in history)
        total=power+eps;bits=total.bit_length();top=total>>(bits-10)
        reciprocal=((1<<19)+top//2)//top
        rows.append((power,total,bits,top-512,reciprocal))
    return rows
