"""Independent full stored-code bounds and normalized/back-substitution traces."""
from itertools import product
from mmse_scale_update_widths import interval,cmul,rnd,update,divide,banks


def bounds(n):
    if type(n) is not int or not 2<=n<=8:raise ValueError('N2..8')
    a,b=1<<33,1<<71;t=n-1;p=2*a*b
    return dict(norm=interval(-(1<<69),(1<<69)-(1<<30)),
                weight=interval(-(1<<86),(1<<86)-(1<<15)),
                mult_re=interval(-(1<<63),(1<<63)-(1<<30)),mult_im=interval(-(1<<63)+(1<<30),1<<63),
                product_re=interval(-p+a,p-a),product_im=interval(-p+2*a,p),
                acc_re=interval(-(1<<101)-t*(p-a),(1<<101)-(1<<30)+t*(p-a)),
                acc_im=interval(-(1<<101)-t*p,(1<<101)-(1<<30)+t*(p-2*a)))


def trace(h,lam,n):
    """Own elimination trace; no use of fixed-model intermediate state."""
    from mmse_n_widths import gram
    g=gram(h,lam,n);G={(i,j):(g[2*(n*i+j)],g[2*(n*i+j)+1]) for i in range(n) for j in range(i,n)}
    e=max(G[i,i][0] for i in range(n)).bit_length()-31
    A={k:tuple(rnd(x,e) for x in v) for k,v in G.items()}
    B=[[(h[n*j+i][0]<<24,-h[n*j+i][1]<<24) for j in range(n)] for i in range(n)]
    events=[[],[]];ds=[]
    norm=[tuple(rnd(x,e) for x in G[i,j]) for i in range(n) for j in range(n) if j>=i]
    nums=[];products=[];accs=[];weights=[]
    for k in range(n):
        d=A[k,k][0]
        if d<=0:raise ValueError('Pivot')
        ds.append(d)
        for i in range(k+1,n):
            a=A[k,i];nums.append((a[0]<<30,-a[1]<<30));m=(divide(a[0]<<30,d),divide(-a[1]<<30,d))
            for j in range(i,n):
                row=update(m,A[k,j],A[i,j],34);events[0].append(row)
                A[i,j]=(row[2],0 if i==j else row[3])
            for j in range(n):
                row=update(m,B[k][j],B[i][j],72);events[1].append(row);B[i][j]=row[2:]
    for k in reversed(range(n)):
        for j in range(n):
            re,im=B[k][j][0]<<30,B[k][j][1]<<30
            accs.append((re,im))
            for c in range(k+1,n):
                p=cmul(A[k,c],B[c][j]);products.append(p);re-=p[0];im-=p[1];accs.append((re,im))
            B[k][j]=(divide(re,ds[k]),divide(im,ds[k]))
    weights=[tuple(rnd(v,e+15) for v in pair) for row in B for pair in row]
    return dict(banks=sum((banks(rows,2) for rows in (norm,nums,products,accs,weights)),[]),weights=weights)
