"""Full signed-state RLS dot-product bounds, distinct from adaptive-state reachability."""
from itertools import product
from numbers import Integral


def component_bounds(state_width,log2n):
    if state_width not in (34,44,48):raise ValueError('Expected signed34/44/48 state')
    if isinstance(log2n,bool) or not isinstance(log2n,Integral) or not 0<=log2n<=10:
        raise ValueError('Expected integer LOG2N in 0..10')
    a=(-(1<<(state_width-1)),(1<<(state_width-1))-1);h=(-131072,131071)
    rows=[(x*z+y*t,x*t-y*z) for x,y,z,t in product(a,a,h,h)]
    n=1<<log2n;shift=30 if state_width==34 else 15
    return dict(real_min=n*min(r[0] for r in rows),real_max=n*max(r[0] for r in rows),
                imag_min=n*min(r[1] for r in rows),imag_max=n*max(r[1] for r in rows),
                width=state_width+19+log2n,rounding_add=1<<(shift-1))


def layout(log2n):
    rows={name:component_bounds(w,log2n) for name,w in (('prediction',34),('matrix',44),('quadratic',48))}
    return dict(log2n=log2n,capacity=1<<log2n,pred_width=rows['prediction']['width'],dot_width=rows['matrix']['width'],
                q_width=rows['quadratic']['width'],old_widths=[64,128,128],bounds=rows,
                denominator_min=-(1<<49)+1,denominator_max=(1<<49)+(1<<30)-2,denominator_width=51)
