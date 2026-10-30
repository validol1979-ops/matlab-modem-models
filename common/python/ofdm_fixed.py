"""Integer block OFDM over fft_fixed (reference of rtl/modems/ofdm_awgn/ofdm_tx.sv, ofdm_rx.sv).

research_core: ofdm_tx = ifft(s)*sqrt(n) with a cyclic prefix of cp samples, ofdm_rx =
fft(frame without the prefix)/sqrt(n). Here samples and symbols are Q15 integers (18 bit).
- TX: y = round(s*K, SHIFT_TX) scales by 1/sqrt(n) (n = 2^b: K = 46341 = round(sqrt(2)*2^15)
  for odd b, 32768 for even b; SHIFT_TX = 15 + ceil(b/2)), then the unhalved inverse
  (fft_fixed.inverse) gives ifft(s)*sqrt(n) directly, saturated to 18 bits; output
  wave[n-cp:] then wave.
- RX: X = fft_fixed.forward(frame[cp:]) = FFT/n, times sqrt(n) = K*2^-SHIFT_RX
  (SHIFT_RX = 15 - floor(b/2)), rounded and saturated to 18 bits.
round is half up, (v + 2^(s-1)) >> s.

Optional stats=None (sat_diag SatStats/SatTrace): transmit/receive count ONLY their outer
18 bit clamps, stages tx.re/tx.im and rx.re/rx.im (clamp='asym', the sat18 rails), each core
sample once before the cyclic-prefix duplication. The embedded fft_fixed calls run without
stats, so no FFT stage is counted; stats=None never touches sat_diag and is bit-identical.

Optional fft_stats=None is forwarded ONLY to the embedded fft_fixed call (inverse in
transmit, forward in receive), so the FFT stage clamps 'inverse.s<g>.<sum|diff>.<re|im>'
(plus 'inverse.conj.im') or 'forward.s<g>.<sum|diff>.<re|im>' are counted separately from
the outer clamps. record() clamps exactly like fft sat, so any combination of
stats/fft_stats stays bit-identical to the plain call."""
import fft_fixed as f

LIMIT=(1<<17)-1


def sat18(value):return max(-LIMIT-1,min(LIMIT,value))


def constants(n):
    bits=n.bit_length()-1
    if n<4 or n!=1<<bits or bits>10:raise ValueError('OFDM size must be a power of two in 4..1024')
    k=46341 if bits%2 else 32768
    return k,15+(bits+1)//2,15-bits//2


def transmit(symbols,n,cp,stats=None,fft_stats=None):
    if not 0<=cp<=n or len(symbols)%n:raise ValueError('Invalid OFDM frame')
    k,shift,_=constants(n);out=[]
    for start in range(0,len(symbols),n):
        y=[(f.rnd(re*k,shift),f.rnd(im*k,shift)) for re,im in symbols[start:start+n]]
        wave=f.inverse(y,stats=fft_stats)
        if stats is None:wave=[(sat18(re),sat18(im)) for re,im in wave]
        else:wave=[(stats.record('tx.re',re,LIMIT),stats.record('tx.im',im,LIMIT)) for re,im in wave]
        out.extend(wave[n-cp:]+wave)
    return out


def receive(samples,n,cp,stats=None,fft_stats=None):
    if not 0<=cp<=n or len(samples)%(n+cp):raise ValueError('Invalid OFDM frame')
    k,_,shift=constants(n);out=[]
    for start in range(0,len(samples),n+cp):
        X=f.forward(samples[start+cp:start+n+cp],stats=fft_stats)
        if stats is None:
            out.extend((sat18(f.rnd(re*k,shift)),sat18(f.rnd(im*k,shift))) for re,im in X)
        else:
            out.extend((stats.record('rx.re',f.rnd(re*k,shift),LIMIT),
                        stats.record('rx.im',f.rnd(im*k,shift),LIMIT)) for re,im in X)
    return out
