"""Floating OM-LSA / IMCRA tracker, transcribed from local ``omlsa.m``.

Source schedule (single frame, 257 one-sided bins, fs=16 kHz, M=512):
  gamma -> eta -> v -> smooth S/St -> window minima -> qhat/phat ->
  lambda_dav -> lambda_dav_long -> Nwin/Vwin rollover -> lambda_d ->
  xi/P_local/P_global/P_frame/q -> gamma -> eta -> v -> PH1 -> GH1/GH0/G ->
  eta_2term=GH1**2*gamma.  The fixture is the independent authority.
"""
from __future__ import annotations

import math

import numpy as np
from scipy.special import exp1

FS_REF = 16000.0
M_REF = 512
MO_REF = 384
M21 = 257
NFFT = 512
HOP = 128
EPS = 1e-10

FIELD_NAMES = (
    "Ya2", "lambda_d", "lambda_dav", "lambda_dav_long", "S", "Sf", "Smin",
    "SMact", "St", "Smint", "SMactt", "qhat", "phat", "q", "PH1", "GH1",
    "GH0", "G", "eta_2term", "xi", "xi_local", "xi_global", "xi_frame",
    "dxi_frame", "P_local", "P_global", "P_frame", "gamma", "eta", "v", "Sy",
)
SCALAR_FIELDS = ("xi_frame", "xi_frame_dB", "xi_m_dB", "dxi_frame",
                 "frame_presence", "mean_local", "rollover", "frame")


def _hann(n: int) -> np.ndarray:
    """Symmetric Hann used by the reference (Hann(3) == [0, 1, 0])."""
    if n == 1:
        return np.ones(1)
    j = np.arange(n, dtype=float)
    return 0.5 * (1.0 - np.cos(2.0 * math.pi * j / (n - 1)))


def _hamming(n: int) -> np.ndarray:
    k = np.arange(n, dtype=float)
    return 0.54 - 0.46 * np.cos(2.0 * math.pi * k / (n - 1))


def _lnshift(x: np.ndarray, t: int) -> np.ndarray:
    return np.concatenate((x[t:], x[:t]))


class IMCRA:
    """State-machine OM-LSA gain stage with the source IMCRA schedule."""

    def __init__(self, fs: float = FS_REF, m: int = M_REF,
                 nonstat: str = "medium", tone: bool = True,
                 broad: bool = True) -> None:
        if isinstance(fs,bool) or fs!=FS_REF or isinstance(m,bool) or not isinstance(m,(int,np.integer)) or m!=M_REF:
            raise ValueError('supported source profile is fs16000/M512')
        if not isinstance(tone,bool) or not isinstance(broad,bool):
            raise ValueError('tone/broad flags must be bool')
        if nonstat not in ("low", "medium", "high"):
            raise ValueError("nonstat must be 'low', 'medium' or 'high'")
        self.fs, self.m = float(fs), int(m)
        self.nonstat, self.tone_flag, self.broad_flag = nonstat, bool(tone), bool(broad)
        self.m21 = self.m // 2 + 1
        self.hop = self.m - int(0.75 * self.m)
        # Source parameter block (alpha_s_ref etc. at 16 kHz).
        if self.fs != FS_REF:
            self.M = 2 ** int(round(math.log2(self.fs / FS_REF * M_REF)))
            self.Mo = MO_REF / M_REF * self.M
            ratio = M_REF / self.M * self.fs / FS_REF
            self.alpha_s, self.alpha_d = 0.9 ** ratio, 0.85 ** ratio
            self.alpha_eta, self.alpha_xi = 0.95 ** ratio, 0.7 ** ratio
        else:
            self.M, self.Mo = self.m, 0.75 * self.m
            self.alpha_s, self.alpha_d = 0.9, 0.85
            self.alpha_eta, self.alpha_xi = 0.95, 0.7
        self.alpha_d_long = 0.99
        self.w, self.Nwin, self.Vwin = 1, 8, 15
        self.delta_s, self.Bmin, self.delta_y, self.delta_yt = 1.67, 1.66, 4.6, 3
        self.w_xi_local, self.w_xi_global = 1, 15
        self.f_u, self.f_l, self.P_min = 10e3, 50.0, 0.005
        self.xi_lu_dB, self.xi_ll_dB = -5.0, -10.0
        self.xi_gu_dB, self.xi_gl_dB = -5.0, -10.0
        self.xi_fu_dB, self.xi_fl_dB = -5.0, -10.0
        self.xi_mu_dB, self.xi_ml_dB = 10.0, 0.0
        self.q_max = 0.998
        self.eta_min = 10.0 ** (-18.0 / 10.0)
        self.G_f = self.eta_min ** 0.5
        self.b = _hann(2 * self.w + 1)
        self.b = self.b / self.b.sum()
        self.b_xi_local = _hann(2 * self.w_xi_local + 1)
        self.b_xi_local = self.b_xi_local / self.b_xi_local.sum()
        self.b_xi_global = _hann(2 * self.w_xi_global + 1)
        self.b_xi_global = self.b_xi_global / self.b_xi_global.sum()
        self.k_u = min(int(round(self.f_u / self.fs * self.m + 1)), self.m21)
        self.k_l = int(round(self.f_l / self.fs * self.m + 1))
        self.k2_local = int(round(500.0 / self.fs * self.m + 1))
        self.k3_local = int(round(3500.0 / self.fs * self.m + 1))
        self.zero_thres = 1e-10
        self.reset()

    # ------------------------------------------------------------------ reset
    def reset(self) -> None:
        """Return to the source pre-loop state (section 1 of the schedule)."""
        n = self.m21
        self.l = 0                 # frames processed
        self.l_fnz = 1             # source 1-based first-nonzero counter
        self.fnz_flag = False
        self.l_mod_lswitch = 0
        self.eta_2term = 1.0
        self.xi = np.zeros(n)
        self.xi_frame = 0.0
        self.lambda_d = np.zeros(n)      # set on the first nonzero frame
        self.lambda_dav = np.zeros(n)
        self.lambda_dav_long = np.zeros(n)
        self.S = np.zeros(n)
        self.St = np.zeros(n)
        self.Smin = np.zeros(n)
        self.SMact = np.zeros(n)
        self.Smint = np.zeros(n)
        self.SMactt = np.zeros(n)
        self.SW = np.zeros((n, self.Nwin))
        self.SWt = np.zeros((n, self.Nwin))
        self.Sy = np.zeros(n)
        self.qhat = np.ones(n)
        self.phat = np.zeros(n)
        self.q = np.ones(n)
        self.PH1 = np.zeros(n)
        self.GH1 = np.ones(n)
        self.GH0 = np.ones(n) * self.G_f
        self.G = np.ones(n)
        self.gamma = np.zeros(n)
        self.eta = np.zeros(n)
        self.v = np.zeros(n)
        self.xi_local = np.zeros(n)
        self.xi_global = np.zeros(n)
        self.P_local = np.ones(n)
        self.P_global = np.ones(n)
        self.P_frame = self.P_min
        self.xi_m_dB = self.xi_ml_dB
        self.xi_frame_dB = -100.0
        self.dxi_frame = 0.0
        self.frame_presence = self.P_min
        self.mean_local = 0.0
        self.Sf = np.zeros(n)
        self.last_power = np.zeros(n)
        self.last_nonzero = False
        self.rollover = 0          # l_mod_lswitch value after last frame
        self.Y = np.zeros(self.m, dtype=complex)
        self.Ya2 = np.zeros(n)      # last analysed power frame

    # ------------------------------------------------------------- smoothing
    def _conv_same_shift(self, x: np.ndarray, k: np.ndarray, w: int) -> np.ndarray:
        """``c=conv(k,x); c(w+1:w+len(x))`` exactly as in omlsa.m."""
        c = np.convolve(k, np.asarray(x, dtype=float))
        return c[w:w + self.m21]

    @staticmethod
    def _dB(v):
        """Octave ``if vector>0`` semantics: all-positive -> elementwise dB,
        otherwise the scalar -100 branch, broadcast by the caller."""
        v = np.asarray(v, dtype=float)
        if v.ndim == 0 or v.size == 1:
            return float(10.0 * np.log10(v.reshape(-1)[0])) if v.reshape(-1)[0] > 0 else -100.0
        if np.all(v > 0):
            return 10.0 * np.log10(v)
        return -100.0

    def _pramp(self, db, lo: float, hi: float) -> np.ndarray:
        db = np.broadcast_to(np.asarray(db, dtype=float), (self.m21,))
        out = np.ones(self.m21)
        out[db <= lo] = self.P_min
        mid = (db > lo) & (db < hi)
        out[mid] = self.P_min + (db[mid] - lo) / (hi - lo) * (1.0 - self.P_min)
        return out

    # ------------------------------------------------------------------ step
    def step(self, power, active=None) -> np.ndarray:
        """Consume one 257-bin one-sided power frame; return the 257 gains."""
        if np.iscomplexobj(power):raise ValueError('real spectral power required')
        if active is not None and not isinstance(active,bool):raise ValueError('active must be bool or None')
        x = np.array(power, dtype=float, copy=True)
        if x.shape != (self.m21,):
            raise ValueError(f"power must have {self.m21} bins, got {x.shape}")
        if not np.all(np.isfinite(x)):
            raise ValueError("power must be finite")
        if np.any(x < 0.0):
            raise ValueError("power must be non-negative")
        self.last_power = x
        self.last_nonzero = bool(np.any(np.abs(x) > self.zero_thres))
        self.l += 1
        # Spectral callers may use the default power policy. Audio supplies
        # the original time-sample activation decision explicitly.
        enabled=(self.fnz_flag or np.any(np.abs(x)>self.zero_thres)) if active is None else active
        if not enabled:
            if not self.fnz_flag:self.l_fnz += 1  # source counts only pre-start silence
            self.rollover = self.l_mod_lswitch
            return self.G.copy()
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
               & (self.S < self.delta_s * self.Bmin * self.Smin)).astype(float)
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

        self.qhat = np.ones(n)
        self.phat = np.zeros(n)
        if self.nonstat == "low":
            gm = ya2 / self.Bmin / np.maximum(self.Smin, EPS)
            zt = self.S / self.Bmin / np.maximum(self.Smin, EPS)
        else:
            gm = ya2 / self.Bmin / np.maximum(self.Smint, EPS)
            zt = self.S / self.Bmin / np.maximum(self.Smint, EPS)
        idx = (gm > 1.0) & (gm < self.delta_yt) & (zt < self.delta_s)
        self.qhat[idx] = (self.delta_yt - gm[idx]) / (self.delta_yt - 1.0)
        den = 1.0 - self.qhat[idx]
        self.phat[idx] = 1.0 / (1.0 + self.qhat[idx] / den
                                * (1.0 + self.eta[idx]) * np.exp(-self.v[idx]))
        self.phat[(gm >= self.delta_yt) | (zt >= self.delta_s)] = 1.0
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
        self.xi_frame = float(np.mean(self.xi[self.k_l - 1:self.k_u]))
        self.dxi_frame = self.xi_frame - prev
        xl = self._dB(self.xi_local)
        xg = self._dB(self.xi_global)
        self.xi_frame_dB = float(self._dB(self.xi_frame))
        self.P_local = self._pramp(xl, self.xi_ll_dB, self.xi_lu_dB)
        self.P_global = self._pramp(xg, self.xi_gl_dB, self.xi_gu_dB)
        k2, k3 = self.k2_local, self.k3_local
        self.mean_local = float(np.mean(self.P_local[2:k2 + k3 - 3]))
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
            self.P_frame = 1.0
        elif xfd >= self.xi_m_dB + self.xi_fu_dB:
            self.P_frame = 1.0
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
        self.frame_presence = float(self.P_frame)

        # ---- gain stage (second gamma/eta/v evaluation)
        self.gamma = ya2 / np.maximum(self.lambda_d, EPS)
        self.eta = np.maximum(self.alpha_eta * self.eta_2term
                              + (1.0 - self.alpha_eta) * np.maximum(self.gamma - 1.0, 0.0),
                              self.eta_min)
        self.v = self.gamma * self.eta / (1.0 + self.eta)
        ph1 = np.zeros(n)
        idx = self.q < 0.9
        ph1[idx] = 1.0 / (1.0 + self.q[idx] / (1.0 - self.q[idx])
                          * (1.0 + self.eta[idx]) * np.exp(-self.v[idx]))
        self.PH1 = ph1
        gh1 = np.ones(n)
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
            self.GH0 = np.ones(n) * self.G_f
        self.G = self.GH1 ** self.PH1 * self.GH0 ** (1.0 - self.PH1)
        self.eta_2term = self.GH1 ** 2 * self.gamma
        return self.G.copy()

    # ------------------------------------------------------------ OLA output
    def process_audio(self, samples) -> np.ndarray:
        """Mono PCM16-normalised samples -> enhanced signal via source OLA.

        Analysis uses the source-normalised hamming window (hamming -> W0
        power correction -> Cwin), 512-point FFT, hop 128.  Synthesis keeps
        only bins 4..256 (1-based), zeroes bins 1..3 and Nyquist, mirrors the
        anti-symmetric half and overlap-adds ``Cwin**2*win*real(ifft(X))``.
        Output length equals the input length; samples past the last complete
        frame stay zero (the source writes exactly Nframes*Mno + M-Mno).
        """
        if np.iscomplexobj(samples):raise ValueError('real mono input required')
        y = np.asarray(samples, dtype=float)
        if y.ndim != 1:
            raise ValueError("process_audio expects mono input")
        if not np.all(np.isfinite(y)):
            raise ValueError("samples must be finite")
        win, cwin, mno = analyze_window(self.m)
        m, n = self.m, self.m21
        nframes = max(0, (y.size - int(self.Mo)) // mno)
        padded = np.concatenate((y, np.zeros(m)))
        out = np.zeros(padded.size, dtype=float)
        for l in range(nframes):
            start = l * mno
            buf = padded[start:start + m]
            spec = np.fft.fft(win * buf)
            active=((not self.fnz_flag and abs(buf[0])>self.zero_thres)
                    or (self.fnz_flag and np.any(abs(buf)>self.zero_thres)))
            gain = self.step(np.abs(spec[:n]) ** 2,active=bool(active))
            if not active:continue
            xspec = np.zeros(m, dtype=complex)
            xspec[3:n - 1] = gain[3:n - 1] * spec[3:n - 1]
            xspec[n:m] = np.conj(xspec[n - 2:0:-1])
            out[start:start + m] += cwin ** 2 * win * np.real(np.fft.ifft(xspec))
        return out[:y.size]

    def fields(self) -> dict:
        """Snapshot of every source-visible intermediate (post-last-frame)."""
        out = {k: np.array(getattr(self, k), copy=True) for k in FIELD_NAMES}
        out["frame"] = float(self.l)
        out["l_fnz"] = float(self.l_fnz)
        for k in SCALAR_FIELDS:
            if k != "frame":
                out[k] = float(getattr(self, k))
        out["first_nonzero"] = float(self.l_fnz)
        return out


def analyze_window(m: int = M_REF):
    """Source window normalisation: hamming, W0 power correction, Cwin."""
    win = _hamming(m)
    win2 = win ** 2
    mno = m - int(0.75 * m)
    w0 = win2[:mno].copy()
    for k in range(mno, m, mno):
        w0 = w0 + _lnshift(win2, k)[:mno]
    w0 = np.mean(w0) ** 0.5
    win = win / w0
    cwin = np.sum(win ** 2) ** 0.5
    return win / cwin, float(cwin), int(mno)


_DEFAULT: "IMCRA | None" = None


def default_tracker() -> "IMCRA":
    """Process-wide default tracker used by the module-level ``step``."""
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = IMCRA()
    return _DEFAULT


def step(power) -> np.ndarray:
    """Module-level convenience wrapper on the default tracker."""
    return default_tracker().step(power)
