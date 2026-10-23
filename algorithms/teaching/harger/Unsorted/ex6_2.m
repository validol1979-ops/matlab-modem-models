% ex6_2.m  exemplifying FIR design
%
% I. we specify the poles and zeros. we begin with a simple design of an FIR
%	filter with one complex conjugate pair of zeros
%	at a specified angle and magnitude and hence a second order pole at z=0:
% 	THEREFORE, SIMPLE BANDSTOP FILTERS CAN BE DESIGNED
%	the user inputs the value of the zeros
%   The column vector of zeros is q=a 
%   The column vector of poles is p=0
clear, clc, clf
disp('a complex conjugate pair of zeros is assumed;')
disp('enter the mag and arg of zero in upper half plane')
mag=input('enter magnitude of the UHP zero  ')
pha=input('enter angle (in [0,pi]) of the UHP zero  ')
% 
q=[mag*exp(i*pha); mag*exp(-i*pha)];
p=[0;0];
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
% it is also of interest to plot the impulse response,
% which, for an FIR filter, is b
figure(3)
plot(b,'x')
title('FIR Impulse Response')
axis([1 3 -max(b) max(b)])
%
% V.  QUESTIONS
%	- where is the UHP zero located for a lowstop filter?
%	- where is the UHP zero located for a highstop filter?
%	- where is the UHP zero located for a bandstop filter?
%	- when mag is replaced by 1/mag,
%		what is the difference in FR magnitude?
%		what is the difference in FR phase? 
