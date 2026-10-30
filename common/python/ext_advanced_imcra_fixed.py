"""Q48 integer OM-LSA/IMCRA spectral tracker with full feedback state.

Scalar operations round half-up after EVERY product/division. Python integers
avoid accumulator wrap; stored scalar range is signed120, overflow rejects.
Sqrt is exact integer isqrt; log/exp/E1 use offline 4096-segment mantissa LUTs
with integer interpolation. Exp underflows below2^-80. No runtime floating
nonlinear arithmetic, covariance/state or gain-feedback calculations.

Supported source profile fs16k/M512. FFT/window/OLA frontend is explicitly
outside this fixed SPECTRAL tracker; fixed power/gain IQ interfaces provided.
"""
import math
import numpy as np
from scipy.special import exp1 as _offline_exp1
try:from .ext_advanced_imcra import IMCRA
except ImportError:from ext_advanced_imcra import IMCRA

BITS=48;S=1<<BITS;L=4096

def _round(n,d):
 if d<0:n=-n;d=-d
 if d==0:raise ZeroDivisionError('fixed zero denominator')
 return (2*n+d)//(2*d)
def _from_float(v):return int(math.floor(float(v)*S+.5))
_LN2=_from_float(math.log(2));_LN10=_from_float(math.log(10))
_LOG=[_from_float(math.log1p(i/L)) for i in range(L+1)]
_EXP=[_from_float(math.exp(math.log(2)*i/L)) for i in range(L+1)]
_E1={e:[_from_float(v) for v in _offline_exp1((1+np.arange(L+1)/L)*2.**e)] for e in range(-48,4)}

def _interpolate(table,index,remainder,denominator):
 return table[index]+_round((table[index+1]-table[index])*remainder,denominator)
def _mantissa(raw):
 exponent=raw.bit_length()-1-BITS
 mant=(raw>>exponent) if exponent>=0 else (raw<<-exponent)
 scaled=(mant-S)*L;index,remainder=divmod(scaled,S)
 return exponent,index,remainder

def _log(raw):
 if raw<=0:raise ArithmeticError('fixed logarithm nonpositive')
 e,i,r=_mantissa(raw)
 return e*_LN2+_interpolate(_LOG,i,r,S)
def _exp(raw):
 e,r=divmod(raw,_LN2)
 if e < -80:return 0
 if e>60:raise OverflowError('fixed exp range')
 i,rem=divmod(r*L,_LN2);v=_interpolate(_EXP,i,rem,_LN2)
 return v<<e if e>=0 else _round(v,1<<-e)
def _e1(raw):
 if raw<=0:raise ArithmeticError('fixed E1 domain')
 e,i,r=_mantissa(raw)
 if e < -48:return -_log(raw)-_from_float(.5772156649015329)
 if e>2:raise ArithmeticError('E1 LUT used only v<=5')
 return _interpolate(_E1[e],i,r,S)

_CONSTANT_RAW={v:_from_float(v) for v in (0.,1.,.25,.5,2.5,5.,.9,2.,1.4685,.8,.2,10.,-100.)}

class Fixed:
 __slots__=('raw',)
 def __init__(self,raw):
  self.raw=int(raw)
  if abs(self.raw)>=(1<<119):raise OverflowError('signed120 fixed scalar')
 @staticmethod
 def of(v):
  if isinstance(v,Fixed):return v
  if isinstance(v,(int,np.integer,bool,np.bool_)):return Fixed(int(v)*S)
  if v not in _CONSTANT_RAW:_CONSTANT_RAW[v]=_from_float(v)  # offline config construction
  return Fixed(_CONSTANT_RAW[v])
 def __float__(self):return self.raw/S
 def __repr__(self):return 'FixedRaw('+str(self.raw)+')'
 def __add__(self,v):
  if isinstance(v,np.ndarray):return NotImplemented
  return Fixed(self.raw+Fixed.of(v).raw)
 __radd__=__add__
 def __sub__(self,v):
  if isinstance(v,np.ndarray):return NotImplemented
  return Fixed(self.raw-Fixed.of(v).raw)
 def __rsub__(self,v):
  if isinstance(v,np.ndarray):return NotImplemented
  return Fixed.of(v)-self
 def __mul__(self,v):
  if isinstance(v,np.ndarray):return NotImplemented
  return Fixed(_round(self.raw*Fixed.of(v).raw,S))
 __rmul__=__mul__
 def __truediv__(self,v):
  if isinstance(v,np.ndarray):return NotImplemented
  return Fixed(_round(self.raw*S,Fixed.of(v).raw))
 def __rtruediv__(self,v):
  if isinstance(v,np.ndarray):return NotImplemented
  return Fixed.of(v)/self
 def __neg__(self):return Fixed(-self.raw)
 def __abs__(self):return Fixed(abs(self.raw))
 def __eq__(self,v):return self.raw==Fixed.of(v).raw
 def __lt__(self,v):return self.raw<Fixed.of(v).raw
 def __le__(self,v):return self.raw<=Fixed.of(v).raw
 def __gt__(self,v):return self.raw>Fixed.of(v).raw
 def __ge__(self,v):return self.raw>=Fixed.of(v).raw
 def __bool__(self):return bool(self.raw)
 def __pow__(self,v):
  if isinstance(v,int) and v==2:return self*self
  exponent=Fixed.of(v)
  if exponent.raw==0:return Fixed(S)
  if self.raw==0:return Fixed(0)
  return Fixed(_exp(_round(_log(self.raw)*exponent.raw,S)))
 def exp(self):return Fixed(_exp(self.raw))
 def sqrt(self):
  if self.raw<0:raise ArithmeticError('sqrt negative')
  return Fixed(math.isqrt(self.raw*S))
 def log10(self):return Fixed(_round(_log(self.raw)*S,_LN10))

def _ones(n):return np.array([Fixed(S) for _ in range(n)],dtype=object)
def _zeros(n):return np.array([Fixed(0) for _ in range(n)],dtype=object)
def _qarray(a):return np.array([Fixed.of(v) for v in np.asarray(a).flat],dtype=object).reshape(np.asarray(a).shape)
def _raw(a,frac=48):return np.array([_round(v.raw,1<<(48-frac)) for v in np.asarray(a).flat],dtype=object).reshape(np.asarray(a).shape)
def _power(a,n):
 a=np.asarray(a,dtype=object)
 if a.shape!=(n,) or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or not 0<=v<=1024*S for v in a):raise ValueError('Q48 nonnegative power257bins, maximum1024')
 return np.array([Fixed(v) for v in a],dtype=object)
def exp1(a):return np.array([Fixed(_e1(v.raw)) for v in a],dtype=object)
def speech_presence(q,eta,v):
 # Algebraic form avoids q/(1-q) when quantization rounds qhat to unity.
 # At q==1, denominator positive and numerator0 => probability0 exactly.
 den=1-q
 return den/(den+q*(1+eta)*np.exp(-v))
EPS=Fixed.of(1e-10)

class IMCRAFixed(IMCRA):
 def __init__(self):
  super().__init__(fs=16000,m=512)
  for key in ('alpha_s','alpha_d','alpha_eta','alpha_xi','alpha_d_long','delta_s','Bmin','delta_y','delta_yt','P_min','xi_lu_dB','xi_ll_dB','xi_gu_dB','xi_gl_dB','xi_fu_dB','xi_fl_dB','xi_mu_dB','xi_ml_dB','q_max','eta_min','G_f','zero_thres'):
   setattr(self,key,Fixed.of(getattr(self,key)))
  self.b=_qarray(self.b);self.b_xi_local=_qarray(self.b_xi_local);self.b_xi_global=_qarray(self.b_xi_global);self.reset()
 def reset(self):
  IMCRA.reset(self)
  for key in ('eta_2term','xi','xi_frame','lambda_d','lambda_dav','lambda_dav_long','S','St','Smin','SMact','Smint','SMactt','SW','SWt','Sy','qhat','phat','q','PH1','GH1','GH0','G','gamma','eta','v','xi_local','xi_global','P_local','P_global','P_frame','xi_m_dB','xi_frame_dB','dxi_frame','frame_presence','mean_local','Sf','last_power'):
   a=getattr(self,key)
   setattr(self,key,_qarray(a) if isinstance(a,np.ndarray) else Fixed.of(a))
 def _conv_same_shift(self,x,k,w):return np.convolve(_qarray(k),_qarray(x))[w:w+self.m21]
 @staticmethod
 def _dB(v):
  a=_qarray(v)
  if a.ndim==0 or a.size==1:
   x=a.ravel()[0];return Fixed.of(10)*x.log10() if x>0 else Fixed.of(-100)
  if not all(x>0 for x in a):return Fixed.of(-100)
  return np.array([Fixed.of(10)*x.log10() for x in a],dtype=object)
 def _pramp(self,db,lo,hi):
  db=np.broadcast_to(np.asarray(db,dtype=object),(self.m21,))
  out=_ones(self.m21);out[db<=lo]=self.P_min;mid=(db>lo)&(db<hi)
  out[mid]=self.P_min+(db[mid]-lo)/(hi-lo)*(1-self.P_min)
  return out
 def process_audio(self,samples):raise NotImplementedError('fixed scope is spectral state/gain; use explicit fixed FFT frontend')
 def apply_gain(self,iq):
  a=np.asarray(iq,dtype=object)
  if a.shape!=(257,2) or any(isinstance(v,(bool,np.bool_)) or not isinstance(v,(int,np.integer)) or not -(1<<17)<=v<(1<<17) for v in a.flat):raise ValueError('signed18 Q17 spectral IQ')
  out=[]
  for k,row in enumerate(a):
   gain=self.G[k].raw if 3<=k<256 else 0
   out.append([max(-(1<<17),min((1<<17)-1,_round(int(v)*gain,S))) for v in row])
  return np.asarray(out,np.int64)

 def step(self, power) -> np.ndarray:
     """Consume one 257-bin one-sided power frame; return the 257 gains."""
     x = _power(power,self.m21)
     self.last_power = x
     self.last_nonzero = bool(np.any(np.abs(x) > self.zero_thres))
     self.l += 1
     if not (self.fnz_flag or np.any(np.abs(x) > self.zero_thres)):
         self.l_fnz += 1          # silent warm-up, no state update
         self.rollover = self.l_mod_lswitch
         return _raw(self.G,31)
     self.fnz_flag = True
     n, w, l = self.m21, self.w, self.l
     ya2 = x
     self.Ya2 = ya2
     if l == self.l_fnz:
         self.lambda_d = ya2.copy()
     self.gamma = ya2 / np.maximum(self.lambda_d, EPS)
     self.eta = np.maximum(self.alpha_eta * self.eta_2term
                           + (1.0 - self.alpha_eta) * np.maximum(self.gamma - 1.0, 0.0),
                           self.eta_min)
     self.v = self.gamma * self.eta / (1.0 + self.eta)

     sf = self._conv_same_shift(ya2, self.b, w)
     self.Sf = sf
     if l == self.l_fnz:
         self.Sy, self.S, self.St = ya2.copy(), sf.copy(), sf.copy()
         self.lambda_dav = ya2.copy()
     else:
         self.S = self.alpha_s * self.S + (1.0 - self.alpha_s) * sf
     if l < 14 + self.l_fnz:
         self.Smin, self.SMact = self.S.copy(), self.S.copy()
     else:
         self.Smin = np.minimum(self.Smin, self.S)
         self.SMact = np.minimum(self.SMact, self.S)
     i_f = ((ya2 < self.delta_y * self.Bmin * self.Smin)
            & (self.S < self.delta_s * self.Bmin * self.Smin)).astype(object)
     conv_i = self._conv_same_shift(i_f, self.b, w)
     sft = self.St.copy()
     idx = conv_i != 0
     if np.any(idx):
         cy = self._conv_same_shift(i_f * ya2, self.b, w)
         sft[idx] = cy[idx] / conv_i[idx]
     if l < 14 + self.l_fnz:
         self.St, self.Smint, self.SMactt = self.S.copy(), self.S.copy(), self.S.copy()
     else:
         self.St = self.alpha_s * self.St + (1.0 - self.alpha_s) * sft
         self.Smint = np.minimum(self.Smint, self.St)
         self.SMactt = np.minimum(self.SMactt, self.St)

     self.qhat = _ones(n)
     self.phat = _zeros(n)
     if self.nonstat == "low":
         gm = ya2 / self.Bmin / np.maximum(self.Smin, EPS)
         zt = self.S / self.Bmin / np.maximum(self.Smin, EPS)
     else:
         gm = ya2 / self.Bmin / np.maximum(self.Smint, EPS)
         zt = self.S / self.Bmin / np.maximum(self.Smint, EPS)
     idx = (gm > 1.0) & (gm < self.delta_yt) & (zt < self.delta_s)
     self.qhat[idx] = (self.delta_yt - gm[idx]) / (self.delta_yt - 1.0)
     self.phat[idx] = speech_presence(self.qhat[idx],self.eta[idx],self.v[idx])
     self.phat[(gm >= self.delta_yt) | (zt >= self.delta_s)] = Fixed(S)
     alpha_dt = self.alpha_d + (1.0 - self.alpha_d) * self.phat
     self.lambda_dav = alpha_dt * self.lambda_dav + (1.0 - alpha_dt) * ya2
     if l < 14 + self.l_fnz:
         self.lambda_dav_long = self.lambda_dav.copy()
     else:
         adl = self.alpha_d_long + (1.0 - self.alpha_d_long) * self.phat
         self.lambda_dav_long = (adl * self.lambda_dav_long
                                 + (1.0 - adl) * ya2)
     self.l_mod_lswitch += 1
     if self.l_mod_lswitch == self.Vwin:
         self.l_mod_lswitch = 0
         if l == self.Vwin - 1 + self.l_fnz:
             self.SW = np.repeat(self.S[:, None], self.Nwin, axis=1)
             self.SWt = np.repeat(self.St[:, None], self.Nwin, axis=1)
         else:
             self.SW = np.column_stack((self.SW[:, 1:], self.SMact))
             self.Smin = self.SW.min(axis=1)
             self.SMact = self.S.copy()
             self.SWt = np.column_stack((self.SWt[:, 1:], self.SMactt))
             self.Smint = self.SWt.min(axis=1)
             self.SMactt = self.St.copy()
     if self.nonstat == "high":
         self.lambda_d = 2.0 * self.lambda_dav
     else:
         self.lambda_d = 1.4685 * self.lambda_dav
     self.rollover = self.l_mod_lswitch

     # ---- a priori probability of signal absence
     self.xi = self.alpha_xi * self.xi + (1.0 - self.alpha_xi) * self.eta
     self.xi_local = self._conv_same_shift(self.xi, self.b_xi_local,
                                           self.w_xi_local)
     self.xi_global = self._conv_same_shift(self.xi, self.b_xi_global,
                                            self.w_xi_global)
     prev = self.xi_frame
     self.xi_frame = np.mean(self.xi[self.k_l - 1:self.k_u])
     self.dxi_frame = self.xi_frame - prev
     xl = self._dB(self.xi_local)
     xg = self._dB(self.xi_global)
     self.xi_frame_dB = self._dB(self.xi_frame)
     self.P_local = self._pramp(xl, self.xi_ll_dB, self.xi_lu_dB)
     self.P_global = self._pramp(xg, self.xi_gl_dB, self.xi_gu_dB)
     k2, k3 = self.k2_local, self.k3_local
     self.mean_local = np.mean(self.P_local[2:k2 + k3 - 3])
     if self.mean_local < 0.25:
         self.P_local[k2 - 1:k3] = self.P_min
     if self.tone_flag and self.mean_local < 0.5 and l > 120:
         ldl = self.lambda_dav_long
         # 1-based 8:M21-8 vs 10:M21-6 and 6:M21-10 -> 0-based shifts 6/7/8.
         core = ldl[7:n - 8]
         idx = np.nonzero(core > 2.5 * (ldl[9:n - 6] + ldl[5:n - 10]))[0]
         if idx.size:
             rows = np.concatenate((idx + 6, idx + 7, idx + 8))
             self.P_local[rows] = self.P_min

     xfd = self.xi_frame_dB
     if xfd <= self.xi_fl_dB:
         self.P_frame = self.P_min
     elif self.dxi_frame >= 0:
         # xi_m_dB is persistent in the source; default is its lower limit.
         self.xi_m_dB = min(max(xfd, self.xi_ml_dB), self.xi_mu_dB)
         self.P_frame = Fixed(S)
     elif xfd >= self.xi_m_dB + self.xi_fu_dB:
         self.P_frame = Fixed(S)
     elif xfd <= self.xi_m_dB + self.xi_fl_dB:
         self.P_frame = self.P_min
     else:
         self.P_frame = (self.P_min
                         + (xfd - self.xi_m_dB - self.xi_fl_dB)
                         / (self.xi_fu_dB - self.xi_fl_dB) * (1.0 - self.P_min))

     if self.broad_flag:
         q = 1.0 - self.P_global * self.P_local * self.P_frame
     else:
         q = 1.0 - self.P_local * self.P_frame
     self.q = np.minimum(q, self.q_max)
     self.frame_presence = self.P_frame

     # ---- gain stage (second gamma/eta/v evaluation)
     self.gamma = ya2 / np.maximum(self.lambda_d, EPS)
     self.eta = np.maximum(self.alpha_eta * self.eta_2term
                           + (1.0 - self.alpha_eta) * np.maximum(self.gamma - 1.0, 0.0),
                           self.eta_min)
     self.v = self.gamma * self.eta / (1.0 + self.eta)
     ph1 = _zeros(n)
     idx = self.q < 0.9
     ph1[idx] = speech_presence(self.q[idx],self.eta[idx],self.v[idx])
     self.PH1 = ph1
     gh1 = _ones(n)
     idx = self.v > 5.0
     gh1[idx] = self.eta[idx] / (1.0 + self.eta[idx])
     idx = (self.v <= 5.0) & (self.v > 0.0)
     gh1[idx] = (self.eta[idx] / (1.0 + self.eta[idx])
                 * np.exp(0.5 * exp1(self.v[idx])))
     self.GH1 = gh1
     if self.tone_flag:
         ldg = self.lambda_d.copy()
         ldg[3:n - 3] = np.minimum(np.minimum(ldg[3:n - 3], ldg[0:n - 6]),
                                   ldg[6:n])
         self.Sy = 0.8 * self.Sy + 0.2 * ya2
         self.GH0 = self.G_f * np.sqrt(ldg / (self.Sy + EPS))
     else:
         self.GH0 = _ones(n) * self.G_f
     self.G = self.GH1 ** self.PH1 * self.GH0 ** (1.0 - self.PH1)
     self.eta_2term = self.GH1 ** 2 * self.gamma
     return _raw(self.G,31)

