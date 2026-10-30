import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common'/'python'))
import copy
import unittest
import numpy as np
from scipy import signal
from ext_signal_sos import SOSFilter,SOSFilterFixed

class TestSOS(unittest.TestCase):
    def test_float_complex_scipy(self):
        rng=np.random.default_rng(918);x=rng.normal(size=1024)+1j*rng.normal(size=1024)
        for ns in [1,2,4]:
            for kind in ['lowpass','highpass']:
                sos=signal.butter(ns*2,.27,btype=kind,output='sos')
                np.testing.assert_allclose(SOSFilter(sos).process(x),signal.sosfilt(sos,x),atol=2e-13)
    def test_integer_hand_recurrence(self):
        sos=[[.5,.25,0,1,-.5,.125]];m=SOSFilterFixed(sos)
        q=np.rint(np.array(sos[0])*2**28).astype(np.int64).tolist();s1=s2=0
        for x in [1200,-1500,0,3100]+[0]*200:
            y=min(131071,max(-131071,(q[0]*x+s1+2**27)>>28))
            s1,s2=q[1]*x-q[4]*y+s2,q[2]*x-q[5]*y
            self.assertEqual(m.push(x),(y,0))
    def test_fixed_scipy_error(self):
        rng=np.random.default_rng(77);x=rng.integers(-3000,3001,size=2048);errors=[]
        for ns in [1,2,4]:
            for kind in ['lowpass','highpass']:
                sos=signal.butter(2*ns,.3,btype=kind,output='sos');m=SOSFilterFixed(sos)
                y=np.array(m.process(x))[:,0];e=float(np.sqrt(np.mean((y-signal.sosfilt(sos,x))**2)));errors.append(e)
                self.assertLess(e,12)
        self.assertGreater(max(errors),0)
    def test_state_validation_and_reset(self):
        for cls in [SOSFilter,SOSFilterFixed]:
            m=cls([[1,0,0,1,-.9,0]]);m.push(100)
            old=copy.deepcopy(m.__dict__)
            for bad in [float('nan'),True,'a']:
                with self.assertRaises(ValueError):m.push(bad)
                self.assertEqual(repr(m.__dict__),repr(old))
            m.push(0,False);self.assertEqual(repr(m.__dict__),repr(old))
            for bad in [[[1,0,0,1,-1,0]],[[1,0,0,0,0,0]],[[1,0,0,1,float('nan'),0]]]:
                with self.assertRaises(ValueError):m.configure(bad)
                self.assertEqual(repr(m.__dict__),repr(old))
            m.reset();self.assertEqual(m.push(0),(0,0) if cls is SOSFilterFixed else 0j)
    def test_quantized_stability_and_state_saturation(self):
        SOSFilterFixed([[1,0,0,1,-.999,0]])
        with self.assertRaises(ValueError):SOSFilterFixed([[1,0,0,1,-(1-1e-12),0]])
        m=SOSFilterFixed([[7,7,7,1,-.99,0]],state_bits=40)
        y=m.process([131071]*20)
        self.assertGreater(m.clipping_count,0)
        self.assertTrue(all(abs(v)<=131071 for row in y for v in row))
        self.assertTrue(all(abs(v)<2**39 for c in m.state for row in c for v in row))
    def test_first_order_and_parameter_rejection(self):
        m=SOSFilterFixed([[.2,0,0,1,-.8,0]]);self.assertEqual(len(m.sos),1)
        for kw in [dict(coef_bits=True),dict(coef_bits=29),dict(state_bits=39)]:
            with self.assertRaises(ValueError):SOSFilterFixed([[1,0,0,1,0,0]],**kw)
        with self.assertRaises(ValueError):SOSFilterFixed([[9,0,0,1,0,0]])
    def test_near_unit_resonator_step_rails_and_limit_cycle(self):
        # Quantized feedback may retain a small bounded zero-input limit cycle.
        r=.995;theta=.19*np.pi
        sos=[[.001,0,0,1,-2*r*np.cos(theta),r*r]]
        m=SOSFilterFixed(sos)
        drive=[20000]+[0]*7999
        y=np.array(m.process(drive))[:,0]
        oracle=signal.sosfilt(sos,drive)
        self.assertLess(max(abs(y-oracle)),15)
        residue=int(max(abs(y[-1000:])))
        self.assertLessEqual(residue,15)
        self.assertLess(max(abs(y[-1000:])),max(abs(y[:1000])))
        # Unit-DC-gain first-order step settles; full rails exercise output clipping.
        m=SOSFilterFixed([[.125,0,0,1,-.875,0]])
        step=np.array(m.process([30000]*1024))[:,0]
        self.assertLessEqual(abs(int(step[-1])-30000),4)
        m=SOSFilterFixed([[2,0,0,1,0,0]])
        self.assertEqual(m.push(131071),(131071,0))
        self.assertEqual(m.push(-131072),(-131071,0))
        self.assertEqual(m.clipping_count,2)
        for bad in [np.array([[1+1j,0,0,1,0,0]]),np.array([[1+0j,0,0,1,0,0]])]:
            with self.assertRaises(ValueError):SOSFilter(bad)

    def test_review_negative_ties_atomic_batch_and_bool_coefficients(self):
        m=SOSFilterFixed([[.5,0,0,1,0,0]])
        self.assertEqual([m.push(v)[0] for v in [-1,1,-3,3,-5,5]],[0,1,-1,2,-2,3])
        for cls in [SOSFilter,SOSFilterFixed]:
            with self.assertRaises(ValueError):cls([[True,False,False,True,False,False]])
            m=cls([[1,0,0,1,-.5,0]]);before=repr(m.__dict__)
            with self.assertRaises(ValueError):m.process([1,2,'bad'])
            self.assertEqual(repr(m.__dict__),before)
        # Quantized feedback deadband is bounded, rather than guaranteed to vanish.
        m=SOSFilterFixed([[1,0,0,1,-.99,0]])
        y=m.process([131071]+[0]*5000)
        self.assertEqual(max(abs(v[0]) for v in y[-1000:]),49)

if __name__=='__main__':unittest.main()
