import itertools,random,sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_turbo import (BLOCKS,TurboResult,constituent_transition,constituent_encode,turbo_interleaver,turbo_encode,turbo_decode,maxlog_map)
def independent_step(state,bit):
    s=[state>>i&1 for i in range(4)];feedback=bit^s[1]^s[0]
    return sum(b<<i for i,b in enumerate((s[1],s[2],s[3],feedback))),[bit,feedback^s[3]^s[1]^s[0],feedback^s[2]^s[0],feedback^s[3]^s[2]^s[1]^s[0]]
def reference_constituent(bits,state=0):
    rows=[]
    for b in bits:
        state,row=independent_step(state,b);rows.append(row)
    for _ in range(4):
        b=(state&1)^(state>>1&1);state,row=independent_step(state,b);rows.append(row)
    return rows,state

def source_address_sim(n):
    k=n//8;p=(31,37,43,47);j=0;done=False;t=0;acc=0;increment=p[1];addr=0;paddr=2;out=[]
    for _ in range(n):
        out.append((paddr&~1)|int(not(addr&1)))
        nextpaddr=(((t+1)&3)<<1)+(((acc+(0 if addr&1 else 21))%k)<<3)
        if not addr&1:
            jnext=0 if done else j+1;donenext=(j==k-2)
            if done:t=(t+3)&3;acc=0;increment=p[(t+1)&3]
            else:acc=(acc+increment)%k
            j=jnext;done=donenext
        addr+=1;paddr=nextpaddr
    return out
class TurboOracles(unittest.TestCase):
    def test_source_trellis_interleaver_and_encoder(self):
        for state in range(16):
            for bit in (0,1):
                nxt,row=constituent_transition(state,bit);expected,code=independent_step(state,bit)
                self.assertEqual((nxt,list(row)),(expected,code))
        for n in BLOCKS:
            pi=turbo_interleaver(n);self.assertEqual(sorted(pi),list(range(n)))
            self.assertEqual(list(pi),source_address_sim(n))
        self.assertEqual(turbo_interleaver(1784)[:4],(3,170,299,466))
        bits=[i%7<3 for i in range(1784)];bits=[int(v) for v in bits];pi=turbo_interleaver(len(bits))
        first,state0=reference_constituent(bits);second,state1=reference_constituent([bits[p] for p in pi]);self.assertEqual((state0,state1),(0,0))
        expected=[b for a,c in zip(first,second) for b in (a[0],a[1],a[2],a[3],c[1],c[3])]
        self.assertEqual(turbo_encode(bits),expected)
    def test_bcjr_against_exhaustive_soft_posterior(self):
        rng=random.Random(161)
        for fixed in (False,True):
            n=4;length=n+4;sy=[rng.randint(-5,5) for _ in range(length)];pa=[[rng.randint(-5,5) for _ in range(3)] for _ in range(length)];ap=[rng.randint(-3,3) for _ in range(n)]+[0]*4
            paths=[]
            for bits in itertools.product((0,1),repeat=n):
                rows,state=reference_constituent(bits);self.assertEqual(state,0)
                metric=sum((1-row[0]*2)*(s+p)+sum((1-b*2)*v for b,v in zip(row[1:],channel)) for row,s,p,channel in zip(rows,sy,ap,pa))/2
                paths.append((bits,metric))
            result=maxlog_map(sy,pa,ap,fixed)
            for i in range(n):
                oracle=max(m for b,m in paths if b[i]==0)-max(m for b,m in paths if b[i]==1)
                self.assertEqual(result.posterior[i],oracle);self.assertEqual(result.extrinsic[i],oracle-sy[i]-ap[i])
            if fixed:self.assertTrue(all(isinstance(v,int) for v in result.posterior))
            beta0=[]
            for start in range(16):
                scores=[]
                for bits in itertools.product((0,1),repeat=n):
                    rows,_=reference_constituent(bits,start)
                    scores.append(sum((1-2*row[0])*(s+p)+sum((1-2*b)*v for b,v in zip(row[1:],channel)) for row,s,p,channel in zip(rows,sy,ap,pa)))
                beta0.append(max(scores))
            maximum=max(beta0)
            self.assertEqual(result.trace['beta_first8'][0],[v-maximum for v in beta0])
    def test_full_blocks_noiseless_float_integer_and_iterations(self):
        rng=random.Random(1301)
        for n,iterations in ((1784,4),(8920,10)):
            bits=[rng.randrange(2) for _ in range(n)];word=turbo_encode(bits);llr=[(1-2*b)*4 for b in word]
            for q in (None,8):
                result=turbo_decode(llr,iterations=iterations,quant_bits=q)
                self.assertEqual(result.bits,bits);self.assertEqual(result.iterations,iterations);self.assertEqual(len(result.trace),2*iterations)
            stopped=turbo_decode(llr,iterations=4,quant_bits=8,early_stop=True)
            self.assertEqual(stopped.bits,bits);self.assertEqual(stopped.iterations,2)
    def test_bounded_noise_improves_hard_bypass(self):
        rng=random.Random(619);n=1784;bits=[rng.randrange(2) for _ in range(n)];word=turbo_encode(bits);sigma=1.2
        llr=[2*((1-2*b)+rng.gauss(0,sigma))/(sigma*sigma) for b in word]
        hard=sum(int(llr[6*i]<0)!=b for i,b in enumerate(bits))
        result=turbo_decode(llr,iterations=4);fixed=turbo_decode(llr,iterations=4,quant_bits=8,self_correct=True)
        errors=sum(a!=b for a,b in zip(result.bits,bits));qerrors=sum(a!=b for a,b in zip(fixed.bits,bits))
        self.assertGreater(hard,100);self.assertLess(errors,hard//4);self.assertLess(qerrors,hard//4)
        print('CCSDS1784 seed619 sigma1.2 hard_errors',hard,'float_errors',errors,'fixed_SC_errors',qerrors)
    def test_clipping_reset_invalid(self):
        bits=[0]*1784;word=turbo_encode(bits);llr=[1e6]*len(word)
        a=turbo_decode(llr,iterations=1,quant_bits=4,metric_bits=8,extrinsic_bits=5)
        self.assertEqual(a.bits,bits);self.assertGreater(sum(t['clips'] for t in a.trace),0)
        self.assertEqual(turbo_decode([0]*len(word),iterations=1).bits,bits)
        for bad in ([0]*30,[float('nan')]*len(word)):
            with self.assertRaises(ValueError):turbo_decode(bad)
        with self.assertRaises(ValueError):turbo_encode([True]*1784)
if __name__=='__main__':unittest.main()
