"""Exact RLS update bounds on full stored operand codes; no reset reachability claim."""
from itertools import product


def signed_width(low,high):
    width=1
    while low<-(1<<(width-1)) or high>=(1<<(width-1)):width+=1
    return width


def complex_bounds(a_width,b_width,shift):
    a=(-(1<<(a_width-1)),(1<<(a_width-1))-1);b=(-(1<<(b_width-1)),(1<<(b_width-1))-1)
    values=[(x*z+y*t,y*z-x*t) for x,y,z,t in product(a,a,b,b)]
    rows=[]
    for k in (0,1):
        low=min(v[k] for v in values);high=max(v[k] for v in values);add=1<<(shift-1)
        rows.append(dict(min=low,max=high,width=signed_width(low,high),rounded_min=(low+add)>>shift,rounded_max=(high+add)>>shift))
    return rows


def layout():
    update=complex_bounds(40,18,15);pt=complex_bounds(40,48,30)
    delta=(1<<43)+(1<<45)-1;cov=delta*((1<<32)-1)
    weights=[dict(min=r['rounded_min']-(1<<33),max=r['rounded_max']+(1<<33)-1) for r in update]
    return dict(gain_width=71,update_width=59,weight_width=44,pt_width=89,cov_width=79,cov_delta_width=47,
                gain_min=-(1<<70),gain_max=((1<<47)-1)*(1<<23),update=update,pt=pt,weights=weights,
                cov_delta_min=-delta,cov_delta_max=delta,cov_min=-cov,cov_max=cov,
                old_widths=[128]*5,variable_gain_rounding_width=128)
