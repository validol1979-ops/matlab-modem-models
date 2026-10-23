% ex5_2.m  to solve the lde y(n)-ay(n-1)=x(n), n=0,1,..., y(-1)=0
%
clear, clf, clc
a=-1.05;
N=32;
nr=1:N;
n=nr-1;
xr=[1,zeros(1,N-1)];   	% to find IR
% handle separately the lde "start-up"
yr(1)=xr(1); 		% the lde at n=0 with y(-1)=0
% now handle the general case lde
for nnr=2:N
	yr(nnr)=a*yr(nnr-1)+xr(nnr);
end
plot(n,yr,'x')
hold on
ymax=max(yr);
axis([0 N-1 -ymax ymax])
title('Response of a Simple (Recursive) lde')
text(N/2,0.8,['a= ',num2str(a)])
% we can also plot the known solution
for nnr=1:N
	nn=nnr-1;
	exact(nnr)=a^nn;
end
plot(n,exact,'ro')
hold off
