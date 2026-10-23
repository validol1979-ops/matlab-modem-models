% p2_44a.m   Problem 2.44a to approximate a continuous time 
% convolution
% 
% we ENCODE as before, setting n=nr-1 and m=mr-1, getting
%	y(nr-1)=sum(h(mr-1)*x(nr-mr), mr=1,...,M), nr=1,...,N
% or
%	yr(nr)=sum[hr(mr)*xr(nr-mr+1), mr=1,...,M], nr=1,...,N
% this last form we can implement in matlab
%
	clear
	clf
	Th=1;
	Tx=3;
	a=2;
	b=3;
% define length of all sequences
	N=256;
	nr=1:N;
	n=nr-1;
	Ts=(Th+Tx)/N;
% define the moving average filter weights
	M=Th/Ts;
	mr=1:M;
	m=mr-1;
	hr=a*[ones(1,M),zeros(1,N-M)];
% define the inputsequence
	L=Tx/Ts;
	xr=b*[ones(1,L),zeros(1,N-L)];
	for nr=1:N
		yr(nr)=0.0;
		for mr=1:M
			if nr-mr+1>=1 & nr-mr+1<=N
				yr(nr)=yr(nr)+xr(nr-mr+1)*hr(mr)*Ts;
			end
		end
	end
	plot(n,xr,n,yr,'r')
%	axis([0 N-1 -10 10])
	xlabel('discrete time  ')
	title('a moving average')