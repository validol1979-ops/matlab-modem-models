% ex6_5.m  exemplifying analog filter design design with poles
%
% I. we specify the poles, from which we can get the vector a
%    the zeros will be at s=infinity: it is easiest to enter this as b=1
%
clear, clc, clf
%
disp('ANALOG FILTER DESIGN BY POLE PLACEMENT: ')
disp('the zeros are all at infinity & so')
disp('the  # of zeros = # of poles ')
disp('the user inputs (only) the pole locations')
disp('the pole-zero plot will be made, the FR plotted and')
disp('the vectors a,b defining the TF and LDE are displayed')
p=input('enter the poles as a column vector [p(1); p(2);...] ')
a=poly(p)
b=1
% 
% II.  we make a pole-zero plot
figure(1)
na=length(p);
for n=1:na
	plot(real(p(n)),imag(p(n)),'x')
	hold on
end
xmin=min(real(p))-1;
xmax=1;
ymin=min(imag(p))-1;
ymax=max(imag(p))+1;
axis([xmin 1 ymin ymax])
axx=linspace(xmin,xmax,128);
axy=linspace(ymin,ymax,128);
plot(axx,zeros(1,length(axx)),':') 	% plots real axis
plot(zeros(1,length(axy)),axy,':')	% plots imag axis
title('pole-zero plot')
text(0.1,ymax/10,'real axis')
text(0.1,ymax-1/2,'imag axis')
hold off
%
% IV.  we can now plot the frequency response
figure(2)
% freqs(b,a)
% the default use of freqs plots a log-log plot that is not helpful now!!
% so we use freqs with the usual plot command
M=max(abs(p));
dw=16*M/256;
w=-8*M:dw:8*M-dw;		% vector of frequencies for plot
fr=freqs(b,a,w);	 % fr is vector of samples of FR
frmag=abs(fr);
frpha=angle(fr);		
frphaun=unwrap(frpha);		
subplot(2,1,1)
plot(w,frmag)
title('FR magnitude')
subplot(2,1,2)
plot(w,frphaun)
title('FR phase')
%
% we now plot the impulse response
disp('the number of FR samples used to compute the IR is   ')
N=length(w)
% shuffle the FR from FT to DFT order
for n=1:N
	if n<= N/2
		frdft(n)=fr(n+N/2);
	else
		frdft(n)=fr(n-N/2);
	end
end
ir=ifft(frdft);
figure(3)
t=(0:1:N-1);
plot(t,ir)	
%
% SUGGESTED EXPERIMENTS
% I Consider two poles with imag parts +i and -i
%	consider a sequence of values for the real parts:
%	e.g., -16,-8,-4,-2,-1,-1/2,-1/4,-1/8

