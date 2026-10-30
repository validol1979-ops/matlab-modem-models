"""Integer LDPC decoder / GF(2) encoder (ldpc_fixed) against research_core."""
from pathlib import Path
import json
import shutil
import sys
import tempfile
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import ldpc_fixed as d
import ldpc_cases
import sat_diag
from research_core import run

A=np.array([[1,1,0,1,0,0],[0,1,1,0,1,0],[1,0,1,0,0,1],[1,1,0,0,1,0],[0,1,1,1,0,0],[1,0,1,0,1,1]])
H=np.c_[np.eye(6,dtype=int),A]


class TestLdpcFixed(unittest.TestCase):
    def test_encode_model_case(self):
        bits=np.array([1,0,1,1,0,1])
        self.assertEqual(d.encode(list(bits),A.tolist()),list(run('gf2_encode',[6,6],bits,A.ravel()).real.astype(int)))

    def test_decode_model_cases(self):
        word=np.array(d.encode([1,0,1,1,0,1],A.tolist()))
        llr=(1-2*word)*6.;llr[7]*=-.12
        for mode in range(4):
            bits,post,_=d.decode(d.quantize_llr(llr),H.tolist(),20,mode)
            expected=run('ldpc',[6,12,20,mode,.8,.15],llr,H.ravel())
            with self.subTest(mode=mode):
                self.assertEqual(bits,list(word))
                self.assertEqual(bits,list(expected[:12].real.astype(int)))
                # Same posterior signs; the magnitudes follow the floating decoder.
                self.assertLess(np.max(abs(np.array(post)/256-expected[12:].real)),.1 if mode==0 else .02)

    def test_random_noisy_words(self):
        rng=np.random.default_rng(3);wins=0
        for trial in range(30):
            msg=rng.integers(0,2,6);word=np.array(d.encode(list(msg),A.tolist()))
            llr=(1-2*word)*2+rng.normal(size=12)*1.2
            for mode in range(4):
                bits,_,_=d.decode(d.quantize_llr(llr),H.tolist(),20,mode)
                ref=run('ldpc',[6,12,20,mode,.8,.15],llr,H.ravel())[:12].real.astype(int)
                wins+=list(bits)==list(ref)
        # Quantisation may change a marginal decision now and then, not more.
        self.assertGreater(wins,0.95*120)

    def test_rejects(self):
        with self.assertRaises(ValueError):d.decode([0]*12,H.tolist(),20,4)
        with self.assertRaises(ValueError):d.encode([1,0],A.tolist())


class ValueTrace(sat_diag.SatTrace):
    """Keeps every recorded (stage, preclamp value) so the counts can be recounted from the
    raw values, independently of what SatStats.record did."""
    def __init__(self):
        super().__init__(); self.values=[]
    def record(self,stage,value,limit,clamp='asym'):
        self.values.append((stage,value)); return super().record(stage,value,limit,clamp)


class TestLdpcSaturation(unittest.TestCase):
    """stats= instrumentation: bit-exact default, exact stage counts, vector-level evidence."""

    def test_stats_never_changes_the_result(self):
        rng=np.random.default_rng(11)
        Hb,_,_=ldpc_cases.code_for('big')
        for code,Hx,n,k in (('model',H.tolist(),12,6),('big',Hb,24,12)):
            for trial in range(8):
                word=np.array(d.encode(list(rng.integers(0,2,k)),A.tolist() if code=='model' else ldpc_cases.code_for('big')[1]))
                llr=d.quantize_llr((1-2*word)*2+rng.normal(size=n)*1.2)
                for mode in range(4):
                    plain=d.decode(llr,Hx,10,mode,.8,.15)
                    with self.subTest(code=code,trial=trial,mode=mode):
                        self.assertEqual(plain,d.decode(llr,Hx,10,mode,.8,.15,stats=sat_diag.SatTrace()))

    def test_stats_counts_are_exact(self):
        word=np.array(d.encode([1,0,1,1,0,1],A.tolist()))
        llr=d.quantize_llr((1-2*word)*6.*4);llr[7]*=-.12*400
        edges=int(H.sum());n=12
        for mode in range(4):
            trace=ValueTrace()
            bits,post,used=d.decode(llr,H.tolist(),20,mode,.8,.15,stats=trace)
            with self.subTest(mode=mode):
                self.assertEqual(trace.evaluations,{'v':used*edges,'post':used*n})
                recount={s:{'pos':sum(1 for st,v in trace.values if st==s and v>32767),
                            'neg':sum(1 for st,v in trace.values if st==s and v<-32768)}
                         for s in ('v','post')}
                self.assertEqual({s:c for s,c in recount.items() if c['pos'] or c['neg']},
                                 {s:dict(c) for s,c in trace.counts.items()})

    def test_stress_transaction_clamps_v_positive_after_iteration_one(self):
        Hl=H.tolist();word=ldpc_cases.kernel_word(Hl);n=len(Hl[0])
        llr=[ldpc_cases.OVERLOAD_LLR if bit==0 else -ldpc_cases.OVERLOAD_LLR for bit in word]
        llr[ldpc_cases.STRESS_FLIP]=-llr[ldpc_cases.STRESS_FLIP]
        trace=ValueTrace()
        bits,post,used=d.decode(llr,Hl,20,0,.8,.15,stats=trace)
        self.assertGreaterEqual(used,2)                      # forces 2+ iterations
        self.assertGreater(trace.counts['v']['pos'],0)       # and a positive v clamp
        self.assertEqual(trace.counts['v']['neg'],0)         # never a negative v clamp...
        clamped=[v for s,v in trace.values if s=='v']
        self.assertGreater(min(clamped),-32768)              # ...so no v lands on -32768
        self.assertEqual(trace.evaluations['v'],used*int(H.sum()))

    def test_vector_folders_expected_files_and_formula(self):
        folder=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,folder,True)
        plain=ldpc_cases.vectors(folder/'model',0)
        stress=ldpc_cases.vectors(folder/'stress',0,stress=True)
        rows=(folder/'model'/'ldpc_sat_expected.txt').read_text().split()
        self.assertEqual(rows[0],'2')                        # FIELDS line
        eval_v,pos_v,neg_v,eval_p,pos_p,neg_p=map(int,rows[1:])
        self.assertEqual(eval_v,8*int(H.sum()))              # 8 iterations actually run x 25 edges
        self.assertEqual(eval_p,8*12)
        self.assertEqual((pos_v,neg_v),(0,0))                # old config: no v clamp...
        self.assertGreater(pos_p+neg_p,0)                    # ...but the overload moves post
        js=json.loads((folder/'model'/'saturation.json').read_text())
        self.assertTrue(js['model_only_evidence'])
        self.assertEqual(js['formula']['v_evaluations'],
                         sum(js['formula']['iterations'])*js['formula']['edges'])
        self.assertEqual(js['formula']['post_evaluations'],
                         sum(js['formula']['iterations'])*js['formula']['n'])
        self.assertEqual(js['evaluations'],{'v':eval_v,'post':eval_p})
        self.assertEqual(plain['saturation_markers'],{'v':(eval_v,0),'post':(eval_p,pos_p+neg_p)})
        # stress folder: old vector prefix preserved, stress transaction appended only
        old=(folder/'model'/'dec_in.txt').read_text().splitlines()
        new=(folder/'stress'/'dec_in.txt').read_text().splitlines()
        self.assertEqual(new[1:len(old)],old[1:])
        self.assertEqual(int(new[0]),len(old)-1+12)
        self.assertEqual(stress['decoder_transactions'],plain['decoder_transactions']+1)
        js=json.loads((folder/'stress'/'saturation.json').read_text())
        self.assertTrue(js['stress'])
        self.assertGreater(js['stages']['v']['pos'],0)
        self.assertEqual(js['stages']['v']['neg'],0)
        self.assertEqual(js['formula']['v_evaluations'],
                         sum(js['formula']['iterations'])*js['formula']['edges'])
        self.assertEqual(js['evaluations']['v'],sum(js['formula']['iterations'])*js['formula']['edges'])


if __name__=='__main__':unittest.main()
