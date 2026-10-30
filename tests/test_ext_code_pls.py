import random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_pls import pls_encode,pls_decode,pls_map,pls_demod,pls_map_fixed,pls_demod_fixed,hadamard32
SCRAMBLE='0111000110011101100000111100100101010011010000100010110111111010'
ROWS=('1'*32,'0'*16+'1'*16,'00000000111111110000000011111111','00001111000011110000111100001111','00110011001100110011001100110011','01'*16)
def source_encoder(label):
    rm=[sum((label>>j&1)*int(ROWS[j][i]) for j in range(6))%2 for i in range(32)]
    return [(rm[i//2]^((label>>6)&(i%2)))^int(SCRAMBLE[i]) for i in range(64)]
def brute(llr):
    return min(range(128),key=lambda d:(-sum((1-2*b)*l for b,l in zip(source_encoder(d),llr)),d))
class PLSOracles(unittest.TestCase):
    def test_all_labels_bits_phase_and_fixed(self):
        for label in range(128):
            bits=pls_encode(label);self.assertEqual(bits,source_encoder(label))
            symbols=pls_map(bits)
            self.assertEqual(pls_decode(pls_demod(symbols)),label)
            self.assertEqual(pls_decode(pls_demod_fixed(pls_map_fixed(bits))),label)
            for i,(bit,symbol) in enumerate(zip(bits,symbols)):
                self.assertAlmostEqual(abs(symbol),1)
                self.assertEqual(symbol.real>0,(bit==0) if i%2==0 else (bit==1))
    def test_fht_against_direct_matrix_and_ml(self):
        rng=random.Random(328)
        for _ in range(50):
            values=[rng.uniform(-10,10) for _ in range(32)]
            expected=[sum(v*(-1 if (i&j).bit_count()%2 else 1) for i,v in enumerate(values)) for j in range(32)]
            for a,b in zip(hadamard32(values),expected):self.assertAlmostEqual(a,b)
            llr=[rng.gauss(0,2) for _ in range(64)]
            self.assertEqual(pls_decode(llr),brute(llr))
            q=[max(-16,min(15,round(v*4))) for v in llr]
            self.assertEqual(pls_decode(llr,5,4),brute(q))
        self.assertEqual(pls_decode([0]*64),0)
    def test_negative_scramble_phase_order_and_validation(self):
        label=57;bits=pls_encode(label);llr=[(1-2*b)*6 for b in bits]
        self.assertNotEqual(pls_decode(llr[::-1]),label)
        self.assertNotEqual(pls_decode([v*(-1 if s=='1' else 1) for v,s in zip(llr,SCRAMBLE)]),label)
        self.assertNotEqual(pls_decode(pls_demod([s*1j for s in pls_map(bits)])),label)
        with self.assertRaises(ValueError):pls_encode(True)
        with self.assertRaises(ValueError):pls_decode([0]*63)
        with self.assertRaises(ValueError):pls_demod([1],0)
if __name__=='__main__':unittest.main()
