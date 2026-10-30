"""Independent carryless arithmetic/polynomial oracles and full source profiles."""
import itertools,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_gf import GF
from ext_code_rs import rs_encode,rs_decode,rs_syndromes
from ext_code_bch import bch_encode,bch_decode,bch_syndromes,bch_generator

def multiply(a,b,primitive=0x11d,m=8):
    product=0
    while b:
        if b&1:product^=a
        a<<=1;b>>=1
    while product.bit_length()>m:product^=primitive<<(product.bit_length()-m-1)
    return product

def independent_rs(data,nsym):
    # Descending generator multiplied with schoolbook polynomial arithmetic.
    generator=[1];root=1
    for _ in range(nsym):
        following=[0]*(len(generator)+1)
        for i,a in enumerate(generator):following[i]^=a;following[i+1]^=multiply(a,root)
        generator=following;root=multiply(root,2)
    work=list(data)+[0]*nsym
    for i in range(len(data)):
        factor=work[i]
        for j,c in enumerate(generator):work[i+j]^=multiply(factor,c)
    return list(data)+work[-nsym:]

class FieldOracles(unittest.TestCase):
    def test_polynomial_arithmetic(self):
        for primitive in (0x11d,0x171):
            f=GF(8,primitive)
            for a in range(256):
                for b in (0,1,2,3,19,127,255):self.assertEqual(f.mul(a,b),multiply(a,b,primitive))
                if a:self.assertEqual(f.div(f.mul(a,173),a),173)
        with self.assertRaises(ValueError):GF(8,0x101)
        with self.assertRaises(ZeroDivisionError):GF().div(1,0)

    def test_strict_public_field_inputs(self):
        f=GF()
        for bad in (-1,256,True,1.0):
            for call in (lambda:f.mul(bad,1),lambda:f.div(1,bad),lambda:f.eval([bad],1),lambda:f.poly_mul([bad],[1]),lambda:f.bm([bad])):
                with self.assertRaises(ValueError):call()
        for primitive in (-285,285.0,True,0x100):
            with self.assertRaises(ValueError):GF(8,primitive)
        with self.assertRaises(ValueError):f.solve([[1,0]],[1])
        with self.assertRaises(ValueError):rs_encode([True])
        with self.assertRaises(ValueError):bch_encode([False]*223)

class RSOracles(unittest.TestCase):
    def test_full_profile_errors_erasures_and_shortening(self):
        rng=random.Random(8012)
        for length in (1,43,210):
            data=[rng.randrange(256) for _ in range(length)];word=rs_encode(data)
            self.assertEqual(word,independent_rs(data,30));self.assertFalse(any(rs_syndromes(word)))
            self.assertEqual(rs_decode(word).data,data)
            for errors,erasures in ((1,0),(15,0),(0,30),(7,16),(0,1),(14,2)):
                received=word.copy();positions=rng.sample(range(len(word)),errors+erasures)
                for p in positions:received[p]^=rng.randrange(1,256)
                result=rs_decode(received,erasures=positions[:erasures])
                self.assertEqual((result.data,result.codeword),(data,word),(length,errors,erasures,result.status))
                self.assertEqual(set(result.corrected_positions),set(positions));self.assertEqual(result.status,'corrected')
            failed=rs_decode(word,erasures=list(range(31)))
            self.assertEqual((failed.status,failed.codeword),('failed',word))
    def test_failure_and_validation(self):
        word=rs_encode(list(range(210)));received=word.copy()
        for i in range(31):received[i]^=i+1
        result=rs_decode(received)
        self.assertEqual(result.status,'failed');self.assertEqual(result.codeword,received)
        for bad in ([-1],[256],[1.0]):
            with self.assertRaises(ValueError):rs_encode(bad)
        with self.assertRaises(ValueError):rs_decode(word,erasures=[1,1])

class BCHOracles(unittest.TestCase):
    def test_source_generator_and_full_shortened_profiles(self):
        self.assertEqual(bch_generator(),0x17e85b4ef)
        rng=random.Random(8881)
        for k in (223,207):
            for trial in range(3):
                bits=[rng.randrange(2) for _ in range(k)];word=bch_encode(bits)
                self.assertEqual(word[:k],bits);self.assertFalse(any(bch_syndromes(word)))
                number=0
                for b in word:number=(number<<1)|b
                generator=0x17e85b4ef
                while number.bit_length()>=generator.bit_length():number^=generator<<(number.bit_length()-generator.bit_length())
                self.assertEqual(number,0)
                for count in range(5):
                    locations=rng.sample(range(len(word)),count);received=word.copy()
                    for p in locations:received[p]^=1
                    result=bch_decode(received)
                    self.assertEqual((result.data,result.codeword),(bits,word))
                    self.assertEqual(set(result.corrected_positions),set(locations))
    def test_small_exhaustive_payload_error_patterns(self):
        # BCH15,7,t2 (GF16/0x13): all128 codewords and <=2 errors on every word.
        words=[bch_encode(bits,4,2,0x13) for bits in itertools.product((0,1),repeat=7)]
        self.assertEqual(len({tuple(w) for w in words}),128)
        self.assertEqual(min(sum(w) for w in words if any(w)),5)
        masks=[()]+[(i,) for i in range(15)]+list(itertools.combinations(range(15),2))
        for word in words:
            for positions in masks:
                received=word.copy()
                for p in positions:received[p]^=1
                self.assertEqual(bch_decode(received,4,2,0x13).codeword,word)
    def test_failure_and_negative(self):
        word=bch_encode([0]*223);word[:8]=[1]*8
        result=bch_decode(word)
        self.assertEqual(result.status,'failed');self.assertEqual(result.codeword,word)
        with self.assertRaises(ValueError):bch_encode([0]*224)
        with self.assertRaises(ValueError):bch_decode([0]*32)

if __name__=='__main__':unittest.main()
