import itertools,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_tcm import tcm_transition,tcm_map_indices,tcm_encode,tcm_decode

def source_map(x):
    bit=lambda n:x>>n&1
    concat=lambda a,b,c:4*bit(a)+2*bit(b)+bit(c)
    base=concat(8,5,1);a=4*bit(7)+2*bit(3);b=4*bit(6)+2*bit(2);c=4*bit(4)+2*bit(0)
    return base,(base+a)&7,(base+b)&7,(base+a+b+c)&7

def cost(groups,reference):return sum(abs(a-b)**2 for g,r in zip(groups,reference) for a,b in zip(g,r))
class TCMOracles(unittest.TestCase):
    def test_source_mapper_and_transitions(self):
        for x in range(512):self.assertEqual(tcm_map_indices(x),source_map(x))
        for s in range(64):
            bits=[s>>j&1 for j in range(6)]
            for x in range(8):
                expected=(bits[0]<<5)|sum(bits[j]<<(j-1) for j in range(2,6))|(bits[1]^bits[0])
                for j,mask in enumerate((3,10,20)):
                    if x>>j&1:expected^=mask
                self.assertEqual(tcm_transition(s,x),expected)
    def test_source_differential_pipeline_golden(self):
        from ext_code_tcm import POINTS
        self.assertEqual(tcm_encode([1,0]),[[POINTS[1]]*4,[POINTS[1],POINTS[1],POINTS[1],POINTS[3]]])

    def test_float_and_integer_noiseless_noisy(self):
        rng=random.Random(448)
        payload=[rng.randrange(256) for _ in range(12)]
        symbols=tcm_encode(payload)
        self.assertEqual(tcm_decode(symbols).payloads,payload)
        fixed=tcm_decode(tcm_encode(payload,True),True)
        self.assertEqual(fixed.payloads,payload);self.assertTrue(all(isinstance(v,int) for t in fixed.metric_trace for v in t))
        noisy=[[v+complex(rng.gauss(0,.025),rng.gauss(0,.025)) for v in group] for group in symbols]
        self.assertEqual(tcm_decode(noisy).payloads,payload);self.assertEqual(tcm_decode(noisy,True).payloads,payload)
        self.assertNotEqual(tcm_decode([[v*1j for v in group] for group in symbols]).payloads,payload)
    def test_exhaustive_short_frame_ml(self):
        rng=random.Random(102)
        received=[[complex(rng.uniform(-1,1),rng.uniform(-1,1)) for _ in range(4)] for _ in range(2)]
        decoded=tcm_decode(received)
        best=min(cost(received,tcm_encode(payload)) for payload in itertools.product(range(256),repeat=2))
        self.assertAlmostEqual(cost(received,tcm_encode(decoded.payloads)),best)
        # Integer word-domain exhaustive independent candidates, quantized cost.
        fixed=tcm_decode(received,True);self.assertEqual(len(fixed.payloads),2)
    def test_validation_and_reset(self):
        self.assertEqual(tcm_encode([5,7]),tcm_encode([5,7]))
        with self.assertRaises(ValueError):tcm_encode([True])
        with self.assertRaises(ValueError):tcm_decode([[0]*3])
        with self.assertRaises(ValueError):tcm_decode([[float('nan')]*4])
if __name__=='__main__':unittest.main()
