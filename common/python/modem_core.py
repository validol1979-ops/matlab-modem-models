"""Переносимые модели модемов и явные границы обработки сигнала."""
from pathlib import Path
import json
import math
import numpy as np


def validate_config(cfg):
    try:
        order,sps=cfg['order'],cfg['sps']
        if order not in (2,4,8,16,64) or not isinstance(sps,int) or sps<2:
            raise ValueError('Invalid modem configuration')
        if cfg['family'] not in ('psk','qam','pi4','msk','gmsk','oqpsk') or cfg['differential'] not in ('none','psk','quadrant','pi4') or cfg['carrier'] not in ('feedforward','feedback','costas') or cfg['timing'] not in ('feedforward','gardner') or cfg['equalizer'] not in ('none','linear','dfe'):
            raise ValueError('Invalid modem configuration')
        if (cfg['differential']=='quadrant' and order%4) or (cfg['differential']=='pi4' and order!=4) or (cfg['family'] in ('msk','gmsk') and order!=2) or (cfg['family']=='oqpsk' and (order!=4 or sps%2)):
            raise ValueError('Invalid modem configuration')
        table=np.asarray(cfg['constellation'],float)
        if table.shape!=(8 if cfg['differential']=='pi4' else order,2) or not np.all(np.isfinite(table)):
            raise ValueError('Invalid modem constellation')
        if cfg['family'] not in ('msk','gmsk'):
            length,beta=cfg['rrc_order'],cfg['rolloff']
            if not isinstance(length,int) or length<=0 or length%2 or not np.isfinite(beta) or not 0<=beta<=1:
                raise ValueError('Invalid modem filter')
        if cfg['family']=='gmsk' and (not np.isfinite(cfg['gaussian_bt']) or cfg['gaussian_bt']<=0):
            raise ValueError('Invalid modem filter')
    except (KeyError,TypeError) as error:
        raise ValueError('Invalid modem configuration') from error
    return cfg


def load_config(path):
    return validate_config(json.loads(Path(path).read_text()))


def constellation(cfg):
    a = np.asarray(cfg['constellation'], dtype=float)
    return a[:, 0] + 1j * a[:, 1]


def checked_data(cfg, data):
    validate_config(cfg)
    a = np.asarray(data)
    if a.ndim != 1 or a.size == 0 or not np.all(np.isfinite(a)):
        raise ValueError('Data must be a nonempty finite one-dimensional array')
    if np.any(a != np.floor(a)) or np.any(a < 0) or np.any(a >= cfg['order']):
        raise ValueError('Symbol index is outside the configured alphabet')
    return a.astype(np.int64)


def gray_inverse(value):
    result = int(value)
    value = result >> 1
    while value:
        result ^= value
        value >>= 1
    return result


def encode(cfg, data):
    data = checked_data(cfg, data)
    state, ids = 0, []
    for value in data:
        value = int(value)
        mode = cfg['differential']
        if mode == 'psk':
            state = (state + (value ^ (value >> 1))) % cfg['order']
            index = state
        elif mode == 'quadrant':
            group = cfg['order'] // 4
            q = value // group
            state = (state + (q ^ (q >> 1))) % 4
            index = group * state + value % group
        elif mode == 'pi4':
            state = (state + 2 * (value ^ (value >> 1)) + 1) % 8
            index = state
        else:
            index = value
        ids.append(index)
    ids = np.asarray(ids, dtype=int)
    return ids, constellation(cfg)[ids]


def decode(cfg, ids):
    state, result = 0, []
    for index in ids:
        index = int(index)
        mode = cfg['differential']
        if mode == 'psk':
            value = gray_inverse((index - state) % cfg['order'])
            state = index
        elif mode == 'quadrant':
            group = cfg['order'] // 4
            q = index // group
            value = group * gray_inverse((q - state) % 4) + index % group
            state = q
        elif mode == 'pi4':
            delta = (index - state) % 8
            value = gray_inverse(((delta - 1) % 8) // 2)
            state = index
        else:
            value = index
        result.append(value)
    return np.asarray(result, dtype=int)


def slice_symbols(cfg, samples):
    table = constellation(cfg)
    return np.argmin(abs(np.asarray(samples)[:, None] - table[None, :]) ** 2, axis=1)


def rrc_taps(sps, order, beta):
    if order <= 0 or order % 2 or not 0 <= beta <= 1 or sps < 2:
        raise ValueError('Invalid root raised cosine filter parameters')
    t = np.arange(-order // 2, order // 2 + 1, dtype=float) / sps
    h = np.empty_like(t)
    for k, x in enumerate(t):
        if abs(x) < 1e-12:
            h[k] = 1 + beta * (4 / np.pi - 1)
        elif beta and abs(abs(4 * beta * x) - 1) < 1e-10:
            h[k] = beta / np.sqrt(2) * ((1 + 2 / np.pi) * np.sin(np.pi / (4 * beta))
                                      + (1 - 2 / np.pi) * np.cos(np.pi / (4 * beta)))
        else:
            h[k] = (np.sin(np.pi * x * (1 - beta)) + 4 * beta * x * np.cos(np.pi * x * (1 + beta))) / (np.pi * x * (1 - (4 * beta * x) ** 2))
    return h / np.linalg.norm(h)


def gaussian_taps(sps, bt):
    if sps < 2 or bt <= 0:
        raise ValueError('Invalid Gaussian filter parameters')
    t = np.arange(-2 * sps, 2 * sps + 1) / sps
    h = np.exp(-2 * (np.pi * bt * t) ** 2 / np.log(2))
    return h / h.sum()


def cubic(samples, positions):
    # Интерполяция Лагранжа через четыре соседних отсчёта, вне кадра — нули.
    samples, positions = np.asarray(samples), np.asarray(positions, dtype=float)
    base = np.floor(positions).astype(int)
    mu = positions - base
    weights = [-mu * (mu - 1) * (mu - 2) / 6,
               (mu + 1) * (mu - 1) * (mu - 2) / 2,
               -(mu + 1) * mu * (mu - 2) / 2,
               (mu + 1) * mu * (mu - 1) / 6]
    output = np.zeros(positions.shape, dtype=complex)
    for shift, weight in zip((-1, 0, 1, 2), weights):
        ids = base + shift
        valid = (ids >= 0) & (ids < len(samples))
        output += weight * np.where(valid, samples[np.clip(ids, 0, len(samples) - 1)], 0)
    return output


def transmit(cfg, data):
    data = checked_data(cfg, data)
    ids, symbols = encode(cfg, data)
    sps = cfg['sps']
    if cfg['family'] in ('msk', 'gmsk'):
        frequency = np.repeat(2 * data - 1, sps).astype(float)
        if cfg['family'] == 'gmsk':
            frequency = np.convolve(frequency, gaussian_taps(sps, cfg['gaussian_bt']))
        waveform = np.exp(1j * np.cumsum(frequency) * np.pi / (2 * sps))
    else:
        upsampled = np.zeros(len(data) * sps, dtype=complex)
        upsampled[::sps] = symbols
        if cfg['family'] == 'oqpsk':
            # В OQPSK квадратурная ветвь задержана на половину символа.
            half = sps // 2
            upsampled = np.pad(upsampled.real, (0, half)) + 1j * np.pad(upsampled.imag, (half, 0))
        waveform = np.convolve(upsampled, rrc_taps(sps, cfg['rrc_order'], cfg['rolloff']))
    return dict(data=data, indices=ids, symbols=symbols, waveform=waveform)


def channel(cfg, waveform, *, snr_db=math.inf, gain=1.0, phase=0.0,
            frequency=0.0, delay=0.0, drift=0.0, phase_noise=0.0,
            echo=0.0, seed=7):
    if gain <= 0 or delay < 0 or abs(drift) >= 0.01:
        raise ValueError('Invalid channel parameters')
    rng = np.random.default_rng(seed)
    wave = np.asarray(waveform, complex)
    if echo:
        taps = np.zeros(cfg['sps'] + 1, complex)
        taps[0], taps[-1] = 1, echo
        wave = np.convolve(wave, taps)
    count = len(wave) + int(math.ceil(delay + abs(drift) * len(wave))) + 4
    n = np.arange(count)
    shifted = cubic(wave, n * (1 - drift) - delay)
    pn = np.cumsum(rng.normal(0, phase_noise, count))
    clean = gain * shifted * np.exp(1j * (phase + 2 * np.pi * frequency * n + pn))
    variance = 0 if np.isinf(snr_db) else float(np.mean(abs(clean) ** 2) / 10 ** (snr_db / 10))
    return clean + np.sqrt(variance / 2) * (rng.normal(size=count) + 1j * rng.normal(size=count))


def fit_carrier(samples, reference):
    # Оценка наклона фазы использует только известную преамбулу.
    samples=np.asarray(samples,complex); reference=np.asarray(reference,complex)
    if samples.shape!=reference.shape or reference.ndim!=1 or len(reference)<2 or not np.all(np.isfinite(np.r_[samples,reference])) or np.any(abs(reference)<1e-12):
        raise ValueError('Carrier fit requires finite samples and a nonzero reference')
    n = np.arange(len(reference), dtype=float)
    ratio = samples / reference
    p = np.unwrap(np.angle(ratio))
    centered = n - n.mean()
    slope = float(np.dot(centered, p - p.mean()) / np.dot(centered, centered))
    h = np.vdot(reference, samples * np.exp(-1j * slope * n)) / np.vdot(reference, reference)
    if not np.isfinite(h) or abs(h)<1e-12: raise ValueError('Carrier fit has zero or nonfinite gain')
    corrected = samples * np.exp(-1j * slope * n) / h
    error = float(np.mean(abs(corrected - reference) ** 2))
    return slope, h, error


def symbol_receiver(cfg, samples, training, *, track_carrier=True):
    # Контуры работают после грубой оценки времени, частоты и усиления.
    table = constellation(cfg)
    out = np.empty(len(samples), complex)
    decisions = np.empty(len(samples), int)
    phase, freq, gain = 0.0, 0.0, 1.0
    mode = cfg['equalizer']
    taps = np.zeros(7, complex)
    taps[0] = 1
    feedback = np.zeros(3, complex)
    history = np.zeros(7, complex)
    past = np.zeros(3, complex)
    for k, sample in enumerate(samples):
        corrected = sample * np.exp(-1j * phase) * gain
        history[1:] = history[:-1]
        history[0] = corrected
        value = np.dot(taps, history) if mode != 'none' else corrected
        if mode == 'dfe': value += np.dot(feedback, past)
        index = int(np.argmin(abs(table - value) ** 2))
        target = training[k] if k < len(training) else table[index]
        error = target - value
        if mode != 'none':
            power = float(np.vdot(history, history).real + (np.vdot(past, past).real if mode == 'dfe' else 0) + 1e-9)
            step = 0.3 if k < len(training) else 0.02
            taps += step * error * history.conj() / power
            if mode == 'dfe': feedback += step * error * past.conj() / power
        past[1:] = past[:-1]
        past[0] = target
        pe = float(np.clip(np.imag(value * target.conjugate()) / max(abs(target) ** 2, 1e-12), -0.5, 0.5))
        if cfg['carrier'] == 'costas' and cfg['order'] == 2:
            pe = float(np.clip(np.imag(value / table[0]) * np.sign(np.real(value / table[0])), -0.5, 0.5))
        if not track_carrier:
            pe=0.0
        if cfg['carrier'] == 'feedforward':
            phase += 0.03 * pe
        else:
            freq += 0.0002 * pe
            phase += freq + 0.04 * pe
        gain *= 1 + 0.002 * float(np.clip(np.real(error * value.conjugate()) / max(abs(target) ** 2, 1e-12), -0.5, 0.5))
        out[k], decisions[k] = value, index
    return dict(symbols=out, indices=decisions, data=decode(cfg, decisions))


def receive(cfg, waveform, preamble, count):
    preamble = checked_data(cfg, preamble)
    if len(preamble) < 32 or count < len(preamble):
        raise ValueError('At least 32 training symbols and a valid frame length are required')
    wave = np.asarray(waveform, complex)
    if wave.ndim != 1 or len(wave) < count * cfg['sps'] or not np.all(np.isfinite(wave)):
        raise ValueError('Invalid or truncated receive waveform')
    if cfg['family'] in ('msk', 'gmsk'):
        return receive_cpm(cfg, wave, preamble, count)
    if cfg['family'] == 'oqpsk':
        return receive_oqpsk(cfg, wave, preamble, count)
    h = rrc_taps(cfg['sps'], cfg['rrc_order'], cfg['rolloff'])
    filtered = np.convolve(wave, h)
    train = encode(cfg, preamble)[1]
    usable = len(train) - 4
    train = train[:usable]
    n = np.arange(usable)
    best = None
    for delay in np.arange(0, 2 * cfg['sps'] + 0.125, 0.25):
        y = cubic(filtered, cfg['rrc_order'] + delay + cfg['sps'] * n)
        slope, gain, error = fit_carrier(y, train)
        if best is None or error < best[0]: best = error, delay, slope, gain
    _, delay, slope, gain = best
    positions = cfg['rrc_order'] + delay + cfg['sps'] * np.arange(count)
    # Gardner подстраивает момент выборки только при наличии соответствующего контура.
    if cfg['timing'] == 'gardner':
        correction = 0.0
        for k in range(count):
            p = positions[k] + correction
            early, mid, late = cubic(filtered, [p - cfg['sps'] / 2, p, p + cfg['sps'] / 2])
            error = np.real((late - early) * mid.conjugate()) / max(abs(gain) ** 2 * np.mean(abs(train) ** 2), 1e-9)
            positions[k] = p
            correction += 0.015 * float(np.clip(error, -1, 1))
    y = cubic(filtered, positions) * np.exp(-1j * slope * np.arange(count)) / gain
    result = symbol_receiver(cfg, y, train)
    result.update(delay=delay, frequency=slope / (2 * np.pi * cfg['sps']), gain=abs(gain), synchronized=y)
    return result


def receive_oqpsk(cfg, wave, preamble, count):
    # Обучение выполняется по известной преамбуле; данные полезной нагрузки недоступны.
    start = cfg['rrc_order']
    reference = transmit(cfg, preamble)['waveform'][start:(len(preamble)-4)*cfg['sps']]
    n = np.arange(len(reference)) + start
    best = None
    for delay in np.arange(0, 2*cfg['sps']+.125, .25):
        slope, gain, error = fit_carrier(cubic(wave, n+delay), reference)
        if best is None or error < best[0]: best = error, delay, slope, gain
    _, delay, slope, gain = best
    n = np.arange(len(wave))
    aligned = cubic(wave, n+delay)*np.exp(-1j*slope*(n-start))/gain
    filtered = np.convolve(aligned, rrc_taps(cfg['sps'], cfg['rrc_order'], cfg['rolloff']))
    positions = cfg['rrc_order'] + cfg['sps']*np.arange(count)
    symbols = cubic(filtered, positions).real + 1j*cubic(filtered, positions+cfg['sps']/2).imag
    result = symbol_receiver(cfg, symbols, encode(cfg, preamble)[1][:-4])
    result.update(delay=delay, frequency=slope/(2*np.pi), gain=abs(gain), synchronized=symbols)
    return result


def receive_cpm(cfg, wave, preamble, count):
    # Частотный дискриминатор; обучение задаёт задержку и постоянное смещение частоты.
    sps = cfg['sps']
    reference = transmit(cfg, preamble)['waveform']
    used = (len(preamble) - 4) * sps
    best = None
    for delay in np.arange(0, 2 * sps + 0.125, 0.25):
        y = cubic(wave, np.arange(used) + delay)
        slope, gain, error = fit_carrier(y, reference[:used])
        if best is None or error < best[0]: best = error, delay, slope, gain
    _, delay, slope, gain = best
    gdelay = 2 * sps if cfg['family'] == 'gmsk' else 0
    positions = np.arange(count * sps + gdelay) + delay
    aligned = cubic(wave, positions) * np.exp(-1j * slope * np.arange(len(positions))) / gain
    increments = np.angle(aligned * np.conj(np.r_[1 + 0j, aligned[:-1]]))
    values = increments[gdelay:gdelay + count * sps].reshape(count, sps).sum(axis=1)
    data = (values >= 0).astype(int)
    return dict(data=data, indices=data, symbols=values.astype(complex), synchronized=values.astype(complex),
                delay=delay, frequency=slope / (2 * np.pi), gain=abs(gain))


def maximal_ratio_combine(branches, gains, variances=None):
    branches, gains = np.asarray(branches, complex), np.asarray(gains, complex)
    if branches.ndim != 2 or gains.shape != (branches.shape[0],) or not np.any(abs(gains) > 0):
        raise ValueError('Invalid diversity branches or gains')
    variances = np.ones(len(gains)) if variances is None else np.asarray(variances, float)
    if variances.shape != gains.shape or np.any(variances <= 0):
        raise ValueError('Noise variances must be positive')
    weights = gains.conj() / variances
    return weights @ branches / np.sum(abs(gains) ** 2 / variances)


def frame_data(cfg, count=768, seed=19):
    if count < 160: raise ValueError('Frame is too short')
    return np.random.default_rng(seed).integers(0, cfg['order'], count)


def run_demo(cfg):
    data = frame_data(cfg)
    tx = transmit(cfg, data)
    rx_wave = channel(cfg, tx['waveform'], snr_db=28, gain=0.65, phase=0.38, frequency=0.00015, delay=2.25)
    result = receive(cfg, rx_wave, data[:192], len(data))
    errors = int(np.count_nonzero(result['data'][192:] != data[192:]))
    report = dict(modem=cfg['name'], payload_symbols=len(data) - 192, symbol_errors=errors,
                  ser=errors / (len(data) - 192), estimated_delay=result['delay'], estimated_frequency=result['frequency'])
    print(json.dumps(report, indent=2))
    return report
