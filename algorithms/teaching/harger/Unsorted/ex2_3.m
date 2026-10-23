% ex2_3.m  Example 2.3 to compute the "simple moving average" of a sequence, defined as
%	y(n) = (1/M)*sum[x(n-m), m=0,...,M-1], n=0,...,N-1
%
% we encode the dsp statement into matlabese
%   by (i) setting n=nr-1 and (ii) m=mr-1  	
% the moving average now reads
% 	yr(nr) = (1/M)*sum[xr(nr-mr+1), mr=1,...,M], nr=1,...,N
% ***** NOTICE THE '+1' WHICH APPEARS IN THE ARGUMENT OF xr( ) !! ****************
% we can now implement this form in matlab
% we define x for more clarity
% this is encoded, then, into xr(nr)=1, nr in [1,16] and zero otherwise
%	
	clf
	N=32;			% total length of sequences
	L=12;			% width of simple pulse x:
	xr=[zeros(1,8),ones(1,L),zeros(1,N-L-8)];
	M=8;			% length of moving average
% perform moving average
	for nr=1:N
		yr(nr)=0.0;
		for mr=1:M	% accumulate average
			if nr-mr+1>=1 & nr-mr+1<=N
				yr(nr)=yr(nr)+xr(nr-mr+1)/M;
			end
		end
	end
% we can now DECODE the matlab representations using the decoded index n
	n=(0:N-1);
	plot(n,xr,'o',n,yr,'r*')
	axis([0 N-1 -0.1 1.1])
	xlabel('discrete time  ')
	title('a simple moving average')
