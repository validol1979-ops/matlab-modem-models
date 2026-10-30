"""Portable DSP kernels with an explicit flat-array transaction contract."""
import math
import numpy as np
from modem_core import cubic
from research_validate import validate

OPERATIONS = ['fir','dft','pfb','lms','nlms','rls','ldpc','stft','istft','omlsa',
              'beamform','mimo','ofdm_tx','ofdm_rx','fsk_tx','fsk_rx','costas',
              'timing','notch','kalman','wola','wsinc','alamouti','gf2_encode']


def frames(x, nfft, hop):
    # Окно sqrt-Hann с ненулевыми краями позволяет проверить весь конечный кадр.
    window=np.sqrt(.5-.5*np.cos(2*np.pi*(np.arange(nfft)+.5)/nfft))
    count=1+(len(x)-nfft)//hop
    return np.array([np.fft.fft(x[k*hop:k*hop+nfft]*window) for k in range(count)]),window


def synthesis(spectra, window, hop):
    nfft=len(window); size=(len(spectra)-1)*hop+nfft
    y=np.zeros(size,complex); norm=np.zeros(size)
    for k,s in enumerate(spectra):
        y[k*hop:k*hop+nfft]+=np.fft.ifft(s)*window
        norm[k*hop:k*hop+nfft]+=window**2
    return y/np.maximum(norm,1e-15)


def expint1(x):
    # Разложение и цепная дробь для E1; аргумент строго положителен.
    x=max(float(x),1e-12)
    if x<=1:
        term=1.; series=0.
        for k in range(1,81):
            term*=-x/k; series+=term/k
        return -0.5772156649015328606-math.log(x)-series
    b=x+1.; c=1e30; d=1/b; h=d
    for k in range(1,101):
        a=-k*k; b+=2; d=1/(a*d+b); c=b+a/c; h*=c*d
    return h*math.exp(-x)


def ldpc_decode(llr,H,iterations,mode,alpha=.8,beta=.15):
    m,n=H.shape; check=[np.flatnonzero(row) for row in H]
    messages=np.zeros((m,n)); posterior=llr.copy()
    for _ in range(iterations):
        variable=posterior[None,:]-messages
        for j,ids in enumerate(check):
            for col in ids:
                values=variable[j,ids[ids!=col]]
                if mode==0:
                    product=np.prod(np.tanh(values/2))
                    messages[j,col]=2*np.arctanh(np.clip(product,-1+1e-12,1-1e-12))
                else:
                    magnitude=np.min(abs(values))
                    if mode==2: magnitude*=alpha
                    if mode==3: magnitude=max(0,magnitude-beta)
                    messages[j,col]=np.prod(np.sign(values))*magnitude
        posterior=llr+messages.sum(axis=0)
        bits=(posterior<0).astype(int)
        if not np.any((H@bits)%2): break
    return np.r_[bits,posterior]


def run(operation, parameters, signal, auxiliary=()):
    if isinstance(operation,(int,np.integer)):
        if not 0<=operation<len(OPERATIONS): raise ValueError('Invalid DSP operation')
        op=OPERATIONS[operation]
    elif isinstance(operation,str): op=operation
    else: raise ValueError('Invalid DSP operation')
    raw=np.asarray(parameters)
    if np.iscomplexobj(raw) and np.any(raw.imag!=0): raise ValueError('DSP parameters must be real')
    p=np.asarray(raw.real,float).reshape(-1); x=np.asarray(signal,complex).reshape(-1); a=np.asarray(auxiliary,complex).reshape(-1)
    if op not in OPERATIONS or not np.all(np.isfinite(x)) or not np.all(np.isfinite(a)) or not np.all(np.isfinite(p)):
        raise ValueError('Invalid DSP transaction')
    p=validate(op,p,x,a)
    if op=='fir': y=np.convolve(x,a)
    elif op=='dft': y=np.fft.ifft(x) if p[0] else np.fft.fft(x)
    elif op in ('pfb','wola'):
        channels,decimation=int(p[0]),int(p[1]); taps=a
        # Анализирующий банк: свёртка по фазам и DFT; начало отсчёта определено явно.
        output=[]
        for end in range(0,len(x),decimation):
            phases=np.zeros(channels,complex)
            for j in range(min(end+1,len(taps))): phases[j%channels]+=taps[j]*x[end-j]
            output.extend(np.fft.fft(phases)*np.exp(2j*np.pi*np.arange(channels)*end/channels))
        y=np.array(output)
    elif op in ('lms','nlms','rls'):
        size=int(p[0]); step=p[1]; w=np.zeros(size,complex); covariance=np.eye(size,dtype=complex)/p[2]
        history=np.zeros(size,complex); estimate=[]; errors=[]
        for sample,target in zip(x,a):
            history=np.r_[sample,history[:-1]]; pred=np.vdot(w,history); error=target-pred
            if op=='rls':
                gain=covariance@history/(step+np.vdot(history,covariance@history))
                w+=gain*error.conjugate()
                covariance=(covariance-np.outer(gain,history.conj())@covariance)/step
            else:
                mu=step/(p[2]+np.vdot(history,history).real) if op=='nlms' else step
                w+=mu*history*error.conjugate()
            estimate.append(pred); errors.append(error)
        y=np.r_[estimate,errors,w]
    elif op=='ldpc':
        m,n,it,mode=map(int,p[:4]); H=a.real.reshape(m,n)
        y=ldpc_decode(x.real,H,it,mode,p[4],p[5])
    elif op=='stft': y=frames(x,int(p[0]),int(p[1]))[0].ravel()
    elif op=='istft':
        n,h=int(p[0]),int(p[1]); window=np.sqrt(.5-.5*np.cos(2*np.pi*(np.arange(n)+.5)/n))
        y=synthesis(x.reshape(-1,n),window,h)
    elif op=='omlsa':
        n,h,nnoise=int(p[0]),int(p[1]),int(p[2]); alpha=p[3]
        # Отражение границ исключает усиление ошибки при делении на малый край окна.
        spectra,window=frames(np.pad(x,(n,n),mode='reflect'),n,h)
        noise=np.maximum(np.mean(abs(spectra[:nnoise])**2,axis=0),1e-9)
        previous=np.ones(n); cleaned=[]
        for s in spectra:
            gamma=abs(s)**2/noise
            xi=np.maximum(alpha*previous+(1-alpha)*np.maximum(gamma-1,0),1e-5)
            v=gamma*xi/(1+xi)
            gain=xi/(1+xi)*np.exp(.5*np.array([expint1(z) for z in v]))
            gain=np.clip(gain,.05,1)
            presence=1/(1+.25*(1+xi)*np.exp(-v))
            gain=gain**presence*.05**(1-presence)
            cleaned.append(s*gain); previous=abs(s*gain)**2/noise
        y=synthesis(cleaned,window,h)[n:n+len(x)]
    elif op=='beamform':
        channels=int(p[0]); matrix=x.reshape(-1,channels); y=matrix@a.conj()/np.vdot(a,a)
    elif op=='mimo':
        n=int(p[0]); H=a.reshape(n,n); observations=x.reshape(-1,n)
        y=np.linalg.solve(H.conj().T@H+p[1]*np.eye(n),H.conj().T@observations.T).T.ravel()
    elif op=='ofdm_tx':
        n,cp=int(p[0]),int(p[1]); symbols=x.reshape(-1,n); out=[]
        for s in symbols:
            wave=np.fft.ifft(s)*np.sqrt(n);out.extend(np.r_[wave[-cp:],wave] if cp else wave)
        y=np.array(out)
    elif op=='ofdm_rx':
        n,cp=int(p[0]),int(p[1]); y=(np.fft.fft(x.reshape(-1,n+cp)[:,cp:],axis=1)/np.sqrt(n)).ravel()
    elif op=='fsk_tx':
        n=int(p[0]); t=np.arange(n); y=np.exp(2j*np.pi*(p[1]+x.real[:,None]*p[2])*t/n).ravel()
    elif op=='fsk_rx':
        n,order=int(p[0]),int(p[3]); t=np.arange(n)
        basis=np.exp(2j*np.pi*(p[1]+np.arange(order)[:,None]*p[2])*t/n)
        y=np.argmax(abs(x.reshape(-1,n)@basis.conj().T),axis=1)
    elif op=='costas':
        phase=0.; frequency=0.; output=[]; history=[]
        for sample in x:
            value=sample*np.exp(-1j*phase); error=np.sign(value.real)*value.imag-np.sign(value.imag)*value.real
            output.append(value);history.append(phase)
            frequency+=p[1]*error;phase+=frequency+p[0]*error
        y=np.r_[output,history]
    elif op=='timing':
        sps,count=int(p[0]),int(p[1]); position=p[2]; rate=0.;output=[];history=[]
        for _ in range(count):
            early,mid,late=cubic(x,[position-sps/2,position,position+sps/2])
            error=np.clip(((late-early)*mid.conjugate()).real,-1,1)
            output.append(mid);history.append(position)
            rate+=p[4]*error;position+=sps+rate+p[3]*error
        y=np.r_[output,history]
    elif op=='notch':
        c=np.cos(2*np.pi*p[0]); r=p[1]; y=np.zeros(len(x),complex)
        for k in range(len(x)):
            y[k]=x[k]
            if k>0:y[k]+=-2*c*x[k-1]+2*r*c*y[k-1]
            if k>1:y[k]+=x[k-2]-r*r*y[k-2]
    elif op=='kalman':
        value=0j;covariance=p[2];y=[]
        for sample in x:
            covariance+=p[0];gain=covariance/(covariance+p[1]);value+=gain*(sample-value)
            covariance*=(1-gain);y.append(value)
    elif op=='wsinc':
        size=int(p[0]); t=np.arange(size)-(size-1)/2
        y=2*p[1]*np.sinc(2*p[1]*t)*(.54-.46*np.cos(2*np.pi*np.arange(size)/(size-1)))
        y/=y.sum()
    elif op=='alamouti':
        h0,h1=a; y=[];energy=abs(h0)**2+abs(h1)**2
        for r0,r1 in x.reshape(-1,2):
            y.extend([(h0.conjugate()*r0+h1*r1.conjugate())/energy,
                      (h1.conjugate()*r0-h0*r1.conjugate())/energy])
    elif op=='gf2_encode':
        m,k=int(p[0]),int(p[1]);A=a.real.astype(int).reshape(m,k)
        y=np.r_[(A@x.real.astype(int))%2,x.real]
    return np.asarray(y,complex).reshape(-1)
