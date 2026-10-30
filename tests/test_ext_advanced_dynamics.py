import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_advanced_dynamics import *
class TestDynamics(unittest.TestCase):
 def test_curve_independent_hard_soft(self):
  x=np.array([-30.,-21,-18,-15,-6]);out=compressor_curve(x,-18,3,6)
  expected=np.array([-30,-21,-18-(2/3)*9/12,-17,-14])
  np.testing.assert_allclose(out,expected)
  np.testing.assert_allclose(compressor_curve([-30,-18,-6],-18,3,0),[-30,-18,-14])
 def test_peak_rms_step_and_fixed(self):
  for detector in ('peak','rms'):
   a=Compressor(fs=8000,attack=.01,release=.02,detector=detector);b=Compressor(fs=8000,attack=.01,release=.02,detector=detector,fixed=True)
   samples=np.r_[np.zeros(20),np.full(800,.5),np.zeros(800)]
   env=0
   for x in samples:
    target=x*x if detector=='rms' else abs(x);alpha=np.exp(-1/(8000*(.01 if target>env else .02)));env=alpha*env+(1-alpha)*target
    y=a.next([x,x/2]);z=b.next(np.floor(np.array([x,x/2])*Q+.5).astype(int))/Q
    self.assertAlmostEqual(a.envelope,env,places=13);self.assertLess(np.max(abs(y-z)),.0002)
   self.assertLess(a.envelope,.0034)
 def test_linked_gain_config_bypass_delay_and_saturation(self):
  a=Compressor(fs=8000,attack=0,knee=0,lookahead=2)
  np.testing.assert_array_equal(a.next([.5,.25]),[0,0]);a.next([.5,.25]);y=a.next([.5,.25]);self.assertAlmostEqual(y[0]/y[1],2)
  old=a.cfg.copy()
  with self.assertRaises(ValueError):a.configure(ratio=0)
  self.assertEqual(a.cfg,old);env=a.envelope;a.configure(threshold=-12);self.assertEqual(a.envelope,env)
  a.configure(bypass=True);np.testing.assert_array_equal(a.next([.5,.25]),[.5,.25])
  b=Compressor(fixed=True,ratio=1,makeup=24,attack=0);self.assertEqual(b.next([Q-1])[0],Q-1);self.assertGreater(b.saturations,0)
 def test_gate_latch_hold_hysteresis_gain(self):
  g=NoiseGate(fs=8000,threshold=-20,hysteresis=6,attack=0,hold=3/8000,release=0,range_db=-60)
  g.next([.2]);self.assertTrue(g.open)
  for _ in range(20):g.next([.075]);self.assertTrue(g.open)
  for i in range(3):g.next([.01]);self.assertTrue(g.open)
  y=g.next([.01]);self.assertFalse(g.open);self.assertAlmostEqual(y[0],.00001)
  z=NoiseGate(range_db=0);self.assertEqual(z.next([.001])[0],.001)
 def test_gate_tau_fixed_filter_stereo_reset(self):
  for fs in (8000,48000):
   a=NoiseGate(fs=fs,attack=.002,release=.01,hold=.001,hp=100,lp=2000);b=NoiseGate(fs=fs,attack=.002,release=.01,hold=.001,hp=100,lp=2000,fixed=True)
   n=np.arange(int(fs*.08));x=.2*np.sin(2*np.pi*700*n/fs);x[n>fs*.025]=0
   maxerr=0
   for v in x:
    y=a.next([v,v/2]);z=b.next(np.floor(np.array([v,v/2])*Q+.5).astype(int))/Q;maxerr=max(maxerr,np.max(abs(y-z)))
   self.assertLess(maxerr,.0003);self.assertFalse(a.open)
   b.reset();first=b.next([1000,2000],False);np.testing.assert_array_equal(first,b.next([1000,2000]))
 def test_reject_before_state_mutation(self):
  for cls in (Compressor,NoiseGate):
   a=cls(fixed=True);old=a.__dict__.copy()
   with self.assertRaises(ValueError):a.next([.5])
   self.assertEqual(a.gain,old['gain'])
   with self.assertRaises(ValueError):a.next([0],accept=1)
if __name__=='__main__':unittest.main()
