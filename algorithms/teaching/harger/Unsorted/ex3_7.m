% ex3_7.m  to compare the direct & DFT methods of computing
% the periodic convolution: spec., the # of flops

clear, clc, clf, flops(0)
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
for nr=1:N
	for mr=1:N
% this is the block for the aperiodic convolution
%		if (nr-mr+1>=1) & (nr-mr+1)<=N
%			hrevr(mr)=hr(nr-mr+1);
%		else
%			hrevr(mr)=0;
%		end
% this is the block for the periodic convolution
		hrevr(mr)=hr(pod(nr-mr,N)+1);
	end
	yr(nr)=dot(hrevr,xr);
end
disp('the direct method: ')
disp('the # of flops used is  ')
flops
%
% now we compute the convolution using the fft
flops(0)
X=fft(xr,N);
H=fft(hr,N);
Y=X.*H;
y=ifft(Y);
disp('the fft method:  ')
disp('the # of flops used is  ')
flops
plot(n,yr,'+')
hold on
plot(n,y,'o')
hold off
