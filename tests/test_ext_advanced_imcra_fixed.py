import sys,unittest
from pathlib import Path
import numpy as np
from scipy.special import exp1
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
import ext_advanced_imcra_fixed as f
class TestIMCRAFixed(unittest.TestCase):
 def test_full497frame_source_oracle(self):
  p=np.load(Path(__file__).parent/'data/imcra_source_reference_20261030.npz');tracker=f.IMCRAFixed();indices=p['indices'].tolist();worst={}
  for i in range(p['Ya2'].shape[1]):
   gain=tracker.step(np.floor(p['Ya2'][:,i]*f.S+.5).astype(np.int64))
   self.assertTrue(all(isinstance(v,int) for v in gain))
   if i in indices:
    j=indices.index(i)
    for name in ('lambda_d','lambda_dav','lambda_dav_long','S','Smin','St','Smint','SMact','SMactt','qhat','phat','q','PH1','gamma','eta','v','GH1','GH0','G','eta_2term','Sy','xi','P_local','P_global'):
     got=np.array([float(v) for v in getattr(tracker,name)]);ref=p[name][:,j]
     # One predeclared absolute+relative budget for all Q48/LUT stages.
     np.testing.assert_allclose(got,ref,rtol=2e-5,atol=2e-6,err_msg=name+str(i))
    for name in ('lambda_d','lambda_dav','lambda_dav_long','S','Smin','St','Smint','qhat','phat','q','PH1','gamma','eta','v','GH1','GH0','G','eta_2term','Sy','xi','P_local','P_global'):
     self.assertTrue(all(isinstance(v,f.Fixed) for v in getattr(tracker,name)),name)
    self.assertIsInstance(tracker.P_frame,f.Fixed)
    self.assertAlmostEqual(float(tracker.frame_presence),float(p['frame_presence'][j]),delta=2e-6)
  self.assertEqual(tracker.l,497);self.assertEqual(tracker.l_mod_lswitch,2)
 def test_lut_error_and_integer_only_runtime(self):
  for x in np.geomspace(1e-9,5,200):
   q=f.Fixed.of(x);x=q.raw/f.S
   self.assertLess(abs(float(f.Fixed(f._e1(q.raw)))-exp1(x)),2e-7)
   self.assertLess(abs(float(q.log10())-np.log10(x)),2e-8)
   self.assertLess(abs(float(q.sqrt())-np.sqrt(x)),1e-10)
  tracker=f.IMCRAFixed();power=np.full(257,int(.001*f.S),dtype=np.int64)
  old=f.Fixed.__float__;old_converter=f._from_float
  try:
   f.Fixed.__float__=lambda _:(_ for _ in ()).throw(AssertionError('floating dynamic conversion'))
   f._from_float=lambda _:(_ for _ in ()).throw(AssertionError('dynamic float constant quantization'))
   for _ in range(16):tracker.step(power)
  finally:f.Fixed.__float__=old;f._from_float=old_converter
 def test_qhat_unity_quantum_boundary(self):
  gm=f.Fixed(f.S+1);qhat=(f.Fixed.of(3)-gm)/f.Fixed.of(2)
  self.assertEqual(qhat.raw,f.S)
  probability=f.speech_presence(qhat,f.Fixed.of(1),f.Fixed.of(.5))
  self.assertEqual(probability.raw,0)
  for raw in (f.S-2,f.S-1,f.S):
   p=f.speech_presence(f.Fixed(raw),f.Fixed.of(1),f.Fixed.of(.5))
   self.assertGreaterEqual(p.raw,0);self.assertLessEqual(p.raw,f.S)
 def test_silence_reset_invalid_and_integer_gain(self):
  a=f.IMCRAFixed();a.step(np.zeros(257,dtype=int));self.assertEqual(a.l_fnz,2)
  power=np.full(257,int(.001*f.S),dtype=np.int64);a.step(power)
  before=a.l
  for bad in (np.full(257,-1),np.ones(257),np.full(256,1),np.full(257,1025*f.S,dtype=object)):
   with self.assertRaises(ValueError):a.step(bad)
   self.assertEqual(a.l,before)
  iq=np.full((257,2),10000,dtype=int);out=a.apply_gain(iq)
  self.assertTrue(np.all(out[:3]==0));self.assertTrue(np.all(out[-1]==0))
  expected=(10000*a.G[4].raw+f.S//2)//f.S;self.assertEqual(out[4,0],expected)
  a.reset();b=f.IMCRAFixed();np.testing.assert_array_equal(a.step(power),b.step(power))
  self.assertIsInstance(a._dB([f.Fixed.of(1),f.Fixed.of(0)]),f.Fixed)
if __name__=='__main__':unittest.main()
