"""MMSE_N weights and N-tuple stream vectors; independent clipped floating checks.

Each case writes cfg.txt, weights.txt, in.txt, out.txt, mmse_n_expected.txt and
saturation.json. The floating reference solves (H^H H + lambda I) W = H^H with
NumPy from the quantised H and rounded lambda; its clipped outputs must agree
with the integer model within BUDGET (the solver is not exact; all cases,
including a condition number near 40, stay within one output LSB).
reject_singular.txt / reject_range.txt are configurations the model rejects.
"""
from pathlib import Path
import json
import sys
import numpy as np
from regression_evidence import ROOT
sys.path.insert(0,str(ROOT/'common/python'))
import mmse_n_fixed as fixed
from sat_diag import SatTrace,write_expected

SIZES=(2,3,4,5,8)
CASES=('identity','complex','regularized','tiny_identity','wide','min_imag','random_complex','conditioned')
# Absolute clipped output budget, the same as mmse3 (one Q15 LSB is 3.05e-5).
BUDGET=5e-5


def stages(n):
    return tuple(f'output.y{i}.{component}' for i in range(n) for component in ('re','im'))


def quantise(H):
    return [[(int(round(z.real*32768)),int(round(z.imag*32768))) for z in row] for row in H]


def channel(kind,n,seed):
    rng=np.random.default_rng(seed)
    if kind=='identity':H=np.eye(n,dtype=complex);lam=0
    elif kind=='complex':
        H=np.eye(n)*(1+.1j)+(rng.uniform(-1,1,(n,n))+1j*rng.uniform(-1,1,(n,n)))*.12;lam=.05
    elif kind=='regularized':H=np.ones((n,n),complex);lam=.1
    elif kind=='tiny_identity':H=np.eye(n)/(1<<15);lam=0
    elif kind=='wide':H=(-4-4j)*np.eye(n);lam=0
    elif kind=='min_imag':H=-4j*np.eye(n);lam=0
    elif kind=='random_complex':
        H=(rng.uniform(-1,1,(n,n))+1j*rng.uniform(-1,1,(n,n)))+.5*np.eye(n);lam=.125
    elif kind=='conditioned':
        # Two nearly parallel columns, condition number of H around 40.
        H=np.eye(n)+(rng.normal(size=(n,n))+1j*rng.normal(size=(n,n)))*.05
        H[:,1]=H[:,0]+.05*H[:,1];lam=0
    else:raise ValueError('Unknown MMSE_N case')
    return quantise(H),lam


def write_cfg(path,H,L):
    Path(path).write_text(''.join(f'{re} {im}\n' for row in H for re,im in row)+f'{L}\n')


def rejected(n):
    """Configurations the integer model rejects, written as cfg files."""
    singular=[[(32768,0)]*n for _ in range(n)]
    # One strong and one 1-LSB channel: the weak pivot vanishes after block normalisation.
    weak=[[(131071 if i==j==0 else 1 if i==j else 0,0) for j in range(n)] for i in range(n)]
    out={}
    for name,H in (('singular',singular),('range',weak)):
        try:fixed.weights(H,0)
        except ValueError as exc:out[name]=(H,str(exc))
        else:raise RuntimeError(f'MMSE_N {name} configuration unexpectedly accepted for N={n}')
    return out


def vectors(folder,kind,n,seed=53):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    H,lam=channel(kind,n,seed);L=fixed.lambda_raw(lam);W=fixed.weights(H,lam)
    write_cfg(folder/'cfg.txt',H,L)
    (folder/'weights.txt').write_text(''.join(f'{re} {im}\n' for row in W for re,im in row))
    reasons={}
    for name,(bad,reason) in rejected(n).items():
        write_cfg(folder/f'reject_{name}.txt',bad,0);reasons[name]=reason
    rng=np.random.default_rng(seed)
    frames=[]
    for count in (1,2,31,64):
        values=rng.integers(-32768,32769,(n*count,2))
        frames.append([tuple(map(int,row)) for row in values])
    rails=[(1,0),(0,1),(-1,1),(-131072,131071),(131071,-131072),(131071,131071),
           (-131072,-131072),(131071,0),(0,-131072)]
    frames.append((rails*n)[:n*((len(rails)+n-1)//n)])
    trace=SatTrace();input_rows=[];output_rows=[];max_error=0.
    Hfloat=np.array([[complex(re,im)/32768 for re,im in row] for row in H])
    Wfloat=np.linalg.solve(Hfloat.conj().T@Hfloat+(L/(1<<30))*np.eye(n),Hfloat.conj().T)
    Wfixed=np.array([[complex(re,im)/(1<<24) for re,im in row] for row in W])
    for frame in frames:
        output=fixed.solve(frame,H,lam,stats=trace)
        input_rows.extend((re,im,int(i==len(frame)-1)) for i,(re,im) in enumerate(frame))
        output_rows.extend((re,im,int(i==len(output)-1)) for i,(re,im) in enumerate(output))
        obs=np.array([complex(re,im)/32768 for re,im in frame]).reshape(-1,n)
        reference=(obs@Wfloat.T).reshape(-1)
        reference=np.clip(reference.real,-4,131071/32768)+1j*np.clip(reference.imag,-4,131071/32768)
        actual=np.array([complex(re,im)/32768 for re,im in output])
        max_error=max(max_error,float(np.max(abs(actual-reference))))
    budget=BUDGET
    if max_error>=budget:raise RuntimeError(f'MMSE_N N={n} {kind} clipped reference error {max_error} >= {budget}')
    (folder/'in.txt').write_text(''.join(f'{re} {im} {last}\n' for re,im,last in input_rows))
    (folder/'out.txt').write_text(''.join(f'{re} {im} {last}\n' for re,im,last in output_rows))
    write_expected(folder/'mmse_n_expected.txt',trace,stages(n))
    saturation=trace.to_dict()
    assert sum(saturation['evaluations'].values())==2*len(output_rows)
    (folder/'saturation.json').write_text(json.dumps(saturation,indent=2)+'\n')
    return dict(case=kind,n=n,seed=seed,H=H,lambda_raw=L,weights=W,frames=len(frames),
                inputs=len(input_rows),outputs=len(output_rows),saturation=saturation,
                weight_max_error=float(np.max(abs(Wfixed-Wfloat))),
                condition_number=float(np.linalg.cond(Hfloat)),
                floating_clipped_max_error=max_error,budget=budget,rejections=reasons)
