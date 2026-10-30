import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_advanced_kalman import Kalman,KalmanFixed

class TestKalmanMatrix(unittest.TestCase):
 def test_scalar_gain_and_missing_reset(self):
  for cls in (Kalman,KalmanFixed):
   k=cls([[1]],[[1]],[[0]],[[3]],[0],[[2]])
   scale=k.scale if cls is KalmanFixed else 1
   x,p=k.step([int(scale)])
   self.assertAlmostEqual(float(k.K[0][0])/scale,.4,places=6)
   self.assertAlmostEqual(float(p[0][0])/scale,1.2,places=6)
   k.step(None);self.assertIsNone(k.K);k.reset()
   self.assertEqual(float(np.asarray(k.x).ravel()[0]),0)
 def test_batch_information_oracle(self):
  # Static vector: batch weighted least squares is independent of recursion.
  rng=np.random.default_rng(99);h=np.array([[1.,.4],[-.3,1.]])
  q=np.zeros((2,2));r=np.array([[.4,.1],[.1,.6]]);p=np.array([[2.,.2],[.2,1.]])
  mean=np.array([-.2,.5]);kf=Kalman(np.eye(2),h,q,r,mean,p)
  info=np.linalg.solve(p,np.eye(2));rhs=info@mean
  for _ in range(30):
   z=h@np.array([1.,-2.])+rng.multivariate_normal([0,0],r)
   info+=h.T@np.linalg.solve(r,h);rhs+=h.T@np.linalg.solve(r,z)
   x,cov=kf.step(z)
   np.testing.assert_allclose(x,np.linalg.solve(info,rhs),atol=2e-14)
   np.testing.assert_allclose(cov,np.linalg.solve(info,np.eye(2)),atol=2e-14)
 def test_cv_fixed_precision_psd(self):
  f=np.array([[1.,1.,0,0],[0,1.,0,0],[0,0,1.,1.],[0,0,0,1.]])
  h=np.array([[1.,0,0,0],[0,0,1.,0]])
  args=(f,h,np.eye(4)*.002,np.eye(2)*.2,[0,0,0,0],np.eye(4))
  a=Kalman(*args);b=KalmanFixed(*args);rng=np.random.default_rng(8)
  largest=0
  for i in range(120):
   z=np.array([i*.01,-i*.015])+rng.normal(0,.05,2)
   x,p=a.step(None if i%9==0 else z)
   xx,pp=b.step(None if i%9==0 else np.floor(z*b.scale+.5).astype(int))
   largest=max(largest,np.max(np.abs(xx/b.scale-x)))
   self.assertGreaterEqual(np.linalg.eigvalsh(pp/b.scale).min(),-2e-6)
   np.testing.assert_array_equal(pp,pp.T)
  self.assertLess(largest,1e-5)
 def test_quantized_covariance_and_real_input(self):
  r=np.array([[1.49,2.51],[2.51,4.49]])/4096
  with self.assertRaises(ValueError):KalmanFixed(np.eye(2),np.eye(2),np.eye(2),r,[0,0],np.eye(2),frac=12)
  with self.assertRaises(ValueError):Kalman([[1j]],[[1]],[[0]],[[1]],[0],[[1]])
  with self.assertRaises(ValueError):Kalman([[1]],[[1]],[[0]],[[1]],[1j],[[1]])
 def test_precision_sweep(self):
  for dimension in (2,4):
   f=np.eye(dimension);f[0,1]=1
   h=np.eye(dimension)[:(1 if dimension==2 else 2)]
   args=(f,h,np.eye(dimension)*.01,np.eye(len(h))*.2,np.zeros(dimension),np.eye(dimension))
   for frac,budget in ((16,.001),(24,1e-5),(32,5e-8)):
    a=Kalman(*args);b=KalmanFixed(*args,frac=frac)
    for i in range(80):
     z=np.sin(i*.07+np.arange(len(h)))
     x,p=a.step(None if i%7==0 else z)
     xx,pp=b.step(None if i%7==0 else np.floor(z*b.scale+.5).astype(int))
     self.assertLess(np.max(abs(xx/b.scale-x)),budget)
     self.assertGreaterEqual(np.linalg.eigvalsh(pp/b.scale).min(),-budget)
    b.reset();np.testing.assert_array_equal(np.asarray(b.x).ravel(),np.zeros(dimension))
 def test_reject(self):
  for bad in (-1,float('nan')):
   with self.assertRaises(ValueError):Kalman([[1]],[[1]],[[bad]],[[1]],[0],[[1]])
  with self.assertRaises(ValueError):Kalman([[1]],[[1]],[[0]],[[0]],[0],[[1]])
  k=KalmanFixed([[1]],[[1]],[[0]],[[1]],[0],[[1]])
  with self.assertRaises(ValueError):k.step([.5])
  with self.assertRaises(OverflowError):k.step([1<<63])
if __name__=='__main__':unittest.main()
