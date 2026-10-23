% ENEE 322
% Project #5 - Studying FIR Filters
% Billy NG, Ronald Mak
% 11/4/96

clear
close all

disp (' ')
disp (' ')
disp ('The purpose of this project is to study the design of')
disp ('FIR filters, with nb > 2, arranged as "quadraplets" -- ')
disp ('(z, z*, 1/z, 1/Z*). ')
disp (' ')
disp (' ')
disp ('Press any key to continue...')
pause

%%%%%%%%%%%%%%%

%%%%%					plain quadraplets # 1   (high-pass)

qa1 = .5*exp(i*45*pi/180);
qa = [qa1; conj(qa1); 1/qa1; 1/conj(qa1)];
pa = zeros(length(qa),1);

%%%%%					plain quadraplets # 2	(low-pass)

qb1 = .5*exp(i*135*pi/180);
qb = [qb1; conj(qb1); 1/qb1; 1/conj(qb1)];
pb = zeros(length(qb),1);

%%%%%					quads. plus one extra zero

ex1 = exp(i*180*pi/180);
qc1 = .5*exp(i*225*pi/180);
qc = [ex1; qc1; conj(qc1); 1/qc1; 1/conj(qc1)];
pc = zeros(length(qc),1);

%%%%% 					quads. plus two extra zeros

ex1 = exp(i*60*pi/180);
qd1 = .5*exp(i*225*pi/180);
qd = [ex1; conj(ex1); qd1; conj(qd1); 1/qd1; 1/conj(qd1)];
pd = zeros(length(qd),1);

%%%%%					quads. plus three extra zeros

ex1 = exp(i*315*pi/180);
ex2 = exp(i*180*pi/180);
qe1 = .5*exp(i*225*pi/180);
qe = [ex1; conj(ex1); ex2; qe1; conj(qe1); 1/qe1; 1/conj(qe1)];
pe = zeros(length(qe),1);

%%%%%					quads. plus four extra zeros

ex1 = exp(i*315*pi/180);
ex2 = exp(i*35*pi/180);
qf1 = .5*exp(i*225*pi/180);
qf = [ex1; conj(ex1); ex2; conj(ex2); qf1; conj(qf1); 1/qf1; 1/conj(qf1)];
pf = zeros(length(qf),1);

%%%%%%%%%%%%%%%

clf reset

subplot (2,1,1)
axis('off')
text(0,1,'Project #5 -- FIR Filters')
text(0,0.8, 'This program consists of six sets of plots.  Each set of plots')
text(0,0.65,'will demonstrate the relationships between the placements ')
text(0,0.5 ,'of ploes and zeros on the z-plane and the properties ')
text(0,0.35,'of the resulting filters. ')
text(0,0.05, 'In addition, other characteristics can also be observed')
text(0,0.-0.1,'from the plots. ')
text(0,0.-0.25,' ')

disp (' ')
disp (' ')
disp ('Press any key to continue...') 
pause

%%%%%%%%%%%%%%%

close all

% to make a pole-zero plot
figure (1)
subplot (2,2,1);
zplane(qa,pa)
title('pole-zero plot')

% to find the transfer function form
b=poly(qa);
a=poly(pa);

% to plot the impulse response, which, for an FIR filter, is b
subplot (2,2,2);
plot(real(b),'x')
title('FIR Impulse Response')
axis([1 length(b) -max(b) max(b)])

subplot(2,2,3);
axis('off')
text(0,1,'The pole-zero plot shows a set of quadruplets.  Since the zeros')
text(0,0.8,'are on the positive half of the real-axis, the plot demonstrates ')
text(0,0.6,'a highpass filter.  The FIR IR shows symmetry about a point.')
text(0,0.2,'[ NOTE: quadruplets is the set (z, z*, 1/z, 1/z*) ]')
disp ('Press any key to continue...')
pause

% to plot the frequency response
figure (2)
freqz(b,a,512,'whole')
title('FIR Frequency Response')
axis([0 2 -50 30])
disp ('Press any key to continue...') 
pause

figure (3)
subplot (2,1,1)
axis('off')
text(0,1,'The upside-down U-shape in the magnitude response plot confirms')
text(0,0.8, 'that this is a highpass filter.  In the phase plot, a ')
text(0,0.65,'phase shift of 720 degrees can be observed for the ')
text(0,0.5 ,'two zeros placed outside the unit circle.  Also, a linear')
text(0,0.35,'phase can be observed. ')
text(0,0.2, 'In this case, each zero outside the unit circle created a ')
text(0,0.05,'phase shift of 360 degrees. ')
text(0,0.-0.1,' ')
disp ('Press any key to continue...') 
pause

%%%%%%%%%%%%%%%

close all

% to make a pole-zero plot
figure (1)
subplot (2,2,1);
zplane(qb,pb)
title('pole-zero plot')

% to find the transfer function form
b=poly(qb);
a=poly(pb);

% to plot the impulse response, which, for an FIR filter, is b
subplot (2,2,2);
plot(real(b),'x')
title('FIR Impulse Response')
axis([1 length(b) -max(b) max(b)])

subplot(2,2,3);
axis('off')
text(0,1,'Again, this pole-zero plot shows a set of quadruplets.  However,')
text(0,0.8,'since the zeros are placed on the negative half of the ')
text(0,0.6,'real-axis, this is a lowpass filter.  The FIR IR is symmetric. ')
text(0,0.4,' ')
disp ('Press any key to continue...')
pause

% to plot the frequency response
figure (2)
freqz(b,a,512,'whole')
title('FIR Frequency Response')
axis([0 2 -50 30])
disp ('Press any key to continue...') 
pause

figure (3)
subplot (2,1,1)
axis('off')
text(0,1,'The magnitude response shows a right-side up U-shaped curve.')
text(0,0.8, 'In this case, the curve symbolizes a lowpass filter.  From ')
text(0,0.65,'the phase plot, one can also see the 720 degree phase ')
text(0,0.5 ,'shift created by the two zeros placed outside the unit ')
text(0,0.35,'circle. ')
text(0,0.2, ' ')
text(0,0.05,'Again, a linear phase should be observed. ')
text(0,0.-0.1,' ')
disp ('Press any key to continue...') 
pause

%%%%%%%%%%%%%%%

close all

% to make a pole-zero plot
figure (1)
subplot (2,2,1);
zplane(qc,pc)
title('pole-zero plot')

% to find the transfer function form
b=poly(qc);
a=poly(pc);

% to plot the impulse response, which, for an FIR filter, is b
subplot (2,2,2);
plot(real(b),'x')
title('FIR Impulse Response')
axis([1 length(b) -max(b) max(b)])

subplot(2,2,3);
axis('off')
text(0,1,'In this pole-zero plot, there are 5 zeros: four from the ')
text(0,0.8,'quadruplets and one at -1.  There are 5 poles centered at ')
text(0,0.6,'the origin corresponding to the five zeros. ')
text(0,0.4,'The IR plot is symmetric.')
text(0,0.2,'[ Note: for FIR filters, poles should be at the origin. ]')
disp ('Press any key to continue...')
pause

% to plot the frequency response
figure (2)
freqz(b,a,512,'whole')
title('FIR Frequency Response')
axis([0 2 -50 30])
disp ('Press any key to continue...') 
pause

figure (3)
subplot (2,1,1)
axis('off')
text(0,1,'The magnitude response shows one sharp drop.  The location of ')
text(0,0.8, 'this drop matches the point of discontinuity in the phase ')
text(0,0.65,'plot.  Due to the presence of the quadruplets, the phase still ')
text(0,0.5 ,'maintains some properties of linearity, but now only as a ')
text(0,0.35,'piece-wise linear phase, for there is one "jump."')
text(0,0.2, ' ')
text(0,0.05,' ')
text(0,0.-0.1,' ')
disp ('Press any key to continue...') 
pause

%%%%%%%%%%%%%%%

close all

% to make a pole-zero plot
figure (1)
subplot (2,2,1);
zplane(qd,pd)
title('pole-zero plot')

% to find the transfer function form
b=poly(qd);
a=poly(pd);

% to plot the impulse response, which, for an FIR filter, is b
subplot (2,2,2);
plot(real(b),'x')
title('FIR Impulse Response')
axis([1 length(b) -max(b) max(b)])

subplot(2,2,3);
axis('off')
text(0,1,'Now, the pole-zero plot contains one set of quadruplets, and ')
text(0,0.8,'a pair of conjugates located on the unit circle. The six ploes')
text(0,0.6,'at the origin correspond to the six zeros.  Again, the IR plot ')
text(0,0.4,'shows symmetry. ')
disp ('Press any key to continue...')
pause

% to plot the frequency response
figure (2)
freqz(b,a,512,'whole')
title('FIR Frequency Response')
axis([0 2 -50 30])
disp ('Press any key to continue...') 
pause

figure (3)
subplot (2,1,1)
axis('off')
text(0,1,'The magnitude shows two drops.  These two drops correspond to ')
text(0,0.8, 'the two breaks in the phase plot.  This phase plot is also ')
text(0,0.65,'piece-wise linear, because there is a set of quadrublets, ')
text(0,0.5 ,'which induces linearity. ')
text(0,0.35,' ')
text(0,0.2, 'The fact that there are two drops is significant, because ')
text(0,0.05,'there are two zeros in addition to the set of quadruplets. ')
text(0,0.-0.1,' ')
disp ('Press any key to continue...') 
pause

%%%%%%%%%%%%%%%

close all

% to make a pole-zero plot
figure (1)
subplot (2,2,1);
zplane(qe,pe)
title('pole-zero plot')

% to find the transfer function form
b=poly(qe);
a=poly(pe);

% to plot the impulse response, which, for an FIR filter, is b
subplot (2,2,2);
plot(real(b),'x')
title('FIR Impulse Response')
axis([1 length(b) -max(b) max(b)])

subplot(2,2,3);
axis('off')
text(0,1,'This particular pole-zero plot has the quadruplets, a pair of ')
text(0,0.8,'conjugates, and a zero located on the unit circle.  The seven ')
text(0,0.6,'zeros are paired with the seven poles at the origin.  The ')
text(0,0.4,'IR plot is symmetric just like the others. ')
disp ('Press any key to continue...')
pause

% to plot the frequency response
figure (2)
freqz(b,a,512,'whole')
title('FIR Frequency Response')
axis([0 2 -50 30])
disp ('Press any key to continue...') 
pause

figure (3)
subplot (2,1,1)
axis('off')
text(0,1,'Here, the magnitude response has three drops.  Each drop can be ')
text(0,0.8, 'matched up with each break in the phase plot.  The phase plot ')
text(0,0.65,'is also piece-wise linear. ')
text(0,0.5 ,' ')
text(0,0.35,'The presense of three drops can be traced back to the three ')
text(0,0.2, 'additional zeros beside the quadruplets.')
text(0,0.05,' ')
text(0,0.-0.1,' ')
disp ('Press any key to continue...') 
pause

%%%%%%%%%%%%%%%

close all

% to make a pole-zero plot
figure (1)
subplot (2,2,1);
zplane(qf,pf)
title('pole-zero plot')

% to find the transfer function form
b=poly(qf);
a=poly(pf);

% to plot the impulse response, which, for an FIR filter, is b
subplot (2,2,2);
plot(real(b),'x')
title('FIR Impulse Response')
axis([1 length(b) -max(b) max(b)])

subplot(2,2,3);
axis('off')
text(0,1,'In this last set, the pole-zero plot has one set of duadruplets ')
text(0,0.8,'and two other pairs of conjugates placed on the unit circle. ')
text(0,0.6,'The IR plot remains symmetric. ')
text(0,0.4,' ')
disp ('Press any key to continue...')
pause

% to plot the frequency response
figure (2)
freqz(b,a,512,'whole')
title('FIR Frequency Response')
axis([0 2 -50 30])
disp ('Press any key to continue...') 
pause

figure (3)
subplot (2,1,1)
axis('off')
text(0,1,'There are four drops in the magnitude response plot.  There are ')
text(0,0.8, 'also four corresponding breaks in the phase plot, creating a ')
text(0,0.65,'piece-wise linear phase plot. ')
text(0,0.5 ,' ')
text(0,0.35,' ')
text(0,0.2, 'This concludes a total of six sets of plots. ')
text(0,0.05,' ')
text(0,0.-0.1,' ')
disp ('Press any key to continue...') 
pause

%%%%%%%%%%%%%%

close all

subplot (2,1,1)
axis('off')
text(0,1,'Observation: ')
text(0,0.8, ' ')
text(0,0.65,'From the previous six sets of plots, one should have observed ')
text(0,0.5 ,'the presence of symmetry in the impulse response plots. ')
text(0,0.35,'Of course, the property of symmetry relys on the location ')
text(0,0.2, 'of the zeros on the pole-zero plot. ')
text(0,0.05,' ')
text(0,0.-0.1,'The piece-wise linear phase is also very important.  When')
text(0,-.25,'the set of quadruplets is included as zeros, a piece-wise phase')
text(0,-.4,'is guaranteed.')
disp ('Press any key to continue...') 
pause

%%%%%%%%%%%%%%%
close all

subplot (2,1,1)
axis('off')
text(0,1,'From the first two sets of plots, one could easily see that a ')
text(0,0.8, 'phase shift of 360 degrees is caused by each zero placed')
text(0,0.65,'outside the unit circle. ')  
text(0,0.5 ,' ')
text(0,0.35,'Though the phase is shifted, dispersion is still avoided.')
text(0,0.2, 'Dispersion is caused by non-linear phase; however, our ')
text(0,0.05,'choice of filters only produce piece-wise linear phase, meaning ')
text(0,0.-0.1,'there is no dispersion.  And the absence of dispersion should')
text(0,0.-0.25,'elimimates many other undesirable effects. ')
text(0,0.-0.4,' ')
text(0,0.-0.55,' ')

disp ('Press any key to continue...') 
pause

close all

%%%%%%%%%%%%%%%
%
% COMMENTS
% very nice interface!!
% the comment on phase might be confusing:
% e.g., two zeros outside the unit circle give zeros
% total phase shift. Since there are corresponsingly
% two poles, their total phase shift of -4pi is not
% cancelled out- as it would be if the zeros were inside.
% grade: A+
