import cmath,math,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_llr import constellation,bit_labels,llr,quantized_demapper,q8_adapter
from psk_fixed import QAM16_LEVELS,QAM64_LEVELS
from ldpc_fixed import quantize_llr
class LLROracles(unittest.TestCase):
    def test_constellations_gray_labels_and_signs(self):
        for order in (2,4,16,64):
            points=constellation(order);labels=bit_labels(order);width=order.bit_length()-1
            self.assertAlmostEqual(sum(abs(v)**2 for v in points)/order,1)
            self.assertEqual(sorted(labels),list(range(order)))
            metrics=llr(points,order,.01)
            for row,label in zip(metrics,labels):self.assertEqual([int(v<0) for v in row],[(label>>b)&1 for b in reversed(range(width))])
            if order>=16:
                expected=QAM16_LEVELS if order==16 else QAM64_LEVELS
                self.assertEqual([(int(v.real),int(v.imag)) for v in constellation(order,False)],list(expected))
                # Every horizontal/vertical adjacent physical point changes one label bit.
                for i,a in enumerate(points):
                    for j,b in enumerate(points):
                        if abs(abs(a-b)-2/math.sqrt(10 if order==16 else 42))<1e-10:self.assertEqual((labels[i]^labels[j]).bit_count(),1)
    def test_exact_probability_oracle_and_bpsk_formula(self):
        rng=random.Random(642)
        for order in (2,4,16,64):
            p=constellation(order);labels=bit_labels(order);width=order.bit_length()-1
            samples=[complex(rng.uniform(-1,1),rng.uniform(-1,1)) for _ in range(6)]
            for sample,row in zip(samples,llr(samples,order,.8,'exact')):
                probs=[math.exp(-abs(sample-v)**2/.8) for v in p]
                for idx,b in enumerate(reversed(range(width))):
                    expected=math.log(sum(v for v,l in zip(probs,labels) if not l>>b&1)/sum(v for v,l in zip(probs,labels) if l>>b&1))
                    self.assertAlmostEqual(row[idx],expected)
        self.assertAlmostEqual(llr([.3+.2j],2,.7)[0][0],4*.3/.7)
    def test_integer_distance_error_saturation_q8_adapter(self):
        rng=random.Random(104)
        for order in (2,4,16,64):
            points=constellation(order);labels=bit_labels(order);scale=1<<14
            ip=[(round(v.real*scale),round(v.imag*scale)) for v in points]
            samples=[v+complex(rng.uniform(-.03,.03),rng.uniform(-.03,.03)) for v in points]
            iq=[(round(v.real*scale),round(v.imag*scale)) for v in samples]
            fixed=quantized_demapper(iq,ip,labels,round(.7*scale*scale));floating=llr(samples,order,.7)
            self.assertLess(max(abs(q/256-f) for qr,fr in zip(fixed,floating) for q,f in zip(qr,fr)),.01)
        self.assertEqual(quantized_demapper([(0,0)],[(100,0),(-100,0)],[0,1],1),[[0]])
        self.assertEqual(quantized_demapper([(10000,0)],[(100,0),(-100,0)],[0,1],1),[[32767]])
        values=[-1000,-1.25,0,.5,1000]
        self.assertEqual(q8_adapter(values),quantize_llr(values))
        with self.assertRaises(ValueError):llr([1],16,0)
        with self.assertRaises(ValueError):quantized_demapper([(1.0,0)],[(1,0),(-1,0)],[0,1],1)
if __name__=='__main__':unittest.main()
