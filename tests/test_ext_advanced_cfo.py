import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_advanced_cfo import *
class TestCFO(unittest.TestCase):
 def test_paper64qam_examples_and_complex_rejection(self):
  rng=np.random.default_rng(18);levels=np.arange(-7,8,2)
  for n in (16,64):
   for cfo in (-.3,.0,.2,.3):
    a=rng.choice(levels,n)+1j*rng.choice(levels,n);b=mixing(n,cfo)@a
    self.assertLess(abs(characteristic(cfo,b,a[0])),1e-11)
    got=estimate_cfo(b,a[0]);self.assertAlmostEqual(got,cfo,places=9)
    np.testing.assert_allclose(correct_spectrum(b,got),a,atol=2e-10)
  # Real-part degeneracy with purely imaginary symbols: f(x) identicallyzero.
  a=1j*np.arange(1,9);b=mixing(8,.2)@a
  with self.assertRaises(ArithmeticError):estimate_cfo(b,a[0])
 def test_dirichlet_independent_time_fft_and_correction(self):
  rng=np.random.default_rng(5);a=(rng.normal(size=16)+1j*rng.normal(size=16))*.1;cfo=.2
  time=np.fft.ifft(a);rx=time*np.exp(-2j*np.pi*cfo*np.arange(16)/16);b=np.fft.fft(rx)
  np.testing.assert_allclose(mixing(16,cfo,'fft_dirichlet')@a,b,atol=2e-15)
  self.assertGreater(np.linalg.norm(mixing(16,cfo)@a-b),.1)
  got=estimate_cfo(b,a[0],'fft_dirichlet');self.assertAlmostEqual(got,cfo,places=9)
  np.testing.assert_allclose(np.fft.fft(correct_time(rx,got)),a,atol=1e-12)
 def test_fixed_grid_and_integer_correction(self):
  rng=np.random.default_rng(33);a=(rng.integers(0,2,8)*2-1+1j*(rng.integers(0,2,8)*2-1))*.1
  for model in ('paper_sinc','fft_dirichlet'):
   f=FixedCFO(8,a[0],model,grid=1025);b=mixing(8,.217,model)@a;bi=np.floor(np.c_[b.real,b.imag]*Q+.5).astype(int)
   got=f.estimate(bi);self.assertLess(abs(got-.217),.0017)
  rx=np.fft.ifft(mixing(8,.217,'fft_dirichlet')@a);q=np.floor(np.c_[rx.real,rx.imag]*Q+.5).astype(int)
  out=correct_time_fixed(q,.217);want=correct_time((q[:,0]+1j*q[:,1])/Q,.217)
  self.assertLess(np.max(abs((out[:,0]+1j*out[:,1])/Q-want)),3e-5)
 def test_noise25db_conditional_paper_ser(self):
  rng=np.random.default_rng(99);levels=np.arange(-7,8,2);errors=[];before=[];after=[];ser0=[];ser1=[];rejected=0
  decision=lambda z:np.clip(np.floor((z.real*np.sqrt(42)+8)/2),0,7)+8j*np.clip(np.floor((z.imag*np.sqrt(42)+8)/2),0,7)
  for frame in range(32):
   a=(rng.choice(levels,16)+1j*rng.choice(levels,16))/np.sqrt(42);a[0]=1+.3j
   b=mixing(16,.2)@a
   b+=(rng.normal(size=16)+1j*rng.normal(size=16))*np.sqrt(np.mean(abs(b)**2)/(2*10**2.5))
   try:got=estimate_cfo(b,a[0],tolerance=.15)
   except ArithmeticError:rejected+=1;continue
   corrected=correct_spectrum(b,got);errors.append(got-.2)
   before.append(np.mean(abs(b-a)**2));after.append(np.mean(abs(corrected-a)**2))
   truth=decision(a[1:]);ser0.append(np.mean(decision(b[1:])!=truth));ser1.append(np.mean(decision(corrected[1:])!=truth))
  self.assertGreaterEqual(len(errors),16);self.assertGreater(rejected,0)
  self.assertLess(np.sqrt(np.mean(np.array(errors)**2)),.07)
  self.assertLess(np.mean(after),np.mean(before)*.15);self.assertLess(np.mean(ser1),np.mean(ser0)*.6)
 def test_existing_ofdm_fft_cp_and_search_edges(self):
  from research_core import run
  rng=np.random.default_rng(13);a=(rng.normal(size=16)+1j*rng.normal(size=16))*.1;a[0]=.1+.03j
  tx=run('ofdm_tx',[16,4],a)
  rx=tx*np.exp(-2j*np.pi*.2*np.arange(-4,16)/16)
  b=run('ofdm_rx',[16,4],rx);got=estimate_cfo(b,a[0],'fft_dirichlet')
  corrected=run('ofdm_rx',[16,4],correct_time(rx,got,16,-4))
  np.testing.assert_allclose(corrected,a,atol=1e-12)
  for cfo in (-.8,.8):
   b=mixing(16,cfo)@a;self.assertAlmostEqual(estimate_cfo(b,a[0]),cfo,places=8)
 def test_failures_bounds_and_known_phase_origin(self):
  a=np.ones(8,complex);b=mixing(8,.6)@a
  with self.assertRaises(ArithmeticError):estimate_cfo(b,a[0],bounds=(-.2,.2))
  with self.assertRaises(ValueError):mixing(8,0,'schmidl_cox')
  x=np.array([.1+.2j]*12);np.testing.assert_allclose(correct_time(x,.2,8,4),x*np.exp(2j*np.pi*.2*np.arange(4,16)/8))
if __name__=='__main__':unittest.main()
