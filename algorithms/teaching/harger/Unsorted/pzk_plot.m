% pzk_plot.m  to make a surface plot of the 
% magnitude of a (digital) filter's transfer function
%
clear, clc, clf; hold off
%
N=32;
x=(1.11:-2.2/N:-1.1);
y=(1.1:-2.2/N:-1.1);
%
q=input('enter zeros in column vector [q(1);q(2);...] ')
p=input('enter poles in column vector [p(1);p(2);...]  ')
k=input('enter gain (k, scalar)  ')
for m=1:N+1
for n=1:N+1
	z(m,n)=x(m)+i*y(n);
end
end
b=k*poly(q);
a=poly(p);
numer=polyval(b,z);
denom=polyval(a,z);
Z=k*(numer./denom);
for m=1:N+1
for n=1:N+1
	Zmag(m,n)=abs(Z(m,n));
	if Zmag(m,n) > 10
		Zmag(m,n)=10;
	end
	if abs(z(m,n))>1
		Zmag(m,n)=0;
	end
end
end
[X,Y]=meshgrid(-1.1:2.2/N:1.1);
figure(1)
surf(X,Y,Zmag)
axis([-1.25 1.25 -1.25 1.25 0 10])
title('Pole-Zero Surface Plot')
figure(2)
v=0:10;
contour(Zmag,v)
title('Pole-Zero Contour Plot')