% ex2_7.m  to make a series of plots explaining the convolution operation
% specifically the FIR/MA is chosen to "differentiate" a sequence
%
clear, clf, clc
% define the filter IR & input seq. & initialize output seq.
N=32;				% total sequence length
M=2;				% total filter length
sigma=3;			% extent parameter of input signal
n=(0:N-1);			% conventional discrete time index
nr=1:N;			% matlab discrete time index
n1=nr-1;			% conventional index
xr(nr)=1.0*exp(-(n1-N/2).^2/(2*sigma^2));
hr=[1,-1,zeros(1,N-M)];
%	
% initialize the output vector to be -5 for "plotting purposes":
% the output will be computed sequentially for each time and stored.
yr=zeros(1,N)-5;			
% 
for nr=1:N
	clf			% clear figure
	subplot(2,1,1)
	plot(n,xr,'+')
	hold on
	axis([0,N-1,-1.2,1.2])
	xlabel('m (convolution sum index) ')
	ylabel('x(m) and h(n-m)')
	title('Sequences For Computing One Output Value')
	for mr=1:N
		if (nr-mr+1>=1) & (nr-mr+1)<=N
			hrevr(mr)=hr(nr-mr+1);
		else
			hrevr(mr)=0;
		end
	end
	subplot(2,1,1)
	plot(n,hrevr,'ro')
%
	yr(nr)=dot(hrevr,xr);
	subplot(2,1,2)
	plot(n,yr,'cx')
	axis([0,N-1,-0.5,0.5])
	xlabel('n (discrete time) ')
	ylabel('y (filter output)')
%	title('Filter Output')
	drawnow
	disp('press any key to continue to next step')
	pause
end
hold off