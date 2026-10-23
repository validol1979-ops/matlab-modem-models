% ex6_1.m  exemplifying FIR design
%
% I. we specify the poles and zeros. we begin with a simple design of an FIR
%	filter with one zero at z=a and hence a single pole at z=0:
% 	THEREFORE, SIMPLE LOWPASS AND HIGHPASS FILTERS CAN BE DESIGNED
%	the user inputs the value of a
%   The column vector of zeros is q=a 
%   The column vector of poles is p=0
clear, clc, clf
a=input('enter zero location, a real number a  ')
% a=-1;
q=a;
p=0;
% II.  we make a pole-zero plot
figure(1)
zplane(q,p)
title('pole-zero plot')
disp('press any key to proceed')
pause
% III. we find the transfer function form
b=poly(q);
a=poly(p);
disp('the numerator polynomial (in 1/z) coeficients b are  ')
b
disp('the denominator polynomial (in 1/z) coeficients a are  ')
a
disp('press any key to proceed')
pause
% IV.  we can now plot the frequency response
figure(2)
freqz(b,a,512,'whole')
title('FIR Frequency Response')
disp('press any key to proceed')
pause
% the impulse response is, for an fir, simply b: plot it
figure(3)
plot(b,'x')
axis([1 2 -max(b) max(b)])
title('FIR Impulse Response')
%
% V.  QUESTIONS
%	- where is a located for a lowpass filter?
%	- where is a located for a highpass filter?
%	- when a is replaced by 1/a,
%		what is the difference in FR magnitude?
%		what is the differenc in FR phase? 
%	- is a bandpass filter possible? with real IR?