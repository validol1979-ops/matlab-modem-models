% Nick Kohout
% Steve Neuendorffer

% Here we consider a signal s containing several frequencies.
% We begin by truncating the sequence at different lengths,
% periodically extending the function to a large length(512) and
% taking the DFT (or FFT) as an approximation to the DTFT.  (Notice 
% that since we have chosen Discrete frequencies of the form 2Pi*k/N,
% the DFT of the sequence trucated to length N will simply be Discrete
% Delta functions at the input frequencies.   This is done for 
% illustrative purposes only.)

% Given a signal x[n] and a truncation window h[n], we are finding the
% DTFT of x[n]h[n] which is proportional to X(ejw)*H(ejw) (periodic 
% convolution).   This shows that it makes sense to look at H(ejw) as a
% "spreading" or "distortion" of the exact frequencies of X(ejw) when
% the DFT is used to approximate X(ejw).   (i.e. we wish to choose a 
% window h[n] whose DTFT H(ejw) is either narrow (high resolution)
% or low ripple (low sidelobe level)).   Unfortunately, there is a 
% trade off between the two.

% Later on we take the DFT (approximating the DTFT) of both windows.
% In order to get a quantitive analysis of the resolution and sidelobe
% level in each, we also plot the Power as a function of frequency for
% each window.

% ANALYSIS:
% it is seen in the first sequence of graphs that at short truncation 
% lengths, both the rectangular window(R) and the Hamming window(H)
% are 'poor'.   At medium lengths (N=32, say)  We can see how the
% Hamming window, with lower resolution does not distinguish between
% frequencies that are close together, but has practically no
% sidelobes.   The Rectangular window, however resolves the large
% peaks very nicely, but does not contain much useful information about
% lower energy frequencies.

% Looking at the plots of the DFT of both windows, we can see that the
% Hamming window has approximately half the resolution of the 
% Rectangular window (twice the main lobe width).   However, the 
% largest sidelobe of the Hamming window is down >40 dB, whereas the 
% largest sidelobe of the Rectangular window is down a mere 10-15 dB. 

N=512;
n=1:N;

s=3*cos(2*pi/N*10*n)+3*cos(2*pi/N*20*n)+cos(2*pi/N*100*n)+cos(2*pi/N*30*n)+2*cos(2*pi/N*60*n);
fs=abs(fft(s));

k=[8 16 32 64 128 256 384 512];
for M=k

r=[ones(1,M) zeros(1,N-M)];
xr=r.*s;
fr=fft(xr);

m=1:M;
ham=.54-.46*cos(2*pi*m/(M-1));
ham=[ham zeros(1,N-M)];
xh=ham.*s;
fh=fft(xh);

clf;


subplot(2,1,1)
hold on;
plot(n,fs*M/N,'r')
plot(n,abs(fr));
title(sprintf('square window M=%i',M))
axis([0 N 0 2*M])

subplot(2,1,2)
hold on;
plot(n,fs*M/N,'r')
plot(n,abs(fh)/0.54);
title(sprintf('hamming window M=%i',M))
axis([0 N 0 2*M])

disp('Hit a key for the next plot')
pause
end % for loop

clf

M=48;

r=[ones(1,M) zeros(1,N-M)];
xr=r.*s;
fr=fft(xr);

m=1:M;
ham=.54-.46*cos(2*pi*m/(M-1));
ham=[ham zeros(1,N-M)];
xh=ham.*s;
fh=fft(xh);

fftr=fft(r);
fftham=fft(ham);


subplot(2,1,1);
hold on;
plot(n,abs(fftr));
title('DFT of Rectangular window N=48');


subplot(2,1,2);
plot(n,abs(fftham));
title('DFT of Hamming window N=48');

disp('hit a key');
pause;
clf;


subplot(2,1,1);
hold on;
plot(n,20*log10((abs(fftr)+.001)./max(abs(fftr))));
title('Power(dB) of DFT of Rectangular window N=48');
axis([0 N -75 0]);

subplot(2,1,2);
plot(n,20*log10((abs(fftham)+.001)./max(abs(fftham))));
title('Power(dB) of DFT of Hamming window N=48');
axis([0 N -75 0]);

% END!