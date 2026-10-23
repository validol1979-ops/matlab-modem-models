% ex6_3.m  exemplifying FIR design
%
% I. the user inputs the value of the zeros as a
%   The column vector of zeros is q=a 
%   The column vector of poles is p=0 is automatically created
clear, clc, clf
q=input('enter the FIR zeros as a column vector [q(1);q(2);...]  ');
p=zeros(length(q),1);
% 
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
axis([0 2 -50 30])
disp('press any key to proceed')
pause
% it is also of interest to plot the impulse response,
% which, for an FIR filter, is b
figure(3)
plot(b,'x')
title('FIR Impulse Response')
axis([1 length(b) -max(b) max(b)])
%
% V.  QUESTIONS
%	- where are the zeros located for a lowpass filter?
%	- where are the zeros located for a highpass filter?
%	- where are the zeros located for a bandpass filter?
%	- when a cc pair of zeros with magnitude mag is replaced by 
%		their reciprocals,
%		what is the difference in FR magnitude?
%		what is the difference in FR phase? 
