"""Reproducible, integer-only inputs and Python golden values for RTL tests."""
from pathlib import Path
import random
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
from fixed_point import QFormat, SAMPLE, complex_add, complex_multiply

BLOCKS={
    'complex_mul':dict(top='fxp_complex_mul',latency=4,define='DUT_MUL'),
    'complex_add':dict(top='fxp_complex_add',latency=2,define='DUT_ADD'),
    'resize':dict(top='fxp_stream_resize',latency=1,define='DUT_RESIZE'),
}


def vectors(block):
    rng=random.Random(310101)
    rows=[]
    if block=='resize':
        inputs=[]
        for quotient in (-131073,-131072,-17,-2,-1,0,1,2,17,131070,131071,131072):
            for remainder in (0,16383,16384,16385,32767):
                inputs.append((quotient*32768+remainder,-quotient*32768-remainder,0,0))
        inputs += [(rng.randrange(-(1<<36),1<<36),rng.randrange(-(1<<36),1<<36),0,0) for _ in range(512)]
        def calculate(values):
            re,r=SAMPLE.requantize(values[0],30);im,i=SAMPLE.requantize(values[1],30)
            return (re,im),int(r)|(int(i)<<1)
    else:
        corners=(-131072,-131071,-65536,-1,0,1,65535,131071)
        inputs=[(a,b,b,a) for a in corners for b in corners]
        inputs += [(rng.randrange(-131072,131072),rng.randrange(-131072,131072),rng.randrange(-131072,131072),rng.randrange(-131072,131072)) for _ in range(512)]
        operation=complex_multiply if block=='complex_mul' else complex_add
        def calculate(values):return operation(values[:2],values[2:])
    for index,values in enumerate(inputs):
        (re,im),overflow=calculate(values)
        rows.append((*values,re,im,overflow,int(index%32==31),int(index in (64,256)),0 if index<128 else rng.randrange(4)))
    return rows


def generate(block,path):
    rows=vectors(block)
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(str(len(rows))+'\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n')
    return len(rows)


def support_vectors(path):
    rows=[]
    for raw in range(-128,128):
        row=[raw]
        for fmt,source_frac in ((QFormat(5,3),4),(QFormat(5,2),4),(QFormat(6,4),4),(QFormat(10,6),2)):
            value,overflow=fmt.requantize(raw,source_frac);row.extend((value,int(overflow)))
        rows.append(row)
    Path(path).write_text('256\n'+'\n'.join(' '.join(map(str,row)) for row in rows)+'\n')
