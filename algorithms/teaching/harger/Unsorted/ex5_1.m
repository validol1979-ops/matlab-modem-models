% ex5_1.m  to plot the "synch" function and an application
%
clear, clf
N=256;
n=0:N;
w=n*(2*pi/N);
M=32;
s=synch(w,M);
subplot(2,1,1)
plot(w,s)
axis([0 2*pi -0.25 1.5])
title('The synch Function')
text(pi,1,['M=',num2str(M)])
% text(3,1,'M=')
hold on
%
w1=2*pi/8;
w2=2*pi/4;
Z1=synch(w+w1,M)+synch(w-w1,M);
Z1=Z1+(3/2)*(synch(w+w2,M)+synch(w-w2,M));
subplot(2,1,2)
plot(w,Z1)
axis([0 2*pi -1 2.5])
title('Effect of Truncation')
text(2,2,25,['M=',num2str(M),', w1=',num2str(w1),', w2=',num2str(w2)])
hold off