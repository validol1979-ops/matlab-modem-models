"""Exact OM-LSA per-bin gain intermediate widths (rtl/common/omlsa_gain.sv).

Bounds use the full codes of the stored registers and ROM ports (no reset-reachability claim).
Two documented contracts: power <= 2^47 (its only writer is re^2 + im^2 of signed24 re/im) and
the interface contract alpha <= 65536 (alpha = round(alpha 2^16), checked by the bench).
Variable rounding (gamma, reciprocal) is exact for EVERY shift code 0..127 in W bits when the
raw value is below 2^(W-1): then the half-up addend always fits, and for shifts >= W both the
W-bit and the 128-bit results are zero."""
from itertools import product

U17=(1<<17)-1;GMAX=(1<<31)-1;LN05=-196328
PARAMETERS=('RECIP_WIDTH','GAMMA_WIDTH','XI_WIDTH','V_WIDTH','G1_WIDTH','T_WIDTH','A_WIDTH','OUT_WIDTH','GG_WIDTH','PREV_WIDTH')
POWER_MAX=2*(1<<23)**2


def unsigned_width(high):return max(1,int(high).bit_length())


def signed_width(low,high):
    width=1
    while low<-(1<<(width-1)) or high>=(1<<(width-1)):width+=1
    return width


def rnd(v,s):
    """omlsa_gain rnd/srnd: half up, s = 0 passes v (arbitrary-precision reference)."""
    return v if s==0 else (v+(1<<(s-1)))>>s


def narrow_rnd(v,s,width):
    """The same rounding evaluated in `width` unsigned bits, as the RTL does (v must fit)."""
    mask=(1<<width)-1;assert 0<=v<=mask
    if s==0:return v
    add=(1<<(s-1))&mask if s-1<width else 0
    return ((v+add)&mask)>>s if s<width else 0


def variable_width(high):
    """Smallest W with exact W-bit rounding for every shift code 0..127: high < 2^(W-1)."""
    return unsigned_width(high)+1


def fixed_round(low,high,shift):
    add=1<<(shift-1);return dict(min=low,max=high,add=add,rounded_min=(low+add)>>shift,rounded_max=(high+add)>>shift)


def layout():
    rows={}
    # R(u) = rnd(RECIP_q, rs - 17): full 17-bit ROM code, any 7-bit shift.
    rows['RECIP_WIDTH']=dict(min=0,max=U17,shift='0..127',width=variable_width(U17))
    # gamma = rnd(power rn, zn - 1): power <= 2^47, full 24-bit rn code, any 7-bit shift.
    high=POWER_MAX*((1<<24)-1);rows['GAMMA_WIDTH']=dict(min=0,max=high,shift='0..127',width=variable_width(high))
    # xi = rnd(A prev + (65536 - A) excess, 16), A <= 65536, prev 31 bit, excess <= GMAX - 65536.
    high=max(a*GMAX+(65536-a)*(GMAX-65536) for a in (0,65536));r=fixed_round(0,high,16)
    rows['XI_WIDTH']=dict(r,width=unsigned_width(high+r['add']))
    # v = rnd(gamma w, 16): full 31-bit gamma, full 17-bit w.
    high=GMAX*U17;r=fixed_round(0,high,16);rows['V_WIDTH']=dict(r,width=unsigned_width(high+r['add']))
    # G1 = rnd(w TF, 12): full 17-bit w, full 20-bit TF code.
    high=U17*((1<<20)-1);r=fixed_round(0,high,12);rows['G1_WIDTH']=dict(r,width=unsigned_width(high+r['add']))
    # t = rnd((65536 + xi) TE, 18): full 31-bit xi, full 16-bit TE code.
    high=(65536+GMAX)*((1<<16)-1);r=fixed_round(0,high,18);rows['T_WIDTH']=dict(r,width=unsigned_width(high+r['add']))
    # a = LN05 + srnd(p (LN - LN05), 16): full 17-bit p, full signed19 LN code.
    d=(-(1<<18)-LN05,(1<<18)-1-LN05);values=[p*x for p,x in product((0,U17),d)]
    r=fixed_round(min(values),max(values),16)
    rows['A_WIDTH']=dict(r,difference_min=d[0],difference_max=d[1],difference_width=signed_width(*d),
                         width=signed_width(min(values),max(values)+r['add']))
    # out = srnd(re G, 16): signed24 re/im, full 17-bit G code.
    values=[x*g for x,g in product((-(1<<23),(1<<23)-1),(0,U17))];r=fixed_round(min(values),max(values),16)
    rows['OUT_WIDTH']=dict(r,width=signed_width(min(values),max(values)+r['add']))
    # gg = rnd(G G, 16), prev = rnd(gg gamma, 16).
    high=U17*U17;r=fixed_round(0,high,16);rows['GG_WIDTH']=dict(r,width=unsigned_width(high+r['add']))
    high=r['rounded_max']*GMAX;r=fixed_round(0,high,16);rows['PREV_WIDTH']=dict(r,width=unsigned_width(high+r['add']))
    selected=[rows[name]['width'] for name in PARAMETERS]
    return dict(parameters=list(PARAMETERS),selected=selected,old=[128]*len(PARAMETERS),rows=rows,
                power_max=POWER_MAX,alpha_max=65536,
                contracts=['power<=2^47 (re^2+im^2 of signed24)','alpha<=65536 (interface)'])


def representable(row,width,signed):
    """Every raw value and its rounding addend fit `width` bits (signedness of the RTL wire)."""
    low,high=row['min'],row['max']+row.get('add',0)
    return -(1<<(width-1))<=low and high<(1<<(width-1)) if signed else 0<=low and high<(1<<width)


SIGNED={'A_WIDTH','OUT_WIDTH'}
