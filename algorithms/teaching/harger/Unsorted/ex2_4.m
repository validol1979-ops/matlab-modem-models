% ex2_4.m   Example 2.4 to implement a 
% general/weighted moving average-
% which is called an FIR filtering in DSP
%	y(n)=sum[h(m)*x(n-m), m=0,...,M-1], n=0,...,N-1
% we ENCODE as before, setting n=nr-1 and m=mr-1, getting
%	y(nr-1)=sum(h(mr-1)*x(nr-mr), mr=1,...,M), nr=1,...,N
% or
%	yr(nr)=sum[hr(mr)*xr(nr-mr+1), mr=1,...,M], nr=1,...,N
% this last form we can implement in matlab
%
	clear
	clf
% define lenth of all sequences
	N=32;
	nr=1:N;
	n=nr-1;
% define the moving average filter weights
	M=8;
	mr=1:M;
	m=mr-1;
	hr(mr)=exp(-m/M);
% define the inputsequence
	L=12;
	D=10;
	xr=[zeros(1,D),ones(1,L),zeros(1,N-L-D)];
	for nr=1:N
		yr(nr)=0.0;
		for mr=1:M
			if nr-mr+1>=1 & nr-mr+1<=N
				yr(nr)=yr(nr)+xr(nr-mr+1)*hr(mr);
			end
		end
	end
	plot(n,xr,'x',n,yr,'ro')
	axis([0 N-1 -10 10])
	xlabel('discrete time  ')
	title('a moving average')