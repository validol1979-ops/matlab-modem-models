import itertools,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_golay import golay_encode,golay_decode,golay_chase,golay_syndrome

class GolayOracles(unittest.TestCase):
    def test_matrix_all_codewords_distance_source_order(self):
        # Independent scalar matrix rows in source order, bit12..23 parity.
        rows=(0x7ff,0xee2,0xdc5,0xb8b,0xf16,0xe2d,0xc5b,0x8b7,0x96e,0xadc,0xdb8,0xb71)
        words=[]
        for data in range(4096):
            parity=0
            for row in rows:
                bit=0
                for j in range(12):bit^=(data>>j&1)*(row>>j&1)
                parity=(parity<<1)|bit
            expected=parity<<12|data;word=golay_encode(data);words.append(word)
            self.assertEqual(word,expected);self.assertEqual(golay_syndrome(word),0)
            self.assertEqual(golay_decode(word).data,data)
        self.assertEqual(len(set(words)),4096);self.assertEqual(min(w.bit_count() for w in words if w),8)
        self.assertEqual(golay_encode(1),0xb71001)
    def test_all_masks_to_radius3_and_radius4_failure(self):
        for data in (0,0xabc):
            word=golay_encode(data)
            for weight in range(4):
                for positions in itertools.combinations(range(24),weight):
                    received=word^sum(1<<i for i in positions);result=golay_decode(received)
                    self.assertEqual((result.data,result.codeword),(data,word))
            received=word^15;result=golay_decode(received)
            self.assertEqual((result.status,result.codeword),('failed',received))
    def test_soft_chase_and_independent_exhaustive_ml(self):
        codebook=[golay_encode(i) for i in range(4096)];rng=random.Random(24)
        for data in (1,0x3e4,0xabd,4095):
            word=codebook[data];llr=[(1-2*(word>>i&1))*8.0 for i in range(24)]
            for p in rng.sample(range(24),4):llr[p]*=-0.02
            oracle=max(codebook,key=lambda w:(sum((1-2*(w>>i&1))*v for i,v in enumerate(llr)),-w))
            floating=golay_chase(llr);fixed=golay_chase(llr,8,8)
            self.assertEqual(oracle,word);self.assertEqual(floating.codeword,oracle);self.assertEqual(fixed.codeword,oracle)
            self.assertLessEqual(len(floating.candidates),16)
            self.assertEqual(fixed.metric,int(fixed.metric))
        self.assertEqual(golay_chase([0]*24).codeword,0)
        self.assertEqual(golay_chase([1e6]*24,4,8).codeword,0)
    def test_negative(self):
        with self.assertRaises(ValueError):golay_encode(4096)
        with self.assertRaises(ValueError):golay_decode(-1)
        with self.assertRaises(ValueError):golay_chase([float('nan')]*24)

if __name__=='__main__':unittest.main()
