"""Integer 2x2 MMSE / zero-forcing solver (reference of rtl/common/mmse2.sv; research_core mimo,
algorithms/mimo/dsplog): y = (H^H H + lambda I)^-1 H^H obs for every observation pair.

H is exactly 2x2 complex integer pairs in signed 18-bit Q15; observations use
the same signed 18-bit pair format. Lambda is a finite nonnegative real scalar;
LAMBDA = round(lambda*2^30) (nearest-even Q30) must fit the unsigned 34-bit port.
Out-of-format inputs are rejected instead of wrapping or clipping.
Once per configuration, exactly:
  G = H^H H + LAMBDA I (Q30: a, d real, b = G01 complex), det = a d - |b|^2 (Q60, > 0),
  M = adj(G) H^H with adj(G) = [[d, -b], [-conj b, a]] (Q45),
  Z = 22 + bit length of det, R = divide(2^Z, det) (nearest-even; beam_fixed.reciprocal),
  W = rnd(M*R, Z - 39) per real component (Q24).
Per pair: y_i = sat18(rnd(W_i0 o_0 + W_i1 o_1, 24)) (Q15).
For a positive shift round is half up, (v + 2^(s-1)) >> s. Zero shift keeps
the integer exactly; a negative shift multiplies by 2^(-s) without rounding."""
import math
from numbers import Integral, Real
import fft_fixed as f
from beam_fixed import reciprocal

LIMIT18=(1<<17)-1
WEIGHT_BITS=48


def sat18(v):return max(-LIMIT18-1,min(LIMIT18,v))
def cmul(a,b):return (a[0]*b[0]-a[1]*b[1],a[0]*b[1]+a[1]*b[0])
def conj(a):return (a[0],-a[1])
def cadd(a,b):return (a[0]+b[0],a[1]+b[1])


def round_shift(value,shift):
    """Weight scaling also needs exact zero/left shifts for small nonzero determinants."""
    if shift>0:return f.rnd(value,shift)
    return int(value) if shift==0 else int(value)<<-shift


def _pair(value,name):
    try:
        if len(value)!=2:raise ValueError(name+' must be a complex integer pair')
        components=[]
        for component in value:
            if not isinstance(component,Integral) or isinstance(component,bool):
                raise ValueError(name+' components must be integers')
            component=int(component)
            if not -131072<=component<=131071:
                raise ValueError(name+' outside signed 18-bit range')
            components.append(component)
        return tuple(components)
    except TypeError as exc:
        raise ValueError(name+' must be a complex integer pair') from exc


def _channel(H):
    try:
        if len(H)!=2 or any(len(row)!=2 for row in H):
            raise ValueError('H must be a 2x2 matrix of integer pairs')
        return [[_pair(value,f'H[{i},{j}]') for j,value in enumerate(row)] for i,row in enumerate(H)]
    except TypeError as exc:
        raise ValueError('H must be a 2x2 matrix of integer pairs') from exc


def lambda_raw(lam):
    if not isinstance(lam,Real) or isinstance(lam,bool) or lam<0:
        raise ValueError('lambda must be a finite nonnegative real scalar')
    try:value=float(lam)
    except (ValueError,OverflowError) as exc:
        raise ValueError('lambda must be a finite nonnegative real scalar') from exc
    if not math.isfinite(value) or value<0 or value>16:
        raise ValueError('lambda must be finite, nonnegative and fit unsigned 34-bit Q30')
    raw=int(round(lam*(1<<30)))
    if not 0<=raw<(1<<34):raise ValueError('Rounded lambda outside unsigned 34-bit Q30 range')
    return raw


def weights(H,lam):
    (h00,h01),(h10,h11)=_channel(H)
    L=lambda_raw(lam)
    a=h00[0]**2+h00[1]**2+h10[0]**2+h10[1]**2+L
    d=h01[0]**2+h01[1]**2+h11[0]**2+h11[1]**2+L
    b=cadd(cmul(conj(h00),h01),cmul(conj(h10),h11))
    det=a*d-(b[0]**2+b[1]**2)
    if det<=0:raise ValueError('Singular normal matrix')
    r,z=reciprocal(det)
    adj=[[(d,0),(-b[0],-b[1])],[(-b[0],b[1]),(a,0)]]
    hh=[[conj(h00),conj(h10)],[conj(h01),conj(h11)]]
    W=[]
    for i in range(2):
        row=[]
        for j in range(2):
            m=cadd(cmul(adj[i][0],hh[0][j]),cmul(adj[i][1],hh[1][j]))
            coefficient=(round_shift(m[0]*r,z-39),round_shift(m[1]*r,z-39))
            if any(value<-(1<<(WEIGHT_BITS-1)) or value>=(1<<(WEIGHT_BITS-1)) for value in coefficient):
                raise ValueError('MMSE coefficient exceeds signed 48-bit Q24 range')
            row.append(coefficient)
        W.append(row)
    return W


def solve(x,H,lam,stats=None):
    try:
        if len(x)%2:raise ValueError('MMSE needs whole observation pairs')
        x=[_pair(value,f'observation[{i}]') for i,value in enumerate(x)]
    except TypeError as exc:
        raise ValueError('MMSE needs a sequence of observation pairs') from exc
    W=weights(H,lam);out=[]
    for k in range(0,len(x),2):
        o=x[k:k+2]
        for i in range(2):
            s=cadd(cmul(W[i][0],o[0]),cmul(W[i][1],o[1]))
            re,im=f.rnd(s[0],24),f.rnd(s[1],24)
            out.append((sat18(re),sat18(im)) if stats is None else
                       (stats.record(f'output.y{i}.re',re,LIMIT18),
                        stats.record(f'output.y{i}.im',im,LIMIT18)))
    return out
