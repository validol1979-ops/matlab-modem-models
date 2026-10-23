% ex2_6.m  to make a movie illustrating the convolution operation
%
clear, clf, clc
% define the filter IR & input seq. & initialize output seq.
N=32;				% total sequence length
M=6;				% total filter length
L=16; 				% extent parameter of input signal
n=(0:N-1);			% conventional discrete time index
for nr=1:N			% matlab discrete time index
	n1=nr-1;			% conventional index
	if nr<=M
		hr(nr)=0.9*exp(-n1/M);
	else
		hr(nr)=0;
	end
	if  n1>=L/2 & n1<=L  
		xr(nr)=1;
	else
		xr(nr)=0;
	end
end
% initialize the output vector to be -1 for "plotting purposes":
% the output will be computed sequentially for each time and stored.
yr=zeros(1,N)-1;			
%
Mv=moviein(32);			% choose N=32 frames for the movie  
for nr=1:N
	clf			% clear figure
	plot(n,xr,'+')
	hold on
	axis([0,N-1,-0.5,1.1])
	text(9,1.3,'x(m)','color','y')
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
	plot(n,hrevr,'ro')
	text(nr+0.5,0.75,'h(n-m)','color','r')
%
	yr(nr)=dot(hrevr,xr);
	plot(n,yr,'cx')
	text(nr+0.5,yr(nr)+0.25,'y(n)','color','c')
	axis([0,N-1,-0.1,5.1])
	xlabel('n (discrete time) ')
	ylabel('y (filter output)')
%	title('Filter Output')
	drawnow
	Mv(:,nr)=getframe;		% get a frame for movie
	hold off
end
hold off
% movie(Mv)
% cannot make a movie using subplot !!