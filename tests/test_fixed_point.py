"""Independent arithmetic checks and cycle/reset/stall contracts for initial RTL."""
from fractions import Fraction
from pathlib import Path
import random
import sys
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from fixed_point import QFormat, QuantizationStats, round_shift, complex_add, complex_multiply, ElasticPipeline


class FixedPointTests(unittest.TestCase):
    def test_rounding_exhaustive_against_rational_arithmetic(self):
        for raw in range(-513,514):
            for drop in range(-3,10):
                self.assertEqual(round_shift(raw,drop),round(Fraction(raw)*Fraction(2)**(-drop)))

    def test_ties_and_asymmetric_signed_limits(self):
        q=QFormat(4,1)
        self.assertEqual([q.quantize(x) for x in (-.75,-.25,.25,.75)],[-2,0,0,2])
        self.assertEqual(q.quantize(-4),-8)
        self.assertEqual(q.quantize(4),7)
        self.assertEqual(q.quantize(3.75),7) # rounding crosses the positive limit

    def test_saturation_flags_and_stats(self):
        q=QFormat(4,2);stats=QuantizationStats()
        self.assertEqual(q.requantize(31,4,stats),(7,True))
        self.assertEqual(q.requantize(-40,4,stats),(-8,True))
        self.assertEqual(q.requantize(-32,4,stats),(-8,False))
        self.assertEqual((stats.values,stats.rounded,stats.overflows),(3,1,2))

    def test_formats_and_nonfinite_input_rejected(self):
        for args in ((1,0),(4,-1),(4,4),(4.5,1),(True,0)):
            with self.assertRaises(ValueError):QFormat(*args)
        for value in (float('nan'),float('inf'),1j):
            with self.assertRaises(ValueError):QFormat(8,4).quantize(value)

    def test_twos_complement_roundtrip(self):
        q=QFormat(8,3)
        for raw in range(q.minimum,q.maximum+1):self.assertEqual(q.decode_bits(q.encode_bits(raw)),raw)
        with self.assertRaises(ValueError):q.decode_bits(256)
        with self.assertRaises(ValueError):q.encode_bits(128)

    def test_complex_known_answers(self):
        q=QFormat(8,4)
        self.assertEqual(complex_multiply((16,16),(16,-16),q,q),((32,0),0))
        self.assertEqual(complex_multiply((-128,-128),(-128,-128),q,q),((0,127),2))
        self.assertEqual(complex_add((127,-128),(1,-1),q,q),((127,-128),3))

    def test_requantization_left_shift(self):
        self.assertEqual(QFormat(8,6).requantize(-3,2),(-48,False))
        self.assertEqual(QFormat(8,6).requantize(8,2),(127,True))

    def test_pipeline_latency_throughput_stalls_reset(self):
        for latency in (1,2,4):
            model=ElasticPipeline(latency,lambda x:x*2)
            model.tick(reset=True)
            for cycle in range(20):
                result=model.tick(valid=True,data=cycle,last=cycle==19)
                self.assertTrue(result['accepted'])
                self.assertEqual(result['emitted'],cycle>=latency)
                if result['emitted']:self.assertEqual(result['output'][0],2*(cycle-latency))
            held=model.tick(ready=False)['output']
            for _ in range(12):
                result=model.tick(valid=True,data=99,ready=False)
                self.assertFalse(result['accepted']);self.assertEqual(result['output'],held)
            reset=model.tick(valid=True,data=10,ready=False,reset=True)
            self.assertFalse(reset['accepted']);self.assertFalse(reset['emitted'])
            for _ in range(latency):self.assertFalse(model.tick()['emitted'])

    def test_random_pipeline_no_loss_or_reordering(self):
        rng=random.Random(119);model=ElasticPipeline(4,lambda x:x)
        queue=[];next_value=0
        for _ in range(3000):
            valid=rng.random()<.7;reset=rng.random()<.03
            result=model.tick(valid=valid,data=next_value,last=next_value%13==12,ready=rng.random()<.6,reset=reset)
            if reset:queue.clear()
            else:
                if result['emitted']:self.assertEqual(result['output'],queue.pop(0))
                if result['accepted']:
                    queue.append((next_value,next_value%13==12));next_value+=1
        for _ in range(5):
            result=model.tick()
            if result['emitted']:self.assertEqual(result['output'],queue.pop(0))
        self.assertFalse(queue)


if __name__=='__main__':unittest.main()
