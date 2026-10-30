import itertools,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_polar import RELIABILITY,information_positions,polar_transform,polar_encode,polar_decode
class PolarOracles(unittest.TestCase):
    def test_table_and_kronecker_matrix(self):
        self.assertEqual(len(set(RELIABILITY)),1024);self.assertEqual(RELIABILITY[:8],(1023,1022,1021,1019,1015,1007,1020,991))
        # Independent G_ij =1 iff j is a bitwise subset of i.
        for bits in itertools.product((0,1),repeat=8):
            expected=[sum(bits[i] for i in range(8) if j&i==j)%2 for j in range(8)]
            self.assertEqual(polar_transform(bits),expected)
        self.assertEqual(information_positions(1024,512),RELIABILITY[:512])
    def test_source_profiles_float_and_integer(self):
        rng=random.Random(1024512)
        for n,k in ((1024,512),(128,64),(32,16),(8,4)):
            for _ in range(3):
                bits=[rng.randrange(2) for _ in range(k)];word=polar_encode(bits,n);llr=[(1-2*b)*8 for b in word]
                for quant in (None,12):
                    result=polar_decode(llr,k,quant)
                    self.assertEqual(result.bits,bits)
                    self.assertTrue(all(result.u[i]==0 for i in set(range(n))-set(information_positions(n,k))))
    def test_small_sc_single_information_ml(self):
        rng=random.Random(711)
        for _ in range(24):
            llr=[rng.gauss(0,2) for _ in range(8)]
            costs=[sum(c*l for c,l in zip(polar_encode([b],8),llr)) for b in (0,1)]
            self.assertEqual(polar_decode(llr,1).bits,[int(costs[1]<costs[0])])
    def test_ties_saturation_minsum_and_negative(self):
        self.assertEqual(polar_decode([0]*1024,512,6).bits,[0]*512)
        result=polar_decode([1e6]*128,64,6,3)
        self.assertGreater(result.clips,0);self.assertTrue(all(isinstance(v,int) for v in result.llr_trace))
        bits=[1,0,1,1];word=polar_encode(bits,8);llr=[(1-2*b)*3 for b in word]
        self.assertEqual(polar_decode(llr,4,minsum=True).bits,polar_decode(llr,4,12,0).bits)
        self.assertNotEqual(polar_decode([-x for x in llr],4).bits,bits)
        for bad in ([0]*7,[float('nan')]*8):
            with self.assertRaises(ValueError):polar_decode(bad,4)
        with self.assertRaises(ValueError):polar_encode([True],8)
if __name__=='__main__':unittest.main()
