"""Seeded stimuli and independent acceptance checks for typed DSP workspaces."""
from pathlib import Path
import sys
import numpy as np
from scipy import signal as scipy_signal
from scipy.special import exp1
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
from research_core import run,OPERATIONS,expint1
from modem_core import load_config,transmit,rrc_taps,cubic


def check_ldpc(bits,word,H):
    bits=np.asarray(bits).real
    if bits.shape!=word.shape or np.any((bits!=0)&(bits!=1)) or np.any(bits!=word) or np.any((H@bits)%2):
        raise AssertionError('LDPC decoded word or syndrome mismatch')


def require_rejection(check):
    try: check()
    except AssertionError: return
    raise AssertionError('Negative control was accepted')


def cases():
    rng=np.random.default_rng(20260930); out=[]
    def add(workspace,name,op,p,x,a=(),truth=None,metric=None,description=''):
        x=np.asarray(x,complex).ravel();a=np.asarray(a,complex).ravel();y=run(op,p,x,a)
        assert np.all(np.isfinite(y)),name
        if truth is not None: np.testing.assert_allclose(y,truth,atol=2e-10,rtol=2e-10,err_msg=name)
        out.append(dict(workspace=workspace,name=name,operation=op,operation_id=OPERATIONS.index(op),
                        parameters=np.array(p,float),x=x,a=a,y=y,metric=metric or {},description=description))
        return y
    noise=lambda n: (rng.normal(size=n)+1j*rng.normal(size=n))/np.sqrt(2)
    x=noise(256);h=np.array([.2,.5,.3])
    add('filters/windowed_sinc','fir_impulse','fir',[],[1,0,0],h,truth=np.r_[h,0,0],description='Impulse response equals the supplied FIR coefficients.')
    add('filters/windowed_sinc','fir_complex','fir',[],x,h,truth=scipy_signal.fftconvolve(x,h))
    h=add('filters/windowed_sinc','hamming_lowpass','wsinc',[41,.12],[0],truth=scipy_signal.firwin(41,.24,window='hamming',scale=True))
    freq,response=scipy_signal.freqz(h,worN=1024);stop=float(np.max(abs(response[freq/np.pi>.4])))
    assert stop<.005
    out[-1]['metric']={'stopband_peak_db':20*np.log10(stop),'dc_gain':float(h.real.sum())}
    t=np.arange(512);x=np.exp(2j*np.pi*.04*t)+.7*np.exp(2j*np.pi*.35*t)
    add('filters/windowed_sinc','two_tone_filter','fir',[],x,h,truth=scipy_signal.fftconvolve(x,h))
    for name,op,step in [('lms','lms',.05),('nlms','nlms',.6),('rls','rls',.995)]:
        x=noise(512);taps=np.array([.6+.1j,-.2+.1j,.15]);desired=np.convolve(x,taps)[:len(x)]
        y=add('adaptive/lms_nlms_rls',name,op,[3,step,.01],x,desired)
        error=y[len(x):2*len(x)]; mse=float(np.mean(abs(error[-128:])**2));initial=float(np.mean(abs(error[:32])**2))
        assert mse<initial*.02,(op,mse,initial)
        np.testing.assert_allclose(y[-3:].conj(),taps,atol=.002)
        out[-1]['metric']={'initial_mse':initial,'final_mse':mse,'improvement_db':10*np.log10(initial/max(mse,1e-30))}
    # Проверка канального банка по независимому прямому смешиванию и свёртке.
    M=4;h=scipy_signal.firwin(33,.20);t=np.arange(256);x=np.exp(2j*np.pi*t/M)+.4*np.exp(-2j*np.pi*t/M)
    for op in ['pfb','wola']:
        for D in [4,3]:
            oracle=np.array([np.convolve(x*np.exp(2j*np.pi*k*t/M),h)[:len(x):D] for k in range(M)]).T.ravel()
            y=add('channelizers/pfb_wola',f'{op}_decimation_{D}',op,[M,D],x,h,truth=oracle)
            power=np.mean(abs(y.reshape(-1,M)[12:])**2,axis=0)
            assert power[3]>20*power[0]
            out[-1]['metric']={'desired_to_dc_leakage_db':float(10*np.log10(power[3]/power[0]))}
    # Порождающая матрица A задаёт систематический код H=[I A].
    A=np.array([[1,1,0,1,0,0],[0,1,1,0,1,0],[1,0,1,0,0,1],[1,1,0,0,1,0],[0,1,1,1,0,0],[1,0,1,0,1,1]])
    H=np.c_[np.eye(6,dtype=int),A];bits=np.array([1,0,1,1,0,1])
    word=add('coding/ldpc','systematic_encode','gf2_encode',[6,6],bits,A.ravel(),truth=np.r_[(A@bits)%2,bits]).real.astype(int)
    assert not np.any((H@word)%2)
    for mode in range(4):
        llr=(1-2*word)*6.; llr[7]*=-.12
        y=add('coding/ldpc',['sum_product','min_sum','normalized_min_sum','offset_min_sum'][mode],'ldpc',[6,12,20,mode,.8,.15],llr,H.ravel())
        check_ldpc(y[:12],word,H)
        corrupted=y[:12].real.copy();corrupted[0]=1-corrupted[0]
        require_rejection(lambda:check_ldpc(corrupted,word,H))
        require_rejection(lambda:check_ldpc((llr<0).astype(int),word,H))
        out[-1]['metric']={'uncoded_errors':int(np.count_nonzero((llr<0)!=word)),'decoded_errors':0,'syndrome_weight':0}
        out[-1]['metric']['negative_control_detected']=True
        out[-1]['metric']['rejected_mutations']=['flipped_decoded_bit','bypassed_decoder']
    n=64;hop=16;x=noise(320)
    spectra=add('audio/stft','analysis','stft',[n,hop],x)
    add('audio/stft','reconstruction','istft',[n,hop],spectra,truth=x,metric={'reconstruction_tolerance':2e-10})
    np.testing.assert_allclose([expint1(v) for v in np.geomspace(1e-5,100,70)],exp1(np.geomspace(1e-5,100,70)),atol=2e-12,rtol=2e-12)
    n=32;hop=8;t=np.arange(640);clean=np.zeros(640);clean[160:]=np.sin(2*np.pi*.125*t[160:]);x=clean+.32*rng.normal(size=640)
    y=add('audio/omlsa','calibrated_noise_reduction','omlsa',[n,hop,12,.92],x)
    before=float(np.mean(abs(x[224:]-clean[224:])**2));after=float(np.mean(abs(y[224:]-clean[224:])**2))
    assert after<before,(before,after)
    assert np.max(abs(y))<1.6, 'Spectral reconstruction amplified an edge artifact'
    out[-1]['metric']={'input_mse':before,'output_mse':after,'improvement_db':10*np.log10(before/after)}
    out[-1]['truth']=clean.astype(complex)
    M=8;t=np.arange(128);desired=np.exp(.12j*t);interference=3*np.exp(.47j*t)
    steering=np.exp(2j*np.pi*np.arange(M)*.125);other=np.ones(M)
    matrix=desired[:,None]*steering+interference[:,None]*other
    y=add('arrays/beamforming','spatial_null','beamform',[M],matrix.ravel(),steering,truth=desired)
    out[-1]['metric']={'interferer_amplitude':3.,'output_mse':float(np.mean(abs(y-desired)**2))}
    for regularization,name in [(0.,'zero_forcing'),(.015,'mmse')]:
        H=np.array([[1+.3j,.4-.2j],[-.2+.1j,.8+.2j]]);symbols=(2*rng.integers(0,2,(128,2))-1).astype(complex)
        observations=symbols@H.T
        if regularization:observations+=.02*noise(observations.size).reshape(observations.shape)
        y=add('mimo/dsplog',name,'mimo',[2,regularization],observations.ravel(),H.ravel())
        assert np.all(np.sign(y.real)==symbols.real.ravel())
        out[-1]['metric']={'bit_errors':0,'payload_bits':256}
    symbols=noise(128);h=np.array([.4+.3j,1-.2j]);s=symbols.reshape(-1,2)
    r=np.c_[h[0]*s[:,0]+h[1]*s[:,1],-h[0]*s[:,1].conj()+h[1]*s[:,0].conj()]
    add('mimo/dsplog','alamouti','alamouti',[],r.ravel(),h,truth=symbols)
    # OFDM использует полный комплексный блок и явный циклический префикс.
    for order in [2,4,16,64]:
        if order==2:const=np.array([-1,1])
        else:
            side=int(np.sqrt(order));levels=np.arange(-(side-1),side,2);const=(levels[:,None]+1j*levels).ravel();const/=np.sqrt(np.mean(abs(const)**2))
        labels=rng.integers(0,order,256);symbols=const[labels]
        wave=add('modems/ofdm_awgn',f'{order}_qam_tx','ofdm_tx',[32,8],symbols)
        received=wave+.003*noise(len(wave));y=add('modems/ofdm_awgn',f'{order}_qam_rx','ofdm_rx',[32,8],received)
        decisions=np.argmin(abs(y[:,None]-const)**2,axis=1);assert np.all(decisions==labels)
        out[-1]['metric']={'symbol_errors':0,'payload_symbols':256,'alphabet':order}
        bad=run('ofdm_rx',[32,8],wave+4*noise(len(wave)));assert np.count_nonzero(np.argmin(abs(bad[:,None]-const)**2,axis=1)!=labels)>30
        out[-1]['metric']['negative_control_detected']=True
    data=np.array([0,1,2,3]*12);wave=add('modems/fsk_text','four_fsk_tx','fsk_tx',[32,2,3,4],data)
    add('modems/fsk_text','four_fsk_rx','fsk_rx',[32,2,3,4],wave+.1*noise(len(wave)),truth=data,metric={'symbol_errors':0,'payload_symbols':len(data)})
    cfg=load_config(ROOT/'modems/qpsk_script_costas/config.json');labels=rng.integers(0,4,768);const=(np.array(cfg['constellation'])@[1,1j]);symbols=const[labels]
    wave=symbols*np.exp(1j*(.3+.006*np.arange(len(symbols))))
    y=add('synchronization/symbol_timing','costas_tracking','costas',[.08,.001],wave)
    before=float(np.mean(abs(wave[200:]-symbols[200:])**2));after=float(np.mean(abs(y[200:len(wave)]-symbols[200:])**2));assert after<before*.01
    out[-1]['metric']={'uncorrected_mse':before,'corrected_mse':after}
    shaped=transmit(cfg,labels)['waveform'];matched=np.convolve(shaped,rrc_taps(8,32,1))
    delayed=cubic(matched,np.arange(len(matched))-1.25)
    y=add('synchronization/symbol_timing','gardner_tracking','timing',[8,700,32,.1,.00005],delayed)
    before=float(np.mean(abs(cubic(delayed,32+8*np.arange(700))[300:]-symbols[300:700])**2));after=float(np.mean(abs(y[300:700]-symbols[300:700])**2))
    assert after<before*.4,(before,after)
    out[-1]['metric']={'uncorrected_mse':before,'corrected_mse':after}
    t=np.arange(512);clean=np.exp(2j*np.pi*.07*t);x=clean+2*np.exp(2j*np.pi*.23*t)
    y=add('filters/oset','notch_interference','notch',[.23,.94],x,truth=scipy_signal.lfilter([1,-2*np.cos(2*np.pi*.23),1],[1,-2*.94*np.cos(2*np.pi*.23),.94**2],x))
    residual=abs(np.mean(y[200:]*np.exp(-2j*np.pi*.23*t[200:])))
    assert residual<.03;out[-1]['metric']={'residual_interference_amplitude':float(residual)}
    x=np.ones(512)+.5*rng.normal(size=512);y=add('filters/oset','scalar_kalman','kalman',[.0005,.25,1],x)
    before=float(np.mean(abs(x[100:]-1)**2));after=float(np.mean(abs(y[100:]-1)**2));assert after<before*.2
    out[-1]['metric']={'input_mse':before,'output_mse':after}
    n=64;t=np.arange(n);tone=np.exp(2j*np.pi*7*t/n);truth=np.zeros(n,complex);truth[7]=n
    add('teaching/harger','dft_single_bin','dft',[0],tone,truth=truth)
    add('teaching/harger','inverse_dft','dft',[1],truth,truth=tone)
    add('teaching/harger','filter_impulse','fir',[],[1,0,0],[.25,.5,.25],truth=[.25,.5,.25,0,0])
    return out


if __name__=='__main__':
    result=cases()
    print(f'PASS {len(result)} analytic and seeded cases across {len(set(c["workspace"] for c in result))} typed workspaces')
    for c in result:
        if c['metric']:print(c['workspace'],c['name'],c['metric'])
