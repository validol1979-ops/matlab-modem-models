"""Exact MMSE3 weights and triple-stream vectors; independent clipped floating checks."""
from pathlib import Path
import json
import sys
import numpy as np
from regression_evidence import ROOT
sys.path.insert(0,str(ROOT/'common/python'))
import mmse3_fixed as fixed
from sat_diag import SatTrace,write_expected

CASES=('identity','complex','regularized','tiny_identity','zero_shift','min_imag','random_complex','wide_reciprocal')
STAGES=tuple(f'output.y{i}.{component}' for i in range(3) for component in ('re','im'))


def channel(kind,seed):
    if kind=='identity':H=np.eye(3,dtype=complex);lam=0
    elif kind=='complex':
        H=np.array([[1+.2j,.125-.1j,.02],[-.1j,.8+.1j,.1+.2j],[.2,-.1+.1j,1.1-.15j]])
        lam=.05
    elif kind=='regularized':H=np.ones((3,3),complex);lam=.1
    elif kind=='tiny_identity':H=np.eye(3)/(1<<15);lam=0
    elif kind=='zero_shift':H=np.diag([4,4,16])/(1<<15);lam=0
    elif kind=='min_imag':H=-4j*np.eye(3);lam=0
    elif kind=='wide_reciprocal':H=(-4-4j)*np.eye(3);lam=0
    elif kind=='gram_peak':
        H=np.full((3,3),-4-4j);lam=((1<<34)-1)/(1<<30)
    elif kind=='random_complex':
        rng=np.random.default_rng(seed)
        H=(rng.uniform(-1,1,(3,3))+1j*rng.uniform(-1,1,(3,3)))+.5*np.eye(3)
        lam=.125
    else:raise ValueError('Unknown MMSE3 case')
    Hraw=[[(int(round(z.real*32768)),int(round(z.imag*32768))) for z in row] for row in H]
    return Hraw,lam


def vectors(folder,kind,seed=53):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    H,lam=channel(kind,seed);L=fixed.lambda_raw(lam);W=fixed.weights(H,lam)
    (folder/'cfg.txt').write_text(''.join(f'{re} {im}\n' for row in H for re,im in row)+f'{L}\n')
    (folder/'weights.txt').write_text(''.join(f'{re} {im}\n' for row in W for re,im in row))
    rng=np.random.default_rng(seed)
    frames=[]
    for count in (1,2,31,64):
        values=rng.integers(-32768,32769,(3*count,2))
        frames.append([tuple(map(int,row)) for row in values])
    # Include both exact rails and tiny integer observations; no extra configuration.
    frames.append([(1,0),(0,1),(-1,1),(-131072,131071),(131071,-131072),(131071,131071),
                   (-131072,-131072),(131071,0),(0,-131072)])
    trace=SatTrace();input_rows=[];output_rows=[];max_error=0.
    Hfloat=np.array([[complex(re,im)/32768 for re,im in row] for row in H])
    Wfloat=np.linalg.solve(Hfloat.conj().T@Hfloat+(L/(1<<30))*np.eye(3),Hfloat.conj().T)
    for frame in frames:
        output=fixed.solve(frame,H,lam,stats=trace)
        input_rows.extend((re,im,int(i==len(frame)-1)) for i,(re,im) in enumerate(frame))
        output_rows.extend((re,im,int(i==len(output)-1)) for i,(re,im) in enumerate(output))
        obs=np.array([complex(re,im)/32768 for re,im in frame]).reshape(-1,3)
        reference=(obs@Wfloat.T).reshape(-1)
        reference=np.clip(reference.real,-4,131071/32768)+1j*np.clip(reference.imag,-4,131071/32768)
        actual=np.array([complex(re,im)/32768 for re,im in output])
        max_error=max(max_error,float(np.max(abs(actual-reference))))
    if max_error>=5e-5:raise RuntimeError(f'MMSE3 independent clipped reference error: {max_error}')
    (folder/'in.txt').write_text(''.join(f'{re} {im} {last}\n' for re,im,last in input_rows))
    (folder/'out.txt').write_text(''.join(f'{re} {im} {last}\n' for re,im,last in output_rows))
    write_expected(folder/'mmse3_expected.txt',trace,STAGES)
    saturation=trace.to_dict()
    assert sum(saturation['evaluations'].values())==2*len(output_rows)
    (folder/'saturation.json').write_text(json.dumps(saturation,indent=2)+'\n')
    return dict(case=kind,seed=seed,H=H,lambda_raw=L,weights=W,frames=len(frames),
                inputs=len(input_rows),outputs=len(output_rows),saturation=saturation,
                floating_clipped_max_error=max_error)
