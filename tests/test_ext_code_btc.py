import itertools,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_btc import btc_encode,btc_decode,component_decode,component_exact,data_positions
from ext_code_basics import hamming_encode
class BTCOracles(unittest.TestCase):
    def test_component_spc_exact_and_chase_candidate_oracle(self):
        rng=random.Random(821)
        for _ in range(10):
            a=[rng.uniform(-3,3) for _ in range(8)];result=component_decode(a,'spc')
            for x,y in zip(result.posterior,component_exact(a,'spc')):self.assertAlmostEqual(x,y)
        for n,k in ((8,4),(16,11)):
            book=[hamming_encode(list(bits)) for bits in itertools.product((0,1),repeat=k)]
            for _ in range(4):
                a=[rng.uniform(-3,3) for _ in range(n)];hard=[int(v<0) for v in a];least=sorted(range(n),key=lambda i:(abs(a[i]),i))[:3 if n==8 else 4]
                candidates=[word for word in book if sum(x!=y for i,(x,y) in enumerate(zip(word,hard)) if i not in least)<=1]
                expected=sorted((sum(abs(v) for v,x,y in zip(a,hard,w) if x!=y),sum(b<<i for i,b in enumerate(w)),w) for w in candidates)
                result=component_decode(a)
                self.assertEqual(result.candidates,[(v,w) for v,_,w in expected])
                best=expected[0];second=expected[1] if len(expected)>1 else best;worst=expected[-1]
                ext=[(1-2*b)*(second[0]-best[0])-a[i] if b!=second[2][i] else (1-2*b)*(worst[0]-best[0])/4 for i,b in enumerate(best[2])]
                for x,y in zip(result.extrinsic,ext):self.assertAlmostEqual(x,y)
    def test_product_profiles_syndromes_soft_iterations_and_error(self):
        rng=random.Random(164)
        for n,kind in ((8,'spc'),(8,'eham'),(16,'eham')):
            k=len(data_positions(n,kind));bits=[rng.randrange(2) for _ in range(k*k)];word=btc_encode(bits,n,kind)
            def valid(w):
                pos=data_positions(n,kind);data=[w[i] for i in pos]
                return w==(hamming_encode(data) if kind=='eham' else data+[sum(data)%2])
            self.assertTrue(all(valid(row) for row in word));self.assertTrue(all(valid([word[i][j] for i in range(n)]) for j in range(n)))
            llr=[[(1-2*b)*5 for b in row] for row in word]
            for q in (None,8):
                result=btc_decode(llr,kind,quant_bits=q,early_stop=True)
                self.assertEqual(result.bits,bits);self.assertTrue(result.valid);self.assertEqual(result.iterations,1)
                self.assertEqual(len(result.trace),2)
                noisy=[row.copy() for row in llr];noisy[2][3]*=-.05
                result=btc_decode(noisy,kind,quant_bits=q)
                self.assertEqual(result.bits,bits);self.assertTrue(result.valid);self.assertEqual(result.iterations,4)
            self.assertNotEqual(btc_decode([[-x for x in row] for row in llr],kind).bits,bits)
    def test_integer_clipping_and_validation(self):
        result=btc_decode([[1e6]*8 for _ in range(8)],quant_bits=5)
        self.assertGreater(result.trace[-1]['clips'],0)
        self.assertTrue(all(isinstance(v,int) for t in result.trace for v in t['posterior_first8']))
        with self.assertRaises(ValueError):btc_decode([[0]*7 for _ in range(8)])
        with self.assertRaises(ValueError):btc_encode([True]*16)
        with self.assertRaises(ValueError):btc_decode([[float('nan')]*8 for _ in range(8)])
if __name__=='__main__':unittest.main()
