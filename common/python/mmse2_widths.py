"""Exact 2x2 MMSE (rtl/common/mmse2.sv) intermediate bounds, independent of RTL expression widths.

Inputs are full codes: H components signed18, LAMBDA unsigned34 (the cfg_lambda port; the Python
model accepts up to 2^34 - 1). Gram, determinant and output sums use plain interval arithmetic,
which also bounds every left-to-right partial sum (every term interval contains zero).
M = adj(G) H^H and its scaling use the exact identities, valid for the exact integer values:
  adj(G) H^H = conj(det H) adj(H) + LAMBDA H^H,   det G = |det H|^2 + LAMBDA tr(H^H H) + LAMBDA^2,
so |M_ij| <= (|det H| + LAMBDA) max|h| with |h|^2 <= 2^35 and |det H| <= 2^36. M is formed only by
additions, subtractions and multiplications, which are exact modulo 2^W; a final value within
signed W bits is therefore exact even if a partial sum would wrap.
"""
from math import isqrt
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent))
from beam_energy import exact_reciprocal

LO,HI=-(1<<17),(1<<17)-1
LAMBDA_MAX=(1<<34)-1
WEIGHT_BITS=48
OLD=dict(gram_width=39,det_width=76,m_width=58,scale_width=84,sum_width=68)
SELECTED=dict(gram_width=38,det_width=74,m_width=55,scale_width=78,sum_width=68)
# Reachable witnesses found by an exhaustive search over the {-2^17, 2^17-1, 0}^8 corners
# with LAMBDA in {0, 2^34-1}; tests recompute their raw values.
DET_WITNESS=(((LO,LO),(LO,HI),(LO,HI),(LO,LO)),LAMBDA_MAX)
SCALE_WITNESS=(((LO,LO),(LO,HI),(HI,HI),(HI,HI)),LAMBDA_MAX)


def signed_width(lo,hi):
    width=1
    while lo< -(1<<(width-1)) or hi>(1<<(width-1))-1:width+=1
    return width


def imul(a,b):
    values=[x*y for x in a for y in b];return (min(values),max(values))


def iadd(*terms):return (sum(t[0] for t in terms),sum(t[1] for t in terms))
def ineg(a):return (-a[1],-a[0])


def gram_intervals():
    h=(LO,HI);square=(0,LO*LO);cross=imul(h,h)                 # x*x >= 0
    diagonal=iadd(square,square,square,square,(0,LAMBDA_MAX))
    real=iadd(cross,cross,cross,cross)
    imag=iadd(cross,ineg(cross),cross,ineg(cross))
    return dict(a=diagonal,d=diagonal,b_re=real,b_im=imag)


def det_interval():
    g=gram_intervals();ad=imul(g['a'],g['d']);br=imul(g['b_re'],g['b_re']);bi=imul(g['b_im'],g['b_im'])
    br=(0,br[1]);bi=(0,bi[1])                               # squares are nonnegative
    return iadd(ad,ineg(br),ineg(bi))


def m_interval():
    """Plain interval bound of the RTL M expressions (sound, not used for the selected width)."""
    g=gram_intervals();h=(LO,HI);bounds=[]
    diag=g['a'];nbr=ineg(g['b_re']);bi=g['b_im'];nbi=ineg(bi)
    # rows 0/1: p=(d,0), q=(-b_re,-b_im); rows 2/3: p=(-b_re,b_im), q=(a,0)
    for p_r,p_i,q_r,q_i in ((diag,(0,0),nbr,nbi),(nbr,bi,diag,(0,0))):
        bounds.append(iadd(imul(p_r,h),imul(p_i,h),imul(q_r,h),imul(q_i,h)))
        bounds.append(iadd(imul(p_i,h),ineg(imul(p_r,h)),imul(q_i,h),ineg(imul(q_r,h))))
    return (min(b[0] for b in bounds),max(b[1] for b in bounds))


def m_bound():
    """max |Re/Im M_ij| <= (2^36 + LAMBDA_MAX) * sqrt(2^35), as an integer."""
    return isqrt(((1<<36)+LAMBDA_MAX)**2<<35)


def small_det_bound(bits):
    """|M component| for 0 < det < 2^bits: |det H| <= sqrt(det), LAMBDA |h| <= LAMBDA tr <= det."""
    det=(1<<bits)-1;return isqrt(det<<35)+det


def scale_bounds():
    det_max=det_interval()[1];amount_max=det_max.bit_length()-17
    positive=(-m_bound()<<23,(m_bound()<<23)+(1<<(amount_max-1)))
    # Negative shift amount = bit_length(det) - 17 < 0 only for det < 2^16.
    left=max(small_det_bound(b)*(1<<23)<<(17-b) for b in range(1,17))
    return dict(amount_max=amount_max,rounding_add_max=1<<(amount_max-1),positive=positive,left_shift_abs=left)


def sum_intervals():
    w=(-(1<<(WEIGHT_BITS-1)),(1<<(WEIGHT_BITS-1))-1);o=(LO,HI);p=imul(w,o)
    real=iadd(p,ineg(p),p,ineg(p));imag=iadd(p,p,p,p)
    rounded=lambda i:(i[0]+(1<<23),i[1]+(1<<23))
    return dict(re=real,im=imag,re_rounding=rounded(real),im_rounding=rounded(imag))


def trace(h,lam):
    """Exact raw values of every sized mmse2 intermediate for H (row-major pairs) and LAMBDA."""
    (a0,a1),(b0,b1),(c0,c1),(d0,d1)=h
    ga=a0*a0+a1*a1+c0*c0+c1*c1+lam;gd=b0*b0+b1*b1+d0*d0+d1*d1+lam
    gbr=a0*b0+a1*b1+c0*d0+c1*d1;gbi=a0*b1-a1*b0+c0*d1-c1*d0
    det=ga*gd-gbr*gbr-gbi*gbi
    result=dict(gram=[ga,gd,gbr,gbi],det=det,m=None,reciprocal=None,z=None,scaled=None,weights=None,overflow=None)
    if det<=0:return result
    rows=(((gd,0),(-gbr,-gbi)),((gd,0),(-gbr,-gbi)),((-gbr,gbi),(ga,0)),((-gbr,gbi),(ga,0)))
    cols=((h[0],h[1]),(h[2],h[3]),(h[0],h[1]),(h[2],h[3]))
    m=[]
    for ((pr,pi),(qr,qi)),(u,v) in zip(rows,cols):
        m.append(pr*u[0]+pi*u[1]+qr*v[0]+qi*v[1]);m.append(pi*u[0]-pr*u[1]+qi*v[0]-qr*v[1])
    r,shift=exact_reciprocal(det);z=shift+15;amount=z-39
    scaled=[]
    for value in m:
        product=value*r
        scaled.append((product+(1<<(amount-1)))>>amount if amount>0 else product if amount==0 else product<<-amount)
    limit=1<<(WEIGHT_BITS-1);overflow=any(not -limit<=v<limit for v in scaled)
    result.update(m=m,reciprocal=r,z=z,scaled=scaled,weights=None if overflow else scaled,overflow=overflow)
    return result


def sums(weights,o0,o1):
    """Raw y0.re, y0.im, y1.re, y1.im before round24/sat18 (weights = 8 interleaved re/im)."""
    w=[(weights[2*k],weights[2*k+1]) for k in range(4)];out=[]
    for i in range(2):
        x,y=w[2*i],w[2*i+1]
        out.append(x[0]*o0[0]-x[1]*o0[1]+y[0]*o1[0]-y[1]*o1[1])
        out.append(x[0]*o0[1]+x[1]*o0[0]+y[0]*o1[1]+y[1]*o1[0])
    return out


def layout():
    g=gram_intervals();det=det_interval();scale=scale_bounds();s=sum_intervals();mb=m_bound()
    widths=dict(gram=max(signed_width(*v) for v in g.values()),det=signed_width(*det),
                m=signed_width(-mb,mb),m_interval=signed_width(*m_interval()),
                scale=max(signed_width(*scale['positive']),signed_width(-scale['left_shift_abs'],scale['left_shift_abs'])),
                sum=max(signed_width(*s['re_rounding']),signed_width(*s['im_rounding'])))
    det_w=trace(*DET_WITNESS);scale_w=trace(*SCALE_WITNESS)
    return dict(gram={k:list(v) for k,v in g.items()},det=list(det),m_abs_bound=mb,m_interval=list(m_interval()),
                scale={k:(list(v) if isinstance(v,tuple) else v) for k,v in scale.items()},
                sums={k:list(v) for k,v in s.items()},widths=widths,selected=SELECTED,old=OLD,
                witnesses=dict(gram_peak=1<<36,det=det_w['det'],m=max(abs(v) for v in det_w['m']),
                               scale=max(abs(v*scale_w['reciprocal']) for v in scale_w['m']),sum=1<<66))
