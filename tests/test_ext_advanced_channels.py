import sys,unittest
from pathlib import Path
import numpy as np
from scipy.special import j0
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_advanced_channels import *
class TestChannels(unittest.TestCase):
 def test_taus_oracle_seed_stall(self):
  # Source nonblocking emission is old XOR, independent scalar bit recurrence.
  a,b,c=2,8,16;gen=Tausworthe()
  for i in range(100):
   expected=a^b^c;self.assertEqual(gen.next(False),expected);self.assertEqual(gen.next(),expected)
   aa=((a*8192)%2**32)^a;bb=((b*4)%2**32)^b;cc=((c*8)%2**32)^c
   a=(((a&0xfffffffe)*4096)^(aa//2**19))%2**32
   b=(((b&0xfffffff8)*16)^(bb//2**25))%2**32
   c=(((c&0xfffffff0)*131072)^(cc//2**11))%2**32
  gen.reset();self.assertEqual(gen.next(),26)
 def test_awgn_statistics_fixed_reset(self):
  for fixed in (False,True):
   g=AWGN(.08,seeds=(123,456,789),fixed=fixed)
   y=np.asarray([g.next() for _ in range(180000)])
   z=y[:,0]/Q+1j*y[:,1]/Q if fixed else y
   self.assertLess(abs(z.mean()),.001)
   self.assertAlmostEqual(np.mean(abs(z)**2),2*.08**2,delta=.0002)
   self.assertLess(abs(np.corrcoef(z.real,z.imag)[0,1]),.012)
   self.assertLess(abs(np.mean(z.real**4)/np.mean(z.real**2)**2-3),.08)
   g.reset();first=g.next(accept=False);self.assertEqual(first,g.next());g.reset();self.assertEqual(first,g.next())
 def test_fixed_boxmuller_error_and_saturation(self):
  a=AWGN(.05,(128,923,99));b=AWGN(.05,(128,923,99),True)
  errors=[]
  for _ in range(2000):
   x=a.next();u,v=b.next();errors.append(abs(x-(u+1j*v)/Q))
  self.assertLess(np.quantile(errors,.99),.0001)
  g=AWGN(1,(123,456,789),True)
  self.assertTrue(any(max(abs(x) for x in g.next((Q-1,Q-1)))>=Q-1 for _ in range(100)))
 def test_rayleigh_ensemble_j0_and_fixed(self):
  lags=np.array([0,1,5,10,20]);cross=np.zeros(len(lags),complex);power=0
  for seed in range(500):
   g=Rayleigh(.02,128,seed);h0=g.next(False)
   vals=np.exp(1j*(g.initial[:,None]+2*np.pi*.02*np.cos(g.theta[:,None])*lags)).sum(0)/np.sqrt(128)
   cross+=vals*np.conj(h0);power+=abs(h0)**2
  self.assertLess(np.max(abs(cross/power-j0(2*np.pi*.02*lags))),.09)
  a=Rayleigh(.007,128,7);b=Rayleigh(.007,128,7,True)
  for _ in range(500):
   x=a.next();u,v=b.next();self.assertLess(abs(x-(u+1j*v)/Q),.002)
  self.assertGreater(abs(a.next().imag),.01)
  b.reset();self.assertEqual(b.next(False),b.next())
 def test_multipath_delay_reset(self):
  for fixed in (False,True):
   a=Multipath([3],[1],0,4,fixed)
   seq=[(Q//8,0)]+[(0,0)]*6 if fixed else [.125]+[0j]*6
   y=[a.next(x) for x in seq]
   zero=(0,0) if fixed else 0j
   self.assertTrue(all(v==zero for v in y[:3]+y[4:]));self.assertNotEqual(y[3],zero)
   a.reset();self.assertEqual(y,[a.next(x) for x in seq])
 def test_reject_before_mutation(self):
  for fixed in (False,True):
   g=AWGN(.1,(123,456,789),fixed);a=g.x.state[:];b=g.y.state[:]
   with self.assertRaises(ValueError):g.next((0.5,0) if fixed else np.nan)
   self.assertEqual(a,g.x.state);self.assertEqual(b,g.y.state)
   r=Rayleigh(.01,64,3,fixed)
   with self.assertRaises(ValueError):r.apply((0.1,0) if fixed else np.nan)
   self.assertEqual(r.n,0)
  for g in (Tausworthe(),AWGN(),Rayleigh(),Multipath([0],[1])):
   with self.assertRaises(ValueError):
    if isinstance(g,Multipath):g.next(0,accept=1)
    else:g.next(accept=1)
  with self.assertRaises(ValueError):Multipath([0],[1j])
 def test_rayleigh_distribution_power_and_modem(self):
  # Independent realizations avoid treating correlated time samples as IID.
  from scipy.stats import kstest
  vals=np.array([Rayleigh(.03,64,s).next() for s in range(5000)])
  self.assertLess(abs(vals.mean()),.035);self.assertAlmostEqual(np.mean(abs(vals)**2),1,delta=.045)
  self.assertLess(kstest(abs(vals),'rayleigh',args=(0,1/np.sqrt(2))).statistic,.025)
  static=Rayleigh(0,64,1);v=static.next()
  self.assertEqual(v,static.next());self.assertEqual(v,static.next())
  # Coherent QPSK: independent noise, known channel; disabled correction is
  # the negative control. Deep fades counted, equalization not noise-free.
  rng=np.random.default_rng(19);bits=rng.integers(0,2,(12000,2));symbols=((2*bits[:,0]-1)+1j*(2*bits[:,1]-1))/np.sqrt(2)
  for fd in (0,.012):
   channel=Rayleigh(fd,64,5);h=np.array([channel.next() for _ in symbols]);noise=(rng.normal(size=len(h))+1j*rng.normal(size=len(h)))*.025
   rx=h*symbols+noise;corrected=rx*np.conj(h)
   detected=np.c_[corrected.real>0,corrected.imag>0];bad=np.c_[rx.real>0,rx.imag>0]
   ber=np.mean(detected!=bits);disabled=np.mean(bad!=bits)
   self.assertLess(ber,.015);self.assertGreater(disabled,ber+.1)
 def test_invalid(self):
  for seed in ((-1,0,0),(True,0,0)):
   with self.assertRaises(ValueError):Tausworthe(seed)
  with self.assertRaises(ValueError):Rayleigh(.5)
  with self.assertRaises(ValueError):AWGN(float('nan'))
if __name__=='__main__':unittest.main()
