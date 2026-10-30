"""Independent integer bounds, arithmetic and configuration traces for MMSE."""
from itertools import product


def interval(lo,hi):
    width=1
    while lo<-(1<<(width-1)) or hi>=(1<<(width-1)):width+=1
    return dict(min=lo,max=hi,bits=width)


def scale_bounds():
    p=1<<128
    return dict(m_bits=106,weight_bits=64,reciprocal=[1<<22,1<<23],shift=[8,134],amount=[-16,110],
                product=interval(-p,p-(1<<23)),round_add=interval(-p+1,p-(1<<23)+(1<<109)),
                scaled=interval(-(1<<144),(1<<144)-(1<<39)))


def scale(value,r,shift):
    if type(value) is not int or not -(1<<105)<=value<(1<<105):raise ValueError('M106')
    if type(r) is not int or not 1<<22<=r<=1<<23:raise ValueError('Normalized reciprocal')
    if type(shift) is not int or not 8<=shift<=134:raise ValueError('Normalized shift')
    p=value*r;a=shift-24
    y=(p+(1<<(a-1)))>>a if a>0 else p<<(-a)
    return p,y,not -(1<<63)<=y<(1<<63)


def cmul(a,b):return a[0]*b[0]-a[1]*b[1],a[0]*b[1]+a[1]*b[0]
def rnd(v,amount=30):return (v+(1<<(amount-1)))>>amount if amount>0 else v<<(-amount)


def update(m,source,current,bits):
    for pair,width in ((m,48),(source,bits),(current,bits)):
        if len(pair)!=2 or any(type(v) is not int or not -(1<<(width-1))<=v<(1<<(width-1)) for v in pair):raise ValueError('Stored code')
    p=cmul(m,source);return (*p,current[0]-rnd(p[0]),current[1]-rnd(p[1]))


def update_bounds(bits):
    m=( -(1<<47),(1<<47)-1);s=(-(1<<(bits-1)),(1<<(bits-1))-1)
    vals=[update(v[:2],v[2:4],v[4:],bits) for v in product(m,m,s,s,s,s)]
    axes=[interval(min(v[i] for v in vals),max(v[i] for v in vals)) for i in range(4)]
    return dict(source_bits=bits,axes=axes,product_bits=max(v['bits'] for v in axes[:2]),update_bits=max(v['bits'] for v in axes[2:]))


def layout():return dict(scale=scale_bounds(),a=update_bounds(34),b=update_bounds(72))


def banks(rows,fields):
    return [dict(count=len(rows),min=min(v[i] for v in rows),max=max(v[i] for v in rows)) for i in range(fields)]


def divide(num,den):
    q,r=divmod(abs(num),den);q+=int(2*r>den or (2*r==den and q%2))
    return -q if num<0 else q


def scale_trace(h,lam):
    from mmse3_config_widths import trace
    t=trace(h,lam);d=t['det'][0]
    if not 0<d<(1<<127):raise ValueError('Det128')
    z=22+d.bit_length();r=divide(1<<z,d);rows=[scale(v,r,z-15) for pair in t['m'] for v in pair]
    if any(v[2] for v in rows):raise ValueError('Coefficient64')
    # product_re/product_im/scaled_re/scaled_im, each nine observations.
    b=[banks([rows[i] for i in range(c,len(rows),2)],2) for c in (0,1)]
    return dict(banks=[b[0][0],b[1][0],b[0][1],b[1][1]],weights=[(rows[i][1],rows[i+1][1]) for i in range(0,len(rows),2)])


def update_trace(h,lam,n):
    """Own elimination trace; no use of fixed-model intermediate state."""
    from mmse_n_widths import gram
    g=gram(h,lam,n);G={(i,j):(g[2*(n*i+j)],g[2*(n*i+j)+1]) for i in range(n) for j in range(i,n)}
    e=max(G[i,i][0] for i in range(n)).bit_length()-31
    A={k:tuple(rnd(x,e) for x in v) for k,v in G.items()}
    B=[[(h[n*j+i][0]<<24,-h[n*j+i][1]<<24) for j in range(n)] for i in range(n)]
    events=[[],[]];ds=[]
    for k in range(n):
        d=A[k,k][0]
        if d<=0:raise ValueError('Pivot')
        ds.append(d)
        for i in range(k+1,n):
            a=A[k,i];m=(divide(a[0]<<30,d),divide(-a[1]<<30,d))
            for j in range(i,n):
                row=update(m,A[k,j],A[i,j],34);events[0].append(row)
                A[i,j]=(row[2],0 if i==j else row[3])
            for j in range(n):
                row=update(m,B[k][j],B[i][j],72);events[1].append(row);B[i][j]=row[2:]
    for k in reversed(range(n)):
        for j in range(n):
            re,im=B[k][j][0]<<30,B[k][j][1]<<30
            for c in range(k+1,n):
                p=cmul(A[k,c],B[c][j]);re-=p[0];im-=p[1]
            B[k][j]=(divide(re,ds[k]),divide(im,ds[k]))
    return dict(banks=banks(events[0],4)+banks(events[1],4),weights=[tuple(rnd(v,e+15) for v in pair) for row in B for pair in row])
