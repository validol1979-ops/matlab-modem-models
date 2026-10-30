"""Exact configuration-expression bounds and independent MMSE3 arithmetic.

The width proof quantifies over every independent signed code of stored G40,
A84 and H18, without assuming these matrices came from a channel. Each scalar
expression is multi-affine in its independent operands, so its extrema occur
at endpoint corners. Storage widths remain G40/A84/D128/M106.
"""
from mmse3_widths import _interval, _pairs, gram


def _expression(left_bits, right_bits, signs):
    """Exact intervals of products, signed terms and successive sum prefixes.

    A signed operand has rails [-a,a-1]. Its product with [-b,b-1] has
    minimum -ab+min(a,b), maximum ab. The independent product terms let us
    add interval endpoints exactly, including subtraction of the asymmetric
    product interval. Negating a cofactor is handled separately in layout().
    """
    a, b = 1 << (left_bits-1), 1 << (right_bits-1)
    lo, hi = -a*b+min(a, b), a*b
    low = high = 0
    signed_terms, prefixes = [], []
    for sign in signs:
        lower, upper = (lo, hi) if sign == 1 else (-hi, -lo)
        signed_terms.append(_interval(lower, upper))
        low += lower
        high += upper
        prefixes.append(_interval(low, high))
    return {**_interval(low, high), 'product': _interval(lo, hi),
            'signs': list(signs), 'signed_terms': signed_terms,
            'prefixes': prefixes}


def layout():
    """Return tight scalar bounds and safe/minimal expression widths.

    real/imag bounds describe the complete stored-operand domain, not the
    narrower reachable Gram/adjugate matrices of an actual MMSE setup.
    Prefix intervals also cover each two-product RHS of a += statement.
    """
    adj_re = _expression(40, 40, (1, -1, -1, 1))
    adj_im = _expression(40, 40, (1, 1, -1, -1))
    det_re = _expression(40, 84, (1, -1)*3)
    det_im = _expression(40, 84, (1, 1)*3)
    m_re = _expression(84, 18, (1, 1)*3)
    m_im = _expression(84, 18, (1, -1)*3)

    def combine(real, imag):
        return {**_interval(min(real['minimum'], imag['minimum']),
                            max(real['maximum'], imag['maximum'])),
                'real': real, 'imag': imag}

    result = {
        'ports': {'h_bits': 18, 'lambda_bits': 34},
        'stored': {'gram': 40, 'adj': 84, 'det': 128, 'm': 106},
        'adj': combine(adj_re, adj_im),
        'det': combine(det_re, det_im),
        'm': combine(m_re, m_im),
    }
    # Each cofactor component has two positive and two negative independent
    # products; its interval is symmetric. Therefore odd parity negation has
    # the same extrema and does not demand another signed bit.
    for axis in ('real', 'imag'):
        entry = result['adj'][axis]
        entry['odd_negated'] = _interval(-entry['maximum'], -entry['minimum'])
    return result


def adjugate(g):
    """adj(G), as nine row-major integer pairs; input is arbitrary stored G40."""
    g = _pairs(g, 9, 40, 'G')
    result = []
    for row in range(3):
        for col in range(3):
            ra, rb = [i for i in range(3) if i != col]
            ca, cb = [i for i in range(3) if i != row]
            x, y = g[3*ra+ca], g[3*rb+cb]
            z, t = g[3*ra+cb], g[3*rb+ca]
            real = x[0]*y[0]-x[1]*y[1]-z[0]*t[0]+z[1]*t[1]
            imag = x[0]*y[1]+x[1]*y[0]-z[0]*t[1]-z[1]*t[0]
            sign = -1 if (row+col) % 2 else 1
            result.append((sign*real, sign*imag))
    return result


def determinant(g, a):
    """G[0,:] dot adj(G)[:,0], allowing independent stored G40 and A84."""
    g, a = _pairs(g, 9, 40, 'G'), _pairs(a, 9, 84, 'A')
    real = imag = 0
    for k in range(3):
        gr, gi = g[k]
        ar, ai = a[3*k]
        real += gr*ar-gi*ai
        imag += gr*ai+gi*ar
    return real, imag


def mentry(a, h):
    """A H^H, as nine pairs, for arbitrary independent stored A84 and H18."""
    a, h = _pairs(a, 9, 84, 'A'), _pairs(h, 9, 18, 'H')
    result = []
    for row in range(3):
        for col in range(3):
            real = imag = 0
            for k in range(3):
                ar, ai = a[3*row+k]
                hr, hi = h[3*col+k]
                real += ar*hr+ai*hi
                imag += ai*hr-ar*hi
            result.append((real, imag))
    return result


def trace(h, lambda_raw):
    """Exact reachable G/adj/det/M from a flat H18 channel and raw Q30 lambda."""
    values = gram(h, lambda_raw)
    g = list(zip(values[::2], values[1::2]))
    a = adjugate(g)
    return {'gram': g, 'adj': a, 'det': determinant(g, a), 'm': mentry(a, h)}


def banks(values):
    """Six raw expression banks, each with name/count/min/max for RTL evidence."""
    result = []
    for kind in ('adj', 'det', 'm'):
        pairs = [values[kind]] if kind == 'det' else values[kind]
        for axis, suffix in enumerate(('re', 'im')):
            components = [pair[axis] for pair in pairs]
            result.append({'name': kind+'_'+suffix, 'count': len(components),
                           'min': min(components), 'max': max(components)})
    return result
