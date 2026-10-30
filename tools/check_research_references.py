#!/usr/bin/env python3
"""Compare Python analogues with independently executed original MATLAB functions."""
import json
from pathlib import Path
import sys
import hashlib
from regression_evidence import begin, finish, write_json, require_pass
import numpy as np
from scipy.io import loadmat
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
from research_core import run,ldpc_decode


def main():
    from regression_evidence import require_unoptimized
    require_unoptimized()
    base=ROOT/'build/typed/originals';results=[]
    native=json.loads((base/'matlab_results.json').read_text());require_pass(native, ROOT)
    evidence=begin();write_json(base/'python_results.json',dict(evidence,status='RUNNING'))
    for c in loadmat(base/'adaptive.mat',simplify_cells=True)['adaptive']:
        actual=run(c['operation'],c['parameters'],c['x'],c['auxiliary']);expected=c['expected']
        np.testing.assert_allclose(actual,expected,atol=1e-10,rtol=1e-10)
        results.append({'name':c['operation'],'status':'PASS','values':actual.size,'maximum_error':float(max(abs(actual-expected)))})
    for c in loadmat(base/'channelizers.mat',simplify_cells=True)['channelizers']:
        actual=run('pfb',[4,c['decimation']],c['x'],c['h']).reshape(-1,4)
        expected=c['expected'];actual=actual[:len(expected),[0,3,2,1]]
        np.testing.assert_allclose(actual,expected,atol=1e-10,rtol=1e-10)
        results.append({'name':f"pfb_D{c['decimation']}",'status':'PASS','values':actual.size,'maximum_error':float(np.max(abs(actual-expected)))})
    d=loadmat(base/'ldpc.mat',simplify_cells=True);H=d['H'];llr=d['llr']
    assert not np.any((H@d['word'])%2)
    for mode in range(4):
        actual=ldpc_decode(llr,H,8,mode,.8,.15)[:2016].astype(int)
        np.testing.assert_array_equal(actual,d['word'])
        np.testing.assert_array_equal(actual[1008:],d['decoded'][mode])
        results.append({'name':f'ldpc_original_length_mode_{mode}','status':'PASS','values':2016,'payload_bits':1008,'decoded_errors':0,'maximum_error':0.})
    report=dict(status='PASS',checks=results,**finish(evidence,[base/'matlab_results.json',*sorted(base.glob('*.mat'))]))
    write_json(base/'python_results.json',report)
    print(f'PASS {len(results)} original MATLAB / Python comparisons, including four LDPC (2016,1008) decoders')

if __name__=='__main__':main()
