import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_advanced_sar import *
class TestSAR(unittest.TestCase):
 def test_point_focus_registration_and_direct_backprojection(self):
  g=Geometry()
  for x,r in ((0,100),(8,112),(-12,90)):
   a=point_echo(g,[(x,r,.01)]);image=omega_k(a,g);peak=np.unravel_index(np.argmax(abs(image)),image.shape)
   self.assertLessEqual(abs(g.azimuths[peak[0]]-x),1)
   self.assertLessEqual(abs(g.ranges[peak[1]]-r),g.c/(2*g.fs))
   az=g.azimuths[peak[0]-3:peak[0]+4];rg=g.ranges[peak[1]-3:peak[1]+4]
   bp=backprojection(a,g,az,rg);self.assertEqual(np.unravel_index(np.argmax(abs(bp)),bp.shape),(3,3))
   # Point-spread widths measured against sampling and pulse bandwidth.
   profile=abs(image[peak[0]]);width=np.sum(profile>profile.max()/np.sqrt(2))
   self.assertGreaterEqual(width,2);self.assertLessEqual(width,8)
   mask=np.ones(image.shape,bool);mask[peak[0]-5:peak[0]+6,peak[1]-10:peak[1]+11]=False
   self.assertGreater(20*np.log10(abs(image[peak])/abs(image[mask]).max()),9)
   if r!=100:
    disabled=omega_k(a,g,stolt=False)
    self.assertGreater(abs(image).max()/abs(disabled).max(),2)
 def test_superposition_phase_and_multitarget(self):
  g=Geometry(nfast=128,nslow=64,fs=32,prf=10)
  a=point_echo(g,[(0,100,.01)]);b=point_echo(g,[(12,112,.007j)])
  np.testing.assert_allclose(omega_k(a+b,g),omega_k(a,g)+omega_k(b,g),atol=2e-16)
  im=omega_k(a,g);np.testing.assert_allclose(omega_k(1j*a,g),1j*im,atol=1e-16)
 def test_stolt_inverse_support_and_fixed_pipeline(self):
  g=Geometry(nfast=128,nslow=64,fs=32,prf=10)
  rfm,left,frac,support=plan(g)
  fr=np.fft.fftshift(np.fft.fftfreq(g.nfast,1/g.fs));fa=np.fft.fftshift(np.fft.fftfreq(g.nslow,1/g.prf))
  old=fr[0]+(left+frac)*(fr[1]-fr[0])
  # Away from clipped invalid support, forward/inverse MathML maps agree.
  new=np.sqrt((g.fc+old)**2-g.c**2*fa[:,None]**2/(4*g.velocity**2))-g.fc
  np.testing.assert_allclose(new[support],np.broadcast_to(fr,new.shape)[support],atol=2e-14)
  self.assertTrue((~support).any())
  a=point_echo(g,[(8,112,.01)]);q=np.floor(np.stack([a.real,a.imag],2)*2**17+.5).astype(int)
  got=OmegaKFixed(g).process(q);z=(got[:,:,0]+1j*got[:,:,1])/2**17
  ref=omega_k((q[:,:,0]+1j*q[:,:,1])/2**17,g)
  self.assertEqual(np.unravel_index(np.argmax(abs(z)),z.shape),np.unravel_index(np.argmax(abs(ref)),ref.shape))
  self.assertLess(np.max(abs(ref-z)),.0003);self.assertLess(np.linalg.norm(ref-z)/np.linalg.norm(ref),.02)
 def test_internal_clipping_is_rejected(self):
  g=Geometry(nfast=128,nslow=64,fs=32,prf=10)
  a=point_echo(g,[(0,100,.4)]);q=np.floor(np.stack([a.real,a.imag],2)*2**17+.5).astype(int)
  with self.assertRaises(OverflowError):OmegaKFixed(g).process(q)
 def test_validation(self):
  with self.assertRaises(ValueError):Geometry(nfast=33)
  with self.assertRaises(ValueError):Geometry(velocity=0)
  with self.assertRaises(ValueError):point_echo(Geometry(),[(0,-1,1)])
  with self.assertRaises(ValueError):omega_k(np.zeros((10,10)),Geometry())
if __name__=='__main__':unittest.main()
