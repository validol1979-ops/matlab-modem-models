"""Exact LMS/NLMS estimate and update intermediate ranges from the configuration contract.

Operands are taken over their full stored codes (signed18 history/desired, sat34 weights,
sat18 prediction/error) or over the ranges forced by the configuration guard and the fixed
reciprocal table: 1 <= MU <= 2^17, 513 <= r <= 1024, k = MU (LMS) or MU*r (NLMS) <= 2^27,
shift = 12 (LMS) or s - 9 with 10 <= s <= bit length of N*2^35 + 2^34 - 1 (NLMS).
The bounds treat operands as independent intervals; reset reachability is not claimed."""
from itertools import product
from numbers import Integral

S18=(-(1<<17),(1<<17)-1)
S34=(-(1<<33),(1<<33)-1)
RECIPROCAL=tuple(((1<<19)+m//2)//m for m in range(512,1024))
MU_MAX=1<<17
OLD=dict(pred_width=64,error_width=64,step_width=64,coeff_width=47,delta_width=65,weight_width=64,dump_width=64)
NAMES=tuple(OLD)


def signed_width(low,high):
    width=1
    while low<-(1<<(width-1)) or high>=(1<<(width-1)):width+=1
    return width


def rnd_range(low,high,shift):
    add=1<<(shift-1);return (low+add)>>shift,(high+add)>>shift


def complex_product(a,b):
    """Exact ranges of (ar*br + ai*bi, ar*bi - ai*br) (conj(a) b) and of
    (ar*br - ai*bi, ar*bi + ai*br) (a b) for independent interval components."""
    rows={}
    for name,f in (('conj_re',lambda ar,ai,br,bi:ar*br+ai*bi),('conj_im',lambda ar,ai,br,bi:ar*bi-ai*br),
                   ('mul_re',lambda ar,ai,br,bi:ar*br-ai*bi),('mul_im',lambda ar,ai,br,bi:ar*bi+ai*br)):
        values=[f(*v) for v in product(a,a,b,b)];rows[name]=(min(values),max(values))
    return rows


def layout(log2n):
    if isinstance(log2n,bool) or not isinstance(log2n,Integral) or not 0<=log2n<=27:
        raise ValueError('Expected integer LOG2N in 0..27')
    n=1<<log2n
    # Prediction: conj(w) h per tap (53-bit registers), N-lane tree, round 30, sat18.
    tap=complex_product(S34,S18)
    product_low=min(tap['conj_re'][0],tap['conj_im'][0]);product_high=max(tap['conj_re'][1],tap['conj_im'][1])
    sum_low=n*product_low;sum_high=n*product_high
    pred_raw=(sum_low+(1<<29),sum_high+(1<<29))
    pred_round=rnd_range(sum_low,sum_high,30)
    # Error: d - sat18(pred).
    error=(S18[0]-S18[1],S18[1]-S18[0])
    # Step: k*e (re) and -k*e (im), variable round half up; the add is part of the expression.
    k_nlms=MU_MAX*max(RECIPROCAL);s_max=(n*(1<<35)+(1<<34)-1).bit_length()
    shifts=sorted({12}|set(range(1,s_max-9+1)))
    step_low=-k_nlms*(1<<17);step_high=k_nlms*(1<<17)       # im: -k*(-2^17); re: k*(-2^17)
    step_raw=(step_low+1,step_high+(1<<(max(shifts)-1)))     # +2^(shift-1), shift >= 1
    coeff=[rnd_range(step_low,step_high,s) for s in shifts]
    coeff_low=min(c[0] for c in coeff);coeff_high=max(c[1] for c in coeff)
    # Tap update: h c with c in [coeff_low, coeff_high], then round 5 and add the weight.
    c=(coeff_low,coeff_high);dl=complex_product(S18,c)
    delta_low=min(dl['mul_re'][0],dl['mul_im'][0]);delta_high=max(dl['mul_re'][1],dl['mul_im'][1])
    delta_raw=(delta_low+16,delta_high+16)
    delta_round=rnd_range(delta_low,delta_high,5)
    weight=(S34[0]+delta_round[0],S34[1]+delta_round[1])
    dump_raw=(S34[0]+(1<<14),S34[1]+(1<<14));dump_round=rnd_range(*S34,15)
    bounds=dict(log2n=log2n,capacity=n,product=(product_low,product_high),product_width=signed_width(product_low,product_high),
        sum=(sum_low,sum_high),sum_width=signed_width(sum_low,sum_high),pred_raw=pred_raw,pred_round=pred_round,
        error=error,k_max=k_nlms,lms_k_max=MU_MAX,reciprocal=(min(RECIPROCAL),max(RECIPROCAL)),
        shift_min=min(shifts),shift_max=max(shifts),step=(step_low,step_high),step_raw=step_raw,coeff=c,
        delta=(delta_low,delta_high),delta_raw=delta_raw,delta_round=delta_round,weight=weight,
        dump_raw=dump_raw,dump_round=dump_round)
    widths=dict(pred_width=signed_width(*pred_raw),error_width=signed_width(*error),
        step_width=signed_width(*step_raw),coeff_width=signed_width(*c),
        delta_width=signed_width(*delta_raw),weight_width=signed_width(*weight),dump_width=signed_width(*dump_raw))
    return dict(bounds={k:list(v) if isinstance(v,tuple) else v for k,v in bounds.items()},selected=widths,old=dict(OLD),
                old_safe={k:OLD[k]>=widths[k] for k in NAMES})


STAGES=('product','sum','pred','error','step','coeff','delta','weight','dump')


def _sat(value,bits):return max(-(1<<(bits-1)),min((1<<(bits-1))-1,value))


def trace(x,d,taps,mode,mu,eps):
    """Replay one transaction with every sized intermediate; returns (outputs, weights, peaks)
    with the same magnitudes the RTL operand monitor reports. Independent of lms_fixed.adapt,
    against which the outputs and weights are compared by the caller."""
    if mode not in ('lms','nlms') or taps<1 or len(x)!=len(d):raise ValueError('Invalid LMS trace')
    w=[(0,0)]*taps;h=[(0,0)]*taps;peaks=[0]*len(STAGES);out=[]
    def track(stage,*values):peaks[stage]=max(peaks[stage],*(abs(v) for v in values))
    for z,target in zip(x,d):
        h=[z]+h[:-1]
        products=[(wr*hr+wi*hi,wr*hi-wi*hr) for (wr,wi),(hr,hi) in zip(w,h)]
        for p in products:track(0,*p)
        total=(sum(p[0] for p in products),sum(p[1] for p in products));track(1,*total)
        raw=(total[0]+(1<<29),total[1]+(1<<29));track(2,*raw)
        pred=(_sat(raw[0]>>30,18),_sat(raw[1]>>30,18))
        difference=(target[0]-pred[0],target[1]-pred[1]);track(3,*difference)
        e=(_sat(difference[0],18),_sat(difference[1],18))
        if mode=='lms':k=mu;shift=12
        else:
            p=eps+sum(hr*hr+hi*hi for hr,hi in h);bits=p.bit_length();m=p>>(bits-10)
            k=mu*(((1<<19)+m//2)//m);shift=bits-9
        step=(k*e[0],-k*e[1]);add=1<<(shift-1);track(4,*step,step[0]+add,step[1]+add)
        c=((step[0]+add)>>shift,(step[1]+add)>>shift);track(5,*c)
        nxt=[]
        for (wr,wi),(hr,hi) in zip(w,h):
            dl=(hr*c[0]-hi*c[1],hr*c[1]+hi*c[0]);track(6,dl[0]+16,dl[1]+16)
            sums=(wr+((dl[0]+16)>>5),wi+((dl[1]+16)>>5));track(7,*sums)
            nxt.append((_sat(sums[0],34),_sat(sums[1],34)))
        w=nxt;out.append((pred,e))
    weights=[]
    for wr,wi in w:
        track(8,wr+(1<<14),wi+(1<<14));weights.append((_sat((wr+(1<<14))>>15,18),_sat((wi+(1<<14))>>15,18)))
    return out,weights,peaks
