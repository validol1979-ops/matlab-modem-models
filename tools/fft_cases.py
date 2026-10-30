"""Streaming FFT RTL vectors: input frames (with driver gaps) and the expected
bit-exact outputs of common/python/fft_fixed.py for rtl/common/fft_r2sdf.sv."""
from pathlib import Path
import math
import sys
import numpy as np
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
import fft_fixed as f
import sat_diag



def save(path,rows):
    rows=list(rows);path.write_text(str(len(rows))+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n');return len(rows)


def frame(rng,n,kind,tour,in_width=18):
    """One frame of N complex samples as (re, im) ints: full-scale random, constant corner
    frames, an impulse or random corners, a tone, small values, spectrum-sized random.
    Full-scale frames saturate the unhalved inverse, which is checked bit-exactly too."""
    FULL=1<<(in_width-1);TOP=FULL-1
    if kind==0:return [(int(a),int(b)) for a,b in zip(rng.integers(-FULL,FULL,n),rng.integers(-FULL,FULL,n))]
    if kind==1:return [((TOP,TOP),(-FULL,-FULL),(TOP,-FULL))[tour%3]]*n
    if kind==2:
        # A single full-scale impulse at a random position; random corners elsewhere in the tour.
        if tour%2==0:
            rows=[(0,0)]*n;rows[int(rng.integers(0,n))]=(int(rng.choice([-FULL,TOP])),int(rng.choice([-FULL,TOP])));return rows
        corner=rng.choice([-FULL,TOP],size=(n,2))
        return [(int(a),int(b)) for a,b in corner]
    if kind==3:
        k=int(rng.integers(1,max(2,n//2)));t=np.arange(n)
        return [(int(round(100000*math.cos(2*math.pi*k*t[j]/n))),int(round(100000*math.sin(2*math.pi*k*t[j]/n)))) for j in range(n)]
    if kind==4:return [(int(a),int(b)) for a,b in zip(rng.integers(-50,51,n),rng.integers(-50,51,n))]
    # Spectrum-sized frames: the unhalved inverse stays inside 20 bits (no saturation).
    shift=(n.bit_length()-1)+1
    return [(int(a)>>shift,int(b)>>shift) for a,b in zip(rng.integers(-FULL,FULL,n),rng.integers(-FULL,FULL,n))]


DIRECTIONS=('forward','inverse');BRANCHES=('sum','diff');COMPONENTS=('re','im')


def saturation_expected_rows(log2n,stats,flags):
    """Rows for saturation_expected.txt: ordered direction (0 forward, 1 inverse),
    stage (0..LOG2N-1), branch (0 sum, 1 diff), component (0 re, 1 im); each row is
    'evaluations positive_events negative_events'. evaluations = frames_in_direction*N/2
    from the actual per-frame inverse flags; events come from the SatStats stage names
    'forward.s<g>.<sum|diff>.<re|im>'/'inverse...'. The final inverse conjugation has no
    clamp in the RTL (stage symmetry keeps it in range), so it has no row here."""
    n=1<<log2n;inv=[int(bool(flag)) for flag in flags]
    per=[(len(inv)-sum(inv))*n//2,sum(inv)*n//2]
    rows=[]
    for d,name in enumerate(DIRECTIONS):
        for g in range(log2n):
            for branch in BRANCHES:
                for comp in COMPONENTS:
                    c=stats.counts.get(f'{name}.s{g}.{branch}.{comp}',{})
                    rows.append((per[d],c.get('pos',0),c.get('neg',0)))
    assert len(rows)==8*log2n
    return rows


def write_saturation_expected(folder,log2n,stats,flags):
    """Write saturation_expected.txt (header LOG2N, then exactly 8*LOG2N rows);
    return the row totals the bench marker must reproduce."""
    rows=saturation_expected_rows(log2n,stats,flags)
    (folder/'saturation_expected.txt').write_text(str(log2n)+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n')
    return dict(rows=len(rows),total_evaluations=sum(row[0] for row in rows),
                total_events=sum(row[1]+row[2] for row in rows))


def read_saturation_expected(path):
    """Parse (log2n, rows) from saturation_expected.txt and check the shape contract."""
    lines=[l for l in Path(path).read_text().splitlines() if l.strip()]
    log2n=int(lines[0]);rows=[tuple(map(int,l.split())) for l in lines[1:]]
    assert len(rows)==8*log2n and all(len(row)==3 and all(v>=0 for v in row) for row in rows)
    return log2n,rows


def boundary_vectors(folder,gaps=False):
    """Hand-computed n4 inverse cases for the symmetric 20-bit clamp.

    Four -131072 real inputs sum to -524288 (one negative clamp), whereas
    three -131072 and one -131071 sum exactly to -524287 (no clamp).
    The imaginary cases are conjugated before the inverse, exercising +524288
    and the exact +524287 rail with fully representable 18-bit input words.
    """
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    blocks=[([(-131072,0)]*4,{'inverse.s1.sum.re':{'pos':0,'neg':1}}),
            ([(-131072,0)]*3+[(-131071,0)],{}),
            ([(131071,0)]*4,{}),
            ([(0,-131072)]*4,{'inverse.s1.sum.im':{'pos':1,'neg':0}}),
            ([(0,-131072)]*3+[(0,-131071)],{})]
    stats=sat_diag.SatStats();inputs=[];outputs=[]
    for block,expected in blocks:
        observed=sat_diag.SatStats();values=f.inverse(block,stats=observed)
        assert observed.counts==expected,(observed.counts,expected)
        stats.merge(observed)
        inputs.extend((re,im,1,int(k==3),7 if gaps and k==0 else int(gaps and k==2))
                      for k,(re,im) in enumerate(block))
        outputs.extend((re,im,1,int(k==3)) for k,(re,im) in enumerate(values))
    samples=save(folder/'in.txt',inputs);save(folder/'out.txt',outputs)
    sat_diag.save_json(folder/'saturation.json',stats,model='fft',log2n=2,in_width=18,width=20)
    expected=write_saturation_expected(folder,2,stats,[1]*len(blocks))
    return dict(in_width=18,width=20,frames=len(blocks),samples=samples,outputs=len(outputs),
                log2n=2,saturation=stats.to_dict(),saturation_expected=expected)


def vectors(folder,log2n,frames=24,seed=11,gaps=False,in_width=18,width=20):
    """in.txt: 're im inverse last gap' per input sample (gap = idle clocks the driver
    inserts before the sample; with gaps=True random 0..3 inside frames and long
    N+20..2N drains before some frames). out.txt: 're im inverse last' per output
    sample = fft_fixed.transform of the frame. Both inverse flag values always occur
    and consecutive frames switch the flag at least once."""
    n=1<<log2n;folder.mkdir(parents=True,exist_ok=True);rng=np.random.default_rng(seed)
    stats=sat_diag.SatStats()
    blocks=[]
    for tour in range((frames+5)//6):
        for kind in range(6):
            if len(blocks)<frames:blocks.append(frame(rng,n,kind,tour,in_width))
    flags=[int(rng.integers(0,2)) for _ in range(frames)]
    if len(set(flags))<2:flags[len(flags)//2]^=1
    if all(flags[j]==flags[j-1] for j in range(1,frames)):flags[-1]^=1
    in_rows=[];out_rows=[]
    for index,block in enumerate(blocks):
        assert len(block)==n
        inverse=flags[index]
        for k,(re,im) in enumerate(block):
            gap=0
            if gaps:
                if k==0:
                    if rng.integers(0,100)<40:gap=int(rng.integers(n+20,max(n+21,2*n+2)))
                elif rng.integers(0,100)<15:gap=int(rng.integers(1,4))
            in_rows.append((re,im,inverse,int(k==n-1),gap))
        for k,(re,im) in enumerate(f.transform(block,inverse,in_width,width,stats=stats)):
            out_rows.append((re,im,inverse,int(k==n-1)))
    samples=save(folder/'in.txt',in_rows)
    save(folder/'out.txt',out_rows)
    sat_diag.save_json(folder/'saturation.json',stats,model='fft',log2n=log2n,in_width=in_width,width=width)
    expected=write_saturation_expected(folder,log2n,stats,flags)
    return dict(in_width=in_width,width=width,frames=frames,samples=samples,outputs=len(out_rows),log2n=log2n,
                saturation=stats.to_dict(),saturation_expected=expected)


if __name__=='__main__':print(vectors(ROOT/'build/rtl/fft/vectors',6))
