% ex2_2.m   Example 2.2  to show relation of 
% matlab and conventional indexing with
% sample averaging
%
N=32;				% sequence length
w=(2*pi/N)*2;			% frequency
% ENCODING	
nr=1:N;
n=nr-1;
xr=cos(w*n);
%
ave=sum(xr)/N;
disp('sequence average is  ')
ave
