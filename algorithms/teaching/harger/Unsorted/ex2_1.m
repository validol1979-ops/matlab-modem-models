% ex2_1.m   Example 2.1  to show relation of 
% matlab and conventional indexing
%
N=32;				% sequence length
w=(2*pi/N)*2;			% frequency
% "ENCODING"
for nr=1:N			% matlab index
	n=nr-1;			% conventional index
	xr(nr)=cos(w*n);
end
% ENCODING- MORE EFFICIENTLY	
nr=1:N;
n=nr-1;
xr=cos(w*n);
%
% "DECODING" BY PLOTTING
plot(n,xr,'o')
axis([0 N-1 -1.1 1.1])
xlabel('discrete time')
