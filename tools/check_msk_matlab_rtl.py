#!/usr/bin/env python3
"""MSK transmitter RTL (cpm_tx, GMSK=0) against the original Simulink capture.

build/matlab_msk_reference (tools/check_matlab_msk.py) holds the 511 scrambler bits and the
16 352 samples of the original at 32 samples per symbol. At 8 samples per symbol, sample t of
the MSK phase trajectory is sample 4t + 3 of the capture (the same phase after 4(t+1) steps),
exactly. The RTL output must equal cpm_fixed.transmit bit for bit and the capture to within the
Q15 rounding of the cos table (2^-15 per axis); a one-sample shift must fail (sensitivity)."""
import argparse
from pathlib import Path
import re
import sys
import numpy as np
from regression_evidence import ROOT,begin,finish,write_json,questa_paths,require_unoptimized
from run_rtl import execute,SOURCES
sys.path.insert(0,str(ROOT/'common/python'))
import cpm_fixed as c

PILOT=ROOT/'rtl/modems/bpsk_costas_2008_08_25'


def main():
    require_unoptimized();parser=argparse.ArgumentParser();parser.add_argument('--suite',choices=['all'],default='all');parser.parse_args()
    reference=ROOT/'build/matlab_msk_reference'
    output=ROOT/'build/rtl/msk_matlab';output.mkdir(parents=True,exist_ok=True)
    evidence=begin();target=output/'all_results.json';write_json(target,dict(evidence,status='RUNNING'))
    bits=[int(v) for v in np.loadtxt(reference/'data.txt',dtype=int)]
    capture=np.loadtxt(reference/'matlab_tx.txt');capture=capture[:,0]+1j*capture[:,1]
    matlab8=capture[3::4][:len(bits)*8]
    model=c.transmit(bits,False)
    assert len(model)==len(bits)*8==len(matlab8)
    model_c=np.array([re_+1j*im for re_,im in model])/32768
    model_error=float(np.max(abs(model_c-matlab8)))
    assert model_error<3e-5,model_error
    shifted=float(np.max(abs(model_c[1:]-matlab8[:-1])))
    assert shifted>1e-2,shifted
    (output/'bits.txt').write_text(f'{len(bits)}\n'+''.join(f'{b} {int(k==len(bits)-1)}\n' for k,b in enumerate(bits)))
    bindir,_=questa_paths();records={}
    for active in (1,0):
        for stall in (False,True):
            work=output/f'reset_{active}{"_stall" if stall else ""}';work.mkdir(exist_ok=True)
            if not (work/'work').is_dir():execute([bindir/'vlib','work'],work,work/'vlib.log')
            execute([bindir/'vlog','-64','-sv',f'+incdir+{PILOT}',*SOURCES,ROOT/'rtl/tb/cpm_tx_dump_tb.sv'],work,work/'compile.log')
            log=work/'run.log'
            text=execute([bindir/'vsim','-64','-c','-quiet','work.cpm_tx_dump_tb',f'-gRESET_ACTIVE={active}',f'-gTABLE_DIR={PILOT/"tables"}',
                          f'+VECTORS={output}',*(['+STALL_OUTPUT'] if stall else []),'-do','onerror {quit -code 1}; run -all; quit -code 0'],work,log)
            if not re.search(r'DUMP CPM TX: (\d+) samples',text) or re.search(r'\*\* (?:Error|Fatal)',text):raise RuntimeError(text[-4000:])
            rows=[tuple(map(int,l.split())) for l in (output/'rtl_tx.txt').read_text().split('\n') if l.strip()]
            assert [(r[0],r[1]) for r in rows]==[tuple(v) for v in model],'RTL differs from cpm_fixed'
            assert [r[2] for r in rows]==[int(k==len(rows)-1) for k in range(len(rows))]
            rtl=np.array([r[0]+1j*r[1] for r in rows])/32768
            error=float(np.max(abs(rtl-matlab8)))
            assert error<3e-5,error
            records[work.name]=dict(samples=len(rows),max_error_vs_matlab=error)
            print(f'PASS MSK RTL vs MATLAB {work.name}: {len(rows)} samples, max error {error:.3g}',flush=True)
    write_json(target,dict(status='PASS',records=records,model_error=model_error,shifted_error=shifted,**finish(evidence,[output/'bits.txt'])))
    print('PASS MSK RTL vs MATLAB')

if __name__=='__main__':main()
