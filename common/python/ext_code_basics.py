"""Python reference models: CRC, PRBS/LFSR scrambling, extended Hamming.

Stdlib only. Bits are lists of ints 0/1; first element is the first bit on the wire.

CRC
  crc(data, width, poly, init, refin, refout, xorout)
      Byte-oriented CRC. If refin, each byte is consumed LSB-first (explicit
      per-byte bit order, as in the Rocksoft model); otherwise MSB-first.
      If refout, the final register is reflected over `width` bits. No other
      byte reversal happens.
  crc_bits(bits, width, poly, init, refin=False, refout=False, xorout=0)
      Bit-level CRC. Bits are consumed in list order. refin=True means the
      list is grouped in bytes and each byte is reversed before consumption
      (same explicit rule as crc()). refout reflects the final register.
  crc_update(state, bits, width, poly, reflected=False)
      Raw incremental update, no init/xorout/reflection of I/O.
      reflected=False: `poly` is the normal (MSB-first) polynomial, top bit
      implicit, e.g. 0x04C11DB7; register shifts left.
      reflected=True : `poly` is the LSB-reflected polynomial (bit i = coefficient
      of x^(width-1-i)), e.g. 0xEDB88320 for CRC-32; register shifts right.
      The state is kept in the orientation of the chosen mode.

LFSR / PRBS (Fibonacci, shift right)
  Connection polynomial x^n + x^k + 1 with (n,k) in {(7,6),(9,5),(15,14),(31,28)}.
  Each step: out = state & 1; fb = (state & 1) ^ ((state >> (n-k)) & 1);
  state = (state >> 1) | (fb << (n-1)).  This is NOT a Galois LFSR; the
  tap for x^k is taken at bit (n-k) of the state register. This is the
  reversed-register connection-polynomial convention (source REVERSE mode).
  The forward output-recurrence characteristic is its reciprocal,
  E^n+E^(n-k)+1 with E the forward shift; the delay-connection
  polynomial is C(D)=1+D^k+D^n with D the unit delay. No universal external PRBS bit-vector convention is claimed.
  Self-sync filters below independently use their explicitly named delays.

Hamming (extended SECDED, positional layout)
  Codeword length N = 2^r (r=3..6 -> N=8,16,32,64), data k = N - r - 1
  (4,11,26,57). Positions 1..N-1 (index i-1 in the list): parity bits at
  powers of two, data at non-powers in increasing order. Index N-1 is the
  overall (even) parity over all N bits. Minimum distance 4.
  NOTE: the source README (32,26,5) is ambiguous; no d_min=5 claim is made.
  The source RTL uses a systematic column permutation (generate_permutation),
  which differs from this positional API; codewords are not interchangeable.
  No guarantees for errors beyond the SECDED capability.
"""

__all__ = [
    "crc", "crc_bits", "crc_update",
    "prbs_bits", "lfsr_jump", "additive_scramble", "additive_descramble",
    "selfsync_scramble", "selfsync_descramble",
    "hamming_encode", "hamming_decode",
]


# ---------------------------------------------------------------- helpers

def _check_bits(bits, name="bits"):
    out = []
    for b in bits:
        if not isinstance(b, int) or isinstance(b, bool) or b not in (0, 1):
            raise ValueError(f"{name} must contain only 0/1, got {b!r}")
        out.append(int(b))
    return out


def _check_width(width):
    if not isinstance(width, int) or isinstance(width, bool) or width < 1:
        raise ValueError("width must be a positive int")


def _check_uint(value, width, name):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value < (1 << width):
        raise ValueError(f"{name} must be an int in [0, 2^{width})")


def _reflect(value, width):
    r = 0
    for _ in range(width):
        r = (r << 1) | (value & 1)
        value >>= 1
    return r


def _byte_bits(data, refin):
    out = []
    for byte in data:
        bb = [(byte >> (7 - i)) & 1 for i in range(8)]  # MSB-first
        out.extend(bb[::-1] if refin else bb)
    return out


# ---------------------------------------------------------------- CRC

def crc_update(state, bits, width, poly, reflected=False):
    """Raw incremental CRC register update over `bits` (no init/xorout)."""
    _check_width(width)
    _check_uint(state, width, "state")
    _check_uint(poly, width, "poly")
    bits = _check_bits(bits)
    mask = (1 << width) - 1
    if not reflected:
        for b in bits:
            fb = ((state >> (width - 1)) ^ b) & 1
            state = (state << 1) & mask
            if fb:
                state ^= poly
    else:
        for b in bits:
            fb = (state ^ b) & 1
            state >>= 1
            if fb:
                state ^= poly
    return state


def crc_bits(bits, width, poly, init, refin=False, refout=False, xorout=0):
    """Bit-level CRC (see module docstring for refin/refout semantics)."""
    _check_width(width)
    _check_uint(poly, width, "poly")
    _check_uint(init, width, "init")
    _check_uint(xorout, width, "xorout")
    bits = _check_bits(bits)
    if refin:
        if len(bits) % 8:
            raise ValueError("refin=True requires a whole number of bytes")
        bits = [b for i in range(0, len(bits), 8) for b in bits[i:i + 8][::-1]]
    reg = crc_update(init, bits, width, poly, reflected=False)
    if refout:
        reg = _reflect(reg, width)
    return reg ^ xorout


def crc(data, width=32, poly=0x04C11DB7, init=0xffffffff, refin=True, refout=True,
        xorout=0xffffffff):
    """Byte-oriented CRC. Defaults give CRC-32/ISO-HDLC (Ethernet)."""
    _check_width(width)
    _check_uint(poly, width, "poly")
    _check_uint(init, width, "init")
    _check_uint(xorout, width, "xorout")
    if isinstance(data, str) or not hasattr(data, "__iter__"):
        raise TypeError("data must be bytes-like")
    data = bytes(data)
    reg = crc_update(init, _byte_bits(data, refin), width, poly, reflected=False)
    if refout:
        reg = _reflect(reg, width)
    return reg ^ xorout


# ---------------------------------------------------------------- LFSR / PRBS

_TAPS = {7: 6, 9: 5, 15: 14, 31: 28}


def _lfsr_check(order):
    if order not in _TAPS:
        raise ValueError(f"order must be one of {sorted(_TAPS)}")
    return order, _TAPS[order]


def _lfsr_step(state, n, k):
    out = state & 1
    fb = (state & 1) ^ ((state >> (n - k)) & 1)
    state = (state >> 1) | (fb << (n - 1))
    return out, state


def prbs_bits(order, n, seed=None):
    """Return (bits, final_state) for n output bits of x^order + x^k + 1 PRBS."""
    order, k = _lfsr_check(order)
    if not isinstance(n, int) or isinstance(n, bool) or n < 0:
        raise ValueError("n must be a non-negative int")
    if seed is None:
        seed = (1 << order) - 1
    _check_uint(seed, order, "seed")
    if seed == 0:
        raise ValueError("seed must be nonzero")
    state = seed
    bits = []
    for _ in range(n):
        o, state = _lfsr_step(state, order, k)
        bits.append(o)
    return bits, state


def _matrix_mul(a, b):
    # matrices as list of row-bitmasks over GF(2); a*b
    n = len(a)
    res = []
    for i in range(n):
        row = 0
        for j in range(n):
            if (a[i] >> j) & 1:
                row ^= b[j]
        res.append(row)
    return res


def lfsr_jump(order, steps, seed=None):
    """State after `steps` transitions, via GF(2) matrix exponentiation."""
    order, k = _lfsr_check(order)
    if not isinstance(steps, int) or isinstance(steps, bool) or steps < 0:
        raise ValueError("steps must be a non-negative int")
    if seed is None:
        seed = (1 << order) - 1
    _check_uint(seed, order, "seed")
    if seed == 0:
        raise ValueError("seed must be nonzero")
    # transition matrix: column j = image of basis vector e_j.
    # Row-bitmask representation: T[i] bit j = coefficient of e_j in new state bit i.
    cols = []
    for j in range(order):
        _, nxt = _lfsr_step(1 << j, order, k)
        cols.append(nxt)
    T = [0] * order
    for j, col in enumerate(cols):
        for i in range(order):
            if (col >> i) & 1:
                T[i] |= 1 << j
    R = [1 << i for i in range(order)]  # identity
    P = T
    e = steps
    while e:
        if e & 1:
            R = _matrix_mul(P, R)
        P = _matrix_mul(P, P)
        e >>= 1
    state = 0
    for i in range(order):
        if bin(R[i] & seed).count("1") & 1:
            state |= 1 << i
    return state


def additive_scramble(bits, order, seed=None):
    """XOR bits with PRBS keystream (self-inverse; same call descrambles)."""
    bits = _check_bits(bits)
    ks, _ = prbs_bits(order, len(bits), seed)
    return [b ^ s for b, s in zip(bits, ks)]


additive_descramble = additive_scramble


def selfsync_scramble(bits, order, delays=None):
    """Self-synchronising scrambler: s[i] = d[i] ^ s[i-k] ^ s[i-n], zero init.

    delays defaults to (k, n) = taps of the polynomial for `order`.
    """
    _, k = _lfsr_check(order)
    n = order
    bits = _check_bits(bits)
    k, n = delays if delays is not None else (k, n)
    if not (1 <= k < n):
        raise ValueError("delays must satisfy 1 <= k < n")
    out = []
    for i, d in enumerate(bits):
        a = out[i - k] if i - k >= 0 else 0
        b = out[i - n] if i - n >= 0 else 0
        out.append(d ^ a ^ b)
    return out


def selfsync_descramble(bits, order, delays=None):
    """Feed-forward descrambler: d[i] = r[i] ^ r[i-k] ^ r[i-n], zero init."""
    _, k = _lfsr_check(order)
    n = order
    bits = _check_bits(bits)
    k, n = delays if delays is not None else (k, n)
    if not (1 <= k < n):
        raise ValueError("delays must satisfy 1 <= k < n")
    out = []
    for i, r in enumerate(bits):
        a = bits[i - k] if i - k >= 0 else 0
        b = bits[i - n] if i - n >= 0 else 0
        out.append(r ^ a ^ b)
    return out


# ---------------------------------------------------------------- Hamming

_HAM_R = {3: 4, 4: 11, 5: 26, 6: 57}  # r -> data bits k (N = 2^r)


def _ham_params(N):
    if N not in (8, 16, 32, 64):
        raise ValueError("codeword length must be 8, 16, 32 or 64")
    r = N.bit_length() - 1
    return r, N - r - 1


def _positions_data(N):
    r, _ = _ham_params(N)
    m = N - 1
    data_pos = [p for p in range(1, m + 1) if p & (p - 1)]
    return data_pos


def hamming_encode(bits):
    """Encode k in {4,11,26,57} data bits to extended-Hamming word of length 2^r."""
    bits = _check_bits(bits)
    k = len(bits)
    N = None
    for cand in (8, 16, 32, 64):
        if _ham_params(cand)[1] == k:
            N = cand
    if N is None:
        raise ValueError("data length must be 4, 11, 26 or 57")
    m = N - 1
    word = [0] * N  # index i <-> position i+1; index m is overall parity
    for p, b in zip(_positions_data(N), bits):
        word[p - 1] = b
    s = 0
    for p in range(1, m + 1):
        if word[p - 1]:
            s ^= p
    for r in range(m.bit_length()):
        if (s >> r) & 1:
            word[(1 << r) - 1] = 1
    word[m] = sum(word[:m]) & 1  # overall even parity
    return word


def hamming_decode(word):
    """Return (data_bits, status, corrected_word).

    status: 'clean' | 'corrected' | 'detected_double'.
    On detected_double the received word is returned unchanged.
    """
    word = _check_bits(word, "word")
    N = len(word)
    _, k = _ham_params(N)
    m = N - 1
    s = 0
    for p in range(1, m + 1):
        if word[p - 1]:
            s ^= p
    p_all = sum(word) & 1
    if s == 0 and p_all == 0:
        status, out = "clean", list(word)
    elif p_all == 1:
        out = list(word)
        if s == 0:
            out[m] ^= 1           # overall parity bit itself flipped
        elif s <= m:
            out[s - 1] ^= 1       # single error at position s
        else:
            return ([word[p - 1] for p in _positions_data(N)], "detected_double", list(word))
        status = "corrected"
    else:
        return ([word[p - 1] for p in _positions_data(N)], "detected_double", list(word))
    data = [out[p - 1] for p in _positions_data(N)]
    return data, status, out

# Parallel datapaths use precomputed GF(2) matrices, not run-time serial updates.
from functools import lru_cache

@lru_cache(maxsize=128)
def _crc_parallel_rows(width, poly, nbits, reflected):
    columns=[]
    for i in range(width+nbits):
        state=(1<<i) if i<width else 0
        bits=[int(j==i-width) for j in range(nbits)]
        columns.append(crc_update(state,bits,width,poly,reflected))
    return tuple(sum(((col>>r)&1)<<c for c,col in enumerate(columns)) for r in range(width))

def crc_parallel(state, word, nbits, width=32, poly=0x04c11db7, reflected=False):
    """One GF(2) word update: normal word MSB first; reflected word LSB first.

    Polynomial orientation follows crc_update. Supports partial words 0..32 bits.
    """
    _check_width(width);_check_uint(state,width,'state');_check_uint(poly,width,'poly')
    if not isinstance(nbits,int) or isinstance(nbits,bool) or not 0<=nbits<=32: raise ValueError('nbits must be 0..32')
    _check_uint(word,nbits,'word')
    wire=word if reflected else _reflect(word,nbits)
    vector=state|(wire<<width)
    return sum(((row&vector).bit_count()&1)<<r for r,row in enumerate(_crc_parallel_rows(width,poly,nbits,bool(reflected))))

_FCS_PROFILES={'ethernet':(32,0x04c11db7,0xffffffff,True,True,0xffffffff,'little'),
               'ccitt_false':(16,0x1021,0xffff,False,False,0,'big')}

def append_fcs(data, profile='ethernet'):
    """Append Ethernet CRC32 little endian or CCITT-FALSE CRC16 big endian."""
    if profile not in _FCS_PROFILES: raise ValueError('unknown FCS profile')
    data=bytes(data);width,poly,init,ri,ro,xo,endian=_FCS_PROFILES[profile]
    return data+crc(data,width,poly,init,ri,ro,xo).to_bytes(width//8,endian)

def check_fcs(packet, profile='ethernet'):
    """Return False on short/corrupt complete frame; preserve caller packet."""
    if profile not in _FCS_PROFILES: raise ValueError('unknown FCS profile')
    packet=bytes(packet);size=_FCS_PROFILES[profile][0]//8
    return len(packet)>=size and append_fcs(packet[:-size],profile)==packet

@lru_cache(maxsize=32)
def _prbs_word_rows(order, nbits):
    columns=[prbs_bits(order,nbits,1<<i) for i in range(order)]
    outputs=tuple(sum(bits[r]<<i for i,(bits,_) in enumerate(columns)) for r in range(nbits))
    states=tuple(sum(((state>>r)&1)<<i for i,(_,state) in enumerate(columns)) for r in range(order))
    return outputs,states

def prbs_parallel(order, nbits=8, seed=None):
    """GF(2) parallel PRBS bits and state, with wire bit0 first in returned word."""
    _lfsr_check(order)
    if not isinstance(nbits,int) or isinstance(nbits,bool) or not 1<=nbits<=32: raise ValueError('nbits must be 1..32')
    if seed is None:seed=(1<<order)-1
    _check_uint(seed,order,'seed')
    if seed==0:raise ValueError('seed must be nonzero')
    outputs,states=_prbs_word_rows(order,nbits)
    return (sum(((r&seed).bit_count()&1)<<i for i,r in enumerate(outputs)),
            sum(((r&seed).bit_count()&1)<<i for i,r in enumerate(states)))

class PRBSStream:
    """Stateful accepted-word PRBS. A rejected word reports current bits, holds state."""
    def __init__(self,order,seed=None):
        _lfsr_check(order);self.order=order;self.seed=(1<<order)-1 if seed is None else seed
        prbs_bits(order,0,self.seed);self.state=self.seed
    def read(self,nbits=8,accept=True):
        word,state=prbs_parallel(self.order,nbits,self.state)
        if accept:self.state=state
        return word
    def reset(self):self.state=self.seed

class SelfSyncStream:
    """Self-sync chunk-carry model; delays(k,n), zero history, held output on stall."""
    def __init__(self,order,descramble=False):
        _,self.k=_lfsr_check(order);self.order=order;self.descramble=bool(descramble);self.reset()
    def reset(self):self.history=[0]*self.order;self.output=0
    def push(self,bit,accept=True):
        bit=_check_bits([bit])[0]
        if accept:
            value=bit^self.history[-self.k]^self.history[-self.order]
            self.history=self.history[1:]+[bit if self.descramble else value]
            self.output=value
        return self.output
    def process(self,bits):return [self.push(bit) for bit in _check_bits(bits)]

def hamming_matrices(n):
    """Return binary G(k x n), H((r+1) x n) in this positional SECDED layout."""
    r,k=_ham_params(n)
    h=[[((p>>j)&1) for p in range(1,n)]+[0] for j in range(r)]+[[1]*n]
    g=[]
    for p in _positions_data(n):
        row=[0]*n;row[p-1]=1
        for j in range(r):row[(1<<j)-1]=(p>>j)&1
        row[-1]=sum(row[:-1])&1;g.append(row)
    return g,h

__all__ += ['crc_parallel','append_fcs','check_fcs','prbs_parallel','PRBSStream','SelfSyncStream','hamming_matrices']
