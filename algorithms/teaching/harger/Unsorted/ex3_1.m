% ex3_1.m  to exhibit the computation of dft s
%
N=32;
nr=(1:N);
n=nr-1;
k=n;
L=5;
% xr=[ones(1,L),zeros(1,N-L)];
w=(2*pi/N)*5;
xr=cos(w*n);
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