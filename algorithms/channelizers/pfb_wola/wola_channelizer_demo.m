function [y,cofs,res] = wola_channelizer_demo(M,D,fs,cbw,tbw,win,attendb)
% Usage: [y,cofs,res] = wola_channelizer_demo(M,D,fs,cbw,tbw,win,attendb)
%
% y = wola_channelizer_demo([indata],[M],[D],[fs=1],[cbw=fs/M],[tbw=0.1],[win='hamming'],[attendb=40])
%
% Demonstration of Weighted Overlap-Add Filter Bank Channelizer
%
% Inputs:
%   M...........integer number of channels (M>1) [default=8]
%   D...........integer decimation (D<=M) [default=8]
%   fs..........input sampling rate (Hz) [default=1]
%   cbw.........channel bandwidth (Hz) [default=fs/M]
%   tbw.........transition bandwidth (Hz) [default=0.1]
%   win.........filter window function (char) [default='hamming']
%   attendb.....filter atten (dB) [default=40]
% Outputs
%   y...........N-by-M array of channelized samples, where
%               N is the number of samples at fsout=fs/D
%               M is the number of channels
%   cofs........1d array of wola filter coefficients
%   res.........cell array of filter design info (see wsinc package)
%

    tic;
    y = [];
    cofs = [];
    res = {};
    if nargin < 2
        M = 8;
        D = 8;
    end
    if nargin < 7
        attendb = 60;
    end
    if nargin < 6
        win = 'hamming';
    end
    if nargin < 5
        tbw = 0.1;
    end
    if nargin < 3
        fs = 1;
    end
    if nargin < 4
        cbw = fs / M;
    end

    % Echo config
    fprintf(1,'WOLA Channelizer Demo\n');
    fprintf(1,'         Channels (M) = %d\n', M);
    fprintf(1,'       Decimation (D) = %d\n', D);
    fprintf(1,'     Sample Rate (fs) = %d Hz\n', fs);
    fprintf(1,'     Channel BW (cbw) = %f Hz\n', cbw);
    fprintf(1,'  Transition BW (tbw) = %.2f\n', tbw);
    fprintf(1,'         Window (win) = %s\n', win);
    fprintf(1,'  Stopband Atten (dB) = %.1f\n\n', attendb);

    % Lowpass prototype filter
    fc = cbw / 2;
    fstop = (1 + tbw) * fc; % transition bw
    res = compare_filters(fc,fstop,fs,attendb,{win,'break'}); % wsinc package
    Nm = M * ceil(res{1}.ntaps / M);
    cofs = zeros(Nm,1);
    cofs(1:res{1}.ntaps) = res{1}.cofs(:);
    Gd = find(cofs == max(cofs)) - 1; % filter group delay

    % Generate test signal
    [indata,fsweep,tsweep] = chirpgen(fs,max(100*Nm,1e4));
    tout = shiftdim(tsweep(1:D:end));
    fout = shiftdim(fsweep(1:D:end));

    % Channelize
    y = wola_chanex(indata,M,D,cofs);

    % Visualize

    figure(101);
    plot(fout - (fsweep(Gd)-fsweep(1)),  20*log10(abs(y)),'LineWidth',1.5);
    xlabel('Sweep Frequency (Hz)');
    ylabel('Magnitude Response (dB)');
    title('Overlay of Channelized Outputs vs Sweep Frequency');
    %figure(102);
    %plot(tout-tsweep(Gd),  20*log10(abs(y)),'LineWidth',1.5);
    %xlabel('Sweep Time (s)');
    %ylabel('Magnitude Response (dB)');
    %title('Overlay of Channelized Outputs vs Sweep Time');

    toc;
end % function

function [sig,fsweep,tsweep] = chirpgen(fs,N)
    t = (0:1:N-1)/fs;
    f0 = -fs/2;
    t1 = max(t);
    f1 = fs/2 * numel(t)/(numel(t)+1);;
    a = pi * (f1 - f0) / t1;
    b = 2 * pi * f0;
    sig = shiftdim(exp(j*(a * t.^2 + b * t)));
    fsweep = shiftdim(diff(unwrap(angle(sig)))/(t(2)-t(1))/2/pi);
    fsweep = [f0;fsweep];
    tsweep = t(:);
end % function
