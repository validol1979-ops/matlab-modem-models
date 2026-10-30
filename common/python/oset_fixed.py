"""Integer notch and scalar Kalman filters (references of rtl/common/notch_iir.sv, kalman_scalar.sv).

research_core notch: y[k] = x[k] - 2c x[k-1] + x[k-2] + 2rc y[k-1] - r^2 y[k-2],
c = cos(2 pi f0). The coefficients are designed here (notch_coefficients) and loaded:
B1 = round(-2c*2^16), A1 = round(2rc*2^16), A2 = round(-r^2*2^16), 18-bit Q16 (B1 = -2 is
-131072, the 18-bit minimum). The state keeps G = 5 guard bits (Q20, 25 bit, saturated):
  X = x << 5, s = X[k] + rnd(B1*X[k-1], 16) + X[k-2] + rnd(A2*Y[k-2], 16),
  Y[k] = sat25(s + rnd(A1*Y[k-1], 16)), out = sat18(rnd(Y[k], 5)).
research_core kalman: P += Qn; K = P/(P+R); v += K*(x - v); P *= (1 - K) (P and the gains
do not depend on the data). Here P is Q24 (32 bit unsigned; Qn, R, P0 = round(.*2^24)),
K = divide(P*2^17, P + R) (nearest-even, as fxp_divide_seq) in Q17, P = rnd(P*(2^17 - K), 17);
the value keeps 8 guard bits: V += rnd(K*((x << 8) - V), 17), out = sat18(rnd(V, 8)).
round is half up, (v + 2^(s-1)) >> s."""
import math
import fft_fixed as f
from bpsk_fixed import divide

LIMIT18=(1<<17)-1
LIMIT25=(1<<24)-1


def sat(value,limit):return max(-limit-1,min(limit,value))


def notch_coefficients(f0,r):
    if not (0<=f0<=.5 and 0<=r<1):raise ValueError('notch needs 0 <= f0 <= 0.5 and 0 <= r < 1')
    c=math.cos(2*math.pi*f0)
    q=lambda v:max(-(1<<17),min((1<<17)-1,int(round(v*(1<<16)))))
    return q(-2*c),q(2*r*c),q(-r*r)


def notch(x,coefficients,stats=None):
    """Notch stream; `stats` (optional sat_diag.SatStats/SatTrace) counts the pre-clamp
    values at the two actual clamp edges: the 25 bit state (stages notch.state.re/im,
    asymmetric rails -2^24/+2^24-1) and the 18 bit output (notch.output.re/im,
    -2^17/+2^17-1). With stats=None the numerical result is the plain model."""
    b1,a1,a2=coefficients;out=[]
    X=[(0,0),(0,0)];Y=[(0,0),(0,0)]   # [k-1, k-2]
    for re,im in x:
        cur=(re<<5,im<<5);new=[]
        for axis in (0,1):
            s=cur[axis]+f.rnd(b1*X[0][axis],16)+X[1][axis]+f.rnd(a2*Y[1][axis],16)
            raw=s+f.rnd(a1*Y[0][axis],16)
            if stats is None:new.append(sat(raw,LIMIT25))
            else:new.append(stats.record('notch.state.%s'%('re','im')[axis],raw,LIMIT25,'asym'))
        X=[cur,X[0]];Y=[tuple(new),Y[0]]
        row=[]
        for axis in (0,1):
            v=f.rnd(new[axis],5)
            if stats is None:row.append(sat(v,LIMIT18))
            else:row.append(stats.record('notch.output.%s'%('re','im')[axis],v,LIMIT18,'asym'))
        out.append(tuple(row))
    return out


def kalman_parameters(q,r,p0):
    if not (q>=0 and r>0 and p0>=0):raise ValueError('kalman needs Q >= 0, R > 0, P0 >= 0')
    v=[int(round(t*(1<<24))) for t in (q,r,p0)]
    if v[1]==0 or any(t>=1<<31 for t in v):raise ValueError('kalman parameters out of range')
    return tuple(v)


def kalman_gains(parameters,count):
    q,r,p=parameters;gains=[]
    for _ in range(count):
        p+=q;k=divide(p<<17,p+r);p=f.rnd(p*((1<<17)-k),17);gains.append(k)
        assert p<(1<<32)
    return gains


def kalman(x,parameters,stats=None):
    """Kalman stream; `stats` (optional) counts the pre-clamp rnd(V,8) values at the
    18 bit output clamp edge (stages kalman.output.re/im, rails -2^17/+2^17-1).
    With stats=None the numerical result is the plain model."""
    gains=kalman_gains(parameters,len(x));v=[0,0];out=[]
    for (re,im),k in zip(x,gains):
        for axis,s in enumerate((re,im)):v[axis]+=f.rnd(k*((s<<8)-v[axis]),17)
        row=[]
        for axis in (0,1):
            val=f.rnd(v[axis],8)
            if stats is None:row.append(sat(val,LIMIT18))
            else:row.append(stats.record('kalman.output.%s'%('re','im')[axis],val,LIMIT18,'asym'))
        out.append(tuple(row))
    return out
