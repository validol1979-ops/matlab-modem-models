% ex5_3.m  to make a surface plot of a pole
% 
M=31;
N=31;
nr=1:N;
n=nr-1-(N-1)/2;
mr=1:M;
m=mr-1-(M-1)/2;
dx=2/M;
x=dx*m;
dy=2/N;
y=dy*n;
pole=-0.5;
for mmr=1:M
for nnr=1:N
	z(mmr,nnr)=x(mmr)+i*y(nnr);
end
end
% it is interest to plot a zero at zero
% H=z;
% it is of interest to plot a real pole
% H=1./(z-pole);
% the tranfer function of ex5_2.m is interesting
H=z./(z-pole);
for mmr=1:M
for nnr=1:N
	if sqrt(x(mmr)^2+y(nnr)^2)<=1
		P(mmr,nnr)=abs(H(mmr,nnr));
	else
		P(mmr,nnr)=0;
	end
end
end
surf(abs(P))
% axis([-1 1 -1 1 0 500])  	% "no good!"