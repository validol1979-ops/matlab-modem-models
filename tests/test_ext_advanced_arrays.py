import sys,unittest
from pathlib import Path
import numpy as np
from scipy.signal import find_peaks
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_advanced_arrays import *
class TestArrays(unittest.TestCase):
 def test_mvdr_direct_constraint_and_noise_suppression(self):
  for m in (4,8):
   a=steering(m,15);b=steering(m,-35);r=10*np.outer(b,b.conj())+.1*np.eye(m)
   w=mvdr(r,a,1e-6);self.assertLess(abs(np.vdot(w,a)-1),1e-12)
   # Independent constrained minimizer via KKT, not same normalizedsolve.
   kkt=np.block([[r+1e-6*np.eye(m),a[:,None]],[a.conj()[None,:],np.zeros((1,1))]])
   want=np.linalg.solve(kkt,np.r_[np.zeros(m),1])[:m];np.testing.assert_allclose(w,want,atol=2e-14)
   ds=a/m;self.assertLess(np.real(np.vdot(w,r@w)),np.real(np.vdot(ds,r@ds))*.2)
   x=a[:,None]*np.array([.1,.2])[None,:];np.testing.assert_allclose(beamform(x,w),[.1,.2],atol=1e-14)
 def test_fixed_covariance_beamformer_integer_oracle(self):
  rng=np.random.default_rng(8);x=(rng.normal(size=(8,200))+1j*rng.normal(size=(8,200)))*.08
  q=np.floor(np.stack([x.real,x.imag],axis=2)*Q+.5).astype(int);xx=(q[:,:,0]+1j*q[:,:,1])/Q
  rq=covariance_fixed(q);np.testing.assert_allclose(covariance_float(rq),xx@xx.conj().T/200,atol=4.3e-8)
  w=mvdr(covariance_float(rq),steering(8,20));wq=weights_fixed(w);y=beamform_fixed(q,wq)
  want=(wq[:,0]-1j*wq[:,1])@xx/W
  self.assertLess(np.max(abs((y[:,0]+1j*y[:,1])/Q-want)),1e-5)
 def test_doa_music_esprit_and_fixed(self):
  rng=np.random.default_rng(12)
  for m,k,angles in ((4,1,[23]),(8,2,[-22,31])):
   a=np.array([steering(m,t) for t in angles]).T
   # Exact ensemble covariance: independent theoretical rankK plus noise.
   r=a@np.diag(np.arange(1,k+1))@a.conj().T+.01*np.eye(m)
   np.testing.assert_allclose(esprit(r,k),angles,atol=1e-10)
   grid=np.linspace(-70,70,561);p=music(r,k,grid);peaks=find_peaks(p)[0];est=np.sort(grid[peaks[np.argsort(p[peaks])[-k:]]]);np.testing.assert_allclose(est,angles,atol=.251)
   rq=np.floor(np.stack([r.real,r.imag],2)*W+.5).astype(int)
   den=music_fixed(rq,k,grid);idx=find_peaks(-np.asarray(den,float))[0];got=np.sort(grid[idx[np.argsort(np.asarray(den[idx],float))[:k]]]);np.testing.assert_allclose(got,angles,atol=.251)
   np.testing.assert_allclose(esprit(covariance_float(rq),k),angles,atol=1e-5)
 def test_projector_invariant_and_invalid(self):
  a=steering(4,0);r=np.outer(a,a.conj())+.01*np.eye(4)
  self.assertEqual(np.argmax(music(r,1,[-10,0,10])),1)
  with self.assertRaises(ValueError):steering(6,0)
  with self.assertRaises(ValueError):mvdr(-np.eye(4),a)
  with self.assertRaises(ValueError):music(r,True,[0])
if __name__=='__main__':unittest.main()
