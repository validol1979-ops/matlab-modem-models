% p2_21d.m  to make a series of plots explaining the convolution operation
%
clear, clf, clc
% define the filter IR & input seq. & initialize output seq.
N=32;				% total sequence length
n=(0:N-1);			% conventional index
xr=[ones(1,5),zeros(1,N-5)];
hr=[zeros(1,2),ones(1,6),zeros(1,3),ones(1,6),zeros(1,15)];
% initialize the output vector to be -1 for "plotting purposes":
% the output will be computed sequentially for each time and stored.
yr=zeros(1,N)-1;			
% 
for nr=1:N
	clf			% clear figure
	subplot(2,1,1)
	plot(n,xr,'+')
	hold on
	axis([0,N-1,-0.1,1.1])
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
	axis([0,N-1,-0.1,5.1])
	xlabel('n (discrete time) ')
	ylabel('y (filter output)')
%	title('Filter Output')
	drawnow
	disp('press any key to continue to next step')
	pause
end
hold off