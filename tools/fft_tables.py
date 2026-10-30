#!/usr/bin/env python3
"""FFT and STFT ROMs; --check forbids drift.
fft_twiddle_<N>.mem (rtl/common/fft_r2sdf.sv, fft_fixed.twiddles): N/2 rows of 36 bits,
{cos[17:0], sin[17:0]} in Q16, k = 0..N/2-1.
stft_window_<N>.mem (stft_fixed.window): N rows of the 18-bit Q17 sqrt-Hann window.
stft_recip_<N>_<HOP>.mem (stft_fixed.reciprocals): HOP*2^R rows of 24 unsigned bits at
address {p, mask}, R = N/HOP; row mask 0 is unused (0).
lms_reciprocal.mem (lms_fixed.RECIPROCAL): 512 rows of 11 bits, round(2^19/m) for m = 512..1023.
ldpc_phi.mem / ldpc_inv.mem (ldpc_fixed.PHI / INV): 2048 rows of 16 / 15 bits.
omlsa_recip/tf/te/ln/expn.mem (omlsa_fixed tables): 2048 x 17, 8192 x 20, 8192 x 16, 4097 x 19 (signed),
4096 x 17 bits."""
from pathlib import Path
import argparse
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'common/python'))
from fft_fixed import twiddles
from stft_fixed import window,reciprocals
from lms_fixed import RECIPROCAL as LMS_RECIPROCAL
from ldpc_fixed import PHI as LDPC_PHI, INV as LDPC_INV
import omlsa_fixed as OM

SIZES=[1<<b for b in range(2,11)]
# STFT (N, HOP) tables: the research case 64/16, OM-LSA 32/8, and the RTL test sizes.
STFT=[(4,1),(8,2),(16,4),(32,8),(32,32),(64,16),(64,32),(256,64)]


def files():
    folder=ROOT/'rtl/common/mem'
    result={folder/f'fft_twiddle_{n}.mem':''.join(f'{c&0x3ffff:018b}{s&0x3ffff:018b}\n' for c,s in twiddles(n)) for n in SIZES}
    for n in sorted({n for n,_ in STFT}):result[folder/f'stft_window_{n}.mem']=''.join(f'{w:018b}\n' for w in window(n))
    for n,hop in STFT:result[folder/f'stft_recip_{n}_{hop}.mem']=''.join(f'{v:024b}\n' for row in reciprocals(n,hop) for v in row)
    result[folder/'omlsa_recip.mem']=''.join(f'{v:017b}\n' for v in OM.RECIP)
    result[folder/'omlsa_tf.mem']=''.join(f'{v:020b}\n' for v in OM.TF)
    result[folder/'omlsa_te.mem']=''.join(f'{v:016b}\n' for v in OM.TE)
    result[folder/'omlsa_ln.mem']=''.join(f'{v&0x7ffff:019b}\n' for v in OM.LN)
    result[folder/'omlsa_expn.mem']=''.join(f'{v:017b}\n' for v in OM.EXPN)
    result[folder/'ldpc_phi.mem']=''.join(f'{v:016b}\n' for v in LDPC_PHI)
    result[folder/'ldpc_inv.mem']=''.join(f'{v:015b}\n' for v in LDPC_INV)
    result[folder/'lms_reciprocal.mem']=''.join(f'{v:011b}\n' for v in LMS_RECIPROCAL)
    return result


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--check',action='store_true');args=parser.parse_args()
    for path,expected in files().items():
        if args.check:
            if not path.is_file() or path.read_text()!=expected:raise RuntimeError(f'Stale table: {path}')
        else:path.write_text(expected)
    print('PASS FFT/STFT tables')

if __name__=='__main__':main()
