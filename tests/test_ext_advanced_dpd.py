import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_advanced_dpd import *
class TestDPD(unittest.TestCase):
 def test_original_order_all_powers_and_fit(self):
  rng=np.random.default_rng(42);x=rng.uniform(.02,.6,3000)*np.exp(1j*rng.uniform(-np.pi,np.pi,3000))
  c=(rng.normal(size=(5,5))+1j*rng.normal(size=(5,5)))*.01;c[0,-1]=.9
  # Independent loop indexing reproduces original n:(n+M-1) oldestfirst.
  y=np.zeros(len(x),complex)
  for n in range(len(x)):
   for k in range(5):
    for m in range(5):
     ix=n-4+m
     if ix>=0:y[n]+=c[k,m]*x[ix]*abs(x[ix])**k
  np.testing.assert_allclose(MemoryPolynomial(c).process(x),y,atol=2e-16)
  np.testing.assert_allclose(fit(x,y),c,atol=2e-12)
 def test_fixed_arithmetic_reset_stall_saturation(self):
  c=np.zeros((5,5),complex);c[0,-1]=.8;c[1,-1]=-.2+.03j;c[2,-2]=.02
  rng=np.random.default_rng(6);x=(rng.normal(size=2000)+1j*rng.normal(size=2000))*.1
  xq=np.floor(np.c_[x.real,x.imag]*Q+.5).astype(int);xx=(xq[:,0]+1j*xq[:,1])/Q
  ref=MemoryPolynomial(c).process(xx);g=MemoryPolynomialFixed(c);y=g.process(xq);z=(y[:,0]+1j*y[:,1])/Q
  self.assertLess(np.max(abs(ref-z)),2e-5)
  g.reset();self.assertEqual(g.next(xq[0],False),g.next(xq[0]));g.reset();np.testing.assert_array_equal(g.process(xq),y)
  clip=MemoryPolynomialFixed([[4]])
  self.assertEqual(clip.next((Q-1,-Q)),(Q-1,-Q));self.assertEqual(clip.saturations,2)
 def test_indirect_learning_improves_synthetic_pa(self):
  rng=np.random.default_rng(8);x=rng.uniform(.01,.45,12000)*np.exp(1j*rng.uniform(-np.pi,np.pi,12000))
  pa=lambda z:z*(1-.4*abs(z)**2)*np.exp(.12j*abs(z)**2)
  y=pa(x);coef=fit(y,x,5,5);pred=MemoryPolynomial(coef).process(x);out=pa(pred)
  self.assertLess(nmse(out[8:],x[8:]),nmse(y[8:],x[8:])-20)
  # A deterministic two-tone regrowth check on bins beyond occupied ±tones.
  n=np.arange(4096);tone=.15*(np.exp(2j*np.pi*43*n/4096)+np.exp(2j*np.pi*71*n/4096))
  raw=pa(tone);corrected=pa(MemoryPolynomial(coef).process(np.tile(tone,2))[4096:])
  rawspec=abs(np.fft.fft(raw))**2;corspec=abs(np.fft.fft(corrected))**2
  regrowth=[15,99,(-13)%4096,127]
  self.assertLess(corspec[regrowth].sum(),rawspec[regrowth].sum()/100)
 def test_original_octave_fixture(self):
  p=np.load(Path(__file__).parent/'data/dpd_source_reference_20261030.npz')
  x,y=p['x'],p['y'];basis=design(x,5,5)[:2048]
  np.testing.assert_allclose(basis,p['basis'],rtol=2e-14,atol=2e-15)
  coef=fit(x[:2052],y[:2052],5,5)
  np.testing.assert_allclose(coef.ravel(),p['coefficients'],rtol=1e-10,atol=2e-11)
  np.testing.assert_allclose(MemoryPolynomial(p['coefficients'].reshape(5,5)).process(x)[4:2052],y[4:2052],atol=1e-13)
 def test_atomic_config_and_bool(self):
  for cls in (MemoryPolynomial,MemoryPolynomialFixed):
   c=cls([[0.,1.]])
   x=(Q//8,0) if cls is MemoryPolynomialFixed else .125
   c.next(x);hist=c.history[:];old=c.c.copy()
   with self.assertRaises(ValueError):c.configure([[float('nan'),1]])
   self.assertEqual(c.history,hist)
   np.testing.assert_array_equal(c.c,old)
   c.configure([[1.,0.]])
   self.assertEqual(c.history,hist)
   out=c.next((0,0) if cls is MemoryPolynomialFixed else 0)
   self.assertEqual(out,x)
   with self.assertRaises(ValueError):c.next(x,accept=1)
 def test_invalid(self):
  with self.assertRaises(ValueError):fit(np.ones(100),np.ones(100))
  with self.assertRaises(ValueError):MemoryPolynomialFixed([[200]])
if __name__=='__main__':unittest.main()
