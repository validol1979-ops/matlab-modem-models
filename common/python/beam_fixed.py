"""Integer beamformer and Alamouti decoder (references of rtl/common/beamform.sv, alamouti_rx.sv).

research_core beamform: y = X @ conj(a) / (a^H a) per snapshot of M channels;
alamouti: per received pair (r0, r1), y0 = (conj(h0) r0 + h1 conj(r1))/E and
y1 = (conj(h1) r0 - h0 conj(r1))/E, E = |h0|^2 + |h1|^2.
Samples and weights are Q15 (18 bit). The energy E (Q30, exact) is inverted once per
configuration with a normalised mantissa: Z = 22 + bit length of E, R = divide(2^Z, E)
(nearest-even, as fxp_divide_seq; 2^22 <= R <= 2^23), and each output is
y = sat18(round(acc*R, Z - 15)) with acc the exact Q30 complex sum.
round is half up, (v + 2^(s-1)) >> s."""
import fft_fixed as f
from bpsk_fixed import divide

LIMIT=(1<<17)-1


def sat18(value):return max(-LIMIT-1,min(LIMIT,value))


def reciprocal(energy):
    if energy<=0:raise ValueError('Zero weight energy')
    z=22+int(energy).bit_length();r=divide(1<<z,energy)
    assert (1<<22)<=r<=(1<<23)
    return r,z


def _scale(re,im,r,z,stats=None,stage='beam.output'):
    """stats=None keeps the plain path byte for byte; with a SatStats the pre-clamp rounded
    values are recorded under stage.re/stage.im and record() returns the same sat18 value."""
    if stats is None:return sat18(f.rnd(re*r,z-15)),sat18(f.rnd(im*r,z-15))
    return (stats.record(stage+'.re',f.rnd(re*r,z-15),LIMIT,clamp='asym'),
            stats.record(stage+'.im',f.rnd(im*r,z-15),LIMIT,clamp='asym'))


def beamform(x,a,stats=None):
    m=len(a)
    if m<1 or len(x)%m:raise ValueError('Beamformer needs whole snapshots of M channels')
    # NumPy-целые переполняются до сужения; считаем в Python int.
    x=[(int(r),int(i)) for r,i in x];a=[(int(r),int(i)) for r,i in a]
    r,z=reciprocal(sum(ar*ar+ai*ai for ar,ai in a));out=[]
    for start in range(0,len(x),m):
        re=im=0
        for (xr,xi),(ar,ai) in zip(x[start:start+m],a):re+=xr*ar+xi*ai;im+=xi*ar-xr*ai
        out.append(_scale(re,im,r,z,stats,'beam.output'))
    return out


def alamouti(x,h,stats=None):
    if len(h)!=2 or len(x)%2:raise ValueError('Alamouti needs two channel taps and sample pairs')
    x=[(int(r),int(i)) for r,i in x];h=[(int(r),int(i)) for r,i in h]
    (h0r,h0i),(h1r,h1i)=h;r,z=reciprocal(h0r*h0r+h0i*h0i+h1r*h1r+h1i*h1i);out=[]
    for k in range(0,len(x),2):
        (ar,ai),(br,bi)=x[k],x[k+1]
        # conj(h0) r0 + h1 conj(r1) and conj(h1) r0 - h0 conj(r1)
        out.append(_scale(h0r*ar+h0i*ai+h1r*br+h1i*bi,h0r*ai-h0i*ar+h1i*br-h1r*bi,r,z,stats,'alamouti.y0'))
        out.append(_scale(h1r*ar+h1i*ai-h0r*br-h0i*bi,h1r*ai-h1i*ar-h0i*br+h0r*bi,r,z,stats,'alamouti.y1'))
    return out
