"""Overflow-before-clipping regressions for accepted finite quantizer inputs."""
import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'common/python'))
from ext_code_btc import btc_decode
from ext_code_turbo import turbo_decode
from ext_code_polar import polar_decode
from ext_code_pls import pls_encode,pls_decode
from ext_code_golay import golay_encode,golay_chase
from ext_code_llr import q8_adapter
from ext_code_trellis import _quantize
from ext_code_tcm import tcm_decode

class FiniteQuantizationRegressions(unittest.TestCase):
    def test_btc_large_input_matches_prescaled_signed_rails(self):
        for value,rail in ((1e308,127/8),(-1e308,-128/8)):
            result=btc_decode([[value]*8 for _ in range(8)],quant_bits=8)
            expected=btc_decode([[rail]*8 for _ in range(8)],quant_bits=8)
            self.assertEqual(result.bits,expected.bits)
            self.assertEqual(result.codeword,expected.codeword)
            self.assertEqual(result.trace[-1]['posterior_first8'],expected.trace[-1]['posterior_first8'])

    def test_turbo_large_input_matches_prescaled_signed_rails(self):
        length=6*(1784+4)
        for value,rail in ((1e308,127/8),(-1e308,-128/8)):
            result=turbo_decode([value]*length,quant_bits=8,iterations=1)
            expected=turbo_decode([rail]*length,quant_bits=8,iterations=1)
            self.assertEqual(result.bits,expected.bits)
            self.assertEqual(result.trace[-1]['extrinsic_first8'],expected.trace[-1]['extrinsic_first8'])

    def test_polar_fractional_scale_extreme_and_tiny_values(self):
        values=[1e308,-1e308]*4
        for frac_bits in (0,7):
            expected=polar_decode([127/(1<<frac_bits),-128/(1<<frac_bits)]*4,4,8,frac_bits)
            result=polar_decode(values,4,8,frac_bits)
            self.assertEqual(result.bits,expected.bits)
            self.assertEqual(result.llr_trace,expected.llr_trace)
        result=polar_decode([5e-324,-5e-324]*4,4,8,7)
        self.assertEqual(result.bits,[0]*4)

    def test_variable_scales_pls_golay_and_q8_rounding(self):
        label=37;word=golay_encode(0xabc)
        pls=[(1-2*b)*1e308 for b in pls_encode(label)]
        golay=[(1-2*(word>>i&1))*1e308 for i in range(24)]
        for scale in (8,1e308,1e-308):
            self.assertEqual(pls_decode(pls,8,scale),label)
            self.assertEqual(golay_chase(golay,8,scale).codeword,word)
            self.assertEqual(_quantize(1e308,8,scale),127 if scale!=1e-308 else 1)
            self.assertEqual(_quantize(-1e308,8,scale),-128 if scale!=1e-308 else -1)
        self.assertEqual(pls_decode(pls,8,5e-324),0)
        self.assertEqual(golay_chase(golay,8,5e-324).codeword,0)
        self.assertEqual(_quantize(1e308,8,5e-324),0)
        self.assertEqual(q8_adapter([1e308,-1e308,5e-324,-5e-324]),[32767,-32768,0,0])
        # Exactly representable half ties retain nearest/even behavior.
        self.assertEqual(q8_adapter([1/512,3/512,5/512,-3/512]),[0,2,2,-2])

    def test_tcm_large_finite_iq_uses_wide_integer_coordinates(self):
        # TCM coordinates are intentionally wide integers, with no input rails.
        # Preserve that contract while avoiding the intermediate float product.
        result=tcm_decode([[complex(1e308,-1e308)]*4],fixed=True,frac_bits=24)
        self.assertEqual(len(result.payloads),1)
        self.assertTrue(all(isinstance(v,int) for pair in result.metric_trace for v in pair))

if __name__=='__main__':unittest.main()
