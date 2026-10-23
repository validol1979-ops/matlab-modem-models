% ex3_5.m  to show how the dft may be used to process a noisy signal to 
% more clearly discover sinusoidal signal components
%
N=512;
nr=1:N;
n=nr-1;
w1=(2*pi/N)*20;
w2=(2*pi/N)*50;
x=cos(w1*n)+cos(w2*n);
var=5;
no=sqrt(var)*randn(size(x));
y=x+no;
subplot(2,1,1)
plot(y)
disp('hit any key')
pause
Y=fft(y,N);
Syy=Y.*conj(Y)/N;
subplot(2,1,2)
plot(Syy)
