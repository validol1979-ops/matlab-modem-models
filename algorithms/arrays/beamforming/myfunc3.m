function f=myfunc3(mu_sig2,xi)

A=0.5;
f_vec=[0.05 0.1 0.15 0.2 0.25 0.3 0.35 0.4];
L=15;
K=4;

i_i=[1; zeros(L-1,1)];
[t1,t2]=meshgrid(1:L,1:L);
Rx=0.5*A^2*cos(2*pi*f_vec(1)*(t1-t2));
for k=2:K
    Rx=Rx+0.5*A^2*cos(2*pi*f_vec(k)*(t1-t2));
end
h=(Rx+mu_sig2*eye(L))\Rx*i_i;
f=h'*h-1/xi;