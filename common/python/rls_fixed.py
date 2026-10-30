"""Integer RLS adaptive filter (reference of rtl/common/rls_filter.sv; research_core rls,
algorithms/adaptive/lms_nlms_rls).

research_core: P = I/eps; per sample h = [x_k .. x_{k-N+1}], pred = vdot(w, h), e = d - pred,
g = P h / (lam + h^H P h), w += g conj(e), P = (P - g (h^H P))/lam. Here, with N taps:
- w Q30 (34 bit, saturated), pred/e as lms_fixed (Q15);
- P Q28 complex (44 bit, saturated), P0 = round(2^28/eps) on the diagonal;
- u = sat48(rnd(P h, 15)) (Q28), q = sat50(rnd(re(h^H u), 15)) (Q28), D = LAM + q with
  LAM = round(lam*2^28) (> 0);
- one normalised reciprocal per sample: Z = 22 + bit length of D, R = divide(2^Z, D) (beam_fixed);
  g = sat40(rnd(u*R, Z - 30)) (Q30);
- w += rnd(g*conj(e), 15); P = sat44(rnd((P - sat46(rnd(g conj(u)^T, 30)))*INVL, 30)) with
  INVL = round(2^30/lam) (since h^H P = (P h)^H = u^H for the Hermitian P), computed for i <= j
  only: P_ji = conj(P_ij) and the diagonal is real (keeps P Hermitian in fixed point).
Outputs: (pred, e) per sample, then the N weights sat18(rnd(w, 15)).
round is half up, (v + 2^(s-1)) >> s.

OPTIONAL CLAMP STATISTICS: adapt(..., stats=SatTrace()) records every real clamp input of the
recursion - the pre-clamp ROUNDED value at the place where the RTL clamps - under the stage names
'pred.re','pred.im','error.re','error.im' (ERROR), 'u.re','u.im' (U, one row per sample step),
'q' (Q), 'gain.re','gain.im' (GAIN, active taps only), 'update.re','update.im' (WEIGHT),
'pt.re','pt.im' (PT, the j >= i pairs the update really uses, both components, diagonal included),
'P.re' (PN, upper triangle including the diagonal, the mirror written once) / 'P.im' (PN, strictly
above the diagonal) and 'dump.re','dump.im' (DUMP, one per reported weight). record() returns the
model's own clamp value, so instrumented and plain runs are bit-identical; stats=None never touches
sat_diag. Per transaction of S samples and T taps the field counts are
pred/errors = S, u/gain/update = S*T, q = S, pt = P.re = S*T*(T+1)/2, P.im = S*T*(T-1)/2 and
dump = T (the RTL observes exactly these, rtl/tb/rls_saturation_check.svh).
"""
import fft_fixed as f
from beam_fixed import reciprocal

LIMIT18=(1<<17)-1
LIMIT34=(1<<33)-1
LIMIT44=(1<<43)-1
# Saturation bounds of the intermediate values (never reached by sane data; they give the
# hardware finite widths): u 48, q 50, g 40, g conj(u) 46 bits.
LIMIT48=(1<<47)-1
LIMIT50=(1<<49)-1
LIMIT40=(1<<39)-1
LIMIT46=(1<<45)-1


def sat(v,limit):return max(-limit-1,min(limit,v))


def parameters(lam,eps):
    if not (0<lam<=1 and eps>0):raise ValueError('RLS needs 0 < lambda <= 1 and eps > 0')
    p0=int(round((1<<28)/eps));l=int(round(lam*(1<<28)));invl=int(round((1<<30)/lam))
    if p0>LIMIT44:raise ValueError('eps too small')
    return p0,l,invl


def adapt(x,d,taps,params,stats=None):
    """One transaction of (x, d) pairs; stats=None keeps the plain path unchanged, a SatStats
    counts the actual clamp inputs of every stage listed in the module docstring."""
    if taps<1 or len(x)!=len(d):raise ValueError('Invalid RLS call')
    p0,lam,invl=params
    def clamp(stage,value,limit):
        return sat(value,limit) if stats is None else stats.record(stage,value,limit)
    P=[[(p0 if i==j else 0,0) for j in range(taps)] for i in range(taps)]
    w=[(0,0)]*taps;h=[(0,0)]*taps;out=[]
    for z,target in zip(x,d):
        h=[z]+h[:-1]
        re=sum(wr*hr+wi*hi for (wr,wi),(hr,hi) in zip(w,h));im=sum(wr*hi-wi*hr for (wr,wi),(hr,hi) in zip(w,h))
        pred=(clamp('pred.re',f.rnd(re,30),LIMIT18),clamp('pred.im',f.rnd(im,30),LIMIT18))
        e=(clamp('error.re',target[0]-pred[0],LIMIT18),clamp('error.im',target[1]-pred[1],LIMIT18))
        u=[(clamp('u.re',f.rnd(sum(P[i][j][0]*h[j][0]-P[i][j][1]*h[j][1] for j in range(taps)),15),LIMIT48),
            clamp('u.im',f.rnd(sum(P[i][j][0]*h[j][1]+P[i][j][1]*h[j][0] for j in range(taps)),15),LIMIT48)) for i in range(taps)]
        q=clamp('q',f.rnd(sum(h[i][0]*u[i][0]+h[i][1]*u[i][1] for i in range(taps)),15),LIMIT50)
        D=lam+q
        if D<=0:raise ValueError('RLS denominator lost positivity')
        r,z_=reciprocal(D)
        g=[(clamp('gain.re',f.rnd(ur*r,z_-30),LIMIT40),clamp('gain.im',f.rnd(ui*r,z_-30),LIMIT40)) for ur,ui in u]
        # w += g conj(e)
        w=[(clamp('update.re',wr+f.rnd(gr*e[0]+gi*e[1],15),LIMIT34),
            clamp('update.im',wi+f.rnd(gi*e[0]-gr*e[1],15),LIMIT34)) for (wr,wi),(gr,gi) in zip(w,g)]
        # P_ij -= g_i conj(u_j); P *= 1/lam. Only i <= j is computed; P_ji = conj(P_ij) and the
        # diagonal is real, which keeps the fixed-point P Hermitian (and positive definite).
        new=[[None]*taps for _ in range(taps)]
        for i in range(taps):
            for j in range(i,taps):
                tr=clamp('pt.re',f.rnd(g[i][0]*u[j][0]+g[i][1]*u[j][1],30),LIMIT46)
                ti=clamp('pt.im',f.rnd(g[i][1]*u[j][0]-g[i][0]*u[j][1],30),LIMIT46)
                pr=clamp('P.re',f.rnd((P[i][j][0]-tr)*invl,30),LIMIT44)
                pi=0 if i==j else clamp('P.im',f.rnd((P[i][j][1]-ti)*invl,30),LIMIT44)
                new[i][j]=(pr,pi);new[j][i]=(pr,-pi)
        P=new
        out.append((pred,e))
    weights=[(clamp('dump.re',f.rnd(wr,15),LIMIT18),clamp('dump.im',f.rnd(wi,15),LIMIT18)) for wr,wi in w]
    return out,weights
