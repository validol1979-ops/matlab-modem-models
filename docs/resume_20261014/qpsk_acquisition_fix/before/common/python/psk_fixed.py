"""Integer PSK receiver/transmitter generalizing the BPSK pilot to QPSK.

A profile fixes the constellation amplitude T (per axis, Q15), the alphabet and
the differential mode. With the BPSK profile every function reproduces
bpsk_fixed bit for bit; the shared primitives are imported from it.

Normalizations by |target|^2 = 2*T^2 are exact for T=2^14 (BPSK). For QPSK
T=23170 (0.7071 in Q15), so 2*T^2 differs from 2^30 by 4e-5: gain and timing
errors use the power-of-two shift and the phase error a 1/sqrt(2) multiplier.

QPSK points on the axes (0, 90, 180, 270 degrees) need no separate receiver: the
preamble phase fit absorbs the 45 degree offset, after which the derotated points
are diagonal with T = |point|/sqrt(2). Only the transmitter mapping differs.

8-PSK uses the same idea: the receiver table is 22.5 + 45k degrees with unit
points, so decisions are octants (signs and |I| > |Q|). Transmit tables at 0 or
22.5 degrees are both absorbed by acquisition. The phase error needs the target
components cos/sin(22.5), the acquisition phase is angle(z) minus the target
angle, and the coherent amplitude is taken after rotating by that angle.
"""
from dataclasses import dataclass
import numpy as np
from fixed_point import round_shift
from bpsk_fixed import (SPS, TRAIN, FIT_START, FIT_COUNT, LOOP_DELAY, GAIN_DELAY,
                        COS, divide, wrap, atan2, sat, rotate, interp, fir, quantize)

USABLE=TRAIN-4
# 8-PSK constants, Q15: cos and sin of 22.5 degrees, 1/sqrt(2) and unit amplitude.
C8,S8,Q8,A8=30274,12540,23170,32768
TARGET8=((C8,S8),(S8,C8),(-S8,C8),(-C8,S8),(-C8,-S8),(-S8,-C8),(S8,-C8),(C8,-S8))
AXIS8=((A8,0),(Q8,Q8),(0,A8),(-Q8,Q8),(-A8,0),(-Q8,-Q8),(0,-A8),(Q8,-Q8))
# QAM16 per-axis levels (odd integers) in config.json table order; point = level*T.
QAM16_LEVELS=((3,3),(1,3),(3,1),(1,1),(-3,3),(-3,1),(-1,3),(-1,1),(-3,-3),(-1,-3),(-3,-1),(-1,-1),(3,-3),(3,-1),(1,-3),(1,-1))
QAM16_INDEX={levels:index for index,levels in enumerate(QAM16_LEVELS)}
# QAM64 per-axis levels (odd integers, +-1..+-7) in config.json table order.
QAM64_LEVELS=((1, 1), (3, 1), (1, 3), (3, 3), (7, 1), (5, 1), (7, 3), (5, 3), (1, 7), (3, 7), (1, 5), (3, 5), (7, 7), (5, 7), (7, 5), (5, 5), (1, -1), (1, -3), (3, -1), (3, -3), (1, -7), (1, -5), (3, -7), (3, -5), (7, -1), (7, -3), (5, -1), (5, -3), (7, -7), (7, -5), (5, -7), (5, -5), (-1, 1), (-1, 3), (-3, 1), (-3, 3), (-1, 7), (-1, 5), (-3, 7), (-3, 5), (-7, 1), (-7, 3), (-5, 1), (-5, 3), (-7, 7), (-7, 5), (-5, 7), (-5, 5), (-1, -1), (-3, -1), (-1, -3), (-3, -3), (-7, -1), (-5, -1), (-7, -3), (-5, -3), (-1, -7), (-3, -7), (-1, -5), (-3, -5), (-7, -7), (-5, -7), (-7, -5), (-5, -5))
QAM64_INDEX={levels:index for index,levels in enumerate(QAM64_LEVELS)}
QAM_LEVELS={16:QAM16_LEVELS,64:QAM64_LEVELS}
QAM_INDEX={16:QAM16_INDEX,64:QAM64_INDEX}


# Equalizer: taps Q2.22 (25 bits) enter the 25x18 products unrounded; the output is
# the sum rounded by 22 and saturated to 18 bits. The NLMS step is 0.3 on the preamble
# and 0.02 on data (Q15). 1/power is a floating reciprocal: a 10-bit mantissa
# addresses a ROM of round(2^19/m), the exponent becomes one shift of the per-symbol
# complex coefficient. The output of symbol k uses the updates of symbols up to
# k-1-EQ_DELAY (delayed LMS: the hardware pipelines the update behind the output,
# one symbol per 4 clocks, so the coefficient of symbol k reaches symbol k+5).
EQ_FORWARD,EQ_FEEDBACK=7,3
EQ_STEP_TRAIN,EQ_STEP_DATA=9830,655
EQ_TAP_MAX=(1<<24)-1
EQ_DELAY=4
EQ_RECIPROCAL=tuple(round((1<<19)/m) for m in range(512,1024))


def eq_tap(x):return max(-EQ_TAP_MAX-1,min(EQ_TAP_MAX,x))


def eq_coefficient(error,power,step):
    """Complex step*error/power scaled so that a tap delta is round_shift(c*conj(x), 18)."""
    s=power.bit_length();m=power>>(s-10) if s>10 else power<<(10-s)
    r=EQ_RECIPROCAL[m-512]
    # delta (Q22) = step*e*conj(x)*r*2^(-2-s): the variable shift acts on the scalar.
    return tuple(sat(round_shift(e*step*r,s-16)) for e in error)


class Equalizer:
    """Integer NLMS/DFE after rotation and gain, before the slicer (modem_core.symbol_receiver)."""
    def __init__(self,mode,delay=None):
        self.mode=mode;self.delay=EQ_DELAY if delay is None else delay
        self.forward=[(0,0)]*EQ_FORWARD;self.forward[0]=(1<<22,0)
        self.feedback=[(0,0)]*EQ_FEEDBACK
        self.history=[(0,0)]*EQ_FORWARD;self.past=[(0,0)]*EQ_FEEDBACK;self.power=0
        self.pending=[]

    def output(self,value):
        old=self.history[-1];self.history=[value]+self.history[:-1]
        self.power+=value[0]**2+value[1]**2-old[0]**2-old[1]**2
        taps=list(zip(self.forward,self.history))
        if self.mode=='dfe':taps+=list(zip(self.feedback,self.past))
        re=sum(wr*xr-wi*xi for (wr,wi),(xr,xi) in taps);im=sum(wr*xi+wi*xr for (wr,wi),(xr,xi) in taps)
        return (sat(round_shift(re,22)),sat(round_shift(im,22)))

    def update(self,y,target,training):
        error=(sat(target[0]-y[0]),sat(target[1]-y[1]))
        power=self.power+(sum(a*a+b*b for a,b in self.past) if self.mode=='dfe' else 0)+1
        c=eq_coefficient(error,power,EQ_STEP_TRAIN if training else EQ_STEP_DATA)
        self.pending.append((c,list(self.history),list(self.past)))
        if len(self.pending)>self.delay:
            (cr,ci),history,past=self.pending.pop(0)
            # c*conj(x) = (cr*xr+ci*xi) + j(ci*xr-cr*xi)
            self.forward=[(eq_tap(w0+round_shift(cr*xr+ci*xi,18)),eq_tap(w1+round_shift(ci*xr-cr*xi,18))) for (w0,w1),(xr,xi) in zip(self.forward,history)]
            if self.mode=='dfe':
                self.feedback=[(eq_tap(w0+round_shift(cr*xr+ci*xi,18)),eq_tap(w1+round_shift(ci*xr-cr*xi,18))) for (w0,w1),(xr,xi) in zip(self.feedback,past)]
        self.past=[target]+self.past[:-1]


def reciprocal(n):
    """Q16 reciprocal of the squared target level norm n = a^2+b^2 (QAM error normalization)."""
    return divide(1<<16,n)


@dataclass(frozen=True)
class Profile:
    name: str
    order: int
    amplitude: int          # T: per-axis symbol value, Q15
    differential: str       # 'psk' (BPSK XOR) or 'none'
    pe_mul: int             # phase error multiplier, Q15: 2^29/T rounded
    ge_shift: int           # gain error: x*2^14/T^2 -> round_shift(x, ge_shift)
    te_shift: int           # timing error shift after inv_square, Q12
    pe_from_decision: bool  # BPSK Costas uses decisions even during training
    tx_axis: bool=False     # transmit points on the axes, |point| = sqrt(2)*T
    freq_gain: int=4        # 0.0002 rad/symbol per unit error; 0 for feedforward carrier
    phase_gain: int=834     # 0.04 rad (feedback) or 626 = 0.03 rad (feedforward)
    timing_gain: int=3932   # 0.015 symbol, Q17; 0 without a timing loop
    equalizer: str='none'   # 'none', 'linear' (7-tap NLMS) or 'dfe' (7 forward + 3 feedback)
    block_fit: bool=False   # acquisition fits block phases (fit_blocks), robust to echoes
    loop_delay: int=LOOP_DELAY  # carrier/timing feedback delay in symbols (8 with an equalizer)
    tx_amplitude: int=0     # QAM transmit level scale (0: T); QAM64 sends level*2^14 with tx_shift 16
    tx_shift: int=17        # transmit FIR rounding
    rx_shift: int=17        # receive FIR rounding; QAM64 19 (+-7 levels would saturate Q3.15)

    @property
    def bits(self):return self.order.bit_length()-1

    @property
    def alphabet(self):
        """Number of symbol labels; pi/4-QPSK sends 4 labels over the 8-point table."""
        return 4 if self.differential=='pi4' else self.order

    @property
    def gain_numerator(self):return (self.amplitude if self.order==8 else 2*self.amplitude)<<20

    def theta(self,index):
        """8-PSK target angle 22.5 + 45*index degrees in 2^-32 turns."""
        return (2*index+1)<<28

    @property
    def qam(self):return self.order>=16

    @property
    def te_mul(self):
        """Q16 factor 2/Es with Es the mean squared level norm (10 for QAM16, 42 for QAM64)."""
        return divide(2<<16,10 if self.order==16 else 42)

    @property
    def max_level(self):return 3 if self.order==16 else 7

    @property
    def log_t(self):
        """QAM: T = 2^log_t (2^14 for QAM16, 2^13 for QAM64)."""
        return self.amplitude.bit_length()-1

    def target(self,index):
        """Integer target point used by the error detectors."""
        if self.order==8:return TARGET8[index]
        a,b=self.point(index);return (a*self.amplitude,b*self.amplitude)

    def point(self,index):
        """Signs (a, b) of the per-axis value; table order follows config.json."""
        if self.order==2:return ((1,1),(-1,-1))[index]
        if self.qam:return QAM_LEVELS[self.order][index]
        return ((1,1),(-1,1),(-1,-1),(1,-1))[index]

    def slice(self,v):
        if self.order==2:return int(v[0]+v[1]<0)
        if self.qam:
            # Nearest odd level per axis (boundaries at even multiples of T, ties upward).
            m=self.max_level;level=lambda x:max(-m,min(m,2*(x//(2*self.amplitude))+1))
            return QAM_INDEX[self.order][(level(v[0]),level(v[1]))]
        if self.order==8:
            # Quadrant from the signs; the |I| > |Q| test picks the octant within it.
            q={(0,0):0,(1,0):1,(1,1):2,(0,1):3}[(int(v[0]<0),int(v[1]<0))];larger=abs(v[0])>abs(v[1])
            return 2*q+int(larger if q&1 else not larger)
        # Quadrant of the value; zero counts as positive.
        return {(0,0):0,(1,0):1,(1,1):2,(0,1):3}[(int(v[0]<0),int(v[1]<0))]


    def tx_point(self,index):
        if self.order==8:return (AXIS8 if self.tx_axis else TARGET8)[index]
        if self.qam:a,b=self.point(index);t=self.tx_amplitude or self.amplitude;return (a*t,b*t)
        if not self.tx_axis:
            a,b=self.point(index);return (a*self.amplitude,b*self.amplitude)
        return ((32768,0),(0,32768),(-32768,0),(0,-32768))[index]


BPSK=Profile('bpsk',2,16384,'psk',32768,14,27,True)
QPSK=Profile('qpsk',4,23170,'none',23171,15,28,False)
# Diagonal QPSK at 0.5 per axis, Gray-differential, feedback carrier, Gardner.
QPSK_HALF_DIFF=Profile('qpsk_half_diff',4,16384,'psk',32768,14,27,False)
# Unit points on the axes: Gray-differential, feedforward carrier, no timing loop.
QPSK_AXIS_DIFF_FF=Profile('qpsk_axis_diff_ff',4,23170,'psk',23171,15,28,False,True,0,626,0)
# Unit points on the axes, no differential coding, feedback carrier, Gardner.
QPSK_AXIS=Profile('qpsk_axis',4,23170,'none',23171,15,28,False,True)
# Diagonal unit QPSK, Gray-differential, feedback carrier, Gardner: the receiver after
# two-branch combining (mrc_fixed); profile_for rejects the two-branch config itself.
QPSK_DIFF=Profile('qpsk_diff',4,23170,'psk',23171,15,28,False)
# 8-PSK, unit points, Gray-differential. tx_axis: transmit table at 0 degrees.
PSK8_FF=Profile('psk8_ff',8,32768,'psk',1,15,28,False,True,0,626,0)
PSK8_FB=Profile('psk8_fb',8,32768,'psk',1,15,28,False,True)
PSK8_ROTATED_FB=Profile('psk8_rotated_fb',8,32768,'psk',1,15,28,False,False,4,834,0)
# pi/4-QPSK: 8-point table at k*45 degrees, index advances by 2*gray(label)+1 (odd steps),
# 2-bit labels; feedforward carrier, no timing loop. Decisions use all 8 points, as in
# the floating receiver.
PI4=Profile('pi4',8,32768,'pi4',1,15,28,False,True,0,626,0)
# QAM16 at levels +-1, +-3 times T = 0.5 (Es = 2.5), quadrant-differential, feedback
# carrier, Gardner. Errors are normalized by |target|^2 = n*T^2 through reciprocal(n).
QAM16=Profile('qam16',16,16384,'quadrant',0,14,27,False)
# QAM16 with the 7-tap NLMS equalizer or the DFE (7 forward, 3 feedback taps).
QAM16_EQ=Profile('qam16_eq',16,16384,'quadrant',0,14,27,False,equalizer='linear',block_fit=True,loop_delay=8)
# QAM64 at levels +-1..+-7 (Es = 42), quadrant-differential, feedback carrier, Gardner. The
# receive filter output is scaled by 1/4 (rx_shift 19) and T = 2^13 after the gain;
# the transmitter sends level*2^14 and its FIR rounds by 16, so the waveform is exact Q15.
QAM64=Profile('qam64',64,8192,'quadrant',0,13,25,False,tx_amplitude=16384,tx_shift=16,rx_shift=19)
QAM16_DFE=Profile('qam16_dfe',16,16384,'quadrant',0,14,27,False,equalizer='dfe',block_fit=True,loop_delay=8)
PROFILES=(BPSK,QPSK,QPSK_HALF_DIFF,QPSK_AXIS_DIFF_FF,QPSK_AXIS,QPSK_DIFF,PSK8_FF,PSK8_FB,PSK8_ROTATED_FB,PI4,QAM16,QAM16_EQ,QAM16_DFE,QAM64)


def profile_for(cfg):
    """Select the integer profile for a modem config; reject unsupported variants."""
    table=np.asarray(cfg['constellation'],float)
    if cfg['family']=='pi4' and cfg['differential']=='pi4' and cfg['diversity_branches']==1 and cfg['equalizer']=='none':
        z=table[:,0]+1j*table[:,1]
        if np.allclose(z,np.exp(1j*np.pi/4*np.arange(8))) and cfg['carrier']=='feedforward' and cfg['timing']!='gardner':return PI4
        raise ValueError('No integer PSK profile for this configuration')
    if cfg['family']=='qam' and cfg['order']==16 and cfg['diversity_branches']==1:
        levels=np.asarray(QAM16_LEVELS,float)*.5
        if np.allclose(table,levels) and cfg['differential']=='quadrant' and cfg['carrier']=='feedback' and cfg['timing']=='gardner':
            return {'none':QAM16,'linear':QAM16_EQ,'dfe':QAM16_DFE}[cfg['equalizer']]
        raise ValueError('No integer PSK profile for this configuration')
    if cfg['family']=='qam' and cfg['order']==64 and cfg['diversity_branches']==1 and cfg['equalizer']=='none':
        if np.allclose(table,QAM64_LEVELS) and cfg['differential']=='quadrant' and cfg['carrier']=='feedback' and cfg['timing']=='gardner':return QAM64
        raise ValueError('No integer PSK profile for this configuration')
    if cfg['family']!='psk' or cfg['diversity_branches']!=1 or cfg['equalizer']!='none':
        raise ValueError('No integer PSK profile for this configuration')
    if cfg['order']==2:
        if cfg['differential']=='psk' and cfg['carrier']=='costas' and cfg['timing']=='gardner' and np.allclose(table,[[.5,.5],[-.5,-.5]]):
            return BPSK
        raise ValueError('No integer PSK profile for this configuration')
    z=table[:,0]+1j*table[:,1];q=np.sqrt(.5)
    feedback=cfg['carrier'] in ('feedback','costas');gardner=cfg['timing']=='gardner'
    if cfg['order']==8:
        k=np.arange(8)
        axis8=np.allclose(z,np.exp(1j*np.pi/4*k));rotated8=np.allclose(z,np.exp(1j*(np.pi/8+np.pi/4*k)))
        if cfg['differential']!='psk':raise ValueError('No integer PSK profile for this configuration')
        if axis8 and cfg['carrier']=='feedforward' and not gardner:return PSK8_FF
        if axis8 and feedback and gardner:return PSK8_FB
        if rotated8 and feedback and not gardner:return PSK8_ROTATED_FB
        raise ValueError('No integer PSK profile for this configuration')
    if cfg['order']!=4:raise ValueError('No integer PSK profile for this configuration')
    diagonal=np.allclose(z,[q,-q,-q,q]+1j*np.array([q,q,-q,-q])*1)
    axis=np.allclose(z,[1,1j,-1,-1j])
    half=np.allclose(z,.5*np.array([1+1j,-1+1j,-1-1j,1-1j]))
    if diagonal and cfg['differential']=='none' and cfg['carrier']=='costas' and gardner:return QPSK
    if diagonal and cfg['differential']=='psk' and feedback and gardner:return QPSK_DIFF
    if half and cfg['differential']=='psk' and feedback and gardner:return QPSK_HALF_DIFF
    if axis and cfg['differential']=='psk' and cfg['carrier']=='feedforward' and not gardner:return QPSK_AXIS_DIFF_FF
    if axis and cfg['differential']=='none' and feedback and gardner:return QPSK_AXIS
    raise ValueError('No integer PSK profile for this configuration')


def check_symbols(profile,symbols):
    for s in symbols:
        if int(s)!=s or not 0<=int(s)<profile.alphabet:raise ValueError('Symbol label outside the alphabet')


def gray(value):return value^(value>>1)


def gray_inverse(value):
    result=value
    while value:=value>>1:result^=value
    return result


def encode(profile,symbols):
    """Table indices; 'psk' advances the phase state by gray(label) (XOR for BPSK)."""
    check_symbols(profile,symbols)
    if profile.differential=='none':return [int(s) for s in symbols]
    state=0;ids=[]
    if profile.differential=='pi4':
        for s in symbols:state=(state+2*gray(int(s))+1)%8;ids.append(state)
        return ids
    if profile.differential=='quadrant':
        # The quadrant q = label // group advances by gray(q); the rest is sent as is.
        group=profile.order//4
        for s in symbols:state=(state+gray(int(s)//group))%4;ids.append(group*state+int(s)%group)
        return ids
    for s in symbols:state=(state+gray(int(s)))%profile.order;ids.append(state)
    return ids


def decode(profile,index,previous):
    if profile.differential=='none':return index
    if profile.differential=='pi4':return gray_inverse((((index-previous)%8-1)%8)>>1)
    if profile.differential=='quadrant':
        group=profile.order//4
        return group*gray_inverse((index//group-previous//group)%4)+index%group
    return gray_inverse((index-previous)%profile.order)


def transmit(profile,symbols):
    wave=[(0,0)]*(len(symbols)*SPS)
    for i,idx in enumerate(encode(profile,symbols)):wave[SPS*i]=profile.tx_point(idx)
    return fir(wave,profile.tx_shift)


FIT_BLOCK=16


def fit_blocks(profile,wave,ids,candidate):
    """Block carrier fit for the equalizer profiles. With a one-symbol echo of 0.45 the
    per-symbol phases of z_k*conj(level_k) slip; coherent sums over 8 blocks of 16
    symbols average the interference. Block phases are unwrapped and fitted as in
    acquire, then rescaled to symbols. Range: 1/32 turn per symbol."""
    blocks=FIT_COUNT//FIT_BLOCK;phases=[];previous=None;unwrapped=0
    for j in range(blocks):
        s_re=s_im=0
        for k in range(FIT_START+FIT_BLOCK*j,FIT_START+FIT_BLOCK*(j+1)):
            r,i=interp(wave,(32<<16)+candidate+(8*k<<16));a,b=profile.point(ids[k])
            s_re+=a*r+b*i;s_im+=a*i-b*r
        phase=atan2(s_im,s_re)
        if previous is None:unwrapped=phase
        else:unwrapped+=wrap(phase-previous)
        previous=phase;phases.append(unwrapped)
    weighted=sum((2*j-blocks+1)*p for j,p in enumerate(phases))
    # Block slope 6*W/(B*(B^2-1)) per block; per symbol divide by FIT_BLOCK as well.
    slope=divide(6*weighted,blocks*(blocks**2-1)*FIT_BLOCK)
    # Block j is centred on symbol FIT_START+16j+7.5.
    intercept=divide(sum(phases),blocks)-round_shift(slope*(2*FIT_START+FIT_COUNT-1),1)
    # Residual at twice the scale: the block centre 2*(FIT_START+16j)+15 is odd.
    score=sum(round_shift(2*(p-intercept)-slope*(2*FIT_START+2*FIT_BLOCK*j+FIT_BLOCK-1),17)**2 for j,p in enumerate(phases))
    return (score,candidate,wrap(slope),wrap(intercept))


def acquire(profile,wave,preamble):
    ids=encode(profile,preamble);energies=[0]*8
    for n in range(64,320):
        re,im=wave[n];energies[n&7]+=re*re+im*im
    energies=[min(131071,round_shift(e,19)) for e in energies]
    re=sum(energies[i]*COS[i*512] for i in range(8))
    im=sum(energies[i]*COS[(i*512-1024)&4095] for i in range(8))
    delay=round_shift(atan2(im,re),13)
    candidates=[]
    for off in (0,8,16):
        candidate=delay+(off<<16)
        if not -(1<<15)<=candidate<=(16<<16)+(1<<15):continue
        if profile.block_fit:
            candidates.append(fit_blocks(profile,wave,ids,candidate));continue
        phases=[];previous=None;unwrapped=0
        for k in range(FIT_START,FIT_START+FIT_COUNT):
            r,i=interp(wave,(32<<16)+candidate+(8*k<<16))
            if profile.order==8:phase=wrap(atan2(i,r)-profile.theta(ids[k]))
            else:
                # angle(z*conj(a+jb)); for BPSK a=b=sign.
                a,b=profile.point(ids[k]);phase=atan2(a*i-b*r,a*r+b*i)
            if previous is None:unwrapped=phase
            else:unwrapped+=wrap(phase-previous)
            previous=phase;phases.append(unwrapped)
        weighted=sum((2*k-FIT_COUNT+1)*p for k,p in enumerate(phases))
        slope=divide(6*weighted,FIT_COUNT*(FIT_COUNT**2-1))
        intercept=divide(sum(phases),FIT_COUNT)-round_shift(slope*(2*FIT_START+FIT_COUNT-1),1)
        score=sum(round_shift(p-intercept-slope*(FIT_START+k),16)**2 for k,p in enumerate(phases))
        candidates.append((score,candidate,wrap(slope),wrap(intercept)))
    if not candidates:raise ValueError('No acquisition candidate')
    score,delay,slope,phase=min(candidates)
    amplitude=0;energy=0
    for k in range(FIT_START,FIT_START+FIT_COUNT):
        if profile.order==8:
            amplitude+=rotate(interp(wave,(32<<16)+delay+(8*k<<16)),phase+slope*k+profile.theta(ids[k]))[0]
        else:
            z=rotate(interp(wave,(32<<16)+delay+(8*k<<16)),phase+slope*k);a,b=profile.point(ids[k])
            amplitude+=a*z[0]+b*z[1];energy+=a*a+b*b
    # QAM: coherent amplitude per level; for +-1 levels divide(2S, 2N) equals divide(S, N).
    amplitude=divide(2*amplitude,energy) if profile.qam else divide(amplitude,FIT_COUNT)
    if amplitude<0:
        phase=wrap(phase+2**31);amplitude=-amplitude
    confidence=amplitude>=32
    amplitude=max(32,amplitude)
    gain=min(16<<20,divide(profile.gain_numerator,amplitude))
    return dict(delay=delay,frequency=slope,phase=phase,gain=gain,score=score,confidence=confidence)


def receive(profile,wave,preamble,count,*,tracking=True,observe=False,eq_delay=None):
    if len(preamble)!=TRAIN or count<TRAIN or count>2048 or len(wave)<count*SPS:raise ValueError('Invalid frame')
    check_symbols(profile,preamble)
    filtered=fir(wave,profile.rx_shift);acq=acquire(profile,filtered,preamble);ids_train=encode(profile,preamble)
    phase=acq['phase'];frequency=acq['frequency'];gain=acq['gain'];correction=0
    # QAM folds 2/Es (in squared levels) into the timing normalization.
    inv_square=round_shift(gain*gain*profile.te_mul,44) if profile.qam else round_shift(gain*gain,28)
    equalizer=Equalizer(profile.equalizer,eq_delay) if profile.equalizer!='none' else None
    pending=[(0,0)]*profile.loop_delay;gain_pending=[0]*GAIN_DELAY;ids=[];labels=[];trace=[];nodes=[];prev=0
    for k in range(count):
        pe,te=pending.pop(0);gd=gain_pending.pop(0)
        if tracking:
            frequency=wrap(frequency+pe*profile.freq_gain)
            phase=wrap(phase+pe*profile.phase_gain)
            gain=max(1,min(16<<20,gain+gd))
            correction+=round_shift(te*profile.timing_gain,17)
        pos=(32<<16)+acq['delay']+(8*k<<16)+correction
        early=interp(filtered,pos-(4<<16));mid=interp(filtered,pos);late=interp(filtered,pos+(4<<16))
        ted=2*((late[0]-early[0])*mid[0]+(late[1]-early[1])*mid[1])
        te=max(-32768,min(32768,round_shift(ted*inv_square,profile.te_shift)))
        phase_used=wrap(phase+acq['frequency']*k)
        rotated=rotate(mid,phase_used)
        value=tuple(sat(round_shift(x*gain,20)) for x in rotated)
        if equalizer:value=equalizer.output(value)
        idx=profile.slice(value)
        target_index=ids_train[k] if k<USABLE else idx
        t0,t1=profile.target(target_index)
        if equalizer:equalizer.update(value,(t0,t1),k<USABLE)
        if profile.order==8:
            # |target|^2 = 2^30: imag(value*conj(target)) >> 15 is the Q15 error.
            pe=max(-16384,min(16384,round_shift(value[1]*t0-value[0]*t1,15)))
        else:
            ta,tb=profile.point(target_index)
            pa,pb=profile.point(idx) if profile.pe_from_decision else (ta,tb)
            # imag(value*conj(target))/|target|^2 in Q15, clipped to +-0.5.
            if profile.qam:
                # imag(value*conj(target))/|target|^2 = (a*v1-b*v0)/(T*n): times 2^15 is
                # (a*v1-b*v0)*R(n) >> (log2 T + 1) with R(n) = 2^16/n.
                r=reciprocal(ta*ta+tb*tb);pe=max(-16384,min(16384,round_shift((ta*value[1]-tb*value[0])*r,profile.log_t+1)))
            else:pe=max(-16384,min(16384,round_shift((pa*value[1]-pb*value[0])*profile.pe_mul,15)))
        if profile.qam:
            ge=max(-16384,min(16384,round_shift(((t0-value[0])*value[0]+(t1-value[1])*value[1])*r,2*profile.log_t+1)))
        else:ge=max(-16384,min(16384,round_shift(2*((t0-value[0])*value[0]+(t1-value[1])*value[1]),profile.ge_shift+1)))
        if observe:nodes.append(dict(position=pos,phase=phase_used,early=early,mid=mid,late=late,rotated=rotated,gain=gain,value=value,pe=pe,ge=ge,te=te))
        pending.append((pe,te));gain_pending.append(round_shift(gain*ge*262,32));phase=wrap(phase+frequency-acq['frequency'])
        label=decode(profile,idx,prev)
        ids.append(idx);labels.append(label);prev=idx
        trace.append((value[0],value[1],phase,frequency,gain,correction,idx,label))
    return dict(data=np.array(labels),trace=trace,filtered=filtered,acquisition=acq,nodes=nodes)
