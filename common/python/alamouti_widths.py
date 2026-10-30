"""Exact signed18 Alamouti bounds, independent of RTL expression widths."""
from itertools import product


def sums(h,x):
    h0r,h0i,h1r,h1i=h;ar,ai,br,bi=x
    return (h0r*ar+h0i*ai+h1r*br+h1i*bi,
            h0r*ai-h0i*ar+h1i*br-h1r*bi,
            h1r*ar+h1i*ai-h0r*br-h0i*bi,
            h1r*ai-h1i*ar-h0i*br+h0r*bi)


def layout():
    corners=[sums(v[:4],v[4:]) for v in product((-131072,131071),repeat=8)]
    bounds=[dict(min=min(v[k] for v in corners),max=max(v[k] for v in corners)) for k in range(4)]
    return dict(product_width=36,sum_width=38,energy_width=37,scale_width=61,
                old_sum_width=39,old_energy_width=40,old_scale_width=64,
                energy_max=1<<36,bounds=bounds,scaled_abs_bound=1<<59,
                rounding_add_max=1<<43,rounded_upper_bound=(1<<59)+(1<<43))
