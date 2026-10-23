% pzk_plta.m  to make a surface plot of the 
% magnitude of an analog filter's transfer function
%
clear, clc, clf; hold off
%
disp('you will be asked to enter the zeros, poles and gain')
disp('the |TF| surface will be plotted')
disp('over the region -10<x<1 and -10<y<10')
q=input('enter zeros in column vector [q(1);q(2);...] ')
p=input('enter poles in column vector [p(1);p(2);...]  ')
k=input('enter gain (k, scalar)  ')
% a trial set of parameters to exhibit program
% q=[0;inf];
% p=[-1-3*i;-1+3*i];
% k=3;
% 
N=32;
dx=20/N;
dy=20/N;
x=(10:-dx:-10);
y=(-10:dy:10); 
%
for m=1:N+1
for n=1:N+1
	s(m,n)=x(m)+i*y(n);
end
end
b=k*poly(q);
a=poly(p);
numer=polyval(b,s);
denom=polyval(a,s);
S=k*(numer./denom);
for m=1:N+1
for n=1:N+1
	Smag(m,n)=abs(S(m,n));
	if Smag(m,n) > 10
		Smag(m,n)=10;
	end
	if x(m)>0
		Smag(m,n)=0;
	end
end
end
[X,Y]=meshgrid(x,y);
figure(1)
surf(X,Y,Smag)
axis([-10 10 -10 10 0 10])
title('Pole-Zero Surface Plot: Analog Filter')
% figure(2)
% v=0:10;
% contour(Smag,v)
% title('Pole-Zero Contour Plot')