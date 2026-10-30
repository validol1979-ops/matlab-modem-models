"""Integer M-FSK modem (references of rtl/common/fsk_tx.sv and fsk_rx.sv).

research_core fsk_tx: symbol x gives n samples exp(2j pi (f0 + x df) t / n), t = 0..n-1
(the phase restarts every symbol); fsk_rx: argmax_m |sum_t x_t conj(basis_m,t)|.
Here the phase steps are designed per label and loaded: STEP[m] = round(((f0 + m df)/n mod 1)
* 2^32) (32-bit turns). The phase of sample t is t*STEP mod 2^32; its top 12 bits index the
pilot's Q17 cos table (bpsk_fixed.COS, 4096 entries, sin = cos(index - 1024)).
- TX: y = (rnd(cos, 2), rnd(sin, 2)) in Q15.
- RX: acc_m = sum_t x_t * (cos - j sin) exactly; c_m = rnd(acc_m, 17 + B) with B = bit length of
  n - 1 (so |c| stays near Q15); energy = re^2 + im^2; the decision is the first maximum.
round is half up, (v + 2^(s-1)) >> s."""
import math
import fft_fixed as f
from bpsk_fixed import COS


def steps(n,f0,df,order):
    if n<1 or order<1:raise ValueError('FSK needs n >= 1 and at least one tone')
    return [int(round(((f0+m*df)/n)%1*(1<<32)))%(1<<32) for m in range(order)]


def _basis(step,t):
    index=((t*step)%(1<<32))>>20
    return COS[index],COS[(index-1024)&4095]


def transmit(labels,n,table):
    if any(not 0<=int(l)<len(table) for l in labels):raise ValueError('FSK label outside the alphabet')
    out=[]
    for label in labels:
        for t in range(n):
            c,s=_basis(table[int(label)],t);out.append((f.rnd(c,2),f.rnd(s,2)))
    return out


def receive(x,n,table):
    if len(x)%n:raise ValueError('FSK input must be whole symbols')
    shift=17+(n-1).bit_length();out=[]
    for start in range(0,len(x),n):
        best=None;label=0
        for m,step in enumerate(table):
            re=im=0
            for t in range(n):
                c,s=_basis(step,t);xr,xi=x[start+t]
                re+=xr*c+xi*s;im+=xi*c-xr*s
            cr,ci=f.rnd(re,shift),f.rnd(im,shift);energy=cr*cr+ci*ci
            if best is None or energy>best:best=energy;label=m
        out.append(label)
    return out
