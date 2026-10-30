#!/usr/bin/env python3
"""Finite Python PFB/STFT/OFDM/OMLSA precision on shared integer input words.

Independent NumPy/SciPy references, explicit FFT scaling/time geometry and
loaded versus ideal coefficients. Clipping error includes distortion. No
fitted shift/gain, decoder SER, width acceptance or RTL equivalence claim.
"""
import argparse
from contextlib import contextmanager
import hashlib
from pathlib import Path
import sys
import numpy as np
from scipy.special import exp1
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import fft_fixed as fft
import pfb_fixed as pfb
import stft_fixed as stft
import ofdm_fixed as ofdm
import omlsa_fixed as omlsa
from sat_diag import SatTrace,RangeTrace
from regression_evidence import begin,finish,write_json,require_unoptimized

SEED=1729
PFB_PROFILES=((4,3,33),(16,8,65),(64,32,129))
STFT_PROFILES=((4,1,23),(32,8,151),(64,16,320),(256,64,1200))
OFDM_PROFILES=((4,0),(32,8),(64,16),(1024,64))
FIXTURES=('impulse','tones','noise','clipping')


def quantize(wave,frac=15,width=18):
    wave=np.asarray(wave,complex);raw=np.rint(np.c_[wave.real,wave.imag]*(1<<frac))
    if not np.all(np.isfinite(raw)):raise ValueError('Finite samples required')
    low,high=-(1<<(width-1)),(1<<(width-1))-1
    clips=int(np.count_nonzero((raw<low)|(raw>high)))
    return [tuple(map(int,pair)) for pair in np.clip(raw,low,high).astype(np.int64)],clips


def complex_of(words,frac=15):
    a=np.asarray(words)
    if a.ndim!=2 or a.shape[1]!=2 or not a.size or not np.issubdtype(a.dtype,np.integer):raise ValueError('Integer Nx2 words required')
    return (a[:,0]+1j*a[:,1])/(1<<frac)


def digest(words):return hashlib.sha256(np.asarray(words,dtype='<i8').tobytes()).hexdigest()


def metric(actual,expected):
    a=np.asarray(actual,complex);e=np.asarray(expected,complex)
    if a.ndim!=1 or a.shape!=e.shape or not a.size or not np.all(np.isfinite(a)) or not np.all(np.isfinite(e)):raise ValueError('Equal finite nonempty precision vectors required')
    power=float(np.mean(abs(e)**2));mse=float(np.mean(abs(a-e)**2))
    return dict(samples=len(a),signal_power=power,error_power=mse,exact_match=mse==0,defined=power>0,
                sqnr_db=float(10*np.log10(power/mse)) if power>0 and mse>0 else None,
                normalized_rms_evm=float(np.sqrt(mse/power)) if power>0 else None,
                rms_error=float(np.sqrt(mse)),max_error=float(np.max(abs(a-e))))


def stimulus(kind,length,seed):
    t=np.arange(length);clean=.4*np.exp(2j*np.pi*.071*t)+.15*np.exp(-2j*np.pi*.213*t)
    noise=np.zeros(length,complex)
    if kind=='impulse':clean=np.r_[1-.5j,np.zeros(length-1)]
    elif kind=='noise':
        rng=np.random.default_rng(seed);sigma=np.sqrt(float(np.mean(abs(clean)**2))/10**1.2/2)
        noise=sigma*(rng.normal(size=length)+1j*rng.normal(size=length))
    elif kind=='clipping':clean=np.full(length,131071/32768-4j)
    elif kind!='tones':raise ValueError('Unknown fixture')
    words,clipped=quantize(clean+noise)
    return words,dict(seed=seed,input_clips=clipped,clean_power=float(np.mean(abs(clean)**2)),noise_power=float(np.mean(abs(noise)**2)),noise_snr_db=12 if kind=='noise' else None)


@contextmanager
def trace_fft(stats):
    """Observe the actual nested integer FFT clipping without replacing arithmetic."""
    forward, inverse = fft.forward, fft.inverse
    def observed_forward(x, in_width=18, width=fft.DATA_WIDTH, stats=None):
        return forward(x, in_width, width, stats=stats if stats is not None else observer)
    def observed_inverse(x, in_width=18, width=fft.DATA_WIDTH, stats=None):
        return inverse(x, in_width, width, stats=stats if stats is not None else observer)
    observer = stats
    fft.forward, fft.inverse = observed_forward, observed_inverse
    try:
        yield
    finally:
        fft.forward, fft.inverse = forward, inverse


def pfb_float(wave,taps,m,d):
    result=[]
    for end in range(0,len(wave),d):
        phase=np.zeros(m,complex)
        for j in range(min(end+1,len(taps))):phase[j%m]+=taps[j]*wave[end-j]
        result.extend(np.fft.fft(np.roll(phase,-(end%m)))/m)
    return np.asarray(result)


def float_window(n):return np.sqrt(.5-.5*np.cos(2*np.pi*(np.arange(n)+.5)/n))


def stft_float(wave,n,hop,window):
    count=1+(len(wave)-n)//hop
    if count<1:raise ValueError('Input shorter than a frame')
    return np.asarray([np.fft.fft(wave[frame*hop:frame*hop+n]*window)/n for frame in range(count)])


def synthesis_float(spectra,n,hop,window,reciprocals=None):
    spectra=np.asarray(spectra,complex).reshape(-1,n);frames=len(spectra);length=(frames-1)*hop+n
    output=np.zeros(length,complex);norm=np.zeros(length)
    for frame,values in enumerate(spectra):
        start=frame*hop;output[start:start+n]+=np.fft.ifft(values)*n*window;norm[start:start+n]+=window**2
    if reciprocals is None:return output/norm
    for t in range(length):
        mask=sum(1<<m for m in range(n//hop) if 0<=t//hop-m<frames)
        output[t]*=reciprocals[t%hop][mask]
    return output


def pfb_case(m,d,tap_count,kind):
    words,metadata=stimulus(kind,4*m+7,SEED+m);wave=complex_of(words)
    t=np.arange(tap_count)-(tap_count-1)/2
    desired=.2*np.sinc(.2*t)*np.hamming(tap_count);desired/=sum(desired)
    if kind=='clipping':desired=np.full(tap_count,131071/2**17)
    taps=pfb.quantize_taps(desired);loaded=np.asarray(taps)/2**17
    phase=SatTrace();embedded=SatTrace();actual=complex_of(pfb.analyze(words,taps,m,d,stats=phase,fft_stats=embedded),19)
    reference=pfb_float(wave,loaded,m,d);ideal=pfb_float(wave,desired,m,d)
    return dict(block='pfb',fixture=kind,parameters=dict(m=m,d=d,taps=tap_count),input_hash=digest(words),coefficient_hash=digest([(x,0) for x in taps]),input=metadata,
                geometry=dict(input_length=len(words),ends=list(range(0,len(words),d)),output_bins=len(reference),padding='zero history before index0; no post-input tail frames',native='FFT/M after phase[(bin+end)%M]; Q19 output'),
                metrics=dict(loaded=metric(actual,reference),ideal=metric(actual,ideal),coefficient=metric(loaded,desired)),
                clipping=dict(outer=phase.total(),embedded=embedded.total()),scope='Full analysis bank on shared Q15 samples and Q17 taps.')


def stft_case(n,hop,length,kind):
    words,metadata=stimulus(kind,length,SEED+n);wave=complex_of(words)
    loaded=np.asarray(stft.window(n))/2**17;ideal=float_window(n);recip=np.asarray(stft.reciprocals(n,hop))/2**stft.recip_frac(n,hop)
    analysis_fft=SatTrace()
    with trace_fft(analysis_fft):spectra=stft.analyze(words,n,hop)
    actual_spectra=complex_of(spectra,19).reshape(-1,n)
    loaded_analysis=stft_float(wave,n,hop,loaded);ideal_analysis=stft_float(wave,n,hop,ideal)
    classification='signal'
    if kind=='clipping':
        spectra=[(stft.SPECTRUM_LIMIT+1,-stft.SPECTRUM_LIMIT-1)]*(3*n)
        actual_spectra=complex_of(spectra,19).reshape(-1,n);classification='synthetic_spectrum';metadata.update(input_clips=0)
    stats=SatTrace();synthesis_fft=SatTrace()
    with trace_fft(synthesis_fft):actual=complex_of(stft.synthesize(spectra,n,hop,stats=stats))
    loaded_synthesis=synthesis_float(actual_spectra,n,hop,loaded,recip)
    ideal_synthesis=synthesis_float(actual_spectra,n,hop,ideal)
    used=len(actual);edge=n-hop
    measures=dict(synthesis_loaded=metric(actual,loaded_synthesis),synthesis_ideal=metric(actual,ideal_synthesis),window_coefficient=metric(loaded,ideal))
    if kind!='clipping':
        measures.update(analysis_loaded=metric(actual_spectra.ravel(),loaded_analysis.ravel()),analysis_ideal=metric(actual_spectra.ravel(),ideal_analysis.ravel()),
                        full_roundtrip_loaded=metric(actual,synthesis_float(loaded_analysis,n,hop,loaded,recip)),
                        full_roundtrip_ideal=metric(actual,synthesis_float(ideal_analysis,n,hop,ideal)),
                        interior_loaded=metric(actual[edge:used-edge],loaded_synthesis[edge:used-edge]),
                        interior_roundtrip_loaded=metric(actual[edge:used-edge],synthesis_float(loaded_analysis,n,hop,loaded,recip)[edge:used-edge]))
    return dict(block='stft',fixture=kind,parameters=dict(n=n,hop=hop,length=length),input_hash=digest(spectra if kind=='clipping' else words),spectrum_hash=digest(spectra),input=metadata,
                geometry=dict(frames=len(spectra)//n,frame_starts=list(range(0,used-n+1,hop)),output_length=used,dropped_input_tail=length-used if kind!='clipping' else None,
                              interior_indices=[edge,used-edge],padding='none',analysis_native='FFT/N Q19',synthesis_native='N*IFFT Q19 -> OLA*loaded reciprocal -> Q15',input_kind=classification),
                conditioning=dict(min_loaded_window=float(min(loaded)),max_loaded_window=float(max(loaded)),reciprocal_frac=stft.recip_frac(n,hop),window_hash=digest([(v,0) for v in stft.window(n)]),reciprocal_hash=hashlib.sha256(np.asarray(stft.reciprocals(n,hop),dtype='<i8').tobytes()).hexdigest(),edge_input_energy=float(np.sum(abs(wave[:edge])**2)+np.sum(abs(wave[max(edge,used-edge):used])**2)) if kind!='clipping' else None,interior_input_energy=float(np.sum(abs(wave[edge:used-edge])**2)) if kind!='clipping' else None),
                metrics=measures,clipping=dict(total=stats.total(),analysis_fft=analysis_fft.total() if kind!='clipping' else 0,synthesis_fft=synthesis_fft.total(),stages=stats.to_dict()),scope='Loaded synthesis uses shared spectrum words; full roundtrip has independent floating analysis as well.')


def ofdm_case(n,cp,kind):
    rng=np.random.default_rng(SEED+n);symbols=[tuple(map(int,pair)) for pair in rng.integers(-8000,8001,(4*n,2))]
    if kind=='impulse':symbols=[(0,0)]*(4*n);symbols[0]=(32768,-16384)
    if kind=='tones':
        symbols=[(0,0)]*(4*n)
        for frame in range(4):symbols[frame*n+min(3,n-1)]=(8000,-8000)
    if kind=='clipping':symbols=[(131071,-131072)]*(4*n)
    z=complex_of(symbols);k,shift_tx,shift_rx=ofdm.constants(n);tx_gain=k/2**shift_tx;rx_gain=k/2**shift_rx
    tx_stats=SatTrace();tx_fft=SatTrace();tx=ofdm.transmit(symbols,n,cp,stats=tx_stats,fft_stats=tx_fft);wave=complex_of(tx)
    loaded_frames=np.fft.ifft(z.reshape(-1,n)*tx_gain)*n;ideal_frames=np.fft.ifft(z.reshape(-1,n))*np.sqrt(n)
    add_cp=lambda frames:np.concatenate([np.r_[frame[n-cp:],frame] if cp else frame for frame in frames])
    loaded_tx=add_cp(loaded_frames);ideal_tx=add_cp(ideal_frames)
    channel=wave.copy();noise=np.zeros(len(wave),complex)
    if kind=='noise':
        sigma=np.sqrt(float(np.mean(abs(wave)**2))/10**1.2/2)
        noise=sigma*(rng.normal(size=len(wave))+1j*rng.normal(size=len(wave)));channel+=noise
    rx_words,clipped=quantize(channel);shared=complex_of(rx_words);rx_stats=SatTrace();rx_fft=SatTrace()
    actual=complex_of(ofdm.receive(rx_words,n,cp,stats=rx_stats,fft_stats=rx_fft));body=shared.reshape(-1,n+cp)[:,cp:]
    loaded_rx=(np.fft.fft(body)/n*rx_gain).ravel();ideal_rx=(np.fft.fft(body)/np.sqrt(n)).ravel()
    return dict(block='ofdm',fixture=kind,parameters=dict(n=n,cp=cp,k=k,shift_tx=shift_tx,shift_rx=shift_rx,tx_gain_loaded=tx_gain,rx_gain_loaded=rx_gain),
                input_hash=digest(symbols),channel_hash=digest(rx_words),input=dict(seed=SEED+n,input_clips=clipped,noise_power=float(np.mean(abs(noise)**2)),noise_snr_db=12 if kind=='noise' else None),
                geometry=dict(frames=4,tx_samples=len(tx),rx_symbols=len(actual),cp='last cp of each native time-domain frame copied before sample0; RX removes exactly cp',native='loaded1/sqrtN -> N*IFFT; FFT/N -> loaded sqrtN',shared_channel='Fixed TX -> one AWGN draw -> Q15 once -> fixed and floating RX'),
                metrics=dict(tx_loaded=metric(wave,loaded_tx),tx_ideal=metric(wave,ideal_tx),rx_loaded=metric(actual,loaded_rx),rx_ideal=metric(actual,ideal_rx),roundtrip_source=metric(actual,z),tx_coefficient=metric(loaded_tx,ideal_tx),rx_coefficient=metric(loaded_rx,ideal_rx)),
                clipping=dict(tx_outer=tx_stats.total(),tx_fft=tx_fft.total(),rx_outer=rx_stats.total(),rx_fft=rx_fft.total()),scope='Symbol-domain precision only; no constellation slicer/decoder or SER.')


def omlsa_float(wave,n,hop,nnoise,alpha,loaded=True):
    padded=np.pad(wave,(n,n),mode='reflect');window=np.asarray(stft.window(n))/2**17 if loaded else float_window(n)
    spectra=stft_float(padded,n,hop,window);noise=np.maximum(np.mean(abs(spectra[:nnoise])**2,axis=0),2.**-38)
    previous=np.ones(n);cleaned=[]
    for frame in spectra:
        gamma=abs(frame)**2/noise;xi=np.maximum(alpha*previous+(1-alpha)*np.maximum(gamma-1,0),1/65536)
        v=gamma*xi/(1+xi);gain=np.clip(xi/(1+xi)*np.exp(.5*exp1(np.maximum(v,1e-12))),.05,1)
        probability=1/(1+.25*(1+xi)*np.exp(-v));gain=gain**probability*.05**(1-probability)
        cleaned.append(frame*gain);previous=abs(frame*gain)**2/noise
    reciprocals=np.asarray(stft.reciprocals(n,hop))/2**stft.recip_frac(n,hop) if loaded else None
    return synthesis_float(cleaned,n,hop,window,reciprocals)[n:n+len(wave)]


def omlsa_case(kind):
    n,hop,length,nnoise,alpha=32,8,320,8,.92;t=np.arange(length);rng=np.random.default_rng(SEED)
    clean=np.zeros(length);clean[96:]=.5*np.sin(2*np.pi*.125*t[96:]);wave=clean+.16*rng.normal(size=length)
    if kind=='clipping':wave=np.r_[np.zeros(128),np.full(length-128,131071/32768-4j)]
    words,clipped=quantize(wave);shared=complex_of(words);stats=RangeTrace();embedded_fft=SatTrace()
    with trace_fft(embedded_fft):actual=complex_of(omlsa.enhance(words,n,hop,nnoise,alpha,stats=stats))
    loaded_alpha=round(alpha*65536)/65536;reference=omlsa_float(shared,n,hop,nnoise,loaded_alpha);ideal=omlsa_float(shared,n,hop,nnoise,alpha,False)
    data=stats.to_dict();caps=sum(v['pos'] for name,v in data['stages'].items() if name in ('omlsa.gamma','omlsa.xi','omlsa.v','omlsa.t','omlsa.prev'))
    return dict(block='omlsa',fixture=kind,parameters=dict(n=n,hop=hop,nnoise=nnoise,alpha=alpha,loaded_alpha=loaded_alpha),input_hash=digest(words),input=dict(seed=SEED,input_clips=clipped),
                geometry=dict(input_length=length,padded_length=length+2*n,padding='reflect excludes endpoint repetition: x[n:0:-1], x[-2:-n-2:-1]',crop=[n,n+length],output_length=len(actual),native='FFT/N Q19; ratio floors1/2^38 power and1/65536 xi; N*IFFT OLA'),
                metrics=dict(loaded=metric(actual,reference),ideal=metric(actual,ideal)),clipping=dict(numeric_ratio_caps=caps,embedded_fft=embedded_fft.total(),algorithm_ranges=data),
                scope='Independent floating gamma/xi/E1/gain/presence/previous state via SciPy exp1; loaded window/reciprocal/alpha and exact nonlinear functions, no fixed lookup or state reuse. No speech-quality/SER claim.')


def report():
    records=[pfb_case(*profile,kind) for profile in PFB_PROFILES for kind in FIXTURES]
    records += [stft_case(*profile,kind) for profile in STFT_PROFILES for kind in FIXTURES]
    records += [ofdm_case(*profile,kind) for profile in OFDM_PROFILES for kind in FIXTURES]
    records += [omlsa_case(kind) for kind in ('noise','clipping')]
    for record in records:record.update(quality_decisions(record))
    return dict(records=records,checks=check_records(records),quality_summary=dict(budget_db=45,rows_meeting_budget=sum(r['quality_budget_met'] is True for r in records),rows_below_budget=sum(r['quality_budget_met'] is False for r in records),rows_undefined=sum(r['quality_budget_met'] is None for r in records),scope='Fixed-versus-floating agreement only; clipping stress includes distortion, OFDM roundtrip_source/noise also includes actual AWGN. Not a speech quality or decoder SER assessment.'))


def identity(row):
    fields={'pfb':('m','d','taps'),'stft':('n','hop','length'),'ofdm':('n','cp'),'omlsa':('n','hop','nnoise')}
    return row['block'],tuple(row['parameters'][key] for key in fields[row['block']]),row['fixture']



def quality_decisions(record):
    decisions={name:dict(defined=m['defined'],budget_db=45,budget_met=(m['exact_match'] or m['sqnr_db']>=45) if m['defined'] else None)
               for name,m in record['metrics'].items() if name!='coefficient' and not name.endswith('_coefficient')}
    defined=[v['budget_met'] for v in decisions.values() if v['defined']]
    return dict(quality=decisions,quality_budget_met=all(defined) if defined else None)

def record_quality_matches(record):
    expected=quality_decisions(record)
    return record['quality']==expected['quality'] and record['quality_budget_met']==expected['quality_budget_met']

def metric_valid(m):
    """Validate denominators and the reported SQNR/EVM without a quality cutoff."""
    if not isinstance(m['samples'], int) or m['samples'] <= 0:
        return False
    fields=('signal_power','error_power','rms_error','max_error')
    if any(not np.isfinite(m[key]) or m[key] < 0 for key in fields):
        return False
    power, error=m['signal_power'], m['error_power']
    if m['defined'] != (power > 0) or m['exact_match'] != (error == 0):
        return False
    if not np.isclose(m['rms_error']**2,error,rtol=1e-10,atol=1e-30):
        return False
    if m['max_error'] + 1e-15 < m['rms_error']:
        return False
    if power == 0:
        return m['sqnr_db'] is None and m['normalized_rms_evm'] is None
    if not np.isclose(m['normalized_rms_evm'],np.sqrt(error/power),rtol=1e-10,atol=1e-15):
        return False
    return m['sqnr_db'] is None if error == 0 else np.isclose(m['sqnr_db'],10*np.log10(power/error),rtol=1e-10,atol=1e-10)


def geometry_valid(row):
    block, parameters, geometry, measures=row['block'],row['parameters'],row['geometry'],row['metrics']
    if block=='pfb':
        m,d=parameters['m'],parameters['d'];length=4*m+7;ends=list(range(0,length,d))
        return (geometry['input_length']==length and geometry['ends']==ends
                and geometry['output_bins']==len(ends)*m
                and all(measures[key]['samples']==len(ends)*m for key in ('loaded','ideal'))
                and measures['coefficient']['samples']==parameters['taps'])
    if block=='stft':
        n,hop,length=parameters['n'],parameters['hop'],parameters['length']
        frames=3 if row['fixture']=='clipping' else 1+(length-n)//hop
        size=(frames-1)*hop+n;edge=n-hop
        valid=(geometry['frames']==frames and geometry['output_length']==size
               and geometry['frame_starts']==[f*hop for f in range(frames)]
               and geometry['interior_indices']==[edge,size-edge]
               and all(measures[key]['samples']==size for key in ('synthesis_loaded','synthesis_ideal'))
               and measures['window_coefficient']['samples']==n)
        if row['fixture']!='clipping':
            valid=valid and geometry['dropped_input_tail']==length-size
            valid=valid and all(measures[key]['samples']==frames*n for key in ('analysis_loaded','analysis_ideal'))
            valid=valid and all(measures[key]['samples']==size for key in ('full_roundtrip_loaded','full_roundtrip_ideal'))
            valid=valid and all(measures[key]['samples']==size-2*edge for key in ('interior_loaded','interior_roundtrip_loaded'))
        return valid
    if block=='ofdm':
        n,cp=parameters['n'],parameters['cp']
        return (geometry['frames']==4 and geometry['tx_samples']==4*(n+cp) and geometry['rx_symbols']==4*n
                and all(measures[key]['samples']==4*(n+cp) for key in ('tx_loaded','tx_ideal','tx_coefficient'))
                and all(measures[key]['samples']==4*n for key in ('rx_loaded','rx_ideal','roundtrip_source','rx_coefficient')))
    n=parameters['n'];length=320
    return (geometry['input_length']==length and geometry['padded_length']==length+2*n
            and geometry['crop']==[n,n+length] and geometry['output_length']==length
            and all(m['samples']==length for m in measures.values()))


def check_records(records):
    expected={('pfb',profile,kind) for profile in PFB_PROFILES for kind in FIXTURES}
    expected|={('stft',profile,kind) for profile in STFT_PROFILES for kind in FIXTURES}
    expected|={('ofdm',profile,kind) for profile in OFDM_PROFILES for kind in FIXTURES}
    expected|={('omlsa',(32,8,8),kind) for kind in ('noise','clipping')}
    checks={'complete_cases':len(records)==len(expected) and set(map(identity,records))==expected}
    for row in records:
        prefix=str(identity(row));block=row['block'];stress=row['fixture']=='clipping'
        checks[prefix+'/geometry']=geometry_valid(row)
        checks[prefix+'/finite_consistent_metrics']=all(metric_valid(m) for m in row['metrics'].values())
        checks[prefix+'/quality_decisions_consistent']=record_quality_matches(row)
        if stress:
            events=(row['clipping']['outer']+row['clipping']['embedded'] if block=='pfb' else row['clipping']['total'] if block=='stft' else sum(row['clipping'].values()) if block=='ofdm' else row['clipping']['numeric_ratio_caps'])
            checks[prefix+'/stress_exercised']=events>0;continue
        checks[prefix+'/no_input_clips']=row['input']['input_clips']==0
        if block=='pfb':
            m=row['metrics']['loaded'];n=row['parameters']['m'];stages=int(np.log2(n))
            envelope=4*(stages+1)/2**19+2*np.sqrt(m['signal_power']*m['samples'])*stages/2**16
            checks[prefix+'/analysis_arithmetic_envelope']=m['max_error']<=envelope
            checks[prefix+'/no_arithmetic_clips']=sum(row['clipping'].values())==0
        elif block=='stft':
            n=row['parameters']['n'];minimum=float(np.min(np.asarray(stft.window(n))/2**17));envelope=2*n/2**19/minimum
            analysis=row['metrics']['analysis_loaded']
            bound=2/2**19 if row['fixture']=='impulse' else 4*(int(np.log2(n))+1)/2**19+2*np.sqrt(analysis['signal_power']*analysis['samples'])*int(np.log2(n))/2**16
            checks[prefix+'/analysis_arithmetic_envelope']=analysis['max_error']<=bound
            checks[prefix+'/loaded_synthesis_arithmetic_envelope']=row['metrics']['synthesis_loaded']['max_error']<=envelope
            checks[prefix+'/full_roundtrip_boundary_envelope']=row['metrics']['full_roundtrip_loaded']['max_error']<=envelope
            checks[prefix+'/no_arithmetic_clips']=row['clipping']['total']+row['clipping']['analysis_fft']+row['clipping']['synthesis_fft']==0
        elif block=='ofdm':
            envelope=4*np.sqrt(row['parameters']['n'])/2**15
            checks[prefix+'/tx_arithmetic_envelope']=row['metrics']['tx_loaded']['max_error']<=envelope
            checks[prefix+'/rx_arithmetic_envelope']=row['metrics']['rx_loaded']['max_error']<=envelope
            checks[prefix+'/no_arithmetic_clips']=sum(row['clipping'].values())==0
        else:
            checks[prefix+'/loaded_arithmetic_envelope']=row['metrics']['loaded']['rms_error']<.02
            checks[prefix+'/no_numeric_ratio_caps']=row['clipping']['numeric_ratio_caps']==0
            checks[prefix+'/no_fft_clips']=row['clipping']['embedded_fft']==0

    return {key:bool(value) for key,value in checks.items()}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=ROOT/'build/rtl/spectral_precision/results.json');args=parser.parse_args(argv)
    evidence=begin();write_json(args.output,dict(evidence,status='RUNNING'))
    try:
        require_unoptimized();data=report();status='PASS' if all(data['checks'].values()) else 'FAIL'
        result=dict(finish(evidence),status=status,**data,rtl_verified=False,scope=__doc__,seed=SEED,status_scope='PASS validates measurement coverage/finite geometry, arithmetic envelopes and exercised clipping controls. Signal quality budget 45 dB is separately reported and can fail on a PASS measurement.',arithmetic_envelopes=dict(scope='Finite regression envelopes; not universal error proofs or width acceptance',q19_lsb=2**-19,q15_lsb=2**-15,pfb_and_stft_analysis='4*(log2(N)+1)*Q19_LSB + 2*sqrt(reference_power*number_of_output_words)*log2(N)/2^16 absolute complex error',stft_edge_impulse_analysis='2*Q19_LSB absolute complex error',stft_synthesis_and_roundtrip='2*N*Q19_LSB/min(loaded_window) absolute complex error; finite fixtures, not an all-input proof',ofdm='4*sqrt(N)*Q15_LSB absolute TX/RX complex error; finite fixtures',omlsa='loaded-reference RMS error<0.02; no nominal numeric ratio caps'),twiddle_scope='NumPy references use exact DFT twiddles; measured error includes fixed FFT Q16 twiddle quantization and rounding.');write_json(args.output,result)
    except Exception as error:
        write_json(args.output,dict(evidence,status='FAIL',error=str(error)));raise
    if status!='PASS':raise RuntimeError('Spectral precision failed: '+', '.join(key for key,value in data['checks'].items() if not value))
    print(f'PASS SPECTRAL PRECISION {len(data["records"])} records');return result


if __name__=='__main__':main()
