% Modest LPF
fprintf(1,'Modest low pass filter specification\n');
res1 = compare_filters(10e3,12e3,64e3,40);
plotres(res1,101);
fprintf(1,'\n');

% Example from "Optimized design of windowed-sinc anti-aliasing 
% filters for phase-preserving decimation of hydrophone data"
% https://pubs.aip.org/asa/jasa/article/151/3/2077/2838345/Optimized-design-of-windowed-sinc-anti-aliasing
fprintf(1,'Example from Zhang et. al. reference\n');
res2 = compare_filters(3.5e3,7e3,256e3,74); % blackman:205 taps, kaiser:171 taps
plotres(res2,102);
fprintf(1,'\n');

% Very strict spec - could take several minutes, depending on your platform
%fprintf(1,'Very strict channelizer filter specification\n');
%res3 = compare_filters(25e3,30e3,6.4e6,120); % tbw=0.08% stopband=120dB (!)
%plotres(res3,103);
%fprintf(1,'\n');
