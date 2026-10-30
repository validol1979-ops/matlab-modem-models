"""Integer radix-2 FFT (fft_fixed) against numpy, plus saturation instrumentation checks
(sat_diag; an output equal to a rail is NOT an event, only pre-clamp values strictly
outside [-2^(w-1), 2^(w-1)-1] are counted, per stage, branch, direction and component)."""
from pathlib import Path
import sys
import json
import tempfile
import unittest
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
sys.path.insert(0,str(ROOT/'tools'))
import fft_fixed as f
import fft_cases
import sat_diag


def complex_of(rows):return np.array([re+1j*im for re,im in rows])


def read_rows(path):
    lines=[l for l in Path(path).read_text().splitlines() if l.strip()]
    total=int(lines[0]);rows=[tuple(map(int,l.split())) for l in lines[1:1+total]]
    assert len(rows)==total
    return rows


def replay(folder):
    """Feed exactly the samples of folder/in.txt through the model, collecting the
    per-frame inverse flags and the instrumented saturation statistics."""
    st=sat_diag.SatStats();frames=[];flags=[];outs=[]
    for re_,im_,inv,last,gap in read_rows(folder/'in.txt'):
        frames.append((re_,im_))
        if last:
            flags.append(inv)
            got=f.transform(frames,bool(inv),stats=st)
            outs.extend((re,im,inv,int(k==len(got)-1)) for k,(re,im) in enumerate(got))
            frames=[]
    return st,flags,outs


class TestFftFixed(unittest.TestCase):
    def test_random_against_numpy(self):
        rng=np.random.default_rng(5)
        for bits in range(1,11):
            n=1<<bits
            for _ in range(3):
                rows=[tuple(map(int,r)) for r in rng.integers(-(1<<17),1<<17,(n,2))]
                z=complex_of(rows)
                with self.subTest(n=n):
                    # Halving stages: the rounding error stays below one LSB per stage.
                    self.assertLess(np.max(abs(complex_of(f.forward(rows))-np.fft.fft(z)/n)),bits+1)
                    # Unhalved inverse of a spectrum-sized input: N*ifft, no saturation.
                    small=[(re>>(bits+1),im>>(bits+1)) for re,im in rows]
                    expected=np.fft.ifft(complex_of(small))*n
                    self.assertLess(np.max(abs(expected)),(1<<19)-1)
                    self.assertLess(np.max(abs(complex_of(f.inverse(small))-expected)),2*n)

    def test_round_trip(self):
        rng=np.random.default_rng(7)
        for bits in (2,5,6,10):
            n=1<<bits
            rows=[tuple(map(int,r)) for r in rng.integers(-(1<<17),1<<17,(n,2))]
            back=complex_of(f.inverse(f.forward(rows)))
            with self.subTest(n=n):self.assertLess(np.max(abs(back-complex_of(rows))),4*n)

    def test_tone_and_impulse(self):
        n=64;t=np.arange(n);tone=np.round(100000*np.exp(2j*np.pi*7*t/n))
        y=complex_of(f.forward([(int(v.real),int(v.imag)) for v in tone]))
        self.assertLess(abs(y[7]-100000),8);self.assertLess(np.max(abs(np.delete(y,7))),8)
        impulse=[(0,0)]*n;impulse[0]=((1<<17)-1,-(1<<17))
        self.assertTrue(all(abs(re-2048)<=1 and abs(im+2048)<=1 for re,im in f.forward(impulse)))
        # Harger inverse_dft: a single bin of 1.0 (Q15) gives the Q15 tone back.
        spectrum=[(0,0)]*n;spectrum[7]=(32768,0)
        back=complex_of(f.inverse(spectrum))
        self.assertLess(np.max(abs(back-32768*np.exp(2j*np.pi*7*t/n))),4)

    def test_forward_full_scale_stays_in_range(self):
        for n in (32,64,1024):
            for value in (((1<<17)-1,(1<<17)-1),(-(1<<17),-(1<<17)),((1<<17)-1,-(1<<17))):
                out=f.forward([value]*n)
                self.assertLessEqual(max(abs(v) for z in out for v in z),185364)

    def test_inverse_saturates_symmetrically(self):
        out=f.inverse([((1<<17)-1,-(1<<17))]*64)
        self.assertEqual(out[0],(f.LIMIT,-f.LIMIT))
        self.assertTrue(all(abs(v)<=f.LIMIT for z in out for v in z))

    def test_inverse_is_conjugated_unhalved_transform(self):
        rng=np.random.default_rng(9);rows=[tuple(map(int,r)) for r in rng.integers(-1000,1000,(32,2))]
        self.assertEqual(f.inverse(rows),[(re,-im) for re,im in f._transform([(re,-im) for re,im in rows],f.TWIDDLE_FRAC)])

    def test_rejects(self):
        with self.assertRaises(ValueError):f.forward([(0,0)]*12)
        with self.assertRaises(ValueError):f.forward([(1<<17+1,0)]*8)
        with self.assertRaises(ValueError):f.forward([(0,0)])

    def test_public_signed_integer_pair_format(self):
        for entry in ((131072,0),(-131073,0),(0,131072),(0,-131073),
                      (1.75,0),(1.,0),(True,0),(1,0,0),1):
            for operation in (f.forward,f.inverse,f._transform):
                with self.subTest(entry=entry,operation=operation.__name__):
                    with self.assertRaises(ValueError):
                        if operation is f._transform:operation([entry]+[(0,0)]*3,16)
                        else:operation([entry]+[(0,0)]*3)
        rows=np.array([[-131072,131071],[131071,-131072],[0,0],[1,-1]],dtype=np.int64)
        self.assertEqual(f.forward(rows),f.forward([tuple(map(int,row)) for row in rows]))
        self.assertEqual(f.inverse(rows),f.inverse([tuple(map(int,row)) for row in rows]))

    def test_inverse_conjugates_legal_minimum_without_port_wrap(self):
        rows=[(0,-131072)]*4
        st=sat_diag.SatTrace()
        self.assertEqual(f.inverse(rows,stats=st),[(0,-524287),(0,0),(0,0),(0,0)])
        self.assertEqual(st.counts,{'inverse.s1.sum.im':{'pos':1,'neg':0}})


class TestSaturation(unittest.TestCase):
    # n=2, WIDTH=19: symmetric clamp [-262143, 262143]; twiddle W=1, so the pre-clamp
    # sum/difference equal a +- b exactly (full-scale inputs are +-2^17).
    def test_exact_boundaries(self):
        cases=[([(131071,0),(-131072,0)],None),      # diff = +262143 == rail exactly
               ([(131071,0),(-131071,0)],None),      # diff = +262142, sum inside
               ([(-131071,0),(-131072,0)],None),     # sum = -262143 == clamp boundary
               ([(-131072,0),(-131072,0)],{'inverse.s0.sum.re':{'pos':0,'neg':1}}),
               ([(0,-131072),(0,-131072)],{'inverse.s0.sum.im':{'pos':1,'neg':0}}),  # internal conjugated sum = 262144
               ([(0,-131072),(0,-131071)],None),      # conjugated sum = +262143 exactly
               ([(-131072,0)]*4,{'inverse.s0.sum.re':{'pos':0,'neg':2},
                                  'inverse.s1.sum.re':{'pos':0,'neg':1}})]
        for rows,expect in cases:
            st=sat_diag.SatStats()
            self.assertEqual(f.inverse(rows,width=19,stats=st),f.inverse(rows,width=19))
            if expect is None:self.assertEqual(st.total(),0,rows)
            else:self.assertEqual(st.counts,expect,rows)

    def test_instrumented_equality_and_events(self):
        big=[((1<<17)-1,-(1<<17))]*64
        st=sat_diag.SatStats()
        self.assertEqual(f.inverse(big,stats=st),f.inverse(big))
        self.assertGreater(st.total(),0)
        # Stages clamp to +-LIMIT, so the final conjugation can never leave the range.
        self.assertEqual(st.counts.get('inverse.conj.im'),None)
        st=sat_diag.SatStats()  # forward halves every stage: full scale stays inside
        self.assertEqual(f.forward(big,stats=st),f.forward(big))
        self.assertEqual(st.total(),0)
        rng=np.random.default_rng(4)
        for bits in (2,5,6):
            rows=[tuple(map(int,t)) for t in rng.integers(-(1<<17),1<<17,(1<<bits,2))]
            for inv in (0,1):
                st=sat_diag.SatStats()
                self.assertEqual(f.transform(rows,inv,stats=st),f.transform(rows,inv))

    def test_vectors_saturation_json(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'n64'
            rep=fft_cases.vectors(folder,6,frames=24,seed=31+6+20)
            again=fft_cases.vectors(Path(d)/'again',6,frames=24,seed=31+6+20)
            self.assertEqual(rep['saturation'],again['saturation'])  # deterministic overload
            js=json.loads((folder/'saturation.json').read_text())
            self.assertEqual(js['stages'],rep['saturation']['stages'])
            self.assertGreater(js['total'],0)
            self.assertTrue(all(k.startswith('inverse.') for k in js['stages']))  # only the unhalved inverse clips
            self.assertTrue(js['model_only_evidence'])
            # Replay exactly the frames the testbench consumes (in.txt) and match the JSON.
            st=sat_diag.SatStats(); rows=[tuple(map(int,l.split())) for l in (folder/'in.txt').read_text().splitlines()[1:] if l.strip()]
            outs=[tuple(map(int,l.split())) for l in (folder/'out.txt').read_text().splitlines()[1:] if l.strip()]
            frame=[]; replay=[]
            for re,im,inv,last,gap in rows:
                frame.append((re,im))
                if last:
                    got=f.transform(frame,bool(inv),stats=st)
                    replay.extend((re_,im_,inv,int(k==len(got)-1)) for k,(re_,im_) in enumerate(got))
                    frame=[]
            self.assertEqual(replay,outs)
            self.assertEqual(st.to_dict()['stages'],js['stages'])


class TestSaturationExpected(unittest.TestCase):
    # saturation_expected.txt: header LOG2N, then 8*LOG2N rows ordered by
    # direction (0 forward, 1 inverse), stage, branch (0 sum, 1 diff), component (0 re, 1 im).
    def test_file_matches_replayed_stats(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'n64'
            rep=fft_cases.vectors(folder,6,frames=24,seed=31+6+20)
            st,flags,outs=replay(folder)
            self.assertEqual(outs,read_rows(folder/'out.txt'))  # replay is the real stream
            log2n,rows=fft_cases.read_saturation_expected(folder/'saturation_expected.txt')
            self.assertEqual(log2n,6);self.assertEqual(len(rows),8*6)
            n=64;frames_inv=sum(flags);frames_fwd=len(flags)-frames_inv
            for index,(evaluations,pos,neg) in enumerate(rows):
                d,rest=divmod(index,4*6);stage,rest=divmod(rest,4);branch,comp=divmod(rest,2)
                name=f'{("forward","inverse")[d]}.s{stage}.{("sum","diff")[branch]}.{("re","im")[comp]}'
                counts=st.counts.get(name,{})
                with self.subTest(row=name):
                    self.assertEqual((pos,neg),(counts.get('pos',0),counts.get('neg',0)))
                    self.assertEqual(evaluations,(frames_fwd if d==0 else frames_inv)*n//2)
            self.assertEqual(sum(r[0] for r in rows),2*n*6*len(flags))  # total evaluations
            self.assertEqual(sum(r[1]+r[2] for r in rows),rep['saturation']['total'])

    def test_forward_rows_have_zero_events(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d)/'n64'
            fft_cases.vectors(folder,6,frames=24,seed=31+6+20)
            _,rows=fft_cases.read_saturation_expected(folder/'saturation_expected.txt')
            _,flags,_=replay(folder)
            evaluations=(len(flags)-sum(flags))*64//2
            self.assertGreater(evaluations,0)
            for row in rows[:4*6]:  # every forward row: halves, so never clips
                self.assertEqual(row,(evaluations,0,0))


if __name__=='__main__':unittest.main()
