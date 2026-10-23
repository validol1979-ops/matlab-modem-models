% ex6_4.m  to show a pair of sub-band filters designed
% for a proposed "personal, wireless, on-demand video" system
%
clear, clc, clf
% the design arrived at the following sub-band filters
hlo=[3 6 2 -1];
hhi=[1,2,-6,3];
% plot the IRs
figure(1)
subplot(2,1,1)
plot(hlo,'o')
title('lo pass IR')
subplot(2,1,2)
plot(hhi,'x')
title('hi pass IR')
% 
% we make pole-zero plots
blo=hlo;
qlo=roots(blo);
plo=zeros(length(qlo),1);
figure(2)
zplane(qlo,plo)
title('pole-zero plot: lo pass FIR')
bhi=hhi;
qhi=roots(bhi);
phi=zeros(length(qhi),1);
figure(3)
zplane(qhi,phi)
title('pole-zero plot: hi pass FIR')
%
% compute the FRs
N=128;
n=1:N;
hloex=[hlo,zeros(1,N-4)];
Hlo=fft(hloex);
hhiex=[hhi,zeros(1,N-4)];
Hhi=fft(hhiex);
% plot the magnitude & phase of each filter
figure(4)
subplot(2,1,1)
plot(abs(Hlo))
title('FIR mag: lo pass FIR')
subplot(2,1,2)
phlo=unwrap(angle(Hlo));
plot(phlo)
title('FIR phase: lo pass FIR')
figure(5)
subplot(2,1,1)
plot(abs(Hhi))
title('FIR mag: hi pass FIR')
phhi=unwrap(angle(Hhi));
subplot(2,1,2)
plot(phhi)
title('FIR phase: hi pass FIR')

