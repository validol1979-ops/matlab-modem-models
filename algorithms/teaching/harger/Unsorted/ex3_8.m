% ex3_8.m  to show how the behavior of the dft, of base N, 
% of a fixed, finite (M) length sequence, as N>M increases. 
%
M=4;
mr=(1:M);
m=mr-1;
N=16;
nr=1:N;
n=nr-1;
h=[ones(1,M),zeros(1,N-M)];
%
H=fft(h,N);
Hmag=H.*conj(H);
plot(n,Hmag,'o')
