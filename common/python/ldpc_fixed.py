"""Integer LDPC decoder and systematic GF(2) encoder (references of rtl/common/ldpc_decoder.sv
and gf2_encoder.sv; research_core ldpc and gf2_encode, algorithms/coding/ldpc).

Decoder (flooding, as research_core.ldpc_decode): LLRs are Q8 (16 bit, saturated, positive =
bit 0). Per iteration, from the previous posterior P and the edge messages M:
  v = sat16(P[col] - M[j,col]) for every edge (j, col) of check j;
  min-sum family (mode 1, 2, 3): magnitude = min over the other edges of |v|, sign = product
  of the other signs (np.sign: a zero v gives a zero message); mode 2 scales by ALPHA
  (rnd(min*ALPHA, 8), ALPHA = round(alpha*256)), mode 3 subtracts BETA = round(beta*256)
  (at least 0);
  sum-product (mode 0) in the phi domain, phi(x) = -ln tanh(x/2) (its own inverse):
  PHI[q] = round(phi((q + 0.5)/32)*4096) (Q12, capped to 65535) with q = min(|v| >> 3, 2047);
  S = sum over the edges of PHI; T = S - own; magnitude = INV[i] (Q8) with i = T >> 2 for
  T < 4096 (phi of (i + 0.5)/1024) and i = 1024 + min((T - 4096) >> 6, 1023) above (phi of
  1 + (i - 1024 + 0.5)/64); the sign is the product of the other signs (a zero v among the
  others makes the message 0).
  P = sat16(L + sum of the new messages); bits = P < 0; stop when H bits = 0 (mod 2).
Encoder: parity = A bits mod 2, output [parity, bits].
round is half up, (v + 2^(s-1)) >> s."""
import math
import fft_fixed as f

LIMIT16=(1<<15)-1
def _phi(x):return -math.log(math.tanh(x/2))
PHI=tuple(min(65535,round(_phi((q+.5)/32)*4096)) for q in range(2048))
INV=tuple(min(LIMIT16,round(_phi((i+.5)/1024)*256)) for i in range(1024))+tuple(min(LIMIT16,round(_phi(1+(i+.5)/64)*256)) for i in range(1024))


def inv_index(t):return t>>2 if t<4096 else 1024+min((t-4096)>>6,1023)


def sat16(v):return max(-LIMIT16-1,min(LIMIT16,v))
def sign(v):return (v>0)-(v<0)


def quantize_llr(llr):return [sat16(int(round(float(v)*256))) for v in llr]


def decode(llr,H,iterations,mode,alpha=.8,beta=.15,stats=None):
    """Decode n Q8 LLRs; `stats` (optional sat_diag.SatStats/SatTrace) counts the pre-clamp
    signed16 values of the two saturating stages: 'v' = post[col] - old message on every real
    edge of every iteration, 'post' = llr[c] + sum of the new messages on every logical column
    of every iteration. sat16 uses the asymmetric rails
    (-32768, 32767), so record(..., LIMIT16, 'asym') reproduces sat16 exactly and instrumented
    and plain runs are bit-identical. With stats=None the numerical result is the plain model."""
    m=len(H);n=len(H[0])
    if mode not in (0,1,2,3) or iterations<1 or len(llr)!=n or any(sum(row)<2 for row in H):raise ValueError('Invalid LDPC decoder call')
    a=int(round(alpha*256));b=int(round(beta*256))
    checks=[[c for c in range(n) if H[j][c]] for j in range(m)]
    msg={(j,c):0 for j in range(m) for c in checks[j]}
    post=list(llr);bits=[int(p<0) for p in post];used=0
    for it in range(iterations):
        used=it+1;new={}
        for j,cols in enumerate(checks):
            if stats is None:
                v={c:sat16(post[c]-msg[j,c]) for c in cols}
            else:
                v={c:stats.record('v',post[c]-msg[j,c],LIMIT16,'asym') for c in cols}
            if mode==0:
                phi={c:PHI[min(abs(v[c])>>3,2047)] for c in cols};total=sum(phi.values())
                for c in cols:
                    others=1
                    for o in cols:
                        if o!=c:others*=sign(v[o])
                    new[j,c]=others*INV[inv_index(total-phi[c])]
            else:
                for c in cols:
                    rest=[v[o] for o in cols if o!=c];magnitude=min(abs(t) for t in rest)
                    if mode==2:magnitude=f.rnd(magnitude*a,8)
                    if mode==3:magnitude=max(0,magnitude-b)
                    s=1
                    for t in rest:s*=sign(t)
                    new[j,c]=s*magnitude
        msg=new
        if stats is None:
            post=[sat16(llr[c]+sum(msg[j,c] for j in range(m) if H[j][c])) for c in range(n)]
        else:
            post=[stats.record('post',llr[c]+sum(msg[j,c] for j in range(m) if H[j][c]),LIMIT16,'asym')
                  for c in range(n)]
        bits=[int(p<0) for p in post]
        if not any(sum(bits[c] for c in cols)%2 for cols in checks):break
    return bits,post,used


def encode(bits,A):
    if any(len(row)!=len(bits) for row in A):raise ValueError('Generator rows must match the message')
    return [sum(a&b for a,b in zip(row,bits))%2 for row in A]+list(bits)
