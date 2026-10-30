"""Independent polynomial, recurrence and parity-check oracles for coding basics."""
import binascii
import itertools
import random
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'common/python'))
from ext_code_basics import (crc, crc_bits, crc_update, prbs_bits, lfsr_jump,
    additive_scramble, selfsync_scramble, selfsync_descramble,
    hamming_encode, hamming_decode)

class CRCOracles(unittest.TestCase):
    def test_standard_byte_oracles(self):
        rng = random.Random(7101)
        for size in (0, 1, 4, 9, 31, 256):
            data = bytes(rng.randrange(256) for _ in range(size))
            self.assertEqual(crc(data), binascii.crc32(data))
            self.assertEqual(crc(data,16,0x1021,0xffff,False,False,0),binascii.crc_hqx(data,0xffff))
        self.assertEqual(crc(b'123456789'),0xcbf43926)
        self.assertEqual(crc(b'123456789',16,0x1021,0xffff,False,False,0),0x29b1)

    def test_polynomial_division_and_chunks(self):
        rng=random.Random(1107)
        for width,poly in ((3,3),(8,7),(16,0x1021),(32,0x04c11db7)):
            for length in (0,1,7,8,15,32,77):
                bits=[rng.randrange(2) for _ in range(length)]
                message=0
                for b in bits: message=(message<<1)|b
                remainder=message<<width
                divisor=(1<<width)|poly
                while remainder.bit_length()>width:
                    remainder ^= divisor << (remainder.bit_length()-width-1)
                self.assertEqual(crc_bits(bits,width,poly,0),remainder)
                for chunk in (1,8,32):
                    state=0
                    for i in range(0,length,chunk): state=crc_update(state,bits[i:i+chunk],width,poly)
                    self.assertEqual(state,remainder)

    def test_fcs_residue_and_corruption(self):
        data=b'frame-data-with-partial-word'
        packet=data+crc(data).to_bytes(4,'little')
        self.assertEqual(crc(packet),0x2144df1c)
        for pos in (0,7,len(packet)*8-1):
            b=bytearray(packet);b[pos//8]^=1<<(pos%8)
            self.assertNotEqual(crc(b),0x2144df1c)

class LFSROracles(unittest.TestCase):
    def test_period_recurrence_jump(self):
        for n,k in ((7,6),(9,5),(15,14),(31,28)):
            size=(1<<n)-1 if n<10 else 300
            bits,state=prbs_bits(n,size)
            # Scalar polynomial recurrence, independently generated output history.
            history=[1]*n
            for i in range(size): history.append(history[i]^history[i+n-k])
            self.assertEqual(bits,history[:size])
            if n<10:
                self.assertEqual(state,(1<<n)-1)
                self.assertEqual(len({prbs_bits(n,i)[1] for i in range(size)}),size)
            for j in (0,1,7,63,299): self.assertEqual(lfsr_jump(n,j),prbs_bits(n,j)[1])
            self.assertEqual(lfsr_jump(n,10**12+57),lfsr_jump(n,10**12,lfsr_jump(n,57)))

    def test_scramblers(self):
        data=[int(x) for x in '1011001000101110']*12
        for n in (7,9,15,31):
            self.assertEqual(additive_scramble(additive_scramble(data,n),n),data)
            scrambled=selfsync_scramble(data,n)
            self.assertEqual(selfsync_descramble(scrambled,n),data)
            received=scrambled.copy();received[40]^=1
            restored=selfsync_descramble(received,n)
            k={7:6,9:5,15:14,31:28}[n]
            self.assertEqual([i for i,(a,b) in enumerate(zip(data,restored)) if a!=b],[40,40+k,40+n])
        with self.assertRaises(ValueError): prbs_bits(7,10,0)

class HammingOracles(unittest.TestCase):
    @staticmethod
    def syndrome(word):
        return [sum(word[p-1]*((p>>r)&1) for p in range(1,len(word)))%2 for r in range(len(word).bit_length()-1)]+[sum(word)%2]

    def test_small_code_distance_and_parity_matrix(self):
        words=[hamming_encode(list(bits)) for bits in itertools.product((0,1),repeat=4)]
        self.assertEqual(len({tuple(w) for w in words}),16)
        self.assertEqual(min(sum(w) for w in words if any(w)),4)
        for word in words:
            self.assertFalse(any(self.syndrome(word)))
            self.assertEqual(hamming_decode(word)[2],word)

    def test_all_single_and_double_locations(self):
        rng=random.Random(9401)
        for k in (4,11,26,57):
            for bits in ([0]*k,[rng.randrange(2) for _ in range(k)]):
                word=hamming_encode(bits)
                self.assertFalse(any(self.syndrome(word)))
                for i in range(len(word)):
                    received=word.copy();received[i]^=1
                    decoded,status,corrected=hamming_decode(received)
                    self.assertEqual((decoded,status,corrected),(bits,'corrected',word))
                for i,j in itertools.combinations(range(len(word)),2):
                    received=word.copy();received[i]^=1;received[j]^=1
                    _,status,corrected=hamming_decode(received)
                    self.assertEqual((status,corrected),('detected_double',received))


class ParallelAndStreamingOracles(unittest.TestCase):
    def test_crc_parallel_matrix_and_fcs(self):
        from ext_code_basics import crc_parallel,append_fcs,check_fcs
        rng=random.Random(719)
        for width,poly in ((16,0x1021),(32,0x04c11db7)):
            for reflected in (False,True):
                rp=int(f'{poly:0{width}b}'[::-1],2) if reflected else poly
                for n in (0,1,7,8,16,31,32):
                    for _ in range(8):
                        state=rng.randrange(1<<width);word=rng.randrange(1<<n)
                        bits=[(word>>(i if reflected else n-1-i))&1 for i in range(n)]
                        self.assertEqual(crc_parallel(state,word,n,width,rp,reflected),crc_update(state,bits,width,rp,reflected))
        for profile,residue,args in (('ethernet',0x2144df1c,()),('ccitt_false',0,(16,0x1021,0xffff,False,False,0))):
            for data in (b'',b'123456789',bytes(range(37))):
                packet=append_fcs(data,profile)
                self.assertTrue(check_fcs(packet,profile))
                self.assertEqual(crc(packet,*args),residue)
                for i in (0,len(packet)-1):
                    bad=bytearray(packet);bad[i]^=1
                    self.assertFalse(check_fcs(bad,profile))
        with self.assertRaises(ValueError):crc_parallel(0,0,33)

    def test_parallel_prbs_and_stalled_chunkcarry(self):
        from ext_code_basics import prbs_parallel,PRBSStream,SelfSyncStream
        for order in (7,9,15,31):
            for n in (1,8,32):
                word,state=prbs_parallel(order,n)
                bits,expected=prbs_bits(order,n)
                self.assertEqual(([word>>i&1 for i in range(n)],state),(bits,expected))
            stream=PRBSStream(order)
            output=[]
            for n in (1,8,32,7,8):
                before=stream.state
                held=stream.read(n,False);self.assertEqual(stream.state,before)
                word=stream.read(n);self.assertEqual(held,word)
                output.extend(word>>i&1 for i in range(n))
            self.assertEqual(output,prbs_bits(order,len(output))[0]);stream.reset()
            self.assertEqual(stream.read(32),prbs_parallel(order,32)[0])
            data=[i%2 for i in range(111)]
            enc=SelfSyncStream(order);out=enc.process(data[:19])+enc.process(data[19:])
            self.assertEqual(out,selfsync_scramble(data,order))
            dec=SelfSyncStream(order,True);decoded=[]
            for bit in out:
                history=dec.history.copy();dec.push(0,False);self.assertEqual(dec.history,history)
                decoded.append(dec.push(bit))
            self.assertEqual(decoded,data)
            enc.reset();self.assertEqual(enc.process(data),out)

    def test_h_g_matrix_orthogonality_and_bit_types(self):
        from ext_code_basics import hamming_matrices
        for n in (8,16,32,64):
            g,h=hamming_matrices(n)
            self.assertEqual(len(g),n-n.bit_length())
            for row in g:
                for check in h:self.assertEqual(sum(a*b for a,b in zip(row,check))%2,0)
            bits=[int(i%3==0) for i in range(len(g))]
            expected=[sum(bit*row[j] for bit,row in zip(bits,g))%2 for j in range(n)]
            self.assertEqual(hamming_encode(bits),expected)
        for invalid in (0.0,1.0,'1',2,-1):
            with self.assertRaises(ValueError):hamming_encode([invalid,0,0,0])

if __name__=='__main__': unittest.main()
