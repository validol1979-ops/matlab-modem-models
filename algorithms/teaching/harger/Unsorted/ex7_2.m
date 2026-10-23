% ex7_2.m  to plot the aliased spectra over one period
%  for f(t) = exp(-a|t|), a>0, -Tc/2<t<Tc/2
%
a=input('enter exponential constant  ')
Tc=input('enter truncation time  ')
Ts=input('enter sampling period Ts  ')
M=input('# of aliases summed, M, an odd integer  ')
N=256;				% # of plot points
dw=2*pi/N;			% point spacing
w=-pi:dw:pi;			% plot points
F1=zeros(1,N+1);		% initialize spectrum values
for mr=1:M
	m=mr-(M+1)/2;
	tmp1=(2/(a*Ts))./(1+((w-m*2*pi)/(a*Ts)).^2);
	tmpc=cos((w-m*2*pi)*Tc/(2*Ts));
	tmps=sin((w-m*2*pi)*Tc/(2*Ts));
	tmpss=tmps.*((w-m*2*pi)/(2*Ts));
	tmp4=tmpc-tmpss;
	tmp5=1-tmpss.*exp(-a*Ts/2);
	tmp=tmp1.*tmp5;
	F1=F1+tmp;
	if m==0
		Fr=tmp;
	end
end
plot(w,F1,':',w,Fr,'r')
title('Rescaled FT (red) & DTFT of Truncated Sample Sequence (yellow)')
pk=max(abs(F1));
axis([-pi pi 0 pk])
