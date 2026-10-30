# Создано tools/generate_validation.py; правьте контракт в генераторе.
import numpy as np

def validate(op,p,x,a):
    if op=='ldpc' and 4<=len(p)<6: p=np.r_[p, [.8,.15][len(p)-4:]]
    counts=dict(zip(['fir', 'dft', 'pfb', 'lms', 'nlms', 'rls', 'ldpc', 'stft', 'istft', 'omlsa', 'beamform', 'mimo', 'ofdm_tx', 'ofdm_rx', 'fsk_tx', 'fsk_rx', 'costas', 'timing', 'notch', 'kalman', 'wola', 'wsinc', 'alamouti', 'gf2_encode'],[0, 1, 2, 3, 3, 3, 6, 2, 2, 4, 1, 2, 2, 2, 4, 4, 2, 5, 2, 3, 2, 2, 0, 2]))
    if op not in counts or len(p)!=counts[op] or not len(x) or not np.all(np.isfinite(np.r_[p,x,a])): raise ValueError('Invalid DSP transaction')
    if op in ['pfb', 'wola'] and not (p[0] >= 1 and p[0] <= 2147483647 and p[0] == np.floor(p[0])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['pfb', 'wola'] and not (p[1] >= 1 and p[1] <= 2147483647 and p[1] == np.floor(p[1])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['lms', 'nlms', 'rls'] and not (p[0] >= 1 and p[0] <= 2147483647 and p[0] == np.floor(p[0])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ldpc'] and not (p[0] >= 1 and p[0] <= 2147483647 and p[0] == np.floor(p[0])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ldpc'] and not (p[1] >= 1 and p[1] <= 2147483647 and p[1] == np.floor(p[1])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ldpc'] and not (p[2] >= 1 and p[2] <= 2147483647 and p[2] == np.floor(p[2])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['stft', 'istft', 'omlsa'] and not (p[0] >= 1 and p[0] <= 2147483647 and p[0] == np.floor(p[0])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['stft', 'istft', 'omlsa'] and not (p[1] >= 1 and p[1] <= 2147483647 and p[1] == np.floor(p[1])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['omlsa'] and not (p[2] >= 1 and p[2] <= 2147483647 and p[2] == np.floor(p[2])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['beamform', 'mimo', 'ofdm_tx', 'ofdm_rx', 'fsk_tx', 'fsk_rx', 'wsinc'] and not (p[0] >= 1 and p[0] <= 2147483647 and p[0] == np.floor(p[0])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['fsk_tx', 'fsk_rx'] and not (p[3] >= 1 and p[3] <= 2147483647 and p[3] == np.floor(p[3])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['timing', 'gf2_encode'] and not (p[0] >= 1 and p[0] <= 2147483647 and p[0] == np.floor(p[0])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['timing', 'gf2_encode'] and not (p[1] >= 1 and p[1] <= 2147483647 and p[1] == np.floor(p[1])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['fir', 'pfb', 'wola'] and not (len(a)>0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['dft'] and not (p[0] in (0,1)): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['lms', 'nlms', 'rls'] and not (len(a)==len(x) and p[1]>0 and p[2]>0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ldpc'] and not (p[3] in (0,1,2,3) and len(x)==p[1] and len(a)==p[0]*p[1] and p[4]>0 and p[5]>=0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ldpc', 'gf2_encode'] and not (np.all(a.imag==0) and np.all((a.real==0)|(a.real==1))): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ldpc'] and not (np.all(x.imag==0) and np.all(a.real.reshape(int(p[0]),int(p[1])).sum(axis=1)>=2)): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['stft', 'istft', 'omlsa'] and not (p[1]<=p[0]): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['stft'] and not (len(x)>=p[0]): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['istft'] and not (len(x)%int(p[0])==0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['omlsa'] and not (len(x)>p[0] and p[2]<=1+(len(x)+p[0])//p[1] and 0<=p[3]<1): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['beamform'] and not (len(a)==p[0] and len(x)%int(p[0])==0 and 1e-24<=np.vdot(a,a).real<=1e300): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['mimo'] and not (len(a)==p[0]**2 and len(x)%int(p[0])==0 and p[1]>=0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['mimo'] and not (mimo_valid(p,a)): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ofdm_tx', 'ofdm_rx'] and not (0<=p[1]<=p[0] and p[1]==np.floor(p[1])): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ofdm_tx'] and not (len(x)%int(p[0])==0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ofdm_rx'] and not (p[0]+p[1]<=2147483647): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['ofdm_rx'] and not (len(x)%int(p[0]+p[1])==0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['fsk_tx'] and not (np.all(x.imag==0) and np.all(x.real==np.floor(x.real)) and np.all((x.real>=0)&(x.real<p[3]))): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['fsk_rx'] and not (len(x)%int(p[0])==0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['costas'] and not (np.all(p>=0)): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['timing'] and not (p[0]>=2 and np.all(p[2:]>=0)): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['notch'] and not (0<=p[0]<=.5 and 0<=p[1]<1): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['kalman'] and not (p[0]>=0 and p[1]>0 and p[2]>=0): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['wsinc'] and not (p[0]>=2 and 0<p[1]<.5): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['alamouti'] and not (len(a)==2 and len(x)%2==0 and 1e-24<=np.vdot(a,a).real<=1e300): raise ValueError('Invalid DSP dimensions or parameters')
    if op in ['gf2_encode'] and not (len(x)==p[1] and len(a)==p[0]*p[1] and np.all(x.imag==0) and np.all((x.real==0)|(x.real==1))): raise ValueError('Invalid DSP dimensions or parameters')
    return p
def mimo_valid(p,a):
    n=int(p[0]); h=a.reshape(n,n)
    with np.errstate(over='ignore', invalid='ignore'):
        matrix=h.conj().T@h+p[1]*np.eye(n)
    if not np.all(np.isfinite(matrix)): return False
    for k in range(n):
        best=k+int(np.argmax(abs(matrix[k:,k])))
        matrix[[k,best]]=matrix[[best,k]]
        pivot=matrix[k,k]
        if abs(pivot)<1e-12: return False
        matrix[k,k:]/=pivot
        for i in range(k+1,n): matrix[i,k:]-=matrix[i,k]*matrix[k,k:]
    return np.all(np.isfinite(matrix))
