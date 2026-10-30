"""Integer LMS / NLMS adaptive filter (reference of rtl/common/lms_filter.sv; research_core
lms and nlms, algorithms/adaptive/lms_nlms_rls).

Per sample: history h = [x_k, x_{k-1}, ..., x_{k-N+1}] (Q15), pred = vdot(w, h), e = d - pred,
w += mu h conj(e) (LMS: mu = step; NLMS: mu = step/(eps + |h|^2)). Here
- w is Q30 (34 bit, saturated), pred = sat18(rnd(sum conj(w) h, 30)), e = sat18(d - pred) (Q15);
- MU = round(step*2^17) (18 bit unsigned, step <= 1);
- LMS: c = rnd(MU*conj(e), 12) (Q20);
- NLMS: P = EPS + |h|^2 (Q30, EPS = round(eps*2^30) >= 2^9, |h|^2 exact), s = bit length of P,
  m = the top 10 bits of P (512..1023), r = round(2^19/m) (ROM), c = rnd((MU*r)*conj(e), s - 9) (Q20);
- w += rnd(h*c, 5) for every tap (the update of sample k is used from sample k+1, as the model).
Outputs: (pred, e) per sample, then the N weights as sat18(rnd(w, 15)) (Q15).
round is half up, (v + 2^(s-1)) >> s."""
import fft_fixed as f

RECIPROCAL=tuple(round((1<<19)/m) for m in range(512,1024))
LIMIT18=(1<<17)-1
LIMIT34=(1<<33)-1


def sat(value,limit):return max(-limit-1,min(limit,value))


def parameters(step,eps):
    mu=int(round(step*(1<<17)));e=int(round(eps*(1<<30)))
    if not 0<mu<=(1<<17) or e<(1<<9) or e>=(1<<34):raise ValueError('LMS needs 0 < step <= 1 and 2^-21 <= eps < 16')
    return mu,e


def adapt(x,d,taps,mode,params,stats=None):
    if mode not in ('lms','nlms') or taps<1 or len(x)!=len(d):raise ValueError('Invalid adaptive filter call')
    mu,eps=params;w=[(0,0)]*taps;h=[(0,0)]*taps;out=[]
    # NumPy-целые переполняются до сужения; считаем в Python int.
    x=[(int(r),int(i)) for r,i in x];d=[(int(r),int(i)) for r,i in d]
    def clamp(stage,value,limit):
        return sat(value,limit) if stats is None else stats.record(stage,value,limit)
    for z,target in zip(x,d):
        h=[z]+h[:-1]
        re=sum(wr*hr+wi*hi for (wr,wi),(hr,hi) in zip(w,h));im=sum(wr*hi-wi*hr for (wr,wi),(hr,hi) in zip(w,h))
        pred=(clamp('pred.re',f.rnd(re,30),LIMIT18),clamp('pred.im',f.rnd(im,30),LIMIT18))
        e=(clamp('error.re',target[0]-pred[0],LIMIT18),clamp('error.im',target[1]-pred[1],LIMIT18))
        if mode=='lms':c=(f.rnd(mu*e[0],12),f.rnd(-mu*e[1],12))
        else:
            p=eps+sum(hr*hr+hi*hi for hr,hi in h);s=p.bit_length();r=RECIPROCAL[(p>>(s-10))-512];k=mu*r
            c=(f.rnd(k*e[0],s-9),f.rnd(-k*e[1],s-9))
        # w += h * c (c = mu conj(e))
        w=[(clamp('update.re',wr+f.rnd(hr*c[0]-hi*c[1],5),LIMIT34),clamp('update.im',wi+f.rnd(hr*c[1]+hi*c[0],5),LIMIT34)) for (wr,wi),(hr,hi) in zip(w,h)]
        out.append((pred,e))
    weights=[(clamp('dump.re',f.rnd(wr,15),LIMIT18),clamp('dump.im',f.rnd(wi,15),LIMIT18)) for wr,wi in w]
    return out,weights
