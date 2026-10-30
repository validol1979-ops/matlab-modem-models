import sys,unittest,json
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_advanced_eq import *
class TestEQ(unittest.TestCase):
 def test_exact_source_prototype(self):
  fixture=json.loads((Path(__file__).parent/'data/eq16_source_prototype_20261030.json').read_text())
  np.testing.assert_allclose(prototype(),fixture['prototype512'],atol=1e-16,rtol=2e-15)
  self.assertEqual(prototype()[0],0);self.assertEqual(np.argmax(prototype()),256)
 def test_independent_modulated_filter_oracle(self):
  rng=np.random.default_rng(4);x=(rng.normal(size=83)+1j*rng.normal(size=83))*.02;h=prototype();g=np.linspace(.1,1.1,16)
  want=np.zeros(8*((len(x)+518)//8-1)+512,complex)
  for k in range(16):
   filt=h*np.exp(2j*np.pi*k*np.arange(512)/16)
   first=np.convolve(x,filt)[::8];ups=np.zeros(8*(len(first)-1)+1,complex);ups[::8]=first
   y=np.convolve(ups,filt)*g[k];want[:len(y)]+=y
  np.testing.assert_allclose(equalize(x,g),want,atol=2e-16)
 def test_unity_latency_gain_and_fixed(self):
  rng=np.random.default_rng(5);x=(rng.normal(size=500)+1j*rng.normal(size=500))*.03
  y=equalize(x);target=y[512:512+len(x)];error=np.linalg.norm(target-x)/np.linalg.norm(x)
  self.assertLess(error,.002)
  q=np.floor(np.c_[x.real,x.imag]*Q+.5).astype(int);xx=(q[:,0]+1j*q[:,1])/Q
  fixed=EqualizerFixed().process(q);z=(fixed[:,0]+1j*fixed[:,1])/Q
  self.assertLess(np.max(abs(z-equalize(xx))),.0005)
  impulse=equalize(np.r_[.2,np.zeros(31)]);self.assertEqual(np.argmax(abs(impulse)),512)
 def test_singleband_gain_and_atomic_config(self):
  n=np.arange(2048);x=.05*np.exp(2j*np.pi*3*n/16)
  g=np.ones(16);g[3]=.25
  y=equalize(x,g);unity=equalize(x);sl=slice(1200,2200)
  self.assertLess(np.linalg.norm(y[sl]-.25*unity[sl])/np.linalg.norm(unity[sl]),.015)
  f=EqualizerFixed(g);old=f.g.copy()
  with self.assertRaises(ValueError):f.configure([1]*15)
  np.testing.assert_array_equal(f.g,old)
if __name__=='__main__':unittest.main()
