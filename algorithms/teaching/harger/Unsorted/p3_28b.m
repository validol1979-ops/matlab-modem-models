% p3_28b.m  to exhibit the computation of dft s of problem
% 3.28b of text
%
% the period of the wave is seen to be N=12: consider sum and
% difference frequencies using a trig identity...
%
clear, clc, clf
N=12;
nr=(1:N);
n=nr-1;
k=n;
w1=(2*pi/N)*4;
w2=(2*pi/N)*3;
xr=sin(w1*n).*cos(w2*n);
WN=exp(-i*2*pi/N);
for krr=1:N
	Xr(krr)=0.0;
	for nrr=1:N
		Xr(krr)=Xr(krr)+xr(nrr)*WN^((krr-1)*(nrr-1));
	end
end
subplot(2,1,1)
plot(n,xr,'o')
axis([0 N-1 -1.5 1.5])
title('Sequence')
xlabel('n (discrete time index)')
subplot(2,1,2)
plot(k,abs(Xr),'xr')
axis([0 N-1 -N N])
title('DFT')
xlabel('k (discrete frequency index)')