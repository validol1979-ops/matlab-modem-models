% ex7_1.m  to plot the aliased spectra over one period
%  for f(t) = exp(-a|t|), a>0, -inf<t<inf
%
a=input('enter exponential constant  ')
Ts=input('enter sampling period Ts  ')
M=input('# of aliases summed, M, an odd integer  ')
N=256;				% # of plot points
dw=2*pi/N;			% point spacing
w=-pi:dw:pi;			% plot points
F1=zeros(1,N+1);		% initialize spectrum values
for mr=1:M
	m=mr-(M+1)/2;
	tmp=(2/(a*Ts))./(1+((w-m*2*pi)/(a*Ts)).^2);
	F1=F1+tmp;
	if m==0
		Fr=tmp;
	end
end
plot(w,F1,':',w,Fr,'r')
title('Rescaled FT (red) & DTFT of Sample Sequence (yellow)')
pk=max(abs(F1));
axis([-pi pi 0 pk])
