"""Independent radar models: chirps, echoes, pulse compression, MTI/Doppler, CA-CFAR.

The fixed-point paths use integer arithmetic where the contract asks for a fixed model;
they are models, not a bit-exact RTL pipeline.  No physical range or maximum-frequency
claim is made.  ``fft_fixed`` is the local read-only FFT reference.
"""
from __future__ import annotations

import math
from numbers import Integral, Real

import numpy as np

try:  # imported as common.python.ext_advanced_radar or with common/python on sys.path
    from . import fft_fixed
except ImportError:  # pragma: no cover - exercised by the direct-script/test layout
    import fft_fixed

Q17 = 1 << 17
Q16 = 1 << 16
MASK32 = (1 << 32) - 1
S18_MIN, S18_MAX = -(1 << 17), (1 << 17) - 1


def _is_int(value):
    return isinstance(value, Integral) and not isinstance(value, bool)


def _as_int(value, name):
    if not _is_int(value):
        raise ValueError(f'{name} must be an integer')
    return int(value)


def _finite(value, name):
    if not isinstance(value, Real) or isinstance(value, bool) or not math.isfinite(float(value)):
        raise ValueError(f'{name} must be finite')
    return float(value)


def _round_half_up(value):
    """Round to nearest integer; exact ties go towards +infinity."""
    return int(math.floor(value + 0.5))


def _round_div_half_up(numerator, denominator):
    if denominator <= 0:
        raise ValueError('rounding denominator must be positive')
    return (2 * numerator + denominator) // (2 * denominator)


def _sat(value, width=18):
    lo, hi = -(1 << (width - 1)), (1 << (width - 1)) - 1
    return max(lo, min(hi, int(value)))


def _wrap32(value):
    value &= MASK32
    return value - (1 << 32) if value & (1 << 31) else value


def _pairs(value, name):
    arr = np.asarray(value)
    if arr.ndim != 1 or arr.shape[0] == 0:
        raise ValueError(f'{name} must be a nonempty one-dimensional complex sequence')
    if arr.dtype == bool:
        raise ValueError(f'{name} must not contain booleans')
    try:
        arr = arr.astype(np.complex128, copy=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be complex numeric') from exc
    if not np.all(np.isfinite(arr)):
        raise ValueError(f'{name} components must be finite')
    return arr


def _seq(values, name, n=None):
    try:
        out = list(values)
    except TypeError as exc:
        raise ValueError(f'{name} must be a sequence') from exc
    if n is not None and len(out) != n:
        raise ValueError(f'{name} must have the same length as delays')
    return out


def chirp(n, fs, f0, slope, amplitude=1.0, phase=0.0):
    """Complex LFM samples exp(j*(phase + 2*pi*(f0*t + slope*t*t/2)))."""
    n = _as_int(n, 'n')
    if not 1 <= n <= 4096:
        raise ValueError('n must be an integer in 1..4096')
    fs = _finite(fs, 'fs')
    f0, slope = _finite(f0, 'f0'), _finite(slope, 'slope')
    amplitude, phase = _finite(amplitude, 'amplitude'), _finite(phase, 'phase')
    if fs <= 0:
        raise ValueError('fs must be positive')
    if not 0 <= amplitude <= 1:
        raise ValueError('amplitude must lie in 0..1')
    t = np.arange(n, dtype=np.float64) / fs
    inst = f0 + slope * t
    if np.any(inst <= -fs / 2) or np.any(inst >= fs / 2):
        raise ValueError('f0 + slope*t must stay strictly inside (-fs/2, fs/2)')
    return amplitude * np.exp(1j * (phase + 2 * np.pi * (f0 * t + 0.5 * slope * t * t)))


def _chirp_parameters(n, fs, f0, slope, amplitude, phase, lut_bits):
    # Reuse the float model's exact validation, but do not use its samples.
    chirp(n, fs, f0, slope, amplitude, phase)
    lut_bits = _as_int(lut_bits, 'lut_bits')
    if not 2 <= lut_bits <= 20:
        raise ValueError('lut_bits must be an integer in 2..20')
    step = _round_half_up((f0 / fs + slope / (2 * fs * fs)) * (1 << 32))
    delta = _round_half_up(slope / (fs * fs) * (1 << 32))
    initial = _round_half_up(phase / (2 * math.pi) * (1 << 32))
    for value, name in ((step, 'initial phase step'), (delta, 'phase increment delta')):
        if not -(1 << 31) <= value <= (1 << 31) - 1:
            raise ValueError(f'{name} does not fit a signed 32-bit accumulator')
    return n, int(initial) & MASK32, step, delta, _round_half_up(amplitude * Q17), lut_bits


def _q17_lut(bits):
    size = 1 << bits
    re, im = [], []
    for k in range(size):
        angle = 2 * math.pi * k / size
        re.append(_sat(_round_half_up(math.cos(angle) * Q17)))
        im.append(_sat(_round_half_up(math.sin(angle) * Q17)))
    return re, im


def _q17_mul(a, b, shift=17):
    return _sat(_round_div_half_up(a * b, 1 << shift))


_ECHO_LUT = None


def _echo_lut():
    global _ECHO_LUT
    if _ECHO_LUT is None:
        _ECHO_LUT = _q17_lut(17)
    return _ECHO_LUT


def chirp_fixed(n, fs, f0, slope, amplitude=1.0, phase=0.0, lut_bits=12):
    """Signed-18 Q17 complex chirp from full 32-bit phase/step accumulators."""
    n, acc, step, delta, amp_q, lut_bits = _chirp_parameters(
        n, fs, f0, slope, amplitude, phase, lut_bits)
    re_lut, im_lut = _q17_lut(lut_bits)
    shift = 32 - lut_bits
    out = []
    for _ in range(n):
        index = (acc & MASK32) >> shift
        out.append((_q17_mul(amp_q, re_lut[index]), _q17_mul(amp_q, im_lut[index])))
        acc = (acc + step) & MASK32
        step = _wrap32(step + delta)
    return out


def _target_lists(delays, gains, dopplers=None):
    delays = _seq(delays, 'delays')
    gains = _seq(gains, 'gains', len(delays))
    if dopplers is None:
        dopplers = [0.0] * len(delays)
    dopplers = _seq(dopplers, 'dopplers', len(delays))
    out = []
    for delay, gain, dop in zip(delays, gains, dopplers):
        delay = _as_int(delay, 'delay')
        if delay < 0:
            raise ValueError('delays must be nonnegative')
        try:
            gain = complex(gain)
        except (TypeError, ValueError) as exc:
            raise ValueError('gains must be complex numeric') from exc
        if not (math.isfinite(gain.real) and math.isfinite(gain.imag)):
            raise ValueError('gains must be finite')
        dop = _finite(dop, 'doppler')
        if not -0.5 <= dop < 0.5:
            raise ValueError('dopplers must lie in [-0.5, 0.5)')
        out.append((delay, gain, dop))
    return out


def _output_length(length, wave_len, targets):
    if length is None:
        return wave_len + (max((d for d, _, _ in targets), default=0))
    length = _as_int(length, 'length')
    if length < 0:
        raise ValueError('length must be nonnegative')
    return length


def echo(waveform, delays, gains, dopplers, length=None):
    """Sum gain*s[n-delay]*exp(j*2*pi*doppler*n) at absolute output time n."""
    wave = _pairs(waveform, 'waveform')
    targets = _target_lists(delays, gains, dopplers)
    length = _output_length(length, len(wave), targets)
    result = np.zeros(length, dtype=np.complex128)
    n_all = np.arange(length)
    for delay, gain, dop in targets:
        if delay < length:
            count = min(length - delay, len(wave))
            result[delay:delay + count] += (gain * wave[:count]
                                            * np.exp(2j * np.pi * dop * n_all[delay:delay + count]))
    return result


def _integer_pairs(value, name):
    try:
        arr = np.asarray(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be IQ integer pairs') from exc
    if arr.ndim != 2 or arr.shape[1] != 2:
        raise ValueError(f'{name} must have shape (samples, 2)')
    rows = []
    for row in arr:
        pair = []
        for component in row:
            if not _is_int(component):
                raise ValueError(f'{name} components must be integers')
            component = int(component)
            if not S18_MIN <= component <= S18_MAX:
                raise ValueError(f'{name} components must fit signed 18 bits')
            pair.append(component)
        rows.append(tuple(pair))
    return rows


def echo_fixed(waveform_iq, delays, gains_iq, doppler_steps, length=None):
    """Integer Q17 echo; doppler_steps are Q17 cycles per output sample."""
    wave = _integer_pairs(waveform_iq, 'waveform_iq')
    delays = _seq(delays, 'delays')
    gains = _integer_pairs(gains_iq, 'gains_iq')
    steps = _seq(doppler_steps, 'doppler_steps', len(delays))
    if len(gains) != len(delays):
        raise ValueError('gains_iq must have the same length as delays')
    targets = []
    for delay, gain, step in zip(delays, gains, steps):
        delay = _as_int(delay, 'delay')
        step = _as_int(step, 'doppler_step')
        if delay < 0:
            raise ValueError('delays must be nonnegative')
        if not -65536 <= step <= 65535:
            raise ValueError('doppler_steps must be Q17 cycles in [-0.5, 0.5)')
        targets.append((delay, gain, step))
    n_out = _output_length(length, len(wave), [(d, None, None) for d, _, _ in targets])
    re_lut, im_lut = _echo_lut()
    phase_mask = Q17 - 1
    out = []
    for n in range(n_out):
        acc_re = acc_im = 0
        for delay, gain, step in targets:
            if n < delay or n - delay >= len(wave):
                continue
            index = (n * step) & phase_mask
            wr, wi = wave[n - delay]
            gr, gi = gain
            base_re = wr * gr - wi * gi
            base_im = wr * gi + wi * gr
            acc_re += base_re * re_lut[index] - base_im * im_lut[index]
            acc_im += base_re * im_lut[index] + base_im * re_lut[index]
        # wave/gain are Q17, the NCO is Q17: Q34 * Q17 / 2^34 -> Q17 output.
        out.append((_sat(_round_div_half_up(acc_re, 1 << 34)),
                    _sat(_round_div_half_up(acc_im, 1 << 34))))
    return out


def _complex_1d(value, name, allow_empty=False):
    arr = np.asarray(value)
    if arr.ndim != 1 or (arr.size == 0 and not allow_empty):
        raise ValueError(f'{name} must be a nonempty one-dimensional complex sequence')
    if arr.dtype == bool:
        raise ValueError(f'{name} must not contain booleans')
    try:
        arr = arr.astype(np.complex128, copy=False)
    except (TypeError, ValueError) as exc:
        raise ValueError(f'{name} must be complex numeric') from exc
    if not np.all(np.isfinite(arr)):
        raise ValueError(f'{name} components must be finite')
    return arr


def pulse_compress(x, reference, method='direct', normalize=True):
    """Full linear matched correlation, with optional reference-energy normalization."""
    x = _complex_1d(x, 'x', allow_empty=True)
    ref = _pairs(reference, 'reference')
    if method not in ('direct', 'fft'):
        raise ValueError("method must be 'direct' or 'fft'")
    energy = float(np.sum(np.abs(ref) ** 2))
    if energy == 0:
        raise ValueError('reference must have nonzero energy')
    if x.size == 0:
        return np.array([], dtype=np.complex128)
    h = np.conj(ref[::-1])
    if method == 'direct':
        y = np.convolve(x, h, mode='full')
    else:
        try:from .ext_signal_spectral import FFTConvolver
        except ImportError:from ext_signal_spectral import FFTConvolver
        nfft=1 << max(1,(2*len(ref)-1).bit_length())
        convolver=FFTConvolver(h,nfft)
        y=np.asarray(list(convolver.push(x))+list(convolver.flush()),complex)
    return y / energy if normalize else y


def pulse_compress_fixed(xiq, refiq, normalize=True):
    """Exact integer full convolution; Q17 output with one final rounding/saturation."""
    xarr = np.asarray(xiq)
    if xarr.size == 0 and xarr.ndim == 1:
        x = []
    elif xarr.ndim == 2 and xarr.shape[1] == 2:
        x = _integer_pairs(xiq, 'xiq') if xarr.size else []
    else:
        raise ValueError('xiq must have shape (samples, 2)')
    ref = _integer_pairs(refiq, 'refiq')
    energy = sum(re * re + im * im for re, im in ref)
    if energy == 0:
        raise ValueError('reference must have nonzero integer energy')
    # Conjugating -131072 gives +131072, deliberately outside signed 18 bits.
    h = [(re, -im) for re, im in reversed(ref)]
    if not x:
        return []
    out = []
    for k in range(len(x) + len(ref) - 1):
        rr = ri = 0
        lo, hi = max(0, k - len(h) + 1), min(len(x) - 1, k)
        for i in range(lo, hi + 1):
            j = k - i
            xr, xi = x[i]
            hr, hi_ = h[j]
            rr += xr * hr - xi * hi_
            ri += xr * hi_ + xi * hr
        if normalize:
            re, im = _round_div_half_up(rr * Q17, energy), _round_div_half_up(ri * Q17, energy)
        else:
            re, im = _round_div_half_up(rr, Q17), _round_div_half_up(ri, Q17)
        out.append((_sat(re), _sat(im)))
    return out


def _range_doppler_parameters(data, pri, mti, window):
    arr = np.asarray(data)
    if arr.ndim != 2 or arr.shape[1] not in (16, 32, 64):
        raise ValueError('data must have shape (range, pulse) with 16, 32 or 64 pulses')
    pri = _finite(pri, 'pri')
    if pri <= 0:
        raise ValueError('pri must be positive')
    mti = _as_int(mti, 'mti')
    if mti not in (0, 1, 2):
        raise ValueError('mti must be 0, 1 or 2')
    if window not in ('hamming', 'rectangular', 'rect', 'none', 'ones'):
        raise ValueError("window must be 'hamming' or rectangular")
    if mti >= arr.shape[1]:
        raise ValueError('mti order must be smaller than the pulse count')
    return arr, pri, mti, window


def range_doppler(data, pri, mti=0, window='hamming'):
    """Windowed slow-time FFT after an n-th order difference along pulses."""
    arr, pri, mti, window = _range_doppler_parameters(data, pri, mti, window)
    try:
        arr = arr.astype(np.complex128, copy=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('data must be numeric') from exc
    if not np.all(np.isfinite(arr)):
        raise ValueError('data must be finite')
    npulse = arr.shape[1]
    valid = np.diff(arr, n=mti, axis=1) if mti else arr
    nvalid = valid.shape[1]
    coeff = np.hamming(nvalid) if window == 'hamming' else np.ones(nvalid)
    padded = np.zeros((arr.shape[0], npulse), dtype=np.complex128)
    padded[:, :nvalid] = valid * coeff
    spectrum = np.fft.fftshift(np.fft.fft(padded, axis=1) / npulse, axes=1)
    frequencies = np.fft.fftshift(np.fft.fftfreq(npulse, pri))
    return spectrum, frequencies


def range_doppler_fixed(iqdata, pri, mti=0, window='hamming'):
    """Integer MTI/window/FFT path, returning signed-24 Q17 IQ pairs."""
    arr = np.asarray(iqdata)
    if arr.ndim != 3 or arr.shape[2] != 2 or arr.shape[1] not in (16, 32, 64):
        raise ValueError('iqdata must have shape (range, pulse, 2) with 16/32/64 pulses')
    arr, pri, mti, window = _range_doppler_parameters(arr[:, :, 0], pri, mti, window)
    iq = []
    for row in np.asarray(iqdata):
        pair_row = []
        for pair in row:
            if len(pair) != 2 or not all(_is_int(v) for v in pair):
                raise ValueError('iqdata components must be integers')
            r, i = int(pair[0]), int(pair[1])
            if not S18_MIN <= r <= S18_MAX or not S18_MIN <= i <= S18_MAX:
                raise ValueError('iqdata components must fit signed 18 bits')
            pair_row.append((r, i))
        iq.append(pair_row)
    npulse = arr.shape[1]
    rows = arr.shape[0]
    nvalid = npulse - mti
    coeff = np.hamming(nvalid) if window == 'hamming' else np.ones(nvalid)
    coeff_q = np.array([_round_half_up(float(c) * Q16) for c in coeff], dtype=object)
    result = np.zeros((rows, npulse, 2), dtype=np.int64)
    frequencies = np.fft.fftshift(np.fft.fftfreq(npulse, pri))
    for r in range(rows):
        differences = iq[r][:]
        for _ in range(mti):
            differences = [(a[0] - b[0], a[1] - b[1])
                           for a, b in zip(differences[1:], differences[:-1])]
        fft_input = []
        for t in range(npulse):
            if t < nvalid:
                rr, ri = differences[t]
                rr = _round_div_half_up(rr * int(coeff_q[t]), Q16)
                ri = _round_div_half_up(ri * int(coeff_q[t]), Q16)
            else:
                rr = ri = 0
            fft_input.append((rr, ri))
        transformed = np.asarray(fft_fixed.forward(fft_input, in_width=20, width=24))
        transformed = np.concatenate((transformed[npulse // 2:], transformed[:npulse // 2]))
        result[r, :, 0] = [v[0] for v in transformed]
        result[r, :, 1] = [v[1] for v in transformed]
    return result, frequencies


def _cfar_parameters(training, guard, pfa):
    training = _as_int(training, 'training')
    guard = _as_int(guard, 'guard')
    pfa = _finite(pfa, 'pfa')
    if training < 2 or training > 64 or training % 2:
        raise ValueError('training must be an even integer in 2..64')
    if not 0 <= guard <= 8:
        raise ValueError('guard must be an integer in 0..8')
    if not 0 < pfa < 1:
        raise ValueError('pfa must lie strictly between 0 and 1')
    return training, guard, pfa


def _cfar_alpha(training, pfa):
    return training * math.expm1(-math.log(pfa) / training)


def ca_cfar(power, training=16, guard=2, pfa=1e-3):
    """Cell-averaging CFAR on the last axis; edges are invalid."""
    training, guard, pfa = _cfar_parameters(training, guard, pfa)
    power = np.asarray(power)
    if power.ndim < 1:
        raise ValueError('power must have at least one dimension')
    if np.iscomplexobj(power):
        raise ValueError('power must be real')
    if power.dtype == bool:
        raise ValueError('power must not contain booleans')
    try:
        power = power.astype(np.float64, copy=False)
    except (TypeError, ValueError) as exc:
        raise ValueError('power must be numeric') from exc
    if np.any(~np.isfinite(power)) or np.any(power < 0):
        raise ValueError('power must be finite and nonnegative')
    detections = np.zeros(power.shape, dtype=bool)
    threshold = np.full(power.shape, np.nan, dtype=np.float64)
    valid = np.zeros(power.shape, dtype=bool)
    n = power.shape[-1]
    half = training // 2
    edge = half + guard
    if n <= 2 * edge:
        return detections, threshold, valid
    alpha = _cfar_alpha(training, pfa)
    # Vectorize independent leading windows; last-axis support remains explicit.
    prefix = np.concatenate((np.zeros(power.shape[:-1]+(1,)), np.cumsum(power,axis=-1)),axis=-1)
    cuts = np.arange(edge,n-edge)
    left=prefix[...,cuts-guard]-prefix[...,cuts-guard-half]
    right=prefix[...,cuts+guard+1+half]-prefix[...,cuts+guard+1]
    threshold[...,cuts]=alpha*(left+right)/training
    valid[...,cuts]=True
    detections[...,cuts]=power[...,cuts]>threshold[...,cuts]
    return detections, threshold, valid


def _alpha_q(training, pfa, frac):
    return _round_half_up(_cfar_alpha(training, pfa) * (1 << frac))


def ca_cfar_fixed(power_integer, training=16, guard=2, pfa=1e-3, alpha_frac=20):
    """Integer CA-CFAR; comparisons use Python integers and one quantized alpha."""
    training, guard, pfa = _cfar_parameters(training, guard, pfa)
    alpha_frac = _as_int(alpha_frac, 'alpha_frac')
    if not 0 <= alpha_frac <= 60:
        raise ValueError('alpha_frac must be an integer in 0..60')
    values = np.asarray(power_integer)
    if values.ndim < 1:
        raise ValueError('power_integer must have at least one dimension')
    flat_values = []
    for value in values.reshape(-1):
        if not _is_int(value):
            raise ValueError('power_integer must contain integers (not bools/floats)')
        value = int(value)
        if value < 0:
            raise ValueError('power_integer must be nonnegative')
        flat_values.append(value)
    flat_values = np.array(flat_values, dtype=object).reshape(values.shape)
    detections = np.zeros(values.shape, dtype=bool)
    threshold = np.zeros(values.shape, dtype=object)
    valid = np.zeros(values.shape, dtype=bool)
    n = values.shape[-1]
    half = training // 2
    edge = half + guard
    if n == 0 or n <= 2 * edge:
        return detections, threshold, valid
    alpha_q = _alpha_q(training, pfa, alpha_frac)
    den = training * (1 << alpha_frac)
    flat = flat_values.reshape(-1, n)
    dflat = detections.reshape(-1, n)
    tflat = threshold.reshape(-1, n)
    vflat = valid.reshape(-1, n)
    for row in range(flat.shape[0]):
        prefix = [0]
        for value in flat[row]:
            prefix.append(prefix[-1] + int(value))
        for cut in range(edge, n - edge):
            left = prefix[cut - guard] - prefix[cut - guard - half]
            right = prefix[cut + guard + 1 + half] - prefix[cut + guard + 1]
            training_sum = left + right
            vflat[row, cut] = True
            dflat[row, cut] = int(flat[row, cut]) * training * (1 << alpha_frac) > alpha_q * training_sum
            tflat[row, cut] = -((-alpha_q * training_sum) // den)
    return detections, threshold, valid
