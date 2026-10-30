import itertools, os, random, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "common", "python"))
from ext_code_trellis import conv_encode, viterbi_decode, _quantize  # noqa: E402

IMPULSE_GOLDEN = [1, 1, 1, 0, 1, 1, 1, 1, 0, 0, 0, 1, 1, 1]  # pairs 11,10,11,11,00,01,11


def oracle_encode(u):
    """Independent temporal XOR encoder with zero tail (171/133 octal, MSB = current bit)."""
    u = list(u) + [0] * 6
    taps0, taps1 = (0, 1, 2, 3, 6), (0, 2, 3, 5, 6)   # delays of set bits
    out = []
    for t in range(len(u)):
        d = lambda k: u[t - k] if t >= k else 0
        out += [sum(d(k) for k in taps0) & 1, sum(d(k) for k in taps1) & 1]
    return out


def cost(coded, llrs):
    return sum(c * l for c, l in zip(coded, llrs))

class TestTrellis(unittest.TestCase):
    def test_impulse_golden(self):
        self.assertEqual(conv_encode([1]), IMPULSE_GOLDEN)

    def test_oracle_match(self):
        rng = random.Random(1)
        for n in (1, 7, 300):
            u = [rng.randint(0, 1) for _ in range(n)]
            self.assertEqual(conv_encode(u), oracle_encode(u))
            self.assertEqual(conv_encode(u, terminate=False), oracle_encode(u)[:2 * n])

    def test_exhaustive_ml(self):
        rng = random.Random(2)
        for n in range(1, 6):
            for _ in range(3):
                llrs = [rng.randint(-6, 6) for _ in range(2 * (n + 6))]
                for term in (True, False):
                    m = n + 6 if term else n
                    llr = llrs[:2 * m]
                    best = min(cost(conv_encode(list(msg), term), llr)
                               for msg in itertools.product((0, 1), repeat=n))
                    for q in (None, 8):
                        r = viterbi_decode(llr, terminated=term, quant_bits=q, scale=1)
                        self.assertEqual(len(r.bits), n)
                        self.assertEqual(cost(conv_encode(r.bits, term), llr), best)

    def test_noiseless_300(self):
        rng = random.Random(3)
        msg = [rng.randint(0, 1) for _ in range(300)]
        llr = [4.0 if c == 0 else -4.0 for c in conv_encode(msg)]
        for q in (None, 6):
            self.assertEqual(viterbi_decode(llr, quant_bits=q).bits, msg)
        self.assertEqual(viterbi_decode(llr, quant_bits=6).final_state, 0)

    def test_noisy_300_transmitted_path_metric_bound(self):
        rng = random.Random(4)
        msg = [rng.randint(0, 1) for _ in range(300)]
        clean = conv_encode(msg)
        for q in (None, 5):
            llr = [(4.0 if c == 0 else -4.0) + rng.gauss(0, 2.5) for c in clean]
            r = viterbi_decode(llr, quant_bits=q)
            self.assertEqual(len(r.bits), 300)
            selected = llr if q is None else [max(-16,min(15,round(v*8))) for v in llr]
            self.assertLessEqual(cost(conv_encode(r.bits), selected), cost(clean, selected) + 1e-9)
    def test_soft_reliability_beats_hard_majority(self):
        competitor=conv_encode([1]);positions=[i for i,b in enumerate(competitor) if b]
        llr=[10.0]*len(competitor)
        for p in positions[:6]:llr[p]=-.1
        self.assertEqual(viterbi_decode(llr).bits,[0])
        self.assertEqual(viterbi_decode(llr,quant_bits=8).bits,[0])
        self.assertEqual(viterbi_decode([1 if v>0 else -1 for v in llr]).bits,[1])

    def test_zero_llr_ties_to_zero(self):
        r = viterbi_decode([0] * 2 * (50 + 6))
        self.assertEqual(r.bits, [0] * 50)
        self.assertTrue(all(t.min_metric == 0 for t in r.metric_trace))

    def test_tails_and_trace(self):
        llr = [1.0] * 2 * (20 + 6)
        self.assertEqual(len(viterbi_decode(llr).bits), 20)
        r = viterbi_decode(llr, terminated=False)
        self.assertEqual(len(r.bits), 26)
        ri = viterbi_decode([2] * 52, quant_bits=4)
        self.assertTrue(all(isinstance(t.min_metric, int) for t in ri.metric_trace))
        self.assertEqual(ri.normalization_sum, sum(t.normalization for t in ri.metric_trace))

    def test_quant_clip_and_round(self):
        self.assertEqual(_quantize(1000, 4, 1), 7)
        self.assertEqual(_quantize(-1000, 4, 1), -8)
        self.assertEqual(_quantize(2.5, 8, 1), 2)
        self.assertEqual(_quantize(3.5, 8, 1), 4)
        self.assertEqual(_quantize(-0.5, 8, 1), 0)
        big = [1000 if c == 0 else -1000 for c in conv_encode([1, 0, 1, 1, 0, 0, 1])]
        clip = [7 if v > 0 else -8 for v in big]
        self.assertEqual(viterbi_decode(big, quant_bits=4).bits, viterbi_decode(clip, quant_bits=4).bits)
    def test_validation(self):
        bad = [lambda: conv_encode([2]), lambda: conv_encode([True]), lambda: viterbi_decode([1, 2, 3]),
               lambda: viterbi_decode([]), lambda: viterbi_decode([float("nan")] * 12),
               lambda: viterbi_decode([1.0] * 8), lambda: viterbi_decode([1.0] * 12, quant_bits=1),
               lambda: viterbi_decode([1.0] * 12, quant_bits=True),
               lambda: viterbi_decode([1.0] * 12, quant_bits=4, scale=0)]
        for f in bad:
            with self.assertRaises(ValueError):
                f()

if __name__ == "__main__":
    unittest.main()
