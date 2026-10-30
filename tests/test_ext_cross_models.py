"""End-to-end checks for conventions shared by independently implemented models."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common/python'))


def wire_bits(packet):
    return [(byte >> bit) & 1 for byte in packet for bit in range(7, -1, -1)]


def wire_bytes(bits):
    return bytes(sum(bits[i+j] << (7-j) for j in range(8)) for i in range(0, len(bits), 8))


class CrossModelConventions(unittest.TestCase):
    def test_crc_scrambler_convolution_awgn_viterbi(self):
        from ext_code_basics import append_fcs, check_fcs, additive_scramble
        from ext_code_trellis import conv_encode, viterbi_decode
        from ext_code_llr import llr, quantized_demapper
        from ext_advanced_channels import AWGN, Q

        packet = append_fcs(bytes(range(12)))
        payload = additive_scramble(wire_bits(packet), 9)
        encoded = conv_encode(payload)
        sigma, amplitude = .1, .25
        for fixed in (False, True):
            channel = AWGN(sigma, seeds=(129, 337, 219), fixed=fixed)
            received, received_q = [], []
            for bit in encoded:
                symbol = amplitude * (1-2*bit)
                if fixed:
                    re, im = channel.next((round(symbol*Q), 0))
                    received_q.append((int(re), int(im)))
                    received.append(complex(re, im)/Q)
                else:
                    received.append(channel.next(symbol))
            # Complex noise variance is 2*sigma**2. Positive LLR means zero.
            llrs = [2*amplitude*z.real/sigma**2 for z in received]
            demapped = [row[0] for row in llr([z/amplitude for z in received], 2,
                                             2*sigma**2/amplitude**2)]
            np.testing.assert_allclose(demapped, llrs, atol=2e-14)
            if fixed:
                coordinate = round(amplitude*Q)
                demapped = [row[0] for row in quantized_demapper(received_q,
                    [(coordinate, 0), (-coordinate, 0)], [0, 1], round(2*sigma**2*Q**2))]
            result = viterbi_decode(demapped, quant_bits=16 if fixed else None, scale=1)
            self.assertEqual(result.bits, payload)
            recovered = wire_bytes(additive_scramble(result.bits, 9))
            self.assertEqual(recovered, packet)
            self.assertTrue(check_fcs(recovered))
            wrong = viterbi_decode([-v for v in llrs]).bits
            self.assertFalse(check_fcs(wire_bytes(additive_scramble(wrong, 9))))

    def test_crc_polar_1024_512_reliability_order(self):
        from ext_code_basics import append_fcs, check_fcs
        from ext_code_polar import polar_encode, polar_decode

        packet = append_fcs(bytes((i*47+19) % 256 for i in range(60)))
        payload = wire_bits(packet)
        encoded = polar_encode(payload, n=1024)
        rng = np.random.default_rng(5121024)
        llrs = [(1-2*b)*8 + float(rng.normal(0, .4)) for b in encoded]
        for quant_bits in (None, 8):
            recovered = polar_decode(llrs, k=512, quant_bits=quant_bits).bits
            self.assertEqual(recovered, payload)
            self.assertTrue(check_fcs(wire_bytes(recovered)))
        corrupted = bytearray(packet)
        corrupted[11] ^= 0x08
        self.assertFalse(check_fcs(corrupted))

    def test_pls_phase_origin_through_complex_awgn(self):
        from ext_code_pls import (pls_encode, pls_decode, pls_map, pls_demod,
                                  pls_map_fixed, pls_demod_fixed)
        from ext_advanced_channels import AWGN

        for label in (0, 1, 31, 63, 64, 127):
            bits = pls_encode(label)
            channel = AWGN(.12, seeds=(153, 467, 991))
            received = [channel.next(symbol) for symbol in pls_map(bits)]
            self.assertEqual(pls_decode(pls_demod(received, 2*.12**2)), label)
            channel_q = AWGN(.035, seeds=(153, 467, 991), fixed=True)
            received_q = [tuple(int(v) for v in channel_q.next(symbol))
                          for symbol in pls_map_fixed(bits)]
            self.assertEqual(pls_decode(pls_demod_fixed(received_q)), label)


if __name__ == '__main__':
    unittest.main()
